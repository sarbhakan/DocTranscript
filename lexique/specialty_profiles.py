"""Compile offline clinical specialty glossaries from pinned French datasets."""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from .__main__ import import_rows, source_list
from .orphanet import ARCHIVE_SHA256


BASE = Path(__file__).resolve().parent
PINNED = {
    "orphanet": ARCHIVE_SHA256,
    "phenotypes": "526123718342e00b1905b79ed9de265a9fc51fc8bbe57a7e3852100f65fb4bd8",
    "hpo": "370807fa818cf8b65c3d0c1ee6a32e2ad4860cdaf036371ec53f3c3e8b87f8a3",
    "medicam": "65b917fa2586ad76c1cea5831bcc1b2b88c29cf26de19571d92f282684103e27",
}
MAX_BYTES = 16 * 1024 * 1024
MAX_TERMS = 10_000
MAX_COMMON = 3_200
MIN_TERMS = 5_000
PROTECTED = frozenset("""
zero un une deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze
seize vingt trente quarante cinquante soixante cent cents mille virgule demi quart demie quarts
milligramme milligrammes microgramme microgrammes gramme grammes millilitre millilitres litre
litres nanogramme nanogrammes millimetre millimetres kilogramme kilogrammes mg ml mcg ug µg ui
pas aucun aucune sans droite droit gauche negatif negative ni non absence dose doses dosage
dosages posologie posologies comprime comprimes pourcentage quotient
""".split())

NABM = {
    "cardio": r"troponin|cardia|lipid|cholesterol|triglycerid|natriuretic|coagula",
    "hemo": r"hemato|hemoglobi|leucocy|lympho|plaquet|coagula|fibrin|thrombo|haptoglo",
    "neuro": r"cerebro|neurolog|neuron|liquide cephalo|acetylcholin|myeline",
    "infection": r"infection|microbi|serolog|bacter|viru|viral|parasito|mycolog|antibiogra|anticorps|levur|cultu|pcr",
    "cancer": r"tumora|cancer|carcin|histopath|cytopath|immunohisto|cytogene|onco|biops",
    "eyes": r"oculaire|conjonctiv|cornee|retin|lacrym",
    "kidney": r"renal|creatini|albumin|proteinurie|urine|urinaire|electrolyt|glomerul",
    "internal": r"autoimmu|anticorps|immunoglob|antinucle|immuno|inflamm|complement",
    "genes": r"genetiqu|chromoso|caryotyp|sequenc|genom|mutation",
    "lung": r"pulmon|bronch|expectora|respir|alveol|pleur|tubercul",
    "skin": r"derm|cutan|mycolog|phaner|keratin",
    "gastro": r"gastro|digest|hepat|pancre|intestin|bili|selles|fecal",
    "child": r"pediatr|neonata|nourris|foetal|croissance|enfant",
}

@dataclass(frozen=True)
class Spec:
    label: str
    direct: tuple = ()
    related: tuple = ()
    hpo: tuple = ()
    ccam: tuple = ()
    emdn: tuple = ()
    cisp: tuple = ()
    atc: tuple = ()
    lab: str = ""


SPECS = {
    "medecine-generale": Spec("Médecine générale", cisp=tuple("ABDFHKLNPRSTUWXYZ")),
    "cardiologie": Spec("Cardiologie", (146, 148), (198,), ("0001626",), ("D", "E"), ("C", "J01", "J02", "P07"), ("K",), ("C", "B01"), "cardio"),
    "hematologie": Spec("Hématologie", (194,), (195,), ("0001871",), ("FD", "FE", "FF", "FG"), ("B", "W0103"), ("B",), ("B", "L01"), "hemo"),
    "neurologie": Spec("Neurologie", (181,), (), ("0000707",), ("A",), ("N",), ("N",), ("N02C", "N03", "N04", "N06D", "N07"), "neuro"),
    "infectiologie": Spec("Infectiologie", (203,), (195,), ("0002719",), (), ("W01",), (), ("J", "P01", "P02", "D01"), "infection"),
    "oncologie": Spec("Oncologie", (202,), (), ("0002664",), (), ("Z1101", "Z1102"), (), ("L01", "L02", "L03", "A04"), "cancer"),
    "ophtalmologie": Spec("Ophtalmologie", (189,), (), ("0000478",), ("B",), ("Q02", "Z1212"), ("F",), ("S01",), "eyes"),
    "pediatrie": Spec("Pédiatrie", (147, 231), (148, 150), ("0001197", "0001507"), (), ("Z1208",), ("W",), (), "child"),
    "nephrologie": Spec("Néphrologie", (188,), (185,), ("0000077",), ("JA", "JB", "JC"), ("F", "U"), ("U",), ("C02", "C03", "V03A", "B03"), "kidney"),
    "medecine-interne": Spec("Médecine interne", (195, 196, 212), (231, 204), ("0002715", "0001939"), (), (), (), ("L04", "H02", "M01"), "internal"),
    "genetique": Spec("Génétique médicale", (156,), (147, 150), ("0000118",), (), (), (), (), "genes"),
    "pneumologie": Spec("Pneumologie", (184,), (186,), ("0002086",), ("GE", "GF", "GG", "GH", "GL"), ("R",), ("R",), ("R03", "R05", "J04"), "lung"),
    "dermatologie": Spec("Dermatologie", (187,), (), ("0001574",), ("Q",), ("M",), ("S",), ("D",), "skin"),
    "gastroenterologie": Spec("Gastro-entérologie", (152, 183), (182,), ("0025031",), ("HE", "HF", "HG", "HH", "HJ", "HK", "HL", "HM", "HN"), ("G",), ("D",), ("A02", "A03", "A06", "A07", "A09"), "gastro"),
}

@dataclass(frozen=True)
class Term:
    label: str
    source: str
    code: str
    category: str
    priority: int


def fold(label):
    return "".join(c for c in unicodedata.normalize("NFD", label.casefold())
                   if not unicodedata.combining(c)).replace("’", "'")


def label_key(label):
    return fold(label)


def clean(label):
    return unicodedata.normalize("NFC", " ".join(label.split()))


def eligible(label):
    if not 4 <= len(label.encode("utf-8")) <= 160:
        return False
    if not all(c.isalpha() or c in " -'’" for c in label):
        return False
    words = re.findall(r"[^\W\d_]+", fold(label))
    return 1 <= len(words) <= 10 and not PROTECTED.intersection(words)


def checked(path, name):
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != PINNED[name]:
            raise ValueError(f"{name} : SHA-256 différent de l’édition attendue")


def classifications(path):
    result = {}
    wanted = set().union(*(s.direct + s.related for s in SPECS.values()))
    with zipfile.ZipFile(path) as archive:
        for item in archive.namelist():
            match = re.search(r"/Classifications/ORPHAclassification_(\d+)_.*_fr_2026\.xml$", item)
            if match and (code := int(match[1])) in wanted:
                root = ET.fromstring(archive.read(item))
                result[code] = {node.text for node in root.findall(".//Disorder/OrphaCode")}
    if result.keys() != wanted:
        raise ValueError("classifications Orphanet manquantes")
    return result


def ontology(path):
    terms, parents = {}, {}
    for record in path.read_text(encoding="utf-8").split("\n[Term]\n")[1:]:
        lines = record.splitlines()
        code = next((line[7:] for line in lines if line.startswith("id: HP:")), "")
        if not re.fullmatch(r"\d{7}", code) or "is_obsolete: true" in lines:
            continue
        parents[code] = {line.split()[1][3:] for line in lines if line.startswith("is_a: HP:")}
        for line in lines:
            if line.startswith("name: ") and 'babelon:translation_status="OFFICIAL"' in line and 'babelon:translation_language="fr"' in line:
                terms[code] = clean(line[6:].split(" {", 1)[0])
                break
    if len(terms) < 8_000:
        raise ValueError("traductions françaises HPO absentes")
    return terms, parents


def descendants(parents, roots):
    seen = set(roots)
    children = defaultdict(set)
    for child, ancestors in parents.items():
        for parent in ancestors:
            children[parent].add(child)
    pending = list(seen)
    while pending:
        for child in children[pending.pop()] - seen:
            seen.add(child)
            pending.append(child)
    return seen


def associated_phenotypes(path):
    associations = {}
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag != "HPODisorderSetStatus":
            continue
        disease = node.find("Disorder")
        if disease is None:
            raise ValueError("association Orphadata sans pathologie")
        code = disease.findtext("OrphaCode", "")
        linked = set()
        for item in disease.findall("HPODisorderAssociationList/HPODisorderAssociation"):
            frequency = item.findtext("HPOFrequency/Name", "")
            if frequency.casefold().startswith(("absent", "exclu")):
                continue
            hpo = item.findtext("HPO/HPOId", "")
            if hpo.startswith("HP:"):
                linked.add(hpo[3:])
        associations.setdefault(code, set()).update(linked)
        node.clear()
    if len(associations) < 4_000:
        raise ValueError("associations Orphadata absentes")
    return associations


def medicines(path):
    with zipfile.ZipFile(path) as archive:
        workbook = archive.read("2025_medic-am-par-classe-atc_cumul-annuel.xlsx")
    with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
        strings = ["".join(node.text or "" for node in item.findall(".//{*}t"))
                   for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]

        def rows(sheet, headers):
            root = ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet}.xml"))
            for row in root.findall(".//{*}row"):
                number = int(row.get("r"))
                if number < 6:
                    continue
                cells = {cell.get("r").rstrip("0123456789"):
                         strings[int(value.text)] if cell.get("t") == "s" else value.text
                         for cell in row if (value := cell.find("{*}v")) is not None}
                if number == 6:
                    if [cells.get(col) for col in headers] != list(headers.values()):
                        raise ValueError("en-tête Medic’AM inattendu")
                else:
                    yield [cells.get(col, "") for col in headers]

        counts = defaultdict(int)
        for code, label, boxes in rows(10, {"A": "Code ATC5", "B": "Libellé ATC5", "D": "Nombre de boites remboursées \n2025"}):
            if re.fullmatch(r"[A-Z]\d\d[A-Z][A-Z]\d\d", code):
                counts[code] = max(0, int(float(boxes or "0")))
                yield Term(clean(label), "medicam", code, "substance", counts[code])
        products = defaultdict(int)
        for name, code, boxes in rows(12, {"C": "PRODUIT", "F": "Code ATC5", "K": "Nombre de boites remboursées \n2025"}):
            label = clean(name)
            # Keep the official dedicated PRODUIT field verbatim; do not trim
            # quantities from packs or infer a proprietary name from NOM COURT.
            if re.fullmatch(r"[A-Z]\d\d[A-Z][A-Z]\d\d", code) and label and not re.search(r"\d|[/+%]", label):
                products[code, label] += max(0, int(float(boxes or "0")))
        for (code, label), boxes in products.items():
            yield Term(label, "medicam", code, "produit", boxes)


def source_terms(manifest):
    metadata, terms = [], defaultdict(list)
    for src, path in source_list(manifest):
        source = src["id"]
        if source not in {"orphanet-fr", "cisp2-ans", "emdn-ans", "ccam-ans", "nabm-ans"}:
            continue
        metadata.append({k: v for k, v in src.items() if k not in {"file", "encoding"}})
        for _, code, label, category, _, kind in import_rows(src, path):
            if source == "ccam-ans" and not re.fullmatch(r"[A-Z]{4}\d{3}", code):
                continue
            if source == "cisp2-ans" and not re.fullmatch(r"[A-Z]\d\d", code):
                continue
            terms[source].append(Term(clean(label), source, code, category, int(kind != "synonyme")))
    if len(metadata) != 5:
        raise ValueError("sources terminologiques attendues absentes")
    return metadata, terms


def choose_profile(key, spec, terms, orpha, hpo, parents, links):
    direct_codes = set().union(*(orpha[i] for i in spec.direct))
    adjacent_codes = set().union(*(orpha[i] for i in spec.related)) - direct_codes
    phenotypes = Counter(code for disease in direct_codes for code in links.get(disease, ()))
    related_hpo = Counter(code for disease in adjacent_codes for code in links.get(disease, ()))
    all_frequency = terms["phenotype-frequency"]
    branch = descendants(parents, spec.hpo)
    direct, adjacent, common = [], [], []
    for term in terms["orphanet-fr"]:
        if term.code in direct_codes:
            direct.append(term)
        elif term.code in adjacent_codes:
            adjacent.append(term)
    for code, label in hpo.items():
        frequency = all_frequency[code]
        if code in branch and code not in spec.hpo:
            direct.append(Term(label, "hpo", f"HP:{code}", "phenotype", phenotypes[code]))
        elif phenotypes[code] >= 2 and phenotypes[code] * 4 >= max(1, frequency):
            direct.append(Term(label, "hpo", f"HP:{code}", "phenotype", phenotypes[code]))
        elif phenotypes[code] >= 1 or related_hpo[code] >= 2:
            adjacent.append(Term(label, "hpo", f"HP:{code}", "phenotype", phenotypes[code] + related_hpo[code]))
        elif frequency >= 4:
            common.append(Term(label, "hpo", f"HP:{code}", "phenotype", frequency))
    for term in terms["cisp2-ans"]:
        # 01–29 symptoms/complaints, 70–99 diseases; omit the administrative part.
        if 1 <= int(term.code[1:]) <= 29 or 70 <= int(term.code[1:]) <= 99:
            (direct if term.code.startswith(spec.cisp) else common).append(term)
    for term in terms["ccam-ans"]:
        if term.code.startswith(spec.ccam):
            direct.append(term)
        elif key == "oncologie" and re.search(r"tumor|tumeur|radiother|chimiother|curiether|tumorectom|carcinom", fold(term.label)):
            direct.append(term)
        elif key == "pediatrie" and re.search(r"enfant|nourrisson|nouveau-ne|neonatal|pediatr|foet", fold(term.label)):
            direct.append(term)
        elif re.search(r"^([eé]chographie|[eé]lectrocardiographie|radiographie|scanographie|t[eé]l[eé]consultation) ", term.label, re.I):
            common.append(term)
    for term in terms["emdn-ans"]:
        if term.code.startswith(spec.emdn):
            direct.append(term)
        elif term.code.startswith(("A01", "A02", "D", "H", "M", "S", "T")):
            common.append(term)
    for term in terms["nabm-ans"]:
        if spec.lab and re.search(NABM[spec.lab], fold(term.label)):
            direct.append(term)
        else:
            common.append(term)
    for term in terms["medicam"]:
        if key == "medecine-generale" or term.code.startswith(spec.atc):
            direct.append(term)
        elif term.priority >= 10_000:
            common.append(term)
    return direct, adjacent, common


def sort_term(term):
    priority = term.priority if term.source != "medicam" else term.priority.bit_length()
    return (-priority, len(term.label), label_key(term.label), term.label, term.source, term.code)


def shortlist(key, selected):
    quotas = (("orphanet-fr", 60), ("hpo", 45), ("cisp2-ans", 16), ("medicam", 60),
              ("ccam-ans", 15), ("emdn-ans", 10), ("nabm-ans", 10))
    out = []
    for source, cap in quotas:
        candidates = [term for term, scope in selected.values()
                      if term.source == source and eligible(term.label)
                      and (scope == "specialty" or (source == "hpo" and key == "medecine-generale"))]
        # Prescription brands are a distinct lexical category. Alternate their
        # selection with substances instead of privileging the larger one.
        if source == "medicam":
            for category in ("substance", "produit"):
                out.extend(t.label for t in sorted((t for t in candidates if t.category == category), key=sort_term)[:cap // 2])
        else:
            out.extend(t.label for t in sorted(candidates, key=sort_term)[:cap])
    return out


def pack_profile(key, spec, direct, adjacent, common, provenance=None):
    selected = {}
    for scope, items, cap in (("specialty", direct, MAX_TERMS), ("related", adjacent, MAX_TERMS),
                              ("shared", common, MAX_COMMON)):
        count = 0
        for term in sorted(items, key=sort_term):
            label = term.label
            if not label or len(label.encode("utf-8")) > 512:
                continue
            k = label_key(label)
            if k in selected:
                continue
            if count == cap or len(selected) == MAX_TERMS:
                break
            selected[k] = term, scope
            count += 1
    counts = Counter(scope for _, scope in selected.values())
    types = Counter(term.category for term, _ in selected.values())
    source_counts = Counter(term.source for term, _ in selected.values())
    entries = [selected[k][0].label for k in sorted(selected)]
    active = shortlist(key, selected)
    if provenance is not None:
        boosted = set(active)
        for k in sorted(selected):
            term, scope = selected[k]
            provenance.append((key, term.label, term.source, term.code, term.category,
                               scope, int(term.label in boosted)))
    return {"id": key, "label": spec.label, "entries": entries,
            "active": active,
            "statistics": {"specialty": counts["specialty"], "related": counts["related"], "shared": counts["shared"],
                           "target_met": len(entries) >= MIN_TERMS, "by_source": dict(sorted(source_counts.items())),
                           "by_category": dict(sorted(types.items()))},
            "classification": {"orphanet_direct": list(spec.direct), "orphanet_related": list(spec.related),
                               "hpo_branches": [f"HP:{code}" for code in spec.hpo],
                               "ccam_prefixes": list(spec.ccam), "emdn_prefixes": list(spec.emdn),
                               "cisp2_chapters": list(spec.cisp), "atc_prefixes": list(spec.atc)}}


EXTRA_SOURCES = (
    {"id": "orphanet-classification", "title": "Orphanet — classifications françaises", "edition": "Paquet FR 2026",
     "url": "https://www.orphacode.org/pack-nomenclature/", "license_url": "https://creativecommons.org/licenses/by/4.0/",
     "attribution": "Orphanet (c) 2026 — Inserm, classifications françaises 2026, sous CC BY 4.0.", "sha256": PINNED["orphanet"]},
    {"id": "orphadata-phenotypes", "title": "Orphadata Science — signes et symptômes associés aux maladies rares",
     "edition": "Extraction du 23 juin 2026", "url": "https://sciences.orphadata.com/phenotypes/",
     "download": "https://www.orphadata.com/data/xml/fr_product4.xml", "license_url": "https://creativecommons.org/licenses/by/4.0/",
     "attribution": "Orphadata Science — Inserm, associations maladies/manifestations (2026), sous CC BY 4.0.", "sha256": PINNED["phenotypes"]},
    {"id": "hpo", "title": "Human Phenotype Ontology — libellés français officiels", "edition": "v2026-09-01",
     "url": "https://github.com/obophenotype/human-phenotype-ontology/releases/tag/v2026-09-01",
     "download": "https://github.com/obophenotype/human-phenotype-ontology/releases/download/v2026-09-01/hp-fr.obo",
     "license_url": "https://human-phenotype-ontology.github.io/license.html",
     "attribution": "Human Phenotype Ontology Consortium, Köhler et al., DOI 10.1093/nar/gkt1026 ; traduction française coordonnée par Orphanet (Inserm).", "sha256": PINNED["hpo"]},
    {"id": "medicam", "title": "Cnam — Medic’AM par classe ATC", "edition": "Cumul annuel 2025 publié le 20 avril 2026",
     "url": "https://www.assurance-maladie.ameli.fr/etudes-et-donnees/medicaments-classe-atc-medicam",
     "download": "https://www.assurance-maladie.ameli.fr/sites/default/files/2025_medic-am-par-classe-atc_cumul-annuel.zip",
     "attribution": "Caisse nationale de l’Assurance Maladie, Medic’AM par classe ATC, cumul annuel 2025, données ouvertes. Libellés ATC5 et PRODUIT ; aucun montant ni volume dans le catalogue.", "sha256": PINNED["medicam"]},
)


def build(manifest, archive, phenotypes, hpo_file, medicam, provenance=None):
    for path, name in ((archive, "orphanet"), (phenotypes, "phenotypes"), (hpo_file, "hpo"), (medicam, "medicam")):
        checked(path, name)
    metadata, terms = source_terms(manifest)
    orpha = classifications(archive)
    hpo, parents = ontology(hpo_file)
    links = associated_phenotypes(phenotypes)
    terms["phenotype-frequency"] = Counter(code for labels in links.values() for code in labels)
    terms["medicam"] = list(medicines(medicam))
    profiles = [pack_profile(key, spec, *choose_profile(key, spec, terms, orpha, hpo, parents, links),
                             provenance=provenance)
                for key, spec in SPECS.items()]
    return {"schema": 1, "profiles": profiles, "sources": [*metadata, *EXTRA_SOURCES]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=BASE / "manifest-essai-public.json")
    parser.add_argument("--orphanet", type=Path, default=BASE / "private/sources/Orphanet_Nomenclature_Pack_FR.zip")
    for name in ("phenotypes", "hpo", "medicam", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--with-provenance", action="store_true",
                        help="écrit aussi provenance.tsv pour l’audit local, sans modifier profiles.json")
    args = parser.parse_args()
    try:
        provenance = [] if args.with_provenance else None
        catalogue = build(args.manifest, args.orphanet, args.phenotypes, args.hpo, args.medicam, provenance)
        data = (json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > MAX_BYTES:
            raise ValueError("catalogue trop volumineux pour l’application")
        args.output.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=args.output, prefix=".profiles-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temporary, args.output / "profiles.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
        if provenance is not None:
            fd, temporary = tempfile.mkstemp(dir=args.output, prefix=".provenance-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                    writer.writerow(("profile", "label", "source", "code", "category", "scope", "active"))
                    writer.writerows(provenance)
                os.replace(temporary, args.output / "provenance.tsv")
            finally:
                Path(temporary).unlink(missing_ok=True)
        print(json.dumps({p["id"]: {"entries": len(p["entries"]), "active": len(p["active"]), **p["statistics"]}
                          for p in catalogue["profiles"]}, ensure_ascii=False, indent=2))
    except (KeyError, OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
