"""Compile and run isolated Windows tests; no real microphone or user library."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import wave
from app.build_windows import WIN, ROOT, CXX_FLAGS, LOCK, run
from app.build_whisper_windows import GENERATOR
from app.fixture_checks import check_fixture

TOOLSET = 'v143,host=x64'  # Test compiler is independent from the decoder compiler.


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
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--engine-only', action='store_true', help='Test only the real decoder from --package.')
    scope.add_argument('--external-only', action='store_true',
                       help='Build and run only the native external-target probe.')
    scope.add_argument('--without-external', action='store_true',
                       help='Build and run the tests other than the interactive external-target probe.')
    parser.add_argument('--include-unsupported-baseline', action='store_true',
                        help='Diagnostic explicite SSE2, hors du minimum CPU du produit (peut échouer).')
    parser.add_argument('--build-cache', type=Path)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    if args.engine_only and not args.package:
        parser.error('--engine-only requiert --package.')
    if args.external_only and (args.package or args.include_unsupported_baseline):
        parser.error('--external-only ne prend ni --package ni --include-unsupported-baseline.')
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
    regressions = {}
    supervisor = None
    if not args.engine_only and not args.external_only:
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
    if not args.engine_only and not args.without_external:
        targets.append(target('external-user32-fixture.exe', [WIN / 'external_user32_fixture.cpp'],
                              libraries=['user32']))
        external_probe = target('external-target-test.exe', [WIN / 'external_target.cpp', WIN / 'external_target_test.cpp'],
                                libraries=['user32', 'advapi32', 'ole32', 'oleaut32', 'uuid',
                                           'bcrypt', 'netapi32', 'userenv'], wide_main=True)
        targets.append(external_probe)
        commands.append([external_probe[0]])
    if args.package:
        runtime = args.package.resolve() / 'runtime'
        real = out / 'production'
        headers(real, runtime / 'NoteVive-ASR.exe')
        # Runtime fingerprints used by both the production worker and the supervisor.
        generated = args.package.resolve() / 'Build/runtime_integrity.h'
        (real / generated.name).write_bytes(generated.read_bytes())
        smoke_target = target('engine-smoke.exe', [WIN / 'engine.cpp', WIN / 'integrity.cpp', WIN / 'engine_smoke.cpp'],
                              defines=['NOTEVIVE_ENGINE_DIAGNOSTICS'], includes=[real], libraries=['bcrypt'], wide_main=True)
        targets.append(smoke_target)
        smoke = smoke_target[0]
        silence = out / 'silence.wav'
        with wave.open(str(silence), 'wb') as file:
            file.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            file.writeframes(bytes(16000 * 2 * 8))
        commands.append([smoke, runtime, silence, '--silence'])
        # Human French simulated prescription, redistributable under CC BY 4.0.
        # The reference and provenance live with the fixture; no patient data.
        fixture_dir = ROOT / 'p0/fixtures'
        spec = json.loads((fixture_dir / 'fixture.json').read_text(encoding='utf-8'))
        packed = (fixture_dir / 'px-826.wav.gz').read_bytes()
        if hashlib.sha256(packed).hexdigest() != spec['gzip_sha256']:
            raise ValueError('Fixture française altérée.')
        audio = gzip.decompress(packed)
        if len(audio) != spec['wav_bytes'] or hashlib.sha256(audio).hexdigest() != spec['wav_sha256']:
            raise ValueError('WAV français altéré.')
        speech = out / 'french-prescription.wav'
        speech.write_bytes(audio)
        regressions[speech] = {**spec, 'id': 'px-826', 'terms': ['prozac'],
                               'critical': {'dose': ['prozac 20 milligrammes']}}
        commands.append([smoke, runtime, speech, '--regression', out / 'px-826.txt'])
        for case in json.loads((fixture_dir / 'regressions.json').read_text(encoding='utf-8'))['cases']:
            packed = (fixture_dir / case['filename']).read_bytes()
            if hashlib.sha256(packed).hexdigest() != case['gzip_sha256']:
                raise ValueError('Fixture de régression altérée.')
            audio = gzip.decompress(packed)
            if len(audio) != case['wav_bytes'] or hashlib.sha256(audio).hexdigest() != case['wav_sha256']:
                raise ValueError('WAV de régression altéré.')
            wave_path = out / (case['id'] + '.wav')
            wave_path.write_bytes(audio)
            regressions[wave_path] = case
            commands.append([smoke, runtime, wave_path, '--regression', out / (case['id'] + '.txt')])
    build('tests', targets)
    (out / 'commands.json').write_text(json.dumps([[str(v) for v in cmd] for cmd in commands], indent=2), encoding='utf-8')
    if args.compile_only:
        print(f'Tests compilés, non exécutés : {out}')
        return
    timings = []
    def execute(cmd, env, is_smoke):
        regression = is_smoke and len(cmd) == 5 and cmd[3] == '--regression' and cmd[2] in regressions
        label = regressions[cmd[2]]['id'] if regression else ('speech-fr' if is_smoke and cmd[-1] == '--speech' else ('silence' if is_smoke else cmd[0].name))
        requested_cpu = env.get('NOTEVIVE_CPU', 'auto')
        print(f'Test {label}, requested_cpu={requested_cpu}', flush=True)
        start = time.perf_counter()
        measured = cmd
        if is_smoke:
            resources = out / f'memory-{label}-{requested_cpu}.json'
            measured = [sys.executable, '-m', 'p0.windows.measure', '--output', resources, '--', *cmd]
        is_external = cmd[0].name == 'external-target-test.exe'
        if is_external:
            measured = [
                Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe',
                '-NoProfile', '-NonInteractive', '-File', WIN / 'external_interactive_test.ps1',
                '-ProbeExe', cmd[0], '-Case', 'Native',
            ]
        completed = subprocess.run(measured, check=False, env=env, timeout=125 if is_external else (120 if is_smoke else 30))
        result = {'test': label, 'requested_cpu': requested_cpu, 'elapsed_seconds': round(time.perf_counter() - start, 3)}
        if is_smoke:
            with wave.open(str(cmd[2]), 'rb') as audio:
                result['audio_seconds'] = audio.getnframes() / audio.getframerate()
            result['elapsed_audio_ratio'] = round(result['elapsed_seconds'] / result['audio_seconds'], 3)
            if resources.exists():
                sampled = json.loads(resources.read_text(encoding='utf-8'))
                result['resources'] = {key: sampled[key] for key in (
                    'interval_ms_requested', 'peak_sampled_private_bytes', 'observed_cpu_seconds',
                    'observed_mean_cpu_core_equivalents', 'snapshot_errors', 'partial_samples', 'exit_code')}
                result['resources']['parent_and_worker_observed'] = any(
                    sample['processes_seen'] >= 2 and sample['processes_read'] >= 2
                    for sample in sampled['samples'])
        critical_ok = True
        if regression and completed.returncode == 0:
            case = regressions[cmd[2]]
            recognized = cmd[-1].read_text(encoding='utf-16')
            result['fixture_checks'] = check_fixture(case, recognized)
            critical_ok = result['fixture_checks']['passed']
        timings.append(result)
        print(json.dumps(result), flush=True)
        (out / 'timings.json').write_text(json.dumps(timings, indent=2) + '\n', encoding='utf-8')
        completed.check_returncode()
        if is_smoke and not result.get('resources', {}).get('parent_and_worker_observed'):
            raise ValueError('La mesure des ressources n’a pas observé le moteur enfant.')
        if not critical_ok:
            raise ValueError(f'Régression critique dans {label}; consulter le rapport local.')

    baseline_commands = []
    failures = []
    for cmd in commands:
        env = os.environ.copy()
        is_smoke = cmd[0].name == 'engine-smoke.exe'
        if cmd[0] == supervisor:
            env['NOTEVIVE_CPU'] = 'baseline'
        elif is_smoke:
            env.pop('NOTEVIVE_CPU', None)
            env['NOTEVIVE_ASR_BENCH_METRICS'] = '1'
        try:
            execute(cmd, env, is_smoke)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
            failures.append(type(error).__name__)
            print(f'Échec du contrôle : {type(error).__name__}', flush=True)
        if args.include_unsupported_baseline and is_smoke and cmd[2] not in regressions:
            baseline_commands.append(cmd)
    # Explicit engineering diagnostic, outside the product CPU requirement.
    # If requested, any failure still fails this invocation. No timeouts change.
    if args.include_unsupported_baseline and args.package:
        baseline_commands.append([smoke, runtime, speech, '--speech'])
    for cmd in baseline_commands:
        env = {**os.environ, 'NOTEVIVE_CPU': 'baseline', 'NOTEVIVE_ASR_BENCH_METRICS': '1'}
        try:
            execute(cmd, env, True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
            failures.append(type(error).__name__)
            print(f'Échec du contrôle SSE2 : {type(error).__name__}', flush=True)
    (out / 'timings.json').write_text(json.dumps(timings, indent=2) + '\n', encoding='utf-8')
    if failures:
        raise SystemExit(f'{len(failures)} contrôle(s) Windows en échec.')
    print('Tests Windows isolés : OK')


if __name__ == '__main__':
    main()
