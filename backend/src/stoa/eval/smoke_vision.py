"""Tiny live smoke check of the vision lane against the real provider. NOT an accuracy eval.

    python -m stoa.eval.smoke_vision [-n 5]

Sends at most n live requests (hard cap via STOA_LLM_MAX_REQUESTS, no retries) on door/window questions and
prints truth vs prediction plus usage. A handful of samples proves the prompt and parsing work end to end; it is
far too few to report an accuracy figure, and none is reported.
"""
from __future__ import annotations

import argparse
import os

from ..data import load_questions
from ..lanes import llm, vision
from ..router import answer


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=5, help="number of questions (= max live requests)")
    a = ap.parse_args(argv)
    os.environ["STOA_LLM_MAX_REQUESTS"] = str(a.n)
    qs = [q for q in load_questions() if q.source == "cubicasa5k" and vision.classify(q.question)[1] == "detect"
          and q.question.startswith("How many")][: a.n]
    for q in qs:
        r = answer(q)
        print(f"{q.path.split('/')[-1]:24} truth={q.answer!s:4} pred={r.value!s:5} boxes={len(r.evidence)} {r.abstain or ''} {r.note}")
    print(f"SMOKE ONLY, no accuracy claimed. llm: {llm.usage()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
