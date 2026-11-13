"""`stoa ask <file> "<question>"` and `stoa serve` (click-to-verify viewer)."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .data import ROOT, Question
from .router import answer as route


def ask(file: str, question: str) -> dict:
    p = Path(file)
    rel = str(p.resolve().relative_to(ROOT.resolve())) if p.is_absolute() or p.exists() and ROOT.resolve() in p.resolve().parents else file
    q = Question(path=rel if rel.startswith("data/") else file, question=question)
    ans = route(q)
    return dataclasses.asdict(ans)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stoa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("file", help="path under the dataset, e.g. data/swiss_dwellings/x.pdf")
    a.add_argument("question")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    if args.cmd == "ask":
        print(json.dumps(ask(args.file, args.question), indent=2, ensure_ascii=False, default=str))
    else:
        from .viewer import serve
        serve(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
