"""Freeze an experimental short prompt from TRAIN texts and official RUIM labels.

Never reads validation, audio or predictions. The resulting list is an ASR trial
input, not a product default or a post-transcription replacement dictionary.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata

from .prepare_041 import ADDITIONS, HERE, sha


def folded(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c)).replace("œ", "oe")


EXCLUDED = re.compile(r"\b(?:mg|g|ml|kg|ui|mcg|milligrammes?|grammes?|microgrammes?|"
                      r"sans|pas|ni|non|moins|ne|gauche|droite?|bilateral|comprime|dose|fois|matin|soir)\b")


def ranked_candidates(train_rows, terminology_rows):
    if not train_rows or any(row.get("partition") != "train" or not isinstance(row.get("text"), str)
                             or not row["text"].strip() for row in train_rows):
        raise ValueError("seuls des textes explicitement partitionnés train sont autorisés")
    ids = [row["id"] for row in train_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("identifiants train dupliqués")
    references = [folded(row["text"]) for row in train_rows]
    grouped = defaultdict(list)
    for row in terminology_rows:
        if row.get("categorie") != "substance":
            raise ValueError("seul le fichier officiel des substances est autorisé")
        text = row["libelle"].strip()
        normalized = folded(text)
        if not text or len(text) > 70 or len(text.split()) > 5 or any(c.isnumeric() for c in text) or EXCLUDED.search(normalized):
            continue
        grouped[normalized].append((text, row["code"]))
    result = []
    for normalized, variants in grouped.items():
        pattern = re.compile(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)")
        count = sum(bool(pattern.search(reference)) for reference in references)
        if count:
            term, code = min(variants, key=lambda pair: (pair[0].encode("utf-8"), pair[1]))
            result.append({"term": term, "source_code": code, "training_clips": count})
    return sorted(result, key=lambda row: (-row["training_clips"], row["term"].encode("utf-8")))


def bounded_prefix(candidates, count_tokens):
    selected = []
    for row in candidates[:16]:
        trial = selected + [row]
        text = ", ".join(item["term"] for item in trial) + "."
        if count_tokens(text) > 64:
            break  # No cherry-picking a shorter or clinically convenient later term.
        selected = trial
    if not selected:
        raise ValueError("aucun contexte ne tient dans le budget fixé")
    text = ", ".join(item["term"] for item in selected) + "."
    return selected, text, count_tokens(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--ruim-csv", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink() or args.output.resolve().is_relative_to(HERE.parent):
            raise ValueError("sortie privée neuve hors du dépôt requise")
        source = next(x for x in json.loads(ADDITIONS.read_text())["sources"] if x["id"] == "ruim-substances")
        terms_blob = args.ruim_csv.read_bytes()
        if sha(terms_blob) != source["sha256"]:
            raise ValueError("CSV RUIM différent du manifeste officiel revu")
        train_blob = args.train.read_bytes()
        train = [json.loads(line) for line in train_blob.decode().splitlines() if line.strip()]
        candidates = ranked_candidates(train, list(csv.DictReader(io.StringIO(terms_blob.decode()))))
        # Optional dependency loaded only for this deliberate local experiment.
        import transformers
        tokenizer = transformers.AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True,
                                                                trust_remote_code=False)
        selected, prompt, token_count = bounded_prefix(candidates, lambda text: len(tokenizer.get_prompt_ids(text)))
        report = {
            "schema": 1, "profile": "ruim-train-frequency-short-context-v1", "frozen_before_generation": True,
            "selection": "Train-only; whole-phrase accent/case-insensitive occurrence by clip; descending frequency, UTF-8 label tie-break; stop at first term exceeding 64 Whisper prompt_ids; maximum16 terms.",
            "excluded": "Digits, numeric glyphs, units, negation, laterality, administration terms; no dose stripping from CIS names.",
            "source": {"id": source["id"], "edition": source["edition"], "url": source["url"], "license_url": source["license_url"],
                       "csv_sha256": source["sha256"], "sources_lock_sha256": sha((HERE / "sources-041.lock.json").read_bytes())},
            "train_manifest_sha256": sha(train_blob), "train_clips": len(train), "matched_candidates": len(candidates),
            "selection_code_sha256": sha(Path(__file__).read_bytes()), "tokenizer_library": transformers.__version__,
            "tokenizer_files": {p.name: sha(p.read_bytes()) for p in sorted(args.tokenizer.iterdir())
                                if p.is_file() and p.suffix in {".json", ".txt"} and p.stat().st_size < 10_000_000},
            "terms": [row["term"] for row in selected], "selected": selected, "prompt": prompt,
            "prompt_sha256": sha(prompt.encode()), "prompt_tokens": token_count,
            "clinical_qualification": False, "asr_gain_measured": False,
        }
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"manifest_sha256": sha(args.output.read_bytes()), "terms": len(selected),
                          "prompt_tokens": token_count, "candidates": len(candidates)}, indent=2))
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
