import unittest
from lexique.short_context import ranked_candidates, bounded_prefix


class ShortContextTest(unittest.TestCase):
    def test_train_only_exact_whole_names_no_oracle_or_strength(self):
        train = [dict(id="1", partition="train", text="Substance école et molécule."),
                 dict(id="2", partition="train", text="substance école école 2 mg")]
        terms = [dict(code=str(i), libelle=t, categorie="substance") for i, t in enumerate(
            ["molécule", "Substance école", "Substance", "école 2 mg", "sans molécule", "demimolécule"])]
        result = ranked_candidates(train, terms)
        self.assertEqual([x["term"] for x in result], ["Substance", "Substance école", "molécule"])
        self.assertEqual([x["training_clips"] for x in result], [2, 2, 1])
        train[0]["partition"] = "validation"
        with self.assertRaises(ValueError):
            ranked_candidates(train, terms)

    def test_token_limit_stops_prefix_does_not_cherry_pick(self):
        rows = [dict(term="école"), dict(term="extraordinairement-long"), dict(term="un")]
        selected, prompt, count = bounded_prefix(rows, lambda text: len(text) * 3)
        self.assertEqual(selected, rows[:1])
        self.assertEqual(prompt, "école.")
        self.assertEqual(count, 18)

    def test_term_limit_and_duplicate_training_ids(self):
        rows = [dict(term="mot" + str(i)) for i in range(20)]
        self.assertEqual(len(bounded_prefix(rows, lambda text: 2)[0]), 16)
        with self.assertRaises(ValueError):
            ranked_candidates([dict(id="1", partition="train", text="x")] * 2, [])


if __name__ == "__main__":
    unittest.main()
