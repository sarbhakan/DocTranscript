"""Extrait les libellés principaux de la CCAM officielle ANS/CNAM (FHIR v84.00)."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata


SOURCE = "https://smt.esante.gouv.fr/fhir/CodeSystem/terminologie-ccam/_history/11?_format=json"
CANONICAL = "https://smt.esante.gouv.fr/terminologie-ccam"
LICENSE = "https://github.com/etalab/licence-ouverte/blob/master/LO.md"
SHA256 = "290c7220534b98cace6a25bec83fe2c6e72867cbb74f99640a82a4b55381cf3a"
CONCEPTS = 38_235
ACTS = 8_558
ACT_CODE = re.compile(r"[A-Z]{4}[0-9]{3}\Z")
TYPES = {"ActeIsole", "Procedure", "ActeComplementaire"}


def extract(blob):
    if hashlib.sha256(blob).hexdigest() != SHA256:
        raise ValueError("SHA-256 différent de la source FHIR v84.00 vérifiée")
    resource = json.loads(blob)
    expected = {
        "resourceType": "CodeSystem",
        "id": "terminologie-ccam",
        "url": CANONICAL,
        "version": "v84.00",
        "date": "2026-07-31T00:00:00+00:00",
        "publisher": "Agence du numérique en santé",
        "status": "active",
        "copyright": f"[LOv2]({LICENSE})",
        "content": "complete",
        "count": CONCEPTS,
    }
    if any(resource.get(key) != value for key, value in expected.items()):
        raise ValueError("métadonnées inattendues du CodeSystem CCAM")
    if resource.get("meta", {}).get("versionId") != "11":
        raise ValueError("version FHIR inattendue")
    concepts = resource["concept"]
    if len(concepts) != CONCEPTS:
        raise ValueError("liste des concepts incomplète")
    seen = set()
    rows = []
    for concept in concepts:
        code = concept["code"]
        if not isinstance(code, str) or code in seen or concept.get("concept"):
            raise ValueError("code invalide, doublon ou hiérarchie inattendue")
        seen.add(code)
        if not ACT_CODE.fullmatch(code):
            continue
        types = [item.get("valueCode") for item in concept.get("property", ()) if item["code"] == "typeActe"]
        if len(types) != 1 or types[0] not in TYPES:
            raise ValueError(f"{code} : type d'acte inattendu")
        label = concept["display"]
        if (not isinstance(label, str) or not label.strip() or len(label) > 500
                or any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in label)
                or label.startswith(("=", "+", "-", "@"))):
            raise ValueError(f"{code} : libellé invalide pour cet export")
        # Préserve display à l'identique. Les chapitres anatomiques ne sont
        # pas des spécialités médicales et ne sont pas inférés.
        rows.append((code, label, "acte", ""))
    if len(rows) != ACTS:
        raise ValueError("nombre inattendu de codes d'actes")
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
        if args.source.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("ressource source supérieure à 32 Mio")
        csv_blob = extract(args.source.read_bytes())
        with args.output.open("xb") as target:
            target.write(csv_blob)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "source_url": SOURCE,
        "source_sha256": SHA256,
        "output_sha256": hashlib.sha256(csv_blob).hexdigest(),
        "edition": "v84.00",
        "publication_date": "2026-07-31",
        "license_url": LICENSE,
        "acts": ACTS,
    }, indent=2))


if __name__ == "__main__":
    main()
