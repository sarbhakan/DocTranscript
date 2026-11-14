"""Compile and run isolated Windows tests; no real microphone or user library."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import wave
from app.build_windows import WIN, ROOT, CXX_FLAGS, LOCK, run
from app.build_whisper_windows import GENERATOR, TOOLSET


def headers(directory, worker):
    spec = LOCK['catalogue']
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'catalogue_integrity.h').write_text(
        f'#define NOTEVIVE_CATALOGUE_SIZE {spec["bytes"]}\n#define NOTEVIVE_CATALOGUE_SHA256 "{spec["hash"]}"\n')
    (directory / 'worker_integrity.h').write_text(
        f'#define NOTEVIVE_WORKER_SIZE {worker.stat().st_size}\n#define NOTEVIVE_WORKER_SHA256 "{hashlib.sha256(worker.read_bytes()).hexdigest()}"\n')


def target_name(path):
    prefix = 'fixture_' if path.parent.name == 'fixture' else 'test_'
    return prefix + path.stem.replace('-', '_')


def build_zig(out, zig, cache, targets):
    for path, sources, defines, includes, libraries, wide_main in targets:
        objects = out / 'objects' / target_name(path)
        objects.mkdir(parents=True)
        definitions = [f'-D{value}' for value in defines]
        include_options = [value for directory in includes for value in ('-I', directory)]
        built = []
        # Preserve the serial, separate compile/link steps for Zig cross-builds.
        for index, source in enumerate(sources):
            obj = objects / f'{index}.obj'
            run(zig, ['c++', *CXX_FLAGS, '-UNDEBUG', '-Werror', *definitions, *include_options,
                      '-c', source, '-o', obj], cache)
            built.append(obj)
        link_options = [f'-l{library}' for library in libraries]
        if wide_main:
            link_options.append('-municode')
        run(zig, ['c++', *CXX_FLAGS, *built, *link_options, '-o', path], cache)


def cmake_path(path):
    # Bracket arguments preserve whitespace and avoid interpretation of strings
    # that are valid in a Windows directory name. Choose a delimiter not present.
    value = path.as_posix()
    delimiter = '='
    while f']{delimiter}]' in value:
        delimiter += '='
    return f'[{delimiter}[{value}]{delimiter}]'


def msvc_project(targets):
    lines = [
        'cmake_minimum_required(VERSION 3.21)',
        'project(NoteViveWindowsTests LANGUAGES CXX)',
        'if(NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)',
        '  message(FATAL_ERROR "NoteVive tests require MSVC x64")',
        'endif()',
        'set(CMAKE_CXX_STANDARD 17)',
        'set(CMAKE_CXX_STANDARD_REQUIRED ON)',
        'set(CMAKE_CXX_EXTENSIONS OFF)',
        'set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")',
        # Keep optimized tests while avoiding a conflicting Release macro.
        'string(REGEX REPLACE "(^| )[/-]DNDEBUG( |$)" " " CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE}")',
    ]
    for path, sources, defines, includes, libraries, _ in targets:
        target = target_name(path)
        lines.extend([
            f"add_executable({target} {' '.join(cmake_path(source) for source in sources)})",
            # With the multi-config VS generator, let MSVC use main/wmain for
            # this console target; no hand-written CRT entry point is needed.
            f'target_compile_options({target} PRIVATE /utf-8 /UNDEBUG /W3)',
            f"target_compile_definitions({target} PRIVATE UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN {' '.join(defines)})",
            f'set_target_properties({target} PROPERTIES',
            f'  RUNTIME_OUTPUT_DIRECTORY_RELEASE {cmake_path(path.parent)}',
            f'  OUTPUT_NAME "{path.stem}")',
        ])
        if includes:
            lines.append(f"target_include_directories({target} PRIVATE {' '.join(cmake_path(directory) for directory in includes)})")
        if libraries:
            lines.append(f"target_link_libraries({target} PRIVATE {' '.join(libraries)})")
    return '\n'.join(lines) + '\n'


def build_msvc(out, cmake, phase, targets):
    source = out / 'msvc' / phase
    source.mkdir(parents=True)
    (source / 'CMakeLists.txt').write_text(msvc_project(targets), encoding='utf-8')
    generated = source / 'generated'
    env = os.environ.copy()
    for variable in ('CL', '_CL_', 'CFLAGS', 'CXXFLAGS', 'LINK', '_LINK_', 'LDFLAGS', 'CMAKE_TOOLCHAIN_FILE'):
        env.pop(variable, None)
    subprocess.run([cmake, '-S', source, '-B', generated, '-G', GENERATOR, '-A', 'x64',
                    '-T', TOOLSET], check=True, env=env)
    subprocess.run([cmake, '--build', generated, '--config', 'Release', '--parallel', '2'], check=True, env=env)
    for path, _, _, _, _, _ in targets:
        if not path.is_file():
            raise ValueError(f'Le compilateur MSVC n’a pas produit le test attendu : {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', choices=('zig', 'msvc'), default='zig')
    parser.add_argument('--zig', type=Path)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--engine-only', action='store_true', help='Test only the real decoder from --package.')
    parser.add_argument('--build-cache', type=Path)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    if args.engine_only and not args.package:
        parser.error('--engine-only requiert --package.')
    native_windows = platform.system() == 'Windows'
    if args.compiler == 'zig' and not args.zig:
        parser.error('--zig est requis avec --compiler zig.')
    if args.compiler == 'msvc' and (not native_windows or platform.machine().lower() not in {'amd64', 'x86_64'}):
        parser.error('--compiler msvc nécessite Windows x64 et Visual Studio 2022.')
    if not native_windows and not args.compile_only:
        parser.error('Exécution native Windows requise ; utiliser --compile-only sur Mac.')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # A test run owns its cache: production generated headers live in a
    # temporary directory which no longer exists once its ZIP is complete.
    cache = args.build_cache.resolve() if args.build_cache else out / 'cache'
    if args.compiler == 'zig':
        cache.mkdir(parents=True, exist_ok=True)

    def build(phase, targets):
        if args.compiler == 'msvc':
            build_msvc(out, args.cmake, phase, targets)
        else:
            build_zig(out, args.zig.resolve(), cache, targets)

    def target(name, sources, defines=(), includes=(), libraries=(), *, wide_main=False):
        for source in sources:
            if not source.is_file():
                raise FileNotFoundError(f'Source de test absente du checkout : {source}')
        return out / name, sources, defines, includes, libraries, wide_main

    targets, commands = [], []
    supervisor = None
    if not args.engine_only:
        fixture = out / 'fixture'
        fixture.mkdir()
        child_target = target('fixture/NoteVive-ASR.exe', [WIN / 'worker_fixture.cpp'], wide_main=True)
        build('fixture', [child_target])
        child = child_target[0]
        headers(fixture, child)
        (fixture / 'runtime_integrity.h').write_text(
            'constexpr Expected kEngine[] = {{L"NoteVive-ASR.exe", ' + str(child.stat().st_size) + ', "' +
            hashlib.sha256(child.read_bytes()).hexdigest() + '"}};\n')
        targets = [
            target('notes-model-test.exe', [WIN / 'notes_model_test.cpp']),
            target('worker-protocol-test.exe', [WIN / 'worker_protocol_test.cpp']),
            target('pause-state-test.exe', [ROOT / 'app/native/PauseStateTest.cpp']),
            target('notes-test.exe', [WIN / 'notes.cpp', WIN / 'notes_test.cpp'],
                   defines=['NOTEVIVE_NOTES_TEST'], libraries=['crypt32', 'ole32', 'shell32', 'uuid']),
            target('supervisor-test.exe', [WIN / 'engine.cpp', WIN / 'integrity.cpp', WIN / 'engine_supervisor_test.cpp'],
                   defines=['NOTEVIVE_SUPERVISOR_TEST'], includes=[fixture], libraries=['bcrypt'], wide_main=True),
        ]
        supervisor = targets[-1][0]
        commands = [[test[0]] for test in targets[:-1]] + [[supervisor, fixture]]
    if args.package:
        runtime = args.package.resolve() / 'runtime'
        real = out / 'production'
        headers(real, runtime / 'NoteVive-ASR.exe')
        # Runtime fingerprints used by both the production worker and the supervisor.
        generated = args.package.resolve() / 'Build/runtime_integrity.h'
        (real / generated.name).write_bytes(generated.read_bytes())
        smoke_target = target('engine-smoke.exe', [WIN / 'engine.cpp', WIN / 'integrity.cpp', WIN / 'engine_smoke.cpp'],
                              includes=[real], libraries=['bcrypt'], wide_main=True)
        targets.append(smoke_target)
        smoke = smoke_target[0]
        silence = out / 'silence.wav'
        with wave.open(str(silence), 'wb') as file:
            file.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            file.writeframes(bytes(16000 * 2 * 8))
        commands.append([smoke, runtime, silence, '--silence'])
        # Official upstream demonstration, included in the hash-pinned source
        # archive. A speech/nonempty lifecycle test, not French accuracy data.
        from app.build_whisper_windows import SOURCE_NAME, SOURCE_SHA256, SOURCE_ROOT
        source = ROOT / 'app/private/downloads' / SOURCE_NAME
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != SOURCE_SHA256:
                raise ValueError('Archive de test altérée.')
        speech = out / 'upstream-demo.wav'
        with tarfile.open(source) as archive:
            speech.write_bytes(archive.extractfile(SOURCE_ROOT + '/samples/jfk.wav').read())
        commands.append([smoke, runtime, speech, '--speech'])
    build('tests', targets)
    (out / 'commands.json').write_text(json.dumps([[str(v) for v in cmd] for cmd in commands], indent=2), encoding='utf-8')
    if args.compile_only:
        print(f'Tests compilés, non exécutés : {out}')
        return
    for cmd in commands:
        env = os.environ.copy()
        is_smoke = cmd[0].name == 'engine-smoke.exe'
        if cmd[0] == supervisor:
            env['NOTEVIVE_CPU'] = 'baseline'
        elif is_smoke:
            env.pop('NOTEVIVE_CPU', None)
        subprocess.run(cmd, check=True, env=env, timeout=120 if is_smoke else 30)
        if is_smoke:
            env['NOTEVIVE_CPU'] = 'baseline'
            subprocess.run(cmd, check=True, env=env, timeout=120)
    print('Tests Windows isolés : OK')


if __name__ == '__main__':
    main()
