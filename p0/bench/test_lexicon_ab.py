"""Scorer safeguards for the actual NoteVive paired experiment."""
import json
from pathlib import Path
import tempfile
import unittest

from p0.lexicon_ab import annotated_matches, critical_words, score, words


class LexiconScoreTests(unittest.TestCase):
    def test_critical_preserves_differences(self):
        for left, right in (
            ("quatre cents milligrammes", "400 mg"),
            ("zéro virgule zéro soixante-quinze millilitres", "0,075 mL"),
            ("un demi-comprimé", "1/2 comprimé"),
            ("trois quarts de comprimé", "¾ comprimé"),
            ("zéro virgule treize pour cent", "0,13 %"),
        ):
            with self.subTest(left=left, right=right):
                self.assertEqual(critical_words(left), critical_words(right))
        for left, right in (
            ("400 mg", "4 mg"), ("0,075 mL", "0,75 mL"), ("0,3 mm", "0,3 mL"),
            ("un demi comprimé", "un quart de comprimé"), ("0,13 %", "0,3 %"),
            ("pas de douleur à droite", "douleur à droite"),
        ):
            with self.subTest(left=left, right=right):
                self.assertNotEqual(critical_words(left), critical_words(right))

    def test_do_not_credit_one_occurrence_twice(self):
        self.assertEqual(annotated_matches("deux bouffées", ["2 bouffées"] * 2, critical_words),
                         [("2 bouffées", True), ("2 bouffées", False)])
        self.assertEqual(annotated_matches("maladie d'Erdheim-Chester",
                                          ["Erdheim Chester", "Erdheim"], words),
                         [("Erdheim Chester", True), ("Erdheim", True)])

    def test_paired_regression_is_not_hidden_by_an_improved_term(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "cases.json").write_text(json.dumps([
                {"id": "sample", "kind": "synth", "profile": "h", "terms": ["caplacizumab"],
                 "reference": "caplacizumab quatre cents milligrammes", "lures": [],
                 "critical": {"dose": ["400 mg"]}, "speech_ends_ms": []}
            ]))
            (path / "profiles.json").write_text(json.dumps(
                {"profiles": [{"id": "h", "active": ["caplacizumab"], "entries": ["caplacizumab"]}]}
            ))
            inputs = [
                {"id": "sample", "arm": arm, "repeat": 0, "profile": profile, "pause": [],
                 "stop": [{"text": transcript, "decode_ms": 123}], "elapsed_ms": 135,
                 "accepted_terms": 1 if profile else 0}
                for arm, profile, transcript in (
                    ("off", "", "caplace quatre cents milligrammes"),
                    ("on", "h", "caplacizumab quatre milligrammes"),
                )
            ]
            (path / "results.ndjson").write_text("\n".join(map(json.dumps, inputs)))
            report = score(path, path / "results.ndjson", path / "profiles.json")
            self.assertEqual(report["rare_expected"], 1)
            self.assertEqual(report["rare_active"], 1)
            self.assertEqual(report["comparisons"]["on"]["rare_gains"][0]["term"], "caplacizumab")
            self.assertEqual(report["comparisons"]["on"]["new_critical_errors"][0]["span"], "400 mg")
            self.assertEqual(report["timing"]["off"]["segment_decode_ms"]["p95"], 123)


if __name__ == "__main__":
    unittest.main()
