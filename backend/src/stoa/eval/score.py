"""Scoring per challenge README: counts exact, area/length/volume within 2%, text free-form."""
from __future__ import annotations

import re


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def correct(qtype: str, truth, pred) -> bool:
    if pred is None:
        return False
    if qtype == "count":
        t, p = _num(truth), _num(pred)
        return t is not None and p is not None and round(p) == round(t) and abs(p - round(p)) < 1e-6
    if qtype in ("area", "length", "volume"):
        t, p = _num(truth), _num(pred)
        if t is None or p is None:
            return False
        return abs(p - t) <= 0.02 * abs(t) if t else abs(p) < 1e-9
    # text: free-form; local proxy = every number in truth appears in prediction
    nums = re.findall(r"\d+(?:\.\d+)?", str(truth))
    return bool(nums) and all(n in str(pred) for n in nums)
