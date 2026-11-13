"""Extract only the verified French nomenclature XML from the 2026 Orphanet pack."""

import argparse
import hashlib
from pathlib import Path
import zipfile


ARCHIVE_SHA256 = "809461ba5e085382e9256895b6ed58d907fc5feb749c104874267e88f10b0b5a"
XML_SHA256 = "6f3fe39ca58d2cc054655202d531259bdd0c657da5490e40ff4f9fb9e55bf1cb"
MEMBER = "Orphanet_Nomenclature_Pack_FR/ORPHAnomenclature_fr_2026.xml"
SIZE = 21_778_650


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.source.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
                raise ValueError("SHA-256 différent du paquet Orphanet FR vérifié")
            with zipfile.ZipFile(source) as archive:
                info = archive.getinfo(MEMBER)
                if info.file_size != SIZE or sum(item.filename == MEMBER for item in archive.infolist()) != 1:
                    raise ValueError("XML Orphanet de taille ou de structure inattendue")
                payload = archive.read(info)
        if hashlib.sha256(payload).hexdigest() != XML_SHA256:
            raise ValueError("SHA-256 différent du XML Orphanet FR vérifié")
        with args.output.open("xb") as output:
            output.write(payload)
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
