"""Isolated AVX2 benchmark builds; do not use these DLLs to replace product files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from app import build_whisper_windows as win
from app.whisper_patch import DECODER_PATCH, edit_decoder


ROOT = Path(__file__).resolve().parents[2]
BASELINE, CANDIDATE = win.VERSION, "1.9.5"
SOURCES = {
    BASELINE: {"url": win.SOURCE_URL, "hash": win.SOURCE_SHA256},
    CANDIDATE: {
        "url": "https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.9.5",
        "hash": "ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720",
    },
}
PROBE_EXPORTS = ("NVWhisperCreate", "NVWhisperDestroy", "NVWhisperReset", "NVWhisperAccept", "NVWhisperFinish")
CANDIDATE_LICENSE = "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d"
BRIDGE = ROOT / "app/native/WhisperBridge.cpp"
PAUSE = ROOT / "app/macos/native/PauseState.h"
SILERO_PAUSE = PAUSE.with_name("SileroPause.h")
FLAGS = ("CL", "_CL_", "CFLAGS", "CXXFLAGS", "ASMFLAGS", "CPPFLAGS", "LINK", "_LINK_", "LDFLAGS",
         "CMAKE_TOOLCHAIN_FILE", "CC", "CXX", "ASM")


def replace_once(source, match, replacement):
    if source.count(match) != 1:
        raise ValueError("Le banc ne reconnaît pas la source verrouillée.")
    return source.replace(match, replacement, 1)


def benchmark_bridge(source, version):
    if version == BASELINE:
        return source
    if version != CANDIDATE:
        raise ValueError("Version du banc inconnue.")
    prefix = b'std::string(whisper_version()) != '
    return replace_once(source, prefix + f'"{BASELINE}"'.encode(), prefix + f'"{version}"'.encode())


def candidate_cmake(path):
    before = path.read_bytes()
    if hashlib.sha256(before).hexdigest() != "f4494d2da1353158b8a33b935abe6bbe76b8cee95d503fb16088224dd4755dcc":
        raise ValueError("Source CMake 1.9.5 altérée.")
    after = replace_once(before, b'\nproject("whisper.cpp" C CXX)\n',
                         b'\ncmake_policy(SET CMP0091 NEW)\nproject("whisper.cpp" C CXX)\n')
    after = replace_once(after, b"\nadd_subdirectory(src)\n",
                         b"\nset(BUILD_SHARED_LIBS ON)\nadd_subdirectory(src)\nset(BUILD_SHARED_LIBS OFF)\n")
    path.write_bytes(after)


def candidate_blas(path):
    before = path.read_bytes()
    if hashlib.sha256(before).hexdigest() != "8722818272683553481d5d36a3dce68c082731a9746d79ea31eb36edcd40f5ee":
        raise ValueError("Source CMake BLAS 1.9.5 altérée.")
    # Same explicit CBLAS target and static archive as the product arm.
    after = replace_once(before, b"find_package(BLAS)\n", b'''if (NOT DEFINED NOTEVIVE_OPENBLAS_ROOT)
    message(FATAL_ERROR "Pinned static OpenBLAS required")
endif()
set(BLAS_INCLUDE_DIRS "${NOTEVIVE_OPENBLAS_ROOT}/generated")
set(BLAS_LIBRARIES "${NOTEVIVE_OPENBLAS_ROOT}/lib/openblas.lib")
if (NOT EXISTS "${BLAS_LIBRARIES}" OR NOT EXISTS "${BLAS_INCLUDE_DIRS}/cblas.h")
    message(FATAL_ERROR "Pinned static OpenBLAS inputs missing")
endif()
set(BLAS_FOUND TRUE)
''')
    path.write_bytes(after)


def stage_probe(tree, version):
    native = tree / "nv-probe/native"
    native.mkdir(parents=True)
    vad = tree / "nv-probe/macos/native"
    vad.mkdir(parents=True)
    shutil.copyfile(PAUSE, vad / PAUSE.name)
    shutil.copyfile(SILERO_PAUSE, vad / SILERO_PAUSE.name)
    shutil.copyfile(BRIDGE.with_suffix(".h"), native / "WhisperBridge.h")
    (native / "WhisperBridge.cpp").write_bytes(benchmark_bridge(BRIDGE.read_bytes(), version))
    # Reuse the product's exact CPUID+OS checks without linking or loading
    # the AVX2 candidate (even its loader initializers may require AVX2).
    with (ROOT / "app/windows/engine.cpp").open(encoding="utf-8") as f:
        source = f.read()
    start, end = "bool processor_supports_avx2() noexcept {", "\nenum class CpuVariant"
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError("Garde AVX2 NoteVive non reconnue.")
    body = source[source.index(start):source.index(end)].rstrip()
    (tree / "nv-probe/cpu.cpp").write_text(
        "#include <windows.h>\n#include <array>\n#include <cstddef>\n#include <intrin.h>\n"
        + body + "\nint main() { return processor_supports_avx2() ? 0 : 1; }\n", encoding="ascii")
    (tree / "nv-probe/CMakeLists.txt").write_text(
        "add_library(nv_probe SHARED native/WhisperBridge.cpp)\n"
        "target_compile_features(nv_probe PRIVATE cxx_std_17)\n"
        "target_compile_definitions(nv_probe PRIVATE WHISPER_SHARED)\n"
        "target_link_libraries(nv_probe PRIVATE whisper)\n"
        + "target_link_options(nv_probe PRIVATE " + " ".join("/EXPORT:" + name for name in PROBE_EXPORTS) + ")\n"
        "add_executable(nv_cpu_check cpu.cpp)\n", encoding="ascii")
    with (tree / "CMakeLists.txt").open("a", encoding="ascii", newline="\n") as stream:
        stream.write("\nadd_subdirectory(nv-probe)\n")


def build_pair(sources, openblas, output, jobs, cmake="cmake"):
    if win.digest(openblas) != win.OPENBLAS_SOURCE_SHA256:
        raise ValueError("Archive OpenBLAS altérée.")
    env = {k: v for k, v in os.environ.items() if k.upper() not in FLAGS}
    config = [cmake, "-G", win.GENERATOR, "-A", "x64", "-T", win.TOOLSETS["clangcl"][0]]
    options = win.variant_options("clangcl", "avx2", True)
    reports = {}
    with tempfile.TemporaryDirectory(prefix="nv-asr-build-") as work:
        temp = Path(work)
        # OpenBLAS is compiled once, with the same compiler as both Whisper builds.
        sdk = temp / "sdk"
        sdk.mkdir()
        (sdk / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.15)\nproject(nv_toolchain C CXX)\n", encoding="ascii")
        toolchain = temp / "sdk-build"
        win.toolchain_query(toolchain)
        subprocess.run([*config, "-S", sdk, "-B", toolchain], env=env, check=True)
        compiler = win.verify_compilers(toolchain, "clangcl")
        blas, metadata = win.build_openblas(openblas, temp, output, cmake, jobs, env, win.read_toolchains(toolchain)["C"])
        blas_sha = win.digest(blas / "lib/openblas.lib")
        for version, spec in SOURCES.items():
            src = sources[version]
            if win.digest(src) != spec["hash"]:
                raise ValueError("Archive Whisper altérée.")
            with tarfile.open(src, "r:gz") as archive:
                archive.extractall(temp, filter="data")
            tree = temp / f"whisper.cpp-{version}"
            flags = options.copy()
            if version == BASELINE:
                win.edit_cmake(tree / "CMakeLists.txt")
                edit_decoder(tree / DECODER_PATCH["path"])
                win.edit_blas_cmake(tree / win.OPENBLAS_PATCH["path"])
            else:
                candidate_cmake(tree / "CMakeLists.txt")
                candidate_blas(tree / win.OPENBLAS_PATCH["path"])
                flags["WHISPER_BUILD_IS_DEV"] = "OFF"
                if win.digest(tree / "LICENSE") != CANDIDATE_LICENSE:
                    raise ValueError("Licence Whisper inattendue.")
            stage_probe(tree, version)
            build = temp / f"build-{version}"
            win.toolchain_query(build)
            subprocess.run([*config, "-S", tree, "-B", build,
                            *[f"-D{k}={v}" for k, v in flags.items()],
                            f"-DNOTEVIVE_OPENBLAS_ROOT={blas.as_posix()}"], env=env, check=True)
            if win.verify_compilers(build, "clangcl") != compiler:
                raise ValueError("Les versions du compilateur diffèrent entre les bras.")
            win.verify_projects(build, "avx2", "clangcl", True)
            subprocess.run([cmake, "--build", build, "--config", "Release", "--parallel", str(jobs),
                            "--target", "nv_probe", "nv_cpu_check"], env=env, check=True)
            subprocess.run([win.find_unique(build, "nv_cpu_check.exe")], env=env, check=True, timeout=10)
            stage = output / version
            stage.mkdir()
            dll, probe = (win.find_unique(build, name) for name in ("whisper.dll", "nv_probe.dll"))
            imports = win.verify_runtime(dll)
            probe_imports = win.pe_imports(probe.read_bytes())
            if "whisper.dll" not in probe_imports or any(
                    item not in win.SYSTEM_DLLS | {"whisper.dll"}
                    and not item.startswith(("api-ms-win-core-", "api-ms-win-crt-", "ext-ms-win-"))
                    for item in probe_imports):
                raise ValueError("Dépendance inattendue du pont de benchmark.")
            for source in (dll, probe, tree / "LICENSE"):
                shutil.copyfile(source, stage / source.name)
            reports[version] = {"compiler": compiler, "cmake_options": flags, "source": spec,
                                "whisper_dll_sha256": win.digest(dll), "probe_dll_sha256": win.digest(probe),
                                "whisper_imports": imports, "probe_imports": probe_imports,
                                "whisper_license_sha256": win.digest(tree / "LICENSE"),
                                "rng_reset": DECODER_PATCH["upstream_commit"] if version == BASELINE else "upstream"}
    return {"openblas": metadata, "openblas_lib_sha256": blas_sha, "arms": reports,
            "bridge_sha256": win.digest(BRIDGE), "pause_state_sha256": win.digest(PAUSE),
            "silero_pause_sha256": win.digest(SILERO_PAUSE)}
