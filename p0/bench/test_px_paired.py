"""Adversarial cases for the separate Px quantity and association counters."""
import unittest

from p0.review.px_paired import evaluate_row


class PxAssociationTests(unittest.TestCase):
    def score(self, text, reference="prozac 20 milligrammes"):
        return evaluate_row(reference, 'B-drug B-d_dos_val B-d_dos_up', text)

    def test_single_dose_with_valid_separators_and_decimal(self):
        for text in ('Prozac 20 mg.', 'Prozac, dosage de 20 mg.', 'Prozac dosé à 20 milligrammes.',
                     'Prozac à 20 mg.', 'Prozac 20 mg; autre mention.'):
            with self.subTest(text=text):
                scores = self.score(text)
                self.assertTrue(scores['strength_unqualified_exact'])
                self.assertTrue(scores['strength_association_strict'])
        self.assertTrue(self.score('Prozac 7.5 mg.', 'prozac 7,5 milligrammes')['strength_association_strict'])
        self.assertTrue(self.score('Prozac 20 μg.', 'prozac 20 microgrammes')['strength_association_strict'])
        self.assertFalse(self.score('Prozac 20 mg.', 'prozac 20 microgrammes')['strength_association_strict'])

    def test_numeric_value_does_not_imply_local_association(self):
        for text in ('Prozac. Sotalex 20 mg', 'Prozac et Sotalex 20 mg',
                     'Prozac 40 mg ; Sotalex 20 mg', 'Prozac 20 mg ou 40 mg', 'Prozac arrêt avant 20 mg',
                     'Ne pas prendre de Prozac 20 mg.', 'Prozac 40 mg, Prozac 20 mg'):
            with self.subTest(text=text):
                scores = self.score(text)
                self.assertTrue(scores['drug_exact'])
                self.assertTrue(scores['strength_exact'])
                self.assertTrue(scores['strength_unqualified_exact'])
                self.assertFalse(scores['strength_association_strict'])
        self.assertFalse(self.score('Fauxprozac 20 mg')['strength_association_strict'])

    def test_range_denominator_negative_or_concentration_not_drug_strength(self):
        for text in ('Prozac 1/20 mg', 'Prozac 1⁄20 mg', 'Prozac 10 à 20 mg',
                     'Prozac 10–20 mg', 'Prozac 10 - 20 mg', 'Prozac −20 mg', 'Prozac − 20 mg', 'Prozac 20½ mg',
                     'Prozac moins 20 mg', 'Prozac 20 mg ⁄ mL', 'Prozac 20 mg par l',
                     'Prozac 20 mg par comprimé', 'Prozac 20'):
            with self.subTest(text=text):
                scores = self.score(text)
                self.assertFalse(scores['strength_unqualified_exact'])
                self.assertFalse(scores['strength_association_strict'])
        # Preserve the historical counters without letting them certify a dose.
        self.assertTrue(self.score('Prozac 1/20 mg')['ordered_pair_nearby'])


if __name__ == '__main__':
    unittest.main()
