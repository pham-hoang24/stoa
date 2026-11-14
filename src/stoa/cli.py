"""`stoa ask <file> "<question>"` and `stoa serve` (click-to-verify viewer)."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .answer import ABSTAIN_DECLINED, Answer
from .assets import DEFAULT_DIRECTORY, PNG_SIGNATURE, AssetStore, DrawingError
from .data import ROOT, Question
from .image_runtime import assess
from .router import answer as route


def ask(file: str, question: str, *, confirmation=None, max_requests=9) -> dict:
    p = Path(file).expanduser()
    if p.is_file():
        with p.open("rb") as stream:
            is_png = stream.read(8) == PNG_SIGNATURE
        if is_png or p.suffix.lower() == ".png":
            from .assets import from_path
            try:
                validated = from_path(p)
                drawing = AssetStore(DEFAULT_DIRECTORY).put(validated.png)
            except DrawingError as exc:
                return dataclasses.asdict(Answer(None, lane="vision", note=str(exc), abstain=ABSTAIN_DECLINED))
            result = assess(drawing, question, confirmation=confirmation, max_requests=max_requests)
            return {**dataclasses.asdict(result.answer), "status": result.status,
                    "choices": result.choices, "drawing": drawing.metadata(), "reviewed": False}
        # Absolute local IFC/PDF files also need to survive the dataset adapter.
        file = str(p.resolve())
    try:
        rel = str(Path(file).resolve().relative_to(ROOT.resolve())) if Path(file).is_absolute() else file
    except ValueError:
        rel = file
    q = Question(path=rel if rel.startswith("data/") else file, question=question)
    ans = route(q)
    return dataclasses.asdict(ans)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stoa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("file", help="local PNG path, or drawing path under the dataset")
    a.add_argument("question")
    a.add_argument("--confirm-target", choices=("window", "door_leaf"))
    a.add_argument("--max-requests", type=int, choices=range(1, 10), default=9)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    if args.cmd == "ask":
        print(json.dumps(ask(args.file, args.question, confirmation=args.confirm_target, max_requests=args.max_requests), indent=2, ensure_ascii=False, default=str))
    else:
        from .viewer import serve
        serve(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
