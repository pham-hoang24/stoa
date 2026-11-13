"""Tiny click-to-verify viewer: ask a question, see the answer and its evidence boxes on the sheet."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .data import ROOT
from .cli import ask

PAGE = (Path(__file__).parent / "viewer.html").read_text() if (Path(__file__).parent / "viewer.html").exists() else "viewer.html missing"


def _safe(rel: str) -> Path | None:
    p = (ROOT / rel).resolve()
    return p if ROOT.resolve() in p.parents and p.is_file() else None


def render(path: Path, zoom: float = 2.0) -> tuple[bytes, float]:
    import pymupdf
    with pymupdf.open(path) as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png"), zoom


class H(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if u.path == "/api/render":
            p = _safe(qs.get("file", [""])[0])
            if p is None or p.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
                return self._send(404, b"{}")
            png, zoom = render(p)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("X-Zoom", str(zoom))
            self.end_headers()
            self.wfile.write(png)
            return
        if u.path == "/api/files":
            fs = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data").rglob("*") if p.suffix.lower() in (".pdf", ".png", ".jpg", ".ifc") and p.is_file())
            return self._send(200, json.dumps(fs[:3000]).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if urlparse(self.path).path != "/api/ask":
            return self._send(404, b"{}")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if _safe(body.get("file", "")) is None:
            return self._send(400, b'{"error":"bad file"}')
        self._send(200, json.dumps(ask(body["file"], body["question"]), default=str).encode())


def serve(port: int = 8765) -> None:
    print(f"viewer on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
