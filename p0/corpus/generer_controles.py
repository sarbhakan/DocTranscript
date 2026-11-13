"""Génère des WAV non vocaux déterministes pour le banc de développement."""

import argparse
import csv
import struct
import wave
from pathlib import Path


RATE = 16_000
CONTROLS = {
    "dev-silence-08s": (8, "silence"),
    "dev-silence-30s": (30, "silence"),
    "dev-noise-12s": (12, "souffle"),
    "dev-noise-30s": (30, "clics"),
}


def pcm(seconds, mode):
    frames = RATE * seconds
    audio = bytearray(frames * 2)
    if mode == "silence":
        return audio

    state = 0x4E4F5445
    rumble = 0
    for i in range(frames):
        state = (1_664_525 * state + 1_013_904_223) & 0xFFFFFFFF
        white = ((state >> 16) - 32768) // 64
        rumble = (rumble * 7 + white) // 8
        sample = rumble * 2 + white // 2
        if mode == "clics" and i >= RATE:
            # Brèves impulsions espacées de 211 ms, sans contenu vocal.
            period = RATE * 211 // 1000
            offset = (i - RATE) % period
            if offset < 48 and (i - RATE) // period % 9 < 5:
                sample += (48 - offset) * (120 if offset % 2 else -120)
        struct.pack_into("<h", audio, i * 2, sample)
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = args.wav_dir / "cas-controles.csv"
    source = Path(__file__).with_name("cas.csv")
    with source.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, strict=True)
        fields = reader.fieldnames
        rows = [row for row in reader if row["id"] in CONTROLS]
    if len(rows) != len(CONTROLS) or {row["id"] for row in rows} != set(CONTROLS):
        parser.error("le manifeste source ne contient pas exactement les contrôles prévus")

    args.wav_dir.mkdir(parents=True, exist_ok=True)
    outputs = [args.wav_dir / f"{row['id']}.wav" for row in rows] + [manifest]
    existing = [path.name for path in outputs if path.exists() or path.is_symlink()]
    if existing:
        parser.error(f"utiliser un dossier sans ces fichiers : {', '.join(existing)}")
    for row in rows:
        seconds, mode = CONTROLS[row["id"]]
        with (args.wav_dir / f"{row['id']}.wav").open("xb") as handle:
            with wave.open(handle, "wb") as wav:
                wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
                wav.writeframes(pcm(seconds, mode))
    with manifest.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} WAV de contrôle et leur manifeste : {args.wav_dir}")


if __name__ == "__main__":
    main()
