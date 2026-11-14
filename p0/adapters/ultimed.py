"""Benchmark Parakeet UltiMed INT8 locally with the P0 NDJSON protocol."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

from .__main__ import RATE, pcm_float, serve


LOCK = Path(__file__).resolve().parents[1] / "packs" / "ultimed-int8.lock.json"
MAX_AUDIO_MS = 30_000
MAX_PCM = RATE * 2 * MAX_AUDIO_MS // 1000
VERSIONS = {"onnx-asr": "0.12.0", "onnxruntime": "1.32.0", "numpy": "2.5.4"}
SPEECH_THRESHOLD = 0.5
MIN_SPEECH_MS = 90


def verify_weights(root, lock):
    for name, expected in lock["files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"Fichier UltiMed absent ou de taille inattendue : {name}")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != expected["sha256"]:
            raise ValueError(f"Empreinte UltiMed différente : {name}")


class UltiMed:
    def __init__(self, model_dir, threads, speech_gate_dir=None):
        import onnx_asr
        import onnxruntime as ort

        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        # An existing local directory uses onnx-asr's offline resolver.
        self.model = onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v3", path=model_dir, quantization="int8",
            providers=["CPUExecutionProvider"], sess_options=options,
        )
        self.speech_gate = None
        if speech_gate_dir is not None:
            gate_options = ort.SessionOptions()
            gate_options.intra_op_num_threads = 1
            gate_options.inter_op_num_threads = 1
            self.speech_gate = onnx_asr.load_vad(
                "silero", path=speech_gate_dir, providers=["CPUExecutionProvider"],
                sess_options=gate_options,
            )

    def start(self):
        self.raw = bytearray()

    def audio(self, raw):
        if len(self.raw) + len(raw) > MAX_PCM:
            raise ValueError("Dictée UltiMed de plus de 30 s")
        self.raw.extend(raw)

    def end(self):
        waveform = pcm_float(self.raw)
        if self.speech_gate is not None:
            import numpy as np

            # Silero consumes 512-sample hops plus 64 samples of context.
            # Pad only its probe; never trim or pad the ASR input.
            probe = np.pad(waveform, (0, max(0, 576 - len(waveform))))
            segments = next(self.speech_gate.segment_batch(
                probe[None, :], np.array([len(waveform)], dtype=np.int64), RATE,
                threshold=SPEECH_THRESHOLD, min_speech_duration_ms=MIN_SPEECH_MS,
                speech_pad_ms=0,
            ))
            if next(segments, None) is None:
                return ""
        return self.model.recognize(waveform, sample_rate=RATE).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--speech-gate-dir", type=Path, help="Activer Silero ONNX depuis un dossier local vérifié")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error("--threads doit être compris entre 1 et 32")
    try:
        lock_bytes = LOCK.read_bytes()
        lock = json.loads(lock_bytes)
        root = args.model_dir.resolve(strict=True)
        verify_weights(root, lock)
        speech_gate_dir = None
        if args.speech_gate_dir is not None:
            speech_gate_dir = args.speech_gate_dir.resolve(strict=True)
            verify_weights(speech_gate_dir, lock["optional_speech_gate"])
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.verify_only:
        print(f"Poids UltiMed vérifiés, révision {lock['revision']}")
        return 0

    os.environ["HF_HUB_OFFLINE"] = "1"
    for package, required in VERSIONS.items():
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "non installé"
        if version != required:
            parser.error(f"{package} {required} requis (trouvé : {version})")

    sys.stdout.flush()
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n") as out:
        with open(os.devnull, "w") as quiet:
            os.dup2(quiet.fileno(), sys.stdout.fileno())

        def emit(kind, **fields):
            out.write(json.dumps({"type": kind, **fields}, ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()

        engine = UltiMed(root, args.threads, speech_gate_dir)
        return serve(engine, {"engine": "parakeet-ultimed-int8", "details": {
            "mode": "final-only", "max_audio_ms": MAX_AUDIO_MS, "vad": speech_gate_dir is not None,
            "provider": "CPUExecutionProvider", "threads": args.threads, "inter_op_threads": 1,
            "precision": "int8", "decode": "greedy", "boosting": False, "regex_fixes": False,
            "model_revision": lock["revision"],
            "model_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
            "runtime": "onnx-asr", "runtime_version": VERSIONS["onnx-asr"],
            "onnxruntime_version": VERSIONS["onnxruntime"], "numpy_version": VERSIONS["numpy"],
            **({"vad_mode": "whole-clip-gate", "vad_threshold": SPEECH_THRESHOLD,
                "vad_min_speech_ms": MIN_SPEECH_MS, "vad_revision": lock["optional_speech_gate"]["revision"]}
               if speech_gate_dir is not None else {}),
        }}, sys.stdin.buffer, emit)


if __name__ == "__main__":
    raise SystemExit(main())
