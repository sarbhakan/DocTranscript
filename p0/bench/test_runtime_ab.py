"""Regression checks for pairing and redaction, without ASR weights."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from p0.windows.runtime_ab import (
    BASELINE, CANDIDATE, CONTROL_ID, WARMUP_ID, attach_fingerprints, execution_orders, fixtures, paired_summary,
)
from p0.windows.runtime_ab_build import BRIDGE, PAUSE, SILERO_PAUSE, benchmark_bridge, stage_probe


class RuntimeAB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clips = fixtures()

    def synthetic_trial(self):
        # Scorer harness only: deliberately return references, not ASR output.
        rows = [{"id": key, "text": case["reference"] if case else "",
                 "speech_seconds": len(pcm) / 32_000, "replay_ms": 110,
                 "segments": [{"frames": 1024, "pcm_fnv1a64": "f" * 16, "phase": "stop", "feed_end_ms": None,
                               "decode_ms": 100}] if case else []}
                for key, (case, pcm) in self.clips.items()]
        arm = {"cold": {"rows": rows[:1], "process_wall_ms": 160, "initialize_ms": 50},
               "warm": {"rows": rows, "process_wall_ms": 410, "initialize_ms": 50}}
        return {BASELINE: deepcopy(arm), CANDIDATE: deepcopy(arm)}

    def test_order_and_full_public_fixtures(self):
        self.assertEqual(execution_orders(4), [(BASELINE, CANDIDATE), (CANDIDATE, BASELINE)] * 2)
        self.assertEqual(set(self.clips), {WARMUP_ID, "px-23", "px-584", CONTROL_ID})
        self.assertEqual(self.clips[WARMUP_ID][0]["frames"], len(self.clips[WARMUP_ID][1]) // 2)
        self.assertEqual(set(self.clips[CONTROL_ID][1]), {0})

    def test_version_guard_only_and_probe_staging(self):
        source = BRIDGE.read_bytes()
        candidate = benchmark_bridge(source, CANDIDATE)
        self.assertEqual(benchmark_bridge(source, BASELINE), source)
        self.assertEqual(candidate.replace(b'"1.9.5"', b'"1.8.5"'), source)
        with self.assertRaises(ValueError):
            benchmark_bridge(b"missing guard", CANDIDATE)
        with TemporaryDirectory() as folder:
            tree = Path(folder)
            stage_probe(tree, CANDIDATE)
            for header in (PAUSE, SILERO_PAUSE):
                self.assertEqual((tree / "nv-probe/macos/native" / header.name).read_bytes(), header.read_bytes())

    def test_backend_and_pcm_are_required(self):
        rows = [{"segments": [{"frames": 1024}]}]
        backend = "nv_accel backend=BLAS\r\n"
        segment = "nv_segment frames=1024 pcm_fnv1a64=9ff91b227cc8a457\r\n"
        for wrong in ("", backend, segment, backend + segment * 2,
                      backend + segment.replace("1024", "1025")):
            with self.subTest(log_length=len(wrong)):
                with self.assertRaises(ValueError):
                    attach_fingerprints(deepcopy(rows), wrong)
        attach_fingerprints(rows, backend + segment)
        self.assertEqual(rows[0]["segments"][0]["pcm_fnv1a64"], "9ff91b227cc8a457")

    def test_result_distinguishes_slowdown_regression_and_instability(self):
        data = [self.synthetic_trial(), self.synthetic_trial()]
        fraction = data[0][CANDIDATE]["warm"]["rows"][2]
        fraction["text"] = "80 mg le matin, pas le soir pendant 2 mois; NE_PAS_PUBLIER"
        fraction["segments"][0]["pcm_fnv1a64"] = "1" * 16
        fraction["segments"][0]["decode_ms"] = 120
        result = paired_summary(data, self.clips)
        changed = next(row for row in result["pair_checks"] if row["regressions"])
        self.assertEqual(changed["id"], "px-584")
        self.assertTrue({"critical:fraction", "terms", "no_added_negation"} <= set(changed["regressions"]))
        self.assertFalse(changed["same_pcm_and_pauses"])
        self.assertFalse(result["public_screen"]["qualified_for_release"])
        self.assertFalse(result["public_screen"]["warm_segment_p95_not_worse"])
        self.assertIn({"runtime": CANDIDATE, "id": "px-584"}, result["unstable_cases"])
        self.assertNotIn("NE_PAS_PUBLIER", json.dumps(result))
        self.assertNotIn('"text":', json.dumps(result))

    def test_same_average_does_not_hide_missing_fixture(self):
        data = [self.synthetic_trial()]
        data[0][BASELINE]["warm"]["rows"].pop(1)
        data[0][CANDIDATE]["warm"]["rows"].pop(1)
        with self.assertRaises(ValueError):
            paired_summary(data, self.clips)
