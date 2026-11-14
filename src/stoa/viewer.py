"""Tiny click-to-verify viewer: ask a question, see the answer and its evidence boxes on the sheet."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .data import ROOT
from .cli import ask
from .assets import DEFAULT_DIRECTORY
from .upload_api import UploadAPI

PAGE = (Path(__file__).parent / "viewer.html").read_text() if (Path(__file__).parent / "viewer.html").exists() else "viewer.html missing"
EXAMPLES = Path(__file__).resolve().parents[2] / "viewer" / "examples.json"
RASTER = (".png", ".jpg", ".jpeg")
# Licence per dataset source (dataset/README.md); per-file credit lives in data/<source>/LICENSE.md and must stay visible.
LICENCES = {
    "cubicasa5k": "CC BY-NC-SA 4.0 (CubiCasa5K, (c) 2019 CubiCasa), non-commercial use only",
    "swiss_dwellings": "CC BY 4.0 (Swiss Dwellings)",
    "opening_design": "CC BY-SA 4.0 / MIT",
    "ifc_models": "per file, see data/ifc_models/LICENSE.md",
    "ifc_bench": "per file, see data/ifc_bench/LICENSE.md",
}
METHODS = {"swiss": "Rules on the DXF sibling (no LLM)", "ifc": "IFC model data (no LLM)",
           "vision": "VLM box detections, validated and counted in code", "llm": "LLM free-text reading"}


def _safe(rel: str) -> Path | None:
    p = (ROOT / rel).resolve()
    return p if ROOT.resolve() in p.parents and p.is_file() else None


def zoom_for(path: Path) -> float:
    """PDF/SVG evidence is in 72-point page units (render at 2x); raster evidence is in source pixels (render at 1x)."""
    return 1.0 if path.suffix.lower() in RASTER else 2.0


def render(path: Path, zoom: float | None = None) -> tuple[bytes, float]:
    import pymupdf
    zoom = zoom_for(path) if zoom is None else zoom
    with pymupdf.open(path) as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png"), zoom


def _rel(file: str) -> str:
    """Dataset-relative path ('data/...') of an evidence file, whatever form the lane stored."""
    try:
        return str(Path(file).resolve().relative_to(ROOT.resolve()))
    except ValueError:
        # A dataset can itself live under a parent named data/. Match the
        # innermost source directory rather than that unrelated parent.
        i = file.rfind("/data/")
        return file[i + 1:] if i >= 0 else file


def _note_fields(note: str) -> dict:
    """IFC notes are 'k=v; k=v' (scope=..., method=...)."""
    out = {}
    for part in note.split("; "):
        k, eq, v = part.partition("=")
        if eq and k.isidentifier():
            out[k] = v
    return out


def present(ans: dict, question: str = "") -> dict:
    """Everything the page shows for one answer. An abstention has state 'abstain' and no value, ever."""
    value = ans.get("value")
    note = ans.get("note") or ""
    fields = _note_fields(note)
    lane = ans.get("lane") or ""
    evidence = []
    for i, e in enumerate(ans.get("evidence") or [], 1):
        src = _rel(e.get("file") or "")
        evidence.append({"n": i, "label": e.get("label") or "", "source": src, "page": e.get("page"), "bbox": e.get("bbox"),
                         "polygon": e.get("polygon"), "global_id": e.get("global_id"),
                         "drawable": bool(e.get("bbox")) and src.lower().endswith((".pdf", ".svg") + RASTER)})
    sources = [x["source"] for x in evidence]
    first_drawn = next((x["source"] for x in evidence if x["drawable"]), sources[0] if sources else "")
    state = "answer" if value is not None else "abstain"
    if note.startswith("error:"):
        state = "error"
    src_name = first_drawn.split("/")[1] if first_drawn.count("/") >= 1 else ""
    return {"state": state, "value": value if state == "answer" else None, "unit": ans.get("unit") if state == "answer" else None,
            "question": question, "lane": lane, "abstain": ans.get("abstain"),
            "reason": note if state != "answer" else "",
            "method": fields.get("method") or METHODS.get(lane, lane),
            "scope": fields.get("scope") or (f"this drawing ({first_drawn.rsplit('/', 1)[-1]})" if first_drawn else "this drawing"),
            "note": note, "source": first_drawn, "licence": LICENCES.get(src_name, "see data/<source>/LICENSE.md"),
            "evidence": evidence}


class H(BaseHTTPRequestHandler):
    uploads = UploadAPI(DEFAULT_DIRECTORY)

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.uploads.handle(self):
            return
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if u.path == "/api/render":
            p = _safe(qs.get("file", [""])[0])
            if p is None or p.suffix.lower() not in (".pdf", ".svg") + RASTER:
                return self._send(404, b"{}")
            png, zoom = render(p)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("X-Zoom", str(zoom))
            self.end_headers()
            self.wfile.write(png)
            return
        if u.path == "/api/examples":
            return self._send(200, EXAMPLES.read_bytes() if EXAMPLES.exists() else b"[]")
        if u.path == "/api/files":
            fs = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data").rglob("*") if p.suffix.lower() in (".pdf", ".png", ".jpg", ".ifc") and p.is_file())
            return self._send(200, json.dumps(fs[:3000]).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if self.uploads.handle(self):
            return
        if urlparse(self.path).path != "/api/ask":
            return self._send(404, b"{}")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if _safe(body.get("file", "")) is None:
            return self._send(400, b'{"error":"bad file"}')
        self._send(200, json.dumps(present(ask(body["file"], body["question"]), body["question"]), default=str).encode())


def serve(port: int = 8765) -> None:
    print(f"Open your PNG: http://127.0.0.1:{port}/upload", flush=True)
    print(f"Dataset examples: http://127.0.0.1:{port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
