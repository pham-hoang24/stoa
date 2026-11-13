"""LLM lane (Featherless, OpenAI-compatible): vision for raster plans, text/PDF/IFC-summary QA.

Config via env (.env, never committed): FEATHERLESS_API_KEY, STOA_LLM_MODEL, STOA_LLM_BASE_URL.
Every call is cached on disk under .cache/llm by hash of (model, messages).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from pathlib import Path

from ..answer import Answer, Evidence
from ..data import Question

REPO = Path(__file__).resolve().parents[3]
CACHE = REPO / ".cache" / "llm"
MODEL = os.environ.get("STOA_LLM_MODEL", "Qwen/Qwen3-VL-30B-A3B-Instruct")
BASE = os.environ.get("STOA_LLM_BASE_URL", "https://api.featherless.ai/v1")
_USAGE = {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0}
_LOCK = threading.Lock()


def _count(**inc: int) -> None:
    with _LOCK:
        for k, v in inc.items():
            _USAGE[k] += v


def usage() -> str:
    """One-line summary of provider use in this process (tokens are as reported by the provider)."""
    u = _USAGE
    return f"{u['calls']} calls, {u['cached']} cached, {u['prompt_tokens']}+{u['completion_tokens']} tokens"


SYSTEM_DRAWING = "You are a careful construction drawing reader."


def _env() -> None:
    f = REPO / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def chat(messages: list[dict], model: str = MODEL, max_tokens: int = 600, temperature: float = 0.0) -> str:
    key = hashlib.sha256(json.dumps([model, messages, max_tokens, temperature], sort_keys=True).encode()).hexdigest()
    cf = CACHE / f"{key}.txt"
    if cf.exists():
        _count(cached=1)
        return cf.read_text()
    _env()
    from openai import OpenAI
    client = OpenAI(base_url=BASE, api_key=os.environ["FEATHERLESS_API_KEY"], timeout=180)
    out = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
    u = getattr(out, "usage", None)
    _count(calls=1, prompt_tokens=getattr(u, "prompt_tokens", 0) or 0, completion_tokens=getattr(u, "completion_tokens", 0) or 0)
    text = out.choices[0].message.content or ""
    CACHE.mkdir(parents=True, exist_ok=True)
    cf.write_text(text)
    return text


def image_part(png: bytes, mime: str = "image/png") -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(png).decode()}"}}


def render_pdf(path: Path, dpi: int = 130, page: int = 0) -> bytes:
    import pymupdf
    with pymupdf.open(path) as doc:
        return doc[page].get_pixmap(dpi=dpi).tobytes("png")


def pdf_text(path: Path, limit: int = 12000) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(p.get_text() for p in doc)[:limit]


def kind_of(question: str, qtype: str | None) -> str:
    if qtype:
        return qtype
    ql = question.casefold()
    if re.search(r"how many|kuinka monta|wie viele|combien|quanti|hvor mange|kui palju", ql):
        return "count"
    if re.search(r"m²|area|length|volume", ql):
        return "area"
    return "text"


def parse_number(text: str):
    m = re.findall(r"ANSWER:\s*(-?\d+(?:[.,]\d+)?)", text)
    if not m:
        m = re.findall(r"-?\d+(?:[.,]\d+)?", text)
    return float(m[-1].replace(",", ".")) if m else None


def ask(question: str, kind: str, parts: list[dict], system: str = "") -> str:
    style = ("Reply with exactly one line: ANSWER: <integer>." if kind == "count"
             else "Reply with exactly one line: ANSWER: <number>." if kind in ("area", "length", "volume")
             else "Answer concisely and factually from the given data only. If the data does not contain it, say so.")
    content = [{"type": "text", "text": f"{question}\n\n{style}"}] + parts
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    return chat(msgs)


def ifc_summary(ifc_path: Path) -> str:
    import ifcopenshell
    import ifcopenshell.util.element as ue
    f = ifcopenshell.open(str(ifc_path))
    lines = [f"Schema {f.schema}"]
    for app in f.by_type("IfcApplication")[:2]:
        lines.append(f"Authoring app: {app.ApplicationFullName} {app.Version}")
    for b in f.by_type("IfcBuilding")[:1]:
        lines.append(f"Building: name={b.Name} common={ue.get_psets(b).get('Pset_BuildingCommon', {})}")
    for st in sorted(f.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0):
        els = ue.get_decomposition(st)
        counts: dict[str, int] = {}
        for e in els:
            counts[e.is_a()] = counts.get(e.is_a(), 0) + 1
        lines.append(f"Storey {st.Name!r} elevation={st.Elevation} counts={counts}")
        for sp in [e for e in els if e.is_a("IfcSpace")][:80]:
            qty = {k: v for ps in ue.get_psets(sp, qtos_only=True).values() for k, v in ps.items() if isinstance(v, float)}
            lines.append(f"  Space no={sp.Name} name={sp.LongName} qty={qty}")
    types: dict[str, int] = {}
    for cls in ("IfcDoor", "IfcWindow", "IfcWall", "IfcSlab"):
        for e in f.by_type(cls):
            t = ue.get_type(e)
            key = f"{cls}:{t.Name if t else e.ObjectType}"
            types[key] = types.get(key, 0) + 1
    lines.append(f"Types: {types}")
    return "\n".join(lines)[:14000]


def answer(q: Question, path: Path) -> Answer:
    kind = kind_of(q.question, q.type)
    ext = path.suffix.lower()
    ev = [Evidence(str(path), "whole drawing", page=0)]
    if ext in (".png", ".jpg", ".jpeg"):
        parts = [image_part(path.read_bytes(), "image/png" if ext == ".png" else "image/jpeg")]
        txt = ask(q.question, kind, parts, SYSTEM_DRAWING)
    elif ext == ".pdf":
        parts = [image_part(render_pdf(path))]
        txt = ask(q.question + f"\n\nText layer of the PDF:\n{pdf_text(path)}", kind, parts, SYSTEM_DRAWING)
    elif ext == ".ifc":
        txt = ask(q.question + f"\n\nBIM model data:\n{ifc_summary(path)}", kind, [], "You answer questions about an IFC building model from the data given.")
    else:
        return Answer(None, lane="llm", note=f"unsupported {ext}")
    if kind in ("count", "area", "length", "volume"):
        v = parse_number(txt)
        if v is not None and kind == "count":
            v = int(round(v))
        return Answer(v, q.unit, ev, "llm", txt[:120])
    return Answer(txt.strip(), None, ev, "llm")
