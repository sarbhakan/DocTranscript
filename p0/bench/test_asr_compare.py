"""High-risk scoring behavior for the paired ASR benchmark."""
import unittest

from p0.asr_compare import annotated_matches, meaning_words, px_posology


class BenchmarkScoringTests(unittest.TestCase):
    def test_decimal_unit_and_polarity(self):
        ref = ["dix grammes et non dix milligrammes"]
        for example, ok in [
            ("10 g, et non dix mg.", True),
            ("10 g et dix mg.", False),
            ("10 mg et non 10 g.", False),
            ("10,1 g et non 10 mg.", False),
        ]:
            with self.subTest(example=example):
                self.assertEqual(annotated_matches(example, ref, meaning_words)[0][1], ok)

    def test_human_repeat_must_not_be_credited_twice(self):
        reference = "1 demi et 1 demi"
        labels = "B-dos_val I-dos_val O B-dos_val I-dos_val"
        checks = px_posology(reference, labels, "un demi, puis un et demi")
        self.assertEqual([ok for _, ok in checks["fraction"]], [True, False])

    def test_annotated_unit_requires_adjacent_quantity(self):
        reference = "1 comprimé pendant 2 jours"
        labels = "B-dos_val B-dos_uf O B-dur_val B-dur_ut"
        checks = px_posology(reference, labels, "2 comprimés pendant un jour")
        self.assertFalse(checks["administered"][0][1])
        self.assertFalse(checks["duration"][0][1])


if __name__ == "__main__":
    unittest.main()
