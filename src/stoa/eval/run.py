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
from dataclasses import dataclass
from pathlib import Path

from ..data import load_questions
from ..lanes.llm import usage as llm_usage
from ..router import answer, lane_for
from .score import correct


BASELINE = Path(__file__).with_name("baseline.json")  # measured accuracy per --source (else --lane)
TOLERANCE = 0.005


@dataclass
class Tally:
    n: int = 0
    ok: int = 0
    abstain: int = 0
    evidenced: int = 0  # answered with at least one evidence item (presence, not validity)
    secs: float = 0.0

    @property
    def acc(self) -> float:
        return self.ok / self.n if self.n else 0.0

    @property
    def evidence_rate(self) -> float:
        answered = self.n - self.abstain
        return self.evidenced / answered if answered else 0.0


def timed(q):
    t = time.perf_counter()
    ans = answer(q)
    return ans, time.perf_counter() - t


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
    ap.add_argument("--gate", action="store_true", help=f"exit 1 if accuracy is more than {TOLERANCE:.1%} under the recorded baseline for --source/--lane")
    ap.add_argument("--update-baseline", action="store_true", help="record this run's accuracy as the baseline for --source/--lane")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--english", action="store_true", help="skip questions with non-ASCII-heavy translations (halves LLM cost)")
    a = ap.parse_args(argv)

    qs = [q for q in load_questions()
          if (not a.source or q.source == a.source) and (not a.type or q.type == a.type)
          and (not a.lane or lane_for(q) == a.lane)
          and (a.split == "all" or split_of(q.path) == a.split)]
    if a.limit:
        qs = qs[: a.limit]
    stats = collections.defaultdict(Tally)
    wrong, out = [], []
    t0 = time.time()
    if a.english:
        qs = [q for q in qs if q.question.startswith(("How", "What", "On sheet"))]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(timed, qs))
    for q, (ans, secs) in zip(qs, results):
        ok = correct(q.type, q.answer, ans.value)
        for key in (("source", q.source), ("type", q.type), ("lane", ans.lane or "none"), ("all", "all")):
            t = stats[key]
            t.n += 1
            t.ok += ok
            t.abstain += ans.value is None
            t.evidenced += ans.value is not None and bool(ans.evidence)
            t.secs += secs
        if not ok:
            wrong.append((q, ans))
        out.append({"path": q.path, "q": q.question, "truth": q.answer, "pred": ans.value, "ok": ok, "lane": ans.lane, "note": ans.note,
                    "evidence": len(ans.evidence), "secs": round(secs, 3)})
    for (k, v), t in sorted(stats.items(), key=lambda x: (x[0][0] != "all", x[0])):
        print(f"{k:7} {str(v):18} n={t.n:5} acc={t.acc:6.1%} abstain={t.abstain/t.n:6.1%} evidence={t.evidence_rate:6.1%} ms/q={1000*t.secs/t.n:7.1f}")
    print(f"{time.time()-t0:.1f}s  llm: {llm_usage()}")
    for q, ans in wrong[: a.show_wrong]:
        print(f"WRONG {q.path.split('/')[-1][:32]} | {q.question[:90]} | truth={q.answer} pred={ans.value} {ans.note}")
    if a.dump:
        with open(a.dump, "w") as fh:
            fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    overall = stats[("all", "all")]
    if a.min_acc is not None and overall.n and overall.acc < a.min_acc:
        print(f"FAIL: accuracy {overall.acc:.1%} < {a.min_acc:.1%}")
        return 1
    key = a.source or a.lane
    if (a.gate or a.update_baseline) and not (key and overall.n):
        print("FAIL: --gate/--update-baseline need --source or --lane and at least one question")
        return 1
    baselines = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    if a.update_baseline:
        baselines[key] = round(overall.acc, 3)
        BASELINE.write_text(json.dumps(baselines, indent=2, sort_keys=True) + "\n")
        print(f"baseline[{key}] = {baselines[key]:.1%}")
    elif a.gate:
        if key not in baselines:
            print(f"FAIL: no baseline for {key!r}; run with --update-baseline first")
            return 1
        if overall.acc < baselines[key] - TOLERANCE:
            print(f"FAIL: accuracy {overall.acc:.1%} < baseline {baselines[key]:.1%} - {TOLERANCE:.1%}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
