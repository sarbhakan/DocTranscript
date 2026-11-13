"""Produce and summarize a local review sheet; judgment stays with reviewers."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


COLUMNS = ["case_id", "attribute_id", "category", "group_id", "reference_span", "expected",
           "text", "asr_status", "rating", "comment"]
RATINGS = {"exact", "substitution", "omission", "insertion", "none"}


def literal(s):
    # Keep untrusted transcriptions literal in Excel.
    return "'" + s if s and s.lstrip().startswith(("=", "+", "-", "@")) else s


def read_expected(args):
    run = {}
    for line in args.transcripts.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item["id"] in run:
            raise ValueError("identifiant de transcription dupliqué")
        run[item["id"]] = item
    if not run:
        raise ValueError("aucune transcription à relire")
    with args.cases.open(encoding="utf-8-sig", newline="") as src:
        case_kinds = {}
        for row in csv.DictReader(src):
            if row["partition"] == args.partition:
                if row["id"] in case_kinds:
                    raise ValueError("cas dupliqué dans le manifeste")
                case_kinds[row["id"]] = row["kind"]
    if set(case_kinds) != set(run):
        raise ValueError("les cas transcrits ne correspondent pas à la partition du manifeste")
    with args.attributes.open(encoding="utf-8-sig", newline="") as src:
        attributes = [row for row in csv.DictReader(src) if row["case_id"] in run]
    expected = {}
    for row in [*attributes, *({"case_id": key, "attribute_id": "__insertions__", "category": "insertions"}
                               for key in run)]:
        key = row["case_id"], row["attribute_id"]
        if key in expected or (row["category"] == "insertions") != (key[1] == "__insertions__"):
            raise ValueError("attribut dupliqué ou catégorie réservée")
        expected[key] = row
    return run, case_kinds, expected


def prepare(args):
    run, _, expected = read_expected(args)
    with args.output.open("x", encoding="utf-8-sig", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        for row in expected.values():
            result = run[row["case_id"]]
            writer.writerow({**{key: literal(val) for key, val in row.items()},
                             "text": literal(result.get("text") or ""), "asr_status": result["status"]})


def summarize(args):
    run, case_kinds, expected = read_expected(args)
    by_category = {}
    failed = set()
    seen = set()
    cases_with_error = set()
    with args.review.open(encoding="utf-8-sig", newline="") as src:
        for row in csv.DictReader(src, delimiter=";"):
            key = (row["case_id"], row["attribute_id"])
            rating = row["rating"].strip().lower()
            insertion = key[1] == "__insertions__"
            if key not in expected or key in seen or rating not in RATINGS | {""}:
                raise ValueError(f"ligne invalide ou dupliquée : {key}")
            original = run[key[0]]
            for field in ("category", "group_id", "reference_span", "expected", "text", "asr_status"):
                source = {"text": original.get("text") or "", "asr_status": original["status"]}
                if row[field] != literal(source.get(field, expected[key].get(field, ""))):
                    raise ValueError(f"champ de référence modifié ({field}) : {key}")
            seen.add(key)
            if rating and ((rating in {"insertion", "none"}) != insertion):
                raise ValueError(f"type de jugement inattendu : {key}")
            if rating in {"substitution", "omission", "insertion"}:
                cases_with_error.add(key[0])
            if original["status"] != "ok":
                failed.add(key[0])
                if not insertion or not original.get("text"):
                    rating = "unavailable"
            counter = by_category.setdefault(row["category"], {})
            rating = rating or "pending"
            counter[rating] = counter.get(rating, 0) + 1
    if seen != set(expected):
        raise ValueError("grille incomplète : reprendre la grille générée")
    totals = {key: sum(c.get(key, 0) for name, c in by_category.items() if name != "insertions")
              for key in ("exact", "substitution", "omission", "pending", "unavailable")}
    denominator = sum(totals[k] for k in ("exact", "substitution", "omission", "unavailable"))
    pending = totals["pending"] + by_category.get("insertions", {}).get("pending", 0)
    with args.review.open("rb") as src:
        digest = hashlib.file_digest(src, "sha256").hexdigest()
    print(json.dumps({"review_sha256": digest, "cases": len(run), "pending": pending, "failed_cases": len(failed),
                      "failed_controls": sum(case_kinds[key] != "speech" for key in failed),
                      "attributes_in_denominator": denominator,
                      "cases_with_critical_error_observed": len(cases_with_error), "attribute_counts": totals,
                      "accuracy": totals["exact"] / denominator if denominator and not pending else None,
                      "by_category": by_category}, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_subparsers(required=True, dest="action")
    a = actions.add_parser("prepare")
    a.add_argument("--output", type=Path, required=True)
    s = actions.add_parser("summarize")
    s.add_argument("--review", type=Path, required=True)
    for action in (a, s):
        action.add_argument("--transcripts", type=Path, required=True)
        action.add_argument("--attributes", type=Path, required=True)
        action.add_argument("--cases", type=Path, required=True)
        action.add_argument("--partition", choices=("dev", "confirm"), required=True)
    args = p.parse_args()
    try:
        (prepare if args.action == "prepare" else summarize)(args)
    except (OSError, KeyError, TypeError, ValueError) as error:
        p.error(str(error))


if __name__ == "__main__":
    main()
