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


def headers(directory, worker):
    spec = LOCK['catalogue']
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'catalogue_integrity.h').write_text(
        f'#define NOTEVIVE_CATALOGUE_SIZE {spec["bytes"]}\n#define NOTEVIVE_CATALOGUE_SHA256 "{spec["hash"]}"\n')
    (directory / 'worker_integrity.h').write_text(
        f'#define NOTEVIVE_WORKER_SIZE {worker.stat().st_size}\n#define NOTEVIVE_WORKER_SHA256 "{hashlib.sha256(worker.read_bytes()).hexdigest()}"\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--build-cache', type=Path, default=ROOT / 'app/private/build-cache')
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cache = args.build_cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    zig = args.zig.resolve()
    def compile(name, sources, extra=()):
        path = out / name
        run(zig, ['c++', *CXX_FLAGS, '-UNDEBUG', '-Werror', *sources, *extra, '-o', path], cache)
        return path
    model = compile('notes-model-test.exe', [WIN / 'notes_model_test.cpp'])
    protocol = compile('worker-protocol-test.exe', [WIN / 'worker_protocol_test.cpp'])
    pauses = compile('pause-state-test.exe', [ROOT / 'app/native/PauseStateTest.cpp'])
    notes = compile('notes-test.exe', [WIN / 'notes.cpp', WIN / 'notes_test.cpp'],
                    ['-DNOTEVIVE_NOTES_TEST', '-lcrypt32', '-lole32', '-lshell32', '-luuid'])
    fixture = out / 'fixture'
    fixture.mkdir()
    child = compile('fixture/NoteVive-ASR.exe', [WIN / 'worker_fixture.cpp'], ['-municode'])
    headers(fixture, child)
    (fixture / 'runtime_integrity.h').write_text(
        'constexpr Expected kEngine[] = {{L"NoteVive-ASR.exe", ' + str(child.stat().st_size) + ', "' +
        hashlib.sha256(child.read_bytes()).hexdigest() + '"}};\n')
    supervisor = compile('supervisor-test.exe', [WIN / 'engine.cpp', WIN / 'integrity.cpp', WIN / 'engine_supervisor_test.cpp'],
                         ['-municode', '-DNOTEVIVE_SUPERVISOR_TEST', '-I', fixture, '-lbcrypt'])
    commands = [[model], [protocol], [pauses], [notes], [supervisor, fixture]]
    if args.package:
        runtime = args.package.resolve() / 'runtime'
        real = out / 'production'
        headers(real, runtime / 'NoteVive-ASR.exe')
        # Runtime fingerprints used by both the production worker and the supervisor.
        generated = args.package.resolve() / 'Build/runtime_integrity.h'
        if generated.exists():
            (real / generated.name).write_bytes(generated.read_bytes())
        smoke = compile('engine-smoke.exe', [WIN / 'engine.cpp', WIN / 'integrity.cpp', WIN / 'engine_smoke.cpp'],
                        ['-municode', '-I', real, '-lbcrypt'])
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
    (out / 'commands.json').write_text(json.dumps([[str(v) for v in cmd] for cmd in commands], indent=2))
    if args.compile_only:
        print(f'Tests compilés, non exécutés : {out}')
        return
    if platform.system() != 'Windows':
        parser.error('Exécution native Windows requise ; utiliser --compile-only sur Mac.')
    for cmd in commands:
        env = os.environ.copy()
        if cmd[0] == supervisor:
            env['NOTEVIVE_CPU'] = 'baseline'
        subprocess.run(cmd, check=True, env=env, timeout=120 if cmd[0].name == 'engine-smoke.exe' else 30)
        if cmd[0].name == 'engine-smoke.exe':
            env['NOTEVIVE_CPU'] = 'baseline'
            subprocess.run(cmd, check=True, env=env, timeout=120)
    print('Tests Windows isolés : OK')


if __name__ == '__main__':
    main()
