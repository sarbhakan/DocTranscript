"""The prompt replay never removes text dictated by the model itself."""
from types import SimpleNamespace
import unittest

from p0.training.replay_drug_prompt import generated_only, prompt_ids, PLAN_LIMIT
from p0.training.train_lora import EOS, PREFIX


class Row(list):
    ndim = 1

    def tolist(self):
        return list(self)

    def numel(self):
        return len(self)


class DrugPromptReplayTests(unittest.TestCase):
    def test_strips_only_input_context_and_reports_end(self):
        context = [50361, 41, 42]
        generated = SimpleNamespace(sequences=[Row(context + PREFIX + [41, 42, EOS])])
        self.assertEqual(generated_only(generated, context), ([41, 42, EOS], True))
        self.assertEqual(generated_only(SimpleNamespace(sequences=[Row(PREFIX + [41])]), []), ([41], False))
        with self.assertRaisesRegex(ValueError, "séquence"):
            generated_only(generated, [50361, 41])

    def test_trims_tail_by_fixed_context_budget_and_rejects_quantity(self):
        tokenizer = SimpleNamespace(convert_tokens_to_ids=lambda _: 50361)
        processor = SimpleNamespace(tokenizer=tokenizer,
                                    get_prompt_ids=lambda text, **kw: Row([50361] + [7] * 32 * len(text.split(","))))
        terms, ids = prompt_ids(processor, ["Azurin", "Bétalix"])
        self.assertEqual(terms, ["Azurin"])
        self.assertLessEqual(ids.numel(), PLAN_LIMIT)
        with self.assertRaisesRegex(ValueError, "Liste médicament"):
            prompt_ids(processor, ["Azurine 20 mg"])


if __name__ == "__main__":
    unittest.main()
