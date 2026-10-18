"""Command line.

    python -m foia_assist process "All records about rural broadband awards in 2025" --requester media
    python -m foia_assist process --file request.txt --endpoint gov-cloud --json
    python -m foia_assist serve --port 8080
"""

import argparse
import json
import sys

from .pipeline import Assistant
from .server import serve


def print_packet(p: dict) -> None:
    t = p["triage"]
    yrs = f"{t['start_year']}–{t['end_year']}" if t["start_year"] else "any"
    print(f"{p['request_id']}  ·  endpoint {p['endpoint']['name']} (up to {p['endpoint']['authorized_level']})")
    print(f"track {t['track']}  ·  fee category {p['fee_category']}  ·  years {yrs}  ·  "
          f"programs {', '.join(t['programs']) or '-'}")
    if t["needs_clarification"]:
        print(f"\nNEEDS CLARIFICATION: {t['clarification_question']}")
    for c in p["candidates"]:
        flags = sorted({f["exemption"] for f in c["flags"]})
        print(f"\n  {c['id']}  [{c['marking']}]  score {c['score']}  {c['title']}")
        print(f"    flags: {', '.join(flags) or 'none'}")
        note = c["note"] if isinstance(c["note"], str) else f"{c['note']['responsive']}: {c['note']['reason']}"
        print(f"    note ({c['note_source']}): {note}")
    print(f"\n{p['notice']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="foia_assist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("process", help="process one request")
    pr.add_argument("text", nargs="?")
    pr.add_argument("--file")
    pr.add_argument("--requester", default="other", choices=["commercial", "media", "educational", "other"])
    pr.add_argument("--endpoint")
    pr.add_argument("--json", action="store_true")
    sv = sub.add_parser("serve", help="run the web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        serve(args.host, args.port)
        return 0
    text = open(args.file).read() if args.file else args.text
    if not text:
        print("give request text or --file", file=sys.stderr)
        return 2
    packet = Assistant().process(text, args.requester, args.endpoint)
    print(json.dumps(packet, indent=2) if args.json else "", end="")
    if not args.json:
        print_packet(packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
