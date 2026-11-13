"""Eval harness: `python -m stoa.eval.run [--source S] [--type T] [--limit N] [--split dev|test|all]`.

Split is by FILE (hash of path), never by question, so sibling questions can't leak.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import time

from ..data import load_questions
from ..router import answer, lane_for
from .score import correct


def split_of(path: str) -> str:
    return "test" if int(hashlib.md5(path.encode()).hexdigest(), 16) % 5 == 0 else "dev"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source")
    ap.add_argument("--type")
    ap.add_argument("--lane")
    ap.add_argument("--split", default="all", choices=["dev", "test", "all"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dump", help="write per-question jsonl here")
    ap.add_argument("--show-wrong", type=int, default=0)
    ap.add_argument("--min-acc", type=float, help="exit 1 if overall accuracy is below this (regression gate)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--english", action="store_true", help="skip questions with non-ASCII-heavy translations (halves LLM cost)")
    a = ap.parse_args(argv)

    qs = [q for q in load_questions()
          if (not a.source or q.source == a.source) and (not a.type or q.type == a.type)
          and (not a.lane or lane_for(q) == a.lane)
          and (a.split == "all" or split_of(q.path) == a.split)]
    if a.limit:
        qs = qs[: a.limit]
    stats = collections.defaultdict(lambda: [0, 0, 0])  # n, ok, abstain
    wrong, out = [], []
    t0 = time.time()
    if a.english:
        qs = [q for q in qs if q.question.startswith(("How", "What", "On sheet"))]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(a.workers) as ex:
        answers = list(ex.map(answer, qs))
    for q, ans in zip(qs, answers):
        ok = correct(q.type, q.answer, ans.value)
        for key in (("source", q.source), ("type", q.type), ("all", "all")):
            s = stats[key]
            s[0] += 1; s[1] += ok; s[2] += ans.value is None
        if not ok:
            wrong.append((q, ans))
        out.append({"path": q.path, "q": q.question, "truth": q.answer, "pred": ans.value, "ok": ok, "lane": ans.lane, "note": ans.note})
    for (k, v), (n, ok, ab) in sorted(stats.items(), key=lambda x: (x[0][0] != "all", x[0])):
        print(f"{k:7} {str(v):18} n={n:5} acc={ok/n:6.1%} abstain={ab/n:6.1%}")
    print(f"{time.time()-t0:.1f}s")
    for q, ans in wrong[: a.show_wrong]:
        print(f"WRONG {q.path.split('/')[-1][:32]} | {q.question[:90]} | truth={q.answer} pred={ans.value} {ans.note}")
    if a.dump:
        with open(a.dump, "w") as fh:
            fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    overall = stats[("all", "all")]
    if a.min_acc is not None and overall[0] and overall[1] / overall[0] < a.min_acc:
        print(f"FAIL: accuracy {overall[1]/overall[0]:.1%} < {a.min_acc:.1%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
