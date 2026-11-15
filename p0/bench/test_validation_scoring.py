"""Adversarial medical development screens, using invented references only."""
from pathlib import Path
from contextlib import redirect_stdout
import io
import json
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

    def test_split_source_bio_fraction_is_joined_without_changing_the_reference(self):
        reference = "1 demi comprimé matin et soir pendant 1 semaine"
        data = case(reference, "B-dos_val B-dos_val B-dos_uf B-rhythm_tdte O B-rhythm_tdte O B-dur_val B-dur_ut")
        self.assertEqual(data["reference"], reference)
        self.assertEqual(data["critical"]["value"], ["1 demi", "1"])
        self.assertEqual(data["critical"]["fraction"], ["1 demi"])
        self.assertTrue(scorer.score_case(data, reference)["screen_passed"])
        self.assertTrue(scorer.score_case(data, "½ comprimé matin et soir pendant une semaine")["screen_passed"])
        self.assertFalse(scorer.score_case(data, "1,5 comprimé matin et soir pendant 1 semaine")["screen_passed"])

    def test_adjacent_distinct_source_numbers_are_not_joined(self):
        data = case("1 2 comprimés", "B-dos_val B-dos_val B-dos_uf")
        self.assertEqual(data["critical"]["value"], ["1", "2"])

    def test_condition_only_source_is_not_counted_twice_by_fallback(self):
        data = case("au goûter", "B-cma_event I-cma_event")
        self.assertEqual(data["critical"]["condition"], ["au goûter"])
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])

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

    def test_negation_scope_cannot_move_while_markers_remain_identical(self):
        reference = "pas de fièvre ; toux présente"
        data = case(reference, "O O O O O O")
        output = "fièvre présente ; pas de toux"
        scored = scorer.score_case(data, output)
        self.assertTrue(scored["guards"]["negation_markers_equal"])
        self.assertFalse(scored["guards"]["negated_clauses_equal"])
        self.assertFalse(scored["spans"]["negated_clause"][0])
        self.assertEqual(data["critical"]["clinical_negation"], [])

    def test_postposed_absence_and_laterality_remain_bound_to_the_clause(self):
        reference = "douleur gauche absente ; douleur droite présente"
        data = case(reference, " ".join(["O"] * len(reference.split())))
        wrong = "douleur gauche présente ; douleur droite absente"
        scored = scorer.score_case(data, wrong)
        self.assertTrue(scored["guards"]["negation_markers_equal"])
        self.assertFalse(scored["guards"]["negated_clauses_equal"])
        self.assertFalse(scored["guards"]["laterality_clauses_equal"])

    def test_same_laterality_words_in_wrong_clauses_are_not_enough(self):
        reference = "paresthésie à gauche ; parésie à droite"
        data = case(reference, " ".join(["O"] * len(reference.split())))
        wrong = "paresthésie à droite ; parésie à gauche"
        self.assertFalse(scorer.score_case(data, wrong)["guards"]["laterality_clauses_equal"])
        self.assertTrue(scorer.score_case(data, reference)["screen_passed"])

    def test_clinical_assertion_cannot_be_assembled_across_two_clauses(self):
        reference = "absence de douleur à gauche"
        data = case(reference, " ".join(["O"] * len(reference.split())))
        data["critical"]["clinical_negation"] = [reference]
        result = scorer.score_case(data, "absence de douleur ; à gauche")
        self.assertFalse(result["spans"]["clinical_negation"][0])

    def test_no_semantic_equivalence_is_invented_for_a_paraphrase(self):
        reference = "pas de fièvre"
        data = case(reference, "O O O")
        self.assertFalse(scorer.score_case(data, "absence de fièvre")["screen_passed"])

    def test_clauses_keep_decimals_and_split_adversatives(self):
        self.assertEqual(scorer.scope_clauses("7,5 mg, sans croquer mais douleur à gauche."),
                         ["7,5 mg", "sans croquer", "douleur à gauche"])

    def test_multiple_drugs_have_individual_strength_associations(self):
        reference = "fictoméd 20 mg ; autreméd 40 mg"
        data = case(reference, "B-drug B-d_dos_val B-d_dos_up O B-drug B-d_dos_val B-d_dos_up")
        self.assertEqual(len(data["drug_strength_associations"]), 2)
        self.assertTrue(scorer.score_case(data, reference)["screen_passed"])
        wrong = scorer.score_case(data, "Autreméd 20 mg ; Fictoméd 40 mg")
        self.assertTrue(wrong["guards"]["numeric_sequence_equal"])
        self.assertFalse(wrong["guards"]["drug_name_order_and_multiplicity_equal"])
        self.assertEqual(wrong["drug_strength_association"], [False, False])

    def test_repeated_drug_is_bound_to_its_own_occurrence(self):
        reference = "fictoméd 20 mg puis fictoméd 40 mg"
        data = case(reference, "B-drug B-d_dos_val B-d_dos_up O B-drug B-d_dos_val B-d_dos_up")
        self.assertEqual(data["critical"]["drug"], ["fictoméd", "fictoméd"])
        self.assertTrue(scorer.score_case(data, reference)["screen_passed"])
        wrong = scorer.score_case(data, "fictoméd 40 mg puis fictoméd 20 mg")
        self.assertEqual(wrong["drug_strength_association"], [False, False])

    def test_correct_drug_repeated_elsewhere_cannot_rescue_wrong_first_association(self):
        data = self.prescription()
        wrong = "Fictoméd 40 mg ; Fictoméd 20 mg ; 1 comprimé le matin pendant 2 jours"
        result = scorer.score_case(data, wrong)
        self.assertFalse(result["drug_strength_association"][0])
        self.assertFalse(result["guards"]["drug_name_order_and_multiplicity_equal"])

    def test_added_unknown_drug_without_a_new_number_requires_review(self):
        data = self.prescription()
        result = scorer.score_case(data, data["reference"] + " et hydralazine")
        self.assertTrue(result["guards"]["numeric_sequence_equal"])
        self.assertTrue(all(result["spans"]["drug"]))
        self.assertFalse(result["guards"]["no_unreviewed_content_addition"])
        self.assertFalse(result["screen_passed"])

    def test_concentration_denominators_cannot_swap_while_values_and_units_remain(self):
        reference = "fictoméd 20 mg par kg ; autreméd 40 mg par ml"
        data = case(reference, "B-drug B-d_dos_val B-d_dos_up O O O B-drug B-d_dos_val B-d_dos_up O O")
        self.assertTrue(scorer.score_case(data, reference)["screen_passed"])
        wrong = scorer.score_case(data, "fictoméd 20 mg par ml ; autreméd 40 mg par kg")
        self.assertTrue(wrong["guards"]["numeric_sequence_equal"])
        self.assertTrue(wrong["guards"]["unit_multiplicities_equal"])
        self.assertTrue(wrong["guards"]["no_added_concentration"])
        self.assertFalse(wrong["guards"]["concentration_clauses_equal"])
        self.assertFalse(wrong["screen_passed"])

    def test_concentration_clause_retains_decimal_and_detects_added_or_removed_denominator(self):
        reference = "fictoméd 2,5 mg par ml"
        data = case(reference, "B-drug B-d_dos_val B-d_dos_up O O")
        self.assertTrue(scorer.score_case(data, "fictoméd 2.5 mg par ml")["screen_passed"])
        removed = scorer.score_case(data, "fictoméd 2,5 mg")
        self.assertFalse(removed["guards"]["concentration_clauses_equal"])
        plain = case("fictoméd 2,5 mg", "B-drug B-d_dos_val B-d_dos_up")
        added = scorer.score_case(plain, reference)
        self.assertFalse(added["guards"]["concentration_clauses_equal"])

    def test_no_source_association_is_guessed_across_a_sentence_boundary(self):
        data = case("fictoméd. 20 mg", "B-drug B-d_dos_val B-d_dos_up")
        self.assertEqual(data["drug_strength_associations"], [])

    def test_explicit_tablet_form_between_name_and_strength_is_not_a_second_drug(self):
        data = case("fictoméd comprimé 20 mg", "B-drug B-dos_uf B-d_dos_val B-d_dos_up")
        self.assertEqual(len(data["drug_strength_associations"]), 1)
        self.assertTrue(scorer.score_case(data, data["reference"])["screen_passed"])
        self.assertFalse(scorer.score_case(data, "fictoméd et autreméd 20 mg")["drug_strength_association"][0])

    def test_full_drug_modifier_wins_over_its_prefix(self):
        self.assertEqual(scorer.drug_mentions("fictoméd LP puis fictoméd", ["fictoméd", "fictoméd lp"]),
                         [("fictomed", "lp"), ("fictomed",)])

    def test_published_synthetic_panel_is_self_consistent_and_rejects_its_mutations(self):
        panel = json.loads((Path(__file__).parents[1] / "training" / "critical_scenarios_v2.json").read_text())
        self.assertEqual(panel["scorer_profile"], scorer.SCORER_PROFILE)
        self.assertFalse(panel["asr_executed"])
        ids = [item["id"] for item in panel["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for item in panel["cases"]:
            with self.subTest(case=item["id"]):
                self.assertTrue(scorer.score_case(item, item["reference"])["screen_passed"])
                self.assertFalse(scorer.score_case(item, item["adversarial_text"])["screen_passed"])
                # Assert the intended dimension, not a coincidental WER failure.
                result = scorer.score_case(item, item["adversarial_text"])
                group, key = item["expected_failed_check"].split(":", 1)
                value = result[group][key] if group != "drug_strength_association" else result[group][int(key)]
                self.assertFalse(all(value) if isinstance(value, list) else value)

    def test_paired_report_does_not_confuse_two_errors_with_two_clips_or_absent_coverage(self):
        reference = "fictoméd 20 mg ; autreméd 40 mg"
        item = case(reference, "B-drug B-d_dos_val B-d_dos_up O B-drug B-d_dos_val B-d_dos_up")
        item.update(id="synthetic-only", speaker_id="synthetic-voice")
        coverage = {name: {"spans": len(values), "clips": int(bool(values))}
                    for name, values in item["critical"].items()}
        coverage["drug_strength_association"] = {"spans": 2, "clips": 1}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grid = {"schema": 2, "scorer_profile": scorer.SCORER_PROFILE,
                    "source_sha256": scorer.PX_SHA256, "predictions_used_to_prepare": False,
                    "scorer_sha256": scorer.sha256(Path(scorer.__file__)),
                    "scoring_code_sha256": scorer.scoring_code_hashes(),
                    "selection_sha256": "synthetic-selection", "validation_manifest_sha256": "synthetic-manifest",
                    "cases": [item], "coverage": coverage, "limitations": ["Synthetic scorer contract test only"]}
            grid_path = root / "grid.json"
            scorer.atomic_json(grid_path, grid)
            grid_path.with_suffix(".json.sha256").write_text(scorer.sha256(grid_path))
            contract = {"selected_rows_sha256": grid["selection_sha256"],
                        "manifest_sha256": {"validation": grid["validation_manifest_sha256"]}}
            scorer.atomic_json(root / "contract.json", contract)
            scorer.atomic_json(root / "report.json", {"status": "completed", "contract_sha256": scorer.json_digest(contract)})
            prediction = {"id": item["id"], "speaker_id": item["speaker_id"], "reference": reference,
                          "base": {"text": reference}, "adapter": {"text": "erreuralpha 20 mg ; erreurbêta 40 mg"}}
            predictions = root / "predictions.local.jsonl"
            predictions.write_text(json.dumps(prediction), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                result = scorer.score_predictions(grid_path, predictions, root / "scores")
            self.assertEqual(result["paired"]["regressions"]["span:drug"], 2)
            self.assertEqual(result["paired_affected_clips"]["regressions"]["span:drug"], 1)
            self.assertEqual(result["paired_affected_clips"]["regressions"]["any_critical_check"], 1)
            self.assertIn("clinical_negation", result["unobserved_categories"])
            self.assertFalse(result["automatic_adoption"])


if __name__ == "__main__":
    unittest.main()
