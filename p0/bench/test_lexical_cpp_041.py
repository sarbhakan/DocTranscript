import unittest

from p0.lexical_cpp_041 import name_counts, pair, word_edits


def result(text, n, fingerprint="19cc"):
    return {"text": text, "tokens_in_prompt": n, "segments": [{"frames": 320, "float32_fnv1a64": fingerprint,
            "phase": "pause", "received_audio_samples": 48000}]}


class NativeContextTest(unittest.TestCase):
    def test_reversed_pair_and_fingerprint_guard(self):
        calls = []

        def infer(pcm, prompt, direct):
            calls.append((pcm, prompt, direct))
            return result("fictif", 3 if prompt else 0)

        pair(infer, b"\0\0", "médicament", 1, True)
        self.assertEqual(calls, [(b"\0\0", "médicament", True), (b"\0\0", "", True)])

        def divide_differently(_pcm, prompt, _direct):
            return result("fictif", 3 if prompt else 0, "0000" if prompt else "0001")

        with self.assertRaises(RuntimeError):
            pair(divide_differently, b"\0\0", "médicament", 0)

    def test_new_false_name_cannot_be_hidden_by_other_false_name_removed(self):
        observations = {"base": {"text": "essai de paracétamol"},
                        "context": {"text": "essai de digoxine"}}
        counted = name_counts("note fictive", observations, ["paracétamol", "digoxine"])
        self.assertEqual((counted["false_base"], counted["false_context"], counted["new_false_with_context"]), (1, 1, 1))

    def test_one_reference_occurrence_does_not_justify_a_repeat(self):
        observations = {"base": {"text": "fictif"}, "context": {"text": "vitamine C vitamine C"}}
        counted = name_counts("une note qui cite vitamine C", observations, ["vitamine C"])
        self.assertEqual((counted["gained_correct_with_context"], counted["new_false_with_context"]), (1, 1))

    def test_omission_is_reported_as_deletion_when_alignable(self):
        self.assertEqual(word_edits(["jamais", "de", "douleur", "gauche"], ["jamais", "de", "gauche"]),
                         {"substitutions": 0, "deletions": 1, "insertions": 0})


if __name__ == "__main__":
    unittest.main()
