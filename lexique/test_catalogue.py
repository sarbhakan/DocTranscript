"""Catalogue tests; all source data in these tests are fictitious."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from lexique.__main__ import build, counts_of, search


class CatalogueTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / "test.sqlite"
        self.manifest = self.root / "sources.json"

    def source(self, key, mode, data, encoding="utf-8-sig"):
        filename = key + ".txt"
        payload = data.encode(encoding)
        (self.root / filename).write_bytes(payload)
        return {"id": key, "format": mode, "file": filename, "encoding": encoding,
                "title": key, "edition": "fixture", "publication_date": "2026-01-01",
                "url": "https://example.org/data", "license_url": "https://example.org/license",
                "attribution": "test fictif", "note": "fichier synthétique", "scope": "catalogue-local",
                "sha256": hashlib.sha256(payload).hexdigest()}

    def run_build(self, *sources):
        self.manifest.write_text(json.dumps({"schema": 1, "sources": sources}), encoding="utf-8")
        return build(self.manifest, self.db)

    def query(self, query, category=None, specialty=None):
        con = sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True)
        try:
            con.row_factory = sqlite3.Row
            return search(con, query, category, specialty, 20)
        finally:
            con.close()

    def test_homonyms_filters_and_official_spelling(self):
        header = "code,libelle,categorie,specialites\n"
        a = self.source("a", "csv", header + "0001,Œdème de l’artère,symptome,cardio\n"
                        + "0001,Œdème de l’artère,symptome,medecine-generale\n")
        b = self.source("b", "csv", header + "0001,Œdème de l’artère,symptome,cardio\n")
        self.assertEqual([row["termes"] for row in self.run_build(a, b)], [1, 1])
        hits = self.query("oedeme artere", "symptome", "cardio")
        self.assertEqual({(row["source"], row["code"], row["libelle"]) for row in hits},
                         {("a", "0001", "Œdème de l’artère"), ("b", "0001", "Œdème de l’artère")})
        self.assertEqual([r["source"] for r in self.query("l'artere", specialty="medecine-generale")], ["a"])
        self.assertEqual(self.query("oedeme", category="acte"), [])
        self.assertEqual(self.query('oedeme OR "manquant"'), [])

    def test_bdpm_keeps_substance_not_dosage_or_therapeutic_fraction(self):
        c = self.source("compo", "bdpm-compo", "00000001\tx\t4\tSubstance-école\t10 mg\tx\tSA\t1\n"
                        + "00000002\tx\t4\tSubstance-école\t20 mg\tx\tSA\t1\n"
                        + "00000001\tx\t5\tFraction-école\t5 mg\tx\tFT\t1\n", "cp1252")
        self.run_build(c)
        self.assertEqual([row["libelle"] for row in self.query("substance", "substance")], ["Substance-école"])
        self.assertEqual(self.query("20 mg"), [])
        self.assertEqual(self.query("fraction"), [])

    def test_orphanet_active_pathologies_and_synonyms_only(self):
        def entry(code, label, status, level):
            return (f'<Disorder><OrphaCode>{code}</OrphaCode><Name lang="fr">{label}</Name>'
                    f'<Totalstatus>{status}</Totalstatus><ClassificationLevel><Name>{level}</Name>'
                    '</ClassificationLevel><SynonymList><Synonym lang="fr">Alias de test</Synonym>'
                    '</SynonymList><Summary>Résumé exclu</Summary></Disorder>')
        xml = ('<JDBOR><DisorderList count="3">' + entry(10, "Test retenu", "Active", "Pathologie")
               + entry(11, "Test obsolète", "Deprecated", "Pathologie")
               + entry(12, "Test générique", "Active", "Groupe de pathologies") + '</DisorderList></JDBOR>')
        self.run_build(self.source("orpha", "orphanet-nomenclature-fr", xml))
        self.assertEqual({(row["code"], row["libelle"], row["type_libelle"]) for row in self.query("test")},
                         {("10", "Test retenu", "principal"), ("10", "Alias de test", "synonyme")})
        self.assertEqual(self.query("exclu"), [])

    def test_bad_checksum_does_not_publish_partial_db_and_no_overwrite(self):
        csv = "code,libelle,categorie,specialites\n1,Acte-école,acte,\n"
        good = self.source("good", "csv", csv)
        bad = self.source("bad", "csv", csv)
        (self.root / bad["file"]).write_bytes(b"changed after review")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.run_build(good, bad)
        self.assertFalse(self.db.exists())
        self.run_build(good)
        with self.assertRaisesRegex(ValueError, "destination déjà présente"):
            self.run_build(good)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(counts_of(con)[0]["termes"], 1)
        finally:
            con.close()

    def test_refuses_external_path_and_doctype(self):
        original = self.source("escape", "csv", "")
        original["file"] = "../escape.txt"
        with self.assertRaisesRegex(ValueError, "chemin source"):
            self.run_build(original)
        xml = '<!DOCTYPE JDBOR SYSTEM "file:///outside"><JDBOR />'
        with self.assertRaisesRegex(ValueError, "DTD"):
            self.run_build(self.source("xml", "orphanet-nomenclature-fr", xml))
        self.assertFalse(self.db.exists())

    def test_cli_json_preserves_non_cp1252_label_when_redirected(self):
        csv = "code,libelle,categorie,specialites\n1,Acte-école │,acte,\n"
        self.run_build(self.source("cli", "csv", csv))
        result = subprocess.run([sys.executable, "-m", "lexique", "search", "--db", str(self.db), "ecole"],
                                capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"}, check=True)
        self.assertEqual(json.loads(result.stdout)[0]["libelle"], "Acte-école │")


if __name__ == "__main__":
    unittest.main()
