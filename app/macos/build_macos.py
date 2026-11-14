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
LOCK = json.loads((ROOT / "p0/packs/ultimed-int8.lock.json").read_text(encoding="utf-8"))
RUNTIME_FOLDER = "onnxruntime-osx-arm64-1.32.0"
RUNTIME_HASH = "8ddca23f532b9d4fbb279ba9b08dab6c0ac94fdc9aec2eb44a1db7049216c043"
RUNTIME_LIB = "libonnxruntime.1.32.0.dylib"
BUNDLE_LIB = "libonnxruntime.1.dylib"  # The LC_ID_DYLIB in the upstream binary.
MODEL_FILES = {
    **LOCK["files"],
    **LOCK["optional_speech_gate"]["files"],
    "nemo128.onnx": {
        "bytes": 139764,
        "sha256": "a9fde1486ebfcc08f328d75ad4610c67835fea58c73ba57e3209a6f6cf019e9f",
    },
}
NOTICE_HASHES = {
    "CC-BY-4.0.txt": "9ba9550ad48438d0836ddab3da480b3b69ffa0aac7b7878b5a0039e7ab429411",
    "UltiMed-README.md": "ad9acfc23f80865a054eea247dbb8b6839d346ccf7e49f273762d5ea718bf488",
    "Silero-LICENSE.txt": "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b",
    "Silero-README.md": "39c6c9b7dce6ac255dcaf269a113af426946fd6290fe1ad4a92ffbbde1781b95",
}
SWIFT_TARGET = "arm64-apple-macosx15.0"


def run(*args):
    subprocess.run(args, check=True, cwd=ROOT)


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def check(path, sha256, size=None):
    if not path.is_file():
        raise FileNotFoundError(f"Fichier requis : {path}")
    if (size is not None and path.stat().st_size != size) or digest(path) != sha256:
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


def extract_file(archive, item, destination):
    if not item.isfile():
        raise ValueError(f"Fichier régulier attendu dans ONNX Runtime : {item.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.extractfile(item) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)


def stage(bundle, assets, build, lexicon):
    model_source = assets / "model"
    notices_source = assets / "notices"
    runtime = assets / f"{RUNTIME_FOLDER}.tgz"
    for name, spec in MODEL_FILES.items():
        check(model_source / name, spec["sha256"], spec["bytes"])
    for name, sha256 in NOTICE_HASHES.items():
        check(notices_source / name, sha256)
    check(runtime, RUNTIME_HASH)

    contents = bundle / "Contents"
    frameworks = contents / "Frameworks"
    model = contents / "Resources/Model"
    notices = contents / "Resources/Licences"
    for p in (frameworks, model, notices, contents / "MacOS"):
        p.mkdir(parents=True, exist_ok=True)
    library = frameworks / BUNDLE_LIB
    with tarfile.open(runtime, "r:gz") as source:
        # Iterate once: seeking independently to each member re-decompresses the archive.
        mappings = {
            f"{RUNTIME_FOLDER}/lib/{RUNTIME_LIB}": library,
            f"{RUNTIME_FOLDER}/LICENSE": notices / "ONNX-Runtime-LICENSE.txt",
            f"{RUNTIME_FOLDER}/ThirdPartyNotices.txt": notices / "ONNX-Runtime-ThirdPartyNotices.txt",
        }
        prefix = f"{RUNTIME_FOLDER}/include/"
        for item in source:
            if item.name in mappings:
                extract_file(source, item, mappings.pop(item.name))
            elif item.name.startswith(prefix) and not item.isdir():
                relative = Path(item.name[len(prefix):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Chemin invalide dans ONNX Runtime : {item.name}")
                extract_file(source, item, build / "include" / relative)
        if mappings:
            raise ValueError(f"Fichiers manquants dans ONNX Runtime : {', '.join(mappings)}")
    library.chmod(0o755)
    run("/usr/bin/lipo", "-verify_arch", "arm64", library)
    for name in MODEL_FILES:
        shutil.copyfile(model_source / name, model / name)
    (model / "SHA256.json").write_text(
        json.dumps({name: spec["sha256"] for name, spec in MODEL_FILES.items()},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name in NOTICE_HASHES:
        shutil.copyfile(notices_source / name, notices / name)
    if lexicon is not None:
        lexicon_dir = contents / "Resources/Lexique"
        lexicon_dir.mkdir()
        profiles = lexicon / "profiles.json"
        attribution = lexicon / "SOURCES.md"
        if profiles.stat().st_size > 16 * 1024 * 1024 or attribution.stat().st_size > 256 * 1024:
            raise ValueError("Le paquet de lexique dépasse la taille admise")
        shutil.copyfile(profiles, lexicon_dir / profiles.name)
        shutil.copyfile(attribution, notices / "Lexique-SOURCES.md")
    shutil.copyfile(HERE / "NOTICE.md", notices / "Composants.md")
    shutil.copyfile(HERE / "Info.plist", contents / "Info.plist")
    run("/usr/bin/plutil", "-lint", contents / "Info.plist", HERE / "NoteVive.entitlements")
    make_icon(build, contents / "Resources")
    return contents


def build_macos(bundle, assets, work, lexicon):
    contents = stage(bundle, assets, work, lexicon)
    executable = contents / "MacOS/NoteVive"
    library = contents / "Frameworks" / BUNDLE_LIB
    objects = []
    for source in sorted((HERE / "native").glob("*.cpp")):
        obj = work / f"{source.stem}.o"
        run(
            "/usr/bin/xcrun", "clang++", "-std=c++17", "-O2", "-Wall", "-Wextra",
            "-target", SWIFT_TARGET, "-I", work / "include", "-c", source, "-o", obj,
        )
        objects.append(obj)
    run(
        "/usr/bin/xcrun", "swiftc", "-O", "-swift-version", "6", "-target", SWIFT_TARGET,
        "-module-cache-path", work / "swift-cache", "-import-objc-header", HERE / "RecognitionBridge.h",
        *objects, library, "-lc++", "-Xlinker", "-rpath",
        "-Xlinker", "@executable_path/../Frameworks",
        *(HERE / name for name in ("Recognition.swift", "Dictation.swift", "AudioRegression.swift",
                                   "Library.swift", "LibraryView.swift", "MedicalLexicon.swift", "main.swift")),
        "-o", executable,
    )
    # File-provider metadata from the development folder must not enter the bundle.
    run("/usr/bin/xattr", "-cr", bundle)
    run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", library)
    run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", "--entitlements",
        HERE / "NoteVive.entitlements", bundle)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", bundle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=APP / "private/ultimed-macos",
                        help="Répertoire contenant les modèles, les notices et l’archive ONNX Runtime")
    parser.add_argument("--lexicon", type=Path,
                        help="Répertoire avec le lexique local profiles.json et sa notice SOURCES.md")
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
        build_macos(bundle, args.assets.resolve(), work, args.lexicon.resolve() if args.lexicon else None)
        if args.zip:
            temporary_archive = work / archive.name
            # Write only the signed bundle's file bytes and POSIX permissions.
            # This leaves Finder metadata and AppleDouble entries out of the ZIP.
            with zipfile.ZipFile(temporary_archive, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as packed:
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
