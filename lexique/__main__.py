"""Compile and query a local terminology catalogue from reviewed source files."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET


MANIFEST_VERSION = 1
CATALOGUE_VERSION = 2
CATEGORIES = {"maladie", "symptome", "acte", "examen", "dispositif", "produit-prestation",
              "medicament", "substance", "anatomie", "motif-plainte", "diagnostic-soins-primaires",
              "forme-pharmaceutique", "voie-administration", "terme-anatomopathologique"}
FORMATS = {"csv", "bdpm-cis", "bdpm-compo", "orphanet-nomenclature-fr"}
KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEADER = ["code", "libelle", "categorie", "specialites"]
DDL = """
PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;
CREATE TABLE source (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, edition TEXT NOT NULL, publication_date TEXT NOT NULL,
  url TEXT NOT NULL, license_url TEXT NOT NULL, attribution TEXT NOT NULL, sha256 TEXT NOT NULL,
  format TEXT NOT NULL, note TEXT NOT NULL
);
CREATE TABLE term (
  id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source(id), code TEXT NOT NULL,
  label TEXT NOT NULL, search_label TEXT NOT NULL, category TEXT NOT NULL,
  label_kind TEXT NOT NULL CHECK(label_kind IN ('libelle-source', 'principal', 'synonyme')),
  UNIQUE(source_id, code, label)
);
CREATE TABLE specialty (
  term_id INTEGER NOT NULL REFERENCES term(id), name TEXT NOT NULL, PRIMARY KEY(term_id, name)
) WITHOUT ROWID;
CREATE INDEX specialty_by_name ON specialty(name, term_id);
CREATE INDEX term_by_category ON term(category);
CREATE VIRTUAL TABLE term_fts USING fts5(search_label, content='term', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2', prefix='2 3');
"""


def clean_text(value, max_len=1000):
    if (not isinstance(value, str) or not value.strip() or len(value) > max_len
            or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)):
        raise ValueError("libellé ou métadonnée absent, trop long ou non textuel")
    return value


def search_form(text):
    text = unicodedata.normalize("NFC", text).casefold().replace("œ", "oe").replace("æ", "ae")
    return re.sub(r"\b[cdjlmnst]['’ʼ]", "", text)


def source_file(root, name):
    path = Path(name)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise ValueError("chemin source non relatif au manifeste")
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("fichier source hors du dossier du manifeste")
    return resolved


def source_list(manifest):
    root = manifest.resolve(strict=True).parent
    cfg = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if type(cfg["schema"]) is not int or cfg["schema"] != MANIFEST_VERSION or not cfg["sources"]:
        raise ValueError("schéma du manifeste non pris en charge ou aucune source")
    seen = set()
    for src in cfg["sources"]:
        key = src["id"]
        if not KEY.fullmatch(key) or key in seen or src["format"] not in FORMATS:
            raise ValueError("identifiant source, doublon ou format invalide")
        seen.add(key)
        if src.get("scope") != "catalogue-local" or not SHA.fullmatch(src["sha256"]):
            raise ValueError(f"{key} : portée revue et empreinte SHA-256 requises")
        date = dt.date.fromisoformat(src["publication_date"])
        if date.isoformat() != src["publication_date"]:
            raise ValueError(f"{key} : date ISO attendue (AAAA-MM-JJ)")
        for field in ("title", "edition", "attribution", "note"):
            clean_text(src[field])
        for field in ("url", "license_url"):
            url = urlsplit(clean_text(src[field]))
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError(f"{key} : URL HTTPS sans identifiants requise")
        if src.get("encoding", "utf-8-sig") not in {"utf-8-sig", "cp1252", "iso-8859-1"}:
            raise ValueError(f"{key} : encodage explicite non pris en charge")
        yield src, source_file(root, src["file"])


def import_rows(src, path):
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("source supérieure à 128 Mio ; scinder en extractions tracées")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != src["sha256"]:
        raise ValueError(f"{src['id']} : SHA-256 différent du manifeste")
    stream = io.StringIO(blob.decode(src.get("encoding", "utf-8-sig")), newline="")
    mode = src["format"]
    if mode == "orphanet-nomenclature-fr":
        xml = stream.getvalue()
        if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
            raise ValueError("DTD et entités XML interdites")
        root = ET.fromstring(xml)
        disorders = root.find("DisorderList")
        if root.tag != "JDBOR" or disorders is None or len(disorders) != int(disorders.get("count", "-1")):
            raise ValueError("structure XML de nomenclature Orphanet inattendue")
        for line, disorder in enumerate(disorders, 1):
            code = disorder.findtext("OrphaCode", "")
            if disorder.tag != "Disorder" or not re.fullmatch(r"[0-9]+", code):
                raise ValueError(f"entité Orphanet invalide à la position {line}")
            if disorder.findtext("Totalstatus") != "Active":
                continue
            level = disorder.findtext("ClassificationLevel/Name")
            if level not in {"Pathologie", "Sous-type d'une pathologie"}:
                continue
            labels = [disorder.find("Name"), *disorder.findall("SynonymList/Synonym")]
            for index, label in enumerate(labels):
                if label is None or label.get("lang") != "fr" or label.text is None:
                    raise ValueError(f"libellé français absent à la position {line}")
                yield line, code, label.text, "maladie", [], "principal" if index == 0 else "synonyme"
        return
    if mode == "csv":
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != HEADER:
            raise ValueError(f"{src['id']} : attendu {','.join(HEADER)}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{src['id']} ligne {reader.line_num} : nombre de champs invalide")
            tags = row["specialites"].split("|") if row["specialites"] else []
            yield reader.line_num, row["code"], row["libelle"], row["categorie"], tags, "libelle-source"
    else:
        reader = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE, strict=True)
        for row in reader:
            if not row:
                continue
            if len(row) < (2 if mode == "bdpm-cis" else 7) or not re.fullmatch(r"\d{8}", row[0]):
                raise ValueError(f"{src['id']} ligne {reader.line_num} : structure BDPM invalide")
            if mode == "bdpm-cis":
                yield reader.line_num, row[0], row[1], "medicament", [], "libelle-source"
            else:
                if not re.fullmatch(r"\d+", row[2]) or row[6] not in {"SA", "ST", "FT"}:
                    raise ValueError(f"{src['id']} ligne {reader.line_num} : code ou nature de substance invalide")
                # Keep the official label verbatim; ignore separate strength and instruction fields.
                if row[6] == "SA":
                    yield reader.line_num, row[2], row[3], "substance", [], "libelle-source"


def build(manifest, destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination déjà présente ; créer un nouvel instantané")
    with tempfile.TemporaryDirectory(prefix=".lexique-", dir=destination.parent) as tmp:
        stage = Path(tmp) / "catalogue.sqlite"
        con = sqlite3.connect(stage)
        try:
            con.executescript(DDL)
            with con:
                for src, path in source_list(manifest):
                    values = [src[key] for key in ("id", "title", "edition", "publication_date", "url", "license_url",
                                                   "attribution", "sha256", "format", "note")]
                    con.execute("INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
                    count = 0
                    for line, code, label, category, tags, label_kind in import_rows(src, path):
                        clean_text(code, 160)
                        clean_text(label, 500)
                        if category not in CATEGORIES or any(not KEY.fullmatch(tag) for tag in tags):
                            raise ValueError(f"{src['id']} ligne {line} : catégorie ou spécialité invalide")
                        con.execute("INSERT INTO term(source_id,code,label,search_label,category,label_kind) "
                                    "VALUES (?, ?, ?, ?, ?, ?) "
                                    "ON CONFLICT(source_id,code,label) DO NOTHING",
                                    (src["id"], code, label, search_form(label), category, label_kind))
                        term_id, original_category = con.execute(
                            "SELECT id, category FROM term WHERE source_id=? AND code=? AND label=?",
                            (src["id"], code, label)).fetchone()
                        if original_category != category:
                            raise ValueError(f"{src['id']} ligne {line} : catégories contradictoires pour un même libellé")
                        con.executemany("INSERT OR IGNORE INTO specialty VALUES (?, ?)",
                                        [(term_id, tag) for tag in sorted(set(tags))])
                        count += 1
                    if not count:
                        raise ValueError(f"{src['id']} : aucun libellé importable")
                con.execute("INSERT INTO term_fts(term_fts) VALUES ('rebuild')")
                con.execute("INSERT INTO term_fts(term_fts, rank) VALUES ('integrity-check', 1)")
            if con.execute("PRAGMA integrity_check").fetchone() != ("ok",) or con.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("contrôle d’intégrité du catalogue en échec")
            counts = counts_of(con)
        finally:
            con.close()
        # Publish a complete file without replacing an existing catalogue.
        os.link(stage, destination)
    return counts


def counts_of(con):
    return [{"source": key, "edition": edition, "categorie": category, "termes": n}
            for key, edition, category, n in con.execute("SELECT s.id,s.edition,t.category,count(*) FROM term t "
                "JOIN source s ON t.source_id=s.id GROUP BY s.id,s.edition,t.category ORDER BY s.id,t.category")]


def search(con, query, category, specialty, limit):
    if len(query) > 200:
        raise ValueError("requête trop longue")
    tokens = re.findall(r"[^\W_]+", search_form(query), re.UNICODE)
    if not 1 <= len(tokens) <= 8 or all(len(token) < 2 for token in tokens):
        raise ValueError("saisir de un à huit mots, dont un d’au moins deux caractères")
    # Tokens are entirely alphanumeric; no caller-supplied FTS operators.
    expr = " AND ".join(f'"{token}"' + ("*" if len(token) >= 2 else "") for token in tokens)
    return [dict(row) for row in con.execute("""
        SELECT t.label AS libelle,t.label_kind AS type_libelle,t.category AS categorie,t.code,
          s.id AS source,s.title AS titre_source,
          s.edition,s.publication_date AS date_source,s.url,s.license_url AS licence,s.attribution,s.note
        FROM term_fts JOIN term t ON t.id=term_fts.rowid JOIN source s ON s.id=t.source_id
        WHERE term_fts MATCH ? AND (? IS NULL OR t.category=?)
          AND (? IS NULL OR EXISTS (SELECT 1 FROM specialty st WHERE st.term_id=t.id AND st.name=?))
        ORDER BY rank,t.label,s.id,t.code LIMIT ?
    """, (expr, category, category, specialty, specialty, limit))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    p = actions.add_parser("build")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    for action in ("stats", "search"):
        p = actions.add_parser(action)
        p.add_argument("--db", type=Path, required=True)
        if action == "search":
            p.add_argument("query")
            p.add_argument("--categorie", choices=sorted(CATEGORIES))
            p.add_argument("--specialite")
            p.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    try:
        if args.action == "build":
            result = build(args.manifest, args.db)
        else:
            con = sqlite3.connect(args.db.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
            try:
                if con.execute("PRAGMA user_version").fetchone() != (CATALOGUE_VERSION,):
                    raise ValueError("schéma inconnu")
                con.row_factory = sqlite3.Row
                if args.action == "search":
                    if not 1 <= args.limit <= 50 or (args.specialite is not None and not KEY.fullmatch(args.specialite)):
                        raise ValueError("spécialité invalide ou limite hors de [1, 50]")
                    result = search(con, args.query, args.categorie, args.specialite, args.limit)
                else:
                    result = counts_of(con)
            finally:
                con.close()
        # Preserve Unicode in JSON even when a Windows pipe uses a legacy code page.
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (OSError, TypeError, ValueError, KeyError, UnicodeError, csv.Error, ET.ParseError, sqlite3.Error) as err:
        print(f"Catalogue refusé : {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
