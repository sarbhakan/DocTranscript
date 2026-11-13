"""Build a locally signed NoteVive .app for Apple Silicon from pinned inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tarfile
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = HERE.parent
LOCK = json.loads((APP / "inputs.lock.json").read_text(encoding="utf-8"))
RUNTIME_FOLDER = "sherpa-onnx-v2.0.1-osx-arm64-shared-no-tts"
RUNTIME_HASH = "4fcc6c77c8d8d2e2f04cfdc17c6fd224c01469b78529370eb9d8e0e5ec97ac79"
MODEL_NAMES = ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt")
NOTICE_NAMES = ("ONNX-LICENSE", "ONNX-ThirdPartyNotices.txt")
LIB_NAMES = ("libsherpa-onnx-c-api.dylib", "libonnxruntime.dylib")


def run(*args):
    subprocess.run(args, check=True, cwd=ROOT)


def digest(path, algorithm="sha256"):
    with path.open("rb") as file:
        return hashlib.file_digest(file, algorithm).hexdigest()


def check(path, spec):
    if digest(path, spec.get("algorithm", "sha256")) != spec["hash"]:
        raise ValueError(f"Empreinte différente de la référence : {path}")


def make_icon(build, resources):
    logo = ROOT / "assets/notevive.png"
    blocks = bytearray()
    for kind, width in ((b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256)):
        size = str(width)
        scaled = build / f"icon-{width}.png"
        subprocess.run(
            ["/usr/bin/sips", "-z", size, size, logo, "--out", scaled],
            check=True, stdout=subprocess.DEVNULL,
        )
        png = scaled.read_bytes()
        blocks.extend(kind + struct.pack(">I", len(png) + 8) + png)
    (resources / "NoteVive.icns").write_bytes(b"icns" + struct.pack(">I", len(blocks) + 8) + blocks)
    shutil.copyfile(logo, resources / "Logo.png")


def stage(bundle, downloads, runtime, build):
    for name in (*MODEL_NAMES, *NOTICE_NAMES):
        check(downloads / name, LOCK["downloads"][name])
    for name, spec in LOCK["headers"].items():
        check(APP / "windows" / name, spec)
    check(runtime, {"hash": RUNTIME_HASH})

    contents = bundle / "Contents"
    frameworks = contents / "Frameworks"
    model = contents / "Resources/Model"
    notices = contents / "Resources/Licences"
    for p in (frameworks, model, notices, contents / "MacOS"):
        p.mkdir(parents=True, exist_ok=True)
    with tarfile.open(runtime, "r:bz2") as source:
        for name in LIB_NAMES:
            item = source.getmember(f"{RUNTIME_FOLDER}/lib/{name}")
            if not item.isfile():
                raise ValueError(f"Bibliothèque attendue : {name}")
            with source.extractfile(item) as library, (frameworks / name).open("wb") as target:
                shutil.copyfileobj(library, target)
            run("/usr/bin/lipo", "-verify_arch", "arm64", frameworks / name)
    for name in MODEL_NAMES:
        shutil.copyfile(downloads / name, model / name)
    (model / "SHA256.json").write_text(
        json.dumps({name: LOCK["downloads"][name]["hash"] for name in MODEL_NAMES},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name in NOTICE_NAMES:
        shutil.copyfile(downloads / name, notices / name)
    shutil.copyfile(APP / "windows/vendor/sherpa-onnx/LICENSE", notices / "Apache-2.0.txt")
    shutil.copytree(APP / "licences/sherpa", notices / "Sherpa-et-dependances", copy_function=shutil.copyfile)
    shutil.copyfile(HERE / "NOTICE.md", notices / "Composants.md")
    shutil.copyfile(HERE / "Info.plist", contents / "Info.plist")
    run("/usr/bin/plutil", "-lint", contents / "Info.plist", HERE / "NoteVive.entitlements")
    make_icon(build, contents / "Resources")
    return contents


def build_macos(bundle, downloads, runtime, work):
    contents = stage(bundle, downloads, runtime, work)
    executable = contents / "MacOS/NoteVive"
    frameworks = contents / "Frameworks"
    run(
        "/usr/bin/xcrun", "swiftc", "-O", "-swift-version", "6", "-target", "arm64-apple-macosx15.0",
        "-module-cache-path", work / "swift-cache", "-import-objc-header", HERE / "SherpaBridge.h",
        "-L", frameworks, "-lsherpa-onnx-c-api", "-Xlinker", "-rpath",
        "-Xlinker", "@executable_path/../Frameworks",
        *(HERE / name for name in ("Recognition.swift", "Dictation.swift", "AudioRegression.swift",
                                   "Library.swift", "LibraryView.swift", "main.swift")),
        "-o", executable,
    )
    # File-provider metadata from the development folder must not enter the bundle.
    run("/usr/bin/xattr", "-cr", bundle)
    for name in LIB_NAMES:
        run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", frameworks / name)
    run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", "--entitlements",
        HERE / "NoteVive.entitlements", bundle)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", bundle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, default=APP / "private/downloads")
    parser.add_argument("--runtime", type=Path, default=APP / "private/downloads/sherpa-macos-smoke.tar.bz2")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/NoteVive-Mac.app")
    parser.add_argument("--zip", action="store_true", help="Ajoute une archive transportable et son empreinte")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Compilation prévue sur macOS Apple Silicon")
    output = args.output.resolve()
    archive = output.with_suffix(".zip")
    checksum = archive.with_suffix(".zip.sha256")
    if output.suffix != ".app" or output.exists() or (args.zip and (archive.exists() or checksum.exists())):
        parser.error("La sortie doit être un nouveau fichier .app (et ses éventuels ZIP/SHA-256)")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Build and sign outside File Provider roots. On a synced folder macOS may
    # attach Finder information while signing, invalidating the resource seal.
    with tempfile.TemporaryDirectory(prefix="notevive-build-", dir="/private/tmp") as directory:
        work = Path(directory)
        bundle = work / output.name
        build_macos(bundle, args.downloads.resolve(), args.runtime.resolve(), work)
        if args.zip:
            temporary_archive = work / archive.name
            # Write only the signed bundle's file bytes and POSIX permissions.
            # This leaves Finder metadata and AppleDouble entries out of the ZIP.
            with zipfile.ZipFile(temporary_archive, "x", zipfile.ZIP_DEFLATED, compresslevel=5) as packed:
                for path in sorted(bundle.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Lien inattendu dans l’application : {path.name}")
                    if path.is_file():
                        packed.write(path, path.relative_to(work))
            round_trip = work / "archive-check"
            run("/usr/bin/ditto", "-x", "-k", temporary_archive, round_trip)
            run("/usr/bin/codesign", "--verify", "--deep", "--strict", round_trip / bundle.name)
            checksum.write_text(f"{digest(temporary_archive)}  {archive.name}\n", encoding="ascii")
            shutil.move(temporary_archive, archive)
        shutil.move(bundle, output)
    print(output)
    if args.zip:
        print(archive)


if __name__ == "__main__":
    main()
