"""Windows x64 comparison: two native Whisper versions, one pinned offline pipeline."""

from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import struct
import subprocess
import sys
import threading
from time import perf_counter

from app.fixture_checks import check_fixture
from app.prepare_windows import LOCK, fetch
from p0.windows.ct2_probe import load_fixtures
from p0.windows.measure import _MemoryCounters, _WindowsProcesses
from p0.windows.runtime_ab_build import BASELINE, CANDIDATE, SOURCES, build_pair


PAIRS = ("cold", "warm")
VERSIONS = (BASELINE, CANDIDATE)
WAV_RATE = 16000
SEND_FRAMES = 320  # 20 ms, same input packet size as the Windows package.
SAMPLE_MS = 50
WARMUP_ID = "px-826"
CONTROL_ID = "silence"
MODEL = "ggml-large-v3-turbo-q5_0.bin"
VAD = "ggml-silero-v6.2.0.bin"
OPENBLAS = "openblas-v0.3.34-source.tar.gz"
SEGMENT = re.compile(r"^nv_segment frames=(\d+) pcm_fnv1a64=([\da-f]{16})\r?$", re.M)
EMIT = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_char_p, c.c_size_t, c.c_double)


def fixtures():
    # The existing loader verifies gzip, WAV and PCM independently. Replay the
    # entire PCM, NOT pre-cut audio, so VAD differences remain visible.
    result = {case["id"]: (case, parts[0][2]) for case, parts in load_fixtures("uncut")}
    result[CONTROL_ID] = (None, bytes(2 * WAV_RATE * 8))
    return result


def initialized_worker(directory, model, vad):
    def symbol(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
        return fn

    start = perf_counter()
    lib = c.CDLL(str((directory / "nv_probe.dll").resolve(strict=True)), winmode=0x00000900)
    create = symbol(lib, "NVWhisperCreate", c.c_void_p, c.c_char_p, c.c_char_p)
    destroy = symbol(lib, "NVWhisperDestroy", None, c.c_void_p)
    reset = symbol(lib, "NVWhisperReset", None, c.c_void_p)
    accept = symbol(lib, "NVWhisperAccept", c.c_int, c.c_void_p, c.POINTER(c.c_float), c.c_size_t, EMIT, c.c_void_p)
    finish = symbol(lib, "NVWhisperFinish", c.c_int, c.c_void_p, EMIT, c.c_void_p)
    handle = create(os.fspath(model.resolve(strict=True)).encode("utf-8"),
                    os.fspath(vad.resolve(strict=True)).encode("utf-8"))
    if not handle:
        raise RuntimeError("Impossible de charger le pont du banc.")
    initialized_ms = (perf_counter() - start) * 1000

    def replay(case_id, pcm):
        floats = (c.c_float * (len(pcm) // 2))(*(row[0] / 32768.0 for row in struct.iter_unpack("<h", pcm)))
        segments, texts = [], []
        cursor, stopped = 0, False

        @EMIT
        def collect(_, result, size, timing):
            try:
                if not 0 < size <= 480_000 or not math.isfinite(timing) or timing < 0:
                    return -1
                texts.append(result.decode("utf-8"))
                segments.append({"frames": size, "decode_ms": round(timing, 3),
                                 "phase": "stop" if stopped else "pause",
                                 "feed_end_ms": None if stopped else cursor / 16})
                return 0
            except (TypeError, ValueError, AttributeError, UnicodeError):
                return -1

        begin = perf_counter()
        reset(handle)
        for offset in range(0, len(floats), SEND_FRAMES):
            count = min(SEND_FRAMES, len(floats) - offset)
            cursor = offset + count
            packet = c.cast(c.byref(floats, offset * c.sizeof(c.c_float)), c.POINTER(c.c_float))
            if accept(handle, packet, count, collect, None):
                raise RuntimeError("Échec du pont pendant la dictée fictive.")
        stopped = True
        if finish(handle, collect, None):
            raise RuntimeError("Échec du pont en fin de dictée fictive.")
        return {"id": case_id, "text": " ".join(part for part in texts if part),
                "speech_seconds": len(floats) / WAV_RATE, "segments": segments,
                "replay_ms": round((perf_counter() - begin) * 1000, 3)}

    return initialized_ms, replay, lambda: destroy(handle)


def worker(directory, model, vad, mode, case_id):
    clips = fixtures()
    ids = [case_id] if mode == "cold" else [WARMUP_ID, *clips.keys()]
    initialize_ms, replay, shutdown = initialized_worker(directory, model, vad)
    try:
        rows = [replay(item, clips[item][1]) for item in ids]
        # Private process pipe to the parent, never a benchmark artifact.
        print(json.dumps({"initialize_ms": round(initialize_ms, 3), "rows": rows}, ensure_ascii=True))
    finally:
        shutdown()


def attach_fingerprints(rows, diagnostic):
    matches = iter(SEGMENT.findall(diagnostic))
    for row in rows:
        for segment in row["segments"]:
            pair = next(matches, None)
            if pair is None or int(pair[0]) != segment["frames"]:
                raise ValueError("Empreinte/durée de tranche Silero absente ou incohérente.")
            segment["pcm_fnv1a64"] = pair[1]
    if next(matches, None) is not None or diagnostic.splitlines().count("nv_accel backend=BLAS") != 1:
        raise ValueError("Tranches non appariables ou backend OpenBLAS non confirmé.")


def sample_memory(process, done, report):
    api = _WindowsProcesses()
    handle = api._open(0x1000, False, process.pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return
    try:
        counters = _MemoryCounters()
        counters.cb = c.sizeof(counters)
        while not done.is_set():
            if api._memory(handle, c.byref(counters), counters.cb):
                report["samples"] += 1
                for key, value in (("peak_private_commit_bytes_sampled", counters.PrivateUsage),
                                   ("peak_working_set_bytes_sampled", counters.WorkingSetSize)):
                    report[key] = max(report[key], int(value))
            done.wait(SAMPLE_MS / 1000)
    finally:
        api._close(handle)


def run_worker(directory, model, vad, mode, case_id=None):
    args = [sys.executable, "-m", "p0.windows.runtime_ab", "--worker", "--output", str(directory),
            "--model", str(model), "--vad", str(vad), "--mode", mode]
    if case_id:
        args += ["--case", case_id]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("OPENBLAS_", "GOTO_", "OMP_", "GGML_", "WHISPER_"))}
    env["NOTEVIVE_ASR_BENCH_METRICS"] = "1"
    start = perf_counter()
    process = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    done = threading.Event()
    memory = {"samples": 0, "sample_ms": SAMPLE_MS, "peak_working_set_bytes_sampled": 0,
              "peak_private_commit_bytes_sampled": 0}
    sampler = threading.Thread(target=sample_memory, args=(process, done, memory))
    sampler.start()
    try:
        try:
            stdout, stderr = process.communicate(timeout=360 if mode == "warm" else 180)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=10)
            raise RuntimeError(f"Délai du processus de benchmark atteint ({directory.name}/{mode}).") from None
        outer_ms = (perf_counter() - start) * 1000
    finally:
        done.set()
        sampler.join()
    if process.returncode != 0:
        raise RuntimeError(f"Le processus de benchmark a échoué ({directory.name}/{mode}; code {process.returncode:#x}).")
    result = json.loads(stdout)
    attach_fingerprints(result["rows"], stderr.decode("utf-8", errors="replace"))
    # A post-communicate measure would observe an exited process. A missing
    # sampler is an error, not an apparent gain in memory.
    if not memory["samples"] or min(memory["peak_working_set_bytes_sampled"],
                                    memory["peak_private_commit_bytes_sampled"]) <= 0:
        raise RuntimeError("Aucun échantillon mémoire du processus Windows.")
    if mode == "warm":
        warmup = result["rows"].pop(0)
        if warmup["id"] != WARMUP_ID or not warmup["segments"]:
            raise RuntimeError("Échauffement voix non exécuté.")
    elif result["rows"][0]["id"] != case_id:
        raise ValueError("Le fils a rendu le mauvais WAV.")
    return {"initialize_ms": result["initialize_ms"], "process_wall_ms": round(outer_ms, 3),
            "memory": memory, "rows": result["rows"]}


def public_row(case, row):
    checks = check_fixture(case, row["text"]) if case else {"silent": not row["text"] and not row["segments"]}
    return {k: row[k] for k in ("id", "speech_seconds", "replay_ms", "segments")} | {
        "realtime_factor": round(row["replay_ms"] / (1000 * row["speech_seconds"]), 6), "checks": checks}


def shape(row):
    return [(seg["phase"], seg["feed_end_ms"], seg["frames"], seg["pcm_fnv1a64"]) for seg in row["segments"]]


def changed_checks(before, after):
    differences = []
    for group in ("terms",):
        if group in before and before[group][0] > after[group][0]:
            differences.append(group)
    for group, counts in before.get("critical_span_presence", {}).items():
        if counts[0] > after["critical_span_presence"][group][0]:
            differences.append("critical:" + group)
    differences += [key for key in before if before[key] is True and after.get(key) is False]
    return differences


def execution_orders(repeats):
    return [VERSIONS if num % 2 == 0 else VERSIONS[::-1] for num in range(repeats)]


def paired_summary(data, clips):
    checks = []
    stabilities = {}
    for i, pass_results in enumerate(data):
        for phase in PAIRS:
            arms = [pass_results[v][phase]["rows"] for v in VERSIONS]
            if [r["id"] for r in arms[0]] != [r["id"] for r in arms[1]]:
                raise ValueError("Fichiers non appariés.")
            expected = list(clips) if phase == "warm" else [WARMUP_ID]
            if [r["id"] for r in arms[0]] != expected:
                raise ValueError("Résultats aval incomplets.")
            for a, b in zip(*arms):
                case = clips[a["id"]][0]
                if case and (not a["segments"] or not b["segments"] or a["speech_seconds"] != b["speech_seconds"]):
                    raise ValueError("Voix non découpée ou longueurs des fichiers différentes.")
                public_a, public_b = public_row(case, a), public_row(case, b)
                checks.append({"repeat": i + 1, "phase": phase, "id": a["id"],
                               "same_pcm_and_pauses": shape(a) == shape(b),
                               "exact_text_equal": a["text"] == b["text"],
                               "regressions": changed_checks(public_a["checks"], public_b["checks"])})
                for version, row in zip(VERSIONS, (a, b)):
                    stabilities.setdefault((version, row["id"]), set()).add((row["text"], tuple(shape(row))))
    report = [
        {v: {mode: {**run, "rows": [public_row(clips[row["id"]][0], row) for row in run["rows"]]}
             for mode, run in arms[v].items()} for v in VERSIONS} for arms in data
    ]
    timing = {}
    for version in VERSIONS:
        warm = [row for trial in report for row in trial[version]["warm"]["rows"] if row["id"] != CONTROL_ID]
        cold = [trial[version]["cold"] for trial in report]
        segment_ms = sorted(segment["decode_ms"] for row in warm for segment in row["segments"])
        if not segment_ms:
            raise ValueError("Aucune transcription vocale à comparer.")
        timing[version] = {"warm_median_ms": statistics.median(row["replay_ms"] for row in warm),
                           "warm_median_realtime_factor": statistics.median(row["realtime_factor"] for row in warm),
                           "warm_segment_median_ms": statistics.median(segment_ms),
                           "warm_segment_p95_empirical_ms": segment_ms[math.ceil(.95 * len(segment_ms)) - 1],
                           "warm_segments": len(segment_ms),
                           "cold_process_median_ms": statistics.median(run["process_wall_ms"] for run in cold),
                           "cold_model_init_median_ms": statistics.median(run["initialize_ms"] for run in cold)}
    warm_ratios = [
        b["replay_ms"] / a["replay_ms"]
        for trial in report for a, b in zip(*(trial[v]["warm"]["rows"] for v in VERSIONS))
        if a["id"] != CONTROL_ID
    ]
    old, new = (timing[v] for v in VERSIONS)
    median_ratio = statistics.median(warm_ratios)
    stable = all(len(values) == 1 for values in stabilities.values())
    return {"measurements": report, "pair_checks": checks, "timing_summary": timing,
            "median_paired_warm_ratio": median_ratio,
            "unstable_cases": [{"runtime": v, "id": case_id} for (v, case_id), values in stabilities.items()
                               if len(values) > 1],
            "public_screen": {
                "warm_ratio_at_most_0_80": median_ratio <= .8,
                "warm_segment_p95_not_worse": new["warm_segment_p95_empirical_ms"] <= old["warm_segment_p95_empirical_ms"],
                "identical_segments": all(item["same_pcm_and_pauses"] for item in checks),
                "identical_transcripts": all(item["exact_text_equal"] for item in checks),
                "stable_transcripts": stable,
                "no_regression_in_tested_spans": all(not item["regressions"] for item in checks),
                "covers_asserted_negations": False,
                "qualified_for_release": False,
            }}


def execute(args):
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("Le benchmark nécessite un Windows x64 AVX2 et Visual Studio 2022.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    downloads = args.downloads or output / "downloads"
    sources = {version: downloads / f"whisper-v{version}-source.tar.gz" for version in VERSIONS}
    for version, name in sources.items():
        fetch(name, SOURCES[version])
    for name in (MODEL, VAD, OPENBLAS):
        fetch(downloads / name, LOCK["downloads"][name])
    builds = output / "builds"
    builds.mkdir()
    build = build_pair(sources, downloads / OPENBLAS, builds, args.jobs, args.cmake)
    clips = fixtures()
    passes = []
    for repeat, order in enumerate(execution_orders(args.repeats)):
        trial = {}
        for version in order:
            print(f"Répétition {repeat + 1}/{args.repeats} — Whisper {version}", flush=True)
            trial[version] = {}
            for phase in PAIRS:
                result = run_worker(builds / version, downloads / MODEL, downloads / VAD, phase,
                                    WARMUP_ID if phase == "cold" else None)
                trial[version][phase] = result
                print(f"  {phase}: {result['process_wall_ms']/1000:.2f} s (chargement inclus)", flush=True)
        passes.append(trial)
    report = {"schema_version": 1, "build": build, "mode": "Windows AVX2 CPU ClangCL",
              "phase_order": list(PAIRS), "repeats": args.repeats, "versions": list(VERSIONS),
              "arm_orders": execution_orders(args.repeats),
              "platform": {"arch": platform.machine(), "os_version": platform.version(), "logical_cpus": os.cpu_count()},
              "assets": {name: LOCK["downloads"][name]["hash"] for name in (MODEL, VAD, OPENBLAS)},
              "wav_sha256": {key: case["wav_sha256"] if case else None for key, (case, _) in clips.items()},
              "silence_control_pcm_sha256": hashlib.sha256(clips[CONTROL_ID][1]).hexdigest(),
              "pause_ms": 576, "asr_threads": 4, "vad_threads": 1, "packet_frames": SEND_FRAMES,
              **paired_summary(passes, clips)}
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, help="Cache existant, toutes les empreintes sont revalidées.")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--vad", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=PAIRS, help=argparse.SUPPRESS)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if not args.model or not args.vad or not args.mode or args.mode == "cold" and not args.case:
            parser.error("Arguments du fils incomplets.")
        worker(args.output, args.model, args.vad, args.mode, args.case)
        return 0
    if not 1 <= args.jobs <= 16 or not 2 <= args.repeats <= 6 or args.repeats % 2:
        parser.error("Jobs 1–16 et répétitions paires de 2 à 6.")
    return execute(args)


if __name__ == "__main__":
    sys.exit(main())
