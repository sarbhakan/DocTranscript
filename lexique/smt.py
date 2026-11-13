"""Extrait les libellés français des instantanés FHIR ANS EMDN et NABM vérifiés."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata


BASE = "https://smt.esante.gouv.fr"
SPECS = {
    "emdn": {
        "history": "3", "edition": "v1.2", "date": "2022-04-28",
        "license_url": "https://creativecommons.org/licenses/by/4.0/legalcode",
        "license_name": "CC BY 4.0", "sha256": "9d0d86451d08a224695a5ae86d26779e9426c468717cf40f98f360ecd0993d3a",
        "count": 8344, "retained": 8149, "category": "dispositif",
        "types": {f"TYPE Level {level}" for level in range(1, 6)},
        "code_pattern": re.compile(r"[A-Z][0-9]+\Z"),
    },
    "nabm": {
        "history": "19", "edition": "V105", "date": "2026-06-04",
        "license_url": "https://github.com/etalab/licence-ouverte/blob/master/LO.md",
        "license_name": "LOv2", "sha256": "2f9465c806150eb8c5f9a7b8f667a501ece33bb2cf9c46f8ead057dd8747251f",
        "count": 1050, "retained": 987, "category": "examen",
        "types": {"code"}, "code_pattern": re.compile(r"[0-9]{4}\Z"),
    },
}


def source_url(name):
    return f"{BASE}/fhir/CodeSystem/terminologie-{name}/_history/{SPECS[name]['history']}?_format=json"


def extract(name, blob):
    spec = SPECS[name]
    if hashlib.sha256(blob).hexdigest() != spec["sha256"]:
        raise ValueError("SHA-256 différent de l'instantané ANS vérifié")
    resource = json.loads(blob)
    expected = {
        "resourceType": "CodeSystem", "id": f"terminologie-{name}",
        "url": f"{BASE}/terminologie-{name}", "version": spec["edition"],
        "date": f"{spec['date']}T00:00:00+00:00", "publisher": "Agence du numérique en santé",
        "status": "active", "copyright": f"[{spec['license_name']}]({spec['license_url']})",
        "content": "complete", "count": spec["count"],
    }
    if any(resource.get(key) != value for key, value in expected.items()):
        raise ValueError("métadonnées inattendues du CodeSystem ANS")
    if resource.get("meta", {}).get("versionId") != spec["history"]:
        raise ValueError("version serveur FHIR inattendue")
    concepts = resource["concept"]
    if len(concepts) != spec["count"]:
        raise ValueError("liste des concepts incomplète")
    seen = set()
    rows = []
    for concept in concepts:
        code = concept["code"]
        if not isinstance(code, str) or code in seen or concept.get("concept"):
            raise ValueError("code invalide, doublon ou hiérarchie inattendue")
        seen.add(code)
        types = [item.get("valueString") for item in concept.get("property", ()) if item["code"] == "type"]
        if len(types) > 1:
            raise ValueError(f"{code} : types multiples")
        if not types or types[0] not in spec["types"]:
            continue
        label = concept["display"]
        if (not spec["code_pattern"].fullmatch(code) or not isinstance(label, str)
                or not label.strip() or len(label) > 500 or label.startswith(("=", "+", "-", "@"))
                or any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in label)):
            raise ValueError(f"{code} : code ou libellé invalide pour cet export")
        # Retain the original French display; no specialties are inferred.
        rows.append((code, label, spec["category"], ""))
    if len(rows) != spec["retained"]:
        raise ValueError("nombre inattendu de libellés retenus")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("code", "libelle", "categorie", "specialites"))
    writer.writerows(sorted(rows))
    return output.getvalue().encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("terminologie", choices=tuple(SPECS))
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    spec = SPECS[args.terminologie]
    try:
        if args.source.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("ressource source supérieure à 8 Mio")
        csv_blob = extract(args.terminologie, args.source.read_bytes())
        with args.output.open("xb") as target:
            target.write(csv_blob)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "source_url": source_url(args.terminologie), "source_sha256": spec["sha256"],
        "output_sha256": hashlib.sha256(csv_blob).hexdigest(), "edition": spec["edition"],
        "publication_date": spec["date"], "license_url": spec["license_url"],
        "count": spec["count"], "retained": spec["retained"], "category": spec["category"],
    }, indent=2))


if __name__ == "__main__":
    main()
