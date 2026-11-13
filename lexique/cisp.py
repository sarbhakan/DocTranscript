"""Extrait les motifs, plaintes et diagnostics de la CISP-2 française (FHIR ANS)."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata


SOURCE = "https://smt.esante.gouv.fr/fhir/CodeSystem/terminologie-cisp/_history/3?_format=json"
CANONICAL = "https://smt.esante.gouv.fr/terminologie-cisp"
LICENSE = "https://github.com/etalab/licence-ouverte/blob/master/LO.md"
SHA256 = "142280de37190e0e023a2f98c5db4c51aa543dc6a40c2acd86e5b738bd3478eb"
CONCEPTS = 1_434
RUBRIC = re.compile(r"[ABDFHKLNPRSTUWXYZ][0-9]{2}\Z")
COUNTS = {"motif-plainte": 320, "diagnostic-soins-primaires": 366}


def extract(blob):
    if hashlib.sha256(blob).hexdigest() != SHA256:
        raise ValueError("SHA-256 différent de la source FHIR CISP-2 vérifiée")
    resource = json.loads(blob)
    expected = {
        "resourceType": "CodeSystem",
        "id": "terminologie-cisp",
        "url": CANONICAL,
        "version": "2019-05",
        "date": "2019-06-26T00:00:00+00:00",
        "publisher": "Agence du numérique en santé",
        "status": "active",
        "copyright": f"[LOv2]({LICENSE})",
        "content": "complete",
        "count": CONCEPTS,
    }
    if any(resource.get(key) != value for key, value in expected.items()):
        raise ValueError("métadonnées inattendues du CodeSystem CISP-2")
    if resource.get("meta", {}).get("versionId") != "3":
        raise ValueError("version FHIR inattendue")
    concepts = resource["concept"]
    if len(concepts) != CONCEPTS:
        raise ValueError("liste des concepts incomplète")
    seen = set()
    rows = []
    counts = dict.fromkeys(COUNTS, 0)
    for concept in concepts:
        code = concept["code"]
        if not isinstance(code, str) or code in seen or concept.get("concept"):
            raise ValueError("code invalide, doublon ou hiérarchie inattendue")
        seen.add(code)
        if not RUBRIC.fullmatch(code):
            continue
        component = int(code[1:])
        if 1 <= component <= 29:
            category = "motif-plainte"
        elif 70 <= component <= 99:
            category = "diagnostic-soins-primaires"
        else:
            continue
        label = concept["display"]
        if (not isinstance(label, str) or not label.strip() or len(label) > 500
                or any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in label)
                or label.startswith(("=", "+", "-", "@"))):
            raise ValueError(f"{code} : libellé invalide pour cet export")
        # Le display français est conservé intégralement. Le tag décrit
        # le domaine de ce référentiel, sans limiter l'usage du terme.
        rows.append((code, label, category, "medecine-generale"))
        counts[category] += 1
    if counts != COUNTS:
        raise ValueError("nombre inattendu de rubriques par composante")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("code", "libelle", "categorie", "specialites"))
    writer.writerows(sorted(rows))
    return output.getvalue().encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.source.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("ressource source supérieure à 8 Mio")
        csv_blob = extract(args.source.read_bytes())
        with args.output.open("xb") as target:
            target.write(csv_blob)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "source_url": SOURCE,
        "source_sha256": SHA256,
        "output_sha256": hashlib.sha256(csv_blob).hexdigest(),
        "edition": "2019-05",
        "publication_date": "2019-06-26",
        "license_url": LICENSE,
        "rubrics": COUNTS,
    }, indent=2))


if __name__ == "__main__":
    main()
