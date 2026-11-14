"""Offline CPU-only development probe for CTranslate2, on the three public Px fixtures."""

from __future__ import annotations

import argparse
import gzip
import hashlib
from importlib.metadata import version
import io
import json
import logging
import os
from pathlib import Path
import platform
import sys
import tempfile
from time import perf_counter
from urllib.request import Request, urlopen
import wave

from app.fixture_checks import check_fixture


P0 = Path(__file__).resolve().parents[1]
MODEL_LOCK = P0 / "packs/ct2-turbo.lock.json"
SLICE_LOCK = P0 / "packs/ct2-silero-slices.lock.json"
FIXTURES = P0 / "fixtures"
RUNTIME = {"faster-whisper": "1.2.1", "ctranslate2": "4.9.0"}
DECODE = {
    "language": "fr", "task": "transcribe", "beam_size": 1, "best_of": 1,
    "temperature": 0.0, "condition_on_previous_text": False,
    "vad_filter": False, "word_timestamps": False,
}
RATE = 16_000


def ms(start):
    return round((perf_counter() - start) * 1000, 3)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_file(path, spec):
    if (not path.is_file() or path.stat().st_size != spec["bytes"] or
            digest(path) != spec["sha256"]):
        raise ValueError(f"Fichier absent, tronqué ou altéré : {path.name}")


def fetch_model(directory):
    lock = load(MODEL_LOCK)
    base = f"https://huggingface.co/{lock['repository']}/resolve/{lock['revision']}/"
    directory.mkdir(parents=True, exist_ok=True)
    for name, spec in lock["files"].items():
        target = directory / name
        if target.exists():
            require_file(target, spec)
            continue
        # An incomplete or corrupt download never acquires the final filename.
        with tempfile.TemporaryDirectory(prefix="ct2-download-", dir=directory) as temporary:
            stage = Path(temporary) / name
            seen = 0
            checksum = hashlib.sha256()
            with urlopen(Request(base + name, headers={"User-Agent": "NoteVive-CT2-probe/1"}), timeout=120) as response:
                with stage.open("xb") as out:
                    while block := response.read(1024 * 1024):
                        seen += len(block)
                        if seen > spec["bytes"]:
                            raise ValueError(f"Taille excessive du fichier publié : {name}")
                        checksum.update(block)
                        out.write(block)
            if seen != spec["bytes"] or checksum.hexdigest() != spec["sha256"]:
                raise ValueError(f"Empreinte du fichier téléchargé incorrecte : {name}")
            stage.rename(target)
        print(f"Modèle préparé : {name} ({seen} octets)", flush=True)


def fixture_pcm(case):
    packed = (FIXTURES / case["filename"]).read_bytes()
    if hashlib.sha256(packed).hexdigest() != case["gzip_sha256"]:
        raise ValueError("Fixture compressée altérée")
    data = gzip.decompress(packed)
    if len(data) != case["wav_bytes"] or hashlib.sha256(data).hexdigest() != case["wav_sha256"]:
        raise ValueError("Fixture WAV altérée")
    with wave.open(io.BytesIO(data)) as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes(),
                audio.getcomptype()) != (RATE, 1, 2, case["frames"], "NONE"):
            raise ValueError("Format de fixture WAV différent de mono 16 kHz int16")
        pcm = audio.readframes(audio.getnframes())
    if len(pcm) != 2 * case["frames"] or hashlib.sha256(pcm).hexdigest() != case["source"]["pcm_sha256"]:
        raise ValueError("Empreinte PCM de la fixture altérée")
    return pcm


def fixture_slices(case, pcm, entry):
    if not entry["slices"] or entry["wav_sha256"] != case["wav_sha256"]:
        raise ValueError("Provenance des tranches de test invalide")
    out = []
    previous_end = 0
    for part in entry["slices"]:
        start, end = part["start_frame"], part["end_frame"]
        if not (previous_end <= start < end <= case["frames"]):
            raise ValueError("Bornes ou ordre des tranches de test invalides")
        clip = pcm[2 * start:2 * end]
        if hashlib.sha256(clip).hexdigest() != part["pcm_sha256"]:
            raise ValueError("Tranche de test altérée")
        out.append((start, end, clip, part["pcm_float32_fnv1a64"]))
        previous_end = end
    return out


def load_fixtures(mode):
    first = dict(load(FIXTURES / "fixture.json"), id="px-826", terms=["prozac"],
                 critical={"dose": ["prozac 20 milligrammes"]})
    cases = [first, *load(FIXTURES / "regressions.json")["cases"]]
    locked = load(SLICE_LOCK)["fixtures"]
    if set(locked) != {case["id"] for case in cases}:
        raise ValueError("Les fixtures ne correspondent pas au verrou des tranches Silero")
    for case in cases:
        pcm = fixture_pcm(case)
        yield case, (fixture_slices(case, pcm, locked[case["id"]]) if mode == "silero576"
                     else [(0, case["frames"], pcm, None)])


def replay(model, parts, np):
    start = perf_counter()
    transcripts, timings = [], []
    for begin, end, pcm, locked_fingerprint in parts:
        clip = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        before = perf_counter()
        segments, _ = model.transcribe(clip, **DECODE)
        # Faster-whisper returns a generator; all decoding must finish in this timer.
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        timings.append({"start_frame": begin, "end_frame": end, "elapsed_ms": ms(before),
                        "nonempty": bool(text), "pcm_float32_fnv1a64_expected": locked_fingerprint})
        if text:
            transcripts.append(text)
    return " ".join(transcripts), timings, ms(start)


def run_probe(args):
    if (os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"} or
            sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32):
        raise RuntimeError("Le banc exige CPython 3.12 Windows x64")
    if args.output.exists() or (args.local_text and args.local_text.exists()):
        raise FileExistsError("Le rapport doit être un nouveau fichier")
    model_path = args.model.resolve(strict=True)
    lock = load(MODEL_LOCK)
    for name, spec in lock["files"].items():
        require_file(model_path / name, spec)
    cases = list(load_fixtures(args.segmentation))
    for package, expected in RUNTIME.items():
        if version(package) != expected:
            raise RuntimeError(f"Version épinglée requise : {package}")
    # No Hugging Face cache/download or library diagnostics during the probe.
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", HF_DATASETS_OFFLINE="1",
                      HF_HUB_DISABLE_IMPLICIT_TOKEN="1", TOKENIZERS_PARALLELISM="false", CT2_VERBOSE="0")
    logging.disable(logging.CRITICAL)
    start = perf_counter()
    import ctranslate2
    import numpy as np
    from faster_whisper import WhisperModel

    import_ms = ms(start)
    supported = ctranslate2.get_supported_compute_types("cpu")
    compute_type = lock["runtime_compute_type"]
    if compute_type not in supported:
        raise RuntimeError("INT8 float32 non pris en charge sur ce CPU")
    start = perf_counter()
    model = WhisperModel(str(model_path), device="cpu", compute_type=compute_type, cpu_threads=args.threads,
                         num_workers=1, local_files_only=True)
    load_ms = ms(start)
    if (model.model.compute_type != compute_type or model.model.device != "cpu" or
            model.model.num_workers != 1 or model.model.n_mels != 128 or not model.model.is_multilingual):
        raise RuntimeError("Configuration native de Whisper inattendue")
    _, _, warmup_ms = replay(model, cases[0][1], np)
    report = {"schema": 1, "engine": RUNTIME, "model_revision": lock["revision"],
              "model_sha256": lock["files"]["model.bin"]["sha256"], "cpu_threads": args.threads,
              "worker_count": 1, "device": model.model.device, "compute_type": model.model.compute_type,
              "decode": DECODE, "segmentation": args.segmentation, "slice_lock_sha256": digest(SLICE_LOCK),
              "import_ms": import_ms, "model_load_ms": load_ms,
              "warmup": {"id": cases[0][0]["id"], "elapsed_ms": warmup_ms}, "cases": []}
    local = {}
    for case, parts in cases:
        text, timings, elapsed_ms = replay(model, parts, np)
        fixture = check_fixture(case, text)
        local[case["id"]] = text
        report["cases"].append({"id": case["id"], "audio_ms": case["duration_ms"], "elapsed_ms": elapsed_ms,
                                "asr_elapsed_audio_ratio": round(elapsed_ms / case["duration_ms"], 5),
                                "slices": timings, "fixture_checks": fixture})
    report["critical_passed"] = all(row["fixture_checks"]["passed"] for row in report["cases"])
    if args.local_text:
        with args.local_text.open("x", encoding="utf-8") as out:
            out.write(json.dumps(local, ensure_ascii=False, indent=2) + "\n")
    with args.output.open("x", encoding="utf-8") as out:
        out.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    # A medical mismatch is a recorded comparison result, not a broken run.
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    fetch = sub.add_parser("fetch", help="Download the pinned model on the benchmark host only")
    fetch.add_argument("--model", type=Path, required=True)
    run = sub.add_parser("run", help="Run the probe without any download")
    run.add_argument("--model", type=Path, required=True)
    run.add_argument("--threads", type=int, choices=(2, 4), required=True)
    run.add_argument("--output", type=Path, required=True, help="New JSON file with metrics and counts, no text")
    run.add_argument("--local-text", type=Path, help="Optional new local transcript file; never an artifact")
    run.add_argument("--segmentation", choices=("silero576", "whole-wav"), default="silero576")
    args = parser.parse_args(argv)
    try:
        if args.operation == "fetch":
            fetch_model(args.model)
            return 0
        return run_probe(args)
    except Exception as error:
        # Remote errors can include temporary signed URLs; native failures can
        # include paths or transcript data. Publish only the exception type.
        print(f"Échec du banc CT2 ({type(error).__name__}).", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
