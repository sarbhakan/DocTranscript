"""Training-only drug token weights from provenance-checked PxSLU BIO labels."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from p0.training.prepare_px import PX_PATH, locked_archive


# Independent exclusions for clear non-names even when the source mislabels.
PROTECTED = frozenset("""
  nanogramme nanogrammes microgramme microgrammes milligramme milligrammes gramme grammes
  kilogramme kilogrammes microlitre microlitres millilitre millilitres litre litres
  millimole millimoles mmol μg µg mcg ng mg kg g μl µl ml l ui iu pourcent
  matin midi soir heure heures comprimé comprimés gélule gélules goutte gouttes
  un une deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze
  seize vingt trente quarante cinquante soixante cent cents mille demi demie demis demies
  quart quarts moitié tiers sans pas jamais aucun aucune ni non
""".split())


def marked_characters(text: str, tags: str) -> tuple[set[int], Counter]:
    words = list(re.finditer(r"\S+", text))
    labels = tags.split()
    if len(words) != len(labels):
        raise ValueError("Annotation d’entraînement désalignée")
    index, covered, stats = 0, set(), Counter()
    while index < len(labels):
        if labels[index] != "B-drug":
            if labels[index] == "I-drug":
                stats["orphan_inside_tags_excluded"] += 1
            index += 1
            continue
        end = index + 1
        while end < len(labels) and labels[end] == "I-drug":
            end += 1
        spans = words[index:end]
        pieces = [word.group() for word in spans]
        if any(not any(char.isalpha() for char in piece)
               or any(char.isnumeric() for char in piece)
               or re.sub(r"[^\w]+", "", piece.casefold()) in PROTECTED for piece in pieces):
            stats["suspect_entities_excluded"] += 1
        else:
            for span in spans:
                covered.update(range(span.start(), span.end()))
            stats["accepted_drug_entities"] += 1
        index = end
    return covered, stats


def lexical_positions(tokenizer, text: str, tags: str, labels: list[int], prefix: list[int], eos: int):
    if not getattr(tokenizer, "is_fast", False):
        raise ValueError("Tokenizer rapide avec offsets source requis pour la pondération")
    marked, stats = marked_characters(text, tags)
    result = tokenizer(text, add_special_tokens=True, return_offsets_mapping=True, truncation=False)
    ids, offsets = result["input_ids"], result["offset_mapping"]
    if (len(ids) != len(offsets) or ids[:len(prefix)] != prefix or ids[-1] != eos or ids[1:] != labels):
        raise ValueError("Les offsets ne suivent pas les cibles réellement encodées")
    positions = []
    for offset_index in range(len(prefix), len(ids) - 1):
        begin, end = offsets[offset_index]
        if (type(begin) is not int or type(end) is not int or not 0 <= begin <= end <= len(text)):
            raise ValueError("Offset tokenizer hors de la référence d’entraînement")
        substantive = [i for i in range(begin, end) if not text[i].isspace()]
        # A token may include leading space, or touch several Unicode slices.
        # A mixed spell/dose token must never become a positive weight.
        if substantive and all(i in marked for i in substantive):
            positions.append(offset_index - 1)  # The objective drops Whisper's start-of-transcript token.
    stats["weighted_subtokens"] = len(positions)
    stats["clips_with_weighted_subtokens"] = int(bool(positions))
    return positions, stats


def training_drug_positions(archive_path: Path, tokenizer, rows: list[dict], labels: dict,
                            prefix: list[int], eos: int) -> tuple[dict[str, list[int]], dict]:
    """Only selected train rows may affect weights; no eval masks are generated."""
    with locked_archive(archive_path) as source:
        references, annotations = (source.read(PX_PATH + name).decode("utf-8-sig").splitlines()
                                   for name in ("seq.in", "seq.out"))
    if len(references) != len(annotations):
        raise ValueError("Références et annotations d’entraînement désalignées")
    positions, stats = {}, Counter()
    for row in rows:
        index = row["source_row_index"]
        if (row["partition"] != "train" or type(index) is not int or not 0 <= index < len(references)
                or row["text"] != references[index] or row["id"] in positions):
            raise ValueError("Seule une référence train vérifiée peut pondérer les médicaments")
        selected, counts = lexical_positions(tokenizer, row["text"], annotations[index], labels[row["id"]], prefix, eos)
        positions[row["id"]] = selected
        stats.update(counts)
    if stats["weighted_subtokens"] <= 0:
        raise ValueError("Aucun jeton médicament train exploitable pour cet essai")
    return positions, dict(stats)
