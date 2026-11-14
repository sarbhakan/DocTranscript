"""Seal or verify local P0 model packs; no download or dependency required."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


PACK_FILES = {
    "sherpa": {"encoder", "decoder", "joiner", "tokens"},
    "sherpa-final": {"encoder", "decoder", "joiner", "tokens"},
    "whisper": {"model"},
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_pack(root):
    root = root.resolve(strict=True)
    config_path = root / "pack.json"
    if config_path.is_symlink():
        raise ValueError("pack.json doit être local")
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    mode = cfg["adapter"]
    if "final_only" in cfg and (mode != "whisper" or type(cfg["final_only"]) is not bool):
        raise ValueError("final_only doit être un booléen dans un pack Whisper")
    if cfg.get("final_only") and ("step_ms" in cfg or "window_ms" in cfg):
        raise ValueError("le décodage Whisper final exclut les réglages de fenêtres")
    if mode not in PACK_FILES:
        raise ValueError("type de pack inconnu")
    file_keys = set(cfg["files"])
    expected = PACK_FILES[mode]
    if cfg.get("final_only") and "vad_model" in file_keys:
        expected = expected | {"vad_model"}
    if file_keys != expected:
        raise ValueError("fichiers attendus différents du type de pack")
    paths = {}
    for key, name in cfg["files"].items():
        rel = Path(name)
        if rel.is_absolute() or rel.drive or ".." in rel.parts or not rel.parts:
            raise ValueError("chemin de modèle non relatif au pack")
        path = (root / rel).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("fichier absent ou hors du pack")
        paths[key] = path
    return root, cfg, paths


def pack_state(root, paths, with_hash):
    return {
        "schema": 1,
        "config_sha256": sha(root / "pack.json"),
        "files": {
            key: {"bytes": path.stat().st_size, **({"sha256": sha(path)} if with_hash else {})}
            for key, path in paths.items()
        },
    }


def read_sealed(root, verify=False):
    root, cfg, paths = read_pack(root)
    manifest = root / "pack.sha256.json"
    if manifest.is_symlink():
        raise ValueError("pack.sha256.json doit être local")
    state = json.loads(manifest.read_text(encoding="utf-8-sig"))
    expected = pack_state(root, paths, verify)
    if not verify:
        for key, info in expected["files"].items():
            digest = state["files"][key]["sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("empreinte invalide")
            info["sha256"] = digest
    if expected != state:
        raise ValueError("pack différent du manifeste")
    return cfg, paths, sha(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seal", "verify"])
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "seal":
            root, _, paths = read_pack(args.pack)
            state = pack_state(root, paths, True)
            with (root / "pack.sha256.json").open("x", encoding="utf-8", newline="\n") as out:
                out.write(json.dumps(state, sort_keys=True, indent=2) + "\n")
        _, _, digest = read_sealed(args.pack, verify=True)
        print(f"Pack vérifié, SHA-256 du manifeste : {digest}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Pack refusé : {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
