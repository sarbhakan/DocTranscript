"""Small fictitious fixtures; the official integration test is explicitly optional."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from lexique import prepare_041 as p


def csv_data(header, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def ruim_fixture():
    cis = dict.fromkeys(p.CIS_HEADER, "")
    cis.update(URI="http://data.esante.gouv.fr/ansm/medicament/SpecialitePharmaceutique_12345678",
               CIS="12345678", libelle="FICTOMÉD 1,25 mg/ml, solution", actif="true", codeATC="N01AA01")
    return {
        "CIS.csv": csv_data(p.CIS_HEADER, [cis]),
        "Substances.csv": csv_data(["URI", "codeSubstance", "libelle_fr", "codeSMS", "synonymes_fr"], [
            dict(URI="http://data.esante.gouv.fr/ansm/medicament/Substance_00123", codeSubstance="00123",
                 libelle_fr="substance-école", codeSMS="", synonymes_fr="alias-école | autre alias")]),
        "Formes.csv": csv_data(["URI", "identifiant", "libelle"], [
            dict(URI="http://data.esante.gouv.fr/ansm/medicament/Forme_FT001", identifiant="FT001", libelle="Forme-école")]),
        "Voies.csv": csv_data(["URI", "identifiant", "libelle", "codeRMS", "codeEDQM"], [
            dict(URI="http://data.esante.gouv.fr/ansm/medicament/Voie_123", identifiant="123", libelle="voie-école", codeRMS="", codeEDQM="")]),
    }


def adicap_fixture(*entries):
    return ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
            'xmlns:a="https://data.esante.gouv.fr/adicap/">' + ''.join(entries) + '</rdf:RDF>').encode()


def adicap_entry(code="A001", label="TERME-ÉCOLE - ALIAS", dictionary="D4", ended=False):
    return (f'<rdf:Description rdf:about="https://data.esante.gouv.fr/adicap/{code}">'
            f'<rdfs:label xml:lang="fr">{label}</rdfs:label><a:dictionaryCode>{dictionary}</a:dictionaryCode>'
            + ('<a:endDate>2000-01-01</a:endDate>' if ended else '') + '</rdf:Description>')


def lahn_fixture(parent="05"):
    return json.dumps(dict(resourceType="CodeSystem", id="terminologie-lahn", version="2026-04",
                           content="complete", count=3, concept=[
        dict(code="LAHN", display="Rubrique"),
        dict(code="05", display="Hématologie", property=[dict(code="type", valueString="Chapitre"),
                                                         dict(code="parent", valueCode="LAHN")]),
        dict(code="E001", display="Analyse-école\nterme conservé", property=[dict(code="type", valueString="code"),
                                                                         dict(code="parent", valueCode=parent)]),
    ])).encode()


class Prepare041Test(unittest.TestCase):
    def test_medication_strength_is_preserved_and_forms_are_separate(self):
        rows = p.ruim_rows(ruim_fixture())
        self.assertEqual(rows["ruim-cis"], [("12345678", "FICTOMÉD 1,25 mg/ml, solution", "medicament", "pharmacologie|ruim-atc-n")])
        self.assertEqual(len(rows["ruim-substances"]), 3)
        self.assertEqual(rows["ruim-formes"][0][2], "forme-pharmaceutique")
        self.assertEqual(rows["ruim-voies"][0][2], "voie-administration")

    def test_archived_cis_excluded_and_no_dose_is_inferred(self):
        fixture = ruim_fixture()
        fixture["CIS.csv"] = fixture["CIS.csv"].replace(b",true,", b",false,")
        self.assertEqual(p.ruim_rows(fixture)["ruim-cis"], [])
        self.assertEqual(p.ruim_rows(fixture)["ruim-substances"][0][1], "substance-école")

    def test_bad_code_header_duplicate_and_atc_refused(self):
        for before, after in [(b"CIS,", b"Unknown,"), (b"N01AA01", b"Z01AA01"),
                              (b"SpecialitePharmaceutique_12345678", b"SpecialitePharmaceutique_87654321")]:
            fixture = ruim_fixture()
            fixture["CIS.csv"] = fixture["CIS.csv"].replace(before, after)
            with self.subTest(before=before), self.assertRaises(ValueError):
                p.ruim_rows(fixture)
        fixture = ruim_fixture()
        fixture["CIS.csv"] += fixture["CIS.csv"].splitlines(keepends=True)[1]
        with self.assertRaisesRegex(ValueError, "dupliqué"):
            p.ruim_rows(fixture)

    def test_intermediate_atc_is_an_official_domain_too(self):
        fixture = ruim_fixture()
        fixture["CIS.csv"] = fixture["CIS.csv"].replace(b"N01AA01", b"N01A")
        self.assertEqual(p.ruim_rows(fixture)["ruim-cis"][0][3], "pharmacologie|ruim-atc-n")

    def test_adicap_keeps_composites_without_multiplying_terms(self):
        blob = adicap_fixture(adicap_entry(), adicap_entry("D4", "RUBRIQUE"), adicap_entry("OLD", ended=True))
        self.assertEqual(p.adicap_rows(blob), [("A001", "TERME-ÉCOLE - ALIAS", "terme-anatomopathologique", "anatomocytopathologie|adicap-d4")])
        self.assertEqual(p.adicap_rows(adicap_fixture(adicap_entry("ORG", dictionary="D3")))[0][2], "anatomie")

    def test_adicap_rejects_ambiguous_ids_and_external_entities(self):
        for blob in [adicap_fixture(adicap_entry(), adicap_entry()),
                     adicap_fixture(adicap_entry(dictionary="DX")),
                     b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///private">]>' + adicap_fixture(adicap_entry())]:
            with self.subTest(blob=blob[:40]), self.assertRaises(ValueError):
                p.adicap_rows(blob)

    def test_lahn_uses_official_parent_not_lexical_guess_and_flattens_lines_only(self):
        self.assertEqual(p.lahn_rows(lahn_fixture()), [("E001", "Analyse-école terme conservé", "examen", "biologie-medicale|lahn-05")])
        for parent in ("E001", "absent"):
            with self.assertRaisesRegex(ValueError, "cycle ou parent"):
                p.lahn_rows(lahn_fixture(parent))

    def test_lahn_edition_or_ambiguous_parent_is_rejected(self):
        data = json.loads(lahn_fixture())
        data["version"] = "2027"
        with self.assertRaises(ValueError):
            p.lahn_rows(json.dumps(data).encode())
        data = json.loads(lahn_fixture())
        data["concept"][2]["property"].append(dict(code="parent", valueCode="06"))
        with self.assertRaisesRegex(ValueError, "ambiguë"):
            p.lahn_rows(json.dumps(data).encode())

    def test_archive_member_duplicate_wrong_hash_and_size_refused(self):
        payload = b"verified source"
        spec = dict(size=len(payload), sha256=p.sha(payload))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("source.csv", payload)
                archive.writestr("../never-extracted.txt", b"no extraction")
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(p.member(archive, "source.csv", spec), payload)
                with self.assertRaises(ValueError):
                    p.member(archive, "source.csv", {**spec, "sha256": "0" * 64})
                with self.assertRaises(ValueError):
                    p.member(archive, "source.csv", {**spec, "size": len(payload) - 1})
            self.assertFalse((Path(directory).parent / "never-extracted.txt").exists())

    def test_source_symlink_and_modified_bytes_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_bytes(b"abc")
            spec = dict(size=3, sha256=p.sha(b"abc"))
            self.assertEqual(p.locked_bytes(path, spec), b"abc")
            with self.assertRaises(ValueError):
                p.locked_bytes(path, dict(size=3, sha256="0" * 64))
            if os.name != "nt":
                link = path.with_name("link")
                link.symlink_to(path)
                with self.assertRaises(ValueError):
                    p.locked_bytes(link, spec)

    def test_fetch_closes_output_and_reuses_only_verified_existing_file(self):
        class Response(io.BytesIO):
            url = "https://smt.esante.gouv.fr/fixture"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            spec = dict(id="test", file="source", url=Response.url, size=3, sha256=p.sha(b"abc"))
            with patch.object(p.urllib.request, "urlopen", return_value=Response(b"abc")) as call:
                p.fetch_sources(path, dict(downloads=[spec]))
                p.fetch_sources(path, dict(downloads=[spec]))
                self.assertEqual(call.call_count, 1)
            self.assertEqual((path / "source").read_bytes(), b"abc")
            self.assertEqual([x.name for x in path.iterdir()], ["source"])

    def test_fetch_oversized_or_wrong_source_cannot_publish_partial_file(self):
        class Response(io.BytesIO):
            url = "https://smt.esante.gouv.fr/fixture"
        with tempfile.TemporaryDirectory() as directory:
            for payload in (b"abcd", b"xyz"):
                with patch.object(p.urllib.request, "urlopen", return_value=Response(payload)), self.assertRaises(ValueError):
                    p.fetch_sources(Path(directory), dict(downloads=[dict(file="source", url=Response.url, size=3, sha256=p.sha(b"abc"))]))
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_existing_output_is_untouched_even_without_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.sqlite"
            output.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "destination déjà présente"):
                p.prepare(Path(directory) / "absent", output)
            self.assertEqual(output.read_bytes(), b"keep")

    @unittest.skipUnless(os.environ.get("NOTEVIVE_041_SOURCES"), "sources officielles privées non demandées")
    def test_official_locked_sources_build_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(p.urllib.request, "urlopen", side_effect=AssertionError("offline build")):
                result = p.prepare(Path(os.environ["NOTEVIVE_041_SOURCES"]), Path(directory) / "additions.sqlite")
            self.assertEqual(sum(x["termes"] for x in result["counts"]), 29658)


if __name__ == "__main__":
    unittest.main()
