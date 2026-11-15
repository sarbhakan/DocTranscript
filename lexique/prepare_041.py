"""Prepare the reviewed 0.4.1 terminology additions, offline unless --fetch is explicit.

Official archives are read from verified file descriptors; no ZIP member is extracted
to its own path. Outputs are new snapshots, never replacements. This catalogue does
not modify an ASR model, infer prescriptions or correct dictated text.
"""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request
from xml.etree import ElementTree as ET
import zipfile

from .__main__ import HEADER, build, clean_text

HERE = Path(__file__).resolve().parent
LOCK = HERE / "sources-041.lock.json"
ADDITIONS = HERE / "manifest-additions-041.json"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
SKOS = "{http://www.w3.org/2004/02/skos/core#}"
ADICAP = "{https://data.esante.gouv.fr/adicap/}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ATC = set("ABCDGHJLMNPRSV")
CIS_HEADER = ["URI", "CIS", "libelle", "actif", "dateDebut", "dateFin", "codeATC", "libelleATC",
              "typeProcedureCourante", "statutCourant", "titulaireCourant", "niveauDeVirtualisation",
              "justificationNiveauVirtualisation", "prescriptibiliteEnDC", "justificationPrescriptibiliteEnDC",
              "formeStandardisee", "voie", "gamme"]


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def locked_bytes(path, spec):
    if path.is_symlink():
        raise ValueError("lien symbolique interdit pour une archive source")
    with path.open("rb") as stream:
        blob = stream.read(spec["size"] + 1)
    if len(blob) != spec["size"] or sha(blob) != spec["sha256"]:
        raise ValueError(f"source différente du verrou : {path.name}")
    return blob


def member(archive, name, spec):
    matches = [item for item in archive.infolist() if item.filename == name]
    if len(matches) != 1 or matches[0].is_dir() or matches[0].file_size != spec["size"]:
        raise ValueError(f"membre ZIP absent, dupliqué ou taille différente : {name}")
    with archive.open(matches[0]) as stream:
        blob = stream.read(spec["size"] + 1)
    if len(blob) != spec["size"] or sha(blob) != spec["sha256"]:
        raise ValueError(f"membre ZIP différent du verrou : {name}")
    return blob


def csv_rows(blob, header):
    reader = csv.DictReader(io.StringIO(blob.decode("utf-8-sig"), newline=""), strict=True)
    if reader.fieldnames != header:
        raise ValueError("en-tête CSV officiel différent du format revu")
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("nombre de colonnes CSV incorrect")
        yield row


def identifier(row, field, kind, pattern):
    code = row[field]
    if not re.fullmatch(pattern, code) or row["URI"] != "http://data.esante.gouv.fr/ansm/medicament/" + kind + "_" + code:
        raise ValueError("identifiant RUIM ou URI incohérent")
    return code


def ruim_rows(files):
    result = {name: [] for name in ("ruim-cis", "ruim-substances", "ruim-formes", "ruim-voies")}
    seen = set()
    for row in csv_rows(files["CIS.csv"], CIS_HEADER):
        code = identifier(row, "CIS", "SpecialitePharmaceutique", r"[0-9]{8}")
        if code in seen or row["actif"] not in {"true", "false"}:
            raise ValueError("CIS dupliqué ou statut actif inattendu")
        seen.add(code)
        if row["actif"] == "false":
            continue
        atc = row["codeATC"]
        if not re.fullmatch(r"[A-Z][0-9]{2}(?:[A-Z](?:[A-Z](?:[0-9]{2})?)?)?", atc) or atc[0] not in ATC:
            raise ValueError("code ATC hors du profil RUIM revu")
        result["ruim-cis"].append((code, row["libelle"], "medicament", "pharmacologie|ruim-atc-" + atc[0].lower()))
    tables = [
        ("Substances.csv", ["URI", "codeSubstance", "libelle_fr", "codeSMS", "synonymes_fr"],
         "ruim-substances", "codeSubstance", "Substance", r"[0-9]{5}", "libelle_fr", "substance"),
        ("Formes.csv", ["URI", "identifiant", "libelle"],
         "ruim-formes", "identifiant", "Forme", r"FT[0-9]{3}", "libelle", "forme-pharmaceutique"),
        ("Voies.csv", ["URI", "identifiant", "libelle", "codeRMS", "codeEDQM"],
         "ruim-voies", "identifiant", "Voie", r"[0-9]+", "libelle", "voie-administration"),
    ]
    for name, header, source, key, kind, pattern, label_key, category in tables:
        seen = set()
        for row in csv_rows(files[name], header):
            code = identifier(row, key, kind, pattern)
            if code in seen:
                raise ValueError("code RUIM dupliqué")
            seen.add(code)
            labels = [row[label_key]]
            if source == "ruim-substances" and row["synonymes_fr"]:
                labels += row["synonymes_fr"].split(" | ")
            for label in dict.fromkeys(labels):
                result[source].append((code, label, category, "pharmacologie"))
    return result


def xml_root(blob):
    if b"<!DOCTYPE" in blob or b"<!ENTITY" in blob:
        raise ValueError("DTD et entités XML interdites")
    return ET.fromstring(blob)


def adicap_rows(blob):
    root = xml_root(blob)
    if root.tag != RDF + "RDF":
        raise ValueError("racine RDF ADICAP incorrecte")
    result, seen = [], set()
    dictionaries = {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D8L"}
    for node in root:
        dictionary = node.findtext(ADICAP + "dictionaryCode")
        if dictionary is None:
            continue  # Ontology metadata, not terminology entries.
        if dictionary not in dictionaries:
            raise ValueError("dictionnaire ADICAP non revu")
        uri = node.get(RDF + "about", "")
        if not uri.startswith("https://data.esante.gouv.fr/adicap/"):
            raise ValueError("URI ADICAP étrangère")
        code = uri.rsplit("/", 1)[1]
        if not re.fullmatch(r"[A-Z0-9]+(?:\.[0-9]+)?", code) or code in seen:
            raise ValueError("code ADICAP invalide ou dupliqué")
        seen.add(code)
        if code in dictionaries or node.find(ADICAP + "endDate") is not None:
            continue  # Root headings and explicitly ended concepts are not counted.
        labels = node.findall(RDFS + "label")
        if len(labels) != 1 or labels[0].get(XML_LANG) != "fr" or labels[0].text is None:
            raise ValueError("libellé ADICAP français ambigu ou absent")
        category = "anatomie" if dictionary in {"D3", "D8", "D8L"} else "terme-anatomopathologique"
        result.append((code, labels[0].text, category, "anatomocytopathologie|adicap-" + dictionary.lower()))
    return result


def lahn_rows(blob):
    data = json.loads(blob)
    if (data.get("resourceType") != "CodeSystem" or data.get("id") != "terminologie-lahn"
            or data.get("version") != "2026-04" or data.get("content") != "complete"
            or len(data.get("concept", [])) != data.get("count")):
        raise ValueError("édition ou contenu LAHN inattendu")
    nodes = {}
    for concept in data["concept"]:
        code = concept["code"]
        if code in nodes:
            raise ValueError("code LAHN dupliqué")
        properties = {}
        for prop in concept.get("property", []):
            if prop["code"] in {"parent", "type"}:
                values = [value for key, value in prop.items() if key.startswith("value")]
                if prop["code"] in properties or len(values) != 1 or not isinstance(values[0], str):
                    raise ValueError("hiérarchie LAHN ambiguë")
                properties[prop["code"]] = values[0]
        nodes[code] = (concept["display"], properties)
    result = []
    for code, (label, props) in nodes.items():
        if props.get("type") != "code":
            continue
        current, visited = code, set()
        while True:
            if current in visited or current not in nodes:
                raise ValueError("cycle ou parent LAHN absent")
            visited.add(current)
            p = nodes[current][1]
            if p.get("type") == "Chapitre":
                if not re.fullmatch(r"(?:0[1-9]|1[0-7])", current) or p.get("parent") != "LAHN":
                    raise ValueError("chapitre LAHN inconnu")
                break
            current = p.get("parent")
        # Six reviewed display labels contain line breaks; keep every word while
        # representing a multiline FHIR display as a single catalogue line.
        label = re.sub(r"\r\n|\r|\n", " ", label)
        result.append((code, label, "examen", "biologie-medicale|lahn-" + current))
    return result


def encoded_rows(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HEADER)
    unique = set()
    for row in sorted(rows):
        clean_text(row[0], 160)
        clean_text(row[1], 500)
        if row in unique:
            raise ValueError("doublon exact inattendu dans l’extraction")
        unique.add(row)
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def fetch_sources(downloads, lock):
    downloads.mkdir(parents=True, exist_ok=True)
    for spec in lock["downloads"]:
        destination = downloads / spec["file"]
        if destination.exists() or destination.is_symlink():
            locked_bytes(destination, spec)
            continue
        with tempfile.TemporaryDirectory(dir=downloads, prefix=".source-") as directory:
            temporary = Path(directory) / "download.part"
            with temporary.open("xb") as stream:
                with urllib.request.urlopen(spec["url"], timeout=30) as response:
                    if not response.url.startswith("https://smt.esante.gouv.fr/"):
                        raise ValueError("redirection hors de la source officielle autorisée")
                    size = 0
                    while block := response.read(65536):
                        size += len(block)
                        if size > spec["size"]:
                            raise ValueError("téléchargement supérieur au verrou")
                        stream.write(block)
            # Close the handle before reopening/linking/unlinking on Windows.
            locked_bytes(temporary, spec)
            os.link(temporary, destination)


def prepare(downloads, output, *, lock_path=LOCK, manifest_path=ADDITIONS):
    if output.exists() or output.is_symlink():
        raise ValueError("destination déjà présente ; choisir un nouvel instantané")
    lock = json.loads(lock_path.read_text())
    specs = {item["id"]: item for item in lock["downloads"]}
    payloads = {key: locked_bytes(downloads / spec["file"], spec) for key, spec in specs.items()}
    ruim = specs["ruim"]
    with zipfile.ZipFile(io.BytesIO(payloads["ruim"])) as archive:
        nested = member(archive, ruim["csv_archive"]["path"], ruim["csv_archive"])
    with zipfile.ZipFile(io.BytesIO(nested)) as archive:
        files = {name: member(archive, name, spec) for name, spec in ruim["members"].items()}
    rows = ruim_rows(files)
    with zipfile.ZipFile(io.BytesIO(payloads["adicap"])) as archive:
        spec = specs["adicap"]["rdf"]
        rows["adicap-ans"] = adicap_rows(member(archive, spec["path"], spec))
    rows["lahn-ans"] = lahn_rows(payloads["lahn"])
    manifest = json.loads(manifest_path.read_text())
    if set(rows) != {source["id"] for source in manifest["sources"]}:
        raise ValueError("sources du manifeste différentes des extractions")
    with tempfile.TemporaryDirectory(prefix=".prepare-041-", dir=output.parent) as directory:
        stage = Path(directory)
        for source in manifest["sources"]:
            payload = encoded_rows(rows[source["id"]])
            if sha(payload) != source["sha256"]:
                raise ValueError(f"extraction CSV différente du manifeste : {source['id']}")
            source["file"] = source["id"] + ".csv"
            (stage / source["file"]).write_bytes(payload)
        compiled_manifest = stage / "manifest.json"
        compiled_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        counts = build(compiled_manifest, stage / "additions.sqlite")
        os.link(stage / "additions.sqlite", output)
    return {"schema": 1, "catalogue_schema": 2, "sources_lock_sha256": sha(lock_path.read_bytes()),
            "manifest_sha256": sha(manifest_path.read_bytes()), "counts": counts,
            "source_bytes": sum(spec["size"] for spec in specs.values()),
            "training_performed": False, "asr_changed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="acquérir les trois sources publiques avant construction")
    args = parser.parse_args()
    try:
        if args.fetch:
            fetch_sources(args.downloads, json.loads(LOCK.read_text()))
        report = prepare(args.downloads, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, csv.Error, ET.ParseError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
