"""Score two PxSLU transcripts without editing them or printing their content.

The input IDs px-N are zero-based rows in the v4 archive. Historical spelling,
strength and proximity counters remain separate from the stricter screening
for an unqualified strength and a unique same-clause association. Neither
validates the prescription. WAVs and optional verbatim output stay local.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from zipfile import ZipFile

PX = "PxCorpus/PxSLU/"
WORD = re.compile(r"-?\d+(?:[.,]\d+)?|[^\W\d_]+|[%/]", re.UNICODE)
STRICT_WORD = re.compile(r"-?\d+(?:[.,]\d+)?|[^\W\d_]+|[%/–¼½¾]", re.UNICODE)
SLASH_OR_SIGN = str.maketrans({"⁄": "/", "∕": "/", "／": "/", "−": "-", "﹣": "-", "－": "-"})
CLAUSE = re.compile(r"[;!?\n]+|(?<!\d)\.|\.(?!\d)")
NEGATION = re.compile(r"\b(?:ne|pas|sans|ni|non|aucun|aucune|jamais|absence)\b|\bn[’'](?=[^\W\d_])",
                      re.IGNORECASE)
LOCAL_LINKS = {(), ("à",), ("de",), ("dosé", "à"), ("dosée", "à"), ("dosage", "de")}
BASIC = ("zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize "
         "quatorze quinze seize").split()
TENS = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante",
        60: "soixante"}


def french(value):
    if value <= 16:
        return BASIC[value]
    if value < 20:
        return "dix " + french(value - 10)
    if value < 70:
        ten, one = divmod(value, 10)
        return TENS[ten * 10] + ("" if not one else (" et " if one == 1 else " ") + french(one))
    if value < 80:
        return "soixante " + ("et " if value == 71 else "") + french(value - 60)
    if value < 100:
        return "quatre vingt" + ("s" if value == 80 else " " + french(value - 80))
    if value < 1000:
        hundred, rest = divmod(value, 100)
        prefix = "cent" if hundred == 1 else french(hundred) + " cent"
        return prefix + ("s" if hundred > 1 and not rest else "") + (" " + french(rest) if rest else "")
    thousand, rest = divmod(value, 1000)
    return ("" if thousand == 1 else french(thousand) + " ") + "mille" + (
        " " + french(rest) if rest else "")


def tokens(value, *, strict=False):
    value = unicodedata.normalize("NFC", value).casefold().replace("μ", "µ")
    # Preserve decimal separators within digits. Hyphens/apostrophes are word boundaries.
    # Treat a spaced group of three digits as a French thousands separator.
    value = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?!\d))", "", value)
    if strict:
        value = value.translate(SLASH_OR_SIGN)
        # Preserve a range dash between figures, including when spaced.
        value = re.sub(r"(?<=\d)\s*[-–—]\s*(?=\d)", " – ", value)
        value = re.sub(r"-\s+(?=\d)", "-", value)
    return tuple((STRICT_WORD if strict else WORD).findall(value))


def no_accents(value):
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


NAMES = {}
for n in range(10000):
    name = french(n).replace("quatre vingts ", "quatre vingt ")
    k = tokens(name)
    for v in (k, tuple(x for x in k if x != "et"), tuple("cent" if x == "cents" else "vingt" if x == "vingts" else x for x in k)):
        NAMES.setdefault(v, n)
NAMES[("une",)] = 1
NAMES[("zero",)] = 0
MAX_NUM_TOKENS = max(map(len, NAMES))

UNIT_NAMES = {
    "mg": ("mg", "milligramme", "milligrammes", "miligramme", "miligrammes"),
    "g": ("g", "gramme", "grammes"),
    "ug": ("µg", "mcg", "microgramme", "microgrammes"),
    "ml": ("ml", "millilitre", "millilitres"),
    "l": ("litre", "litres", "l"),
    "%": ("%", "pour cent", "pourcent"),
    "ui": ("ui", "unité internationale", "unités internationales"),
}
UNITS = {tokens(alias): name for name, aliases in UNIT_NAMES.items() for alias in aliases}


def scalar(parts):
    if len(parts) == 1 and re.fullmatch(r"-?\d+(?:[.,]\d+)?", parts[0]):
        return Decimal(parts[0].replace(",", "."))
    if parts in NAMES:
        return Decimal(NAMES[parts])
    for marker in ("virgule", "point"):
        if marker not in parts:
            continue
        sep = parts.index(marker)
        whole, fraction = parts[:sep], parts[sep + 1:]
        if marker in fraction or not whole or not fraction:
            return None
        a = scalar(whole)
        if a is None or a != a.to_integral_value():
            return None
        digits = [scalar((piece,)) for piece in fraction]
        if all(d is not None and 0 <= d <= 9 and d == d.to_integral_value() for d in digits):
            tail = "".join(str(d) for d in digits)
        else:
            f = scalar(fraction)
            if f is None or f != f.to_integral_value():
                return None
            tail = str(f)
        return Decimal(f"{a}.{tail}")
    return None


def quantities(parts, *, strict=False):
    found = []
    for end in range(len(parts)):
        for alias, unit in UNITS.items():
            j = end + 1 - len(alias)
            if j < 1 or parts[j:end + 1] != alias:
                continue
            suffix = parts[end + 1:]
            # A concentration or a per-act dosage is not an unqualified
            # mass/volume. Do not drop the denominator to force a match.
            if (suffix[:1] == ("/",) or
                    (len(suffix) >= 2 and suffix[0] == "par" and
                     (suffix[1] in {"ml", "millilitre", "millilitres", "litre", "litres",
                                    "dose", "doses", "comprimé", "comprimés", "gélule", "gélules"}
                      or (strict and suffix[1] == "l")))):
                continue
            # Longest valid suffix before the unit; "de" and punctuation are not numeric.
            for start in range(max(0, j - MAX_NUM_TOKENS * 2 - 1), j):
                amount = scalar(parts[start:j])
                if amount is None:
                    continue
                # A denominator or upper end of a range is not a standalone
                # quantity. Also reject the trailing literal from "moins 20".
                if not strict or (amount > 0 and not follows_compound(parts, start)):
                    found.append((amount, unit, start, end + 1))
                break
    return found


def quantity_before(parts, end):
    return any(scalar(parts[start:end]) is not None for start in range(max(0, end - MAX_NUM_TOKENS), end))


def follows_compound(parts, start):
    return start and (
        parts[start - 1] in {"/", "–", "moins"} or
        (parts[start - 1] in {"à", "et", "ou"} and quantity_before(parts, start - 1)))


def spans(reference, bio):
    text, tags = reference.split(), bio.split()
    if len(text) != len(tags):
        raise ValueError("nombre de mots différent entre référence et annotation")
    groups = []
    for i, (part, tag) in enumerate(zip(text, tags)):
        if tag.startswith("B-"):
            groups.append([tag[2:], [part], i, i + 1])
        elif tag.startswith("I-") and groups and groups[-1][0] == tag[2:] and groups[-1][-1] == i:
            groups[-1][1].append(part)
            groups[-1][-1] += 1
    return [(k, " ".join(v), start, end) for k, v, start, end in groups]


def positions(parts, target):
    return [i for i in range(len(parts) - len(target) + 1) if target and parts[i:i + len(target)] == target]


def strict_local_association(output, drug, expected_value, expected_unit):
    """Conservative screening for a unique same-clause name and strength."""
    name = tokens(drug)
    for clause in CLAUSE.split(output):
        if NEGATION.search(clause):
            continue
        parts = tokens(clause, strict=True)
        places = positions(parts, name)
        values = quantities(parts, strict=True)
        if len(places) != 1 or len(values) != 1:
            continue
        i = places[0]
        amount, unit, start, _ = values[0]
        if ((amount, unit) == (expected_value, expected_unit) and
                i + len(name) <= start and parts[i + len(name):start] in LOCAL_LINKS):
            return True
    return False


def evaluate_row(ref, bio, output):
    entities = spans(ref, bio)
    drugs = [v for k, v, _, _ in entities if k == "drug"]
    strengths = [(v, w) for (k, v, _, stop), (l, w, start, _) in zip(entities, entities[1:])
                 if k == "d_dos_val" and l == "d_dos_up" and 0 <= start - stop <= 1]
    parts = tokens(output)
    measures = {"drug_ref": drugs, "strength_ref": strengths, "reason": ""}
    places = []
    if len(drugs) == 1:
        drug = drugs[0]
        places = positions(parts, tokens(drug))
        measures.update(
            drug_ref=drug, drug_exact=bool(places),
            drug_no_accents_exact=bool(positions(tuple(map(no_accents, parts)), tuple(map(no_accents, tokens(drug))))))
    if len(strengths) != 1:
        measures["reason"] = "annotation multiple ou incomplète"
        return measures
    strength, unit = strengths[0]
    expected_val, expected_unit = scalar(tokens(strength)), UNITS.get(tokens(unit))
    if expected_val is None or expected_unit is None:
        measures["reason"] = "quantité ou unité de référence non gérée"
        return measures
    decoded = quantities(parts)
    matched = [(start, end) for v, u, start, end in decoded if v == expected_val and u == expected_unit]
    mass_factors = {"mg": Decimal(1000), "g": Decimal(1_000_000), "ug": Decimal(1)}
    volume_factors = {"ml": Decimal(1), "l": Decimal(1000)}
    dimensions = (mass_factors, volume_factors)
    physical_equivalence = any(
        u in factors and expected_unit in factors and v * factors[u] == expected_val * factors[expected_unit]
        for v, u, _, _ in decoded for factors in dimensions)
    measures.update(
        strength_ref=f"{expected_val} {expected_unit}",
        strengths_output=[f"{amount} {kind}" for amount, kind, _, _ in decoded],
        strength_exact=bool(matched),
        strength_equivalent=bool(matched) or physical_equivalence,
        strength_unqualified_exact=any((v, u) == (expected_val, expected_unit)
                                      for v, u, _, _ in quantities(tokens(output, strict=True), strict=True)),
        extra_quantity_review=len(decoded) > 1,
    )
    if len(drugs) == 1:
        # Keep the proximity measure separate from stronger local evidence.
        measures["ordered_pair_nearby"] = any(
            0 <= start - (i + len(tokens(drug))) <= 6 for i in places for start, _ in matched)
        measures["strength_association_strict"] = strict_local_association(output, drug, expected_val, expected_unit)
    return measures


def catalogue_headings(path):
    if path is None:
        return None
    # A bare prefix can accidentally match another product. Use the complete
    # substance name or the complete specialty heading before its first number.
    names = set()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for label, category in db.execute(
                "SELECT label, category FROM term WHERE category IN ('medicament', 'substance')"):
            parts = tuple(map(no_accents, tokens(label)))
            if category == "medicament":
                stop = next((i for i, token in enumerate(parts) if token[0].isdigit()), len(parts))
                parts = parts[:stop]
            if parts:
                names.add(parts)
    return names


def report(archive, files, out, bdpm):
    headings = catalogue_headings(bdpm)
    with ZipFile(archive) as z:
        refs = z.read(PX + "seq.in").decode("utf-8-sig").splitlines()
        bios = z.read(PX + "seq.out").decode("utf-8-sig").splitlines()
        voices = [row[0] for row in csv.reader(z.read(PX + "metadata.txt").decode("utf-8-sig").splitlines())]
    if len(refs) != len(bios) or len(refs) != len(voices):
        raise ValueError("fichiers PxSLU de longueurs différentes")
    tables = {}
    for name, file in files:
        data = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
        table = {}
        for row in data:
            if re.fullmatch(r"px-\d+", row.get("id", "")):
                if row["id"] in table:
                    raise ValueError("identifiant Px dupliqué")
                table[row["id"]] = row
        if name in tables or not table:
            raise ValueError("nom de moteur dupliqué ou aucun résultat Px")
        tables[name] = table
    keys = set(next(iter(tables.values())))
    if any(set(t) != keys for t in tables.values()):
        raise ValueError("les résultats ne couvrent pas les mêmes identifiants Px")
    scores = {name: Counter() for name in tables}
    records = []
    for case in sorted(keys, key=lambda s: int(s[3:])):
        ix = int(case[3:])
        for name, table in tables.items():
            row = table[case]
            output = row["text"] if row.get("status") == "ok" and isinstance(row.get("text"), str) else ""
            measures = evaluate_row(refs[ix], bios[ix], output)
            score = scores[name]
            if measures["reason"]:
                score["annotation_manual_review"] += 1
            if "drug_exact" in measures:
                score["n_drug"] += 1
                score["drug_exact"] += measures["drug_exact"]
                score["drug_no_accents_exact"] += measures["drug_no_accents_exact"]
                if headings is not None:
                    verified = tuple(map(no_accents, tokens(measures["drug_ref"]))) in headings
                    measures["drug_ref_in_bdpm_heading_index"] = verified
                    score["n_drug_in_bdpm_heading_index"] += verified
                    score["drug_exact_on_bdpm_ref_subset"] += verified and measures["drug_exact"]
                    score["drug_no_accents_exact_on_bdpm_ref_subset"] += verified and measures["drug_no_accents_exact"]
            if "strength_exact" in measures:
                score["n_strength"] += 1
                score["strength_exact"] += measures["strength_exact"]
                score["strength_equivalent"] += measures["strength_equivalent"]
                score["strength_unqualified_exact"] += measures["strength_unqualified_exact"]
                score["extra_quantity_review"] += measures["extra_quantity_review"]
            if "ordered_pair_nearby" in measures:
                score["n_pair"] += 1
                score["ordered_pair_nearby"] += measures["ordered_pair_nearby"]
                score["strength_association_strict"] += measures["strength_association_strict"]
            score["decode_failures"] += row.get("status") != "ok"
            records.append({"case": case, "model": name, "reference": refs[ix], "output": output, **measures})
    if out:
        with out.open("x", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    voice_count = len({voices[int(case[3:])] for case in keys})
    result = {"scoring_revision": 2, "case_count": len(keys), "voice_count": voice_count, "automatic_screening": scores}
    if len(tables) == 2:
        a, b = tables
        record_map = {(record["case"], record["model"]): record for record in records}
        paired = {}
        for measure in ("drug_exact", "strength_equivalent", "strength_unqualified_exact",
                        "ordered_pair_nearby", "strength_association_strict"):
            buckets = Counter()
            for case in keys:
                x, y = (record_map[case, name].get(measure) for name in (a, b))
                if x is not None and y is not None:
                    buckets["both_correct" if x and y else a + "_only" if x else
                            b + "_only" if y else "neither_correct"] += 1
            paired[measure] = dict(buckets)
        result["paired_counts"] = paired
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--model", metavar="NAME:TRANSCRIPTS.NDJSON", action="append", required=True)
    parser.add_argument("--bdpm", type=Path, help="optional local BDPM SQLite from lexique build")
    parser.add_argument("--review", type=Path, help="optional new local file with paired output and source labels")
    args = parser.parse_args()
    files = []
    for spec in args.model:
        name, separator, path = spec.partition(":")
        if not name or not separator or not path:
            parser.error("each --model requires NAME:TRANSCRIPTS.NDJSON")
        files.append((name, Path(path)))
    try:
        result = report(args.archive, files, args.review, args.bdpm)
    except (OSError, ValueError, IndexError, KeyError, TypeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
