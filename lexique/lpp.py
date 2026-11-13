"""Convert the public CNAM LPP dBase archive to a local catalogue CSV."""

import argparse
from collections import Counter
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import unicodedata
from zipfile import BadZipFile, ZipFile


LIMIT = 32 * 1024 * 1024
CODE = re.compile(rb"[0-9]{7}")
MEMBER = re.compile(r"lpp_(fiche|histo)_tot([0-9]+)\.dbf", re.I)
HEADER = ("code", "libelle", "categorie", "specialites")


def dbf_rows(data, required):
    if len(data) < 33 or data[0] != 3:
        raise ValueError("table dBase III non reconnue")
    count, header_len, record_len = struct.unpack_from("<IHH", data, 4)
    data_end = header_len + count * record_len
    if (header_len < 33 or (header_len - 33) % 32 or header_len > len(data)
            or data[header_len - 1] != 13 or record_len < 2 or data_end > len(data)
            or data[data_end:] not in (b"", b"\x1a")):
        raise ValueError("taille, en-tête ou fin de table dBase invalide")
    columns = {}
    names = set()
    position = 1
    for start in range(32, header_len - 1, 32):
        name = data[start:start + 11].split(b"\0", 1)[0].decode("ascii")
        kind, width = chr(data[start + 11]), data[start + 16]
        if not name or name in names or not width:
            raise ValueError("colonne dBase invalide")
        names.add(name)
        if name in required:
            if (kind, width) != required[name]:
                raise ValueError(f"type ou largeur inattendus pour {name}")
            columns[name] = slice(position, position + width)
        position += width
    if position != record_len or set(columns) != set(required):
        raise ValueError("colonnes requises ou longueur d’enregistrement invalides")
    for start in range(header_len, data_end, record_len):
        status = data[start]
        if status == 42:  # dBase deleted record
            continue
        if status != 32:
            raise ValueError("statut d’enregistrement dBase inconnu")
        record = data[start:start + record_len]
        yield tuple(record[columns[name]].rstrip(b" ") for name in required)


def dbf_date(value):
    if value in (b"", b"00000000"):
        return None
    if not re.fullmatch(rb"[0-9]{8}", value):
        raise ValueError("date dBase non reconnue")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def convert(raw, expected_sha256, as_of, encoding):
    if len(raw) > LIMIT:
        raise ValueError("archive LPP supérieure à 32 Mio")
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != expected_sha256:
        raise ValueError("SHA-256 de l’archive différent de l’empreinte attendue")
    with ZipFile(io.BytesIO(raw)) as archive:
        members = {}
        editions = set()
        for info in archive.infolist():
            match = MEMBER.fullmatch(info.filename)
            if match is None:
                continue
            kind, edition = match.groups()
            kind = kind.lower()
            if kind in members or info.file_size > LIMIT:
                raise ValueError("table LPP en double ou trop volumineuse")
            members[kind] = info
            editions.add(edition)
        if set(members) != {"fiche", "histo"} or len(editions) != 1:
            raise ValueError("fichiers LPP de codes et d’historiques de même version requis")
        tables = {kind: archive.read(info) for kind, info in members.items()}

    valid_history = set()
    counts = Counter({"codes_lus": 0, "historiques_lus": 0, "codes_sortis": 0,
                      "codes_radiés": 0, "sans_historique_valide": 0,
                      "historiques_sans_début": 0})
    for code, start, end in dbf_rows(tables["histo"], {
            "CODE_TIPS": ("C", 13), "DEBUTVALID": ("D", 8), "FINHISTO": ("D", 8)}):
        counts["historiques_lus"] += 1
        if not CODE.fullmatch(code):
            raise ValueError("code d’historique LPP non conforme")
        first, last = dbf_date(start), dbf_date(end)
        if first is None:
            counts["historiques_sans_début"] += 1
        elif last is not None and last < first:
            raise ValueError("fin d’historique antérieure à son début")
        elif first <= as_of and (last is None or as_of <= last):
            valid_history.add(code)

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    seen = set()
    for code, name, end in dbf_rows(tables["fiche"], {
            "CODE_TIPS": ("C", 13), "NOM_COURT": ("C", 80), "DATE_FIN": ("D", 8)}):
        counts["codes_lus"] += 1
        if code in seen or not CODE.fullmatch(code):
            raise ValueError("code LPP non conforme ou en double")
        seen.add(code)
        removed = dbf_date(end)
        if removed is not None and removed <= as_of:
            counts["codes_radiés"] += 1
        elif code not in valid_history:
            counts["sans_historique_valide"] += 1
        else:
            label = name.decode(encoding)
            if not label.strip() or any(unicodedata.category(c) in {"Cc", "Cs"} for c in label):
                raise ValueError(f"nom court LPP invalide pour {code.decode('ascii')}")
            writer.writerow((code.decode("ascii"), label, "produit-prestation", ""))
            counts["codes_sortis"] += 1

    if not counts["codes_sortis"]:
        raise ValueError("aucun code LPP avec un historique valide à cette date")
    csv_bytes = out.getvalue().encode("utf-8")
    return csv_bytes, {
        **counts, "date_filtre": as_of.isoformat(), "édition_membres": next(iter(editions)),
        "encodage_source": encoding, "sha256_archive": source_sha256,
        "sha256_csv": hashlib.sha256(csv_bytes).hexdigest(),
        "fichiers_dbf": {kind: {"nom": members[kind].filename, "sha256": hashlib.sha256(table).hexdigest()}
                         for kind, table in tables.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sha256", required=True, help="empreinte SHA-256 revue de l’archive source")
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="date de publication de l’archive en AAAA-MM-JJ")
    parser.add_argument("--encoding", choices=("cp1252", "iso-8859-1"), required=True,
                        help="encodage des libellés vérifié pour l’édition")
    args = parser.parse_args()
    try:
        with args.archive.open("rb") as source:
            data = source.read(LIMIT + 1)
        csv_bytes, report = convert(data, args.sha256, args.date, args.encoding)
        with args.output.open("xb") as dest:
            dest.write(csv_bytes)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, BadZipFile, RuntimeError) as error:
        print(f"Import LPP : {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
