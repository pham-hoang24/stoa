"""Dataset access. Dataset root is the ./dataset symlink (override: STOA_DATASET)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("STOA_DATASET", Path(__file__).resolve().parents[2] / "dataset"))


@dataclass
class Question:
    path: str  # as in questions.jsonl, e.g. data/swiss_dwellings/x.pdf
    question: str
    answer: float | int | str | None = None
    unit: str | None = None
    type: str | None = None

    @property
    def source(self) -> str:
        return self.path.split("/")[1]

    @property
    def abspath(self) -> Path:
        return ROOT / self.path


def load_questions(path: Path | None = None) -> list[Question]:
    p = path or ROOT / "questions.jsonl"
    with open(p, encoding="utf-8") as fh:
        return [Question(**json.loads(line)) for line in fh if line.strip()]


def sibling(path: Path, *exts: str) -> Path | None:
    """Same drawing in another format (same stem, other extension)."""
    for e in exts:
        c = path.with_suffix(e)
        if c.exists():
            return c
    return None
