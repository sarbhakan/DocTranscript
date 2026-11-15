"""Tests of the isolated LoRA retention experiment, without loading ASR weights."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from p0.training.train_lora import PREFIX, EOS, checkpoint, forward_loss, token_retention, validation_window


class ValidationWindowTests(unittest.TestCase):
    def test_windows_are_disjoint_and_keep_voice_balance(self):
        rows = [{"id": str(speaker * 100 + index), "speaker_id": str(speaker),
                 "partition": "validation", "text": "irrelevant"}
                for speaker in range(8) for index in range(14)]
        historical = validation_window(rows, 32)
        extra = validation_window(list(reversed(rows)), 64, 32)
        self.assertEqual(historical + extra, validation_window(rows, 96))
        self.assertEqual(len({row["id"] for row in historical} & {row["id"] for row in extra}), 0)
        self.assertEqual([sum(row["speaker_id"] == str(speaker) for row in extra)
                          for speaker in range(8)], [8] * 8)
        self.assertEqual(len(validation_window(rows, 0, 32)), 80)
        for count, offset in [(17, 96), (1, 112), (2, -1), (-1, 0)]:
            with self.subTest(count=count, offset=offset), self.assertRaises(ValueError):
                validation_window(rows, count, offset)


class RetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError as error:
            raise unittest.SkipTest("PyTorch absent de ce venv de tests") from error
        cls.torch = torch

    def test_kl_direction_per_valid_token_and_no_teacher_gradient(self):
        torch = self.torch
        student = torch.zeros((1, 6, 2), requires_grad=True)
        teacher = torch.tensor([[[20., 0.], [20., 0.], [20., 0.],
                                 [2., 0.], [0., 0.], [20., 0.]]], requires_grad=True)
        loss = token_retention(torch, student, teacher, 5)
        probs = torch.softmax(torch.tensor([2., 0.]), dim=0)
        expected = torch.sum(probs * (probs.log() - torch.tensor(0.5).log())) / 2
        self.assertAlmostEqual(loss.item(), expected.item(), places=6)
        loss.backward()
        self.assertIsNone(teacher.grad)
        self.assertEqual(torch.count_nonzero(student.grad[:, [0, 1, 2, 4, 5]]).item(), 0)
        self.assertLess(student.grad[0, 3, 0].item(), 0)

    def test_teacher_does_not_record_gradient_or_change_training_modes(self):
        torch = self.torch
        calls = []

        class Encoder(torch.nn.Module):
            def forward(self, input_features, **kwargs):
                calls.append(("encoder", self.training, torch.is_grad_enabled()))
                return input_features

        class Toy(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = Encoder()
                self.adapter = torch.nn.Parameter(torch.zeros((1, 6, 51866)))
                self.disabled = False

            def get_encoder(self):
                return self.encoder

            @contextmanager
            def disable_adapter(self):
                self.disabled = True
                self.adapter.requires_grad_(False)
                try:
                    yield
                finally:
                    self.disabled = False
                    self.adapter.requires_grad_(True)

            def forward(self, encoder_outputs, **kwargs):
                calls.append(("teacher" if self.disabled else "student", self.training,
                              torch.is_grad_enabled()))
                return SimpleNamespace(logits=encoder_outputs if self.disabled else encoder_outputs + self.adapter)

        model = Toy().train()
        model.encoder.eval()
        labels = PREFIX[1:] + [1200, EOS, -100]
        features = torch.zeros_like(model.adapter)
        loss, _, ce, kl = forward_loss({"torch": torch}, model, model, features, labels, "cpu", "float32", 0.35)
        self.assertEqual(calls, [("encoder", False, False), ("teacher", False, False), ("student", True, True)])
        self.assertTrue(model.training)
        self.assertFalse(model.encoder.training)
        self.assertAlmostEqual(loss.item(), ce.item(), places=6)
        self.assertAlmostEqual(kl.item(), 0.0, places=6)
        loss.backward()
        self.assertTrue(torch.isfinite(model.adapter.grad).all())
        self.assertGreater(torch.count_nonzero(model.adapter.grad).item(), 0)
        calls.clear()
        control_loss, _, _, control_kl = forward_loss(
            {"torch": torch}, model, model, features, labels, "cpu", "float32")
        self.assertIsNone(control_kl)
        self.assertEqual(calls, [("encoder", False, False), ("student", True, True)])
        self.assertAlmostEqual(control_loss.item(), loss.item(), places=6)

    def test_checkpoint_rejects_nonfinite_adapter_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rt = {"torch": self.torch, "state": lambda model: {
                "adapter": self.torch.tensor([float("nan")])}}
            with self.assertRaisesRegex(ValueError, "sauvegarde refusée"):
                checkpoint(rt, None, root, 2, "contract")
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
