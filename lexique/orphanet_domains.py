"""Map existing ORPHAcodes to the 33 official French classification domains.

No new disease label is created. Repeated classification nodes are deduplicated;
only the active pathologies/subtypes selected by the existing catalogue qualify.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from .orphanet import ARCHIVE_SHA256, MEMBER, XML_SHA256, SIZE
from .prepare_041 import HERE, member, xml_root, sha

LOCK = HERE / "orphanet-domains.lock.json"


def active_codes(blob):
    root = xml_root(blob)
    disorders = root.find("DisorderList")
    if root.tag != "JDBOR" or disorders is None or len(disorders) != int(disorders.get("count", "-1")):
        raise ValueError("nomenclature Orphanet inattendue")
    result = set()
    for disorder in disorders:
        code = disorder.findtext("OrphaCode", "")
        if disorder.tag != "Disorder" or not re.fullmatch(r"[0-9]+", code):
            raise ValueError("ORPHAcode invalide")
        if (disorder.findtext("Totalstatus") == "Active"
                and disorder.findtext("ClassificationLevel/Name") in {"Pathologie", "Sous-type d'une pathologie"}):
            if code in result:
                raise ValueError("ORPHAcode actif dupliqué")
            result.add(code)
    return result


def classification_codes(blob, spec):
    root = xml_root(blob)
    listing = root.find("ClassificationList")
    if root.tag != "JDBOR" or listing is None or listing.get("count") != "1" or len(listing) != 1:
        raise ValueError("classification Orphanet ambiguë")
    classification = listing[0]
    name = classification.find("Name")
    if (classification.tag != "Classification" or classification.get("id") != spec["id"]
            or name is None or name.get("lang") != "fr" or name.text != spec["title"]):
        raise ValueError("identité ou titre de classification différent du verrou")
    if root.findtext("Availability/Licence/ShortIdentifier") != "CC-BY-4.0":
        raise ValueError("licence de classification différente")
    result = set()
    for node in classification.findall(".//Disorder/OrphaCode"):
        if not re.fullmatch(r"[0-9]+", node.text or ""):
            raise ValueError("ORPHAcode de classification invalide")
        result.add(node.text)
    return result


def build_mapping(archive_path, lock):
    if archive_path.is_symlink():
        raise ValueError("lien symbolique source interdit")
    with archive_path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
            raise ValueError("archive Orphanet différente de l’édition verrouillée")
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            codes = active_codes(member(archive, MEMBER, {"sha256": XML_SHA256, "size": SIZE}))
            records, summaries = [], []
            for spec in lock["classifications"]:
                found = classification_codes(member(archive, spec["path"], spec), spec) & codes
                domain = "orpha-" + spec["id"]
                records.extend({"source_id": "orphanet-fr", "code": code, "domain": domain} for code in sorted(found))
                summaries.append({"domain": domain, "title": spec["title"], "codes": len(found), "member_sha256": spec["sha256"]})
    records.sort(key=lambda row: (row["source_id"], row["code"], row["domain"]))
    if len({(r["source_id"], r["code"], r["domain"]) for r in records}) != len(records):
        raise ValueError("affectation Orphanet dupliquée")
    covered = {row["code"] for row in records}
    return {
        "schema": 1, "scope": "official-domain-assignment-to-existing-codes", "source_id": "orphanet-fr",
        "edition": "2026", "source_url": lock["url"], "archive_sha256": ARCHIVE_SHA256,
        "nomenclature_sha256": XML_SHA256, "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Orphanet (c) 2026 — Inserm. Classifications françaises 2026, extraction du 23 juin 2026. CC BY 4.0.",
        "transformation": "Intersection des ORPHAcodes de chaque classification officielle avec les pathologies/sous-types actifs de la nomenclature ; dédoublonnage des répétitions. Aucune spécialité inférée ni libellé ajouté.",
        "active_codes": len(codes), "covered_codes": len(covered), "unassigned_codes": len(codes - covered),
        "classifications": summaries, "records": records,
    }


def prepare(archive, output, lock_path=LOCK):
    if output.exists() or output.is_symlink():
        raise ValueError("destination déjà présente ; choisir une sortie neuve")
    lock = json.loads(lock_path.read_text())
    result = build_mapping(archive, lock)
    blob = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    if sha(blob) != lock["mapping_sha256"]:
        raise ValueError("affectations différentes du verrou revu")
    with output.open("xb") as stream:
        stream.write(blob)
    return {key: value for key, value in result.items() if key != "records"} | {"records": len(result["records"]), "sha256": sha(blob)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.archive, args.output), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
