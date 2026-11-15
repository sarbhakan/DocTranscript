"""Drug-only masks and bounded optimizer checks without audio or model weights."""
import importlib.util
import unittest

from p0.training.drug_objective import lexical_positions, marked_characters
from p0.training.report_stability import paired
from p0.training.shadow_optimizer import cpu_shadow_adamw
from p0.training.train_lora import EOS, PREFIX, cross_entropy


class FrozenTokenizer:
    is_fast = True

    def __init__(self, body_ids, body_offsets):
        self.ids = [*PREFIX, *body_ids, EOS]
        self.offsets = [(0, 0)] * len(PREFIX) + body_offsets + [(0, 0)]

    def __call__(self, *_args, **_kwargs):
        return {"input_ids": self.ids, "offset_mapping": self.offsets}


class MaskTests(unittest.TestCase):
    def test_no_promotion_of_dose_or_unmarked_conjunction(self):
        source = "sans médicament 20 mg"
        tokenizer = FrozenTokenizer([10, 11, 12, 13, 14, 15, 16],
                                   [(0, 4), (4, 8), (8, 15), (14, 18), (16, 18), (18, 21), (0, 0)])
        positions, stats = lexical_positions(tokenizer, source, "O B-drug B-d_dos_val B-d_dos_up",
                                               tokenizer.ids[1:], PREFIX, EOS)
        self.assertEqual(positions, [4, 5])  # Two subtokens, one includes a leading space.
        self.assertEqual(stats["weighted_subtokens"], 2)

    def test_bad_source_name_annotations_are_skipped(self):
        mask, stats = marked_characters("MotInitial dossier 20 Zeta sans Traitement Test",
                                       "I-drug O B-drug I-drug B-drug B-drug I-drug")
        self.assertEqual(stats["orphan_inside_tags_excluded"], 1)
        self.assertEqual(stats["suspect_entities_excluded"], 2)
        self.assertEqual(stats["accepted_drug_entities"], 1)
        self.assertEqual("".join("MotInitial dossier 20 Zeta sans Traitement Test"[i] for i in sorted(mask)),
                         "TraitementTest")

    def test_misaligned_token_ids_and_invalid_offsets_are_refused(self):
        tokenizer = FrozenTokenizer([10], [(0, 99)])
        with self.assertRaisesRegex(ValueError, "offsets ne suivent"):
            lexical_positions(tokenizer, "Nom", "B-drug", [12], PREFIX, EOS)
        with self.assertRaisesRegex(ValueError, "hors de la référence"):
            lexical_positions(tokenizer, "Nom", "B-drug", tokenizer.ids[1:], PREFIX, EOS)

    def test_paired_counts_expose_a_loss_hidden_by_total_gain(self):
        before = [{"span:drug": [True, False], "span:dose": [True]}, {"span:drug": [False]}]
        after = [{"span:drug": [False, True], "span:dose": [True]}, {"span:drug": [True]}]
        report = paired(before, after)
        self.assertEqual(report["losses"], {"span:drug": 1})
        self.assertEqual(report["gains"], {"span:drug": 2})
        self.assertEqual(report["clips_with_loss"], {"span:drug": 1, "any_critical_check": 1})
        with self.assertRaises(ValueError):
            paired(before[:1], after)


@unittest.skipUnless(importlib.util.find_spec("torch"), "Torch local absent")
class OptimizerTests(unittest.TestCase):
    def test_matches_clipped_adamw_weights_and_moments_and_resets(self):
        import torch
        reference = [torch.nn.Parameter(torch.tensor(v)) for v in ([0.4, -0.2], [0.8])]
        actual = [torch.nn.Parameter(t.detach().clone()) for t in reference]
        shadow = cpu_shadow_adamw(torch, actual, lr=1e-3, weight_decay=0.01)
        plain = torch.optim.AdamW(reference, lr=1e-3, weight_decay=0.01, foreach=False)
        steps = []
        shadow.register_step_post_hook(lambda *_: steps.append(True))
        for scale in (1.0, -0.6, 2.0):
            for optimizer, weights in ((plain, reference), (shadow, actual)):
                optimizer.zero_grad(set_to_none=True)
                self.assertTrue(all(x.grad is None for x in weights))
                weights[0].grad, weights[1].grad = torch.tensor([scale, -2 * scale]), torch.tensor([3 * scale])
                torch.nn.utils.clip_grad_norm_(weights, 1.0, error_if_nonfinite=True, foreach=False)
                optimizer.param_groups[0]["lr"] = 0.001 / (1 + abs(scale))
                optimizer.step()
            for x, y, copy in zip(reference, actual, shadow.shadow, strict=True):
                self.assertTrue(torch.equal(x, y))
                self.assertTrue(torch.equal(copy, y))
                self.assertIsNone(copy.grad)
                self.assertEqual(x.dtype, torch.float32)
                for key in ("exp_avg", "exp_avg_sq"):
                    self.assertTrue(torch.equal(plain.state[x][key], shadow.cpu_adamw.state[copy][key]))
        self.assertEqual(len(steps), 3)

    def test_grad_scaler_uses_live_parameters_and_nonfinite_never_moves_weights(self):
        import torch
        value = torch.nn.Parameter(torch.tensor([0.4, -0.2]))
        safe = cpu_shadow_adamw(torch, [value], lr=1e-3, weight_decay=0.01)
        scaler = torch.amp.GradScaler("cpu", init_scale=16.0)
        scaler.scale(value.square().sum()).backward()
        scaler.unscale_(safe)
        self.assertTrue(torch.equal(value.grad, torch.tensor([0.8, -0.4])))
        scaler.step(safe)
        scaler.update()
        snapshot = value.detach().clone()
        safe.zero_grad(set_to_none=True)
        with self.assertRaisesRegex(ValueError, "gradient absent"):
            safe.step()
        value.grad = torch.tensor([float("nan"), 3.0])
        with self.assertRaisesRegex(ValueError, "gradient non fini"):
            safe.step()
        self.assertTrue(torch.equal(value, snapshot))
        self.assertEqual(safe.cpu_adamw.state[safe.shadow[0]]["step"].item(), 1)

    def test_weighted_ce_normalizes_by_weights_and_leaves_padding_out(self):
        import torch
        logits = torch.tensor([[[4.0, 3.0], [6.0, -1.0], [1.0, 0.0], [3.0, -3.0]]], requires_grad=True)
        targets = torch.tensor([[0, 1, 0, -100]])
        reference = torch.nn.functional.cross_entropy(logits.view(-1, 2), targets.view(-1), reduction="none")
        observed = cross_entropy(torch, logits, targets, [1], 2.0)
        self.assertTrue(torch.allclose(observed, (reference[0] + 2 * reference[1] + reference[2]) / 4))
        self.assertTrue(torch.equal(cross_entropy(torch, logits, targets, [], 2.0), reference.sum() / 3))
        observed.backward()
        self.assertTrue(torch.all(logits.grad[0, 3] == 0))


if __name__ == "__main__":
    unittest.main()
