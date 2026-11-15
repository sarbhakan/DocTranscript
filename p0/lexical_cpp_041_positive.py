"""Positive synthetic companion to the frozen native no-regression A/B."""

from argparse import ArgumentParser
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from time import perf_counter

from p0 import lexical_cpp_041 as bench
from p0.training.prepare_px import canonical_wav


VOICE = "Jacques"
SPEED_WPM = 175
WALL_BUDGET_S = 240
# Fixed in frozen context order. Every phrase is an invented text transcription
# exercise, not a dosage recommendation. Preserve all phrases after synthesis.
SCENARIOS = (
    ("5", "cinq", "un demi", "pas de nausée", "pas", False),
    ("8", "huit", "un quart", "sans douleur à gauche", "sans", True),
    ("13", "treize", "trois quarts", "aucun œdème à droite", "aucun", True),
    ("21", "vingt et un", "un demi", "pas de fièvre", "pas", False),
    ("32", "trente-deux", "un quart", "sans rougeur à gauche", "sans", True),
    ("39", "trente-neuf", "trois quarts", "pas de gêne à droite", "pas", True),
    ("41", "quarante et un", "un demi", "aucune fatigue", "aucune", False),
    ("46", "quarante-six", "un quart", "sans toux", "sans", False),
    ("52", "cinquante-deux", "trois quarts", "pas de douleur à droite", "pas", True),
    ("65", "soixante-cinq", "un demi", "aucune rougeur à gauche", "aucune", True),
    ("77", "soixante-dix-sept", "un quart", "sans difficulté", "sans", False),
)


def deck(terms):
    cases = []
    for i, (name, (digits, spoken, fraction, negation, marker, side)) in enumerate(zip(terms, SCENARIOS, strict=True), 1):
        strength = digits + " milligrammes"
        portion = fraction + (" de comprimé" if "quart" in fraction else " comprimé")
        template = "Note fictive : {} {}, {}, {}."
        reference = template.format(name, strength, portion, negation)
        speech = template.format(name, spoken + " milligrammes", portion, negation)
        case = {"id": f"context-positive-{i:02}", "wav": f"fixture-{i:02}.wav", "reference": reference,
                "critical": {"drug": [name], "value": [digits, fraction], "unit": ["milligrammes", "comprimé"],
                             "dose": [strength, portion], "fraction": [fraction], "negation": [marker],
                             "negated_clause": [negation], "clinical_negation": [negation],
                             "laterality": [negation] if side else []},
                "drug_strength_associations": [{"drug": name, "value": digits, "unit": "mg", "drug_occurrence": 0}]}
        if (not bench.score.score_case(case, reference)["screen_passed"]
                or len(bench.score.drug_mentions(reference, terms)) != 1):
            raise ValueError("Chaque phrase doit valider dose, fraction, négation et son seul nom de référence")
        cases.append((case, speech))
    return cases


def main_lock(args):
    path = bench.safe_artifact(args.main, "protocol.frozen.json")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol["code_sha256"] != bench.sha256(Path(bench.__file__)) or protocol["context_sha256"] != bench.CONTEXT_SHA
            or protocol["evaluation_started"] is not False or protocol["product_pause_ms"] != 576):
        raise ValueError("Le banc de non-régression n'est pas celui figé")
    for relative, digest in protocol["dependencies_sha256"].items():
        bench.locked(bench.ROOT / relative, digest)
    return path, protocol


def prepare(args):
    terms, _ = bench.context_source(args.context)
    frozen, _ = main_lock(args)
    items = deck(terms)
    output = bench.lab.output_path(args.output, [args.main.resolve()], minimum_free=0.1)
    output.mkdir(mode=0o700)
    declaration = {"schema": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                   "source_code_sha256": bench.sha256(Path(__file__)), "main_protocol_sha256": bench.sha256(frozen),
                   "terms_sha256": bench.CONTEXT_SHA, "voice": VOICE, "rate_wpm": SPEED_WPM,
                   "must_keep_every_planned_item": True, "asr_not_started": True, "n": len(items)}
    # Freeze references and matching rules before audio synthesis as well.
    bench.lab.atomic_json(output / "planned.local.json", {
        **declaration, "items": [{"case": case, "spoken": spoken} for case, spoken in items]})
    rendered = []
    aiff = output / "render.aiff"
    try:
        for case, spoken in items:
            subprocess.run(["/usr/bin/say", "-v", VOICE, "-r", str(SPEED_WPM), "-o", str(aiff), spoken],
                           check=True, timeout=15, capture_output=True)
            pcm = subprocess.check_output(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(aiff),
                                           "-map_metadata", "-1", "-ar", "16000", "-ac", "1", "-c:a",
                                           "pcm_s16le", "-f", "s16le", "pipe:1"], timeout=10)
            if len(pcm) % 2 or not 2 * bench.RATE <= len(pcm) <= 12 * 2 * bench.RATE:
                raise ValueError("Rendu synthétique hors du contrat ; aucune phrase éliminée ou remplacée")
            path = output / case["wav"]
            path.write_bytes(canonical_wav(pcm))
            rendered.append({**case, "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
                             "wav_sha256": bench.sha256(path), "frames": len(pcm) // 2})
            aiff.unlink()
    except subprocess.SubprocessError:
        raise RuntimeError("Le synthétiseur ou le convertisseur a échoué ; aucune phrase remplacée") from None
    finally:
        aiff.unlink(missing_ok=True)
    bench.lab.atomic_json(output / "frozen.local.json", {**declaration, "os": platform.platform(), "cases": rendered,
                                                         "planned_sha256": bench.sha256(output / "planned.local.json")})
    print(f"11 phrases synthétiques figées, sans décodage : {bench.sha256(output / 'frozen.local.json')}", flush=True)


def replay(args):
    terms, prompt = bench.context_source(args.context)
    base_protocol, base = main_lock(args)
    negative = json.loads(bench.safe_artifact(args.main, "aggregate.json").read_text(encoding="utf-8"))
    if negative["status"] != "complete" or negative["protocol_sha256"] != bench.sha256(base_protocol):
        raise ValueError("Contre-épreuve de non-régression non terminée")
    out = bench.lab.private_directory(args.output)
    if out.stat().st_mode & 0o077:
        raise ValueError("Les sorties doivent rester dans un répertoire privé (0700)")
    frozen = bench.safe_artifact(out, "frozen.local.json")
    manifest = json.loads(frozen.read_text(encoding="utf-8"))
    bench.locked(bench.safe_artifact(out, "planned.local.json"), manifest["planned_sha256"])
    if (manifest["source_code_sha256"] != bench.sha256(Path(__file__)) or manifest["main_protocol_sha256"] != bench.sha256(base_protocol)
            or manifest["terms_sha256"] != bench.CONTEXT_SHA or manifest["asr_not_started"] is not True
            or manifest["n"] != 11 or manifest["voice"] != VOICE or manifest["rate_wpm"] != SPEED_WPM):
        raise ValueError("Plan positif modifié")
    audios = []
    for (planned, _), case in zip(deck(terms), manifest["cases"], strict=True):
        if any(case[k] != v for k, v in planned.items()):
            raise ValueError("Les règles de comparaison ne suivent pas le plan figé")
        pcm = bench.audio(bench.safe_artifact(out, case["wav"]), case["wav_sha256"], case["pcm_sha256"])
        if len(pcm) != 2 * case["frames"]:
            raise ValueError("Nombre d'échantillons différent du gel")
        audios.append((case, pcm))
    build = args.build.resolve(strict=True)
    bench.locked(build / "bridge.dylib", base["cpp_build"]["binary_sha256"])
    deps = json.loads(bench.safe_artifact(build, "dependencies.local.json").read_text(encoding="utf-8"))
    bench.locked(Path(deps["whisper"]), base["cpp_build"]["whisper_library_sha256"])
    for name, expected in base["cpp_build"]["ggml_libraries_sha256"].items():
        bench.locked(Path(deps["ggml"]) / name, expected)
    bench.locked(args.model, base["weights_sha256"])
    bench.locked(args.vad, base["vad_sha256"])
    with (out / "started.lock").open("x", encoding="utf-8") as lock:
        lock.write(bench.sha256(frozen) + "\n")
    with ExitStack() as stack:
        infer = bench.engine(args, stack)
        # Same non-panel warm-up as the negative run, once per arm. Start timing
        # the 11 positive pairs only after reaching the same warm state.
        bench.locked(args.smoke_wav, base["offgrid_wav_sha256"])
        warm = bench.pair(infer, bench.audio(args.smoke_wav, base["offgrid_wav_sha256"], None), prompt, 0)
        if not all(r["text"] for r in warm.values()):
            raise ValueError("Préchauffage positif refusé")
        started = perf_counter()
        rows = []
        for i, (case, pcm) in enumerate(audios):
            record = bench.pair(infer, pcm, prompt, i)
            if (not record["base"]["segments"] or record["context"]["tokens_in_prompt"] != warm["context"]["tokens_in_prompt"]
                    or perf_counter() - started > WALL_BUDGET_S):
                raise ValueError("Comparatif positif incomplet ; ne publier aucun résultat partiel")
            rows.append((case, record))
            if (i + 1) % 3 == 0:
                print(f"Positifs fictifs : {i + 1}/11 paires", flush=True)
    total = sum(len(pcm) for _, pcm in audios) / (2 * bench.RATE)
    raw = out / "paired.local.json"
    bench.lab.atomic_json(raw, [{"id": case["id"], "predictions": r} for case, r in rows])
    report = {"schema": 1, "status": "complete", "fixture_freeze_sha256": bench.sha256(frozen),
              "script_sha256": bench.sha256(Path(__file__)), "main_protocol_sha256": bench.sha256(base_protocol),
              "raw_results_sha256": bench.sha256(raw), "context_sha256": bench.CONTEXT_SHA,
              "positive_test_designed_to_cover_each_known_name": True, "only_synthetic": True, "independent": False,
              "one_phrase_per_term": True, "no_cases_dropped": True, "accuracy_not_qualified": True,
              "product_change": False, "will_not_override_negative_panel": True, "results": bench.summarize(rows, terms, total)}
    bench.lab.atomic_json(out / "aggregate.json", report)
    print("11 paires synthétiques regroupées, sans transcription.", flush=True)


def main():
    parser = ArgumentParser(description=__doc__)
    children = parser.add_subparsers(dest="action", required=True)
    for action, flags in (("prepare", ()), ("run", ("build", "model", "vad", "smoke-wav"))):
        sub = children.add_parser(action)
        for flag in ("main", "context", "output", *flags):
            sub.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args) if args.action == "prepare" else replay(args)
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Comparatif positif interrompu : {error}\n")


if __name__ == "__main__":
    main()
