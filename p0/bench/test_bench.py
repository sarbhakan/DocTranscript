"""Tests du banc avec fixtures en mémoire et processus simulé."""

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

from .scoring import edit_distance, nearest_rank, words


class ScoringTest(unittest.TestCase):
    def test_normalization_and_edit_distance(self):
        self.assertEqual(words("L’ŒIL : 2,5 mg, pas 25 mg."), ["l'œil", "2.5", "mg", "pas", "25", "mg"])
        self.assertEqual(edit_distance(words("2,5 mg, pas à droite"), words("25 mg, à gauche")), 3)

    def test_percentile_counts_failures(self):
        self.assertEqual(nearest_rank([3, 4, None]), {
            "status": "failed_percentile", "value": None, "n": 3, "failures": 1,
        })
        self.assertEqual(nearest_rank([3] * 19 + [None]), {
            "status": "measured", "value": 3, "n": 20, "failures": 1,
        })
        self.assertEqual(nearest_rank([])["status"], "not_applicable")


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.table = self.path / "corpus.csv"
        self.output = self.path / "out"
        with self.table.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(("id", "partition", "kind", "reference", "speech_start_ms", "speech_end_ms"))
            w.writerow(("s1", "dev", "speech", "Texte simulé.", 0, 140))
            w.writerow(("c1", "dev", "silence", "", "", ""))
            w.writerow(("s2", "confirm", "speech", "Texte simulé.", 0, 140))
        for name in ("s1", "s2", "c1"):
            self.write_wav(name, amplitude=1 if name == "s2" else 0)

    def write_wav(self, name, amplitude=0, frames=2_560):
        path = self.path / f"{name}.wav"
        with wave.open(str(path), "wb") as f:
            f.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
            f.writeframes(bytes((amplitude, 0)) * frames)
        return path

    def run_bench(self, mode="realtime", behavior="ok", extra=()):
        return subprocess.run(
            [sys.executable, "-m", "p0.bench", "--cases", str(self.table),
             "--wav-dir", str(self.path), "--output", str(self.output), "--mode", mode,
             *extra, "--", sys.executable, "-m", "p0.bench.fake_worker", "--behavior", behavior],
            capture_output=True, text=True, timeout=15,
        )

    def report(self):
        return json.loads((self.output / "results.json").read_text(encoding="utf-8"))

    def test_persistent_worker_and_artifacts(self):
        run = self.run_bench()
        self.assertEqual(run.returncode, 0, run.stderr)
        result = self.report()
        self.assertEqual(result["summary"]["classification"], "simulation_only")
        self.assertEqual(result["summary"]["wer"], 0)
        self.assertEqual(result["summary"]["p95_first_correct_from_speech_start_ms"]["status"], "measured")
        self.assertEqual(result["summary"]["controls_with_nonempty_hypotheses"], 1)
        self.assertEqual(result["warmup"][0]["id"], "s1")
        self.assertEqual(result["cases"][0]["audio_chunks"], 8)
        self.assertFalse((self.output / "transcripts.ndjson").exists())
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["cases"][0]["wav_sha256"],
                         hashlib.sha256((self.path / "s1.wav").read_bytes()).hexdigest())
        for name in ("manifest.json", "results.json", "cases.csv", "trace.ndjson"):
            self.assertNotIn("Texte simul", (self.output / name).read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (self.output / "trace.ndjson").read_text().splitlines()]
        self.assertEqual(sum(event["event"] == "ready" for event in events), 1)

    def test_accelerated_and_explicit_transcripts(self):
        run = self.run_bench(mode="accelerated", extra=("--include-text", "--warmup", "0"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.report()["summary"]["p95_rtf_accelerated"]["status"], "measured")
        self.assertEqual(self.report()["summary"]["p95_final_from_speech_end_ms"]["status"], "not_applicable")
        lines = (self.output / "transcripts.ndjson").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0]), {"id": "s1", "status": "ok", "text": "Texte simulé."})

    def test_silent_speech_is_a_latency_failure_and_word_deletion(self):
        run = self.run_bench(behavior="silent", extra=("--warmup", "0"))
        self.assertEqual(run.returncode, 0, run.stderr)
        result = self.report()["summary"]
        self.assertEqual(result["wer"], 1)
        self.assertEqual(result["p95_first_correct_from_speech_start_ms"]["status"], "failed_percentile")
        self.assertEqual(result["p95_final_from_speech_end_ms"]["failures"], 1)

    def test_timeout_records_remaining_cases(self):
        run = self.run_bench(behavior="stall", extra=("--timeout-s", "0.25", "--warmup", "0"))
        self.assertEqual(run.returncode, 1, run.stderr)
        result = self.report()
        self.assertEqual(result["run_error"], "timeout")
        self.assertEqual([case["status"] for case in result["cases"]], ["failed", "not_run"])
        self.assertEqual(result["summary"]["p95_first_correct_from_speech_start_ms"]["failures"], 1)

    def test_timeout_worker_not_reading_stdin(self):
        self.write_wav("s1", frames=160_000)
        run = self.run_bench(mode="accelerated", behavior="no-read",
                             extra=("--timeout-s", "0.25", "--warmup", "0"))
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(self.report()["run_error"], "timeout")

    def test_startup_timeout(self):
        run = self.run_bench(behavior="startup-stall", extra=("--startup-timeout-s", "0.3"))
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(self.report()["summary"]["not_run_cases"], 2)
        self.assertEqual(self.report()["summary"]["classification"], "no_engine_result")

    def test_bad_finalization(self):
        run = self.run_bench(behavior="bad-done", extra=("--warmup", "0"))
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(self.report()["run_error"], "missing_final")

    def test_optional_artifact_preserves_observed_final_without_done(self):
        run = self.run_bench(mode="accelerated", behavior="no-done", extra=("--warmup", "0", "--include-text"))
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(self.report()["summary"]["wer"], 1)
        lines = (self.output / "transcripts.ndjson").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0]), {"id": "s1", "status": "failed", "text": "Texte simulé."})

    def test_confirmation_is_not_used_for_warmup(self):
        run = self.run_bench(mode="accelerated", extra=("--partition", "confirm"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.report()["warmup"], [])
        self.assertEqual([case["id"] for case in self.report()["cases"]], ["s2"])

    def test_confirmation_accepts_explicit_development_wav(self):
        run = self.run_bench(mode="accelerated", extra=("--partition", "confirm",
                                                       "--warmup-wav", str(self.path / "s1.wav")))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.report()["warmup"][0]["id"], "benchmark_warmup")

    def test_confirmation_rejects_identical_warmup_wav(self):
        run = self.run_bench(mode="accelerated", extra=("--partition", "confirm",
                                                       "--warmup-wav", str(self.path / "s2.wav")))
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
