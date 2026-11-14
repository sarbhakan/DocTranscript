"""Offline, paired decoder experiments. Raw outputs belong in a private directory.

The macOS build deliberately compiles the same upstream source twice against
the same GGML libraries. It is an experiment, not the Windows release build.
"""
from contextlib import ExitStack
import argparse
import ctypes
import json
from pathlib import Path
import platform
import shutil
import subprocess
from time import perf_counter
from types import SimpleNamespace

from app.whisper_patch import DECODER_PATCH, patched_decoder
from p0.asr_compare import digest
from p0.asr_native import native_whisper

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("baseline", "rng", "beam5", "forced-baseline", "forced-rng")


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("La source du pont a changé ; revoir l’expérience.")
    return text.replace(before, after, 1)


def build(args):
    if platform.system() != "Darwin":
        raise ValueError("Cette construction comparative utilise clang et les dylib macOS.")
    source, runtime, output = (p.resolve(strict=True) for p in (args.source, args.runtime, args.output.parent))
    output = output / args.output.name
    output.mkdir()  # Never replace results or an earlier build.
    before = (source / DECODER_PATCH["path"]).read_bytes()
    after = patched_decoder(before)
    # Freeze included project/upstream headers too: a later checkout must not
    # silently change the experiment while its copied .cpp remains identical.
    frozen = output / "upstream"
    for folder in ("include", "src", "ggml/include", "ggml/src"):
        for header in (source / folder).rglob("*"):
            if header.is_file() and header.suffix in {".h", ".hpp", ".inc"}:
                destination = frozen / header.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(header, destination)
    project = output / "notevive"
    project.mkdir()
    for header in (ROOT / "app/native/WhisperBridge.h", ROOT / "app/macos/native/PauseState.h",
                   ROOT / "app/macos/native/SileroPause.h"):
        shutil.copyfile(header, project / header.name)
    libraries = [runtime / name for name in ("libggml.0.13.1.dylib", "libggml-base.0.13.1.dylib",
                                              "libggml-cpu.0.13.1.dylib", "libggml-blas.0.13.1.dylib")]
    for lib in libraries:
        lib.resolve(strict=True)
    includes = [p for folder in (frozen / "include", frozen / "src", frozen / "ggml/include", frozen / "ggml/src")
                for p in ("-I", str(folder))]
    commands = []
    def compile(command):
        commands.append([str(p) for p in command])
        subprocess.run(command, check=True)
    for arm, data in (("baseline", before), ("rng", after)):
        cpp, lib = output / f"whisper-{arm}.cpp", output / f"libwhisper-{arm}.dylib"
        cpp.write_bytes(data)
        compile(["/usr/bin/clang++", "-std=c++17", "-O3", "-DNDEBUG", "-dynamiclib",
                 '-DWHISPER_VERSION="1.8.5"', "-DWHISPER_SHARED", "-DWHISPER_BUILD",
                 *includes, cpp, *libraries, "-Wl,-headerpad_max_install_names", f"-Wl,-rpath,{runtime}",
                 f"-Wl,-install_name,{lib}", "-o", lib])
        # Wheel dylibs carry their original build-machine install IDs. Change
        # only dependencies of our new library; leave the shared inputs intact.
        for dependency in libraries:
            install_id = subprocess.check_output(["otool", "-D", dependency], text=True).splitlines()[1].strip()
            compile(["install_name_tool", "-change", install_id, f"@rpath/{dependency.name}", lib])
        compile(["codesign", "--force", "--sign", "-", lib])
    original = (ROOT / "app/native/WhisperBridge.cpp").read_text(encoding="utf-8")
    original = replace_once(original, '#include "WhisperBridge.h"',
                            f'#include "{project}/WhisperBridge.h"')
    original = replace_once(original, '#include "../macos/native/PauseState.h"',
                            f'#include "{project}/PauseState.h"')
    for arm in PROFILES:
        text = original
        if arm == "beam5":
            text = replace_once(text, "whisper_full_default_params(WHISPER_SAMPLING_GREEDY)",
                                "whisper_full_default_params(WHISPER_SAMPLING_BEAM_SEARCH)")
        if arm.startswith("forced-"):
            text = replace_once(text, "params.n_threads = 4;",
                                "params.n_threads = 4; params.temperature = 0.4f; params.temperature_inc = 0.0f;")
        cpp, binary = output / f"bridge-{arm}.cpp", output / f"bridge-{arm}.dylib"
        cpp.write_text(text, encoding="utf-8")
        engine = "baseline" if arm in ("baseline", "forced-baseline") else "rng"
        compile(["/usr/bin/clang++", "-std=c++17", "-O3", "-dynamiclib", *includes, cpp,
                 output / f"libwhisper-{engine}.dylib", f"-Wl,-rpath,{runtime}", "-o", binary])
    report = {"schema": 1, "platform": platform.platform(), "decoder_patch": DECODER_PATCH,
              "compiler": subprocess.check_output(["/usr/bin/clang++", "--version"], text=True).splitlines()[0],
              "bridge_source_sha256": digest(ROOT / "app/native/WhisperBridge.cpp"),
              "ggml_libraries": {p.name: digest(p) for p in libraries}, "commands": commands,
              "artifacts": {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}}
    (output / "build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Construction comparative terminée.")


def selected_rows(manifest, cohort):
    rows = json.loads(manifest.read_text(encoding="utf-8"))
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Identifiants dupliqués.")
    # Corti is not licensed for adaptation/development. Never use its outputs
    # to select or tune decoder settings, even if present in the old manifest.
    return [r for r in rows if "corti" not in r["cohorts"]
            and (cohort == "development" or cohort in r["cohorts"])]


def run(args):
    rows = selected_rows(args.manifest, args.cohort)
    warm = next((r for r in rows if r["id"] == "dev-17"), None)
    if warm is None:
        raise ValueError("Le contrôle de préchauffage dev-17 est requis.")
    if args.repeat:
        rows = [warm] * args.repeat
    profiles = args.profiles
    if len(set(profiles)) != len(profiles):
        raise ValueError("Profils dupliqués.")
    if any(p.startswith("forced-") for p in profiles) and not args.repeat:
        raise ValueError("La température forcée est réservée au contrôle de répétition, hors score produit.")
    args.output.mkdir()
    build_info = json.loads((args.build / "build.json").read_text(encoding="utf-8"))
    # Reject modified binaries. Their settings and source hashes are recorded.
    for name, expected in build_info["artifacts"].items():
        if digest(args.build / name) != expected:
            raise ValueError(f"Construction modifiée : {name}")
    with ExitStack() as stack:
        runners, logs = {}, {}
        for profile in profiles:
            binary = args.build / f"bridge-{profile}.dylib"
            started = perf_counter()
            runners[profile] = native_whisper(ctypes.CDLL(str(binary.resolve())),
                SimpleNamespace(model=args.model, vad=args.vad, pause_ms=576), stack)
            wav = args.manifest.parent / warm["path"]
            if digest(wav) != warm["sha256"]:
                raise ValueError("Préchauffage altéré.")
            runners[profile](wav)
            logs[profile] = stack.enter_context((args.output / f"{profile}.ndjson").open("x", encoding="utf-8"))
            meta = {"manifest": digest(args.manifest), "engine": "whisper-native", "profile": profile,
                    "runtime": platform.platform(), "threads": 4, "pause_ms_requested": 576,
                    "cohort": None if args.cohort == "development" else args.cohort,
                    "selected_count": len(rows), "excluded_cohorts": ["corti"],
                    "repeat_control_only": bool(args.repeat), "binary_sha256": digest(binary),
                    "build_manifest_sha256": digest(args.build / "build.json"),
                    "whisper_weights_sha256": digest(args.model), "vad_sha256": digest(args.vad),
                    "startup_plus_warmup_ms": (perf_counter() - started) * 1000,
                    "method": "Paired WAV, alternating profile order; development, not independent confirmation."}
            print(json.dumps({"meta": meta}), file=logs[profile], flush=True)
        for index, row in enumerate(rows):
            wav = args.manifest.parent / row["path"]
            if digest(wav) != row["sha256"]:
                raise ValueError("Audio altéré.")
            order = profiles if index % 2 == 0 else list(reversed(profiles))
            for profile in order:
                print(f"{index + 1}/{len(rows)} {profile} {row['id']}", flush=True)
                result = runners[profile](wav)
                print(json.dumps({"id": row["id"], "status": "ok", **result}, ensure_ascii=False),
                      file=logs[profile], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    for name in ("source", "runtime", "output"):
        b.add_argument("--" + name, type=Path, required=True)
    r = sub.add_parser("run")
    for name in ("build", "manifest", "model", "vad", "output"):
        r.add_argument("--" + name, type=Path, required=True)
    r.add_argument("--profiles", choices=PROFILES, nargs="+", default=["baseline", "rng"])
    r.add_argument("--cohort", choices=("stress", "development"), default="stress")
    r.add_argument("--repeat", type=int, default=0)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        if args.repeat < 0:
            parser.error("--repeat doit être positif")
        run(args)


if __name__ == "__main__":
    main()
