"""Create a pip hash lock from a reviewed, Windows x64 wheelhouse."""
import argparse
from email.parser import BytesParser
from pathlib import Path
import re
import zipfile

from p0.packs.__main__ import sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wheelhouse", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    wheels = {}
    for path in sorted(args.wheelhouse.glob("*.whl")):
        try:
            with zipfile.ZipFile(path) as wheel:
                infos = [item for item in wheel.infolist() if item.filename.endswith(".dist-info/METADATA")]
                if len(infos) != 1 or infos[0].file_size > 4_000_000:
                    raise ValueError("métadonnées inattendues")
                msg = BytesParser().parsebytes(wheel.read(infos[0]), headersonly=True)
            name = re.sub(r"[-_.]+", "-", msg["Name"].lower())
            version = msg["Version"]
            if (name in wheels or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
                    or not re.fullmatch(r"[0-9][0-9a-zA-Z.+!_-]*", version)):
                raise ValueError("nom, version ou doublon invalide")
            wheels[name] = (version, sha(path))
        except (KeyError, TypeError, ValueError, zipfile.BadZipFile) as error:
            p.error(f"{path.name} : {error}")
    for name, version in {"sherpa-onnx": "2.0.1", "pywhispercpp": "1.5.1"}.items():
        if name not in wheels or wheels[name][0] != version:
            p.error(f"wheel directe attendue : {name}=={version}")
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        out.write("# P0 Windows CPython 3.12 x64 - transférer avec le wheelhouse.\n")
        for name, (version, digest) in sorted(wheels.items()):
            out.write(f"{name}=={version} --hash=sha256:{digest}\n")


if __name__ == "__main__":
    main()
