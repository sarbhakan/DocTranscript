import json
from pathlib import Path
import unittest
from app.fixture_checks import check_fixture


class FixtureChecksTest(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads((Path(__file__).resolve().parents[2] / 'p0/fixtures/regressions.json').read_text())['cases']

    def test_equivalent_fraction_notation(self):
        ref = self.cases[0]['reference']
        for fraction in ('1 quart de', 'un quart de', '¼ de', '1/4 de'):
            with self.subTest(fraction=fraction):
                self.assertTrue(check_fixture(self.cases[0], ref.replace('1 quart de', fraction))['passed'])

    def test_feminine_capsule_quantity_is_equivalent_but_not_optional(self):
        case = {'reference': 'prozac 20 milligrammes 1 gélule matin et soir',
                'critical': {'dose': ['prozac 20 milligrammes']}, 'terms': ['prozac']}
        for amount in ('1', 'une'):
            with self.subTest(amount=amount):
                self.assertTrue(check_fixture(case, f'Prozac 20 mg, {amount} gélule matin et soir.')['passed'])
        for amount in ('2', 'deux', ''):
            with self.subTest(amount=amount):
                self.assertFalse(check_fixture(case, f'Prozac 20 mg, {amount} gélule matin et soir.')['passed'])
        self.assertFalse(check_fixture(case, 'Prozac 20 mg, une gélule matin et soir, puis une gélule.')['passed'])

    def test_mistakes_cannot_keep_presence_score_green(self):
        case = self.cases[0]
        ref = case['reference']
        for text in (
            ref.replace('7,5 milligrammes', '75 milligrammes'),
            ref.replace('1 quart', '1,5'),
            ref.replace('7,5 milligrammes', '7,5 mg/mL'),
            ref.replace('1 quart', 'pas 1 quart'),
            ref + ' puis 7,5 milligrammes',
            'imovane 7 mg ; 7,5 mg de prozac ; un quart de comprimé',
        ):
            with self.subTest(text=text):
                self.assertFalse(check_fixture(case, text)['passed'])

    def test_morning_and_evening_halves_are_distinct(self):
        case = self.cases[1]
        ref = case['reference']
        self.assertTrue(check_fixture(case, ref)['passed'])
        self.assertFalse(check_fixture(case, ref.replace('1 demi soir', '1,5 soir'))['passed'])
        self.assertFalse(check_fixture(case, ref.replace('1 demi soir', '1 demi le matin'))['passed'])
        changed = check_fixture(case, ref.replace('1 demi soir', '1,5 soir'))
        self.assertIn('½', changed['expected_numeric_sequence'])
        self.assertIn('1,5', changed['actual_numeric_sequence'])
        self.assertNotEqual(changed['expected_numeric_sequence'], changed['actual_numeric_sequence'])

    def test_alterations_hidden_by_legacy_normalization(self):
        case = self.cases[0]
        ref = case['reference']
        for erroneous, field in (
            (ref.replace('7,5 milligrammes', '−7,5 mg'), 'no_negative_number'),
            (ref.replace('7,5 milligrammes', 'moins sept virgule cinq mg'), 'no_negative_number'),
            (ref.replace('7,5 milligrammes', '7,5 mg ⁄ mL'), 'no_added_concentration'),
            (ref.replace('7,5 milligrammes', '7,5 mg ∕ kg'), 'no_added_concentration'),
            (ref.replace('7,5 milligrammes', '7,5 mg par comprimé'), 'no_added_concentration'),
            (ref.replace("débuter aujourd'hui", "ne débuter aujourd'hui"), 'no_added_negation'),
            (ref.replace("débuter aujourd'hui", "n'initier aujourd'hui"), 'no_added_negation'),
            (ref.replace('1 comprimé par jour', '1 par jour'), 'administered_form_amounts_equal'),
            (ref.replace('7 jours', '7 semaines'), 'duration_amounts_equal'),
        ):
            with self.subTest(erroneous=erroneous):
                result = check_fixture(case, erroneous)
                self.assertTrue(result['numeric_sequence_equal'])
                self.assertFalse(result[field])
                self.assertFalse(result['passed'])
        self.assertFalse(check_fixture(case, ref.replace('7,5 milligrammes', '7,5 microgrammes'))['passed'])

    def test_narration_order_is_distinct_from_fraction_association(self):
        case = self.cases[1]
        text = case['reference'].replace('1 demi le matin à 1 demi soir', '½ le soir, ½ le matin')
        result = check_fixture(case, text)
        self.assertEqual(result['critical_span_presence']['fraction'], [2, 2])
        self.assertTrue(result['numeric_sequence_equal'])
        self.assertFalse(result['fraction_spans_ordered'])
        self.assertTrue(result['passed'])


if __name__ == '__main__':
    unittest.main()
