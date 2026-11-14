"""Build the pinned, CPU-only Whisper 1.8.5 DLL for NoteVive on Windows x64."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET


VERSION = "1.8.5"
SOURCE_NAME = f"whisper-v{VERSION}-source.tar.gz"
SOURCE_URL = f"https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v{VERSION}"
SOURCE_SHA256 = "cd702189cb5e608c8bc487f4b151db593c4455925b37cc06ef76b44861911db1"
SOURCE_ROOT = f"whisper.cpp-{VERSION}"
CMAKE_PATCH = {"path": "CMakeLists.txt",
               "before_sha256": "14b57729cec1bf09635ea23f551112f51220ad2f22214b42c1f1689b96480d7b",
               "after_sha256": "3d65c6bbe3f6e4f3033fa047e92c6754132a2f385a1e77b126f10a27dc3be74d"}
OPENBLAS_VERSION = "0.3.34"
OPENBLAS_SOURCE_URL = ("https://github.com/OpenMathLib/OpenBLAS/releases/download/"
                      f"v{OPENBLAS_VERSION}/OpenBLAS-{OPENBLAS_VERSION}.tar.gz")
OPENBLAS_SOURCE_SHA256 = "cd7e129868320cc2d033afa920e31202dfe0b8066a5b66661900ccc0f197dfed"
OPENBLAS_LICENSE = "LICENSE.OpenBLAS"
OPENBLAS_LICENSE_SHA256 = "190b5a9c8d9723fe958ad33916bd7346d96fab3c5ea90832bb02d854f620fcff"
OPENBLAS_PATCH = {"path": "ggml/src/ggml-blas/CMakeLists.txt",
                  "before_sha256": "dc7028c2c7207e8c334fd61ea4556599a326710cd9b33050bace38833529df71",
                  "after_sha256": "51bf55eca2ae18fce5b8ed07a7c9bd911a2280b074a669b8a1483607a78c1db1"}
VARIANT_DLL = {"baseline": "whisper.dll", "avx2": "cpu-avx2/whisper.dll"}
DLL_NAMES = tuple(VARIANT_DLL.values())
HEADERS = {
    "whisper.h": "include/whisper.h",
    **{f"{name}.h": f"ggml/include/{name}.h" for name in ("ggml", "ggml-alloc", "ggml-backend", "ggml-cpu")},
}
ARTIFACTS = (*[f"bin/{name}" for name in DLL_NAMES], "lib/whisper.lib",
             *[f"include/{name}" for name in HEADERS], "LICENSE")
GENERATOR = "Visual Studio 17 2022"
TOOLSETS = {"msvc": ("v143,host=x64", "v143", "MSVC", "cl.exe"),
            "clangcl": ("ClangCL", "ClangCL", "Clang", "clang-cl.exe")}
DEFAULT_TOOLSET = "clangcl"
CONFIG = "Release"
STATIC_CRT_PROJECTS = ("whisper", "ggml", "ggml-base", "ggml-cpu")
# Build GGML into each DLL statically. The worker loads one of the two, which
# owns all ASR allocations and never needs a dynamically discovered backend.
BASELINE_OPTIONS = {
    "BUILD_SHARED_LIBS": "OFF",
    "CMAKE_MSVC_RUNTIME_LIBRARY": "MultiThreaded",
    "GGML_CPU": "ON",
    **dict.fromkeys((
        "WHISPER_BUILD_TESTS", "WHISPER_BUILD_EXAMPLES", "WHISPER_BUILD_SERVER",
        "WHISPER_CURL", "WHISPER_SDL2", "WHISPER_USE_SYSTEM_GGML", "WHISPER_COREML",
        "WHISPER_OPENVINO", "GGML_BUILD_TESTS", "GGML_BUILD_EXAMPLES", "GGML_CCACHE",
        "GGML_BACKEND_DL", "GGML_CPU_ALL_VARIANTS", "GGML_OPENMP", "GGML_LTO",
        "GGML_NATIVE", "GGML_SSE42", "GGML_AVX", "GGML_AVX_VNNI", "GGML_AVX2", "GGML_BMI2",
        "GGML_AVX512", "GGML_AVX512_BF16", "GGML_AVX512_VBMI", "GGML_AVX512_VNNI",
        "GGML_CPU_HBM", "GGML_CPU_KLEIDIAI", "GGML_BLAS", "GGML_LLAMAFILE",
        "GGML_CUDA", "GGML_HIP", "GGML_VULKAN", "GGML_OPENCL", "GGML_METAL", "GGML_SYCL",
    ), "OFF"),
}
VARIANT_OPTIONS = {
    "baseline": BASELINE_OPTIONS,
    # On MSVC GGML_AVX2 adds /arch:AVX2 and implies GGML_FMA and GGML_F16C
    # preprocessor definitions. Never pass host-native, AVX512 or AVX-VNNI.
    "avx2": {**BASELINE_OPTIONS, "GGML_AVX": "ON", "GGML_AVX2": "ON", "GGML_LLAMAFILE": "ON"},
}
# ClangCL's /arch:AVX2 also selects these features, which the NoteVive
# supervisor does not test. Keep its existing AVX2 selection contract.
CLANGCL_AVX2_LIMITS = tuple(f"-clang:-mno-{feature}" for feature in ("fsgsbase", "movbe", "pclmul", "xsaveopt"))
OPENBLAS_OPTIONS = {
    "CMAKE_BUILD_TYPE": CONFIG,
    "CMAKE_POLICY_DEFAULT_CMP0091": "NEW",
    "CMAKE_MSVC_RUNTIME_LIBRARY": "MultiThreaded",
    "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
    "CMAKE_C_FLAGS_INIT": " ".join(("/arch:AVX2", *CLANGCL_AVX2_LIMITS)),
    "BINARY": "64", "TARGET": "HASWELL", "NUM_THREADS": "4",
    **dict.fromkeys(("BUILD_SINGLE", "BUILD_STATIC_LIBS", "BUILD_WITHOUT_LAPACK", "FIXED_LIBNAME",
                     "NOFORTRAN", "NO_AVX512", "ONLY_CBLAS", "USE_THREAD"), "ON"),
    **dict.fromkeys(("BUILD_SHARED_LIBS", "BUILD_DOUBLE", "BUILD_COMPLEX", "BUILD_COMPLEX16",
                     "BUILD_TESTING", "DYNAMIC_ARCH", "USE_OPENMP", "INTERFACE64"), "OFF"),
}
# Windows 11 system DLL names allowed by the import-table audit. In particular
# VCRUNTIME*, MSVCP*, VCOMP*, libomp*, and any GGML plugin are not allowed.
SYSTEM_DLLS = {"kernel32.dll", "psapi.dll", "advapi32.dll", "user32.dll", "bcrypt.dll",
               "shell32.dll", "ntdll.dll", "ucrtbase.dll", "version.dll", "ole32.dll", "ws2_32.dll",
               "synchronization.dll"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def edit_cmake(path):
    before = path.read_bytes()
    data = before
    for search, replace in (
        # Activate CMP0091 before the first project() enables C/C++.
        (b'\nproject("whisper.cpp" C CXX)\n',
         b'\ncmake_policy(SET CMP0091 NEW)\nproject("whisper.cpp" C CXX)\n'),
        # The OFF option applies to ggml/ above. Only src/ builds a DLL.
        (b"\nadd_subdirectory(src)\n",
         b"\nset(BUILD_SHARED_LIBS ON)\nadd_subdirectory(src)\nset(BUILD_SHARED_LIBS OFF)\n"),
    ):
        if data.count(search) != 1:
            raise ValueError("Le correctif Whisper ne correspond pas aux sources verrouillées.")
        data = data.replace(search, replace, 1)
    if (hashlib.sha256(before).hexdigest() != CMAKE_PATCH["before_sha256"] or
            hashlib.sha256(data).hexdigest() != CMAKE_PATCH["after_sha256"]):
        raise ValueError("Empreinte incorrecte pour le correctif CMake de Whisper.")
    path.write_bytes(data)
    return CMAKE_PATCH


def edit_blas_cmake(path):
    # The built-in FindBLAS probes a Fortran symbol and may select a system
    # library. Our experiment only uses CBLAS from the pinned static build.
    before = path.read_bytes()
    marker = b"find_package(BLAS)\n"
    after = before.replace(marker, b'''if (WIN32 AND GGML_BLAS_VENDOR STREQUAL "OpenBLAS" AND DEFINED NOTEVIVE_OPENBLAS_ROOT)
    set(BLAS_INCLUDE_DIRS "${NOTEVIVE_OPENBLAS_ROOT}/generated")
    set(BLAS_LIBRARIES "${NOTEVIVE_OPENBLAS_ROOT}/lib/openblas.lib")
    if (NOT EXISTS "${BLAS_LIBRARIES}" OR NOT EXISTS "${BLAS_INCLUDE_DIRS}/cblas.h")
        message(FATAL_ERROR "Pinned static OpenBLAS inputs missing")
    endif()
    set(BLAS_FOUND TRUE)
else()
    find_package(BLAS)
endif()
''', 1)
    if (before.count(marker) != 1 or hashlib.sha256(before).hexdigest() != OPENBLAS_PATCH["before_sha256"]
            or hashlib.sha256(after).hexdigest() != OPENBLAS_PATCH["after_sha256"]):
        raise ValueError("Le correctif BLAS ne correspond pas aux sources Whisper verrouillées.")
    path.write_bytes(after)


def pe_imports(data):
    """Get normal and delay-loaded imports from a PE32+ x64 DLL."""
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("Signature DOS manquante.")
    pe, = struct.unpack_from("<I", data, 0x3c)
    if pe > len(data) - 24 or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Signature PE manquante.")
    machine, sections, _, _, _, opt_size, flags = struct.unpack_from("<HHIIIHH", data, pe + 4)
    opt = pe + 24
    if (machine != 0x8664 or not flags & 0x2000 or opt_size < 112 or
            opt + opt_size + sections * 40 > len(data) or
            struct.unpack_from("<H", data, opt)[0] != 0x20b):
        raise ValueError("Le moteur doit être une DLL Windows PE32+ x64.")
    spans = [struct.unpack_from("<IIII", data, opt + opt_size + i * 40 + 8) for i in range(sections)]

    def file_range(rva, size):
        for _, address, raw_size, raw in spans:
            offset = rva - address
            if 0 <= offset and offset + size <= raw_size and raw + offset + size <= len(data):
                return raw + offset, min(raw + raw_size, len(data))
        raise ValueError(f"RVA hors section PE : 0x{rva:x}")

    imports = set()
    directory_count, = struct.unpack_from("<I", data, opt + 108)
    for entry, words, name_pos in ((1, 5, 3), (13, 8, 1)):
        if entry >= directory_count:
            continue
        if 112 + 8 * (entry + 1) > opt_size:
            raise ValueError("Répertoire PE tronqué.")
        rva, size = struct.unpack_from("<II", data, opt + 112 + 8 * entry)
        if not rva and not size:
            continue
        width = words * 4
        offset, _ = file_range(rva, size)
        for pos in range(offset, offset + size - width + 1, width):
            row = struct.unpack_from(f"<{words}I", data, pos)
            if not any(row):
                break
            if not row[name_pos] or (entry == 13 and row[0] != 1):
                raise ValueError("Descripteur d’import PE invalide.")
            start, end = file_range(row[name_pos], 1)
            stop = data.find(b"\0", start, min(end, start + 256))
            if stop < 0:
                raise ValueError("Nom de DLL importée non terminé.")
            imports.add(data[start:stop].decode("ascii").lower())
        else:
            raise ValueError("Table d’import PE non terminée.")
    if not imports:
        raise ValueError("Aucun import Windows dans la DLL.")
    return sorted(imports)


def verify_runtime(dll_file):
    imports = pe_imports(dll_file.read_bytes())
    unexpected = [dep for dep in imports if dep not in SYSTEM_DLLS and
                  not dep.startswith(("api-ms-win-core-", "api-ms-win-crt-", "ext-ms-win-"))]
    if unexpected:
        raise ValueError(f"Installation externe requise pour la DLL Whisper : {', '.join(unexpected)}")
    return imports


def valid_compilers(compilers, toolset):
    _, _, expected_id, expected_exe = TOOLSETS[toolset]
    return (isinstance(compilers, dict) and compilers.keys() == {"C", "CXX"}
            and compilers["C"] == compilers["CXX"]
            and all(isinstance(spec, dict) and spec.get("id") == expected_id
                    and spec.get("executable") == expected_exe and isinstance(spec.get("version"), str)
                    and re.fullmatch(r"\d+(?:\.\d+)+", spec["version"]) is not None
                    for spec in compilers.values()))


def variant_options(toolset, variant, openblas=False):
    options = VARIANT_OPTIONS[variant].copy()
    if toolset == "clangcl" and variant == "avx2":
        limits = " ".join(CLANGCL_AVX2_LIMITS)
        # Seed the flags; CMake appends its Windows defaults (including /EHsc).
        options.update(CMAKE_C_FLAGS_INIT=limits, CMAKE_CXX_FLAGS_INIT=limits)
    if openblas and variant == "avx2":
        options.update(GGML_BLAS="ON", GGML_BLAS_VENDOR="OpenBLAS", GGML_LLAMAFILE="OFF")
    return options


def read_toolchains(build):
    reply = build / ".cmake/api/v1/reply"
    index = json.loads(find_unique(reply, "index-*.json").read_text(encoding="utf-8"))
    reference = index["reply"]["toolchains-v1"]["jsonFile"]
    data = json.loads((reply / reference).read_text(encoding="utf-8"))
    return {row["language"]: row["compiler"] for row in data["toolchains"]}


def verify_compilers(build, toolset):
    compilers = {}
    for language, selected in read_toolchains(build).items():
        if language in {"C", "CXX"}:
            compilers[language] = {"id": selected["id"], "version": selected["version"],
                                   "executable": Path(selected["path"]).name.lower()}
    if not valid_compilers(compilers, toolset):
        raise ValueError(f"Compilateurs {toolset} attendus, CMake a choisi : {compilers}")
    return compilers


def verify_projects(build, variant, toolset, openblas=False):
    _, expected_platform, _, _ = TOOLSETS[toolset]
    projects = STATIC_CRT_PROJECTS + (("ggml-blas",) if openblas else ())
    for name in projects:
        files = list(build.rglob(f"{name}.vcxproj"))
        if len(files) != 1:
            raise ValueError(f"Projet Visual Studio manquant ou dupliqué : {name}")
        tree = ET.parse(files[0])
        platforms = {node.text for node in tree.findall("{*}PropertyGroup/{*}PlatformToolset")}
        if platforms != {expected_platform}:
            raise ValueError(f"Toolset {expected_platform} non confirmé dans le projet {name} : {platforms}")
        release = [cfg for cfg in tree.findall("{*}ItemDefinitionGroup")
                   if "Release|x64" in cfg.attrib.get("Condition", "")]
        if len(release) != 1:
            raise ValueError(f"Configuration Release x64 manquante : {name}")
        values = {x.text for x in release[0].findall("{*}ClCompile/{*}RuntimeLibrary")}
        if values != {"MultiThreaded"}:
            raise ValueError(f"CRT statique /MT non confirmé dans le projet {name} : {values}")
        compiler = release[0].find("{*}ClCompile")
        isa = compiler.findtext("{*}EnableEnhancedInstructionSet")
        flags = compiler.findtext("{*}AdditionalOptions", "").lower().split()
        has_cpp = any(Path(source.attrib.get("Include", "")).suffix.lower() in {".cpp", ".cxx", ".cc"}
                      for source in tree.findall("{*}ItemGroup/{*}ClCompile"))
        if has_cpp:
            exceptions = compiler.findtext("{*}ExceptionHandling")
            enabled = exceptions == "Sync" or "/ehsc" in flags or "-ehsc" in flags
            disabled = {"/ehs-", "-ehs-", "/ehsc-", "-ehsc-", "-fno-exceptions", "-fno-cxx-exceptions",
                        "-clang:-fno-exceptions", "-clang:-fno-cxx-exceptions"}.intersection(flags)
            if not enabled or exceptions == "false" or disabled:
                raise ValueError(f"Exceptions C++ /EHsc non confirmées dans le projet {name} : {exceptions} {flags}")
        if {"/md", "/mdd", "/mtd", "-md", "-mdd", "-mtd"}.intersection(flags):
            raise ValueError(f"Flag CRT incompatible dans le projet {name} : {flags}")
        if toolset == "clangcl" and variant == "avx2" and not set(CLANGCL_AVX2_LIMITS).issubset(flags):
            raise ValueError(f"Limites ISA ClangCL absentes du projet {name} : {flags}")
        has_avx2 = isa == "AdvancedVectorExtensions2" or any(x in flags for x in ("/arch:avx2", "-arch:avx2"))
        if has_avx2 != (variant == "avx2" and name == "ggml-cpu") or (
                isa not in (None, "", "NotSet", "StreamingSIMDExtensions2", "AdvancedVectorExtensions2") or
                any(option.startswith(("/arch:", "-arch:")) and option[1:] not in {"arch:sse2", "arch:avx2"}
                    for option in flags)):
            raise ValueError(f"Architecture CPU inattendue pour {variant}/{name} : {isa} {flags}")


def verify_loaded_version(dll):
    # Safe DLL lookup and a C ABI call verify loading and version on Windows.
    lib = ctypes.WinDLL(str(dll), winmode=0x00000900)  # DLL_LOAD_DIR | SYSTEM32
    try:
        lib.whisper_version.argtypes = []
        lib.whisper_version.restype = ctypes.c_char_p
        if lib.whisper_version() != VERSION.encode("ascii"):
            raise ValueError("L’export C whisper_version ne renvoie pas la version demandée.")
    finally:
        # ctypes leaves its DLL loaded. Free it so Windows can move the staging directory.
        free = ctypes.WinDLL("kernel32.dll", winmode=0x800).FreeLibrary
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_int
        if not free(lib._handle):
            raise OSError("Impossible de fermer la DLL contrôlée.")


def find_unique(directory, filename):
    files = list(directory.rglob(filename))
    if len(files) != 1 or not files[0].stat().st_size:
        raise ValueError(f"Fichier construit absent, vide ou dupliqué : {filename}")
    return files[0]


def artifact_spec(directory, openblas=False):
    artifacts = ARTIFACTS + ((OPENBLAS_LICENSE,) if openblas else ())
    return {name: {"sha256": digest(directory / name), "bytes": (directory / name).stat().st_size}
            for name in artifacts}


def openblas_metadata(compiler):
    return {"version": OPENBLAS_VERSION, "source_url": OPENBLAS_SOURCE_URL,
            "source_sha256": OPENBLAS_SOURCE_SHA256, "variant": "avx2", "generator": "Ninja",
            "cmake_options": OPENBLAS_OPTIONS, "compiler": compiler, "whisper_patch": OPENBLAS_PATCH}


def validate_staged(directory):
    """Verify the Windows-produced directory before bundling on any host."""
    log = json.loads((directory / "attestation.json").read_text(encoding="utf-8"))
    variants = log.get("variants")
    toolset = log.get("toolset")
    blas = log.get("openblas")
    openblas = blas is not None
    if (log.get("schema") != (4 if openblas else 3) or log.get("version") != VERSION
            or log.get("source_url") != SOURCE_URL or log.get("source_sha256") != SOURCE_SHA256
            or log.get("patch") != CMAKE_PATCH
            or log.get("generator") != GENERATOR or not isinstance(toolset, str) or toolset not in TOOLSETS
            or log.get("cmake_toolset") != TOOLSETS[toolset][0]
            or not valid_compilers(log.get("compilers"), toolset)
            or log.get("config") != CONFIG or log.get("static_crt_projects") != list(STATIC_CRT_PROJECTS)
            or log.get("artifacts") != artifact_spec(directory, openblas)
            or not isinstance(variants, dict) or variants.keys() != VARIANT_DLL.keys()):
        raise ValueError("La construction Whisper ne correspond pas à son attestation.")
    if openblas and (toolset != "clangcl" or blas != openblas_metadata(log["compilers"]["C"])
                     or log["artifacts"][OPENBLAS_LICENSE]["sha256"] != OPENBLAS_LICENSE_SHA256):
        raise ValueError("La construction OpenBLAS ne correspond pas à l’attestation Whisper.")
    for variant, path in VARIANT_DLL.items():
        spec = variants[variant]
        if (spec.get("cmake_options") != variant_options(toolset, variant, openblas) or spec.get("dll") != f"bin/{path}" or
                spec.get("imports") != verify_runtime(directory / "bin" / path) or
                not isinstance(spec.get("native_load_checked"), bool) or
                (variant == "baseline" and not spec["native_load_checked"])):
            raise ValueError(f"L’attestation Whisper ne correspond pas à la variante {variant}.")
    return log


def available_avx2():
    # This build-time smoke only loads the DLL and queries its version; it
    # doesn't enter GGML CPU kernels. The worker performs stricter checks
    # (FMA, F16C and related flags) before any native decoding.
    feature = ctypes.WinDLL("kernel32.dll", winmode=0x800).IsProcessorFeaturePresent
    feature.argtypes = [ctypes.c_uint]
    feature.restype = ctypes.c_int
    return bool(feature(40))  # PF_AVX2_INSTRUCTIONS_AVAILABLE


def toolchain_query(build):
    query = build / ".cmake/api/v1/query/toolchains-v1"
    query.parent.mkdir(parents=True)
    query.touch()


def ninja_environment(temp, env):
    # Ninja needs the Visual Studio SDK environment (Whisper's VS generator
    # resolves SDK headers and libraries internally). Use the installed tools.
    vswhere = (Path(env["ProgramFiles(x86)"]) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe")
    install = subprocess.check_output([vswhere, "-latest", "-products", "*", "-version", "[17.0,18.0)",
                                       "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                                       "-property", "installationPath", "-utf8"], encoding="utf-8", env=env).strip()
    vs = Path(install)
    setup = vs / "VC/Auxiliary/Build/vcvars64.bat"
    ninja = shutil.which("ninja.exe", path=env.get("PATH"))
    ninja = Path(ninja) if ninja else vs / "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe"
    if not install or not setup.is_file() or not ninja.is_file():
        raise ValueError("OpenBLAS nécessite le SDK Visual Studio 2022 x64 et Ninja.")
    batch = temp / "nv-vcvars.cmd"
    batch.write_text('@call "%NOTEVIVE_VCVARS64%" >nul && set\n', encoding="ascii")
    cmd = Path(env["SystemRoot"]) / "System32/cmd.exe"
    output = subprocess.check_output([cmd, "/d", "/u", "/v:off", "/c", batch.name], cwd=temp, env={
        **env, "NOTEVIVE_VCVARS64": str(setup),
    }).decode("utf-16-le")
    return ({key: value for row in output.splitlines() if not row.startswith("=")
             for key, sep, value in (row.partition("="),) if sep and key != "NOTEVIVE_VCVARS64"}, ninja)


def build_openblas(source, temp, staging, cmake, jobs, env, whisper_compiler):
    contents = temp / "openblas-source"
    contents.mkdir()
    with tarfile.open(source, "r:gz") as archive:
        archive.extractall(contents, filter="data")
    tree = contents / f"OpenBLAS-{OPENBLAS_VERSION}"
    if not (tree / "CMakeLists.txt").is_file() or digest(tree / "LICENSE") != OPENBLAS_LICENSE_SHA256:
        raise ValueError("Structure inattendue de l’archive OpenBLAS.")
    clang = Path(whisper_compiler["path"])
    ninja_env, ninja = ninja_environment(temp, env)
    build = temp / "openblas-build"
    toolchain_query(build)
    flags = [f"-D{k}={v}" for k, v in OPENBLAS_OPTIONS.items()]
    subprocess.run([cmake, "-S", tree, "-B", build, "-G", "Ninja", *flags,
                    f"-DCMAKE_MAKE_PROGRAM={ninja.as_posix()}",
                    f"-DCMAKE_C_COMPILER={clang.as_posix()}", f"-DCMAKE_ASM_COMPILER={clang.as_posix()}"],
                   check=True, env=ninja_env)
    compiler = read_toolchains(build).get("C", {})
    if (Path(compiler.get("path", "")).resolve() != clang.resolve()
            or compiler.get("id") != "Clang" or compiler.get("version") != whisper_compiler["version"]):
        raise ValueError("Les compilateurs OpenBLAS et Whisper diffèrent.")
    config = (build / "config.h").read_text(encoding="ascii")
    if (not re.search(r"^\s*#\s*define\s+CORE_HASWELL\b", config, re.MULTILINE)
            or not re.search(r"^\s*#\s*define\s+HAVE_AVX2\b", config, re.MULTILINE)):
        raise ValueError("Noyau OpenBLAS Haswell AVX2 non confirmé.")
    commands = json.loads((build / "compile_commands.json").read_text(encoding="utf-8"))
    c_flags = [set(row["command"].lower().replace('"', '').split())
               for row in commands if Path(row["file"]).suffix.lower() == ".c"]
    if not c_flags or any(not {"mt", "arch:avx2", *[flag[1:] for flag in CLANGCL_AVX2_LIMITS]}.issubset(flags)
                          or flags.intersection({"md", "mdd", "mtd"})
                          for flags in ({flag.lstrip('/-') for flag in row} for row in c_flags)):
        raise ValueError("CRT statique /MT ou limites ISA non confirmés pour OpenBLAS.")
    subprocess.run([cmake, "--build", build, "--parallel", str(jobs), "--target", "openblas_static"],
                   check=True, env=ninja_env)
    lib = find_unique(build, "openblas.lib")
    fixed = build / "lib/openblas.lib"
    if lib != fixed:
        fixed.parent.mkdir(exist_ok=True)
        shutil.copyfile(lib, fixed)
    shutil.copyfile(build / "openblas_config.h", build / "generated/openblas_config.h")
    shutil.copyfile(tree / "LICENSE", staging / OPENBLAS_LICENSE)
    return build, openblas_metadata({"id": "Clang", "executable": clang.name.lower(),
                                     "version": compiler["version"]})


def build_release(source, output, cmake, jobs, toolset=DEFAULT_TOOLSET, openblas_source=None):
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("Compiler sur Windows x64 avec Visual Studio 2022, le SDK Windows et CMake.")
    if digest(source) != SOURCE_SHA256:
        raise ValueError("Empreinte incorrecte pour l’archive officielle de sources Whisper.")
    if openblas_source and (toolset != "clangcl" or digest(openblas_source) != OPENBLAS_SOURCE_SHA256):
        raise ValueError("OpenBLAS exige ClangCL et l’empreinte de l’archive officielle.")
    if output.exists():
        raise ValueError(f"La sortie existe déjà : {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nv-wcpp-") as temp, \
            tempfile.TemporaryDirectory(prefix="nv-whisper-stage-", dir=output.parent) as staging:
        temp, staging = Path(temp), Path(staging) / "release"
        with tarfile.open(source, "r:gz") as archive:
            archive.extractall(temp, filter="data")
        tree = temp / SOURCE_ROOT
        changed = edit_cmake(tree / "CMakeLists.txt")
        env = os.environ.copy()
        # These can inject compiler switches or change the chosen SDK/libraries.
        for var in ("CL", "_CL_", "CFLAGS", "CXXFLAGS", "ASMFLAGS", "CPPFLAGS", "LINK", "_LINK_", "LDFLAGS",
                    "CMAKE_TOOLCHAIN_FILE", "CC", "CXX", "ASM"):
            env.pop(var, None)
        (staging / "include").mkdir(parents=True)
        (staging / "lib").mkdir()
        variants = {}
        compilers = None
        cmake_toolset = TOOLSETS[toolset][0]
        blas, baseline_compiler = None, None
        for variant, path in VARIANT_DLL.items():
            build = temp / ("build-" + variant)
            toolchain_query(build)
            use_blas = bool(openblas_source and variant == "avx2")
            options = variant_options(toolset, variant, use_blas)
            flags = [f"-D{k}={v}" for k, v in options.items()]
            if use_blas:
                blas_build, blas = build_openblas(openblas_source, temp, staging, cmake, jobs, env, baseline_compiler)
                edit_blas_cmake(tree / OPENBLAS_PATCH["path"])
                flags.append(f"-DNOTEVIVE_OPENBLAS_ROOT={blas_build.as_posix()}")
            subprocess.run([cmake, "-S", tree, "-B", build, "-G", GENERATOR, "-A", "x64",
                            "-T", cmake_toolset, *flags], check=True, env=env)
            selected = verify_compilers(build, toolset)
            if variant == "baseline" and openblas_source:
                baseline_compiler = read_toolchains(build)["C"]
            if compilers is not None and compilers != selected:
                raise ValueError("Les deux variantes doivent utiliser la même version du compilateur.")
            compilers = selected
            verify_projects(build, variant, toolset, use_blas)
            subprocess.run([cmake, "--build", build, "--config", CONFIG, "--parallel", str(jobs),
                            "--target", "whisper"], check=True, env=env)
            dll = staging / "bin" / path
            dll.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(find_unique(build, dll.name), dll)
            if variant == "baseline":
                shutil.copyfile(find_unique(build, "whisper.lib"), staging / "lib/whisper.lib")
            imports = verify_runtime(dll)
            check_load = variant == "baseline" or available_avx2()
            if check_load:
                verify_loaded_version(dll)
            variants[variant] = {"dll": f"bin/{path}", "cmake_options": options, "imports": imports,
                                 "native_load_checked": check_load}
        for file, rel in HEADERS.items():
            shutil.copyfile(tree / rel, staging / "include" / file)
        shutil.copyfile(tree / "LICENSE", staging / "LICENSE")
        log = {"schema": 4 if blas else 3, "version": VERSION,
               "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
               "patch": changed, "generator": GENERATOR, "toolset": toolset, "cmake_toolset": cmake_toolset,
               "compilers": compilers, "config": CONFIG,
               "cmake_version": subprocess.check_output([cmake, "--version"], text=True).splitlines()[0],
               "variants": variants, "static_crt_projects": list(STATIC_CRT_PROJECTS),
               "artifacts": artifact_spec(staging, bool(blas))}
        if blas:
            log["openblas"] = blas
        (staging / "attestation.json").write_text(json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_staged(staging)
        staging.rename(output)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--openblas-source", type=Path,
                        help="Archive officielle d’OpenBLAS 0.3.34 pour la variante AVX2 expérimentale.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--jobs", type=int, default=2, choices=range(1, 9), metavar="1..8")
    parser.add_argument("--toolset", choices=TOOLSETS, default=DEFAULT_TOOLSET,
                        help="Compilateur C/C++ de Whisper (défaut : clangcl ; référence : msvc).")
    args = parser.parse_args()
    build_release(args.source.resolve(), args.output.resolve(), args.cmake, args.jobs, args.toolset,
                  args.openblas_source.resolve() if args.openblas_source else None)


if __name__ == "__main__":
    main()
