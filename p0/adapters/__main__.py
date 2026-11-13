"""P0 local ASR workers. stdout is exclusively the NDJSON protocol."""
import argparse
import base64
import binascii
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import sys

from p0.packs.__main__ import read_sealed


RATE = 16000
MAX_PCM = RATE * 2 * 20 * 60
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
RUNTIMES = {"sherpa": ("sherpa-onnx", "2.0.1"), "sherpa-final": ("sherpa-onnx", "2.0.1"),
            "whisper": ("pywhispercpp", "1.5.1")}


def pcm_float(raw):
    import numpy as np
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


class Sherpa:
    def __init__(self, cfg, files, threads):
        import sherpa_onnx
        self.final_only = cfg["adapter"] == "sherpa-final"
        self.locale = cfg.get("locale")
        self.tail_ms = cfg.get("tail_ms", 0)
        if self.locale not in {None, "fr-FR"} or type(self.tail_ms) is not int or not 0 <= self.tail_ms <= 1000:
            raise ValueError("configuration Sherpa invalide")
        options = dict(**{key: str(path) for key, path in files.items()}, num_threads=threads,
                       provider="cpu", sample_rate=RATE, feature_dim=80,
                       decoding_method="greedy_search", model_type=cfg.get("model_type", ""))
        if self.final_only:
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(**options)
        else:
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**options,
                                                                          enable_endpoint_detection=False)

    def start(self):
        self.stream = self.recognizer.create_stream()
        self.raw = bytearray()
        if self.locale:
            self.stream.set_option("language", self.locale)

    def decode_online(self):
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        return self.recognizer.get_result(self.stream).strip()

    def audio(self, raw):
        if self.final_only:
            self.raw.extend(raw)
            return None
        self.stream.accept_waveform(RATE, pcm_float(raw))
        return self.decode_online()

    def end(self):
        if self.final_only:
            self.stream.accept_waveform(RATE, pcm_float(self.raw))
            self.recognizer.decode_stream(self.stream)
            return self.stream.result.text.strip()
        if self.tail_ms:
            self.stream.accept_waveform(RATE, pcm_float(bytes(self.tail_ms * 32)))
        self.stream.input_finished()
        return self.decode_online()


class Whisper:
    # Non-overlapping windows with a hard cap. The current window is redecoded
    # periodically. Boundary artifacts are part of this baseline, not repaired.
    def __init__(self, cfg, files, threads):
        from pywhispercpp.model import Model
        step = cfg["step_ms"]
        window = cfg["window_ms"]
        if type(step) is not int or type(window) is not int or not 250 <= step <= window <= 30000:
            raise ValueError("fenêtre Whisper invalide")
        self.step_bytes, self.window_bytes = step * 32, window * 32
        self.model = Model(str(files["model"]), context_params={"use_gpu": False},
                           language="fr", n_threads=threads, translate=False, no_context=True,
                           print_progress=False, print_realtime=False, print_timestamps=False,
                           redirect_whispercpp_logs_to=None)

    def start(self):
        self.window = bytearray()
        self.committed = []
        self.last_size = 0

    def decode(self):
        return " ".join(s.text.strip() for s in self.model.transcribe(pcm_float(self.window)) if s.text.strip())

    def audio(self, raw):
        pos = 0
        hypothesis = None
        while pos < len(raw):
            size = min(len(raw) - pos, self.window_bytes - len(self.window))
            self.window.extend(raw[pos:pos + size])
            pos += size
            if len(self.window) == self.window_bytes:
                self.committed.append(self.decode())
                self.window.clear()
                self.last_size = 0
                hypothesis = " ".join(filter(None, self.committed))
            elif len(self.window) - self.last_size >= self.step_bytes:
                self.last_size = len(self.window)
                hypothesis = " ".join(filter(None, [*self.committed, self.decode()]))
        return hypothesis

    def end(self):
        return " ".join(filter(None, [*self.committed, self.decode() if self.window else ""]))


def serve(engine, ready, inp, emit):
    emit("ready", protocol=1, simulated=False, **ready)
    current = None
    seq = size = 0
    last = ""
    for line in inp:
        try:
            if len(line) > 1_000_000:
                raise ValueError("message too large")
            msg = json.loads(line)
            action, case_id = msg["type"], msg["id"]
            if not isinstance(case_id, str) or not ID.fullmatch(case_id):
                raise ValueError("case id")
            if action == "start" and current is None:
                if (msg["sample_rate"], msg["channels"], msg["sample_format"]) != (RATE, 1, "pcm_s16le"):
                    raise ValueError("audio format")
                current = case_id
                seq = size = 0
                last = ""
                engine.start()
            elif action == "audio" and current == case_id and msg["seq"] == seq:
                raw = base64.b64decode(msg["pcm_b64"], validate=True)
                size += len(raw)
                if not raw or len(raw) % 2 or size > MAX_PCM:
                    raise ValueError("audio size")
                seq += 1
                result = engine.audio(raw)
                if result is not None and result != last:
                    emit("partial", id=current, text=result)
                    last = result
            elif action == "end" and current == case_id and seq > 0:
                emit("final", id=current, text=engine.end())
                emit("done", id=current)
                current = None
            else:
                raise ValueError("invalid sequence")
        except (KeyError, TypeError, ValueError, binascii.Error):
            emit("error", code="invalid_request_or_input", **({"id": current} if current else {}))
            return 2
        except Exception:
            emit("error", code="worker_inference", **({"id": current} if current else {}))
            return 2
    return 0 if current is None else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter", choices=RUNTIMES)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error("--threads doit être compris entre 1 et 32")
    # Keep a dedicated protocol fd even if a native library writes to stdout.
    sys.stdout.flush()
    out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    # The duplicate of a redirected fd can be inheritable on some runtimes.
    os.set_inheritable(out.fileno(), False)
    with out, open(os.devnull, "w") as quiet:
        os.dup2(quiet.fileno(), sys.stdout.fileno())
        os.dup2(quiet.fileno(), sys.stderr.fileno())

        def emit(kind, **fields):
            out.write(json.dumps({"type": kind, **fields}, ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()

        try:
            cfg, files, manifest_sha = read_sealed(args.pack)
            if cfg["adapter"] != args.adapter or not ID.fullmatch(cfg["id"]):
                raise ValueError("adaptateur différent du pack")
        except (OSError, ValueError, TypeError, KeyError):
            emit("error", code="worker_pack_invalid")
            return 2
        runtime, required = RUNTIMES[args.adapter]
        try:
            if metadata.version(runtime) != required:
                emit("error", code="worker_runtime_version")
                return 2
            engine = (Whisper if args.adapter == "whisper" else Sherpa)(cfg, files, args.threads)
        except (ImportError, metadata.PackageNotFoundError):
            emit("error", code="worker_runtime_missing")
            return 2
        except Exception:
            emit("error", code="worker_model_init")
            return 2
        return serve(engine, {"engine": cfg["id"], "details": {
            "adapter": args.adapter, "provider": "cpu", "threads": args.threads,
            "runtime": runtime, "runtime_version": required, "manifest_sha256": manifest_sha,
            "mode": {"sherpa": "native-stream", "sherpa-final": "final-only", "whisper": "windows"}[args.adapter],
            **{key: cfg[key] for key in ("locale", "tail_ms", "step_ms", "window_ms", "model_type") if key in cfg},
        }}, sys.stdin.buffer, emit)


if __name__ == "__main__":
    sys.exit(main())
