"""Adversarial medical development screens, using invented references only."""
from pathlib import Path
import tempfile
import unittest

from p0.training import score_validation as scorer


def case(reference, bio):
    critical, relations = scorer.annotate(reference, bio)
    return {"reference": reference, "critical": critical, "drug_strength_associations": relations}


class ValidationScoringTests(unittest.TestCase):
    def prescription(self):
        return case("fictoméd 20 milligrammes 1 comprimé le matin pendant 2 jours",
                    "B-drug B-d_dos_val B-d_dos_up B-dos_val B-dos_uf O B-rhythm_tdte O B-dur_val B-dur_ut")

    def test_reference_passes_its_own_grid(self):
        data = self.prescription()
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])

    def test_written_numbers_abbreviated_units_and_drug_accents(self):
        data = self.prescription()
        for output in ("Fictomed vingt mg, un comprimé le matin pendant deux jours.",
                       "Fictoméd 20 mg, 1 comprimé matin pendant 2 jours."):
            with self.subTest(output=output):
                self.assertTrue(scorer.score_case(data, output)["screen_passed"])

    def test_correct_scalar_elsewhere_does_not_certify_an_association(self):
        data = self.prescription()
        for output in ("Fictoméd 40 mg. Autrex 20 mg. 1 comprimé le matin pendant 2 jours.",
                       "Fictoméd et Autrex 20 mg, 1 comprimé le matin pendant 2 jours.",
                       "Fictoméd. Autrex 20 mg, 1 comprimé le matin pendant 2 jours."):
            with self.subTest(output=output):
                result = scorer.score_case(data, output)
                self.assertFalse(result["drug_strength_association"][0])
                self.assertFalse(result["screen_passed"])

    def test_ambiguous_range_denominator_concentration_and_sign_rejected(self):
        data = self.prescription()
        for strength in ("1/20 mg", "10 à 20 mg", "10–20 mg", "20 mg/ml", "20 mg par litre", "20 mg par kg",
                         "−20 mg", "moins vingt mg", "20 microgrammes", "20 mg ou 40 mg"):
            with self.subTest(strength=strength):
                result = scorer.score_case(data, f"Fictoméd {strength}, 1 comprimé le matin pendant 2 jours.")
                self.assertFalse(result["drug_strength_association"][0])
                self.assertFalse(result["screen_passed"])

    def test_no_drug_fragment_still_rejects_spoken_negative_amount(self):
        data = case("20 milligrammes", "B-dos_val B-dos_uf")
        result = scorer.score_case(data, "moins vingt milligrammes")
        self.assertFalse(result["guards"]["no_added_signed_number"])
        self.assertFalse(result["screen_passed"])

    def test_decimal_mass_is_not_a_tablet_fraction(self):
        data = case("fictoméd 0,25 milligrammes", "B-drug B-d_dos_val B-d_dos_up")
        self.assertEqual(data["critical"]["fraction"], [])
        self.assertTrue(scorer.score_case(data, "Fictomed zéro virgule vingt cinq mg")["screen_passed"])
        self.assertFalse(scorer.score_case(data, "Fictomed 25 mg")["screen_passed"])

    def test_fraction_time_relation_catches_swapped_times_with_same_numbers(self):
        data = case("1 quart de comprimé matin et 1 demi le soir",
                    "B-dos_val I-dos_val O B-dos_uf B-rhythm_tdte O B-dos_val I-dos_val O B-rhythm_tdte")
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])
        valid = scorer.score_case(data, "¼ comprimé le matin et ½ le soir")
        self.assertTrue(valid["screen_passed"])
        wrong = scorer.score_case(data, "¼ comprimé le soir et ½ le matin")
        self.assertTrue(wrong["guards"]["numeric_sequence_equal"])
        self.assertFalse(all(wrong["spans"]["administration_time"]))
        self.assertFalse(wrong["screen_passed"])

    def test_fraction_administrations_must_not_become_alternatives(self):
        data = case("1 quart de comprimé matin et 1 demi le soir",
                    "B-dos_val I-dos_val O B-dos_uf B-rhythm_tdte O B-dos_val I-dos_val O B-rhythm_tdte")
        result = scorer.score_case(data, "1/4 comprimé matin ou 1/2 soir")
        self.assertTrue(result["guards"]["numeric_sequence_equal"])
        self.assertFalse(result["guards"]["alternative_connector_positions_equal"])
        self.assertFalse(result["screen_passed"])

    def test_negative_sign_cannot_migrate_to_another_quantity(self):
        data = case("moins 2 comprimés puis 3 comprimés", "O B-dos_val B-dos_uf O B-dos_val B-dos_uf")
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])
        for text in ("2 comprimés puis moins 3 comprimés", "2 comprimés puis −3 comprimés"):
            with self.subTest(text=text):
                result = scorer.score_case(data, text)
                self.assertTrue(result["guards"]["numeric_sequence_equal"])
                self.assertFalse(result["guards"]["no_added_signed_number"])
                self.assertFalse(result["screen_passed"])

    def test_two_occurrences_cannot_be_satisfied_by_one(self):
        data = case("2 comprimés matin et 2 comprimés soir",
                    "B-dos_val B-dos_uf B-rhythm_tdte O B-dos_val B-dos_uf B-rhythm_tdte")
        result = scorer.score_case(data, "2 comprimés matin et soir")
        self.assertEqual(result["spans"]["dose"], [True, False])
        self.assertFalse(result["guards"]["numeric_sequence_equal"])

    def test_keep_existing_instruction_negation_and_detect_changed_scope(self):
        data = case("fictoméd 20 milligrammes à avaler sans croquer",
                    "B-drug B-d_dos_val B-d_dos_up O O O O")
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])
        result = scorer.score_case(data, "Fictoméd 20 mg à croquer sans avaler")
        self.assertTrue(result["guards"]["negation_markers_equal"])
        self.assertFalse(result["spans"]["negation"][0])
        self.assertFalse(result["screen_passed"])

    def test_added_negation_is_not_hidden_by_all_numbers_remaining(self):
        data = self.prescription()
        result = scorer.score_case(data, "Ne pas prendre Fictoméd 20 mg, 1 comprimé le matin pendant 2 jours")
        self.assertTrue(result["guards"]["numeric_sequence_equal"])
        self.assertFalse(result["guards"]["negation_markers_equal"])
        self.assertFalse(result["drug_strength_association"][0])

    def test_modification_lp_is_part_of_source_drug(self):
        data = case("fictoméd lp 600 milligrammes", "B-drug B-A B-d_dos_val B-d_dos_up")
        self.assertEqual(data["critical"]["drug"], ["fictoméd lp"])
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])
        self.assertFalse(scorer.score_case(data, "fictoméd 600 mg")["screen_passed"])

    def test_administered_range_cannot_be_reduced_to_upper_bound(self):
        data = case("2 à 3 comprimés", "B-dos_val O B-dos_val B-dos_uf")
        self.assertEqual(data["critical"]["dose"], ["2 à 3 comprimés"])
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])
        self.assertFalse(scorer.score_case(data, "3 comprimés")["screen_passed"])

    def test_condition_missing_cannot_pass_with_correct_drug_and_amount(self):
        data = case("fictoméd 1 dose uniquement si douleur", "B-drug B-dos_val B-dos_uf O O B-dos_cond")
        self.assertEqual(data["critical"]["condition"], ["uniquement si douleur"])
        self.assertFalse(scorer.score_case(data, "fictoméd 1 dose")["screen_passed"])

    def test_sealed_grid_modification_is_rejected_before_predictions_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grid = root / "grid.json"
            grid.write_text('{"changed":true}')
            grid.with_suffix(".json.sha256").write_text("0" * 64)
            with self.assertRaisesRegex(ValueError, "grille a changé"):
                scorer.score_predictions(grid, root / "nonexistent-predictions.jsonl", root / "scores")
            self.assertFalse((root / "scores").exists())


if __name__ == "__main__":
    unittest.main()
