import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.catalogue_package import SOURCE_COLUMNS, content_digest, domain_header, extend, open_readonly, validate
from lexique.__main__ import DDL


class CataloguePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, name, label, tag):
        path = self.root / (name + '.sqlite')
        source = dict(zip(SOURCE_COLUMNS.split(','), [name, 'Source fictive', '1', '2026-11-15',
            'https://example.org/source', 'https://example.org/license', 'Attribution fictive',
            'a' * 64, 'csv', 'Données fictives de recette']))
        with sqlite3.connect(path) as con:
            con.executescript(DDL)
            con.execute('INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?)', tuple(source.values()))
            con.execute('INSERT INTO term VALUES (1,?,?,?,?,?,?)',
                        (name, 'A1', label, label.lower(), 'maladie', 'libelle-source'))
            con.execute('INSERT INTO specialty VALUES (1,?)', (tag,))
            con.execute("INSERT INTO term_fts(term_fts) VALUES('rebuild')")
        return path, source

    def specification(self, path, sources):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'schema': 1, 'sources': sources}), encoding='utf-8')
        with open_readonly(path) as con:
            spec = {'schema': 2, 'sources': sorted(s['id'] for s in sources),
                    'entries': con.execute('SELECT count(*) FROM term').fetchone()[0],
                    'content_sha256': content_digest(con)}
        return manifest, spec

    def test_extend_preserves_labels_tags_provenance_and_inputs(self):
        base, a = self.fixture('base', 'Œdème α', 'cardiologie')
        extra, b = self.fixture('extra', 'Maladie bêta', 'dermatologie')
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (base, extra)]
        output = self.root / 'combined.sqlite'
        extend(base, extra, output)
        manifest, spec = self.specification(output, [a, b])
        self.assertEqual(validate(output, manifest, spec)['sources'], [a, b])
        with open_readonly(output) as con:
            self.assertEqual(con.execute('SELECT label FROM term ORDER BY source_id').fetchall(),
                             [('Œdème α',), ('Maladie bêta',)])
            self.assertEqual(con.execute('SELECT name FROM specialty ORDER BY name').fetchall(),
                             [('cardiologie',), ('dermatologie',)])
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (base, extra)])

    def test_no_overwrite_and_duplicate_source_not_published(self):
        base, _ = self.fixture('base', 'Terme', 'general')
        destination = self.root / 'output.sqlite'
        with self.assertRaises(sqlite3.IntegrityError):
            extend(base, base, destination)
        self.assertFalse(destination.exists())
        destination.write_bytes(b'existing')
        with self.assertRaises(ValueError):
            extend(base, base, destination)
        self.assertEqual(destination.read_bytes(), b'existing')

    def test_changed_spelling_or_provenance_rejected(self):
        base, source = self.fixture('base', 'Terme exact', 'general')
        manifest, spec = self.specification(base, [source])
        with sqlite3.connect(base) as con:
            con.execute("UPDATE term SET label='Terme modifié'")
        with self.assertRaises(ValueError):
            validate(base, manifest, spec)

    def test_corrupt_external_content_index_rejected(self):
        base, source = self.fixture('base', 'Terme exact', 'general')
        manifest, spec = self.specification(base, [source])
        with sqlite3.connect(base) as con:
            con.execute("INSERT INTO term_fts(term_fts) VALUES('delete-all')")
        with self.assertRaises(sqlite3.DatabaseError):
            validate(base, manifest, spec)

    def test_missing_domain_detected_even_with_same_counts(self):
        base, source = self.fixture('base', 'Terme', 'general')
        manifest, spec = self.specification(base, [source])
        with sqlite3.connect(base) as con:
            con.execute("UPDATE specialty SET name='autre'")
        with self.assertRaises(ValueError):
            validate(base, manifest, spec)

    def test_official_domains_apply_to_all_labels_of_code(self):
        base, _ = self.fixture('orphanet-fr', 'Libellé principal', 'general')
        extra, _ = self.fixture('extra', 'Autre terme', 'general')
        with sqlite3.connect(base) as con:
            con.execute("UPDATE term SET code='123'")
            con.execute("INSERT INTO term VALUES (2,'orphanet-fr','123','Synonyme','synonyme','maladie','synonyme')")
            con.execute("INSERT INTO term_fts(term_fts) VALUES('rebuild')")
        mapping = {'records': [{'source_id': 'orphanet-fr', 'code': '123', 'domain': 'orpha-146'}]}
        output = self.root / 'combined.sqlite'
        extend(base, extra, output, mapping)
        with open_readonly(output) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM specialty WHERE name='orpha-146'").fetchone(), (2,))
            self.assertEqual(con.execute('SELECT count(*) FROM term').fetchone(), (3,))

    def test_unknown_mapping_code_cannot_publish(self):
        base, _ = self.fixture('base', 'Terme', 'general')
        extra, _ = self.fixture('extra', 'Autre', 'general')
        output = self.root / 'bad.sqlite'
        with self.assertRaises(ValueError):
            extend(base, extra, output, {'records': [{'source_id':'orphanet-fr','code':'123','domain':'orpha-146'}]})
        self.assertFalse(output.exists())

    def test_domain_label_header_escapes_quotes_and_rejects_controls(self):
        path = self.root / 'labels.json'
        path.write_text(json.dumps({'schema':1,'labels':{'cardio':'Cœur "rare"'}}))
        self.assertIn(r'L"Cœur \"rare\""', domain_header(path))
        path.write_text(json.dumps({'schema':1,'labels':{'cardio':'Cœur\nrare'}}))
        with self.assertRaises(ValueError):
            domain_header(path)


if __name__ == '__main__':
    unittest.main()
