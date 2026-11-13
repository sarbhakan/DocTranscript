"""Vérifie la cohérence d'un manifeste et, sur demande, des WAV et annotations."""

import argparse
import csv
import re
import sys
import wave
from collections import defaultdict
from pathlib import Path


ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
CASE_FIELDS = {"id", "partition", "kind", "reference"}
ATTR_FIELDS = {"case_id", "attribute_id", "category", "group_id", "reference_span", "expected"}
SPEECH_TIME = ("speech_start_ms", "speech_end_ms")


def load_csv(path, fields):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, strict=True)
        header = reader.fieldnames or []
        missing = fields - set(header)
        if missing:
            raise ValueError(f"{path.name} : colonnes manquantes : {', '.join(sorted(missing))}")
        if len(header) != len(set(header)):
            raise ValueError(f"{path.name} : colonne répétée")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path.name}:{reader.line_num} : nombre de colonnes invalide")
            rows.append(row)
    if not rows:
        raise ValueError(f"{path.name} : aucune ligne de données")
    return rows


def inspect_cases(rows, wav_dir, errors):
    cases = {}
    voices = defaultdict(set)
    for row in rows:
        cid = row["id"]
        if not ID.fullmatch(cid) or cid in cases:
            errors.append(f"{cid!r} : identifiant de cas invalide ou répété")
            continue
        cases[cid] = row
        partition, kind = row["partition"], row["kind"]
        if partition not in {"dev", "confirm"}:
            errors.append(f"{cid} : partition dev/confirm attendue")
        if kind not in {"speech", "noise", "silence"}:
            errors.append(f"{cid} : type speech/noise/silence attendu")
        if bool(row["reference"].strip()) != (kind == "speech"):
            errors.append(f"{cid} : référence présente uniquement pour la parole")

        voice = row.get("voice_id", "")
        if voice:
            if kind != "speech" or not ID.fullmatch(voice):
                errors.append(f"{cid} : identifiant de voix invalide ou présent sans parole")
            voices[voice].add(partition)
        elif wav_dir is not None and kind == "speech":
            errors.append(f"{cid} : identifiant de voix requis pour le banc enregistré")

        start, end = (row.get(field, "") for field in SPEECH_TIME)
        bounds = None
        if kind != "speech":
            if start or end:
                errors.append(f"{cid} : bornes de parole présentes sans parole")
        elif start or end or wav_dir is not None:
            if not all(re.fullmatch(r"[0-9]{1,9}", field) for field in (start, end)):
                errors.append(f"{cid} : début et fin de parole requis (ms entières)")
            elif int(start) >= int(end):
                errors.append(f"{cid} : le début de parole doit précéder la fin")
            else:
                bounds = int(start), int(end)

        if wav_dir is None:
            continue
        try:
            with wave.open(str(wav_dir / f"{cid}.wav"), "rb") as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
                    1, 2, 16_000, "NONE"
                ):
                    errors.append(f"{cid} : WAV PCM signé 16 bits, mono, 16 kHz requis")
                    continue
                frames = wav.getnframes()
                if not frames:
                    errors.append(f"{cid} : WAV vide")
                    continue
                if bounds is not None and bounds[1] * 16 > frames:
                    errors.append(f"{cid} : fin de parole après la durée du WAV")
                remaining = frames
                nonzero = False
                while remaining:
                    count = min(remaining, 16_000)
                    chunk = wav.readframes(count)
                    if len(chunk) != count * 2:
                        errors.append(f"{cid} : données WAV tronquées")
                        break
                    remaining -= count
                    nonzero |= any(chunk)
                if kind == "silence" and nonzero:
                    errors.append(f"{cid} : le contrôle silence doit être nul numériquement")
                if kind in {"noise", "speech"} and not nonzero:
                    errors.append(f"{cid} : fichier silencieux étiqueté {kind}")
        except (OSError, EOFError, wave.Error):
            errors.append(f"{cid} : WAV absent ou illisible")
    for voice, partitions in voices.items():
        if len(partitions) > 1:
            errors.append(f"{voice} : même voix déclarée en développement et en confirmation")
    return cases


def inspect_attributes(rows, cases, errors):
    seen = set()
    for row in rows:
        cid, aid = row["case_id"], row["attribute_id"]
        if (cid, aid) in seen or not ID.fullmatch(aid):
            errors.append(f"{cid}/{aid} : identifiant d’attribut invalide ou répété")
        seen.add((cid, aid))
        if cid not in cases or cases[cid]["kind"] != "speech":
            errors.append(f"{cid}/{aid} : aucun cas de parole correspondant")
            continue
        if not all(ID.fullmatch(row[field]) for field in ("group_id", "category")):
            errors.append(f"{cid}/{aid} : catégorie ou groupe invalide")
        if not row["expected"].strip():
            errors.append(f"{cid}/{aid} : valeur attendue vide")
        span = row["reference_span"]
        if not span.strip() or span not in cases[cid]["reference"]:
            errors.append(f"{cid}/{aid} : extrait absent de la référence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cas.csv"))
    parser.add_argument("--attributes", type=Path, help="CSV des attributs correspondant à --cases")
    parser.add_argument("--wav-dir", type=Path, help="Vérifie tous les WAV du manifeste fourni")
    args = parser.parse_args()
    errors = []
    try:
        cases = inspect_cases(load_csv(args.cases, CASE_FIELDS), args.wav_dir, errors)
        attributes = load_csv(args.attributes, ATTR_FIELDS) if args.attributes else []
        inspect_attributes(attributes, cases, errors)
    except (OSError, ValueError, csv.Error) as exc:
        errors.append(str(exc))
    if errors:
        for message in errors:
            print(message, file=sys.stderr)
        return 1
    checked = f", {len(cases)} WAV contrôlés" if args.wav_dir is not None else ""
    print(f"{len(cases)} cas, {len(attributes)} attributs vérifiés{checked}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
