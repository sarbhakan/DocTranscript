import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.build_whisper_windows import (validate_staged, VERSION, SOURCE_URL, SOURCE_SHA256,
                                     CMAKE_PATCH, GENERATOR, CONFIG, STATIC_CRT_PROJECTS,
                                     VARIANT_DLL, variant_options, TOOLSETS)
from app.whisper_patch import DECODER_PATCH, edit_decoder, patched_decoder
from p0.decoder_ab import selected_rows
from p0.decoder_report import read_run, paired_changes


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
            compiler = {"id": "Clang", "executable": "clang-cl.exe", "version": "20.1.3"}
            valid = {"schema": 5, "version": VERSION, "source_url": SOURCE_URL,
                     "source_sha256": SOURCE_SHA256, "patch": CMAKE_PATCH, "decoder_patch": DECODER_PATCH,
                     "generator": GENERATOR, "toolset": "clangcl", "cmake_toolset": TOOLSETS["clangcl"][0],
                     "compilers": {"C": compiler, "CXX": compiler}, "config": CONFIG,
                     "static_crt_projects": list(STATIC_CRT_PROJECTS), "artifacts": {},
                     "variants": {name: {"cmake_options": variant_options("clangcl", name),
                                         "dll": "bin/" + dll, "imports": ["kernel32.dll"],
                                         "native_load_checked": True} for name, dll in VARIANT_DLL.items()}}
            # PE import and file hash checks have their separate native build
            # coverage; isolate the new attestation requirement here.
            with patch("app.build_whisper_windows.artifact_spec", return_value={}), \
                    patch("app.build_whisper_windows.verify_runtime", return_value=["kernel32.dll"]):
                (path / "attestation.json").write_text(json.dumps(valid))
                self.assertEqual(valid, validate_staged(path))
                for change in ({"schema": 3}, {"decoder_patch": None},
                               {"decoder_patch": {**DECODER_PATCH, "after_sha256": "0" * 64}}):
                    (path / "attestation.json").write_text(json.dumps({**valid, **change}))
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

    def test_report_refuses_partial_duplicate_and_forced_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.ndjson"
            meta = {"meta": {"manifest": "locked", "repeat_control_only": False}}
            a = {"id": "a", "status": "ok", "text": "fictif"}
            b = {**a, "id": "b"}
            def write(rows):
                path.write_text("\n".join(json.dumps(row) for row in rows))
            write([meta, a, b])
            self.assertEqual({"a", "b"}, read_run(path, "locked", {"a", "b"})[1].keys())
            for bad in ([meta, a], [meta, a, a],
                        [{"meta": {"manifest": "locked", "repeat_control_only": True}}, a, b]):
                write(bad)
                with self.assertRaises(ValueError):
                    read_run(path, "locked", {"a", "b"})

    def test_equal_totals_do_not_hide_paired_critical_regression(self):
        def report(errors):
            return {"cohorts": {"p0": {"records": []}, "stress": {"records": [
                {"id": key, "critical_errors": {"dose": value}, "missing_terms": []}
                for key, value in errors.items()]}}}
        before = report({"a": ["dose A"], "b": []})
        after = report({"a": [], "b": ["dose B"]})
        self.assertEqual({"gained": 1, "lost": 1}, paired_changes(before, after)["critical"]["dose"])
        self.assertEqual({"gained": 2, "lost": 0}, paired_changes(
            report({"a": ["dose A", "dose A"]}), report({"a": []}))["critical"]["dose"])


if __name__ == "__main__":
    unittest.main()
