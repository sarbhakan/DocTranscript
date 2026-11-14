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


if __name__ == '__main__':
    unittest.main()
