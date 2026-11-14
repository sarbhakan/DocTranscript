import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from lexique import specialty_profiles as profiles


class SpecialtyProfilesTests(unittest.TestCase):
    def test_context_ignores_dose_fraction_negation_and_laterality(self):
        for unsafe in ("Méthotrexate 2,5 mg", "un demi comprimé", "examen sans douleur",
                       "côté gauche", "analyse négative", "trois quarts", "insuline UI",
                       "dosage des anticorps", "1/4", "inhibiteur A+B", "masse à droite"):
            with self.subTest(term=unsafe):
                self.assertFalse(profiles.eligible(unsafe))
        for safe in ("Électroneuromyographie", "Maladie d’Addison", "Alpha-bloquant"):
            with self.subTest(term=safe):
                self.assertTrue(profiles.eligible(safe))

    def test_profile_counts_scope_only_once_and_keeps_provenance(self):
        term = profiles.Term
        provenance = []
        profile = profiles.pack_profile(
            "test", profiles.Spec("Essai"),
            [term("Échographie", "ccam-ans", "A", "acte", 1),
             term("Test sans réaction", "ccam-ans", "B", "acte", 1)],
            [term("echographie", "hpo", "HP:1", "phenotype", 8)],
            [term("Chlorhexidine", "medicam", "A01AB03", "substance", 100)],
            provenance,
        )
        self.assertEqual(profile["statistics"]["specialty"], 2)
        self.assertEqual(profile["statistics"]["related"], 0)
        self.assertEqual(profile["statistics"]["shared"], 1)
        self.assertFalse(profile["statistics"]["target_met"])
        self.assertEqual(set(profile["entries"]), {"Échographie", "Test sans réaction", "Chlorhexidine"})
        self.assertEqual(profile["active"], ["Échographie"])
        self.assertIn(("test", "Échographie", "ccam-ans", "A", "acte", "specialty", 1), provenance)

    def test_hpo_traversal_follows_multiply_inherited_terms_once(self):
        parents = {"child": {"root", "other"}, "leaf": {"child"}, "other": {"root"}, "foreign": {"separate"}}
        self.assertEqual(profiles.descendants(parents, ["root"]), {"root", "other", "child", "leaf"})

    def test_input_rejects_wrong_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "corrupted.xml"
            bad.write_text("not a clinical nomenclature", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                profiles.checked(bad, "phenotypes")

    def test_orphadata_only_counts_positive_associations(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "sample.xml"
            associations = "".join(
                f"<HPODisorderAssociation><HPO><HPOId>HP:{code}</HPOId></HPO>"
                f"<HPOFrequency><Name>{frequency}</Name></HPOFrequency></HPODisorderAssociation>"
                for code, frequency in (("0000001", "Fréquent (79-30%)"), ("0000002", "Absent (0%)"),
                                        ("0000003", "Exclu (0%)"))
            )
            cases = "".join(f"<HPODisorderSetStatus><Disorder><OrphaCode>{i}</OrphaCode>"
                            f"<HPODisorderAssociationList>{associations}</HPODisorderAssociationList>"
                            "</Disorder></HPODisorderSetStatus>" for i in range(4000))
            file.write_text(f"<HPODisorderSetStatusList>{cases}</HPODisorderSetStatusList>", encoding="utf-8")
            self.assertEqual(profiles.associated_phenotypes(file)["42"], {"0000001"})

    @unittest.skipUnless(os.getenv("NOTEVIVE_PROFILES_DIR"), "fixture: NOTEVIVE_PROFILES_DIR")
    def test_frozen_full_catalogue(self):
        directory = Path(os.environ["NOTEVIVE_PROFILES_DIR"])
        blob = (directory / "profiles.json").read_bytes()
        self.assertLess(len(blob), profiles.MAX_BYTES)
        self.assertEqual(hashlib.sha256(blob).hexdigest(),
                         "8929b965a9053972832c89ae1a13908525e251758ec9b0fda3d4ac95bb4cf18c")
        raw = json.loads(blob)
        self.assertEqual(raw["schema"], 1)
        self.assertEqual(set(profiles.SPECS), {p["id"] for p in raw["profiles"]})
        self.assertFalse(any("bdpm" in s["id"] for s in raw["sources"]))
        size = 0
        lookup = {}
        for p in raw["profiles"]:
            entries = p["entries"]
            size += len(entries)
            lookup[p["id"]] = set(entries)
            with self.subTest(id=p["id"]):
                self.assertEqual(len(entries), len({profiles.label_key(term) for term in entries}))
                self.assertGreaterEqual(len(entries), profiles.MIN_TERMS)
                self.assertLessEqual(len(entries), profiles.MAX_TERMS)
                self.assertEqual(p["statistics"]["specialty"] + p["statistics"]["related"] + p["statistics"]["shared"], len(entries))
                self.assertEqual(sum(p["statistics"]["by_source"].values()), len(entries))
                self.assertTrue(set(p["active"]).issubset(entries))
                self.assertEqual(len(p["active"]), len(set(p["active"])))
                self.assertLessEqual(len(p["active"]), 256)
                self.assertTrue(all(profiles.eligible(term) for term in p["active"]))
        with (directory / "provenance.tsv").open(encoding="utf-8", newline="") as stream:
            rows = csv.DictReader(stream, delimiter="\t")
            sources = {s["id"] for s in raw["sources"]}
            for row in rows:
                self.assertIn(row["source"], sources)
                lookup[row["profile"]].remove(row["label"])
            self.assertEqual(rows.line_num, size + 1)
        self.assertTrue(all(not remaining for remaining in lookup.values()))


if __name__ == "__main__":
    unittest.main()
