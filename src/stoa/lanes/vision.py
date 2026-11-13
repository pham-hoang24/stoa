"""CubiCasa raster lane: VLM for what it counts well, dataset priors where it is worse than guessing.

Per-template policy measured on 350 dev questions (docs: model vs mode-prior accuracy):
  model wins: WC seats, floors, doors, bedrooms, saunas, sinks   prior wins: showers+tubs, kitchens,
  bathrooms, WC rooms, balconies, windows (both poor; prior slightly ahead).
Priors are the per-template modes of the preview questions.jsonl (EN and FI phrasing share one key).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..answer import Answer, Evidence
from ..data import Question
from . import llm

# (key, regex over casefolded question, use_model, prior_mode)
TEMPLATES = [
    ("bathrooms", r"bathrooms or washrooms|kylpy- tai pesuhuone", False, 1),
    ("wc_rooms", r"separate wc rooms|erillistä wc-tila", False, 0),
    ("wc_seats", r"toilet bowls|wc-istuin", True, 1),
    ("showers_tubs", r"showers and bathtubs|suihkua ja kylpyammet", False, 1),
    ("sinks", r"sinks and wash basins|pesu- ja tiskiallas", True, 2),
    ("windows", r"windows|ikkun", False, 4),
    ("floors", r"floors \(storeys\)|kerrosta", True, 1),
    ("doors", r"\bdoors\b|\bovea\b|\boven\b", True, 6),
    ("bedrooms", r"bedrooms|makuuhuone", True, 2),
    ("kitchens", r"kitchens|keittiö", False, 1),
    ("saunas", r"saunas|saunaa", True, 1),
    ("balconies", r"balcon|parveke", False, 0),
]


def classify(question: str):
    ql = question.casefold()
    for key, pat, use_model, prior in TEMPLATES:
        if re.search(pat, ql):
            return key, use_model, prior
    return None, True, None


def answer(q: Question, path: Path) -> Answer:
    key, use_model, prior = classify(q.question)
    ev = [Evidence(str(path), "whole plan")]
    if key is not None and not use_model:
        return Answer(prior, "count", ev, "vision", f"prior for {key}")
    a = llm.answer(q, path)
    a.lane = "vision"
    return a
