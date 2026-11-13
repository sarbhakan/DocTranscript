"""Mesures reproductibles, sans dépendance tierce."""

import math
import re
import unicodedata


TOKEN = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]+(?:'[^\W\d_]+)*")


def words(text):
    """Garde accents, nombres et négations ; harmonise casse, apostrophes et décimales."""
    normalized = unicodedata.normalize("NFC", text).casefold()
    normalized = normalized.replace("’", "'").replace("ʼ", "'")
    return [token.replace(",", ".") for token in TOKEN.findall(normalized)]


def edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, expected in enumerate(reference, 1):
        row = [i]
        for j, actual in enumerate(hypothesis, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (actual != expected)))
        previous = row
    return previous[-1]


def nearest_rank(values, percentile=0.95):
    """None représente un échec, traité comme une latence infinie."""
    if not values:
        return {"status": "not_applicable", "value": None, "n": 0, "failures": 0}
    ordered = sorted(math.inf if value is None else value for value in values)
    rank_value = ordered[math.ceil(percentile * len(ordered)) - 1]
    return {
        "status": "failed_percentile" if math.isinf(rank_value) else "measured",
        "value": None if math.isinf(rank_value) else rank_value,
        "n": len(ordered),
        "failures": ordered.count(math.inf),
    }
