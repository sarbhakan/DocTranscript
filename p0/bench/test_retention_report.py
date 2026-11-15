"""Development gate checks on synthetic reports, no model or audio."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from p0.training import report_retention as runner


class RetentionReportTests(unittest.TestCase):
    def build_tree(self, root, regressions=None, changed_base=False):
        def write(name, contents):
            target = root / name
            target.parent.mkdir(exist_ok=True, parents=True)
            target.write_text(json.dumps(contents), encoding="utf-8")
        plan = Path(runner.__file__).with_name("retention_experiment_plan.json")
        shutil.copyfile(plan, root / "plan.frozen.json")
        grid = {name: f"fictitious-{name}" for name in runner.WINDOWS}
        write("evaluation-freeze.json", {"grid_sha256": grid, "windows": {
            name: {"offset": offset, "count": count, "sha256": grid[name],
                   "selected_sha256": runner.json_digest(list(range(offset, offset + count)))}
            for name, (offset, count) in runner.WINDOWS.items()}})
        for arm, weight in runner.ARMS.items():
            contract = {"optimizer_updates_planned": 50, "accumulation": 4, "seed": 20261114,
                        "peak_learning_rate": 1e-4, "device": "mps", "dtype": "float16",
                        "base": {"fictitious_source": "same"}, "versions": {"torch": "fictitious"},
                        "manifest_sha256": {"train": "t", "validation": "v"},
                        "training_objective": {"cross_entropy_weight": 1, "base_retention_kl_weight": weight}}
            write(f"{arm}/contract.json", contract)
            write(f"{arm}/report.json", {
                "status": "completed", "contract_sha256": runner.json_digest(contract),
                "actual_optimizer_updates": 50, "clips_consumed": 200, "training_performed": True,
                "base_weights_unchanged": True, "adapter_weights_changed": True, "adapter_reload_exact": True,
                "base_parameters_sha256": "base", "adapter_initial_sha256": "init", "adapter_final_sha256": arm,
                "promoted_to_application": False, "elapsed_seconds": 1, "last_validation": {},
                "process_peak_rss_bytes": 1})
            events = []
            for update in range(1, 51):
                entry = {"phase": "train", "update": update, "clips_in_update": 4}
                if weight:
                    entry["mean_clip_base_retention_kl"] = 0.2
                events.append(entry)
            (root / arm / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events))
            for window, (offset, count) in runner.WINDOWS.items():
                prefix = f"eval-{arm}-{window}"
                ids = list(range(offset, offset + count))
                evaluation = {**{key: contract[key] for key in ("base", "device", "dtype", "seed", "versions")},
                              "generation": runner.GENERATION, "validation_selection_key": runner.SELECTION_KEY,
                              "references_never_passed_to_generate": True, "return_dict_in_generate": True,
                              "adapter": {"adapter_parameters_sha256": arm,
                                          "contract_sha256": runner.json_digest(contract)}, "validation_offset": offset,
                              "selected_clips": count, "selected_speakers": 8,
                              "selected_rows_sha256": runner.json_digest(ids),
                              "manifest_sha256": contract["manifest_sha256"]}
                write(f"{prefix}/contract.json", evaluation)
                write(f"{prefix}/report.json", {
                    "status": "completed", "paired_same_audio": True, "selected_speakers": 8, "selected_clips": count,
                    "contract_sha256": runner.json_digest(evaluation),
                    "scores": {"base": {"word_errors": 10}, "adapter": {"word_errors": 1}}})
                pred = root / prefix / "predictions.local.jsonl"
                measures = {"inference_seconds": 2, "eos_present": True}
                pred.write_text("".join(json.dumps(
                    {"id": index, "base": {**measures, "text": "TEMOIN_SECRET_A" if changed_base and arm == "kl50"
                                           and index == 35 else "TEMOIN_SECRET_B"},
                     "adapter": {**measures, "text": "PREDICTION_SECRETE"}}) + "\n" for index in ids))
                write(f"critical-{arm}-{window}/report.json", {
                    "clips": count, "predictions_sha256": runner.sha256(pred), "grid_sha256": grid[window],
                    "paired": {"improvements": {"span:drug": 4},
                               "regressions": regressions if regressions and arm == "ce50"
                               and window == "additional64" else {}}, "coverage": {},
                    "paired_affected_clips": {}, "unobserved_categories": [], "unlinked_source_strengths": 0,
                    "scores": {"base": {"spans": {"drug": [8, 12]}},
                               "adapter": {"spans": {"drug": [12, 12]}}}})

    def test_regression_overrides_better_words_and_report_contains_no_predictions(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.build_tree(root, {"association": 1})
            report = runner.combine(root)
            self.assertEqual(report["eligible_arms_before_manual_review"], ["kl50"])
            self.assertFalse(report["promoted_to_application"])
            self.assertNotIn("SECRET", json.dumps(report))

    def test_disagreeing_base_transcripts_block_treatment_attribution(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.build_tree(root, changed_base=True)
            report = runner.combine(root)
            self.assertEqual(report["paired_baseline_text_differences"], {"historical32": 0, "additional64": 1})
            self.assertEqual(report["eligible_arms_before_manual_review"], [])

    def test_changed_predictions_refuse_the_stale_score(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.build_tree(root)
            pred = root / "eval-kl50-additional64" / "predictions.local.jsonl"
            pred.write_text(pred.read_text().replace("PREDICTION_SECRETE", "MODIFIED"))
            with self.assertRaisesRegex(ValueError, "ne correspondent pas"):
                runner.combine(root)

    def test_selected_audio_is_bound_to_prefixed_freeze(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.build_tree(root)
            path = root / "evaluation-freeze.json"
            freeze = json.loads(path.read_text())
            freeze["windows"]["additional64"]["selected_sha256"] = "different"
            path.write_text(json.dumps(freeze))
            with self.assertRaisesRegex(ValueError, "ne correspondent pas"):
                runner.combine(root)

    def test_rehashed_contract_cannot_replace_the_generation_settings(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.build_tree(root)
            evaluation = root / "eval-ce50-historical32"
            contract_path, report_path = (evaluation / name for name in ("contract.json", "report.json"))
            contract, report = (json.loads(file.read_text()) for file in (contract_path, report_path))
            contract["generation"]["num_beams"] = 5
            report["contract_sha256"] = runner.json_digest(contract)
            contract_path.write_text(json.dumps(contract))
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "Contrat de génération"):
                runner.combine(root)

    def test_single_finished_arm_stays_descriptive(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.build_tree(root)
            (root / "kl50/report.json").write_text(json.dumps(
                {"status": "failed", "actual_optimizer_updates": 2,
                 "elapsed_seconds": 14, "promoted_to_application": False}))
            for window in runner.WINDOWS:
                shutil.rmtree(root / f"eval-kl50-{window}")
                shutil.rmtree(root / f"critical-kl50-{window}")
            report = runner.combine(root)
            self.assertFalse(report["paired_treatment_comparison_complete"])
            self.assertEqual(report["failed_arms"]["kl50"]["actual_optimizer_updates"], 2)
            self.assertFalse(report["failed_arms"]["kl50"]["failure_report_contains_contract_sha256"])
            self.assertTrue(report["evaluations"]["ce50"]["additional64"]["automatic_checks"]["drug_gain"])
            self.assertEqual(report["evaluations"]["ce50"]["additional64"]["critical_scores"]
                             ["base"]["spans"]["drug"], [8, 12])
            self.assertEqual(report["eligible_arms_before_manual_review"], [])


if __name__ == "__main__":
    unittest.main()
