"""cutline auto VIDEO: rough cut + Shorts in one command, no chat needed."""

from __future__ import annotations

import argparse
import json

from . import project as P


def main() -> None:
    ap = argparse.ArgumentParser(prog="cutline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auto", help="Cut silences and ums, then make Shorts")
    a.add_argument("video")
    a.add_argument("--shorts", type=int, default=5)
    a.add_argument("--no-transcribe", action="store_true")
    a.add_argument("--captions", default="bold", choices=["bold", "clean", "karaoke"])
    args = ap.parse_args()

    p = P.create(args.video)
    P.analyze(p, do_transcribe=not args.no_transcribe)
    P.render_long(p)
    if p.transcript and args.shorts:
        P.set_shorts(p, P.suggest_shorts(p, args.shorts))
        p.edits.captions.preset = args.captions
        P.render_shorts(p)
    print(json.dumps(P.summary(p), indent=2))


if __name__ == "__main__":
    main()
