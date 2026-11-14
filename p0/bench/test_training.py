"""Leakage and provenance checks for the local PxCorpus adaptation exporter."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from zipfile import ZipFile

from p0.training import prepare_px as px


def wav_bytes(value, rate=16000, frames=512):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(int(value).to_bytes(2, "little", signed=True) * frames)
    return stream.getvalue()


def make_archive(path, mutate=None):
    fields = {"paths": [], "text": [], "tags": [], "metadata": []}
    audios, splits = {}, {"train": [], "dev": [], "test": [0]}
    for index in range(13):
        speaker = (index + 1) // 2 if index else 99
        category = "doctor" if index == 0 else "expert" if speaker % 2 else "non-expert"
        text = f"phrase fictive pour la voix {speaker} prise {index}"
        fields["paths"].append(f"session{speaker}/recording_{index}.wav")
        fields["text"].append(text)
        fields["tags"].append(" ".join("O" for _ in text.split()))
        fields["metadata"].append(f"{speaker},18–28,F,{category}")
        audios[fields["paths"][-1]] = wav_bytes(index + 1)
        if index:
            splits["train" if index % 2 else "dev"].append(index)
    if mutate:
        mutate(fields, audios, splits)
    with ZipFile(path, "w") as archive:
        for key, name in (("paths", "paths.txt"), ("text", "seq.in"), ("tags", "seq.out"), ("metadata", "metadata.txt")):
            archive.writestr(px.PX_PATH + name, "\n".join(fields[key]) + "\n")
        for name, indexes in splits.items():
            archive.writestr(px.PX_PATH + f"data_splits/{name}/{name}.txt", "\n".join(map(str, indexes)) + "\n")
        for name, audio in audios.items():
            archive.writestr(px.PX_PATH + "recordings/" + name, audio)
    return fields


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "public-fixture.zip"
        self.source = make_archive(self.archive)
        self.lock = patch.object(px, "PX_SHA256", px.sha256(self.archive))
        self.lock.start()
        self.addCleanup(self.lock.stop)
        for name in ("BENCHMARK_ROWS", "PRIOR_ROWS"):
            context = patch.object(px, name, frozenset({0}))
            context.start()
            self.addCleanup(context.stop)

    def exported(self):
        result = self.root / "out"
        px.export(self.archive, result)
        return result

    def rows(self, root, partition):
        return [json.loads(line) for line in (root / f"{partition}.jsonl").read_text().splitlines()]

    def rewrite_manifest(self, root, partition, rows):
        target = root / f"{partition}.jsonl"
        target.write_text("".join(json.dumps(row) + "\n" for row in rows))
        report = json.loads((root / "report.json").read_text())
        report["artifacts_sha256"][target.name] = px.sha256(target)
        px.write_json(root / "report.json", report)

    def update_hash(self, root, name):
        report = json.loads((root / "report.json").read_text())
        report["artifacts_sha256"][name] = px.sha256(root / name)
        px.write_json(root / "report.json", report)

    def test_export_preserves_source_and_protects_speakers(self):
        root = self.exported()
        report = json.loads((root / "report.json").read_text())
        self.assertFalse(report["training_performed"])
        self.assertEqual(report["source_train_dev_shared_speakers"], 6)
        train, validation = self.rows(root, "train"), self.rows(root, "validation")
        self.assertFalse({r["speaker_id"] for r in train} & {r["speaker_id"] for r in validation})
        self.assertNotIn("px-99", {r["speaker_id"] for r in train + validation})
        self.assertEqual(len(train) + len(validation), 12)
        for row in train + validation:
            self.assertEqual(row["text"], self.source["text"][row["source_row_index"]])
            self.assertEqual(px.read_pcm((root / row["audio_filepath"]).read_bytes()),
                             px.read_pcm(wav_bytes(row["source_row_index"] + 1)))
        self.assertEqual(px.verify_export(root, self.archive), report["partitions"])

    def test_deterministic_manifests_and_refuse_overwrite(self):
        first = self.exported()
        second = self.root / "again"
        px.export(self.archive, second)
        for name in ("train.jsonl", "validation.jsonl", "reserve.local.json", "report.json"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        with self.assertRaisesRegex(ValueError, "existe"):
            px.export(self.archive, first)

    def test_rejects_other_dataset_and_archive_mutation_before_export(self):
        self.archive.write_bytes(b"Corti / PARROT or an unverified source")
        output = self.root / "out"
        with self.assertRaisesRegex(ValueError, "empreinte"):
            px.export(self.archive, output)
        self.assertFalse(output.exists())

    def test_rejects_output_inside_repository(self):
        output = Path(px.__file__).resolve().parents[2] / "p0/private/unwanted-training-export"
        with self.assertRaisesRegex(ValueError, "hors du dépôt"):
            px.export(self.archive, output)
        self.assertFalse(output.exists())

    def test_detects_cross_partition_speaker_even_with_new_manifest_hash(self):
        root = self.exported()
        validation = self.rows(root, "validation")
        validation[0]["speaker_id"] = self.rows(root, "train")[0]["speaker_id"]
        self.rewrite_manifest(root, "validation", validation)
        with self.assertRaisesRegex(ValueError, "Fuite"):
            px.verify_export(root, self.archive)

    def test_detects_case_and_space_reference_leak(self):
        root = self.exported()
        validation = self.rows(root, "validation")
        validation[0]["text"] = "  " + self.rows(root, "train")[0]["text"].upper().replace(" ", "  ")
        self.rewrite_manifest(root, "validation", validation)
        with self.assertRaisesRegex(ValueError, "Fuite"):
            px.verify_export(root, self.archive)

    def test_detects_reserved_voice(self):
        root = self.exported()
        train = self.rows(root, "train")
        train[0]["speaker_id"] = "px-99"
        self.rewrite_manifest(root, "train", train)
        with self.assertRaisesRegex(ValueError, "Fuite"):
            px.verify_export(root, self.archive)

    def test_detects_renamed_duplicate_audio(self):
        root = self.exported()
        validation, train = self.rows(root, "validation"), self.rows(root, "train")
        audio = (root / train[0]["audio_filepath"]).read_bytes()
        (root / validation[0]["audio_filepath"]).write_bytes(audio)
        validation[0]["audio_sha256"] = hashlib.sha256(audio).hexdigest()
        validation[0]["pcm_sha256"] = hashlib.sha256(px.read_pcm(audio)).hexdigest()
        self.rewrite_manifest(root, "validation", validation)
        with self.assertRaisesRegex(ValueError, "Fuite"):
            px.verify_export(root, self.archive)

    def test_detects_audio_mutation(self):
        root = self.exported()
        train = self.rows(root, "train")
        (root / train[0]["audio_filepath"]).write_bytes(wav_bytes(99))
        with self.assertRaisesRegex(ValueError, "Empreinte"):
            px.verify_export(root, self.archive)

    def test_rejects_path_escape_and_foreign_source(self):
        root = self.exported()
        train = self.rows(root, "train")
        train[0]["audio_filepath"] = "../outside.wav"
        self.rewrite_manifest(root, "train", train)
        with self.assertRaisesRegex(ValueError, "Chemin"):
            px.verify_export(root, self.archive)
        report = json.loads((root / "report.json").read_text())
        for dataset in ("corti", "parrot"):
            with self.subTest(dataset=dataset):
                report["dataset"] = dataset
                px.write_json(root / "report.json", report)
                with self.assertRaisesRegex(ValueError, "Source non autorisée"):
                    px.verify_export(root, self.archive)

    def test_shared_texts_and_pcm_are_removed_from_both_partitions(self):
        base = self.exported()
        left = self.rows(base, "train")[0]["source_row_index"]
        right = self.rows(base, "validation")[0]["source_row_index"]
        def mutate(fields, audios, splits):
            fields["text"][left] = fields["text"][right]
            fields["tags"][left] = fields["tags"][right]
            audios[fields["paths"][left + 1]] = audios[fields["paths"][right + 1]]
        make_archive(self.archive, mutate)
        with patch.object(px, "PX_SHA256", px.sha256(self.archive)):
            output = self.root / "filtered"
            report = px.export(self.archive, output)
            self.assertEqual(report["excluded_by_reason"]["reference_crosses_partitions"], 2)
            self.assertEqual(report["excluded_by_reason"]["pcm_crosses_partitions"], 2)
            self.assertEqual(sum(p["rows"] for p in report["partitions"].values()), 8)
            px.verify_export(output, self.archive)

    def test_candidates_matching_the_reserve_are_removed(self):
        def mutate(fields, audios, splits):
            fields["text"][1] = fields["text"][0]
            fields["tags"][1] = fields["tags"][0]
            audios[fields["paths"][2]] = audios[fields["paths"][0]]
        make_archive(self.archive, mutate)
        with patch.object(px, "PX_SHA256", px.sha256(self.archive)):
            root = self.root / "filtered"
            report = px.export(self.archive, root)
            self.assertEqual(report["excluded_by_reason"]["reference_matches_reserve"], 1)
            self.assertEqual(report["excluded_by_reason"]["pcm_matches_reserve"], 1)
            remaining = self.rows(root, "train") + self.rows(root, "validation")
            self.assertTrue({"px-0", "px-1", "px-2"}.isdisjoint({r["id"] for r in remaining}))

    def test_long_audio_is_excluded_whole_and_truncation_rejected(self):
        def mutate(fields, audios, splits):
            audios[fields["paths"][1]] = wav_bytes(42, frames=31 * 16000)
        make_archive(self.archive, mutate)
        with patch.object(px, "PX_SHA256", px.sha256(self.archive)):
            root = self.root / "long-filtered"
            report = px.export(self.archive, root)
            self.assertEqual(report["excluded_by_reason"]["longer_than_30_seconds"], 1)
            self.assertFalse((root / "wav/px-1.wav").exists())
        with self.assertRaisesRegex(ValueError, "tronqué"):
            px.read_pcm(wav_bytes(1)[:-10])

    def test_missing_locked_benchmark_row_aborts_without_output(self):
        with patch.object(px, "BENCHMARK_ROWS", frozenset({999})):
            with self.assertRaisesRegex(ValueError, "benchmark verrouillé"):
                px.export(self.archive, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_source_comparison_rejects_relabelled_rows_even_if_rehashed(self):
        root = self.exported()
        original = self.rows(root, "train")
        for field, value in (("source_row_index", 0), ("speaker_id", "px-999"),
                             ("text", "Une référence de remplacement absente de la source")):
            with self.subTest(field=field):
                modified = [dict(row) for row in original]
                modified[0][field] = value
                self.rewrite_manifest(root, "train", modified)
                with self.assertRaisesRegex(ValueError, "Entrée différente"):
                    px.verify_export(root, self.archive)

    def test_recomputed_reserve_and_attribution_hashes_do_not_authenticate_them(self):
        root = self.exported()
        reserve = (root / "reserve.local.json").read_bytes()
        px.write_json(root / "reserve.local.json", {"speakers": [], "reference_keys": [], "pcm_sha256": [], "excluded_rows": []})
        self.update_hash(root, "reserve.local.json")
        with self.assertRaisesRegex(ValueError, "Réserve différente"):
            px.verify_export(root, self.archive)
        (root / "reserve.local.json").write_bytes(reserve)
        self.update_hash(root, "reserve.local.json")
        (root / "ATTRIBUTION.txt").write_text("Incorrect attribution")
        self.update_hash(root, "ATTRIBUTION.txt")
        with self.assertRaisesRegex(ValueError, "Attribution différente"):
            px.verify_export(root, self.archive)

    def test_source_row_omission_is_rejected(self):
        root = self.exported()
        self.rewrite_manifest(root, "train", self.rows(root, "train")[1:])
        with self.assertRaisesRegex(ValueError, "Partition source incomplète"):
            px.verify_export(root, self.archive)

    @unittest.skipIf(os.name == "nt", "La création de symlinks Windows exige un privilège distinct")
    def test_rejects_linked_metadata_and_wav_parent(self):
        root = self.exported()
        for name in ("report.json", "train.jsonl", "validation.jsonl", "reserve.local.json", "ATTRIBUTION.txt", "wav"):
            with self.subTest(name=name):
                target = self.root / ("external-" + name)
                (root / name).rename(target)
                (root / name).symlink_to(target, target_is_directory=target.is_dir())
                try:
                    with self.assertRaisesRegex(ValueError, "liens"):
                        px.verify_export(root, self.archive)
                finally:
                    (root / name).unlink()
                    target.rename(root / name)
        link = self.root / "linked-root"
        link.symlink_to(root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "racine"):
            px.verify_export(link, self.archive)

    @unittest.skipIf(os.name == "nt", "Windows peut interdire de renommer un fichier ouvert")
    def test_archive_is_hashed_and_parsed_through_the_same_handle(self):
        original_digest = hashlib.file_digest
        def swap_after_hash(stream, algorithm):
            result = original_digest(stream, algorithm)
            self.archive.rename(self.root / "original.zip")
            self.archive.write_bytes(b"Untrusted replacement")
            return result
        with patch.object(px.hashlib, "file_digest", side_effect=swap_after_hash):
            with px.locked_archive(self.archive) as archive:
                rows, _ = px.load_archive(archive)
                self.assertEqual(len(rows), 13)

    def test_invalid_source_metadata_and_audio_are_rejected(self):
        mutations = {
            "labels": lambda f, a, s: f["tags"].__setitem__(1, "O"),
            "speaker": lambda f, a, s: f["metadata"].__setitem__(1, ",18,F,expert"),
            "path": lambda f, a, s: f["paths"].__setitem__(1, "../outside.wav"),
            "split": lambda f, a, s: s["train"].append(0),
            "rate": lambda f, a, s: a.__setitem__(f["paths"][1], wav_bytes(1, 44100)),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                make_archive(self.archive, mutate)
                with ZipFile(self.archive) as archive, self.assertRaises(ValueError):
                    px.load_archive(archive)

    def test_text_key_preserves_critical_differences(self):
        for left, right in (("7,5 mg", "75 mg"), ("1/2 comprimé", "2 comprimés"),
                            ("pas de douleur", "douleur"), ("0,3 mL", "0,3 mg")):
            with self.subTest(left=left):
                self.assertNotEqual(px.text_key(left), px.text_key(right))

    def test_short_invalid_wav_has_a_controlled_error(self):
        for raw in (b"", b"RIFF", b"RIFF\xff\x00"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "invalide ou tronqué"):
                px.read_pcm(raw)


if __name__ == "__main__":
    unittest.main()
