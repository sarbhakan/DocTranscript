"""Double de test déterministe : ignore le signal audio, ne fait aucun ASR."""

import argparse
import base64
import binascii
import json
import sys
import time


def send(message):
    print(json.dumps(message, ensure_ascii=True, separators=(",", ":")), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behavior", choices=("ok", "silent", "stall", "startup-stall", "no-read",
                                               "error", "bad-done", "no-done"), default="ok")
    parser.add_argument("--text", default="Texte simulé.")
    args = parser.parse_args()
    if args.behavior == "startup-stall":
        time.sleep(60)
        return 0
    send({"type": "ready", "protocol": 1, "engine": "fixture", "simulated": True,
          "details": {"behavior": args.behavior}})
    if args.behavior == "no-read":
        time.sleep(60)
        return 0
    active = None
    seq = 0
    for line in sys.stdin.buffer:
        event = json.loads(line)
        typ, case_id = event["type"], event["id"]
        if typ == "start" and active is None:
            active, seq = case_id, 0
        elif typ == "audio" and active == case_id and event["seq"] == seq:
            try:
                pcm = base64.b64decode(event["pcm_b64"], validate=True)
            except (binascii.Error, ValueError):
                pcm = b""
            if len(pcm) == 0 or len(pcm) % 2:
                send({"type": "error", "id": case_id, "code": "invalid_audio"})
                return 1
            if args.behavior == "ok" and seq == 0:
                send({"type": "partial", "id": case_id, "text": args.text.split()[0] if args.text.split() else ""})
            seq += 1
        elif typ == "end" and active == case_id and seq:
            if args.behavior == "stall":
                time.sleep(60)
                return 0
            if args.behavior == "error":
                send({"type": "error", "id": case_id, "code": "synthetic_error"})
                return 1
            if args.behavior != "bad-done":
                send({"type": "final", "id": case_id, "text": "" if args.behavior == "silent" else args.text})
            if args.behavior == "no-done":
                return 1
            send({"type": "done", "id": case_id})
            active = None
        else:
            send({"type": "error", "id": case_id, "code": "fixture_contract_error"})
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
