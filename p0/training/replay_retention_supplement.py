"""Score frozen LoRA research artifacts on separate speech checks. No tuning."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

from p0.asr_compare import CORTI_SPANS, annotated_matches, meaning_words
from p0.bench.scoring import edit_distance, words
from p0.training import train_lora as lab
from p0.training.prepare_px import safe_artifact, sha256
from p0.training.report_stability import checks, paired, read
from p0.training.score_validation import score_case
from p0.windows.ct2_corti import LOCK, read_cases, read_lock


def synth_cases(manifest):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data["schema"] != 1 or not 1 <= len(data["cases"]) <= 32:
        raise ValueError("Taille ou version du panel synthétique inattendue")
    ids = set()
    cases = []
    for case in data["cases"]:
        name, rid = case["wav"], case["id"]
        if Path(name).name != name or rid in ids:
            raise ValueError("Chemin ou ID invalide dans le panel")
        ids.add(rid)
        path = safe_artifact(manifest.parent, name)
        pcm = lab.read_pcm(path.read_bytes())
        if (not 0 < len(pcm) // 2 <= lab.RATE * 30
                or hashlib.sha256(pcm).hexdigest() != case["pcm_sha256"]):
            raise ValueError("PCM synthétique différent du gel")
        ref = case["reference"]
        if not score_case(case, ref)["screen_passed"]:
            raise ValueError("Un cas synthétique ne reconnaît pas sa propre référence")
        cases.append((case, ref, [pcm]))
    return cases, {"cortimeddictate_benchmark": False, "source": "synthetic_fr_not_human",
                   "source_sha256": sha256(manifest), "voices": data["voices"]}


def corti_cases(directory):
    specs = list(read_cases(directory, read_lock()))
    cases = [(s, ref, [chunk for _, _, chunk, _ in parts]) for s, ref, parts in specs]
    return cases, {"cortimeddictate_benchmark": True, "source": "Corti/Med-Dictate FR",
                   "source_sha256": sha256(LOCK), "dataset_revision": read_lock()["revision"],
                   "notice": "Corti ApS; Nix et al., arXiv:2605.16545; benchmark only, without feedback into any model.",
                   "license": "https://huggingface.co/datasets/corti/med-dictate/blob/main/LICENCE.md"}


def infer(rt, model, processor, clip, device, dtype):
    torch = rt["torch"]
    waveform = rt["np"].frombuffer(clip, dtype="<i2").astype("float32") / 32768.0
    encoded = processor.feature_extractor(waveform, sampling_rate=lab.RATE, return_tensors="pt",
                                          padding="max_length", max_length=30 * lab.RATE,
                                          truncation=False, return_attention_mask=True)
    features = encoded.input_features.to(device=device, dtype=getattr(torch, dtype))
    mask = encoded.attention_mask.to(device=device)
    if tuple(features.shape) != (1, 128, 3000):
        raise ValueError("Prétraitement inattendu")
    if device == "mps":
        torch.mps.synchronize()
    started = time.monotonic()
    with torch.inference_mode(), torch.autocast(device_type=device, dtype=torch.float16, enabled=dtype == "float16"):
        prediction = model.generate(input_features=features, attention_mask=mask, return_dict_in_generate=True, **lab.GENERATION)
    if device == "mps":
        torch.mps.synchronize()
    elapsed = time.monotonic() - started
    ids, eos = lab.generated_sequence(prediction)
    return processor.tokenizer.decode(ids, skip_special_tokens=True).strip(), elapsed, eos


def replay(args):
    runs = lab.private_directory(args.runs)
    eval_freeze = read(runs, "evaluation.frozen.json")
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    if (freeze["code_sha256"] != sha256(Path(__file__))
            or freeze["px_freeze_sha256"] != sha256(safe_artifact(runs, "evaluation.frozen.json"))
            or freeze["generation"] != lab.GENERATION or freeze["supplement_generation_started"] is not False):
        raise ValueError("Gel du supplément incompatible")
    use = str(freeze["type"])
    if (use, bool(args.corti), bool(args.synthetic)) == ("corti", True, False):
        corpus, source_meta = corti_cases(args.corti)
    elif (use, bool(args.corti), bool(args.synthetic)) == ("synthetic", False, True):
        corpus, source_meta = synth_cases(args.synthetic)
    else:
        raise ValueError("Un seul lot de voix à la fois")
    if source_meta["source_sha256"] != freeze["supplement_source_sha256"]:
        raise ValueError("Source voix différente du gel")
    _, source, _, output, _, provenance, _, hashes = lab.prepare(SimpleNamespace(
        model=args.model, corpus=args.corpus, px_archive=args.px_archive,
        output=args.output, min_free_gib=2.0, adapter=None))
    device, dtype = "mps", "float16"
    rt = lab.load_runtime(device)
    torch = rt["torch"]
    torch.set_num_threads(4)
    output.mkdir(mode=0o700)
    variants, screens = {}, {}
    for key in ("base", "ce24", "kl24", "drug24"):
        adapter = None
        if key != "base":
            report = read(runs, f"{key}/report.json")
            if sha256(safe_artifact(runs, f"{key}/report.json")) != eval_freeze["training_reports_sha256"][key]:
                raise ValueError("Rapport d’adaptateur différent du gel")
            if report["status"] != "completed":
                continue
            adapter = runs / key / "checkpoints/update-000024"
            metadata = lab.verify_adapter(adapter, provenance, hashes)
            if metadata["adapter_parameters_sha256"] != report["adapter_final_sha256"]:
                raise ValueError("L’adaptateur ne correspond pas au résultat de l’entraînement")
        torch.manual_seed(20261114)
        model, base, processor = lab.model_setup(rt, source, device, dtype, False, adapter)
        model.eval()
        time_sum, endings, count, word_count, word_errors = 0.0, 0, 0, 0, 0
        screen, totals, possible = [], Counter(), Counter()
        detailed = []
        for expected, reference, clips in corpus:
            outputs = [infer(rt, model, processor, pcm, device, dtype) for pcm in clips]
            count += len(outputs)
            time_sum += sum(elapsed for _, elapsed, _ in outputs)
            endings += sum(ended for _, _, ended in outputs)
            text = " ".join(text for text, _, _ in outputs).strip()
            if use == "corti":
                conditions = {category: [ok for _, ok in annotated_matches(text, spans, meaning_words)]
                              for category, spans in CORTI_SPANS[expected["row"]].items()}
                tokenizer = meaning_words
                rid = f"corti-{expected['row']}"
            else:
                conditions = checks(score_case(expected, text))
                tokenizer, rid = words, expected["id"]
            word_count += len(tokenizer(reference))
            word_errors += edit_distance(tokenizer(reference), tokenizer(text))
            for category, passed in conditions.items():
                totals[category] += sum(passed)
                possible[category] += len(passed)
            screen.append(conditions)
            detailed.append({"id": rid, "text": text, "checks": conditions})
        lab.atomic_json(output / f"{key}.local.json", detailed)
        variants[key] = {"slices": count, "eos": endings, "word_errors": word_errors, "word_count": word_count,
                         "length_weighted_wer": word_errors / word_count, "generation_seconds": time_sum,
                         "checks": {category: [totals[category], total] for category, total in possible.items()}}
        screens[key] = screen
        del model, base, processor
        gc.collect()
        torch.mps.empty_cache()
        print(json.dumps({"variant": key, "cases": len(corpus), "slices": count, "eos": endings}), flush=True)
    report = {"schema": 1, "evaluated_after_model_freeze": True, "type": use, **source_meta,
              "private_references_or_predictions_in_report": False, "cases": len(corpus),
              "audio_seconds": sum(len(clip) / (2 * lab.RATE) for _, _, clips in corpus for clip in clips),
              "versions": rt["versions"], "device": device, "dtype": dtype, "generation": lab.GENERATION,
              "report_is_development_signal": use != "corti", "metrics": variants,
              "changes_vs_base": {name: paired(screens["base"], test) for name, test in screens.items() if name != "base"},
              "changes_vs_ce24": {name: paired(screens["ce24"], screens[name]) for name in ("kl24", "drug24")
                                  if "ce24" in screens and name in screens},
              "no_product_or_export_change": True}
    lab.atomic_json(output / "aggregate.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("runs", "freeze", "model", "corpus", "px-archive", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--corti", type=Path)
    input_group.add_argument("--synthetic", type=Path)
    try:
        replay(parser.parse_args())
    except (ValueError, OSError, TypeError, KeyError, RuntimeError) as error:
        parser.exit(1, f"Supplément refusé : {error}\n")


if __name__ == "__main__":
    main()
