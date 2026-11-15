"""Fetch pinned build inputs on a connected preparation machine, never at app startup."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

if __package__:
    from .catalogue_package import extend, validate
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.catalogue_package import extend, validate

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'app/inputs.lock.json').read_text(encoding='utf-8'))
CATALOGUE_ARCHIVE = {
    'url': 'https://github.com/sarbhakan/DocTranscript/releases/download/v0.1.0-essai/NoteVive-Windows-x64-Essai.zip',
    'hash': '43711335e4ec8aaf38d2179615de92de2d086943c1de4abc6db29edd33d59c28',
}
BASE_CATALOGUE_SHA256 = 'd23ba8cb29b02e3f00d769ed670ae3c3b8cd4ad4a6c9cbdbdf4ab279787f4ccc'
PUBLIC_MANIFEST = ROOT / 'lexique/manifest-essai-041.json'


def digest(path, spec):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, spec.get('algorithm', 'sha256')).hexdigest()


def fetch(path, spec):
    if path.exists():
        if digest(path, spec) != spec['hash']:
            raise ValueError(f'Empreinte inattendue pour {path}; conserver ce fichier et choisir une nouvelle destination.')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='notevive-download-', dir=path.parent) as directory:
        temporary = Path(directory) / 'download'
        # curl uses the Mac system trust store. Do not disable TLS verification.
        if platform.system() == 'Darwin':
            subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '2', '--output', str(temporary), spec['url']], check=True)
        else:
            request = urllib.request.Request(spec['url'], headers={'User-Agent': 'NoteVive-offline-builder'})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open('xb') as stream:
                shutil.copyfileobj(response, stream)
        if digest(temporary, spec) != spec['hash']:
            raise ValueError(f'Empreinte du téléchargement incorrecte : {path.name}')
        temporary.rename(path)
    print(f'Vérifié : {path.name}', flush=True)


def prepare_catalogue(destination, downloads):
    if destination.exists() or destination.is_symlink():
        validate(destination, PUBLIC_MANIFEST, LOCK['catalogue'])
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.catalogue-041-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        base = stage / 'base.sqlite'
        existing_base = ROOT / 'lexique/private/catalogue-essai-public.sqlite'
        if existing_base.is_file() and digest(existing_base, {}) == BASE_CATALOGUE_SHA256:
            shutil.copyfile(existing_base, base)
        else:
            archive = downloads / 'catalogue-source-v0.1.0.zip'
            fetch(archive, CATALOGUE_ARCHIVE)
            with zipfile.ZipFile(archive) as source:
                data = source.read('NoteVive/runtime/catalogue.sqlite')
            if hashlib.sha256(data).hexdigest() != BASE_CATALOGUE_SHA256:
                raise ValueError('Catalogue de base altéré.')
            base.write_bytes(data)
        additions = stage / 'additions.sqlite'
        subprocess.run([sys.executable, '-m', 'lexique.prepare_041', '--fetch',
                        '--downloads', str(downloads / 'lexique-041'), '--output', str(additions)],
                       check=True, cwd=ROOT)
        domains = json.loads((ROOT / 'lexique/orphanet-domains.lock.json').read_text(encoding='utf-8'))
        orphanet = downloads / 'lexique-041' / domains['file']
        fetch(orphanet, {'url': domains['url'], 'hash': domains['sha256']})
        mapping_path = stage / 'orphanet-domains.json'
        subprocess.run([sys.executable, '-m', 'lexique.orphanet_domains', '--archive', str(orphanet),
                        '--output', str(mapping_path)], check=True, cwd=ROOT)
        mapping_bytes = mapping_path.read_bytes()
        if hashlib.sha256(mapping_bytes).hexdigest() != LOCK['catalogue']['domain_mapping_sha256']:
            raise ValueError('Affectations Orphanet différentes du verrou public.')
        complete = stage / 'complete.sqlite'
        extend(base, additions, complete, json.loads(mapping_bytes))
        validate(complete, PUBLIC_MANIFEST, LOCK['catalogue'])
        os.link(complete, destination)
    print('Catalogue enrichi vérifié : sources, domaines et index de recherche.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, default=ROOT / 'app/private/downloads')
    parser.add_argument('--catalogue', type=Path, default=ROOT / 'lexique/private/catalogue-essai-041.sqlite')
    parser.add_argument('--toolchain', type=Path, default=ROOT / 'app/private/toolchain')
    args = parser.parse_args()
    for name, spec in LOCK['downloads'].items():
        fetch(args.downloads / name, spec)
    prepare_catalogue(args.catalogue.resolve(), args.downloads.resolve())
    host = ('windows-x64' if platform.system() == 'Windows' and platform.machine().lower() in {'amd64','x86_64'}
            else 'macos-arm64' if platform.system() == 'Darwin' and platform.machine() == 'arm64' else None)
    if host is None:
        raise ValueError('Préparation automatique prévue sur Windows x64 ou Mac Apple Silicon.')
    spec = LOCK['zig'][host]
    archive = args.downloads / Path(spec['url']).name
    fetch(archive, spec)
    folder = ('zig-x86_64-windows-' if host == 'windows-x64' else 'zig-aarch64-macos-') + LOCK['zig']['version']
    executable = args.toolchain / folder / ('zig.exe' if host == 'windows-x64' else 'zig')
    if not executable.exists():
        args.toolchain.mkdir(parents=True, exist_ok=True)
        if host == 'windows-x64':
            with zipfile.ZipFile(archive) as source:
                source.extractall(args.toolchain)
        else:
            with tarfile.open(archive) as source:
                source.extractall(args.toolchain, filter='data')
    print(f'Prêt pour compilation hors ligne. Zig : {executable}')


if __name__ == '__main__':
    main()
