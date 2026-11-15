"""Offline, paired Whisper.cpp context experiment. No changes to production."""

from argparse import ArgumentParser
from collections import Counter
from contextlib import ExitStack
import ctypes as c
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
from statistics import median
from time import perf_counter

from app.whisper_patch import DECODER_PATCH
from p0.asr_native import PCM, PTR, WHISPER_EMIT, symbol
from p0.bench.scoring import edit_distance, nearest_rank, words
from p0.decoder_ab import replace_once
from p0.training import score_validation as score, train_lora as lab
from p0.training.prepare_px import read_pcm, safe_artifact, sha256
from p0.training.report_stability import checks, paired


ROOT = lab.REPO
CONTEXT_SHA = "3f96d1818f6902ca6f15af08c15e224fc8e1193c0c2151227e2ca29c3249f097"
SYNTH_SHA = "7e71d9bfb6d1507a029c1c6a43b4680ebe3016f9bc7fd7a34d389828ef619cbd"
GRID_SHA = "e68b37befd34ae93870d14be4a5b54c2d3889c2b1a1f417f808326d718f7ebd7"
MODEL_SHA = "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"
VAD_SHA = "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
NATIVE = "app/native/WhisperBridge.cpp"
NAME_BUDGET = 64
RATE = 16000
LIMIT_SEC = 900
CONTROLS = (1, 3)
ARMS = ("base", "context")


def locked(path, expected):
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Empreinte différente : {path.name}")
    return actual


def capture_bridge(source, headers):
    """Copy the current bridge, sharing all ASR params except the prompt."""
    text = replace_once(source, '#include "WhisperBridge.h"', f'#include "{headers}/WhisperBridge.h"')
    text = replace_once(text, '#include "../macos/native/PauseState.h"', f'#include "{headers}/PauseState.h"')
    text = replace_once(text, 'void segment_log(const float* samples, size_t count) {',
                        'std::uint64_t fingerprint(const float* samples, size_t count) {')
    text = replace_once(text, '    std::fprintf(stderr, "nv_segment frames=%zu pcm_fnv1a64=%016" PRIx64 "\\n", count, fnv);',
                        '    return fnv;')
    text = replace_once(text, '    bool benchmark_metrics = false;',
                        '    bool benchmark_metrics = false;\n'
                        '    std::string context;\n'
                        '    std::uint64_t last_fingerprint = 0;')
    text = replace_once(text, '        if (benchmark_metrics) segment_log(samples, count);',
                        '        last_fingerprint = fingerprint(samples, count);')
    text = replace_once(text, '        params.n_threads = 4;',
                        '        params.n_threads = 4;\n'
                        '        params.initial_prompt = context.empty() ? nullptr : context.c_str();')
    text = replace_once(text, '    void reset() { pending = 0;',
                        '    int set_context(const char* prompt) {\n'
                        '        if (!prompt) return -1;\n'
                        '        const int n = *prompt ? whisper_token_count(asr.get(), prompt) : 0;\n'
                        f'        if ((*prompt && n < 1) || n > {NAME_BUDGET}) return -1;\n'
                        '        context = prompt; return n;\n'
                        '    }\n'
                        '    std::uint64_t segment_fingerprint() const { return last_fingerprint; }\n'
                        '    int direct(const float* pcm, size_t n, NVWhisperEmit fn, void* ctx) {\n'
                        '        emit = fn; output_context = ctx;\n'
                        '        return transcribe(pcm, n);\n'
                        '    }\n'
                        '    void reset() { pending = 0;')
    return replace_once(text, 'void* NVWhisperCreate(const char* model, const char* vad) {',
                        'int BenchContext(void* h, const char* prompt) {\n'
                        '    try { return h ? static_cast<Pipeline*>(h)->set_context(prompt) : -1; }\n'
                        '    catch (...) { return -1; }\n'
                        '}\n'
                        'std::uint64_t BenchFingerprint(void* h) { return static_cast<Pipeline*>(h)->segment_fingerprint(); }\n'
                        'int BenchDirect(void* h, const float* pcm, size_t n, NVWhisperEmit fn, void* ctx) {\n'
                        '    if (!h || !pcm || !n || n > 480000 || !fn) return -1;\n'
                        '    try { return static_cast<Pipeline*>(h)->direct(pcm, n, fn, ctx); }\n'
                        '    catch (...) { return -1; }\n'
                        '}\n'
                        'void* NVWhisperCreate(const char* model, const char* vad) {')


def build(args):
    if platform.system() != "Darwin":
        raise ValueError("La construction comparative locale exige macOS")
    upstream_build = args.frozen_decoder.resolve(strict=True)
    runtime = args.runtime.resolve(strict=True)
    archive = json.loads((upstream_build / "build.json").read_text(encoding="utf-8"))
    if archive["decoder_patch"] != DECODER_PATCH:
        raise ValueError("Le comparatif local ne correspond pas à 1.8.5 + correctif RNG")
    locked(upstream_build / "whisper-rng.cpp", DECODER_PATCH["after_sha256"])
    engine = upstream_build / "libwhisper-rng.dylib"
    old_artifacts = archive["artifacts"]
    engine_sha = locked(engine, old_artifacts[engine.name])
    libraries = {name: locked(runtime / name, expected) for name, expected in archive["ggml_libraries"].items()}
    for name in ("include/whisper.h", "ggml/include/ggml.h", "ggml/include/ggml-cpu.h", "ggml/include/ggml-backend.h"):
        locked(upstream_build / "upstream" / name, old_artifacts[f"upstream/{name}"])
    original = ROOT / NATIVE
    headers = ("app/native/WhisperBridge.h", "app/macos/native/PauseState.h", "app/macos/native/SileroPause.h")
    output = lab.output_path(args.build, [upstream_build, runtime], minimum_free=0.1)
    output.mkdir(mode=0o700)
    for name in headers:
        (output / Path(name).name).write_bytes((ROOT / name).read_bytes())
    cpp, binary = output / "bridge.cpp", output / "bridge.dylib"
    cpp.write_text(capture_bridge(original.read_text(encoding="utf-8"), output), encoding="utf-8")
    subprocess.run(["/usr/bin/clang++", "-std=c++17", "-O3", "-Wall", "-Wextra", "-Werror", "-dynamiclib",
                    "-isystem", str(upstream_build / "upstream/include"),
                    "-isystem", str(upstream_build / "upstream/ggml/include"),
                    str(cpp), str(engine), f"-Wl,-rpath,{runtime}", "-o", str(binary)], check=True)
    lab.atomic_json(output / "build.json", {
        "schema": 1, "compiled_source_sha256": sha256(cpp), "binary_sha256": sha256(binary),
        "production_source": {path: sha256(ROOT / path) for path in [NATIVE, *headers]},
        "whisper_library_sha256": engine_sha, "ggml_libraries_sha256": libraries,
        "upstream_decoder_build_manifest_sha256": sha256(upstream_build / "build.json"),
        "decoder_patch": DECODER_PATCH, "platform": platform.platform(),
    })
    lab.atomic_json(output / "dependencies.local.json", {"whisper": str(engine), "ggml": str(runtime)})


def context_source(path):
    locked(path, CONTEXT_SHA)
    item = json.loads(path.read_text(encoding="utf-8"))
    terms, prompt = item["terms"], item["prompt"]
    if (item["frozen_before_generation"] is not True or len(terms) != 11
            or any(not term or not all(v.isalpha() or v in " -'’" for v in term) for term in terms)
            or len(set(terms)) != len(terms) or prompt != ", ".join(terms) + "."):
        raise ValueError("La liste exploration figée est invalide")
    return terms, prompt


def audio(path, wav_hash, pcm_hash):
    if path.stat().st_size > 30 * 2 * RATE + 8192:
        raise ValueError("Audio trop long pour le protocole")
    payload = path.read_bytes()
    if wav_hash is not None and hashlib.sha256(payload).hexdigest() != wav_hash:
        raise ValueError("Les octets WAV diffèrent du manifeste")
    pcm = read_pcm(payload)
    if not 0 < len(pcm) <= 30 * 2 * RATE or (pcm_hash is not None and hashlib.sha256(pcm).hexdigest() != pcm_hash):
        raise ValueError("Le PCM diffère du manifeste")
    return pcm


def cohorts(args):
    locked(args.grid, GRID_SHA)
    locked(args.synthetic, SYNTH_SHA)
    grid, synth = (json.loads(p.read_text(encoding="utf-8")) for p in (args.grid, args.synthetic))
    if (grid["scoring_code_sha256"] != score.scoring_code_hashes() or grid["source_sha256"] != lab.PX_SHA256
            or grid["selection_count"] != 32 or grid["selection_offset"] != 0
            or len(grid["cases"]) != 32 or grid["predictions_used_to_prepare"] is not False
            or synth["train_eligible"] is not False or len(synth["cases"]) != 16):
        raise ValueError("Le lot d'évaluation ne correspond pas au protocole")
    px_manifest = safe_artifact(args.corpus, "validation.jsonl")
    locked(px_manifest, grid["validation_manifest_sha256"])
    picked = lab.validation_window([json.loads(line) for line in px_manifest.read_text(encoding="utf-8").splitlines()], 32, 0)
    cases = {"historical32": [], "synthetic16": []}
    for row, case in zip(picked, grid["cases"], strict=True):
        if ((row["id"], row["speaker_id"], row["text"], row["pcm_sha256"]) !=
                (case["id"], case["speaker_id"], case["reference"], case["pcm_sha256"])):
            raise ValueError("Les références et le PCM de Px ne sont pas appariés")
        path = safe_artifact(args.corpus, row["audio_filepath"])
        cases["historical32"].append((case, audio(path, row["audio_sha256"], case["pcm_sha256"])))
    for case in synth["cases"]:
        if Path(case["wav"]).name != case["wav"]:
            raise ValueError("Chemin synthétique invalide")
        path = safe_artifact(args.synthetic.parent, case["wav"])
        cases["synthetic16"].append((case, audio(path, case["wav_sha256"], case["pcm_sha256"])))
    all_ids = [case["id"] for values in cases.values() for case, _ in values]
    if len(set(all_ids)) != len(all_ids) or any(not score.score_case(case, case["reference"])["screen_passed"]
                                               for values in cases.values() for case, _ in values):
        raise ValueError("Référence dupliquée ou refusée par son propre écran critique")
    return cases


def active_contract(args, cases):
    build = json.loads((args.build / "build.json").read_text(encoding="utf-8"))
    locked(args.build / "bridge.dylib", build["binary_sha256"])
    files = json.loads((args.build / "dependencies.local.json").read_text(encoding="utf-8"))
    locked(Path(files["whisper"]), build["whisper_library_sha256"])
    for name, expected in build["ggml_libraries_sha256"].items():
        locked(Path(files["ggml"]) / name, expected)
    locked(args.model, MODEL_SHA)
    locked(args.vad, VAD_SHA)
    return {
        "schema": 1, "experiment": "cpp_initial_prompt_041", "evaluation_started": False,
        "code_sha256": sha256(Path(__file__)),
        "dependencies_sha256": {name: sha256(ROOT / name) for name in (
            "p0/asr_native.py", "p0/bench/scoring.py", "p0/decoder_ab.py", "p0/training/prepare_px.py",
            "p0/training/report_stability.py", "p0/training/train_lora.py", *score.scoring_code_hashes())},
        "cpp_build": build, "weights_sha256": MODEL_SHA, "vad_sha256": VAD_SHA,
        "context_sha256": CONTEXT_SHA, "medical_grid_sha256": GRID_SHA, "synthetic_sha256": SYNTH_SHA,
        "details": {key: {"clips": len(values), "pcm_seconds": sum(len(pcm) for _, pcm in values) / (2 * RATE),
                          "pcm_sequence_sha256": lab.json_digest([item["pcm_sha256"] for item, _ in values])}
                    for key, values in cases.items()},
        "offgrid_wav_sha256": sha256(args.smoke_wav), "language": "fr", "threads": 4,
        "rate": RATE, "packet_frames": 1600, "product_pause_ms": 576, "same_context_sequential_pairs": True,
        "one_pass_per_arm": True, "pair_order": "odd=base->context, even=context->base, restarts with each cohort",
        "no_context_history": True, "decoder": "greedy, upstream temperature fallback; same runtime and params",
        "max_wall_seconds": LIMIT_SEC, "silence_lengths_seconds": list(CONTROLS), "soft_prompt_max_tokens": NAME_BUDGET,
        "silence_pipelines": ["product_vad", "direct_shadow_only"],
        "decision_rule": "any new critical loss or prompted term insertion vetoes promotion; never auto promotes",
        "word_edits_tie_break": "substitution, deletion, insertion; literal WER tokenizer unchanged",
    }


def engine(args, stack):
    import numpy as np

    lib = c.CDLL(str((args.build / "bridge.dylib").resolve(strict=True)))
    create = symbol(lib, "NVWhisperCreateWithPause", PTR, c.c_char_p, c.c_char_p, c.c_uint)
    destroy = symbol(lib, "NVWhisperDestroy", None, PTR)
    context = symbol(lib, "BenchContext", c.c_int, PTR, c.c_char_p)
    fingerprint = symbol(lib, "BenchFingerprint", c.c_uint64, PTR)
    reset = symbol(lib, "NVWhisperReset", None, PTR)
    accept = symbol(lib, "NVWhisperAccept", c.c_int, PTR, PCM, c.c_size_t, WHISPER_EMIT, PTR)
    direct = symbol(lib, "BenchDirect", c.c_int, PTR, PCM, c.c_size_t, WHISPER_EMIT, PTR)
    finish = symbol(lib, "NVWhisperFinish", c.c_int, PTR, WHISPER_EMIT, PTR)
    cancel_t = c.CFUNCTYPE(c.c_bool, PTR)
    set_cancel = symbol(lib, "NVWhisperSetCancellation", None, PTR, cancel_t, PTR)
    handle = create(bytes(args.model.resolve()), bytes(args.vad.resolve()), 576)
    if not handle:
        raise RuntimeError("Initialisation du moteur impossible")
    stack.callback(destroy, handle)
    deadline = perf_counter() + LIMIT_SEC

    @cancel_t
    def cancel(_):
        return perf_counter() >= deadline

    set_cancel(handle, cancel, None)

    def infer(pcm, prompt, bypass_vad=False):
        clip = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(32768.0)
        reset(handle)
        n = context(handle, prompt.encode("utf-8"))
        if (prompt and not 1 <= n <= NAME_BUDGET) or (not prompt and n != 0):
            raise RuntimeError("Contexte Whisper refusé ou rogné")
        segments, callback_error, phase, audio_samples = [], [], "pause", 0

        @WHISPER_EMIT
        def collect(_, text, frames, ms):
            try:
                text = text.decode("utf-8")
                if not 0 < frames <= 30 * RATE or not math.isfinite(ms) or ms <= 0:
                    raise ValueError("Segment Whisper non conforme")
                segments.append({"text": text, "frames": frames, "float32_fnv1a64": f"{fingerprint(handle):016x}",
                                 "phase": phase, "received_audio_samples": audio_samples, "decode_ms": ms})
                return 0
            except (AttributeError, UnicodeError, ValueError) as error:
                callback_error.append(error)
                return -1

        def check(status):
            if status or cancel(None):
                raise RuntimeError("Moteur interrompu, comparatif incomplet") from (callback_error[0] if callback_error else None)

        def pointer(packet):
            return packet.ctypes.data_as(PCM)

        started = perf_counter()
        if bypass_vad:
            phase, audio_samples = "direct", clip.size
            check(direct(handle, pointer(clip), clip.size, collect, None))
        else:
            for i in range(0, clip.size, 1600):
                packet = clip[i:i + 1600]
                audio_samples = i + packet.size
                check(accept(handle, pointer(packet), packet.size, collect, None))
            phase = "stop"
            check(finish(handle, collect, None))
        return {"text": " ".join(s["text"] for s in segments if s["text"]), "tokens_in_prompt": n,
                "segments": segments, "elapsed_ms": (perf_counter() - started) * 1000,
                "decode_ms": sum(s["decode_ms"] for s in segments)}

    return infer


def order(index):
    return ARMS if index % 2 == 0 else ARMS[::-1]


def signature(record):
    return [(s["frames"], s["float32_fnv1a64"], s["phase"], s["received_audio_samples"]) for s in record["segments"]]


def pair(infer, pcm, prompt, index, direct=False):
    observed = {name: infer(pcm, prompt if name == "context" else "", direct) for name in order(index)}
    if (signature(observed["base"]) != signature(observed["context"]) or observed["base"]["tokens_in_prompt"] != 0
            or not 0 < observed["context"]["tokens_in_prompt"] <= NAME_BUDGET):
        raise RuntimeError("Tranches ou paramètres Whisper différents entre les bras")
    return observed


def word_edits(reference, hypothesis):
    """Deterministic decomposition of the existing literal word edit distance."""
    def add(values, edit):
        return tuple(value + (i == edit) for i, value in enumerate(values))

    last = [(0, 0, i) for i in range(len(hypothesis) + 1)]
    for i, original in enumerate(reference, 1):
        row = [(0, i, 0)]
        for j, predicted in enumerate(hypothesis, 1):
            candidates = (last[j - 1] if original == predicted else add(last[j - 1], 0),
                          add(last[j], 1), add(row[-1], 2))
            row.append(min(candidates, key=sum))
        last = row
    result = dict(zip(("substitutions", "deletions", "insertions"), last[-1], strict=True))
    if sum(result.values()) != edit_distance(reference, hypothesis):
        raise ValueError("Décomposition WER incohérente")
    return result


def name_counts(reference, observations, terms):
    expected = Counter(score.drug_mentions(reference, terms))
    actual = {name: Counter(score.drug_mentions(item["text"], terms)) for name, item in observations.items()}
    false = {name: observed - expected for name, observed in actual.items()}
    hits = {name: observed & expected for name, observed in actual.items()}
    return {"reference_occurrences": sum(expected.values()), **{
        "false_" + name: sum(false[name].values()) for name in ARMS}, **{
        "correct_" + name: sum(hits[name].values()) for name in ARMS},
        "new_false_with_context": sum((false["context"] - false["base"]).values()),
        "lost_correct_with_context": sum((hits["base"] - hits["context"]).values()),
        "gained_correct_with_context": sum((hits["context"] - hits["base"]).values())}


def summarize(rows, terms, seconds):
    totals = {name: Counter() for name in ARMS}
    all_checks, times = {name: [] for name in ARMS}, {name: [] for name in ARMS}
    all_names = Counter()
    changed = bystander = changed_without_expected_name = 0
    for case, records in rows:
        ref = words(case["reference"])
        names = name_counts(case["reference"], records, terms)
        all_names.update(names)
        bystander += names["reference_occurrences"] == 0
        different = records["base"]["text"] != records["context"]["text"]
        changed += different
        changed_without_expected_name += different and names["reference_occurrences"] == 0
        for name, rec in records.items():
            all_checks[name].append(checks(score.score_case(case, rec["text"])))
            totals[name].update(word_edits(ref, words(rec["text"])))
            totals[name].update({"clips_empty": not rec["text"], "reference_words": len(ref), "vad_segments": len(rec["segments"])})
            times[name].append(rec["elapsed_ms"])

    arms = {}
    for name, totals_arm in totals.items():
        totals_arm["word_errors"] = sum(totals_arm[k] for k in ("substitutions", "deletions", "insertions"))
        screened = {}
        for examined in all_checks[name]:
            for key, hits in examined.items():
                tally = screened.setdefault(key, [0, 0])
                tally[0] += sum(hits)
                tally[1] += len(hits)
        arm_ms = times[name]
        arms[name] = {**totals_arm, "wer": totals_arm["word_errors"] / totals_arm["reference_words"],
                      "critical": screened, "elapsed_ms": sum(arm_ms), "median_clip_ms": median(arm_ms),
                      "p95_clip_ms": nearest_rank(arm_ms), "rtf": sum(arm_ms) / (seconds * 1000)}
    return {"clips": len(rows), "input_audio_seconds": seconds, "arms": arms, "changed_transcripts": changed,
            "clips_without_expected_context_term": bystander, "modified_without_expected_term": changed_without_expected_name,
            "context_names": dict(all_names), "critical_changes": paired(all_checks["base"], all_checks["context"]),
            "context_to_base_wall_ratio": arms["context"]["elapsed_ms"] / arms["base"]["elapsed_ms"]}


def smoke(infer, pcm, prompt, terms, cases):
    warm = pair(infer, pcm, prompt, 0)
    repeated = pair(infer, pcm, prompt, 1)
    nonempty = all(rec["text"] for rec in warm.values())
    stable = all(warm[name]["text"] == repeated[name]["text"] and signature(warm[name]) == signature(repeated[name])
                 for name in ARMS)
    false = {name: name_counts("", warm, terms)["false_" + name] for name in ARMS}
    # Materialize the extreme bound apart from this single non-matched clip.
    # This is a rough go/no-go estimate, not a claim about actual speed.
    estimate = sum(r["elapsed_ms"] for r in repeated.values()) * (4 + 1.5 * sum(map(len, cases.values()))) / 1000
    return {"offgrid_both_nonempty": nonempty, "order_reversed_transcripts_and_segments_identical": stable,
            "no_prompt_names_on_offgrid": not any(false.values()), "prompt_names_on_offgrid": false, "frames": len(pcm) // 2,
            "warm_pair_ms": sum(r["elapsed_ms"] for r in repeated.values()),
            "context_tokens": warm["context"]["tokens_in_prompt"], "rough_wall_seconds_upper_estimate": estimate}


def process(args):
    terms, prompt = context_source(args.context)
    cases = cohorts(args)
    contract = active_contract(args, cases)
    if args.action == "freeze":
        output = lab.output_path(args.output, [args.corpus.resolve(), args.build.resolve()], minimum_free=0.1)
        output.mkdir(mode=0o700)
        lab.atomic_json(output / "protocol.frozen.json", {**contract, "frozen_utc": datetime.now(timezone.utc).isoformat()})
        print(f"Protocole gelé : {sha256(output / 'protocol.frozen.json')}", flush=True)
        return

    directory = lab.private_directory(args.output)
    if directory.stat().st_mode & 0o077:
        raise ValueError("Les sorties doivent rester dans un répertoire privé (0700)")
    freeze = safe_artifact(directory, "protocol.frozen.json")
    existing = json.loads(freeze.read_text(encoding="utf-8"))
    existing.pop("frozen_utc")
    if existing != contract or (directory / "aggregate.json").exists():
        raise ValueError("Protocole modifié, ou résultat déjà présent")
    pcm = audio(args.smoke_wav, contract["offgrid_wav_sha256"], None)
    with ExitStack() as stack:
        infer = engine(args, stack)
        if args.action == "smoke":
            output = directory / "smoke.json"
            if output.exists():
                raise ValueError("Ne pas remplacer une mesure déjà observée")
            probe = smoke(infer, pcm, prompt, terms, cases)
            lab.atomic_json(output, probe)
            print(json.dumps(probe), flush=True)
            return
        probe = json.loads(safe_artifact(directory, "smoke.json").read_text(encoding="utf-8"))
        if (probe["rough_wall_seconds_upper_estimate"] > LIMIT_SEC or probe["offgrid_both_nonempty"] is not True
                or probe["order_reversed_transcripts_and_segments_identical"] is not True
                or probe["no_prompt_names_on_offgrid"] is not True):
            raise ValueError("Le contrôle hors grille ne permet pas d'étendre la mesure")
        repetition = smoke(infer, pcm, prompt, terms, cases)
        if (repetition["context_tokens"] != probe["context_tokens"] or repetition["rough_wall_seconds_upper_estimate"] > LIMIT_SEC
                or not all(repetition[key] for key in ("offgrid_both_nonempty", "order_reversed_transcripts_and_segments_identical",
                                                       "no_prompt_names_on_offgrid"))):
            raise ValueError("Écart entre le contrôle initial et le moteur apparié")
        with (directory / "started.lock").open("x", encoding="utf-8") as lock:
            lock.write(sha256(freeze) + "\n")
        silence_rows, silence_aggregate = [], []
        for i, n in enumerate(CONTROLS):
            for direct in (False, True):
                row = pair(infer, b"\0" * (2 * RATE * n), prompt, i, direct)
                if any(r["tokens_in_prompt"] != (probe["context_tokens"] if title == "context" else 0) for title, r in row.items()):
                    raise ValueError("Nombre de jetons de contexte différent sur silence")
                mode = "direct_shadow_only" if direct else "product_vad"
                notes = {name: {"empty": not r["text"], "nonempty_word_text": bool(words(r["text"])),
                                "segments": len(r["segments"]), "elapsed_ms": r["elapsed_ms"],
                                "context_names": len(score.drug_mentions(r["text"], terms))} for name, r in row.items()}
                silence_rows.append({"seconds": n, "mode": mode, "records": row})
                silence_aggregate.append({"seconds": n, "mode": mode, "observed": notes})
        lab.atomic_json(directory / "silences.local.json", silence_rows)
        summarized, originals = {}, {}
        for key, items in cases.items():
            outputs = []
            for i, (case, pcm) in enumerate(items):
                record = pair(infer, pcm, prompt, i)
                if not record["base"]["segments"] or record["context"]["tokens_in_prompt"] != probe["context_tokens"]:
                    raise RuntimeError("Une dictée a perdu sa segmentation ou son contexte")
                outputs.append((case, record))
                if (i + 1) % 4 == 0:
                    print(f"{key} : {i + 1}/{len(items)} paires", flush=True)
            local = directory / (key + ".local.json")
            lab.atomic_json(local, [{"id": case["id"], "predictions": rec} for case, rec in outputs])
            originals[key] = sha256(local)
            summarized[key] = summarize(outputs, terms, contract["details"][key]["pcm_seconds"])
    report = {"schema": 1, "status": "complete", "protocol_sha256": sha256(freeze), "parameters": contract,
              "replays_without_or_with_same_frozen_names": summarized, "digital_silence": silence_aggregate,
              "silences_raw_sha256": sha256(directory / "silences.local.json"), "raw_results_sha256": originals,
              "offgrid_control": probe, "development_only": True, "references_used_to_select_context": False,
              "product_change": False, "windows_measured": False, "clinical_qualification": False}
    lab.atomic_json(directory / "aggregate.json", report)
    print("Rapport agrégé enregistré sans transcription.", flush=True)


def main():
    parser = ArgumentParser(description=__doc__)
    children = parser.add_subparsers(dest="action", required=True)
    for command, flags in (("build", ("frozen-decoder", "runtime", "build")),
                           *((command, ("build", "output", "model", "vad", "context", "grid", "synthetic", "corpus", "smoke-wav"))
                             for command in ("freeze", "smoke", "run"))):
        sub = children.add_parser(command)
        for flag in flags:
            sub.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args) if args.action == "build" else process(args)
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Comparatif interrompu : {error}\n")


if __name__ == "__main__":
    main()
