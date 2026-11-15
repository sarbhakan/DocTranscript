"""Build a Windows x64 offline evaluation bundle with pinned local inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import zipfile

if __package__:
    from .build_whisper_windows import validate_staged, DLL_NAMES, DECODER_PATCH
    from .catalogue_package import domain_header, validate as validate_catalogue
else:
    from build_whisper_windows import validate_staged, DLL_NAMES, DECODER_PATCH
    from catalogue_package import domain_header, validate as validate_catalogue


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "app/windows"
LOCK = json.loads((ROOT / "app/inputs.lock.json").read_text(encoding="utf-8"))
PUBLIC_CATALOGUE_MANIFEST = ROOT / "lexique/manifest-essai-041.json"
WHISPER_NOTICES = WIN / "vendor/whisper-notices"
BASE_FLAGS = ["-target", "x86_64-windows-gnu", "-O2", "-DUNICODE", "-D_UNICODE"]
VERSION = "0.4.1-essai"
CXX_FLAGS = [*BASE_FLAGS, "-std=c++17", "-Wall", "-Wextra",
             f'-DNOTEVIVE_RELEASE_LABEL=L"{VERSION.removesuffix("-essai")}"']


def digest(path, algo="sha256"):
    with path.open("rb") as file:
        return hashlib.file_digest(file, algo).hexdigest()


def check(path, spec):
    if not path.is_file() or digest(path, spec.get("algorithm", "sha256")) != spec["hash"]:
        raise ValueError(f"Fichier manquant ou empreinte inattendue : {path}")


def padding(n):
    return b"\0" * (-n % 4)


def resource(typ, name, data, flags=0x0030, language=0):
    # Binary .res record; GNU/LLVM linkers can consume this directly.
    return (struct.pack("<IIHHHHIHHII", len(data), 32, 0xffff, typ, 0xffff, name, 0, flags, language, 0, 0)
            + data + padding(len(data)))


def make_resources(path):
    manifest = (WIN / "notevive.manifest").read_bytes()
    icon = (ROOT / "assets/notevive.png").read_bytes()
    width, height = struct.unpack_from(">II", icon, 16)
    if icon[:8] != b"\x89PNG\r\n\x1a\n" or not (1 <= width <= 256 and 1 <= height <= 256):
        raise ValueError("PNG du logo invalide")
    group = struct.pack("<HHHBBBBHHIH", 0, 1, 1, width % 256, height % 256, 0, 0, 1, 32, len(icon), 1)
    path.write_bytes(resource(0, 0, b"", 0) + resource(24, 1, manifest)
                     + resource(3, 1, icon, 0x1010) + resource(14, 1, group, 0x1030))


def stage_inputs(downloads, staging, catalogue, whisper_runtime):
    whisper_attestation = validate_staged(whisper_runtime)
    for name, spec in LOCK["downloads"].items():
        check(downloads / name, spec)
    for name, spec in LOCK["headers"].items():
        check(WIN / name, spec)
    lex = check_public_catalogue(catalogue)

    work = staging / "work"
    package = staging / "NoteVive"
    runtime = package / "runtime"
    notices = package / "Licences"
    for p in (work, runtime, notices):
        p.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(downloads / "sqlite-amalgamation.zip") as sqlite_zip:
        for name in ("sqlite3.c", "sqlite3.h"):
            (work / name).write_bytes(sqlite_zip.read(f"sqlite-amalgamation-3540100/{name}"))
    for name in DLL_NAMES:
        (runtime / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(whisper_runtime / "bin" / name, runtime / name)
    for name in ("ggml-large-v3-turbo-q5_0.bin", "ggml-silero-v6.2.0.bin"):
        shutil.copyfile(downloads / name, runtime / name)
    shutil.copyfile(catalogue, runtime / "catalogue.sqlite")
    for name in ("Whisper-cpp-MIT.txt", "Whisper-OpenAI-MIT.txt", "Silero-VAD-MIT.txt", "Llamafile-MIT.txt"):
        notice = WHISPER_NOTICES / name
        if not notice.is_file() or not notice.stat().st_size:
            raise ValueError(f"Notice Whisper/Silero absente ou vide : {notice}")
        shutil.copyfile(notice, notices / notice.name)
    if (notices / "Whisper-cpp-MIT.txt").read_bytes() != (whisper_runtime / "LICENSE").read_bytes():
        raise ValueError("La notice Whisper ne correspond pas aux sources compilées.")
    if whisper_attestation.get('openblas'):
        notice = WHISPER_NOTICES / 'OpenBLAS-BSD.txt'
        if notice.read_bytes() != (whisper_runtime / 'LICENSE.OpenBLAS').read_bytes():
            raise ValueError('La notice OpenBLAS ne correspond pas aux sources compilées.')
        shutil.copyfile(notice, notices / notice.name)
    (notices / 'cxx-runtime').mkdir()
    for name, spec in LOCK['runtime_notices'].items():
        source = ROOT / 'app/licences/cxx-runtime' / name
        check(source, spec)
        shutil.copyfile(source, notices / 'cxx-runtime' / name)
    shutil.copyfile(ROOT / "app/NOTICE.md", notices / "Composants.md")
    for source in lex["sources"]:
        del source["file"]
    (notices / "Referentiels.json").write_text(json.dumps(lex, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / "lexique/orphanet-domains.lock.json", notices / "Domaines-Orphanet.json")
    shutil.copyfile(ROOT / "docs/lexique-041.md", notices / "Vocabulaire-041.md")
    shutil.copyfile(ROOT / "app/LIRE-AVANT-ESSAI.txt", package / "LIRE-AVANT-ESSAI.txt")
    return work, package


def check_public_catalogue(path):
    return validate_catalogue(path, PUBLIC_CATALOGUE_MANIFEST, LOCK["catalogue"])


def run(zig, args, cache):
    env = {**os.environ, "ZIG_GLOBAL_CACHE_DIR": str(cache / "global"), "ZIG_LOCAL_CACHE_DIR": str(cache / "local")}
    subprocess.run([str(zig), *map(str, args)], check=True, cwd=ROOT, env=env)


def compile_bundle(zig, work, package, cache, whisper_runtime, preview_exe=None):
    make_resources(work / "notevive.res")
    catalogue = package / "runtime/catalogue.sqlite"
    domain_labels = ROOT / "lexique/domain_labels.json"
    (work / "catalogue_domains.h").write_text(domain_header(domain_labels), encoding="utf-8")
    (work / "catalogue_integrity.h").write_text(
        f'#define NOTEVIVE_CATALOGUE_SIZE {catalogue.stat().st_size}\n'
        f'#define NOTEVIVE_CATALOGUE_SHA256 "{digest(catalogue)}"\n', encoding="ascii")
    (package / "Build").mkdir()
    (package / "Build/catalogue.json").write_text(json.dumps({
        **LOCK["catalogue"], "bytes": catalogue.stat().st_size, "sha256": digest(catalogue),
        "domain_labels_sha256": digest(domain_labels),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package / "Build/version.json").write_text(json.dumps({
        "product": "NoteVive", "version": VERSION,
        "source_commit": os.environ.get("GITHUB_SHA", "local-build"),
        "asr": "whisper.cpp-1.8.5", "model": "large-v3-turbo-q5_0",
        "decoder_upstream_fix": DECODER_PATCH["upstream_commit"],
        "vad": "silero-6.2.0-ggml", "pause_ms": 576, "asr_threads": 4,
        "cpu_required": "AVX2/FMA/F16C/BMI1/BMI2/LZCNT/SSE4.2/POPCNT with OS AVX state",
        "cpu_variants": ["avx2"], "diagnostic_only_variants": ["baseline"], "audio_queue_seconds": 30,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(whisper_runtime / "attestation.json", package / "Build/whisper.json")
    inputs = sorted(p for p in (package / "runtime").rglob('*') if p.is_file() and p.name != "catalogue.sqlite")
    runtime_header = 'constexpr Expected kEngine[] = {\n' + ''.join(
        f'    {{L"{path.relative_to(package / "runtime").as_posix()}", {path.stat().st_size}, "{digest(path)}"}},\n' for path in inputs) + '};\n'
    (work / "runtime_integrity.h").write_text(runtime_header, encoding="ascii")
    (package / "Build/runtime_integrity.h").write_text(runtime_header, encoding="ascii")
    child = package / "runtime/NoteVive-ASR.exe"
    run(zig, ["c++", *CXX_FLAGS, "-municode", "-DNOTEVIVE_WORKER_BUILD", "-I", work, "-s",
              "-I", whisper_runtime / "include", "-DWHISPER_SHARED",
              *(WIN / f for f in ("worker_main.cpp", "local_engine.cpp", "integrity.cpp")),
              ROOT / "app/native/WhisperBridge.cpp", whisper_runtime / "lib/whisper.lib",
              "-lwinmm", "-lbcrypt", "-o", child], cache)
    shutil.copyfile(child, package / "runtime/cpu-avx2/NoteVive-ASR.exe")
    (work / "worker_integrity.h").write_text(
        f'#define NOTEVIVE_WORKER_SIZE {child.stat().st_size}\n'
        f'#define NOTEVIVE_WORKER_SHA256 "{digest(child)}"\n', encoding="ascii")
    run(zig, ["cc", *BASE_FLAGS, "-DNDEBUG", "-DSQLITE_ENABLE_FTS5", "-DSQLITE_OMIT_LOAD_EXTENSION",
              "-DSQLITE_OMIT_DEPRECATED", "-c", work / "sqlite3.c", "-o", work / "sqlite3.obj"], cache)
    gui_args = ["c++", *CXX_FLAGS, "-municode", "-Wl,--subsystem,windows", "-I", work, "-s",
              *(WIN / f for f in ("main.cpp", "engine.cpp", "notes.cpp", "catalogue.cpp", "integrity.cpp",
                                  "ui_theme.cpp", "dictation_overlay.cpp", "external_target.cpp")),
              work / "sqlite3.obj", work / "notevive.res", "-luser32", "-lgdi32", "-lwtsapi32", "-lwinmm",
              "-lcrypt32", "-lole32", "-loleaut32", "-ladvapi32", "-lshell32", "-luuid", "-lbcrypt", "-lcomctl32"]
    run(zig, [*gui_args, "-o", package / "NoteVive.exe"], cache)
    check_windows_gui(package / "NoteVive.exe")
    if preview_exe:
        # Separate, non-shipping artifact for a fictional UI screenshot only.
        preview_exe = preview_exe.resolve()
        if preview_exe.exists() or preview_exe.is_relative_to(package.resolve()):
            raise ValueError("Le binaire de capture doit être neuf et hors du paquet distribué")
        preview_exe.parent.mkdir(parents=True, exist_ok=True)
        run(zig, [*gui_args, "-DNOTEVIVE_UI_CAPTURE_TEST", "-o", preview_exe], cache)
        check_windows_gui(preview_exe)


def check_windows_gui(path):
    binary = path.read_bytes()
    pe = struct.unpack_from("<I", binary, 0x3c)[0]
    if (binary[:2] != b"MZ" or binary[pe:pe + 4] != b"PE\0\0"
            or struct.unpack_from("<H", binary, pe + 4)[0] != 0x8664
            or struct.unpack_from("<H", binary, pe + 24)[0] != 0x20b
            or struct.unpack_from("<H", binary, pe + 24 + 68)[0] != 2
            or not struct.unpack_from("<I", binary, pe + 24 + 112 + 2 * 8)[0]):
        raise ValueError("L’EXE attendu doit être une application graphique x64 avec ses ressources Windows")


def publish(package, output):
    paths = sorted(p for p in package.rglob("*") if p.is_file())
    (package / "SHA256.txt").write_text("".join(f"{digest(p)}  {p.relative_to(package).as_posix()}\n" for p in paths),
                                        encoding="utf-8")
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for path in sorted(p for p in package.rglob("*") if p.is_file()):
            archive.write(path, Path(package.name) / path.relative_to(package))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Erreur de lecture de l’archive compilée")
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest(output)}  {output.name}\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, default=ROOT / "app/private/downloads")
    parser.add_argument("--whisper-runtime", type=Path, default=ROOT / "app/private/whisper-build")
    parser.add_argument("--catalogue", type=Path, default=ROOT / "lexique/private/catalogue-essai-041.sqlite")
    parser.add_argument("--build-cache", type=Path, default=ROOT / "app/private/build-cache")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/NoteVive-Windows-x64-Essai.zip")
    parser.add_argument("--preview-exe", type=Path, help="Binaire séparé de capture UI fictive, jamais ajouté au ZIP")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        parser.error(f"La sortie existe déjà : {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = args.build_cache.resolve()
    (cache / "global").mkdir(parents=True, exist_ok=True)
    (cache / "local").mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(args.zig.resolve()), "version"], text=True).strip() != LOCK["zig"]["version"]:
        parser.error("Version Zig différente de celle déclarée dans le verrou")
    with tempfile.TemporaryDirectory(prefix="notevive-", dir=cache) as tmp:
        work, package = stage_inputs(args.downloads.resolve(), Path(tmp), args.catalogue.resolve(), args.whisper_runtime.resolve())
        compile_bundle(args.zig.resolve(), work, package, cache, args.whisper_runtime.resolve(), args.preview_exe)
        publish(package, output)
    print(output)


if __name__ == "__main__":
    main()
