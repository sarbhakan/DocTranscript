"""Compare NoteVive's local lexical context against the same app without context."""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import random
import re
import select
import shutil
import struct
import subprocess
import tempfile
import unicodedata
import wave

from p0.bench.scoring import edit_distance, nearest_rank
from p0.corpus.lexicon_cases import LONG, ORDINARY, PUBLIC


RATE = 16000
# Preserve accents and decimals. Split punctuation, apostrophes and hyphens.
TOKEN = re.compile(r"[0-9]+(?:[.,][0-9]+)?|[^\W\d_]+|%|[¼½¾/]")
SMALL = dict(zip(
    "zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize".split(),
    range(17),
))
TENS = dict(zip("vingt trente quarante cinquante soixante septante huitante nonante".split(),
                (20, 30, 40, 50, 60, 70, 80, 90)))


def words(text):
    text = unicodedata.normalize("NFC", text).casefold().replace("µ", "μ")
    text = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?!\d))", "", text)
    return [x.replace(".", ",") for x in TOKEN.findall(text)]


def cardinal(tokens):
    """Bounded French cardinal grammar used only by the critical-span scorer."""
    if not tokens:
        return None
    if len(tokens) == 1 and tokens[0].isdecimal():
        return int(tokens[0])
    if tokens.count("mille") == 1:
        at = tokens.index("mille")
        left = cardinal(tokens[:at]) if at else 1
        right = cardinal(tokens[at + 1:]) if at + 1 < len(tokens) else 0
        return 1000 * left + right if left is not None and right is not None else None
    markers = [i for i, w in enumerate(tokens) if w in {"cent", "cents"}]
    if len(markers) == 1:
        at = markers[0]
        left = cardinal(tokens[:at]) if at else 1
        right = cardinal(tokens[at + 1:]) if at + 1 < len(tokens) else 0
        return 100 * left + right if left is not None and 1 <= left <= 9 and right is not None and 0 <= right < 100 else None
    if len(tokens) == 1:
        return SMALL.get(tokens[0], TENS.get(tokens[0]))
    if tokens in (["dix", "sept"], ["dix", "huit"], ["dix", "neuf"]):
        return 10 + SMALL[tokens[-1]]
    if tokens[:2] in (["quatre", "vingt"], ["quatre", "vingts"]):
        base, rest = 80, tokens[2:]
    elif tokens[0] in TENS:
        base, rest = TENS[tokens[0]], tokens[1:]
    else:
        return None
    if not rest:
        return base
    if rest[0] == "et":
        if rest[1:] not in (["un"], ["onze"]):
            return None
        rest = rest[1:]
    val = cardinal(rest)
    if val is None or val <= 0 or val >= (20 if base in {60, 80} else 10):
        return None
    return base + val


def digit_prefix(tokens, start, length=8):
    if start >= len(tokens):
        return None, start
    for stop in range(min(start + length, len(tokens)), start, -1):
        value = cardinal(tokens[start:stop])
        if value is not None:
            return value, stop
    return None, start


CRITICAL_ALIASES = {
    ("milligramme",): ("mg",), ("milligrammes",): ("mg",),
    ("microgramme",): ("μg",), ("microgrammes",): ("μg",),
    ("millilitre",): ("ml",), ("millilitres",): ("ml",),
    ("millimètre",): ("mm",), ("millimètres",): ("mm",),
    ("kilogramme",): ("kg",), ("kilogrammes",): ("kg",),
    ("millimètres", "de", "mercure"): ("mmhg",),
    ("millimètre", "de", "mercure"): ("mmhg",),
    ("pour", "cent"): ("%",), ("pourcent",): ("%",),
    ("unités", "internationales"): ("ui",), ("unité", "internationale"): ("ui",),
    ("1", "demi", "de", "comprimé"): ("½", "comprimé"),
    ("1", "demi"): ("½",), ("le", "demi"): ("½",), ("1", "quart", "de"): ("¼",),
    ("3", "quarts", "de"): ("¾",),
    ("1", "/", "2"): ("½",), ("1", "/", "4"): ("¼",), ("3", "/", "4"): ("¾",),
    ("0,5", "comprimé"): ("½", "comprimé"), ("0,25", "comprimé"): ("¼", "comprimé"),
    ("0,75", "comprimé"): ("¾", "comprimé"),
}


def numbers(tokens):
    out = []
    i = 0
    while i < len(tokens):
        current = tokens[i]
        if tokens[i:i + 2] == ["pour", "cent"]:
            out.append("%")
            i += 2
            continue
        value, end = digit_prefix(tokens, i)
        if value is None:
            out.append(current)
            i += 1
            continue
        if end < len(tokens) and tokens[end] in {"virgule", "point"}:
            decimal_start = end + 1
            while decimal_start < len(tokens) and tokens[decimal_start] in {"zéro", "0"}:
                decimal_start += 1
            fractional, decimal_end = digit_prefix(tokens, decimal_start)
            leading_zeros = "0" * (decimal_start - end - 1)
            if fractional is not None or leading_zeros:
                out.append(f"{value},{leading_zeros}{'' if fractional is None else fractional}")
                i = decimal_end
                continue
        out.append(str(value))
        i = end
    return out


def critical_words(text):
    tokens = numbers(words(text))
    out = []
    i = 0
    while i < len(tokens):
        for size in range(min(4, len(tokens) - i), 0, -1):
            hit = CRITICAL_ALIASES.get(tuple(tokens[i:i+size]))
            if hit is not None:
                out.extend(hit)
                i += size
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def matches(haystack, needle):
    n = len(needle)
    if n:
        for start in range(len(haystack) - n + 1):
            if haystack[start:start+n] == needle:
                yield (start, start + n)


def annotated_matches(text, expected, normalization):
    haystack = normalization(text)
    used = set()
    checks = []
    for label in expected:
        candidates = {pair for alt in label.split("|")
                      for pair in matches(haystack, normalization(alt))}
        hit = next((pair for pair in sorted(candidates) if pair not in used), None)
        if hit is not None:
            used.add(hit)
        checks.append((label, hit is not None))
    return checks


def write_wav(path, frames):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        stream.writeframes(frames)


def synthesize(sentences, wave_path, voice, scratch):
    # One second of digital silence gives the detector an unambiguous boundary.
    # No synthetic quiet appended to the end: the final passage can arrive at stop.
    result = bytearray(2 * RATE * 3 // 10)
    speech_ends = []
    for index, sentence in enumerate(sentences):
        aiff = scratch / "fixture.aiff"
        aiff.unlink(missing_ok=True)
        subprocess.run(["say", "-v", voice, "-r", "165", "-o", str(aiff), sentence], check=True)
        clip = subprocess.check_output([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(aiff), "-ar", str(RATE),
            "-ac", "1", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
        ])
        pcm = memoryview(clip)
        last = next((i for i in range(len(pcm) - 2, -1, -2)
                     if abs(struct.unpack_from("<h", pcm, i)[0]) >= 350), None)
        if last is None or last < RATE // 2:
            raise ValueError("signal synthétique vide ou trop court")
        result.extend(pcm[:min(last + 2 * RATE * 6 // 100, len(pcm))])
        speech_ends.append(round((len(result) - min(2 * RATE * 6 // 100, len(pcm) - last)) / (2 * RATE) * 1000))
        if index + 1 < len(sentences):
            result.extend(bytes(2 * RATE))
    write_wav(wave_path, result)
    return speech_ends


def prepare(output, p0_lot, voice):
    output.mkdir(parents=True, exist_ok=False)
    wave_dir = output / "wav"
    wave_dir.mkdir()
    with (p0_lot / "cases.csv").open(encoding="utf-8", newline="") as stream:
        refs = {row["id"]: row for row in csv.DictReader(stream)}
    rows = []
    with tempfile.TemporaryDirectory(prefix="nvlex-voice-") as directory:
        scratch = Path(directory)
        for cid, profile, sentences, terms, critical in LONG:
            ends = synthesize(sentences, wave_dir / f"{cid}.wav", voice, scratch)
            rows.append(dict(id=cid, profile=profile, reference=" ".join(sentences), kind="synth",
                             terms=terms, critical=critical, lures=[], speech_ends_ms=ends))
        for cid, profile, sentences, lures in ORDINARY:
            ends = synthesize(sentences, wave_dir / f"{cid}.wav", voice, scratch)
            rows.append(dict(id=cid, profile=profile, reference=" ".join(sentences), kind="ordinary",
                             terms=[], critical={}, lures=lures, speech_ends_ms=ends))
    for cid, profile, terms, critical in PUBLIC:
        kind = refs[cid]["kind"]
        if cid.startswith("px-"):
            kind = "human"
        elif cid in {"dev-19", "dev-20"}:
            kind = "ordinary"
        elif kind == "speech":
            kind = "synth"
        shutil.copyfile(p0_lot / "wav" / f"{cid}.wav", wave_dir / f"{cid}.wav")
        rows.append(dict(id=cid, profile=profile, reference=refs[cid]["reference"], kind=kind,
                         terms=terms, critical=critical, lures=[], speech_ends_ms=[]))
    for row in rows:
        wave_path = wave_dir / f"{row['id']}.wav"
        row["wav_sha256"] = hashlib.sha256(wave_path.read_bytes()).hexdigest()
        with wave.open(str(wave_path), "rb") as stream:
            row["duration_ms"] = round(stream.getnframes() * 1000 / stream.getframerate())
    (output / "cases.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} cas préparés, dont {len(LONG)} dictées longues en voix synthétique ({voice}).")


def read_reply(worker, profile, wav):
    worker.stdin.write(profile.encode("ascii") + b"\n" + struct.pack("<I", len(wav)) + wav)
    worker.stdin.flush()
    if not select.select([worker.stdout], [], [], 100)[0]:
        raise TimeoutError("délai de réponse NoteVive dépassé")
    data = worker.stdout.readline(1_000_001)
    if not data.endswith(b"\n") or len(data) > 1_000_000:
        raise RuntimeError(f"réponse NoteVive absente ou invalide (code {worker.poll()})")
    result = json.loads(data)
    if "error" in result:
        raise RuntimeError(result["error"])
    if result["profile"] != profile or bool(result["accepted_terms"]) != bool(profile):
        raise ValueError("profil de contexte non appliqué comme demandé")
    return result


def run_arms(binary, case_dir, output, repeats, include_full):
    rows = json.loads((case_dir / "cases.json").read_text(encoding="utf-8"))
    rows_by_id = {r["id"]: r for r in rows}
    wavs = {}
    for cid, row in rows_by_id.items():
        data = (case_dir / "wav" / f"{cid}.wav").read_bytes()
        if hashlib.sha256(data).hexdigest() != row["wav_sha256"]:
            raise ValueError(f"empreinte du WAV différente: {cid}")
        wavs[cid] = data
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2916)
    ids = list(rows_by_id)
    rng.shuffle(ids)
    with output.open("x", encoding="utf-8") as stream:
        worker = subprocess.Popen([str(binary.resolve()), "--lexicon-bench"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            # Warm both paths and every tested profile outside the timed sample.
            # Use a short ordinary utterance; it has no target terms.
            warmup = wavs["leurre-01"]
            read_reply(worker, "", warmup)
            for profile in sorted({r["profile"] for r in rows}):
                read_reply(worker, profile, warmup)
                if include_full:
                    read_reply(worker, f"full:{profile}", warmup)
            arms = ["off", "on", "full"] if include_full else ["off", "on"]
            for repeat in range(repeats):
                if repeat > 0:
                    rng.shuffle(ids)
                for i, cid in enumerate(ids):
                    rotate = (repeat + i) % len(arms)
                    order = arms[rotate:] + arms[:rotate]
                    for arm in order:
                        row = rows_by_id[cid]
                        profile = f"full:{row['profile']}" if arm == "full" else row["profile"] if arm == "on" else ""
                        response = read_reply(worker, profile, wavs[cid])
                        response.update(id=cid, arm=arm, repeat=repeat)
                        stream.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                print(f"Répétition {repeat + 1}/{repeats} : {len(ids)} cas appariés.", flush=True)
            worker.stdin.close()
            if worker.wait(timeout=10) != 0:
                raise RuntimeError("le processus NoteVive a échoué")
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()


def result_text(result):
    return " ".join(p["text"] for p in result["pause"] + result["stop"])


def segment_sequence(result):
    return ([(p["audio_ms"], p["text"]) for p in result["pause"]],
            [p["text"] for p in result["stop"]])


def lexicon_text(entry):
    if isinstance(entry, str):
        return entry
    return entry["term"] if "term" in entry else entry["text"]


def active_catalogue(path):
    profiles = json.loads(path.read_text(encoding="utf-8"))["profiles"]
    return {p["id"]: [lexicon_text(v) for v in p["active"]] for p in profiles}, {
        p["id"]: [lexicon_text(v) for v in p["entries"]] for p in profiles}


def intrusions(text, ref, terms):
    heard, spoken = words(text), words(ref)
    found = []
    for term in sorted(set(terms)):
        query = words(term)
        extras = sum(1 for _ in matches(heard, query)) - sum(1 for _ in matches(spoken, query))
        if extras > 0:
            found.extend([term] * extras)
    return found


def quantiles(values):
    return {f"p{int(p * 100)}": nearest_rank(values, p)["value"] for p in (0.5, 0.95)} | {"n": len(values)}


def score(case_dir, inputs, catalogue):
    rows = json.loads((case_dir / "cases.json").read_text(encoding="utf-8"))
    active, full = active_catalogue(catalogue)
    results = {}
    for line in inputs.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = item["id"], item["repeat"], item["arm"]
        if key in results:
            raise ValueError(f"résultat dupliqué : {key}")
        results[key] = item
    repeats = sorted({r for _, r, _ in results})
    arms = ["off", "on", "full"] if any(arm == "full" for _, _, arm in results) else ["off", "on"]
    expected = {(r["id"], repeat, arm) for r in rows for repeat in repeats for arm in arms}
    if not repeats or repeats != list(range(len(repeats))) or set(results) != expected:
        raise ValueError("résultats incomplets ou bras non appariés")

    totals = {arm: dict(rare_correct=0, critical_correct=Counter(), control_outputs=0,
                        ordinary_edits=0, added_active_terms=0, added_lures=0)
              for arm in arms}
    stats = {arm: Counter() for arm in arms}
    coverage = Counter()
    per_profile = {}
    comparisons = {arm: dict(rare_gains=[], rare_losses=[], new_critical_errors=[],
                             critical_gains=[], changed=[], identical_segment_replays=0)
                   for arm in arms if arm != "off"}
    alerts = []
    for row in rows:
        cid, profile = row["id"], row["profile"]
        variants = row["terms"]
        rare_in_profile = per_profile.setdefault(profile, Counter())
        rare_in_profile["expected"] += len(variants)
        for label, entries in (("active", active), ("catalogue", full)):
            frozen = {tuple(words(x)) for x in entries[profile]}
            covered = sum(any(tuple(words(x)) in frozen for x in v.split("|")) for v in variants)
            coverage[label] += covered
            rare_in_profile[label] += covered
        lex_checks, critical_checks = {}, {}
        for arm in arms:
            result = results[cid, 0, arm]
            text = result_text(result)
            lex_checks[arm] = annotated_matches(text, variants, words)
            found = sum(ok for _, ok in lex_checks[arm])
            totals[arm]["rare_correct"] += found
            rare_in_profile[arm] += found
            critical_checks[arm] = {k: annotated_matches(text, v, critical_words)
                                    for k, v in row["critical"].items()}
            for cat, items in critical_checks[arm].items():
                totals[arm]["critical_correct"][cat] += sum(ok for _, ok in items)
            # Use the same active list in both core arms. The full arm reports
            # this same comparison plus any match against the whole catalogue.
            added = intrusions(text, row["reference"], active[profile])
            if arm == "full":
                stats[arm]["added_full_catalogue"] += len(intrusions(text, row["reference"], full[profile]))
            elif arm == "off" and "full" in arms:
                stats[arm]["added_full_catalogue"] += len(intrusions(text, row["reference"], full[profile]))
            lures = intrusions(text, row["reference"], row["lures"])
            totals[arm]["added_active_terms"] += len(added)
            totals[arm]["added_lures"] += len(lures)
            if row["kind"] in {"noise", "silence"}:
                totals[arm]["control_outputs"] += bool(text)
            if row["kind"] == "ordinary":
                totals[arm]["ordinary_edits"] += edit_distance(words(row["reference"]), words(text))
            if added or lures:
                alerts.append(dict(id=cid, arm=arm, active=added, lures=lures))
            if any(segment_sequence(results[cid, r, arm]) != segment_sequence(result)
                   for r in repeats[1:]):
                stats[arm]["non_deterministic_cases"] += 1
        for arm, comp in comparisons.items():
            comp["identical_segment_replays"] += sum(
                segment_sequence(results[cid, r, "off"]) == segment_sequence(results[cid, r, arm])
                for r in repeats)
            for (term, off), (_, on) in zip(lex_checks["off"], lex_checks[arm]):
                if off != on:
                    comp["rare_gains" if on else "rare_losses"].append({"id": cid, "term": term})
            for cat in row["critical"]:
                for (span, off), (_, on) in zip(critical_checks["off"][cat], critical_checks[arm][cat]):
                    if off != on:
                        comp["critical_gains" if on else "new_critical_errors"].append(
                            {"id": cid, "category": cat, "span": span})
            off_text, arm_text = (result_text(results[cid, 0, a]) for a in ("off", arm))
            if off_text != arm_text:
                comp["changed"].append(dict(id=cid, off=off_text, compared=arm_text))

    metrics = {}
    for arm in arms:
        observations = [r for r in results.values() if r["arm"] == arm]
        decode = [p["decode_ms"] for r in observations for p in r["pause"] + r["stop"]]
        elapsed = [r["elapsed_ms"] for r in observations]
        pauses = [p["decode_ms"] for r in observations for p in r["pause"]]
        setup = [r["setup_ms"] + r["selection_ms"] for r in observations
                 if "setup_ms" in r and "selection_ms" in r]
        # The feed is accelerated; only measure gap from each artificial speech
        # endpoint to the pause packet plus native decode time, not UI latency.
        estimated, no_phrase = [], 0
        for row in rows:
            for r in repeats:
                pause_events = results[row["id"], r, arm]["pause"]
                for end in row["speech_ends_ms"][:-1]:
                    candidates = [p for p in pause_events if end <= p["audio_ms"] <= end + 1200]
                    if candidates:
                        p = min(candidates, key=lambda item: item["audio_ms"])
                        estimated.append(round(p["audio_ms"] - end + p["decode_ms"], 2))
                    else:
                        no_phrase += 1
        metrics[arm] = dict(segment_decode_ms=quantiles(decode), decode_after_pause_ms=quantiles(pauses),
                            replay_elapsed_ms=quantiles(elapsed), profile_setup_ms=quantiles(setup),
                            pause_estimate_ms=quantiles(estimated),
                            artificial_pauses_missing=no_phrase, **stats[arm])
    total_terms = sum(len(r["terms"]) for r in rows)
    critical = Counter()
    for row in rows:
        critical.update({k: len(v) for k, v in row["critical"].items()})
    return dict(cases=len(rows), kind_counts=Counter(r["kind"] for r in rows), repeats=len(repeats),
                accepted_by_profile={p: sorted({r["accepted_terms"] for r in results.values() if r["profile"] == p})
                                     for p in sorted({r["profile"] for r in results.values() if r["profile"]})},
                rare_expected=total_terms, rare_active=coverage["active"], rare_catalogue=coverage["catalogue"],
                critical_expected=critical,
                ordinary_words=sum(len(words(r["reference"])) for r in rows if r["kind"] == "ordinary"),
                by_profile=per_profile, totals=totals, timing=metrics,
                comparisons=comparisons, intrusions=alerts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="fichier local P0, say et ffmpeg requis")
    prep.add_argument("--p0-lot", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--voice", default="Jacques")
    run = sub.add_parser("run", help="mesurer dans un seul processus NoteVive signé")
    run.add_argument("--binary", type=Path, required=True)
    run.add_argument("--cases", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--include-full", action="store_true", help="bras exploratoire : tout le catalogue")
    run.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    report = sub.add_parser("score", help="mesurer et exporter les différences locales")
    report.add_argument("--cases", type=Path, required=True)
    report.add_argument("--results", type=Path, required=True)
    report.add_argument("--profiles", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output, args.p0_lot, args.voice)
    elif args.command == "run":
        run_arms(args.binary, args.cases, args.output, args.repeats, args.include_full)
    else:
        data = score(args.cases, args.results, args.profiles)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        summary = {k: data[k] for k in ("cases", "kind_counts", "rare_expected", "rare_active", "rare_catalogue",
                                         "critical_expected", "totals", "timing")}
        print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
