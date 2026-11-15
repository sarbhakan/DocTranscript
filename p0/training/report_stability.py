"""Aggregate the frozen three-arm Px experiment; no references leave this report."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from statistics import median

from p0.bench.scoring import edit_distance, words
from p0.training import score_validation as scorer
from p0.training.prepare_px import safe_artifact, sha256
from p0.training.train_lora import GENERATION, atomic_json, json_digest, private_directory


def read(root: Path, name: str):
    return json.loads(safe_artifact(root, name).read_text(encoding="utf-8"))


def checks(scores: dict):
    result = {f"span:{category}": spans for category, spans in scores["spans"].items()}
    result.update({f"guard:{category}": [value] for category, value in scores["guards"].items()})
    result["association"] = scores["drug_strength_association"]
    if any(type(value) is not bool for values in result.values() for value in values):
        raise ValueError("Type de contrôle critique inattendu")
    return result


def paired(before: list[dict], after: list[dict]) -> dict:
    changes = {key: Counter() for key in ("gains", "losses", "clips_with_gain", "clips_with_loss")}
    for left, right in zip(before, after, strict=True):
        if set(left) != set(right):
            raise ValueError("Profils critiques différents sur le même cas")
        any_gain, any_loss = False, False
        for key, original in left.items():
            values = list(zip(original, right[key], strict=True))
            gains = sum(not previous and current for previous, current in values)
            losses = sum(previous and not current for previous, current in values)
            if gains:
                changes["gains"][key] += gains
                changes["clips_with_gain"][key] += 1
                any_gain = True
            if losses:
                changes["losses"][key] += losses
                changes["clips_with_loss"][key] += 1
                any_loss = True
        if any_gain:
            changes["clips_with_gain"]["any_critical_check"] += 1
        if any_loss:
            changes["clips_with_loss"]["any_critical_check"] += 1
    return {key: dict(values) for key, values in changes.items()}


def measured(rows, cases, key):
    times, transcripts, screens = [], [], []
    score, words_total, eos_total = 0, 0, 0
    totals = {}
    for row, case in zip(rows, cases, strict=True):
        packet = row[key]
        text = packet["text"]
        seconds = packet["inference_seconds"]
        if (not isinstance(text, str) or type(seconds) not in (int, float)
                or not math.isfinite(seconds) or seconds <= 0 or type(packet["eos_present"]) is not bool):
            raise ValueError("Prédiction non conforme")
        actual, reference = words(text), words(case["reference"])
        score += edit_distance(reference, actual)
        words_total += len(reference)
        eos_total += int(packet["eos_present"])
        screen = checks(scorer.score_case(case, text))
        for category, values in screen.items():
            counts = totals.setdefault(category, [0, 0])
            counts[0] += sum(values)
            counts[1] += len(values)
        transcripts.append(text)
        screens.append(screen)
        times.append(seconds)
    return ({"word_errors": score, "reference_words": words_total, "wer": score / words_total,
             "eos": eos_total, "critical": totals, "total_seconds": sum(times), "median_seconds": median(times)},
            transcripts, screens)


def all_paired_outputs_have_eos(summary: dict) -> bool:
    variants, evidence = summary["variants"], summary["arm_evidence"]
    count = summary["clips"]
    return bool(variants) and set(variants) == set(evidence) and all(
        values["eos"] == evidence[key]["paired_base"]["eos"] == count for key, values in variants.items())


def combine(root: Path, grids: Path, *, eos_audit=False) -> dict:
    root = private_directory(root)
    frozen = read(root, "protocol.frozen.json")
    eval_freeze = read(root, "evaluation.frozen.json")
    reporter = sha256(Path(__file__))
    if eos_audit:
        amendment = read(root, "reporter-eos-amendment.json")
        if (amendment["scope"] != "verify EOS in every candidate and base, including the CE replay"
                or amendment["previous_reporter_sha256"] != eval_freeze["reporter_sha256"]
                or amendment["evaluation_freeze_sha256"] != sha256(safe_artifact(root, "evaluation.frozen.json"))
                or amendment["previous_aggregate_sha256"] != sha256(safe_artifact(root, "aggregate-px.json"))
                or amendment["eos_independent_audit_sha256"] != sha256(safe_artifact(root, "eos-independent-audit.json"))):
            raise ValueError("L’amendement post-évaluation ne correspond pas aux observations figées")
        expected_reporter = amendment["amended_reporter_sha256"]
    else:
        expected_reporter = eval_freeze["reporter_sha256"]
    plan = frozen["protocol"]
    expected = json.loads(Path(__file__).with_name("retention_stability_plan.json").read_text(encoding="utf-8"))
    if (plan != expected or eval_freeze["training_freeze_sha256"] != sha256(safe_artifact(root, "protocol.frozen.json"))
            or frozen["prediction_generation_started"] is not False
            or eval_freeze["px_generation_started"] is not False
            or expected_reporter != reporter
            or sha256(Path(scorer.__file__)) != plan["generation"]["grid_scorer_sha256"]):
        raise ValueError("Contrat, code de score ou gel de l’essai différent")
    train_reports, train_contracts, all_reports, completed = {}, {}, {}, []
    common_train, common_state = None, None
    for arm in plan["arms_in_order"]:
        key = arm["id"]
        contract, report = read(root, f"{key}/contract.json"), read(root, f"{key}/report.json")
        if (sha256(safe_artifact(root, f"{key}/report.json")) != eval_freeze["training_reports_sha256"][key]
                or report["contract_sha256"] != json_digest(contract)):
            raise ValueError("Le rapport d’entraînement n’est pas lié au gel")
        grid_match = plan["matching"]
        match = {name: grid_match[name] for name in ("seed", "threads", "device", "dtype", "adamw_backend", "accumulation")}
        match.update(optimizer_updates_planned=grid_match["updates"], peak_learning_rate=grid_match["peak_learning_rate"],
                     validation_rows=grid_match["validation_loss_clips"], max_grad_norm=grid_match["gradient_clip"],
                     epochs_requested=grid_match["epochs"],
                     trainer_source_sha256=frozen["source_sha256"]["p0/training/train_lora.py"],
                     training_rows_sha256=frozen["planned_train_rows_sha256"])
        obj = contract["training_objective"]
        base_contract = {name: value for name, value in contract.items() if name != "training_objective"}
        if (any(contract.get(name) != value for name, value in match.items())
                or any(obj.get(name) != value for name, value in arm.items() if name != "id")
                or (common_train is not None and common_train != base_contract)):
            raise ValueError("Les variantes n’ont pas le même entraînement en dehors de l’objectif")
        common_train = base_contract
        train_reports[key] = {name: report[name] for name in
                              ("status", "actual_optimizer_updates", "elapsed_seconds")}
        if report["status"] != "completed":
            if report["status"] != "failed" or report.get("promoted_to_application") is not False:
                raise ValueError("Statut d’entraînement inattendu")
            continue
        tokens = (report["base_parameters_sha256"], report["adapter_initial_sha256"])
        if (common_state is not None and common_state != tokens
                or report["actual_optimizer_updates"] != grid_match["updates"]
                or report["clips_consumed"] != grid_match["train_clips"]
                or not all(report.get(flag) is True for flag in
                           ("training_performed", "base_weights_unchanged", "adapter_weights_changed", "adapter_reload_exact"))
                or report.get("promoted_to_application") is not False):
            raise ValueError("Provenance ou durée d’entraînement non conforme")
        common_state = tokens
        train_contracts[key] = (contract, report)
        train_reports[key].update({k: report[k] for k in ("clips_consumed", "adapter_final_sha256", "last_validation")})
        events = [json.loads(line) for line in safe_artifact(root, f"{key}/events.jsonl").read_text().splitlines()]
        steps = [event for event in events if event.get("phase") == "train"]
        if ([event["update"] for event in steps] != list(range(1, grid_match["updates"] + 1))
                or sum(event["clips_in_update"] for event in steps) != grid_match["train_clips"]):
            raise ValueError("Trace des étapes incomplète")
        train_reports[key]["mps_driver_peak_observed_bytes"] = max(event.get("mps_driver_allocated_bytes", 0) for event in events)
        train_reports[key]["process_peak_rss_bytes"] = report["process_peak_rss_bytes"]
        drug_events = [event for event in events if event.get("phase") == "drug_weights"]
        if arm["drug_subtoken_weight"] > 1.0:
            declared = frozen["real_tokenizer_preflight"]
            if (len(drug_events) != 1 or drug_events[0]["unique_training_rows"] != declared["rows"]
                    or any(drug_events[0].get(name) != value for name, value in declared.items() if name != "rows")):
                    raise ValueError("Pondération des médicaments différente du masque gelé")
            train_reports[key]["drug_weights"] = {name: value for name, value in drug_events[0].items() if name != "phase"}
        elif drug_events:
            raise ValueError("Poids médicament inattendus dans un témoin")
        completed.append(key)

    selected_sets = []
    for window in plan["generation"]["windows_in_order"]:
        name, count = window["id"], window["count"]
        grid_path = safe_artifact(grids, f"critical-v2-r2-{count}.json")
        if sha256(grid_path) != window["grid_sha256"]:
            raise ValueError("Grille non conforme au gel")
        grid = json.loads(grid_path.read_text(encoding="utf-8"))
        cases = grid["cases"]
        ids = [case["id"] for case in cases]
        if (len(ids) != len(set(ids)) or len(ids) != count or grid["selection_offset"] != window["offset"]
                or grid["selection_sha256"] != json_digest(ids)
                or grid["scoring_code_sha256"] != scorer.scoring_code_hashes()
                or grid["predictions_used_to_prepare"] is not False):
            raise ValueError("Grille et sélection incompatibles")
        selected_sets.append(set(ids))
        base_transcripts, screen_sets, method_scores, arm_evidence = None, {}, {}, {}
        disagreement = {}
        for key in completed:
            eval_prefix = f"eval-{key}-{name}"
            p = safe_artifact(root, f"{eval_prefix}/predictions.local.jsonl")
            contract = read(root, f"{eval_prefix}/contract.json")
            report = read(root, f"{eval_prefix}/report.json")
            tc, tr = train_contracts[key]
            if (contract["manifest_sha256"] != tc["manifest_sha256"]
                    or any(contract.get(field) != tc[field] for field in ("base", "device", "dtype", "versions", "seed"))
                    or contract["generation"] != GENERATION or contract["adapter"]["contract_sha256"] != tr["contract_sha256"]
                    or contract["adapter"]["adapter_parameters_sha256"] != tr["adapter_final_sha256"]
                    or contract["selected_rows_sha256"] != grid["selection_sha256"]
                    or contract["validation_offset"] != window["offset"] or contract["selected_clips"] != count
                    or contract.get("return_dict_in_generate") is not True
                    or contract.get("references_never_passed_to_generate") is not True
                    or report.get("paired_same_audio") is not True or report.get("status") != "completed"
                    or report["contract_sha256"] != json_digest(contract)):
                raise ValueError("Contrat de génération incompatible")
            rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
            if (len(rows) != count or any(any(row[k] != item[k] for k in ("id", "speaker_id", "reference"))
                                          for row, item in zip(rows, cases, strict=True))):
                raise ValueError("Prédictions et références non appariées")
            base_scores, transcripts, base_screens = measured(rows, cases, "base")
            candidate, _, candidate_screens = measured(rows, cases, "adapter")
            prior_base = base_transcripts if base_transcripts is not None else transcripts
            disagreement[key] = sum(before != after for before, after in zip(prior_base, transcripts, strict=True))
            if base_transcripts is None:
                base_transcripts = transcripts
            arm_evidence[key] = {"paired_base": base_scores, "predictions_sha256": sha256(p),
                                 "changes_vs_base": paired(base_screens, candidate_screens),
                                 "ratio_total_seconds_vs_base": candidate["total_seconds"] / base_scores["total_seconds"],
                                 "ratio_median_seconds_vs_base": candidate["median_seconds"] / base_scores["median_seconds"]}
            screen_sets[key], method_scores[key] = candidate_screens, candidate
        for key in completed:
            if "ce24" in screen_sets and key != "ce24":
                arm_evidence[key]["changes_vs_ce24"] = paired(screen_sets["ce24"], screen_sets[key])
        all_reports[name] = {"clips": count, "speakers": len({case["speaker_id"] for case in cases}),
                             "scoring_grid_sha256": window["grid_sha256"], "coverage": grid["coverage"],
                             "unlinked_source_strengths": grid["unlinked_source_strengths"], "variants": method_scores,
                             "baseline_text_differences": disagreement, "arm_evidence": arm_evidence}
    if selected_sets[0] & selected_sets[1]:
        raise ValueError("Les fenêtres de développement se superposent")
    gates = {}
    for arm in (key for key in completed if key != "ce24"):
        gates[arm] = {}
        for name, summary in all_reports.items():
            evidence = summary["arm_evidence"][arm]
            score = summary["variants"][arm]
            base = evidence["paired_base"]
            ce = summary["variants"].get("ce24")
            gates[arm][name] = {
                "baseline_replayed_identically": not any(summary["baseline_text_differences"].values()),
                "no_critical_loss_vs_base": not evidence["changes_vs_base"]["losses"],
                "no_critical_loss_vs_ce": ce is not None and not evidence["changes_vs_ce24"]["losses"],
                "each_output_has_eos": bool(ce) and all_paired_outputs_have_eos(summary),
                "time_ratio_within_110_percent": max(evidence["ratio_total_seconds_vs_base"],
                                                     evidence["ratio_median_seconds_vs_base"]) <= 1.10,
            }
            if name == "additional64":
                gates[arm][name].update({
                    "fewer_words_wrong_than_base_and_ce": bool(ce) and score["word_errors"] < min(base["word_errors"], ce["word_errors"]),
                    "more_drug_mentions_than_base_and_ce": bool(ce) and score["critical"]["span:drug"][0] > max(
                        base["critical"]["span:drug"][0], ce["critical"]["span:drug"][0]),
                })
    return {"schema": 1, "experiment": plan["experiment"], "training": train_reports, "windows": all_reports,
            "gates": gates, "passes_px_screen": [key for key, groups in gates.items() if all(all(values.values()) for values in groups.values())],
            "complete_three_arm_comparison": len(completed) == 3, "product_model_changed": False,
            "no_reserve_generation_or_scoring": True, "exported": False, "mac_fp16_research_only": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--grids", required=True, type=Path)
    parser.add_argument("--eos-audit", action="store_true", help="Rendre l’audit EOS sans écraser le rapport initial")
    args = parser.parse_args()
    try:
        result = combine(args.directory, args.grids, eos_audit=args.eos_audit)
        output = args.directory / ("aggregate-px-eos-audited.json" if args.eos_audit else "aggregate-px.json")
        if output.exists() or output.is_symlink():
            raise ValueError("Un rapport existe déjà")
        atomic_json(output, result)
        print(json.dumps({"passes_px_screen": result["passes_px_screen"],
                          "comparison_completed": result["complete_three_arm_comparison"]}, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Agrégation refusée : {error}\n")


if __name__ == "__main__":
    main()
