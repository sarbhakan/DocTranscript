"""Fetch/verify immutable public Whisper weights. No audio or labels are sent."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

LOCK_PATH = Path(__file__).with_name("model.lock.json")
REPO_ROOT = Path(__file__).resolve().parents[2]


def validate_file(path: Path, spec: dict) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != spec["bytes"]:
        raise ValueError(f"Fichier absent, lié ou taille incorrecte : {spec['path']}")
    sha = hashlib.sha256()
    git = hashlib.sha1(f"blob {spec['bytes']}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            sha.update(block)
            git.update(block)
    if "sha256" in spec:
        matches = sha.hexdigest() == spec["sha256"]
    else:
        matches = git.hexdigest() == spec["git_blob_sha1"]
    if not matches:
        raise ValueError(f"Empreinte source incorrecte : {spec['path']}")
    return sha.hexdigest()


def verify_model(directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Le répertoire modèle ne doit pas être un lien")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock["repo"] != "openai/whisper-large-v3-turbo" or lock["revision"] != "41f01f3fe87f28c78e2fbf8b568835947dd65ed9":
        raise ValueError("Révision de modèle inattendue")
    allowed = {spec["path"] for spec in lock["files"]} | {"provenance.json"}
    if any(path.name not in allowed or path.is_symlink() or not path.is_file()
           for path in directory.iterdir()):
        raise ValueError("Fichier supplémentaire ou lié dans le modèle verrouillé")
    result = {}
    for spec in lock["files"]:
        if Path(spec["path"]).name != spec["path"]:
            raise ValueError("Chemin modèle non autorisé")
        result[spec["path"]] = validate_file(directory / spec["path"], spec)
    return {"repo": lock["repo"], "revision": lock["revision"], "sha256": result}


def fetch(directory: Path) -> dict:
    directory = directory.resolve()
    if directory.is_relative_to(REPO_ROOT):
        raise ValueError("Choisir un dossier local hors dépôt et hors synchronisation")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    needed = sum(row["bytes"] for row in lock["files"]) + 1024 ** 3
    if shutil.disk_usage(directory.parent).free < needed:
        raise ValueError("Espace insuffisant pour les poids et la marge de travail")
    directory.mkdir()  # never replace an earlier download
    for spec in lock["files"]:
        name = spec["path"]
        if Path(name).name != name:
            raise ValueError("Chemin modèle non autorisé")
        part = directory / (name + ".part")
        url = f"https://huggingface.co/{lock['repo']}/resolve/{lock['revision']}/{name}"
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                        "--proto", "=https", "--proto-redir", "=https", "--retry", "2",
                        "--connect-timeout", "20", "--max-time", "1800",
                        "--output", str(part), url], check=True)
        validate_file(part, spec)
        part.rename(directory / name)
        print(f"Vérifié : {name}", flush=True)
    result = verify_model(directory)
    (directory / "provenance.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "verify"))
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    result = fetch(args.model) if args.action == "fetch" else verify_model(args.model)
    print(json.dumps({"revision": result["revision"], "verified_files": len(result["sha256"]) }))


if __name__ == "__main__":
    main()
