"""OpenAI-compatible transport: NVIDIA by default, with timeout-only fallback.

Config is read at call time from env (.env, never committed):
  STOA_LLM_API_KEY (or FEATHERLESS_API_KEY), STOA_LLM_BASE_URL (any OpenAI-compatible endpoint, default Featherless),
  STOA_LLM_MODEL, STOA_LLM_MAX_REQUESTS (live-request cap per process, default 200; 0 = no live calls).
  STOA_LLM_PROVIDER=modal selects MODAL_API_KEY plus STOA_MODAL_BASE_URL/STOA_MODAL_MODEL overrides.
  NVIDIA uses NVIDIA_API_KEY plus STOA_NVIDIA_BASE_URL/STOA_NVIDIA_MODEL overrides.
  STOA_LLM_FALLBACK selects modal (default), featherless, or none for NVIDIA timeouts.
  STOA_LLM_TIMEOUT_SECONDS defaults to 60 seconds per provider attempt.
Every call is cached under .cache/llm by provider, endpoint, model, messages and generation parameters.
Cached replies are free and uncapped.
SDK retries are disabled. NVIDIA timeouts may use one secondary attempt; each live
attempt counts against the shared cap. Other failures raise LLMError directly.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from stoa.project import ROOT as PROJECT_ROOT
from pathlib import Path

from ..answer import Answer, Evidence
from ..data import Question

REPO = PROJECT_ROOT
CACHE = REPO / ".cache" / "llm"
DEFAULT_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct"
DEFAULT_BASE = "https://api.featherless.ai/v1"
DEFAULT_MAX_REQUESTS = 200
_USAGE = {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0}
_LOCK = threading.Lock()


class LLMError(RuntimeError):
    """Provider unavailable, misconfigured or over the request cap. The message says which."""


class ProviderTimeout(LLMError):
    """Only transport timeouts may activate the configured secondary provider."""


class Completion(str):
    """Backward-compatible text carrying its actual producing provider identity."""

    def __new__(cls, text, config, model, cached=False):
        value = super().__new__(cls, text)
        value.provenance = {'provider': config['provider'], 'model': model, 'cached': cached}
        return value

    def __getnewargs__(self):
        # Preserve ordinary string deepcopy/pickling used by legacy Answer exports.
        return (str(self), {'provider': self.provenance['provider']},
                self.provenance['model'], self.provenance['cached'])


def settings(provider: str | None = None) -> dict:
    """Provider settings from the environment right now (not frozen at import)."""
    _env()
    from ..providers import configuration
    try:
        return configuration(DEFAULT_MODEL, DEFAULT_BASE, DEFAULT_MAX_REQUESTS, provider=provider)
    except ValueError as exc:
        raise LLMError(str(exc)) from exc


def reset_usage() -> None:
    with _LOCK:
        for k in _USAGE:
            _USAGE[k] = 0


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
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=False)


def chat(messages: list[dict], model: str | None = None, max_tokens: int = 600, temperature: float = 0.0) -> str:
    cfg = settings()
    try:
        return _attempt(cfg, messages, model or cfg['model'], max_tokens, temperature)
    except ProviderTimeout:
        secondary = cfg['fallback_provider']
        if not secondary:
            raise
        fallback = settings(secondary)
        try:
            result = _attempt(fallback, messages, fallback['model'], max_tokens, temperature)
        except ProviderTimeout as exc:
            raise ProviderTimeout(f"{cfg['provider']} and {secondary} timed out; no further attempts") from exc
        result.provenance.update(fallback_from=cfg['provider'], fallback_reason='timeout')
        return result


def _attempt(cfg: dict, messages: list[dict], model: str, max_tokens: int, temperature: float) -> Completion:
    """One cache lookup or one bounded SDK attempt; never recursively falls back."""
    key = hashlib.sha256(json.dumps([cfg["provider"], cfg["base_url"], model, messages, max_tokens, temperature], sort_keys=True).encode()).hexdigest()
    cf = CACHE / f"{key}.txt"
    if cf.exists():
        _count(cached=1)
        return Completion(cf.read_text(), cfg, model, cached=True)
    if not cfg["api_key"]:
        raise LLMError(f"no API key: set {cfg['api_key_env']}")
    with _LOCK:  # reserve the request before sending so parallel workers cannot overshoot the cap
        if _USAGE["calls"] >= cfg["max_requests"]:
            raise LLMError(f"request cap reached ({cfg['max_requests']} live requests; raise STOA_LLM_MAX_REQUESTS)")
        _USAGE["calls"] += 1
    import openai
    client = openai.OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=cfg['timeout_seconds'], max_retries=0)
    try:
        out = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
    except openai.APITimeoutError as e:
        raise ProviderTimeout(f"{cfg['provider']} timed out") from e
    except openai.AuthenticationError as e:
        raise LLMError(f"provider rejected the API key ({cfg['base_url']}): {e}") from e
    except openai.RateLimitError as e:
        raise LLMError(f"provider rate limit or quota hit ({cfg['base_url']}); no retry attempted: {e}") from e
    except openai.APIError as e:
        if getattr(e, 'status_code', None) in {408, 504}:
            raise ProviderTimeout(f"{cfg['provider']} timed out (HTTP {e.status_code})") from e
        raise LLMError(f"provider error from {cfg['base_url']} ({type(e).__name__}): {e}") from e
    u = getattr(out, "usage", None)
    _count(prompt_tokens=getattr(u, "prompt_tokens", 0) or 0, completion_tokens=getattr(u, "completion_tokens", 0) or 0)
    text = out.choices[0].message.content or ""
    CACHE.mkdir(parents=True, exist_ok=True)
    cf.write_text(text)
    return Completion(text, cfg, model)


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
