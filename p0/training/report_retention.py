"""Combine the predeclared LoRA retention A/B reports without exposing texts."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

from p0.training.prepare_px import safe_artifact, sha256
from p0.training.train_lora import GENERATION, SELECTION_KEY, atomic_json, json_digest, private_directory


ARMS = {"ce50": 0.0, "kl50": 0.35}
WINDOWS = {"historical32": (0, 32), "additional64": (32, 64)}


def load(root: Path, name: str):
    return json.loads(safe_artifact(root, name).read_text(encoding="utf-8"))


def positive_seconds(row: dict, method: str) -> float:
    seconds = row[method]["inference_seconds"]
    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Mesure de génération invalide")
    return seconds


def combine(root: Path) -> dict:
    root = private_directory(root)
    plan_path = safe_artifact(root, "plan.frozen.json")
    expected_plan = Path(__file__).with_name("retention_experiment_plan.json")
    if sha256(plan_path) != sha256(expected_plan):
        raise ValueError("Le plan gelé ne correspond pas au plan publié")
    freeze = load(root, "evaluation-freeze.json")
    if set(freeze["grid_sha256"]) != set(WINDOWS) or set(freeze["windows"]) != set(WINDOWS):
        raise ValueError("Il faut les deux grilles et sélections gelées")
    for window, (offset, count) in WINDOWS.items():
        frozen = freeze["windows"][window]
        if (frozen.get("count") != count or frozen.get("offset") != offset
                or frozen.get("sha256") != freeze["grid_sha256"][window]):
            raise ValueError("Fenêtre différente du gel des grilles")
    training, evaluations, baselines, row_ids, failed = {}, {}, {}, {}, {}
    common_training_contract = None
    common_start = None
    for arm, weight in ARMS.items():
        contract = load(root, f"{arm}/contract.json")
        result = load(root, f"{arm}/report.json")
        objective = contract["training_objective"]
        if (contract.get("optimizer_updates_planned") != 50 or contract.get("accumulation") != 4
                or contract.get("seed") != 20261114 or contract.get("peak_learning_rate") != 1e-4
                or contract.get("device") != "mps" or contract.get("dtype") != "float16"
                or objective.get("cross_entropy_weight") != 1.0 or objective.get("base_retention_kl_weight") != weight):
            raise ValueError("Contrat d’entraînement non conforme au plan")
        comparable = {key: value for key, value in contract.items() if key != "training_objective"}
        if common_training_contract is not None and comparable != common_training_contract:
            raise ValueError("Contrats des bras différents en dehors de l’objectif")
        common_training_contract = comparable
        if result.get("status") == "failed":
            updates = result.get("actual_optimizer_updates")
            if (type(updates) is not int or not 0 <= updates <= 50
                    or result.get("promoted_to_application") is not False
                    or ("contract_sha256" in result and result["contract_sha256"] != json_digest(contract))
                    or any((root / f"eval-{arm}-{window}").exists() for window in WINDOWS)):
                raise ValueError("Un bras interrompu ne doit pas être évalué")
            failed[arm] = {"status": "failed", "actual_optimizer_updates": updates,
                           "elapsed_seconds": result["elapsed_seconds"], "checkpoint_evaluated": False,
                           "failure_report_contains_contract_sha256": "contract_sha256" in result}
            continue
        if (result.get("status") != "completed" or result.get("contract_sha256") != json_digest(contract)
                or result.get("actual_optimizer_updates") != 50 or result.get("clips_consumed") != 200
                or not all(result.get(flag) is True for flag in
                           ("training_performed", "base_weights_unchanged", "adapter_weights_changed", "adapter_reload_exact"))
                or result.get("promoted_to_application") is not False):
            raise ValueError("Essai d’entraînement incomplet ou non conforme")
        start = (result["base_parameters_sha256"], result["adapter_initial_sha256"])
        if common_start is not None and start != common_start:
            raise ValueError("Les bras n’ont pas la même initialisation")
        common_start = start
        events = [json.loads(line) for line in
                  safe_artifact(root, f"{arm}/events.jsonl").read_text(encoding="utf-8").splitlines()]
        updates = [event for event in events if event.get("phase") == "train"]
        if [item["update"] for item in updates] != list(range(1, 51)) or sum(
                item["clips_in_update"] for item in updates) != 200:
            raise ValueError("Trace incomplète des mises à jour")
        kl_values = [item["mean_clip_base_retention_kl"] for item in updates
                     if "mean_clip_base_retention_kl" in item]
        if weight:
            if len(kl_values) != 50 or not all(math.isfinite(number) for number in kl_values) or max(kl_values) <= 0:
                raise ValueError("Trace incomplète de la perte KL")
        elif kl_values:
            raise ValueError("Une perte KL apparaît dans le bras témoin")
        training[arm] = {key: result[key] for key in
                         ("actual_optimizer_updates", "clips_consumed", "elapsed_seconds",
                          "base_weights_unchanged", "adapter_reload_exact", "adapter_final_sha256",
                          "last_validation")}
        training[arm]["mps_driver_peak_observed_bytes"] = max(
            event.get("mps_driver_allocated_bytes", 0) for event in events)
        training[arm]["process_peak_rss_bytes"] = result["process_peak_rss_bytes"]
        training[arm]["base_retention_kl_weight"] = weight
        if kl_values:
            training[arm]["mean_kl_by_update"] = sum(kl_values) / len(kl_values)
        for window, (offset, count) in WINDOWS.items():
            eval_prefix = f"eval-{arm}-{window}"
            score_prefix = f"critical-{arm}-{window}"
            eval_contract = load(root, f"{eval_prefix}/contract.json")
            report = load(root, f"{eval_prefix}/report.json")
            critical = load(root, f"{score_prefix}/report.json")
            path = safe_artifact(root, f"{eval_prefix}/predictions.local.jsonl")
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            ids = [row["id"] for row in rows]
            selected_sha256 = json_digest(ids)
            if (any(eval_contract.get(key) != contract[key] for key in ("base", "device", "dtype", "seed", "versions"))
                    or eval_contract.get("generation") != GENERATION
                    or eval_contract.get("validation_selection_key") != SELECTION_KEY
                    or eval_contract.get("references_never_passed_to_generate") is not True
                    or eval_contract.get("return_dict_in_generate") is not True):
                raise ValueError("Contrat de génération différent du protocole")
            if (len(rows) != count or len(set(ids)) != count or eval_contract.get("validation_offset") != offset
                    or eval_contract.get("selected_rows_sha256") != selected_sha256
                    or freeze["windows"][window].get("selected_sha256") != selected_sha256
                    or eval_contract.get("adapter", {}).get("adapter_parameters_sha256") != result["adapter_final_sha256"]
                    or eval_contract.get("adapter", {}).get("contract_sha256") != result["contract_sha256"]
                    or report.get("status") != "completed" or report.get("contract_sha256") != json_digest(eval_contract)
                    or report.get("paired_same_audio") is not True or critical.get("clips") != count
                    or eval_contract.get("selected_clips") != count or report.get("selected_clips") != count
                    or report.get("selected_speakers") != eval_contract.get("selected_speakers")
                    or eval_contract.get("manifest_sha256") != contract["manifest_sha256"]
                    or critical.get("predictions_sha256") != sha256(path)
                    or critical.get("grid_sha256") != freeze["grid_sha256"][window]):
                raise ValueError("Comparaison, grille ou prédictions ne correspondent pas")
            if window in row_ids and ids != row_ids[window]:
                raise ValueError("Les variantes n’utilisent pas les mêmes audios")
            row_ids[window] = ids
            baselines[(arm, window)] = [row["base"]["text"] for row in rows]
            times = {method: [positive_seconds(row, method) for row in rows] for method in ("base", "adapter")}
            eos = {method: sum(row[method].get("eos_present") is True for row in rows) for method in times}
            stats = {"total_ratio": sum(times["adapter"]) / sum(times["base"]),
                     "median_ratio": median(times["adapter"]) / median(times["base"])}
            scores = report["scores"]
            regressions = critical["paired"]["regressions"]
            improvements = critical["paired"]["improvements"]
            checks = {"no_scored_regression": not any(regressions.values()), "all_eos": min(eos.values()) == count,
                      "time_total_and_median": max(stats.values()) <= 1.10}
            if window == "additional64":
                checks.update({"word_error_gain": scores["adapter"]["word_errors"] < scores["base"]["word_errors"],
                               "drug_gain": improvements.get("span:drug", 0) > 0 and not regressions.get("span:drug", 0)})
            evaluations.setdefault(arm, {})[window] = {
                "clips": count, "speakers": report["selected_speakers"], "coverage": critical["coverage"],
                "scores": scores, "paired": critical["paired"], "eos_observed": eos,
                "time_ratios": stats, "automatic_checks": checks,
                "critical_scores": critical["scores"],
                "unobserved_categories": critical["unobserved_categories"],
                "unlinked_source_strengths": critical["unlinked_source_strengths"],
                "paired_affected_clips": critical["paired_affected_clips"],
                "grid_sha256": critical["grid_sha256"], "predictions_sha256": critical["predictions_sha256"],
            }
    if set(row_ids.get("historical32", [])) & set(row_ids.get("additional64", [])):
        raise ValueError("Les clips des deux fenêtres se superposent")
    complete = not failed
    base_differences = {window: sum(x != y for x, y in
                        zip(baselines[("ce50", window)], baselines[("kl50", window)], strict=True))
                        for window in WINDOWS} if complete else None
    eligible = [arm for arm, values in evaluations.items()
                if all(all(item["automatic_checks"].values()) for item in values.values())]
    admissible = complete and not any(base_differences.values())
    return {
        "schema": 1, "experiment": "px-retention-ce-kl-50", "plan_sha256": sha256(plan_path),
        "evaluation_freeze_sha256": sha256(safe_artifact(root, "evaluation-freeze.json")),
        "training": training, "failed_arms": failed, "evaluations": evaluations, "paired_treatment_comparison_complete": complete,
        "paired_baseline_text_differences": base_differences,
        "passes_automatic_checks_before_review": admissible and bool(eligible),
        "eligible_arms_before_manual_review": eligible if admissible else [],
        "manual_review_and_independent_confirmation_required": True,
        "promoted_to_application": False, "export_performed": False,
        "limits": "Development clips only; no reserve, new voices, Windows or Q5_0 evaluated here.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = combine(args.directory)
        path = args.directory / "aggregate-report.json"
        if path.exists() or path.is_symlink():
            raise ValueError("Un rapport agrégé existe déjà")
        atomic_json(path, report)
        print(json.dumps({"eligible": report["eligible_arms_before_manual_review"],
                          "baseline_differences": report["paired_baseline_text_differences"],
                          "published_or_exported": False}, sort_keys=True))
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"Comparaison refusée : {error}\n")


if __name__ == "__main__":
    main()
