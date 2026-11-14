"""Aggregate a complete paired decoder run without publishing its transcripts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from app.whisper_patch import DECODER_PATCH
from p0.asr_compare import digest, score
from p0.decoder_ab import selected_rows


def read_run(path, manifest_hash, expected_ids):
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    meta, rows = lines[0]["meta"], lines[1:]
    if (not expected_ids or meta.get("manifest") != manifest_hash or meta.get("repeat_control_only")
            or len(rows) != len(expected_ids) or {r["id"] for r in rows} != expected_ids
            or any(r.get("status") != "ok" or not isinstance(r.get("text"), str) for r in rows)):
        raise ValueError("Comparatif incomplet, modifié ou non destiné à la précision.")
    return meta, {r["id"]: r for r in rows}


def paired_changes(before, after):
    result = {"critical": {}, "terms": {"gained": 0, "lost": 0}, "px": {}}
    for cohort in ("p0", "stress"):
        a = {r["id"]: r for r in before["cohorts"][cohort]["records"]}
        b = {r["id"]: r for r in after["cohorts"][cohort]["records"]}
        if a.keys() != b.keys():
            raise ValueError("Cas non appariés.")
        for key, old in a.items():
            new = b[key]
            if cohort == "stress":
                for category in old["critical_errors"].keys() | new["critical_errors"].keys():
                    lost_before = Counter(old["critical_errors"].get(category, []))
                    lost_after = Counter(new["critical_errors"].get(category, []))
                    counts = result["critical"].setdefault(category, {"gained": 0, "lost": 0})
                    counts["gained"] += sum((lost_before - lost_after).values())
                    counts["lost"] += sum((lost_after - lost_before).values())
                old_terms, new_terms = Counter(old["missing_terms"]), Counter(new["missing_terms"])
                result["terms"]["gained"] += sum((old_terms - new_terms).values())
                result["terms"]["lost"] += sum((new_terms - old_terms).values())
            if cohort == "p0" and "px" in old:
                for metric in ("drug_exact", "strength_exact", "strength_unqualified_exact",
                               "ordered_pair_nearby", "strength_association_strict"):
                    if metric not in old["px"]:
                        continue
                    counts = result["px"].setdefault(metric, {"gained": 0, "lost": 0})
                    counts["gained"] += bool(new["px"][metric]) and not bool(old["px"][metric])
                    counts["lost"] += bool(old["px"][metric]) and not bool(new["px"][metric])
                for category in old["px"]["posology_errors"].keys() | new["px"]["posology_errors"].keys():
                    lost_before = Counter(old["px"]["posology_errors"].get(category, []))
                    lost_after = Counter(new["px"]["posology_errors"].get(category, []))
                    counts = result["px"].setdefault("posology_" + category, {"gained": 0, "lost": 0})
                    counts["gained"] += sum((lost_before - lost_after).values())
                    counts["lost"] += sum((lost_after - lost_before).values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "px-archive", "runs", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    expected = {r["id"] for r in selected_rows(args.manifest, "development")}
    paths = [args.runs / (name + ".ndjson") for name in ("baseline", "rng", "beam5")]
    runs = [read_run(p, digest(args.manifest), expected) for p in paths]
    for field in ("build_manifest_sha256", "whisper_weights_sha256", "vad_sha256", "threads", "pause_ms_requested"):
        if len({m[field] for m, _ in runs}) != 1:
            raise ValueError("Constructions ou paramètres non appariés.")
    if any(meta.get("profile") != path.stem for path, (meta, _) in zip(paths, runs)):
        raise ValueError("Profil mal identifié.")
    with tempfile.TemporaryDirectory(prefix="nv-decoder-report-") as folder:
        detailed = Path(folder) / "details.json"
        score(SimpleNamespace(manifest=args.manifest, px_archive=args.px_archive,
                              runs=paths, output=detailed, aggregate=False, partial=True))
        scored = json.loads(detailed.read_text(encoding="utf-8"))
    baseline = scored["baseline.ndjson"]
    comparisons = {}
    for name, (_, records) in zip(("rng", "beam5"), runs[1:]):
        comparisons[name] = paired_changes(baseline, scored[name + ".ndjson"])
        comparisons[name]["changed_transcripts"] = sum(
            row["text"] != runs[0][1][key]["text"] for key, row in records.items())
    for run in scored.values():
        # Corti was deliberately excluded. Do not publish empty pseudo-results.
        del run["cohorts"]["corti"]
        for cohort in run["cohorts"].values():
            del cohort["records"]
    result = {"schema": 1, "date": "2026-11-14", "development_only": True,
              "complete_selected_records_per_arm": len(expected), "decoder_patch": DECODER_PATCH,
              "raw_run_sha256": {p.name: digest(p) for p in paths},
              "profiles": {"baseline": "greedy best_of=5; upstream temperature fallback",
                           "rng": "baseline plus upstream per-call RNG reset",
                           "beam5": "RNG reset plus native BEAM_SEARCH defaults: beam_size=5, fallback one decoder"},
              "paired_vs_baseline": comparisons, "results": scored,
              "limitations": ["Development data already seen; no independent medical confirmation.",
                              "Automatic span and association screening is not clinical validation.",
                              "One paired run per clip; Mac timings exploratory, not Windows microphone latency.",
                              "Native beam defaults change both search and fallback; not an isolated beam-size ablation."]}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"Rapport agrégé : {len(expected)} audios par profil, sans transcription.")


if __name__ == "__main__":
    main()
