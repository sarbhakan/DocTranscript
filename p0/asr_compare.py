"""Replay the same locked WAVs against local ASR engines; keep raw results local."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
from time import perf_counter
import wave
import os

from p0.bench.scoring import edit_distance
from p0.lexicon_ab import annotated_matches, critical_words, quantiles, read_reply, result_text, words
from p0.corpus.prepare_head_to_head import PX_SHA256
from p0.review.px_paired import evaluate_row, spans, PX
from zipfile import ZipFile

WHISPER_LOCK = {
    "ggml-small-q5_1.bin": "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
    "ggml-large-v3-turbo-q5_0.bin": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
    "ggml-large-v3-q5_0.bin": "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1",
    "ggml-silero-v6.2.0.bin": "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987",
}

# Locked by reading the independent source, before running any engine on Corti.
# Equivalent notation is accepted; spans carry the entity or both ends of a range.
CORTI_SPANS = {
    2: {"laterality": ["lésion de l’amygdale droite"], "quantity": ["6 cures"]},
    3: {},
    5: {
        "dose": ["AMIPRIL 5 mg par jour", "atorvastatine 20 mg"],
        "duration": ["depuis environ 3 semaines", "entre 5 et 15 minutes", "holter ECG sur 24 heures"],
        "negation": ["sans syncope ni lipothymie", "ne rapporte pas de douleurs thoraciques",
                     "pas d’antécédents d’infarctus du myocarde ni d’accident vasculaire cérébral",
                     "sans souffle ni galop", "pas d’œdème des membres inférieurs",
                     "sans troubles de la conduction ni signes d’ischémie aiguë"],
        "vitals": ["135 par 85 millimètres de mercure|135/85 mmHg", "78 battements par minute|78 bpm"],
    },
    6: {
        "dose": ["paracétamol 1 g 3 fois par jour", "ibuprofène 400 mg si besoin"],
        "duration": ["évoluant depuis 6 semaines", "réévaluation à 6 semaines"],
        "laterality": ["lombosciatalgie droite", "cuisse droite", "Lasègue est positif à 40 degrés à droite"],
        "negation": ["pas de syndrome de la queue-de-cheval", "pas de troubles sphinctériens ni de déficit moteur franc",
                     "sans compression significative", "sans chirurgie rachidienne",
                     "pas de prise prolongée d’AINS", "VS non accélérée"],
        "scale": ["7 sur 10|7/10"],
    },
}
CORTI_REVISION = "2a840558d221b4f306c52419d58f93270ea599bb"
CORTI_PCM_SHA256 = {
    2: "a5f9a182d4f9e12370ff5131145c398497659c24b4db62f649dc98a9f6e42244",
    3: "b027ed2b4869907d0e373affd516eb6f87f5be76299bb7b15dacfb0694721fec",
    5: "09ed3774d1e25edc839a4c78e605895aa9c1e11470d8a9d9fbc9edc5df091d0d",
    6: "6becc0f3ef1f6a0bf969d51c4d633b8fd49d7eaceb65b7cdcc665928c081d0e1",
}


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def create_manifest(p0, stress, corti_index=None, corti_wavs=None, output=None):
    rows = {}
    def add(row, path, cohort):
        path = path.resolve(strict=True)
        sha = digest(path)
        if row.get("wav_sha256", sha) != sha:
            raise ValueError(f"empreinte différente : {row['id']}")
        with wave.open(str(path)) as handle:
            if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (16000, 1, 2):
                raise ValueError(f"format WAV non conforme : {row['id']}")
            sec = handle.getnframes() / 16000
        if row["id"] in rows:
            prior = rows[row["id"]]
            if prior["sha256"] != sha:
                raise ValueError(f"audio différent pour le même identifiant : {row['id']}")
            for key in ("terms", "critical", "lures", "speech_ends_ms"):
                if key in row:
                    prior[key] = row[key]
            prior["cohorts"].append(cohort)
        else:
            rows[row["id"]] = {**row, "path": os.path.relpath(path, output.parent.resolve()), "sha256": sha,
                               "seconds": sec, "cohorts": [cohort]}
    with (p0 / "cases.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            add(row, p0 / "wav" / (row["id"] + ".wav"), "p0")
    for row in json.loads((stress / "cases.json").read_text(encoding="utf-8")):
        add(row, stress / "wav" / (row["id"] + ".wav"), "stress")
    if bool(corti_index) != bool(corti_wavs):
        raise ValueError("le lot Corti requiert l’index officiel et les WAV locales")
    if corti_index:
        source = json.loads(corti_index.read_text(encoding="utf-8"))
        for index, critical in CORTI_SPANS.items():
            row = next(r["row"] for r in source["rows"] if r["row_idx"] == index)
            if not any(CORTI_REVISION in audio["src"] for audio in row["audio"]):
                raise ValueError("révision Corti différente")
            audio = corti_wavs / f"corti-{index}.wav"
            with wave.open(str(audio)) as handle:
                if hashlib.sha256(handle.readframes(handle.getnframes())).hexdigest() != CORTI_PCM_SHA256[index]:
                    raise ValueError(f"audio indépendant non conforme : {index}")
            add(dict(id=f"corti-{index}", kind="speech", reference=row["transcription_formatted"],
                     terms=row["medical_terms_formatted"], critical=critical), audio, "corti")
    # Keep the independent controls first so their results arrive before the full stress lot.
    rows = sorted(rows.values(), key=lambda row: ("corti" not in row["cohorts"], row["seconds"] > 28, row["id"]))
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(rows)} WAV scellées : {sum(r['seconds'] for r in rows):.1f} s.")


def whisper_runner(args, stack):
    import numpy as np
    from pywhispercpp.model import Model

    if importlib.metadata.version("pywhispercpp") != "1.5.1":
        raise ValueError("pywhispercpp 1.5.1 attendu")
    paths = (args.model,) if args.mode == "pause" else (args.model, args.vad)
    for path in paths:
        if not path or digest(path) != WHISPER_LOCK.get(path.name):
            raise ValueError(f"fichier Whisper non verrouillé : {path}")
    options = {"vad": False}
    if args.mode == "pause":
        from p0.asr_native import load_silero
        split = load_silero(args.binary, args.pause_vad, stack)
    else:
        split = None
        options = {"vad": True, "vad_model_path": str(args.vad.resolve())}
    model = Model(str(args.model.resolve()), context_params={"use_gpu": False},
                  n_threads=args.threads, language="fr", translate=False, no_context=True,
                  print_progress=False, print_realtime=False, print_timestamps=False,
                  redirect_whispercpp_logs_to=None, **options)
    def run(path):
        with wave.open(str(path)) as stream:
            x = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768
        before = perf_counter()
        rows = []
        for fragment in split(x) if split else (x,):
            started = perf_counter()
            segments = model.transcribe(fragment)
            rows.append({"text": " ".join(t.text.strip() for t in segments if t.text.strip()),
                         "decode_ms": (perf_counter() - started) * 1000})
        wall = (perf_counter() - before) * 1000
        return {"text": " ".join(r["text"] for r in rows if r["text"]), "elapsed_ms": wall,
                **({"segments": rows} if split else {})}
    return run


def app_runner(args, stack):
    worker = subprocess.Popen([str(args.binary.resolve()), "--lexicon-bench"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE)
    def close():
        worker.stdin.close()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()
        worker.stdout.close()
        if worker.returncode:
            raise RuntimeError(f"NoteVive a quitté avec le code {worker.returncode}")
    stack.callback(close)

    def run(path):
        result = read_reply(worker, args.profile, path.read_bytes())
        return {**result, "text": result_text(result)}
    return run


def replay(args):
    from contextlib import ExitStack

    if args.pause_ms is not None and args.engine != "whisper-native":
        raise ValueError("--pause-ms requiert le pont natif Whisper")
    if args.profile and args.engine != "macos":
        raise ValueError("les profils lexicaux ne sont disponibles que pour la .app macOS")

    if (args.mode == "extended" and args.engine != "ultimed"
            or args.mode == "pause" and args.engine != "whisper"):
        raise ValueError("ce mode ne s’applique pas au moteur sélectionné")
    if args.engine == "macos" and not args.binary:
        raise ValueError("la .app macOS requiert --binary")
    if args.engine in ("macos", "ultimed", "whisper-native") and args.threads != 4:
        raise ValueError("le moteur natif est compilé avec 4 fils fixes")
    started = perf_counter()
    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    with ExitStack() as stack:
        if args.engine == "whisper":
            run = whisper_runner(args, stack)
        elif args.engine == "macos":
            run = app_runner(args, stack)
        else:
            from p0.asr_native import engine_runner
            run = engine_runner(args, stack)
        warm = next((r for r in rows if r["id"] == "dev-17"), None)
        if warm is None or "corti" in warm["cohorts"]:
            raise ValueError("le WAV de développement dev-17 est requis pour le préchauffage")
        warm_path = args.manifest.parent / warm["path"]
        if digest(warm_path) != warm["sha256"]:
            raise ValueError("empreinte différente pour le préchauffage")
        run(warm_path)
        startup_ms = (perf_counter() - started) * 1000
        with args.output.open("x", encoding="utf-8", newline="\n") as out:
            meta = {"manifest": digest(args.manifest), "engine": args.engine,
                    "model": args.model.name if args.model else None,
                    "runtime": platform.platform(), "threads": args.threads,
                    "mode": args.mode, "profile": args.profile, "cohort": args.cohort,
                    "pause_ms_requested": args.pause_ms,
                    "startup_plus_warmup_ms": startup_ms,
                    "binary_sha256": digest(args.binary) if args.binary else None,
                    "whisper_weights_sha256": WHISPER_LOCK.get(args.model.name) if args.model else None}
            print(json.dumps({"meta": meta}, ensure_ascii=False), file=out, flush=True)
            for row in rows:
                if args.cohort and args.cohort not in row["cohorts"]:
                    continue
                path = args.manifest.parent / row["path"]
                if digest(path) != row["sha256"]:
                    raise ValueError(f"le fichier a changé : {row['id']}")
                result = run(path)
                print(json.dumps({"id": row["id"], "status": "ok", **result}, ensure_ascii=False), file=out, flush=True)


def meaning_words(text):
    # Unambiguous spelling/abbreviation variants. Keep amounts, units and polarity.
    return ["g" if token in ("gramme", "grammes") else token for token in critical_words(text)]


def px_posology(reference, bio, text):
    """Screen paired spans with simple, explicitly annotated quantities/units."""
    grouped = {"administered": [], "duration": [], "fraction": []}
    entities = spans(reference, bio)
    for i, (kind, amount, _, stop) in enumerate(entities):
        if kind == "dos_val" and any(token in ("½", "¼", "¾") for token in meaning_words(amount + " de")):
            grouped["fraction"].append(amount + (" de" if amount.endswith(("quart", "quarts")) else ""))
        if i + 1 >= len(entities):
            continue
        unit_kind, unit, start, _ = entities[i + 1]
        if stop != start:
            continue
        # Some annotations attach an article (e.g. "gélules le").
        unit = re.sub(r"\s+(?:le|la|les)$", "", unit)
        if kind == "dos_val" and unit_kind == "dos_uf":
            grouped["administered"].append(amount + " " + unit)
        elif kind == "dur_val" and unit_kind == "dur_ut":
            grouped["duration"].append(amount + " " + unit)
    return {key: annotated_matches(text, tests, meaning_words) for key, tests in grouped.items()}


def score(args):
    rows = {row["id"]: row for row in json.loads(args.manifest.read_text(encoding="utf-8"))}
    manifest_sha = digest(args.manifest)
    px = {}
    if args.px_archive:
        if digest(args.px_archive) != PX_SHA256:
            raise ValueError("empreinte différente de PxCorpus v4")
        with ZipFile(args.px_archive) as archive:
            raw = [archive.read(PX + name).decode("utf-8-sig").splitlines() for name in ("seq.in", "seq.out")]
        px = {key: [column[int(key[3:])] for column in raw] for key in rows if re.fullmatch(r"px-\d+", key)}
    summary = {}
    for path in args.runs:
        with path.open(encoding="utf-8") as handle:
            meta = json.loads(next(handle))["meta"]
            if meta["manifest"] != manifest_sha:
                raise ValueError(f"manifeste différent : {path}")
            results = [json.loads(line) for line in handle if line.strip()]
        case_ids = {r["id"] for r in results}
        if len(results) != len(case_ids) or not case_ids <= rows.keys():
            raise ValueError(f"doublons ou identifiants inconnus : {path}")
        expected = {key for key, row in rows.items()
                    if not meta.get("cohort") or meta["cohort"] in row["cohorts"]}
        if case_ids != expected and not args.partial:
            raise ValueError(f"lot incomplet : {path} ({len(case_ids)} / {len(expected)})")
        cohorts = {}
        for cohort in ("p0", "stress", "corti"):
            report = {"records": [], "critical": {}, "terms": [0, 0], "word_changes": [0, 0],
                      "control_nonempty": [0, 0], "drug": [0, 0], "strength": [0, 0], "drug_strength": [0, 0],
                      "strength_unqualified": [0, 0], "drug_strength_association_strict": [0, 0], "px_posology": {}}
            timings, ratios, segment_timings, pause_estimates, queued_pause_estimates = [], [], [], [], []
            pauses_expected = pauses_missing = 0
            for res in results:
                ref = rows[res["id"]]
                if cohort not in ref["cohorts"]:
                    continue
                if res.get("status") != "ok" or not isinstance(res.get("text"), str):
                    raise ValueError(f"sortie invalide : {res['id']}")
                text = res["text"]
                timings.append(res["elapsed_ms"])
                if ref["reference"]:
                    ratios.append(res["elapsed_ms"] / (1000 * ref["seconds"]))
                segment_timings.extend(p["decode_ms"] for source in ("pause", "stop", "segments")
                                       for p in res.get(source, []))
                if "pause" in res:
                    # This excludes backlog, transport and UI. Endpoints are synthetic and known.
                    # Use a generous 2 s window so slower VAD thresholds remain observable.
                    events = []
                    available = 0.0
                    for p in res["pause"]:
                        if p["audio_ms"] is None:
                            continue
                        available = max(available, p["audio_ms"]) + p["decode_ms"]
                        # Even an empty segment needs to complete on the serial decoder.
                        if p["text"].strip():
                            events.append((p, available))
                    used = set()
                    for end in ref.get("speech_ends_ms", [])[:-1]:
                        pauses_expected += 1
                        match = next(((i, p, ready) for i, (p, ready) in enumerate(events) if i not in used
                                      and end <= p["audio_ms"] <= end + 2000), None)
                        if match is None:
                            pauses_missing += 1
                        else:
                            i, p, ready = match
                            used.add(i)
                            pause_estimates.append(p["audio_ms"] - end + p["decode_ms"])
                            queued_pause_estimates.append(ready - end)
                checks = {key: annotated_matches(text, vals, meaning_words)
                          for key, vals in ref.get("critical", {}).items()}
                terms = annotated_matches(text, ref.get("terms", []), words)
                scored = {"id": ref["id"], "missing_terms": [label for label, good in terms if not good],
                          "critical_errors": {category: [label for label, good in vals if not good]
                                              for category, vals in checks.items() if not all(ok for _, ok in vals)}}
                for category, vals in checks.items():
                    totals = report["critical"].setdefault(category, [0, 0])
                    totals[0] += sum(ok for _, ok in vals)
                    totals[1] += len(vals)
                report["terms"][0] += sum(ok for _, ok in terms)
                report["terms"][1] += len(terms)
                refwords = meaning_words(ref["reference"])
                hypwords = meaning_words(text)
                if refwords:
                    report["word_changes"][0] += edit_distance(refwords, hypwords)
                    report["word_changes"][1] += len(refwords)
                else:
                    report["control_nonempty"][0] += bool(text.strip())
                    report["control_nonempty"][1] += 1
                if cohort == "p0" and ref["id"] in px:
                    check = evaluate_row(*px[ref["id"]], text)
                    for label, metric in (("drug", "drug_exact"), ("strength", "strength_exact"),
                                          ("drug_strength", "ordered_pair_nearby"),
                                          ("strength_unqualified", "strength_unqualified_exact"),
                                          ("drug_strength_association_strict", "strength_association_strict")):
                        if metric in check:
                            report[label][0] += check[metric]
                            report[label][1] += 1
                    posology = px_posology(*px[ref["id"]], text)
                    for name, vals in posology.items():
                        totals = report["px_posology"].setdefault(name, [0, 0])
                        totals[0] += sum(ok for _, ok in vals)
                        totals[1] += len(vals)
                    scored["px"] = {**check, "posology_errors": {
                        category: [label for label, good in vals if not good]
                        for category, vals in posology.items() if not all(ok for _, ok in vals)}}
                report["records"].append(scored)
            report["elapsed_ms"] = quantiles(timings)
            report["speech_rtf"] = quantiles(ratios)
            report["decode_ms_per_segment"] = quantiles(segment_timings)
            report["pause_estimate_synth_ms"] = quantiles(pause_estimates)
            report["pause_estimate_synth_with_serial_queue_ms"] = quantiles(queued_pause_estimates)
            report["pause_estimate_missing"] = [pauses_missing, pauses_expected]
            report["covered"] = [len(timings), sum(cohort in row["cohorts"] for row in rows.values())]
            cohorts[cohort] = report
        if path.name in summary:
            raise ValueError(f"nom de rapport ambigu : {path.name}")
        if args.aggregate:
            for report in cohorts.values():
                del report["records"]
        summary[path.name] = {"meta": meta, "scoring_revision": 2, "cohorts": cohorts}
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for flag in ("p0", "stress", "output", "corti-index", "corti-wavs"):
        prep.add_argument("--" + flag, type=Path, required=flag in ("p0", "stress", "output"))
    run = sub.add_parser("run")
    run.add_argument("--engine", choices=("whisper", "whisper-native", "macos", "zipformer", "ultimed"), required=True)
    run.add_argument("--mode", choices=("default", "extended", "pause"), default="default")
    run.add_argument("--threads", type=int, choices=(2, 4), default=4)
    run.add_argument("--profile", default="")
    run.add_argument("--pause-ms", type=int, choices=(576, 1200))
    run.add_argument("--cohort", choices=("p0", "stress", "corti"))
    for flag in ("manifest", "output", "model", "vad", "pause-vad", "binary"):
        run.add_argument("--" + flag, type=Path, required=flag in ("manifest", "output"))
    sc = sub.add_parser("score")
    for flag in ("manifest", "output", "px-archive"):
        sc.add_argument("--" + flag, type=Path, required=flag in ("manifest", "output"))
    sc.add_argument("--aggregate", action="store_true", help="omit labels and case records in shareable output")
    sc.add_argument("--partial", action="store_true", help="autoriser un lot en cours ou réduit")
    sc.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        create_manifest(args.p0, args.stress, args.corti_index, args.corti_wavs, args.output)
    elif args.command == "run":
        replay(args)
    else:
        score(args)


if __name__ == "__main__":
    main()
