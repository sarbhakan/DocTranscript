"""Extract the fixed PxSLU evaluation sample; do not use system outputs as labels."""
import argparse
import csv
from collections import defaultdict
import hashlib
import io
from pathlib import Path
import random
import shutil
import subprocess
import wave
from zipfile import ZipFile

from p0.corpus.generer_controles import CONTROLS, pcm as control_pcm

PX_PATH = "PxCorpus/PxSLU/"
PX_SHA256 = "b901f59118f06854a4c4823611d8cadbbd2e68e48459bc514dabe0bda6f7d81c"
PRIOR_ROWS = {558, 241, 178, 574, 1667, 727, 813, 51, 785, 684}
SEED = 814239
RATE = 16_000
PCM_BYTES_PER_SECOND = 2 * RATE
SYNTH_CASES = {
    "dev-01", "dev-03", "dev-04", "dev-05", "dev-06", "dev-08", "dev-09", "dev-10",
    "dev-11", "dev-13", "dev-15", "dev-16", "dev-17", "dev-18", "dev-19", "dev-20",
}
SPOKEN_FORMS = {
    "dev-04": {"7,5 mg": "sept virgule cinq milligrammes"},
    "dev-05": {"25 ": "vingt-cinq ", "50 ": "cinquante "},
    "dev-06": {"0,3 mL": "zéro virgule trois millilitres"},
    "dev-11": {
        "L’HbA1c": "L'hémoglobine glyquée", "6,4 %": "six virgule quatre pour cent",
        "92 ": "quatre-vingt-douze ", "DFG": "débit de filtration glomérulaire",
    },
    "dev-16": {
        "128 sur 76 mmHg": "cent vingt-huit sur soixante-seize millimètres de mercure",
        "118 sur 72": "cent dix-huit sur soixante-douze",
    },
}
REQUIRED_TAGS = ("B-drug", "B-d_dos_val", "B-d_dos_up")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--px-archive", type=Path, required=True, help="Local PxCorpus v4 ZIP")
    parser.add_argument("--output", type=Path, required=True, help="New local output folder")
    parser.add_argument("--with-mac-synth", action="store_true", help="Add macOS Jacques TTS fixtures; requires ffmpeg")
    args = parser.parse_args()
    if args.with_mac_synth and not (shutil.which("say") and shutil.which("ffmpeg")):
        parser.error("--with-mac-synth needs macOS say and ffmpeg")

    with args.px_archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != PX_SHA256:
            parser.error("empreinte SHA-256 différente de PxCorpus v4")

    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    out = root / "wav"
    out.mkdir(exist_ok=False)
    rows = []

    def add(case_id, kind, reference, pcm):
        path = out / f"{case_id}.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            stream.writeframes(pcm)
        rows.append({"id": case_id, "partition": "dev", "kind": kind, "reference": reference})

    def read_pcm(source):
        with wave.open(source, "rb") as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, RATE):
                raise ValueError("WAV PCM16 mono 16 kHz attendu")
            return stream.readframes(stream.getnframes())

    with ZipFile(args.px_archive) as archive:
        base = PX_PATH
        def read(name):
            return archive.read(base + name).decode("utf-8-sig").splitlines()
        paths, ref, tags, speakers = map(read, ("paths.txt", "seq.in", "seq.out", "metadata.txt"))
        test = sorted({int(s) for s in read("data_splits/test/test.txt") if s.strip()})
        if not (len(paths) == len(ref) == len(tags) == len(speakers)
                and all(0 <= i < len(paths) for i in test)):
            raise ValueError("métadonnées PxSLU désalignées")
        people = defaultdict(list)
        names = set(archive.namelist())
        for ix in test:
            if ix in PRIOR_ROWS:
                continue
            voice, _, _, category = next(csv.reader([speakers[ix]]))
            if category != "doctor":
                raise ValueError("index du jeu de médecins PxSLU invalide")
            markers = tags[ix].split()
            if len(ref[ix].split()) != len(markers) or any(markers.count(t) != 1 for t in REQUIRED_TAGS):
                continue
            filename = f"{base}recordings/{paths[ix].strip()}"
            if filename not in names:
                continue
            pcm = read_pcm(io.BytesIO(archive.read(filename)))
            if not 3 * PCM_BYTES_PER_SECOND <= len(pcm) <= 20 * PCM_BYTES_PER_SECOND:
                continue
            people[voice].append((ix, filename))
        rng = random.Random(SEED)
        for voice, options in sorted(people.items()):
            rng.shuffle(options)
            sessions = set()
            for ix, filename in options:
                session = filename.rsplit("/",1)[0]
                if session in sessions:
                    continue
                pcm = read_pcm(io.BytesIO(archive.read(filename)))
                add(f"px-{ix}", "speech", ref[ix], pcm)
                sessions.add(session)
                if len(sessions) == 4:
                    break
        print(f"{len(people)} voix, {len(rows)} prescriptions")

    if args.with_mac_synth:
        with (Path(__file__).resolve().parents[1] / "corpus/cas.csv").open(encoding="utf-8", newline="") as stream:
            for r in csv.DictReader(stream):
                cid, ref = r["id"], r["reference"]
                if cid not in SYNTH_CASES:
                    continue
                spoken = ref
                for src, dst in SPOKEN_FORMS.get(cid, {}).items():
                    spoken = spoken.replace(src, dst)
                aiff = root / "synth.aiff"
                if aiff.exists():
                    aiff.unlink()
                subprocess.run(["say", "-v", "Jacques", "-r", "170", "-o", str(aiff), spoken], check=True)
                wave_bytes = subprocess.check_output([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(aiff),
                    "-af", "adelay=350:all=1,apad=pad_dur=0.8", "-ar", str(RATE), "-ac", "1",
                    "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
                ])
                add(cid, "speech", spoken, read_pcm(io.BytesIO(wave_bytes)))
        (root / "synth.aiff").unlink(missing_ok=True)
    for cid, (seconds, mode) in sorted(CONTROLS.items()):
        add(cid, "silence" if mode == "silence" else "noise", "", control_pcm(seconds, mode))
    manifest = root / "cases.csv"
    with manifest.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    print(f"{len(rows)} cas ; SHA-256 du manifeste : {digest}")


if __name__ == "__main__":
    main()
