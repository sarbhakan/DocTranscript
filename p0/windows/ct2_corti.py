"""Evaluation-only paired CT2 replay of two pinned Corti Med-Dictate FR notes."""

from __future__ import annotations

import argparse
from collections import defaultdict
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
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import wave

from p0.asr_compare import CORTI_PCM_SHA256, CORTI_REVISION, CORTI_SPANS, annotated_matches, edit_distance, meaning_words
from p0.windows import ct2_probe as probe


LOCK = probe.P0 / "packs/ct2-corti.lock.json"
HOST = "datasets-server.huggingface.co"
SELECTED = (5, 6)
THREADS = 4


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def text_sha256(text):
    return sha256(text.encode("utf-8"))


def read_lock():
    lock = probe.load(LOCK)
    if (lock["schema"], lock["dataset"], lock["revision"], lock["config"], lock["split"]) != (
        1, "corti/med-dictate", CORTI_REVISION, "fr", "test"
    ) or set(lock["cases"]) != {f"corti-{index}" for index in SELECTED}:
        raise ValueError("Verrou du corpus inattendu")
    for key, spec in lock["cases"].items():
        index = spec["row"]
        spans = CORTI_SPANS[index]
        baseline = spec["macos_whisper_cpp"]["matched_spans"]
        if key != f"corti-{index}" or spec["pcm_sha256"] != CORTI_PCM_SHA256[index] or set(spans) != set(baseline):
            raise ValueError("Annotations ou PCM du verrou inattendus")
        if any(len(baseline[name]) != len(expected) or not all(type(value) is bool for value in baseline[name])
               for name, expected in spans.items()):
            raise ValueError("Comparateur de spans incomplet")
    return lock


class SameOriginRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.scheme, target.netloc) != ("https", HOST):
            raise ValueError("Redirection hors de la source officielle")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get(url, maximum):
    request = Request(url, headers={"User-Agent": "NoteVive-CT2-Corti-evaluation/1"})
    with build_opener(SameOriginRedirects).open(request, timeout=30) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Réponse distante trop volumineuse")
    return data


def official_audio_url(row, lock, spec):
    path = (f"/assets/{lock['dataset']}/--/{lock['revision']}/--/"
            f"{lock['config']}/{lock['split']}/{spec['row']}/audio/audio.wav")
    matching = []
    for audio in row["audio"]:
        url = urlsplit(audio["src"])
        if (url.scheme, url.netloc, url.path) == ("https", HOST, path) and not url.fragment:
            matching.append(audio["src"])
    if len(matching) != 1:
        raise ValueError("Révision Corti, régime HTTPS ou source audio différente")
    return matching[0]


def checked_reference(row, spec):
    reference = row["transcription_formatted"]
    if not isinstance(reference, str) or text_sha256(reference) != spec["reference_sha256"]:
        raise ValueError("Référence Corti différente")
    return reference


def checked_pcm(data, spec):
    with wave.open(io.BytesIO(data)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes(), wav.getcomptype()) != (
            1, 2, probe.RATE, spec["frames"], "NONE"
        ):
            raise ValueError("Format Corti différent du WAV figé")
        pcm = wav.readframes(wav.getnframes())
    if len(pcm) != 2 * spec["frames"] or sha256(pcm) != spec["pcm_sha256"]:
        raise ValueError("PCM Corti différent du WAV figé")
    return pcm


def read_cases(data, lock):
    for name, spec in lock["cases"].items():
        ref = checked_reference(probe.load(data / f"{name}.json"), spec)
        pcm = checked_pcm((data / f"{name}.wav").read_bytes(), spec)
        previous_end = 0
        parts = []
        for part in spec["slices"]:
            start, end = part["start_frame"], part["end_frame"]
            if not (previous_end <= start < end <= spec["frames"]) or end - start > 30 * probe.RATE:
                raise ValueError("Bornes de tranche Corti invalides")
            chunk = pcm[2 * start:2 * end]
            if sha256(chunk) != part["pcm_sha256"]:
                raise ValueError("Tranche Corti différente")
            parts.append((start, end, chunk, part["pcm_float32_fnv1a64"]))
            previous_end = end
        if not parts:
            raise ValueError("Aucune tranche Corti")
        yield spec, ref, parts


def fetch_cases(directory):
    lock = read_lock()
    if directory.exists():
        list(read_cases(directory, lock))
        print("Lot Corti local déjà vérifié.", flush=True)
        return
    query = urlencode({key: lock[key] for key in ("dataset", "config", "split")})
    index = json.loads(get(f"https://{HOST}/first-rows?{query}", maximum=256 * 1024))
    if any(index.get(key) != lock[key] for key in ("dataset", "config", "split")):
        raise ValueError("Index Corti différent")
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="corti-fetch-", dir=directory.parent) as temporary:
        stage = Path(temporary) / "data"
        stage.mkdir()
        for name, spec in lock["cases"].items():
            rows = [entry["row"] for entry in index["rows"] if entry["row_idx"] == spec["row"]]
            if len(rows) != 1:
                raise ValueError("Ligne Corti absente ou dupliquée")
            row = rows[0]
            reference = checked_reference(row, spec)
            wav = get(official_audio_url(row, lock, spec), maximum=spec["frames"] * 2 + 65536)
            checked_pcm(wav, spec)
            (stage / f"{name}.wav").write_bytes(wav)
            (stage / f"{name}.json").write_text(
                json.dumps({"transcription_formatted": reference}, ensure_ascii=False) + "\n",
                encoding="utf-8")
        list(read_cases(stage, lock))
        stage.rename(directory)
    print("Deux WAV Corti et leurs références vérifiés (données privées de test).", flush=True)


def score_case(spec, reference, recognized, changes, edits):
    for category, spans in CORTI_SPANS[spec["row"]].items():
        actual = [ok for _, ok in annotated_matches(recognized, spans, meaning_words)]
        baseline = spec["macos_whisper_cpp"]["matched_spans"][category]
        total = changes[category]
        total["tested"] += len(actual)
        total["ct2_windows_correct"] += sum(actual)
        total["whisper_cpp_macos_correct"] += sum(baseline)
        for previous, current in zip(baseline, actual, strict=True):
            total["ct2_gains"] += int(current and not previous)
            total["ct2_losses"] += int(previous and not current)
    expected = meaning_words(reference)
    if len(expected) != spec["macos_whisper_cpp"]["normalized_reference_words"]:
        raise ValueError("Normalisation du score différente de la référence Mac")
    edits["words"] += len(expected)
    edits["ct2_windows"] += edit_distance(expected, meaning_words(recognized))
    edits["whisper_cpp_macos"] += spec["macos_whisper_cpp"]["normalized_word_edits"]


def run(args):
    if (os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"} or
            sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32):
        raise RuntimeError("Le banc exige CPython 3.12 Windows x64")
    if args.output.exists() or (args.local_review and args.local_review.exists()):
        raise FileExistsError("Le rapport doit être un nouveau fichier")
    if args.local_review and os.environ.get("CI"):
        raise ValueError("Les sorties textuelles sont réservées à la relecture locale, hors CI")
    lock = read_lock()
    cases = list(read_cases(args.data, lock))
    model_lock = probe.load(probe.MODEL_LOCK)
    model_path = args.model.resolve(strict=True)
    for name, spec in model_lock["files"].items():
        probe.require_file(model_path / name, spec)
    for package, expected in probe.RUNTIME.items():
        if version(package) != expected:
            raise RuntimeError("Version du moteur différente du banc Px")
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", HF_DATASETS_OFFLINE="1",
                      HF_HUB_DISABLE_IMPLICIT_TOKEN="1", TOKENIZERS_PARALLELISM="false", CT2_VERBOSE="0")
    logging.disable(logging.CRITICAL)
    start = perf_counter()
    import ctranslate2
    import numpy as np
    from faster_whisper import WhisperModel

    import_ms = probe.ms(start)
    compute_type = model_lock["runtime_compute_type"]
    if compute_type not in ctranslate2.get_supported_compute_types("cpu"):
        raise RuntimeError("INT8 float32 indisponible sur ce CPU")
    start = perf_counter()
    model = WhisperModel(str(model_path), device="cpu", compute_type=compute_type, cpu_threads=THREADS,
                         num_workers=1, local_files_only=True)
    load_ms = probe.ms(start)
    if (model.model.compute_type != compute_type or model.model.device != "cpu" or
            model.model.num_workers != 1 or model.model.n_mels != 128 or not model.model.is_multilingual):
        raise RuntimeError("Configuration native de Whisper inattendue")
    warm, parts = next(probe.load_fixtures("silero576"))
    _, _, warmup_ms = probe.replay(model, parts, np)
    timings = []
    audio_ms = 0.0
    edits = {"words": 0, "ct2_windows": 0, "whisper_cpp_macos": 0}
    changes = defaultdict(lambda: dict(tested=0, ct2_windows_correct=0, whisper_cpp_macos_correct=0,
                                      ct2_gains=0, ct2_losses=0))
    local = []
    for spec, reference, parts in cases:
        text, times, _ = probe.replay(model, parts, np)
        timings.extend(times)
        audio_ms += spec["frames"] * 1000 / probe.RATE
        score_case(spec, reference, text, changes, edits)
        if args.local_review:
            local.append({"id": f"corti-{spec['row']}", "recognized": text})
    report = {
        "schema": 1,
        "dataset": lock["dataset"],
        "dataset_revision": lock["revision"],
        "benchmark_lock_sha256": probe.digest(LOCK),
        "cases": len(cases),
        "slices": len(timings),
        "whole_note_audio_ms": audio_ms,
        "note": "Exploratory CT2 Windows vs prior whisper.cpp macOS fidelity. Timings are only CT2 Windows.",
        "ct2": {"runtime": platform.platform(), "versions": probe.RUNTIME, "threads": THREADS,
                "compute_type": model.model.compute_type, "model_revision": model_lock["revision"],
                "model_sha256": model_lock["files"]["model.bin"]["sha256"],
                "decode": probe.DECODE, "import_ms": import_ms, "load_ms": load_ms,
                "warmup": {"id": warm["id"], "elapsed_ms": warmup_ms},
                "decode_ms_sum": round(sum(part["elapsed_ms"] for part in timings), 3),
                "empty_slices": sum(not part["nonempty"] for part in timings)},
        "reference_engine": lock["reference_engine"],
        "critical": dict(changes),
        "ct2_no_new_strict_negation_loss": changes["negation"]["ct2_losses"] == 0,
        "normalized_wer": {
            "reference_words": edits["words"],
            **{engine: {"edits": edits[engine], "wer": round(edits[engine] / edits["words"], 6)}
               for engine in ("ct2_windows", "whisper_cpp_macos")}
        }
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    if args.local_review:
        with args.local_review.open("x", encoding="utf-8") as stream:
            json.dump(local, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(report), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("fetch", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--data", type=Path, required=True, help="private folder for licensed benchmark data")
    run_args = sub.choices["run"]
    run_args.add_argument("--model", type=Path, required=True)
    run_args.add_argument("--output", type=Path, required=True, help="new aggregate JSON report")
    run_args.add_argument("--local-review", type=Path, help="private transcripts for re-reading; forbidden in CI")
    args = parser.parse_args(argv)
    try:
        if args.operation == "fetch":
            fetch_cases(args.data)
        else:
            run(args)
        return 0
    except Exception as error:
        # Never log signed source URLs, file contents or recognition output.
        print(f"Échec du contrôle Corti ({args.operation}, {type(error).__name__}).", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
