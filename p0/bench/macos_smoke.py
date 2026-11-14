"""Mesurer l'écart lexical et comparer deux exports d'une dictée fictive sur Mac."""

import argparse
import csv
import json
from pathlib import Path

from .scoring import edit_distance, words


SMOKE_REFERENCE = (
    "Pas de douleur à la cheville droite. "
    "La gêne concerne la cheville gauche depuis cinq jours."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("avant", type=Path, help="Export du brouillon brut avant de quitter")
    parser.add_argument("--apres", type=Path, help="Export de la même note après avoir relancé l'application")
    parser.add_argument("--cas", choices=("micro-cheville", "dev-17"), default="micro-cheville")
    args = parser.parse_args()
    try:
        reference = SMOKE_REFERENCE
        if args.cas == "dev-17":
            cases_path = Path(__file__).resolve().parents[1] / "corpus" / "cas.csv"
            with cases_path.open(encoding="utf-8-sig", newline="") as source:
                reference = next(row["reference"] for row in csv.DictReader(source) if row["id"] == "dev-17")
        first = args.avant.read_bytes()
        hypothesis = words(first.decode("utf-8-sig"))
        persistence = "non_vérifiée"
        if args.apres is not None:
            if args.avant.samefile(args.apres):
                parser.error("choisir deux fichiers distincts, exportés avant et après relance")
            second = args.apres.read_bytes()
            persistence = "identique" if hypothesis and first == second else "différente_ou_vide"
    except (OSError, UnicodeError, StopIteration) as error:
        parser.error(str(error))

    expected = words(reference)
    distance = edit_distance(expected, hypothesis)
    print(json.dumps({
        "cas": args.cas,
        "mots_attendus": len(expected),
        "mots_observés": len(hypothesis),
        "écarts_lexicaux": distance,
        "wer": distance / len(expected),
        "export_après_relance": persistence,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
