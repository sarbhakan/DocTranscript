"""Rejoue un corpus de dictée vers un processus local persistant."""

import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import wave

from .scoring import edit_distance, nearest_rank, words


RATE = 16_000
PROTOCOL = 1
MAX_LINE = 1_048_576
MAX_TEXT = 32_768
CSV_FIELDS = ("id", "partition", "kind", "status", "reason", "warmup", "duration_ms",
              "speech_start_ms", "speech_end_ms", "first_nonempty_from_audio_start_ms",
              "first_correct_from_speech_start_ms", "first_correct_event",
              "first_correct_before_speech_end", "final_from_speech_end_ms",
              "final_from_end_request_ms", "case_elapsed_ms", "rtf", "audio_chunks",
              "partial_updates", "revised_partial_tokens", "send_lag_p95_ms",
              "reference_words", "hypothesis_words", "word_errors",
              "non_speech_nonempty_hypothesis")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
SAFE_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


class BenchError(Exception):
    """Erreur de banc affichable sans journaliser les sorties du moteur."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def offset_ms(case, column):
    value = (case.get(column) or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        raise BenchError(f"{case['id']}: {column} invalide") from None
    if not math.isfinite(number) or number < 0:
        raise BenchError(f"{case['id']}: {column} invalide")
    return number


def read_wav(path):
    try:
        blob = path.read_bytes()
        with wave.open(io.BytesIO(blob)) as f:
            if (f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getcomptype()) != (
                1, 2, RATE, "NONE"
            ):
                raise BenchError(f"{path.name}: attendu WAV PCM 16 bits mono 16 kHz")
            nframes = f.getnframes()
            pcm = f.readframes(nframes)
    except (OSError, EOFError, wave.Error):
        raise BenchError(f"{path.name}: WAV absent, illisible ou incompatible") from None
    if nframes == 0 or len(pcm) != 2 * nframes:
        raise BenchError(f"{path.name}: WAV vide ou tronqué")
    return pcm, digest(blob)


def load_corpus(path, wav_dir, partitions):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    required = {"id", "partition", "kind", "reference"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise BenchError("Colonnes CSV requises : id,partition,kind,reference")
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise BenchError("En-tête CSV ambigu (colonnes répétées)")
    cases = []
    seen = set()
    present_partitions = set()
    for row in reader:
        if None in row or any(row.get(key) is None for key in required):
            raise BenchError(f"CSV mal formé à la ligne {reader.line_num}")
        case_id = row["id"].strip()
        partition = row["partition"].strip()
        kind = row["kind"].strip()
        if not SAFE_ID.fullmatch(case_id) or not SAFE_ID.fullmatch(partition):
            raise BenchError(f"Identifiant ou partition invalide à la ligne {reader.line_num}")
        # Windows et macOS peuvent ignorer la casse dans les noms de fichiers.
        if case_id.casefold() in seen or kind not in {"speech", "silence", "noise"}:
            raise BenchError(f"{case_id}: doublon ou kind invalide")
        seen.add(case_id.casefold())
        present_partitions.add(partition)
        if "all" not in partitions and partition not in partitions:
            continue
        reference = row["reference"].strip()
        if (kind == "speech" and not words(reference)) or (kind != "speech" and reference):
            raise BenchError(f"{case_id}: référence incompatible avec kind")
        path_wav = wav_dir / f"{case_id}.wav"
        pcm, sha256 = read_wav(path_wav)
        duration = 1000 * len(pcm) / 2 / RATE
        begin, end = (offset_ms(row, key) for key in ("speech_start_ms", "speech_end_ms"))
        if (begin is None) != (end is None) or (
            begin is not None and not (kind == "speech" and 0 <= begin < end <= duration)
        ):
            raise BenchError(f"{case_id}: bornes de parole incompatibles avec le WAV")
        cases.append({"id": case_id, "partition": partition, "kind": kind, "reference": reference,
                      "wav": path_wav, "duration_ms": duration, "wav_sha256": sha256,
                      "speech_start_ms": begin, "speech_end_ms": end})
    if not cases or ("all" not in partitions and not set(partitions) <= present_partitions):
        raise BenchError("Aucun cas sélectionné ou partition demandée absente")
    return cases, digest(raw)


def receive_lines(pipe, events):
    """Horodate au moment où la ligne complète est lue, avant le décodage JSON."""
    try:
        while True:
            raw = pipe.readline(MAX_LINE + 1)
            arrived = time.perf_counter_ns()
            if not raw:
                events.put((arrived, None))
                return
            if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                events.put((arrived, {"type": "_invalid"}))
                return
            try:
                message = json.loads(raw.decode("utf-8"))
                if not isinstance(message, dict):
                    raise ValueError
            except (UnicodeError, ValueError, RecursionError):
                message = {"type": "_invalid"}
            events.put((arrived, message))
    except OSError:
        events.put((time.perf_counter_ns(), None))


def write_event(pipe, message):
    pending = memoryview(json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n")
    while pending:
        count = pipe.write(pending)
        if not count:
            raise BrokenPipeError
        pending = pending[count:]


def json_line(file, item):
    file.write(json.dumps(item, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    file.flush()


def wait_event(events, deadline_ns):
    remaining = (deadline_ns - time.perf_counter_ns()) / 1e9
    try:
        arrived, message = events.get(timeout=max(remaining, 0))
    except queue.Empty:
        raise BenchError("timeout") from None
    if arrived > deadline_ns:
        raise BenchError("timeout")
    if message is None:
        raise BenchError("worker_eof")
    if message.get("type") == "_invalid":
        raise BenchError("invalid_ndjson")
    return arrived, message


def error_code(message):
    code = message.get("code")
    if not isinstance(code, str) or not SAFE_CODE.fullmatch(code):
        return "worker_error"
    return f"worker_error:{code}"


class Worker:
    def __init__(self, command, startup_timeout):
        self.events = queue.Queue()
        self.started_ns = time.perf_counter_ns()
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, shell=False)
            # stdout reste tamponné pour lire les lignes. stdin est détaché afin
            # que sa fermeture après un délai ne dépende pas du verrou d'écriture.
            self.process.stdin = self.process.stdin.detach()
        except OSError:
            raise BenchError("worker_launch_failed") from None
        self.reader = threading.Thread(target=receive_lines,
                                       args=(self.process.stdout, self.events), daemon=True)
        self.reader.start()
        try:
            arrived, ready = wait_event(self.events, self.started_ns + int(startup_timeout * 1e9))
            if ready.get("type") == "error":
                raise BenchError(error_code(ready))
            if (ready.get("type") != "ready" or type(ready.get("protocol")) is not int
                    or ready["protocol"] != PROTOCOL or not isinstance(ready.get("engine"), str)
                    or not SAFE_ID.fullmatch(ready["engine"]) or type(ready.get("simulated")) is not bool):
                raise BenchError("invalid_ready")
            self.ready = {key: ready[key] for key in ("protocol", "engine", "simulated")}
            if isinstance(ready.get("details"), dict):
                # Les détails autorisés sont les paramètres techniques, pas des chemins ni du texte.
                try:
                    json.dumps(ready["details"], allow_nan=False)
                except ValueError:
                    raise BenchError("invalid_ready_details") from None
                self.ready["details"] = ready["details"]
            self.ready_ms = (arrived - self.started_ns) / 1e6
        except BaseException:
            self.close(force=True)
            raise

    def close(self, force=False):
        proc = self.process
        if force:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            proc.stdin.close()
        else:
            proc.stdin.close()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        # Le thread atteint EOF à la fermeture du worker. Ne pas bloquer sur un
        # descendant qui aurait hérité par erreur du handle stdout.
        self.reader.join(timeout=0.2)
        if not self.reader.is_alive():
            proc.stdout.close()
        return proc.returncode


def send_case(pipe, case, pcm, chunk_frames, realtime, signals, stop):
    case_id = case["id"]
    try:
        write_event(pipe, {"type": "start", "id": case_id, "sample_rate": RATE,
                           "channels": 1, "sample_format": "pcm_s16le"})
        origin_ns = time.perf_counter_ns()
        signals["origin_ns"] = origin_ns
        chunk_bytes = 2 * chunk_frames
        for seq, first in enumerate(range(0, len(pcm), chunk_bytes)):
            block = pcm[first:first + chunk_bytes]
            target = origin_ns + ((first + len(block)) // 2) * 1_000_000_000 // RATE
            if realtime and stop.wait(max(0, (target - time.perf_counter_ns()) / 1e9)):
                return
            if stop.is_set():
                return
            write_event(pipe, {"type": "audio", "id": case_id, "seq": seq,
                               "pcm_b64": base64.b64encode(block).decode("ascii")})
            sent = time.perf_counter_ns()
            if realtime:
                signals["send_lag_ms"].append(max(0.0, (sent - target) / 1e6))
            signals["audio_chunks"] = seq + 1
        if not stop.is_set():
            signals["end_ns"] = time.perf_counter_ns()
            write_event(pipe, {"type": "end", "id": case_id})
    except (OSError, ValueError):
        signals["write_error"] = True


def relative_ms(timestamp_ns, origin_ns):
    if timestamp_ns is None or origin_ns is None:
        return None
    return round((timestamp_ns - origin_ns) / 1e6, 3)


def run_case(worker, case, args, trace, warmup=False):
    pcm, actual_sha = read_wav(case["wav"])
    if actual_sha != case["wav_sha256"]:
        raise BenchError(f"{case['id']}: WAV modifié après l’inventaire")
    started_ns = time.perf_counter_ns()
    case_id = case["id"]
    realtime = args.mode == "realtime"
    duration_ns = int(case["duration_ms"] * 1e6) if realtime else 0
    deadline = started_ns + duration_ns + int(args.timeout_s * 1e9)
    signals = {"send_lag_ms": [], "audio_chunks": 0}
    stop = threading.Event()
    reference = words(case["reference"])
    sender = threading.Thread(target=send_case, daemon=True, args=(
        worker.process.stdin, case, pcm, args.chunk_ms * RATE // 1000, realtime, signals, stop
    ))
    first_nonempty = first_correct = final_at = done_at = None
    first_correct_type = final_text = None
    previous_partial = ()
    updates = revised_tokens = 0
    control_output = False
    failure = None
    json_line(trace, {"event": "case_started", "id": case_id, "warmup": warmup})
    sender.start()
    try:
        while done_at is None:
            at, message = wait_event(worker.events, deadline)
            typ = message.get("type")
            if message.get("id") != case_id:
                raise BenchError("unexpected_case_id")
            if typ == "error":
                raise BenchError(error_code(message))
            if typ not in ("partial", "final", "done"):
                raise BenchError("unexpected_event")
            if typ == "done":
                if final_at is None:
                    raise BenchError("missing_final")
                done_at = at
            else:
                text = message.get("text")
                if not isinstance(text, str) or len(text) > MAX_TEXT:
                    raise BenchError("invalid_text")
                if final_at is not None:
                    raise BenchError("event_after_final")
                tokens = words(text)
                if text.strip() and first_nonempty is None:
                    first_nonempty = at
                if reference and tokens[:1] == reference[:1] and first_correct is None:
                    first_correct = at
                    first_correct_type = typ
                if case["kind"] != "speech" and text.strip():
                    control_output = True
                if typ == "final":
                    if "end_ns" not in signals or at < signals["end_ns"]:
                        raise BenchError("premature_final")
                    final_at, final_text = at, text
                else:
                    updates += 1
                    prefix = 0
                    for before, after in zip(previous_partial, tokens):
                        if before != after:
                            break
                        prefix += 1
                    revised_tokens += len(previous_partial) - prefix
                    previous_partial = tokens
            json_line(trace, {"event": typ, "id": case_id, "warmup": warmup,
                              "ms_from_case_start": relative_ms(at, started_ns)})
    except BenchError as e:
        failure = str(e)
    finally:
        stop.set()
        sender.join(timeout=0.2)
    if signals.get("write_error") or (not failure and sender.is_alive()):
        failure = failure or "worker_write_failed"
    if failure:
        json_line(trace, {"event": "failed", "id": case_id, "warmup": warmup, "reason": failure})
    origin = signals.get("origin_ns")
    audio_first = relative_ms(first_nonempty, origin)
    first_word_audio = relative_ms(first_correct, origin)
    audio_final = relative_ms(final_at, origin)
    first_latency = final_latency = None
    begin, end = case["speech_start_ms"], case["speech_end_ms"]
    if not failure and realtime and begin is not None:
        if first_word_audio is not None and first_word_audio >= begin:
            first_latency = round(first_word_audio - begin, 3)
        if final_text and final_text.strip() and audio_final is not None and audio_final >= end:
            final_latency = round(audio_final - end, 3)
    complete_ms = relative_ms(done_at, started_ns)
    result = {"id": case_id, "partition": case["partition"], "kind": case["kind"],
              "status": "failed" if failure else "ok", "reason": failure, "warmup": warmup,
              "duration_ms": case["duration_ms"], "speech_start_ms": begin, "speech_end_ms": end,
              "first_nonempty_from_audio_start_ms": audio_first,
              "first_correct_from_speech_start_ms": first_latency, "first_correct_event": first_correct_type,
              "first_correct_before_speech_end": bool(first_latency is not None and first_word_audio < end)
              if realtime and end is not None else None,
              "final_from_speech_end_ms": final_latency,
              "final_from_end_request_ms": relative_ms(final_at, signals.get("end_ns")),
              "case_elapsed_ms": complete_ms,
              "rtf": round(complete_ms / case["duration_ms"], 6)
              if complete_ms is not None and not realtime and not failure else None,
              "audio_chunks": signals["audio_chunks"], "partial_updates": updates,
              "revised_partial_tokens": revised_tokens,
              "send_lag_p95_ms": nearest_rank(signals["send_lag_ms"])["value"],
              "reference_words": len(reference), "hypothesis_words": len(words(final_text or ""))
              if not failure else 0,
              "word_errors": edit_distance(reference, words(final_text or "") if not failure else [])
              if reference else None,
              "non_speech_nonempty_hypothesis": control_output if case["kind"] != "speech" else None}
    return result, final_text


def not_run(case, reason):
    ref_count = len(words(case["reference"]))
    return {"id": case["id"], "partition": case["partition"], "kind": case["kind"],
            "status": "not_run", "reason": reason, "warmup": False,
            "duration_ms": case["duration_ms"], "speech_start_ms": case["speech_start_ms"],
            "speech_end_ms": case["speech_end_ms"], "reference_words": ref_count,
            "hypothesis_words": 0, "word_errors": ref_count if ref_count else None}


def summary(rows, mode, simulated):
    speech = [row for row in rows if row["kind"] == "speech"]
    annotated = [row for row in speech if row["speech_start_ms"] is not None] if mode == "realtime" else []
    reference_words = sum(row["reference_words"] for row in speech)
    errors = sum(row["word_errors"] for row in speech)
    controls = [row for row in rows if row["kind"] != "speech"]
    return {
        "classification": "simulation_only" if simulated is True else "engine_worker_only"
        if simulated is False else "no_engine_result",
        "cases": len(rows),
        "failed_cases": sum(row["status"] == "failed" for row in rows),
        "not_run_cases": sum(row["status"] == "not_run" for row in rows),
        "speech_cases": len(speech),
        "annotated_realtime_speech_cases": len(annotated),
        "reference_words": reference_words, "word_errors": errors,
        "wer": round(errors / reference_words, 6) if reference_words else None,
        "p95_first_correct_from_speech_start_ms": nearest_rank(
            [row.get("first_correct_from_speech_start_ms") for row in annotated]),
        "p95_final_from_speech_end_ms": nearest_rank(
            [row.get("final_from_speech_end_ms") for row in annotated]),
        "first_correct_before_speech_end_cases": sum(
            row.get("first_correct_before_speech_end") is True for row in annotated),
        "p95_rtf_accelerated": nearest_rank([row.get("rtf") for row in speech] if mode == "accelerated" else []),
        "controls": len(controls),
        "controls_with_nonempty_hypotheses": sum(
            row.get("non_speech_nonempty_hypothesis") is True for row in controls),
        "controls_completed": sum(row["status"] == "ok" for row in controls),
    }


def dump_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def run(args, command):
    cases, corpus_sha = load_corpus(args.cases, args.wav_dir, args.partition)
    if args.warmup and args.warmup_wav:
        pcm, sha = read_wav(args.warmup_wav)
        if any(case["wav_sha256"] == sha for case in cases if case["partition"] != "dev"):
            raise BenchError("Le WAV d’échauffement figure dans une partition autre que dev")
        warmup_case = {"id": "benchmark_warmup", "kind": "speech", "partition": "warmup",
                       "reference": "", "wav": args.warmup_wav, "wav_sha256": sha,
                       "duration_ms": 1000 * len(pcm) / 2 / RATE,
                       "speech_start_ms": None, "speech_end_ms": None}
    else:
        warmup_case = next((case for case in cases
                            if case["kind"] == "speech" and case["partition"] == "dev"), None)
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        raise BenchError("Le dossier de sortie doit être absent ou vide")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(), "system": platform.system(),
        "system_release": platform.release(), "system_version": platform.version(),
        "machine": platform.machine(), "logical_cpus": os.cpu_count(),
        "mode": args.mode, "partitions": args.partition, "chunk_ms": args.chunk_ms,
        "startup_timeout_s": args.startup_timeout_s, "timeout_s": args.timeout_s,
        "warmup_requested": args.warmup, "include_text": args.include_text,
        "warmup_source": ("explicit_development_wav" if args.warmup_wav else "first_development_speech")
        if args.warmup and warmup_case else None,
        "warmup_wav_sha256": warmup_case["wav_sha256"] if args.warmup and warmup_case else None,
        "cases_csv_sha256": corpus_sha, "runner_sha256": digest(Path(__file__).read_bytes()),
        "scoring_sha256": digest(Path(__file__).with_name("scoring.py").read_bytes()),
        # Les paramètres du moteur passent par ready.details. Les arguments bruts
        # peuvent contenir des chemins locaux et ne sont pas inscrits au manifeste.
        "worker": None, "cases": [
            {key: row[key] for key in ("id", "partition", "kind", "duration_ms", "wav_sha256",
                                      "speech_start_ms", "speech_end_ms")}
            for row in cases
        ],
    }
    dump_json(args.output / "manifest.json", manifest)
    rows, warmups = [], []
    terminal_failure = None
    worker = None
    with (args.output / "trace.ndjson").open("w", encoding="utf-8") as trace:
        transcripts = (args.output / "transcripts.ndjson").open("w", encoding="utf-8") if args.include_text else None
        try:
            try:
                worker = Worker(command, args.startup_timeout_s)
                manifest["worker"] = worker.ready
                manifest["worker_ready_ms"] = worker.ready_ms
                dump_json(args.output / "manifest.json", manifest)
                json_line(trace, {"event": "ready", "ms_from_launch": round(worker.ready_ms, 3)})
                if warmup_case:
                    for _ in range(args.warmup):
                        row, _ = run_case(worker, warmup_case, args, trace, warmup=True)
                        warmups.append({"id": row["id"], "status": row["status"], "reason": row["reason"]})
                        if row["status"] == "failed":
                            raise BenchError("warmup_failed:" + row["reason"])
            except BenchError as e:
                terminal_failure = str(e)
                json_line(trace, {"event": "startup_failed", "reason": terminal_failure})
            for case in cases:
                final_text = None
                if terminal_failure:
                    row = not_run(case, terminal_failure)
                else:
                    try:
                        row, final_text = run_case(worker, case, args, trace)
                    except BenchError as e:
                        terminal_failure = str(e)
                        row = not_run(case, terminal_failure)
                    if row["status"] == "failed":
                        terminal_failure = row["reason"]
                rows.append(row)
                if transcripts:
                    json_line(transcripts, {"id": row["id"], "status": row["status"], "text": final_text})
        finally:
            if transcripts:
                transcripts.close()
            if worker:
                code = worker.close(force=bool(terminal_failure or len(rows) != len(cases)))
                if not terminal_failure and code != 0:
                    terminal_failure = "worker_exit_nonzero"
                json_line(trace, {"event": "worker_exit", "returncode": code})
    simulated = manifest["worker"]["simulated"] if manifest["worker"] else None
    report = {"schema_version": 1, "mode": args.mode, "warmup": warmups,
              "run_error": terminal_failure, "summary": summary(rows, args.mode, simulated),
              "cases": rows}
    dump_json(args.output / "results.json", report)
    with (args.output / "cases.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{report['summary']['classification']}: {len(rows)} cas, "
          f"{report['summary']['failed_cases']} échoués, {report['summary']['not_run_cases']} non exécutés")
    return 1 if terminal_failure else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Banc ASR local (Python stdlib) ; ajouter -- suivi de la commande worker.")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--wav-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--partition", action="append", help="Partition à mesurer, dev par défaut ; all = toutes.")
    parser.add_argument("--mode", choices=("realtime", "accelerated"), default="realtime")
    parser.add_argument("--chunk-ms", type=int, default=20)
    parser.add_argument("--startup-timeout-s", type=float, default=30)
    parser.add_argument("--timeout-s", type=float, default=30)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--warmup-wav", type=Path,
                        help="WAV hors validation à utiliser pour l’échauffement, de préférence un cas dev.")
    parser.add_argument("--include-text", action="store_true", help="Conserver les transcriptions finales de test.")
    if "--" in argv:
        split = argv.index("--")
        args = parser.parse_args(argv[:split])
        command = argv[split + 1:]
    else:
        args = parser.parse_args(argv)
        command = []
    if not command:
        parser.error("Commande worker requise après --")
    args.partition = args.partition or ["dev"]
    if "all" in args.partition and len(args.partition) != 1:
        parser.error("Utiliser --partition all seul, ou répéter --partition avec des partitions nommées.")
    if (not 1 <= args.chunk_ms <= 1000 or not 0 <= args.warmup <= 100
            or not all(math.isfinite(value) and value > 0 for value in (
                args.startup_timeout_s, args.timeout_s))):
        parser.error("Bloc entre 1 et 1 000 ms, 0 à 100 échauffements et délais positifs.")
    try:
        return run(args, command)
    except (BenchError, OSError, UnicodeError, csv.Error) as e:
        print(f"Erreur du banc : {e}", file=sys.stderr)
        return 2
