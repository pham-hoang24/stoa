"""Language-agnostic helpers to pick structure out of a question."""
from __future__ import annotations

import re

_QUOTES = [
    r"«\s*(.+?)\s*»",
    r"„(.+?)[“”\"]",
    r"“(.+?)”",
    r"(?<![\w])'(.+?)'(?![\w])",
    r"\"(.+?)\"",
]


def quoted(q: str) -> list[str]:
    """All quoted strings in order of appearance."""
    hits: list[tuple[int, str]] = []
    for pat in _QUOTES:
        for m in re.finditer(pat, q):
            hits.append((m.start(), m.group(1).strip()))
    hits.sort()
    out, last_end = [], -1
    for pos, s in hits:  # drop quotes nested inside an earlier match
        if pos >= last_end:
            out.append(s)
            last_end = pos + len(s)
    return out


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold()).strip()


def has(q: str, *words: str) -> bool:
    ql = q.casefold()
    return any(w in ql for w in words)
