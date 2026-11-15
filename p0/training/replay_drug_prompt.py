"""Paired pre-registered Whisper vocabulary prompt; no adapted weights or post-edits."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
import time
from types import SimpleNamespace

from p0.training import score_validation as scorer, train_lora as lab
from p0.training.prepare_px import safe_artifact, sha256
from p0.training.report_stability import measured, paired, read


PLAN_LIMIT = 64
OUTPUT_LIMIT = 448 - len(lab.PREFIX) - PLAN_LIMIT


def prompt_ids(processor, terms):
    tokenizer = processor.tokenizer
    if (not isinstance(terms, list) or not 1 <= len(terms) <= 16
            or any(not isinstance(term, str) or not 1 <= len(term) <= 60 or term.strip() != term
                   or not all(char.isalpha() or char in " -'’" for char in term)
                   or not any(char.isalpha() for char in term) for term in terms)
            or len({term.casefold() for term in terms}) != len(terms)):
        raise ValueError("Liste médicament invalide")
    # Only this deterministic tail trim is allowed, before any candidate is heard.
    start = tokenizer.convert_tokens_to_ids("<|startofprev|>")
    for length in range(len(terms), 0, -1):
        ids = processor.get_prompt_ids(", ".join(terms[:length]) + ".", return_tensors="pt")
        if ids.ndim != 1 or ids.tolist()[:1] != [start]:
            raise ValueError("Le point d’entrée officiel produit un contexte différent")
        if ids.numel() <= PLAN_LIMIT:
            return terms[:length], ids
    raise ValueError("Aucun nom entier dans le budget du contexte")


def generated_only(generated, context):
    sequences = getattr(generated, "sequences", None)
    if sequences is None or len(sequences) != 1:
        raise ValueError("Une seule séquence Whisper brute est attendue")
    ids = sequences[0].tolist()
    prefix = [*context, *lab.PREFIX]
    if ids[:len(prefix)] != prefix or any(type(value) is not int or not 0 <= value < 51866 for value in ids):
        raise ValueError("Le contexte d’entrée ne correspond pas à la séquence renvoyée")
    output = ids[len(prefix):]
    # Remove only the input context. A prompt word produced again by the model
    # remains in text and counts as a potential false insertion.
    return output, lab.EOS in output


def run(args):
    root = lab.private_directory(args.runs)
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    protocol = read(root, "protocol.frozen.json")["protocol"]
    if (freeze.get("speech_generated_for_this_arm") is not False or freeze["max_prompt_ids"] != PLAN_LIMIT
            or freeze["max_output_ids_both_arms"] != OUTPUT_LIMIT or freeze["source_sha256"] != sha256(args.source)
            or freeze["code_sha256"] != sha256(Path(__file__))
            or freeze["px_freeze_sha256"] != sha256(safe_artifact(root, "evaluation.frozen.json"))
            or protocol["generation"]["grid_scorer_sha256"] != sha256(Path(scorer.__file__))):
        raise ValueError("Le contexte, les sources ou le comparateur ont changé depuis le gel")
    data = json.loads(args.source.read_text(encoding="utf-8"))
    corpus, source, _, output, _, _, partitions, _ = lab.prepare(SimpleNamespace(
        model=args.model, corpus=args.corpus, px_archive=args.px_archive, output=args.output,
        min_free_gib=2.0, adapter=None))
    rt = lab.load_runtime("mps")
    torch = rt["torch"]
    torch.manual_seed(20261114)
    torch.set_num_threads(4)
    model, _, processor = lab.model_setup(rt, source, "mps", "float16", False)
    terms, prompt = prompt_ids(processor, data["terms"])
    context = prompt.tolist()
    if (terms != data["terms"] or ", ".join(terms) + "." != data["prompt"]
            or lab.json_digest(context) != freeze["prompt_ids_sha256"]
            or lab.json_digest(terms) != freeze["chosen_terms_sha256"]):
        raise ValueError("Les mêmes noms et le même tokenizer doivent suivre le gel")
    prompt = prompt.to("mps")
    config = {**lab.GENERATION, "max_new_tokens": OUTPUT_LIMIT}

    def generate(features, mask, prompted):
        torch.mps.synchronize()
        t = time.monotonic()
        with torch.inference_mode(), torch.autocast(device_type="mps", dtype=torch.float16):
            generated = model.generate(input_features=features, attention_mask=mask,
                                       prompt_ids=prompt if prompted else None, return_dict_in_generate=True, **config)
        torch.mps.synchronize()
        elapsed = time.monotonic() - t
        values, eos = generated_only(generated, context if prompted else [])
        return {"text": processor.tokenizer.decode(values, skip_special_tokens=True).strip(),
                "inference_seconds": elapsed, "eos_present": eos}

    output.mkdir(mode=0o700)
    controls, raw_controls = [], []
    for duration in (1, 3):
        samples = rt["np"].zeros(lab.RATE * duration, dtype="float32")
        features = processor.feature_extractor(samples, sampling_rate=lab.RATE, return_tensors="pt", padding="max_length",
                                               max_length=30 * lab.RATE, truncation=False, return_attention_mask=True)
        base = features.input_features.to(device="mps", dtype=torch.float16)
        mask = features.attention_mask.to(device="mps")
        observed = {name: generate(base, mask, enabled) for name, enabled in (("base", False), ("prompt", True))}
        controls.append({"duration_seconds": duration, "method": {
            name: {"text_empty": not record["text"], "eos": record["eos_present"],
                   "named_prompt_terms": len(scorer.drug_mentions(record["text"], terms))}
            for name, record in observed.items()}})
        raw_controls.append(observed)
    lab.atomic_json(output / "silences.local.json", raw_controls)

    result = {}
    for group in protocol["generation"]["windows_in_order"]:
        count, name = group["count"], group["id"]
        path = safe_artifact(args.grids, f"critical-v2-r2-{count}.json")
        if sha256(path) != group["grid_sha256"]:
            raise ValueError("La grille n’est pas celle de la comparaison appariée")
        grid = json.loads(path.read_text(encoding="utf-8"))
        if grid["scoring_code_sha256"] != scorer.scoring_code_hashes():
            raise ValueError("Le code du scoreur a changé")
        cases = grid["cases"]
        selected = lab.validation_window(partitions["validation"], count, group["offset"])
        if (len(cases) != count or any((row["id"], row["speaker_id"], row["text"]) !=
                                     (case["id"], case["speaker_id"], case["reference"])
                                     for row, case in zip(selected, cases, strict=True))):
            raise ValueError("Le contexte ne peut être testé que sur la sélection figée")
        rows = []
        false_mentions, introduced_false, cases_with_new_false, named_support = Counter(), 0, 0, 0
        for index, (row, case) in enumerate(zip(selected, cases, strict=True), 1):
            features, mask = lab.audio_features(rt, processor, corpus, row, "mps", "float16")
            record = {"id": case["id"], "base": generate(features, mask, False), "prompt": generate(features, mask, True)}
            rows.append(record)
            allowed = Counter(scorer.drug_mentions(case["reference"], terms))
            named_support += sum(allowed.values())
            unexpected = {}
            for method in ("base", "prompt"):
                unexpected[method] = Counter(scorer.drug_mentions(record[method]["text"], terms)) - allowed
                false_mentions[method] += sum(unexpected[method].values())
            additions = unexpected["prompt"] - unexpected["base"]
            introduced_false += sum(additions.values())
            cases_with_new_false += int(bool(additions))
            if index % 8 == 0 or index == count:
                print(json.dumps({"window": name, "clips_done": index, "clips_total": count}), flush=True)
        baseline, reference_texts, baseline_seen = measured(rows, cases, "base")
        with_prompt, _, prompted_seen = measured(rows, cases, "prompt")
        external = safe_artifact(root, f"eval-ce24-{name}/predictions.local.jsonl")
        paired_original = [json.loads(line) for line in external.read_text(encoding="utf-8").splitlines()]
        if [item["id"] for item in paired_original] != [item["id"] for item in rows]:
            raise ValueError("Bases de comparaison décalées")
        raw_path = output / f"{name}.local.json"
        lab.atomic_json(raw_path, rows)
        result[name] = {"clips": count, "base": baseline, "prompt": with_prompt, "critical": paired(baseline_seen, prompted_seen),
                        "number_of_prompt_name_occurrences_in_references": named_support,
                        "false_prompt_name_occurrences": dict(false_mentions),
                        "introduced_false_prompt_name_occurrences": introduced_false,
                        "clips_with_introduced_false_prompt_names": cases_with_new_false,
                        "base_differences_vs_ce_protocol_444_max": sum(text != item["base"]["text"] for text, item in
                                                                      zip(reference_texts, paired_original, strict=True)),
                        "local_results_sha256": sha256(raw_path)}
    report = {"schema": 1, "technique": "official WhisperProcessor prompt_ids on original base", "generation": config,
              "name_count": len(terms), "context_token_count": len(context), "source_list_sha256": sha256(args.source),
              "digital_silent_audio_direct_to_whisper": controls, "metrics": result, "model_weights_changed": False,
              "refs_used_for_prompt": False, "product_change": False, "no_reserve_or_corti_used_to_select_prompt": True}
    lab.atomic_json(output / "aggregate.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("runs", "freeze", "model", "corpus", "px-archive", "output", "source", "grids"):
        parser.add_argument("--" + option, type=Path, required=True)
    try:
        run(parser.parse_args())
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        parser.exit(1, f"Biais contextuel refusé : {error}\n")


if __name__ == "__main__":
    main()
