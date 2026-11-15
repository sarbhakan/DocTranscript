#!/usr/bin/env python3
"""Build the unmodified whisper.cpp 1.8.5 quantizer for local Apple Silicon export."""

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

SOURCE_SHA256 = "cd702189cb5e608c8bc487f4b151db593c4455925b37cc06ef76b44861911db1"
WHEEL_SHA256 = "d929d69b9c9b960114eee2d7ee4a5ec4a3553bcace173c155d951f94f5c835c8"
SOURCE_ROOT = "whisper.cpp-1.8.5"
WHEEL_NAME = "pywhispercpp-1.5.1-cp312-cp312-macosx_11_0_arm64.whl"
SOURCE_FILES = (
    "LICENSE",
    "examples/quantize/quantize.cpp",
    "examples/common.h",
    "examples/common-ggml.cpp",
    "examples/common-ggml.h",
    "ggml/include/ggml.h",
    "ggml/include/ggml-backend.h",
    "ggml/include/ggml-alloc.h",
)
LIBS = tuple(f"libggml{suffix}.0.13.1.dylib" for suffix in ("", "-base", "-cpu", "-blas", "-metal"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def locked(file, expected):
    # Retain the exact byte sequence verified, instead of reopening the path
    # after verification for archive reads. Both input archives are small.
    data = file.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"Empreinte SHA-256 inattendue : {file}")
    return data


def command_env():
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("DYLD_", "LD_")) and key != "GGML_BACKEND_PATH"}


def build(source, wheel, output):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Compilation prévue sur macOS Apple Silicon natif.")
    if output.exists() or output.is_symlink():
        raise ValueError("Choisir un dossier de sortie neuf.")
    output = output.resolve()
    if not output.parent.is_dir():
        raise ValueError("Le parent du dossier de sortie doit déjà exister.")
    source, wheel = source.resolve(strict=True), wheel.resolve(strict=True)
    git_source_url = "https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v1.8.5.tar.gz"
    wheel_url = "https://pypi.org/project/pywhispercpp/1.5.1/#files"
    src_bytes, wheel_bytes = locked(source, SOURCE_SHA256), locked(wheel, WHEEL_SHA256)
    env = command_env()
    with tempfile.TemporaryDirectory(prefix=".quantizer-", dir=output.parent) as temporary:
        stage = Path(temporary) / "build"
        stage.mkdir(mode=0o700)
        lib = stage / "lib"
        lib.mkdir()
        src = stage / "sources"
        extracted = {}
        with tarfile.open(fileobj=io.BytesIO(src_bytes), mode="r:gz") as tar:
            # Copy regular files chosen by constant name instead of extracting
            # the archive's directory entries, permissions or links.
            for name in SOURCE_FILES:
                member = tar.getmember(f"{SOURCE_ROOT}/{name}")
                if not member.isfile():
                    raise ValueError(f"Source attendue comme fichier régulier : {name}")
                with tar.extractfile(member) as handle:
                    payload = handle.read()
                target = src / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                extracted[name] = digest(payload)
        libraries = {}
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
            for name in LIBS:
                payload = archive.read(f"pywhispercpp/.dylibs/{name}")
                (lib / name).write_bytes(payload)
                libraries[name] = digest(payload)
            (lib / "LICENSE.pywhispercpp").write_bytes(archive.read("pywhispercpp-1.5.1.dist-info/licenses/LICENSE"))

        commands = []

        def run(args, *, check=True):
            argv = [os.fspath(arg) for arg in args]
            commands.append(argv)
            return subprocess.run(argv, check=check, capture_output=True, text=True, env=env, cwd=stage, timeout=180)

        compiler = run(["/usr/bin/clang++", "--version"]).stdout.strip()
        sdk = run(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-version"]).stdout.strip()
        tool = stage / "whisper-quantize"
        run(["/usr/bin/clang++", "-arch", "arm64", "-std=c++17", "-O3", "-DNDEBUG",
             "-I", src / "examples", "-I", src / "ggml/include", src / "examples/quantize/quantize.cpp",
             src / "examples/common-ggml.cpp", lib / LIBS[0], lib / LIBS[1],
             "-Wl,-headerpad_max_install_names", "-o", tool])
        for name in LIBS[:2]:
            run(["/usr/bin/install_name_tool", "-change", f"/DLC/pywhispercpp/.dylibs/{name}",
                 f"@loader_path/lib/{name}", tool])
        run(["/usr/bin/codesign", "--force", "--sign", "-", tool])
        run(["/usr/bin/codesign", "--verify", "--strict", tool])
        deps = run(["/usr/bin/otool", "-L", tool]).stdout.splitlines()[1:]
        links = [line.strip().split(" (", 1)[0] for line in deps]
        if (not all(f"@loader_path/lib/{name}" in links for name in LIBS[:2]) or
                any(not name.startswith(("@loader_path/lib/", "/usr/lib/", "/System/Library/")) for name in links)):
            raise ValueError("Dépendances Mach-O du quantizer inattendues.")
        smoke = run([tool], check=False)
        if smoke.returncode != 1 or "model-f32.bin model-quant.bin type" not in smoke.stderr or "q5_0" not in smoke.stderr:
            raise ValueError(f"Le lancement d’usage du quantizer a échoué (code {smoke.returncode}).")
        for name in LIBS:
            if digest((lib / name).read_bytes()) != libraries[name]:
                raise ValueError(f"Bibliothèque GGML modifiée pendant la construction : {name}")

        result = {
            "schema": 1,
            "source": {"url": git_source_url, "sha256": SOURCE_SHA256, "selected_files": extracted},
            "ggml": {"abi": "0.13.1", "wheel": WHEEL_NAME, "url": wheel_url,
                     "wheel_sha256": WHEEL_SHA256, "libraries": libraries, "links": links},
            "compiler": compiler, "sdk": sdk, "commands": commands,
            "quantizer_sha256": digest(tool.read_bytes()),
            "verification": {"usage_exit": 1, "q5_0_listed": True, "model_processed": False},
        }
        (stage / "build.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Never overwrite an existing tool or attestation, even if an output
        # path appeared while the compiler was running.
        output.mkdir(mode=0o700)
        for child in stage.iterdir():
            child.rename(output / child.name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Official whisper.cpp v1.8.5 source archive")
    parser.add_argument("--wheel", required=True, type=Path, help=f"Local {WHEEL_NAME}; not installed")
    parser.add_argument("--output", required=True, type=Path, help="New local directory")
    args = parser.parse_args()
    try:
        report = build(args.source, args.wheel, args.output)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"Échec de la construction : {exc}\n{exc.stderr or ''}")
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Échec de la construction : {exc}\n")
    print(f"Quantizer : {args.output.resolve() / 'whisper-quantize'}")
    print(f"SHA-256 : {report['quantizer_sha256']}")


if __name__ == "__main__":
    main()
