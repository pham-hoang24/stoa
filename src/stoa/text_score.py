"""Conservative local text proxy, also usable on existing eval JSONL dumps.

This is normalized exact matching plus explicit unavailability matching. It is
not a semantic grader: correct paraphrases or differently formatted inventories
can fail. Numeric overlap alone never establishes correctness. Keeping this
separate leaves numeric regression gates and the shared eval runner unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def normalize(text) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKC", str(text)).casefold().replace("−", "-")
    return tuple(re.findall(r"[+-]?\d+(?:\.\d+)?|[^\W\d_]+|[%°]", value))


def unavailable(text) -> bool:
    if text is None:
        return True
    value = unicodedata.normalize("NFKC", str(text)).casefold().strip()
    # Mixed references ("unavailable, however estimated at 66 m2") are not
    # abstentions. Nor is a positive answer that mentions one missing field.
    if not value or re.search(r"\d|\b(?:however|but|estimate\w*|likely|inferred|manual\w*|based on)\b", value):
        return False
    if len(value) > 700:
        return False
    pattern = (r"not (?:explicitly |directly )?(?:available|provided|defined|specified|included)"
               r"|no\b.{0,80}\b(?:information|data)\b|cannot be determined")
    sentences = [s.strip() for s in re.split(r"[.!?;\n]+", value) if s.strip()]
    if not sentences or not re.search(pattern, sentences[0]) or ":" in value:
        return False
    return all(re.search(r"\b(?:not|no|cannot|requires|empty|absent|unavailable|missing)\b", s)
               for s in sentences)


def correct_text(truth, pred) -> bool:
    if unavailable(truth):
        return unavailable(pred)
    if pred is None or unavailable(pred):
        return False
    expected = normalize(truth)
    return bool(expected) and expected == normalize(pred)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="JSONL from stoa.eval.run --dump")
    args = parser.parse_args(argv)
    records = [json.loads(line) for line in args.dump.read_text().splitlines() if line.strip()]
    attempted = [r for r in records if r.get("attempted", True)]
    ok = sum(correct_text(r["truth"], r["pred"]) for r in attempted)
    print(f"text proxy: {ok}/{len(attempted)} normalized/abstention matches; "
          f"{len(records) - len(attempted)} not attempted")
    print("Conservative local proxy, not semantic accuracy or held-out performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
