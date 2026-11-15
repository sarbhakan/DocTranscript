"""Offline candidate export: exact FP32 LoRA merge, HF FP16, upstream GGML Q5_0.

No download, training, ASR evaluation or automatic product integration occurs.
Run conversion for the untouched base as well, before attributing any change to LoRA.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

from p0.training.fetch_model import LOCK_PATH, validate_file, verify_model
from p0.training.prepare_px import safe_artifact, sha256
from p0.training.train_lora import (
    TARGETS, atomic_json, json_digest, load_existing_adapter, load_runtime,
    output_path, prepare, private_directory, validate_architecture, verify_adapter,
)


CONVERTER_SHA256 = "9cc282dfcd9a24da03ffa1b4123b5508ee935e19e369c33520b1a73f89440094"
CONVERTER_URL = "https://github.com/ggml-org/whisper.cpp/blob/v1.8.5/models/convert-h5-to-ggml.py"
MEL_SHA256 = "7450ae70723a5ef9d341e3cee628c7cb0177f36ce42c44b7ed2bf3325f0f6d4c"
MEL_URL = "https://github.com/openai/whisper/blob/v20250625/whisper/assets/mel_filters.npz"
TARGET_WEIGHTS = {name + ".weight" for name in TARGETS}


def locked_file(path: Path, expected: str) -> Path:
    if path.is_symlink() or not path.is_file() or sha256(path) != expected:
        raise ValueError("Fichier d’export absent, lié ou différent de l’empreinte verrouillée")
    return path.resolve(strict=True)


def parameter_fingerprints(model, torch) -> dict[str, str]:
    """Fingerprint one tensor at a time in the actual target dtype, without a second model."""
    result = {}
    for name, value in model.named_parameters():
        tensor = value.detach().to(device="cpu", dtype=torch.float16).contiguous()
        if not bool(torch.isfinite(tensor).all().item()):
            raise ValueError("Poids non fini lors de l’export FP16")
        signature = hashlib.sha256(json.dumps([name, list(tensor.shape), "float16"]).encode())
        signature.update(tensor.numpy().tobytes())
        result[name] = signature.hexdigest()
        del tensor
    return result


def changed_weights(before: dict, after: dict, adapted: bool) -> list[str]:
    if before.keys() != after.keys():
        raise ValueError("L’architecture ou les noms de poids ont changé pendant la fusion")
    changed = sorted(name for name in before if before[name] != after[name])
    if set(changed) - TARGET_WEIGHTS:
        raise ValueError("La fusion a modifié un poids hors des projections LoRA autorisées")
    if adapted != bool(changed):
        raise ValueError("Fusion sans effet FP16 mesurable, ou base témoin modifiée")
    return changed


def copy_source_metadata(source: Path, destination: Path, provenance: dict) -> dict:
    preserved = {}
    for name, digest in provenance["sha256"].items():
        if name == "model.safetensors":
            continue
        source_file = safe_artifact(source, name)
        shutil.copyfile(source_file, destination / name)
        if sha256(destination / name) != digest:
            raise ValueError("Tokenizer/configuration d’origine non préservé octet pour octet")
        preserved[name] = digest
    config = json.loads((destination / "config.json").read_text(encoding="utf-8"))
    validate_architecture(config)
    if config.get("max_length") not in (None, 448):
        raise ValueError("Contexte texte incompatible avec le convertisseur whisper.cpp")
    return preserved


def merge(args):
    corpus, source, adapter, output, summary, provenance, partitions, manifests = prepare(args)
    metadata = verify_adapter(adapter, provenance, manifests) if adapter else None
    # Output needs one full FP16 model, plus the operator's reserved free space.
    required = (source / "model.safetensors").stat().st_size + int(args.min_free_gib * 1024 ** 3)
    output_path(output, [source, corpus] + ([adapter] if adapter else []), required)
    rt = load_runtime("cpu")
    torch = rt["torch"]
    torch.set_num_threads(args.threads)
    started = time.monotonic()
    output.mkdir(mode=0o700)
    try:
        base = rt["Whisper"].from_pretrained(str(source), local_files_only=True, use_safetensors=True,
                                           torch_dtype=torch.float32, attn_implementation="sdpa")
        base.eval()
        validate_architecture(base.config.to_dict())
        before = parameter_fingerprints(base, torch)
        if adapter:
            model = load_existing_adapter(rt, base, adapter)
            # Base and adapter are FP32 here: add the learned delta before the
            # single, final FP16 rounding used by the downstream converter.
            merged = model.merge_and_unload(safe_merge=True)
        else:
            merged = base
        merged = merged.to(dtype=torch.float16)
        after = parameter_fingerprints(merged, torch)
        changed = changed_weights(before, after, bool(adapter))
        with tempfile.TemporaryDirectory(prefix=".hf-", dir=output) as temporary:
            stage = Path(temporary) / "complete"
            merged.save_pretrained(str(stage), safe_serialization=True, max_shard_size="5GB")
            if not (stage / "model.safetensors").is_file():
                raise ValueError("Export attendu dans un seul fichier safetensors")
            preserved = copy_source_metadata(source, stage, provenance)
            expected = set(provenance["sha256"])
            if {item.name for item in stage.iterdir()} != expected:
                raise ValueError("Fichiers inattendus dans l’export HF")
            hashes = {path.name: sha256(path) for path in sorted(stage.iterdir())}
            stage.rename(output / "hf")
        if verify_model(source) != provenance:
            raise ValueError("Les fichiers des poids d’origine ont changé")
        result = {"schema": 1, "status": "completed", "kind": "lora_merged" if adapter else "base_control",
                  "base": provenance, "adapter_checkpoint": metadata, "manifest_sha256": manifests,
                  "merge_dtype": "float32", "export_dtype": "float16", "safe_merge": True,
                  "source_files_unchanged": True, "unchanged_parameters_verified": True,
                  "changed_weights": changed, "preserved_metadata_sha256": preserved,
                  "files_sha256": hashes, "hf_directory": "hf", "versions": rt["versions"],
                  "promoted_to_application": False, "native_conversion_tested": False,
                  "elapsed_seconds": time.monotonic() - started}
        atomic_json(output / "export.json", result)
        print(json.dumps({"status": result["status"], "changed_weights": len(changed),
                          "export_dtype": "float16", "model_sha256": hashes["model.safetensors"]}), flush=True)
        del merged, base
        gc.collect()
        return result
    except BaseException as error:
        atomic_json(output / "export.json", {"schema": 1, "status": "failed",
                    "error_type": type(error).__name__, "promoted_to_application": False})
        raise


def verify_hf_input(model: Path, export_report: Path | None) -> dict:
    if export_report is None:
        return {"kind": "original_base", "base": verify_model(model)}
    if export_report.is_symlink() or not export_report.is_file():
        raise ValueError("Rapport de fusion absent ou lié")
    report_path = export_report.resolve(strict=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (report.get("schema") != 1 or report.get("status") != "completed"
            or report.get("export_dtype") != "float16" or report.get("source_files_unchanged") is not True
            or report.get("unchanged_parameters_verified") is not True
            or report.get("hf_directory") != "hf" or model != report_path.parent / "hf"):
        raise ValueError("Rapport de fusion absent, incomplet ou incohérent")
    if {path.name for path in model.iterdir()} != set(report["files_sha256"]):
        raise ValueError("Fichiers non attestés dans l’export HF")
    for name, digest in report["files_sha256"].items():
        if sha256(safe_artifact(model, name)) != digest:
            raise ValueError("Export HF modifié depuis la fusion")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (report["base"].get("repo") != lock["repo"] or report["base"].get("revision") != lock["revision"]
            or set(report["files_sha256"]) != {item["path"] for item in lock["files"]}):
        raise ValueError("Base ou liste de fichiers différente de la révision verrouillée")
    for spec in lock["files"]:
        if spec["path"] != "model.safetensors":
            validate_file(model / spec["path"], spec)
    config = json.loads((model / "config.json").read_text(encoding="utf-8"))
    validate_architecture(config)
    if config.get("max_length") not in (None, 448):
        raise ValueError("Contexte texte d’export invalide")
    return {"kind": report["kind"], "merge_report_sha256": sha256(report_path),
            "base": report["base"], "hf_files_sha256": report["files_sha256"]}


def ggml_header(path: Path, expected_ftype: int) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(56)
    if len(raw) != 56:
        raise ValueError("Fichier GGML tronqué avant son en-tête")
    values = struct.unpack("<14i", raw)
    expected = (0x67676D6C, 51866, 1500, 1280, 20, 32, 448, 1280, 20, 4, 128, expected_ftype, 128, 201)
    if values != expected:
        raise ValueError("En-tête GGML incompatible avec Turbo, 128 mel, contexte 448 ou Q5_0")
    return {"vocabulary_size": values[1], "encoder_layers": values[5], "decoder_layers": values[9],
            "text_context": values[6], "mel_bands": values[10], "ftype": values[11]}


def quantize(args):
    model = private_directory(args.model)
    provenance = verify_hf_input(model, args.export_report)
    converter = locked_file(args.converter, CONVERTER_SHA256)
    mel = locked_file(args.mel_filters, MEL_SHA256)
    if len(args.quantizer_sha256) != 64 or any(char not in "0123456789abcdef" for char in args.quantizer_sha256):
        raise ValueError("Empreinte SHA-256 de l’exécutable quantizer requise")
    quantizer = locked_file(args.quantizer, args.quantizer_sha256)
    if not os.access(quantizer, os.X_OK):
        raise ValueError("Le quantizer local doit être exécutable")
    # FP16 GGML + Q5_0 coexist temporarily. Do not count just the final Q5 file.
    required = math.ceil((model / "model.safetensors").stat().st_size * 1.5) + int(args.min_free_gib * 1024 ** 3)
    output = output_path(args.output, [model], required)
    rt = load_runtime("cpu")  # Check pinned converter dependencies, no model loading here.
    started = time.monotonic()
    output.mkdir(mode=0o700)
    env = dict({key: value for key, value in os.environ.items()
                if key != "GGML_BACKEND_PATH" and not key.startswith(("DYLD_", "LD_"))},
               OMP_NUM_THREADS=str(args.threads), MKL_NUM_THREADS=str(args.threads),
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    try:
        with tempfile.TemporaryDirectory(prefix=".conversion-", dir=output) as temporary:
            stage = Path(temporary)
            script = stage / "convert-h5-to-ggml.py"
            shutil.copyfile(converter, script)
            mel_root = stage / "openai-whisper"
            asset = mel_root / "whisper" / "assets" / "mel_filters.npz"
            asset.parent.mkdir(parents=True)
            shutil.copyfile(mel, asset)
            locked_file(script, CONVERTER_SHA256)
            locked_file(asset, MEL_SHA256)
            commands = [[sys.executable, str(script), str(model), str(mel_root), str(stage)],
                        [str(quantizer), str(stage / "ggml-model.bin"), str(stage / "model-q5_0.bin"), "q5_0"]]
            with (output / "conversion.local.log").open("x", encoding="utf-8") as log:
                print("Conversion HF FP16 vers GGML via whisper.cpp 1.8.5…", flush=True)
                subprocess.run(commands[0], env=env, cwd=stage, stdout=log, stderr=subprocess.STDOUT, check=True)
                fp16_header = ggml_header(stage / "ggml-model.bin", 1)
                fp16_hash = sha256(stage / "ggml-model.bin")
                locked_file(quantizer, args.quantizer_sha256)
                print("Quantification Q5_0 locale…", flush=True)
                subprocess.run(commands[1], env=env, cwd=stage, stdout=log, stderr=subprocess.STDOUT, check=True)
            q5_header = ggml_header(stage / "model-q5_0.bin", 2008)
            quantized = stage / "model-q5_0.bin"
            if not 400 * 1024 ** 2 <= quantized.stat().st_size <= 800 * 1024 ** 2:
                raise ValueError("Taille de candidat Turbo Q5_0 anormale")
            q5_hash, q5_size = sha256(quantized), quantized.stat().st_size
            quantized.rename(output / "model-q5_0.bin")
            if args.keep_intermediate:
                (stage / "ggml-model.bin").rename(output / "ggml-fp16.bin")
        if verify_hf_input(model, args.export_report) != provenance:
            raise ValueError("L’entrée HF a changé pendant la conversion")
        result = {"schema": 1, "status": "completed", "input": provenance,
                  "converter": {"url": CONVERTER_URL, "sha256": CONVERTER_SHA256},
                  "mel_filters": {"url": MEL_URL, "sha256": MEL_SHA256},
                  "quantizer": {"sha256": args.quantizer_sha256,
                                "provenance": "operator-supplied local executable; its build must be recorded separately"},
                  "fp16_ggml_sha256": fp16_hash, "fp16_header": fp16_header,
                  "q5_0_sha256": q5_hash, "q5_0_bytes": q5_size, "q5_0_header": q5_header,
                  "fp16_intermediate_retained": args.keep_intermediate, "versions": rt["versions"],
                  "native_model_load_tested": False, "paired_asr_evaluation_completed": False,
                  "promoted_to_application": False, "elapsed_seconds": time.monotonic() - started}
        atomic_json(output / "export.json", result)
        print(json.dumps({"status": "completed", "q5_0_sha256": q5_hash, "q5_0_bytes": q5_size}), flush=True)
        return result
    except BaseException as error:
        atomic_json(output / "export.json", {"schema": 1, "status": "failed",
                    "error_type": type(error).__name__, "promoted_to_application": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    merge_cli = commands.add_parser("merge", help="Fusion CPU exacte, puis export HF FP16")
    merge_cli.add_argument("--model", type=Path, required=True)
    merge_cli.add_argument("--corpus", type=Path, required=True)
    merge_cli.add_argument("--px-archive", type=Path, required=True)
    merge_cli.add_argument("--adapter", type=Path, help="Absent = témoin de conversion sans adaptation")
    quant_cli = commands.add_parser("quantize", help="Conversion upstream puis quantification Q5_0")
    quant_cli.add_argument("--model", type=Path, required=True, help="Base vérifiée ou dossier hf issu de merge")
    quant_cli.add_argument("--export-report", type=Path, help="export.json de merge, requis pour un modèle adapté")
    quant_cli.add_argument("--converter", type=Path, required=True)
    quant_cli.add_argument("--mel-filters", type=Path, required=True)
    quant_cli.add_argument("--quantizer", type=Path, required=True)
    quant_cli.add_argument("--quantizer-sha256", required=True)
    quant_cli.add_argument("--keep-intermediate", action="store_true")
    for command in (merge_cli, quant_cli):
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--min-free-gib", type=float, default=2)
        command.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        if not math.isfinite(args.min_free_gib) or args.min_free_gib < 1 or not 1 <= args.threads <= 16:
            raise ValueError("Marge disque d’au moins 1 Gio et threads entre 1 et 16 requis")
        merge(args) if args.command == "merge" else quantize(args)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, ImportError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Export refusé ou interrompu : {error}\n")


if __name__ == "__main__":
    main()
