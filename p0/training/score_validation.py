"""Predeclare source-derived medical screens for the 32 development clips.

These conservative string/quantity screens are not a prescription validator.
They never edit transcripts and cannot establish clinical safety or broad
specialty coverage. References, annotations and per-case output stay private.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from p0.lexicon_ab import critical_words, matches
from p0.review.px_paired import (
    CLAUSE, LOCAL_LINKS, NEGATION, UNITS, no_accents, positions, quantities, scalar, spans, tokens,
)
from p0.training.prepare_px import PX_PATH, PX_SHA256, locked_archive, safe_artifact, sha256, verify_export
from p0.training.train_lora import REPO, SELECTION_KEY, atomic_json, json_digest, validation_selection


CATEGORIES = ("drug", "value", "unit", "dose", "fraction", "frequency", "duration",
              "administration_time", "condition", "negation", "delay")
NUMBER = re.compile(r"\d+(?:[,.]\d+)?|[¼½¾]")
TIME = {"matin", "midi", "soir"}
COUNT_UNITS = {"comprimé", "capsule", "gélule", "sachet", "bouffée", "prise", "dose", "fois"}
SINGULAR = {word + "s": word for word in COUNT_UNITS | {"jour", "semaine", "heure", "minute", "repas"}
            if not word.endswith("s")}
UNIT_SCREEN = COUNT_UNITS | {"mg", "g", "μg", "ml", "l", "kg", "ui", "%", "jour", "semaine", "mois", "heure", "minute"}
CONCENTRATION = re.compile(r"\b(?:mg|g|µg|μg|mcg|milligrammes?|grammes?|microgrammes?)\s*"
                           r"(?:[/⁄∕／]|par\s+(?:ml|l|kg|g|millilitres?|litres?|kilogrammes?|grammes?|doses?|comprimés?|gélules?)\b)", re.IGNORECASE)
NUMERIC_KINDS = {"d_dos_val", "dos_val", "dur_val", "rhythm_perday", "freq_int_v1", "freq_int_v2", "min_gap_val"}


def medical_words(text):
    values = [SINGULAR.get(value, value) for value in critical_words(text)]
    values = ["g" if value in {"gramme", "grammes"} else value for value in values]
    values = ["1" if value == "une" and (len(values) == 1 or i + 1 < len(values) and values[i + 1] in COUNT_UNITS)
              else value for i, value in enumerate(values)]
    result, index = [], 0
    while index < len(values):
        pair = values[index:index + 2]
        if pair in (["1", "quart"], ["3", "quarts"], ["1", "demi"]):
            result.append({("1", "quart"): "¼", ("3", "quarts"): "¾", ("1", "demi"): "½"}[tuple(pair)])
            index += 2
            continue
        value = values[index]
        if value == "de" and result and result[-1] in {"¼", "½", "¾"}:
            index += 1
            continue
        if value in {"le", "la", "les"} and index + 1 < len(values) and values[index + 1] in TIME:
            index += 1
            continue
        if value == "et" and result and result[-1] in TIME and index + 1 < len(values) and values[index + 1] in TIME:
            index += 1
            continue
        result.append(value)
        index += 1
    return [{"0,25": "¼", "0,5": "½", "0,75": "¾"}.get(value, value)
            if i + 1 < len(result) and result[i + 1] in {"comprimé"} | TIME else value
            for i, value in enumerate(result)]


def negations(text):
    return ["ne" if value.casefold() in {"n'", "n’"} else value.casefold() for value in NEGATION.findall(text)]


def signed_quantities(text):
    # Preserve the ordinal position of each signed scalar, not just the
    # presence of one minus sign somewhere in the utterance.
    marked = re.sub(r"[-−–—﹣－]\s*(?=\d)", "moins ", text)
    values, result, ordinal = medical_words(marked), [], 0
    for index, value in enumerate(values):
        if NUMBER.fullmatch(value):
            if index and values[index - 1] == "moins":
                result.append((ordinal, value))
            ordinal += 1
    return result


def alternatives(text):
    # The two doses in "quart matin et demi soir" must not become options
    # via "ou". Anchor "ou/soit" to quantities and times so a source "soit"
    # used to restate a duration cannot migrate to a different administration.
    result, anchor = [], 0
    for value in medical_words(text):
        if value in {"ou", "soit"}:
            result.append((value, anchor))
        if NUMBER.fullmatch(value) or value in TIME:
            anchor += 1
    return result


def span_checks(text, labels, category):
    normalize = lambda value: [no_accents(token) for token in medical_words(value)] if category == "drug" else medical_words(value)
    haystack, used, result = normalize(text), set(), []
    for label in labels:
        candidates = list(matches(haystack, normalize(label)))
        hit = next((pair for pair in candidates if pair not in used), None)
        if hit is not None:
            used.add(hit)
        result.append(hit is not None)
    return result


def association_check(text, relation, reference):
    # Local name + unqualified strength, with no new/removed negation anywhere.
    # Existing "sans croquer" must not be misclassified as a negated drug.
    if negations(text) != negations(reference):
        return False
    name = tuple(no_accents(value) for value in tokens(relation["drug"]))
    expected = Decimal(relation["value"]), relation["unit"]
    allowed = LOCAL_LINKS | {tuple(relation["source_link"])}
    for clause in CLAUSE.split(text):
        if CONCENTRATION.search(clause):
            continue
        parts = tokens(clause, strict=True)
        places = positions(tuple(no_accents(value) for value in parts), name)
        amounts = quantities(parts, strict=True)
        if len(places) != 1 or len(amounts) != 1:
            continue
        amount, unit, start, _ = amounts[0]
        name_end = places[0] + len(name)
        if (amount, unit) == expected and name_end <= start and parts[name_end:start] in allowed:
            return True
    return False


def annotate(reference, bio):
    pieces, entities = reference.split(), spans(reference, bio)
    critical = {name: [] for name in CATEGORIES}
    def add(category, start, end):
        value = " ".join(pieces[start:end])
        if value and value not in critical[category]:
            critical[category].append(value)
    # Keep repeated doses/fractions as separate checks; one occurrence cannot
    # satisfy two source entities. Other identical spans are still counted below.
    def add_occurrence(category, start, end):
        if start < end:
            critical[category].append(" ".join(pieces[start:end]))
    drugs, strengths = [], []
    for index, (kind, text, start, end) in enumerate(entities):
        if kind in {"drug", "inn"}:
            if index + 1 < len(entities) and entities[index + 1][0] == "A" and entities[index + 1][2] == end:
                end = entities[index + 1][3]
            add("drug", start, end)
            drugs.append((" ".join(pieces[start:end]), start, end))
        if kind in NUMERIC_KINDS:
            add_occurrence("value", start, end)
        if kind in {"d_dos_up", "dos_uf", "dur_ut"}:
            while end > start and pieces[end - 1] in {"le", "la", "les", "de"}:
                end -= 1
            add_occurrence("unit", start, end)
        if kind == "dos_val" and any(token in {"quart", "quarts", "demi", "demie", "¼", "½", "¾"} for token in text.split()):
            add_occurrence("fraction", start, end)
        if kind == "rhythm_tdte":
            add_occurrence("frequency", start - 1 if start and pieces[start - 1] == "chaque" else start, end)
        if kind == "rhythm_perday":
            if pieces[end:end + 3] == ["fois", "par", "jour"]:
                end += 3
            elif end < len(pieces) and pieces[end] == "prise":
                end += 1
                if start and pieces[start - 1] == "en":
                    start -= 1
            add_occurrence("frequency", start, end)
        if kind in {"cma_event", "fasting", "dos_cond"}:
            if kind == "dos_cond" and start and pieces[start - 1] == "si":
                start -= 1
                if start and pieces[start - 1] == "uniquement":
                    start -= 1
            add_occurrence("condition", start, end)
            if "repas" in pieces[start:end] and any(word in {"chaque", "chacun"} for word in pieces[start:end]):
                add("frequency", start, end)
        if index + 1 < len(entities):
            following, _, next_start, next_end = entities[index + 1]
            if kind in {"d_dos_val", "dos_val", "dur_val"} and following in {"d_dos_up", "dos_uf", "dur_ut"} and 0 <= next_start - end <= 1:
                pair_start = start
                if kind == "dos_val" and index and entities[index - 1][0] == "dos_val":
                    previous = entities[index - 1]
                    if pieces[previous[3]:start] == ["à"]:
                        pair_start = previous[2]
                while next_end > next_start and pieces[next_end - 1] in {"le", "la", "les"}:
                    next_end -= 1
                add_occurrence("duration" if kind == "dur_val" else "dose", pair_start, next_end)
                if kind == "d_dos_val":
                    value, unit = scalar(tokens(text)), UNITS.get(tokens(" ".join(pieces[next_start:next_end])))
                    if value is not None and unit is not None:
                        strengths.append((str(value), unit, start, next_end))
        if kind == "dos_val":
            # Associate the administered amount/fraction with the explicit time
            # before the next amount/duration. Preserve all times sharing a dose.
            time_end = None
            for following, _, next_start, next_end in entities[index + 1:]:
                if following in {"dos_val", "d_dos_val", "dur_val", "min_gap_val"}:
                    break
                if following == "rhythm_tdte":
                    time_end = next_end
            if time_end:
                add_occurrence("administration_time", start, time_end)
    intervals = [entity for entity in entities if entity[0].startswith("freq_")]
    if intervals:
        add("frequency", intervals[0][2], intervals[-1][3])
    if "par jour" in reference and not any("par jour" in label for label in critical["frequency"]):
        critical["frequency"].append("par jour")
    for match in re.finditer(r"\battendre\s+[^;.!?]+?\b(?:heures?|minutes?)\b", reference):
        critical["delay"].append(match.group())
    for match in re.finditer(r"\b\d+(?:[.,]\d+)?\s+dose\s+de\s+\d+\s+kilogrammes?\b", reference):
        critical["dose"].append(match.group())
    for index, word in enumerate(pieces):
        if NEGATION.fullmatch(word):
            add_occurrence("negation", index, min(len(pieces), index + 2))
    if not any(critical[name] for name in ("drug", "dose", "frequency", "duration")):
        critical["condition"].append(reference)
    relations = []
    if len(drugs) == 1 and len(strengths) == 1:
        drug, _, drug_end = drugs[0]
        value, unit, dose_start, _ = strengths[0]
        if drug_end <= dose_start:
            relations.append({"drug": drug, "value": value, "unit": unit,
                              "source_link": list(tokens(" ".join(pieces[drug_end:dose_start])))})
    return critical, relations


def score_case(case, hypothesis):
    reference = case["reference"]
    normalized, actual = medical_words(reference), medical_words(hypothesis)
    checks = {category: span_checks(hypothesis, labels, category) for category, labels in case["critical"].items()}
    signature = lambda values: [value for value in values if NUMBER.fullmatch(value)]
    units = lambda values: Counter(value for value in values if value in UNIT_SCREEN)
    guards = {
        "numeric_sequence_equal": signature(normalized) == signature(actual),
        "unit_multiplicities_equal": units(normalized) == units(actual),
        "negation_markers_equal": negations(reference) == negations(hypothesis),
        "no_added_signed_number": signed_quantities(reference) == signed_quantities(hypothesis),
        "alternative_connector_positions_equal": alternatives(reference) == alternatives(hypothesis),
        "no_added_concentration": bool(CONCENTRATION.search(reference)) == bool(CONCENTRATION.search(hypothesis)),
    }
    associations = [association_check(hypothesis, relation, reference) for relation in case["drug_strength_associations"]]
    return {"spans": checks, "guards": guards, "drug_strength_association": associations,
            "screen_passed": all(guards.values()) and all(all(values) for values in checks.values()) and all(associations)}


def prepare_grid(corpus: Path, archive: Path, output: Path):
    output = output.resolve()
    if output.is_relative_to(REPO) or output.exists() or not output.parent.is_dir():
        raise ValueError("La grille doit être un nouveau fichier privé hors dépôt")
    corpus = corpus.resolve(strict=True)
    verify_export(corpus, archive)
    rows = [json.loads(line) for line in safe_artifact(corpus, "validation.jsonl").read_text(encoding="utf-8").splitlines()]
    selected = validation_selection(rows, 32)
    with locked_archive(archive) as source:
        references = source.read(PX_PATH + "seq.in").decode("utf-8-sig").splitlines()
        annotations = source.read(PX_PATH + "seq.out").decode("utf-8-sig").splitlines()
    cases = []
    for row in selected:
        reference, bio = references[row["source_row_index"]], annotations[row["source_row_index"]]
        if reference != row["text"]:
            raise ValueError("Référence différente de la source verrouillée")
        critical, relations = annotate(reference, bio)
        case = {"id": row["id"], "speaker_id": row["speaker_id"], "source_row_index": row["source_row_index"],
                "pcm_sha256": row["pcm_sha256"], "reference": reference, "source_bio": bio,
                "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
                "critical": critical, "drug_strength_associations": relations}
        sanity = score_case(case, reference)
        if not sanity["screen_passed"]:
            raise ValueError(f"La référence ne passe pas sa propre grille : {row['id']} {sanity}")
        cases.append(case)
    coverage = {category: {"spans": sum(len(case["critical"][category]) for case in cases),
                           "clips": sum(bool(case["critical"][category]) for case in cases)} for category in CATEGORIES}
    coverage["drug_strength_association"] = {"spans": sum(len(case["drug_strength_associations"]) for case in cases),
                                              "clips": sum(bool(case["drug_strength_associations"]) for case in cases)}
    result = {"schema": 1, "created_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": PX_SHA256,
              "selection_key": SELECTION_KEY, "selection_sha256": json_digest([row["id"] for row in selected]),
              "validation_manifest_sha256": sha256(corpus / "validation.jsonl"), "reference_only_annotation": True,
              "predictions_used_to_prepare": False, "scorer_sha256": sha256(Path(__file__)),
              "cases": cases, "coverage": coverage,
              "limitations": ["32 development clips from eight voices; this is not an independent clinical test",
                              "Fractions occur in only one clip; no clinical symptom negations are represented",
                              "The single negation is an administration instruction: sans croquer",
                              "Historical seq.in spelling and incomplete BIO annotations are preserved, not medically re-audited",
                              "Conservative literal screens flag equivalent paraphrases for review; WER and these screens alone cannot qualify a model",
                              "Drug accents are ignored only in drug/association comparisons; no names are corrected",
                              "Association screen covers a single drug and an unqualified strength, not all possible prescription relations"]}
    atomic_json(output, result)
    output.with_suffix(output.suffix + ".sha256").write_text(sha256(output) + "\n", encoding="ascii")
    print(json.dumps({"prepared_clips": len(cases), "speakers": len({case['speaker_id'] for case in cases}),
                      "grid_sha256": sha256(output), "coverage": coverage}, ensure_ascii=False), flush=True)
    return result


def score_predictions(grid_path: Path, predictions: Path, output: Path):
    output = output.resolve()
    if output.is_relative_to(REPO) or output.exists() or not output.parent.is_dir():
        raise ValueError("Choisir un nouveau dossier de résultat privé")
    expected_digest = grid_path.with_suffix(grid_path.suffix + ".sha256").read_text(encoding="ascii").strip()
    if grid_path.is_symlink() or sha256(grid_path) != expected_digest:
        raise ValueError("La grille a changé depuis sa préparation")
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    contract = json.loads(safe_artifact(predictions.parent.resolve(), "contract.json").read_text(encoding="utf-8"))
    report = json.loads(safe_artifact(predictions.parent.resolve(), "report.json").read_text(encoding="utf-8"))
    if (grid.get("schema") != 1 or grid.get("source_sha256") != PX_SHA256
            or grid.get("predictions_used_to_prepare") is not False
            or grid.get("scorer_sha256") != sha256(Path(__file__))
            or contract.get("selected_rows_sha256") != grid["selection_sha256"]
            or contract.get("manifest_sha256", {}).get("validation") != grid["validation_manifest_sha256"]
            or report.get("status") != "completed" or report.get("contract_sha256") != json_digest(contract)):
        raise ValueError("Grille, sélection, code ou évaluation incompatible/incomplète")
    rows = [json.loads(line) for line in predictions.read_text(encoding="utf-8").splitlines()]
    if [row["id"] for row in rows] != [case["id"] for case in grid["cases"]]:
        raise ValueError("Ordre ou ensemble de prédictions différent des 32 cas fixés")
    details, aggregates = [], {method: {"spans": {}, "guards": {}, "screen_passed": 0,
                                       "drug_strength_association": [0, 0]} for method in ("base", "adapter")}
    paired = {"regressions": {}, "improvements": {}}
    for case, row in zip(grid["cases"], rows):
        if row.get("reference") != case["reference"] or row.get("speaker_id") != case["speaker_id"]:
            raise ValueError("Référence ou voix différente de la grille")
        result = {"id": case["id"]}
        flattened = {}
        for method in aggregates:
            if not isinstance(row.get(method, {}).get("text"), str):
                raise ValueError("Résultat apparié base/adaptateur requis")
            scored = score_case(case, row[method]["text"])
            result[method] = scored
            aggregate = aggregates[method]
            aggregate["screen_passed"] += int(scored["screen_passed"])
            for category, checks in scored["spans"].items():
                counts = aggregate["spans"].setdefault(category, [0, 0])
                counts[0] += sum(checks)
                counts[1] += len(checks)
            for category, good in scored["guards"].items():
                counts = aggregate["guards"].setdefault(category, [0, 0])
                counts[0] += int(good)
                counts[1] += 1
            aggregate["drug_strength_association"][0] += sum(scored["drug_strength_association"])
            aggregate["drug_strength_association"][1] += len(scored["drug_strength_association"])
            flattened[method] = {**{f"span:{category}:{index}": value for category, values in scored["spans"].items()
                                     for index, value in enumerate(values)},
                                 **{f"guard:{category}": value for category, value in scored["guards"].items()},
                                 **{f"association:{index}": value for index, value in enumerate(scored["drug_strength_association"])}}
        for key, baseline in flattened["base"].items():
            candidate = flattened["adapter"][key]
            group = ":".join(key.split(":")[:2]) if key.startswith("span:") else key.split(":")[0] if key.startswith("association:") else key
            if baseline and not candidate:
                paired["regressions"][group] = paired["regressions"].get(group, 0) + 1
            if candidate and not baseline:
                paired["improvements"][group] = paired["improvements"].get(group, 0) + 1
        details.append(result)
    output.mkdir(mode=0o700)
    atomic_json(output / "details.local.json", details)
    result = {"schema": 1, "clips": len(rows), "grid_sha256": expected_digest,
              "predictions_sha256": sha256(predictions), "scores": aggregates, "paired": paired,
              "coverage": grid["coverage"], "limitations": grid["limitations"],
              "automatic_adoption": False, "all_regressions_require_review": True}
    atomic_json(output / "report.json", result)
    print(json.dumps({"clips": len(rows), "scores": aggregates, "paired": paired}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--corpus", type=Path, required=True)
    prepare.add_argument("--px-archive", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("--grid", type=Path, required=True)
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_grid(args.corpus, args.px_archive, args.output) if args.command == "prepare" else score_predictions(args.grid, args.predictions, args.output)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Grille/évaluation refusée : {error}\n")


if __name__ == "__main__":
    main()
