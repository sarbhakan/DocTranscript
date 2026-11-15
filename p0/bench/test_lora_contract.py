"""Offline training contracts; no torch, transformers, GPU or speech inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from p0.training import train_lora as runner
from p0.training import export_lora as exporter


def row(index, speaker, partition="validation"):
    return {"id": f"px-{index}", "speaker_id": f"px-{speaker}", "partition": partition,
            "pcm_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
            "text": f"référence fictive numéro {index}"}


class LoRAContractTests(unittest.TestCase):
    def test_module_import_does_not_import_training_libraries(self):
        code = ("import sys; import p0.training.train_lora; import p0.training.export_lora; "
                "assert not ({'torch', 'transformers', 'peft', 'numpy'} & set(sys.modules))")
        result = subprocess.run([sys.executable, "-c", code], cwd=runner.REPO,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_decoder_projections_are_matched(self):
        self.assertEqual(len(runner.TARGETS), 16)
        for name in runner.TARGETS:
            self.assertIsNotNone(re.fullmatch(runner.TARGET_RE, name))
        forbidden = ["model.encoder.layers.0.self_attn.q_proj", "model.decoder.layers.4.self_attn.v_proj",
                     "model.decoder.layers.0.self_attn.k_proj", "model.decoder.layers.0.encoder_attn.out_proj",
                     "model.decoder.layers.0.self_attn.q_proj.extra"]
        for name in forbidden:
            self.assertIsNone(re.fullmatch(runner.TARGET_RE, name))
        self.assertEqual(16 * (1280 * 8 + 8 * 1280), runner.LORA_PARAMETERS)

    def test_sot_removed_eos_kept_and_padding_masked(self):
        ids = runner.PREFIX + [1200, 1500, runner.EOS, runner.EOS, runner.EOS]
        labels = runner.label_ids(ids, [1] * 7 + [0, 0])
        self.assertEqual(labels, runner.PREFIX[1:] + [1200, 1500, runner.EOS, -100, -100])
        self.assertEqual(runner.shift_labels(labels),
                         [runner.SOT] + runner.PREFIX[1:] + [1200, 1500, runner.EOS, runner.EOS])

    def test_missing_eos_wrong_language_and_repeated_sot_rejected(self):
        fixtures = [runner.PREFIX + [1200, 1500],
                    [runner.SOT, 50259, runner.TRANSCRIBE, runner.NO_TIMESTAMPS, 1200, runner.EOS],
                    runner.PREFIX + [runner.SOT, 1200, runner.EOS],
                    runner.PREFIX + [runner.TRANSCRIBE, 1200, runner.EOS],
                    runner.PREFIX + [runner.EOS, 1200, runner.EOS],
                    runner.PREFIX + [runner.EOS]]
        for ids in fixtures:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                runner.label_ids(ids, [1] * len(ids))

    def test_maximum_is_checked_after_removing_sot_without_truncation(self):
        ids = runner.PREFIX + [1200] * 444 + [runner.EOS]
        self.assertEqual(len(runner.label_ids(ids, [1] * len(ids))), 448)
        ids.insert(4, 1201)
        with self.assertRaises(ValueError):
            runner.label_ids(ids, [1] * len(ids))

    def test_non_contiguous_or_wrong_masks_rejected(self):
        ids = runner.PREFIX + [1200, runner.EOS]
        for mask in ([1, 1], [1, 1, 1, 1, 0, 1], [1, 1, 1, 1, 2, 1]):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                runner.label_ids(ids, mask)

    def test_validation_selection_uses_ids_and_voices_not_references(self):
        rows = [row(speaker * 100 + index, speaker) for speaker in range(8) for index in range(6)]
        selected = runner.validation_selection(rows, 32)
        modified = [dict(item, text="référence remplacée sans modifier la sélection") for item in reversed(rows)]
        self.assertEqual([item["id"] for item in selected],
                         [item["id"] for item in runner.validation_selection(modified, 32)])
        self.assertEqual(len(selected), 32)
        self.assertEqual({speaker: sum(item["speaker_id"] == speaker for item in selected)
                          for speaker in {item["speaker_id"] for item in rows}},
                         {f"px-{speaker}": 4 for speaker in range(8)})

    def test_selection_handles_uneven_voice_counts_and_all(self):
        rows = [row(0, 0)] + [row(index, 1) for index in range(1, 7)]
        self.assertEqual({item["id"] for item in runner.validation_selection(rows, 0)},
                         {item["id"] for item in rows})
        self.assertEqual(len(runner.validation_selection(rows, 6)), 6)

    def test_training_rows_duplicates_and_excess_count_not_allowed_in_validation(self):
        for rows, count in (([row(1, 1, "train")], 1), ([row(1, 1), row(1, 1)], 1),
                            ([row(1, 1)], 2), ([], 0), ([row(1, 1)], -1)):
            with self.subTest(rows=rows, count=count), self.assertRaises(ValueError):
                runner.validation_selection(rows, count)

    def test_cross_partition_speaker_audio_id_reference_rejected(self):
        train = row(1, 1, "train")
        validation = row(2, 2)
        runner.verify_partition_contract({"train": [train], "validation": [validation]})
        for field in ("speaker_id", "pcm_sha256", "id", "text"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.verify_partition_contract({"train": [train], "validation": [dict(validation, **{field: train[field]})]})

    def test_accumulation_keeps_last_clip_with_its_actual_group_size(self):
        groups = list(runner.accumulation_groups(list(range(1081)), 4))
        self.assertEqual(len(groups), 271)
        self.assertEqual([value for group in groups for value in group], list(range(1081)))
        self.assertEqual(len(groups[-1]), 1)
        self.assertEqual(sum(1 / len(group) for group in groups[-1:] for value in group), 1)

    def test_learning_rate_warmup_and_final_step_are_positive(self):
        rates = [runner.learning_rate(index, 271, 1e-4) for index in range(1, 272)]
        self.assertTrue(all(0 < value <= 1e-4 for value in rates))
        self.assertEqual(rates.index(max(rates)), 27)
        self.assertGreater(rates[1], rates[0])
        self.assertLess(rates[-1], rates[28])
        with self.assertRaises(ValueError):
            runner.learning_rate(272, 271, 1e-4)

    def test_output_refuses_existing_repository_and_source_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            source.mkdir()
            for destination in (source, source / "results", runner.REPO / "private-training"):
                with self.subTest(destination=destination), self.assertRaises(ValueError):
                    runner.output_path(destination, [source], 0)

    def test_disk_budget_failure_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-results"
            with patch.object(runner.shutil, "disk_usage", return_value=argparse.Namespace(free=1024)):
                with self.assertRaisesRegex(ValueError, "Espace libre insuffisant"):
                    runner.output_path(output, [], 1025)
            self.assertFalse(output.exists())

    def test_output_refuses_link_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "linked"
            try:
                destination.symlink_to(root / "missing", target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation unavailable on this host")
            with self.assertRaises(ValueError):
                runner.output_path(destination, [], 0)

    def test_full_architecture_is_fixed_but_context_generation_is_not_mutated(self):
        config = {"d_model": 1280, "encoder_layers": 32, "decoder_layers": 4,
                  "num_mel_bins": 128, "max_target_positions": 448, "max_source_positions": 1500,
                  "vocab_size": 51866, "decoder_start_token_id": runner.SOT,
                  "eos_token_id": runner.EOS, "pad_token_id": runner.EOS}
        runner.validate_architecture(config)
        for field, value in (("num_mel_bins", 80), ("decoder_layers", 32), ("max_target_positions", 128)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.validate_architecture(dict(config, **{field: value}))
        self.assertNotIn("max_length", config)
        self.assertLessEqual(4 + runner.GENERATION["max_new_tokens"], 448)

    def test_atomic_json_replaces_complete_file_and_rejects_nonfinite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            runner.atomic_json(path, {"status": "first"})
            runner.atomic_json(path, {"status": "second", "updates": 8})
            self.assertEqual(json.loads(path.read_text()), {"status": "second", "updates": 8})
            with self.assertRaises(ValueError):
                runner.atomic_json(path, {"loss": float("nan")})
            self.assertEqual(json.loads(path.read_text())["status"], "second")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_default_is_eight_updates_and_no_implicit_resume(self):
        options = runner.parser().parse_args(["train", "--model", "/x/base", "--corpus", "/x/corpus",
                                              "--px-archive", "/x/source.zip", "--output", "/x/run"])
        self.assertEqual(options.max_updates, 8)
        self.assertEqual(options.accumulation, 4)
        self.assertEqual(options.epochs, 1)
        self.assertFalse(hasattr(options, "resume"))

    def test_eos_is_observed_in_raw_structured_generation_sequence(self):
        class Tokens:
            def __init__(self, values):
                self.values = values

            def tolist(self):
                return self.values
        finished = runner.PREFIX + [1200, runner.EOS]
        self.assertEqual(runner.generated_sequence(SimpleNamespace(sequences=[Tokens(finished)])), (finished, True))
        limited = runner.PREFIX + [1200, 1300]
        self.assertEqual(runner.generated_sequence(SimpleNamespace(sequences=[Tokens(limited)])), (limited, False))
        for invalid in ([Tokens([1200])], SimpleNamespace(sequences=[]),
                        SimpleNamespace(sequences=[Tokens([1200, runner.EOS])])):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                runner.generated_sequence(invalid)

    def test_failed_run_or_changed_adapter_cannot_be_evaluated_as_validated_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory).resolve()
            adapter = run / "checkpoints" / "update-000008"
            adapter.mkdir(parents=True)
            provenance, manifests = {"revision": "fixture"}, {"train": "train-sha", "validation": "validation-sha"}
            contract = {"base": provenance, "manifest_sha256": manifests, "corpus_source_sha256": runner.PX_SHA256,
                        "target_modules": runner.TARGETS, "rank": 8}
            for name in ("adapter_model.safetensors", "adapter_config.json"):
                (adapter / name).write_text("fixture")
            metadata = {"schema": 1, "actual_optimizer_updates": 8,
                        "contract_sha256": runner.json_digest(contract),
                        "files_sha256": {path.name: runner.sha256(path) for path in adapter.iterdir()}}
            report = {"status": "completed", "base_weights_unchanged": True, "adapter_reload_exact": True,
                      "contract_sha256": metadata["contract_sha256"], "actual_optimizer_updates": 8}
            runner.atomic_json(run / "contract.json", contract)
            runner.atomic_json(run / "report.json", report)
            runner.atomic_json(adapter / "checkpoint.json", metadata)
            self.assertEqual(runner.verify_adapter(adapter, provenance, manifests), metadata)
            for extra in ("adapter_model.safetensors.index.json", "adapter_model.bin", "unexpected"):
                (adapter / extra).write_text("unverified alternative")
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    runner.verify_adapter(adapter, provenance, manifests)
                (adapter / extra).unlink()
            runner.atomic_json(run / "report.json", dict(report, status="failed"))
            with self.assertRaises(ValueError):
                runner.verify_adapter(adapter, provenance, manifests)
            runner.atomic_json(run / "report.json", report)
            (adapter / "adapter_model.safetensors").write_text("changed")
            with self.assertRaises(ValueError):
                runner.verify_adapter(adapter, provenance, manifests)

    @unittest.skipUnless(os.environ.get("NOTEVIVE_LORA_RUNTIME_TEST") == "1", "Optional tiny PEFT runtime regression")
    def test_real_peft_fp32_reload_is_exact_on_half_precision_base(self):
        # This is a 3x3 CPU Linear, not Whisper, speech inference or training.
        import torch
        from peft import LoraConfig, get_peft_model, get_peft_model_state_dict
        runtime = {"torch": torch, "LoraConfig": LoraConfig, "get_peft_model": get_peft_model,
                   "state": get_peft_model_state_dict}
        base = torch.nn.Sequential(torch.nn.Linear(3, 3, bias=False)).half()
        model = get_peft_model(base, LoraConfig(r=2, lora_alpha=4, target_modules=["0"]),
                               autocast_adapter_dtype=True)
        with torch.no_grad():
            for name, value in model.named_parameters():
                if "lora_" in name:
                    value.fill_(0.123456789)  # Deliberately not exactly representable in FP16.
        expected = {key: value.detach().cpu().clone() for key, value in get_peft_model_state_dict(model).items()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            model.save_pretrained(path, safe_serialization=True, save_embedding_layers=False)
            runner.reload_check(runtime, model, path)
            restored_base = torch.nn.Sequential(torch.nn.Linear(3, 3, bias=False)).half()
            restored = runner.load_existing_adapter(runtime, restored_base, path)
            actual = get_peft_model_state_dict(restored)
            self.assertEqual(expected.keys(), actual.keys())
            for name, value in expected.items():
                self.assertEqual(actual[name].dtype, torch.float32)
                self.assertTrue(torch.equal(value, actual[name].detach().cpu()))

    def test_offline_preflight_calls_locked_archive_and_model_verifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            corpus, model = root / "corpus", root / "model"
            corpus.mkdir()
            model.mkdir()
            for partition, data in (("train", [row(1, 1, "train")]), ("validation", [row(2, 2)])):
                (corpus / f"{partition}.jsonl").write_text("".join(json.dumps(value) + "\n" for value in data))
            args = argparse.Namespace(corpus=corpus, model=model, output=root / "output",
                                      px_archive=root / "source.zip", min_free_gib=1)
            with patch.object(runner, "verify_export", return_value={"verified": True}) as archive_check, \
                    patch("p0.training.fetch_model.verify_model", return_value={"revision": "fixture"}) as model_check, \
                    patch.object(runner.shutil, "disk_usage", return_value=argparse.Namespace(free=2 * 1024 ** 3)):
                prepared = runner.prepare(args)
            archive_check.assert_called_once_with(corpus, args.px_archive)
            model_check.assert_called_once_with(model)
            self.assertEqual(prepared[5], {"revision": "fixture"})
            self.assertFalse(args.output.exists())


class LoRAExportContractTests(unittest.TestCase):
    def test_merge_rejects_changes_outside_exact_lora_weights(self):
        target = sorted(exporter.TARGET_WEIGHTS)[0]
        before = {target: "old", "model.encoder.conv1.weight": "same"}
        after = dict(before, **{target: "new"})
        self.assertEqual(exporter.changed_weights(before, after, True), [target])
        self.assertEqual(exporter.changed_weights(before, before, False), [])
        for candidate, adapted in ((before, True), (after, False),
                                   (dict(after, **{"model.encoder.conv1.weight": "changed"}), True),
                                   ({target: "new"}, True)):
            with self.subTest(candidate=candidate, adapted=adapted), self.assertRaises(ValueError):
                exporter.changed_weights(before, candidate, adapted)

    def test_ggml_header_requires_turbo_mel_context_and_quantization(self):
        header = [0x67676D6C, 51866, 1500, 1280, 20, 32, 448, 1280, 20, 4, 128, 2008, 128, 201]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(struct.pack("<14i", *header))
            self.assertEqual(exporter.ggml_header(path, 2008)["text_context"], 448)
            with self.assertRaises(ValueError):
                exporter.ggml_header(path, 1)
            for index, value in ((6, 20), (9, 32), (10, 80), (11, 8), (12, 80)):
                invalid = list(header)
                invalid[index] = value
                path.write_bytes(struct.pack("<14i", *invalid))
                with self.subTest(index=index), self.assertRaises(ValueError):
                    exporter.ggml_header(path, 2008)
            path.write_bytes(b"truncated")
            with self.assertRaises(ValueError):
                exporter.ggml_header(path, 2008)

    def test_metadata_copy_preserves_bytes_and_never_copies_source_weights(self):
        config = {"d_model": 1280, "encoder_layers": 32, "decoder_layers": 4,
                  "num_mel_bins": 128, "max_target_positions": 448, "max_source_positions": 1500,
                  "vocab_size": 51866, "decoder_start_token_id": runner.SOT,
                  "eos_token_id": runner.EOS, "pad_token_id": runner.EOS}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, destination = root / "source", root / "target"
            source.mkdir()
            destination.mkdir()
            (source / "config.json").write_text(json.dumps(config, indent=3) + "\n")
            (source / "vocab.json").write_bytes(b'{ "fake": 0 }\n')
            (source / "model.safetensors").write_bytes(b"source weights")
            (destination / "model.safetensors").write_bytes(b"new adapted weights")
            provenance = {"sha256": {path.name: runner.sha256(path) for path in source.iterdir()}}
            result = exporter.copy_source_metadata(source, destination, provenance)
            self.assertEqual(set(result), {"config.json", "vocab.json"})
            self.assertEqual((destination / "model.safetensors").read_bytes(), b"new adapted weights")
            for name in result:
                self.assertEqual((destination / name).read_bytes(), (source / name).read_bytes())
            self.assertNotIn("max_length", json.loads((destination / "config.json").read_text()))

    def test_converter_and_asset_hashes_reject_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"
            path.write_bytes(b"locked fixture")
            digest = runner.sha256(path)
            self.assertEqual(exporter.locked_file(path, digest), path.resolve())
            path.write_bytes(b"changed fixture")
            with self.assertRaises(ValueError):
                exporter.locked_file(path, digest)


if __name__ == "__main__":
    unittest.main()
