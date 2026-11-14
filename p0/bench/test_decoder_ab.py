import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.build_whisper_windows import validate_staged
from app.whisper_patch import DECODER_PATCH, edit_decoder, patched_decoder
from p0.decoder_ab import selected_rows


class DecoderPatchTests(unittest.TestCase):
    def test_wrong_source_is_not_modified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "whisper.cpp"
            original = b"not the locked upstream source\n"
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                edit_decoder(path)
            self.assertEqual(original, path.read_bytes())

    def test_patch_selects_full_decode_not_initialization(self):
        # An upstream file has several similarly named TAGS. Use a reduced
        # fixture to exercise selection and hash guards without vendoring it.
        marker = b"    // TAGS: WHISPER_DECODER_INIT\n"
        before = marker + b"    initialize();\n" + marker + b"    for (int j = 1; j < n_decoders; j++) {\n"
        expected = (marker + b"    initialize();\n    state->decoders[0].rng = std::mt19937(0);\n\n"
                    + marker + b"    for (int j = 1; j < n_decoders; j++) {\n")
        hashes = {"before_sha256": hashlib.sha256(before).hexdigest(),
                  "after_sha256": hashlib.sha256(expected).hexdigest()}
        with patch.dict(DECODER_PATCH, hashes):
            self.assertEqual(expected, patched_decoder(before))
            with self.assertRaises(ValueError):
                patched_decoder(expected)  # A second application must fail.
            with self.assertRaises(ValueError):
                patched_decoder(before + b"changed")

    def test_old_runtime_attestation_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "attestation.json").write_text(json.dumps({"schema": 4, "version": "1.8.5"}))
            with self.assertRaises(ValueError):
                validate_staged(path)

    def test_corti_cannot_select_an_adaptation(self):
        rows = [{"id": "dev-17", "cohorts": ["stress", "p0"]},
                {"id": "px-23", "cohorts": ["p0"]},
                {"id": "corti-2", "cohorts": ["corti", "stress"]}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            path.write_text(json.dumps(rows))
            self.assertEqual(["dev-17", "px-23"], [r["id"] for r in selected_rows(path, "development")])
            self.assertEqual(["dev-17"], [r["id"] for r in selected_rows(path, "stress")])
            path.write_text(json.dumps(rows + [rows[0]]))
            with self.assertRaises(ValueError):
                selected_rows(path, "development")


if __name__ == "__main__":
    unittest.main()
