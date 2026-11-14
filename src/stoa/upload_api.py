"""Dataset-free upload routes, ready to mount in the shared local viewer.

The module entry point is a loopback-only integration preview until the viewer
owner hands off integration. Assets persist locally; assessments expire on restart.
"""
from __future__ import annotations

import argparse
import json
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .assets import MAX_BYTES, AssetStore
from .image_review import review
from .image_runtime import assess, provider


class UploadAPI:
    def __init__(self, directory: Path, detect=provider):
        self.assets = AssetStore(directory)
        self.detect = detect
        self.runs = OrderedDict()
        self.lock = threading.Lock()
        self.inference = threading.BoundedSemaphore(1)

    def question(self, data):
        if not isinstance(data, dict):
            raise ValueError("Provide a question request object")
        budget = data.get("max_requests", 9)
        if type(budget) is not int or not 1 <= budget <= 9:
            raise ValueError("Request budget must be an integer from 1 to 9")
        drawing = self.assets.get(data.get("drawing"))
        if not self.inference.acquire(blocking=False):
            raise ValueError("An image inspection is already running; wait for it to finish")
        try:
            result = assess(drawing, data.get("question"), confirmation=data.get("confirmation"),
                            max_requests=budget, detect=self.detect)
        finally:
            self.inference.release()
        identifier = uuid.uuid4().hex
        with self.lock:
            self.runs[identifier] = result
            # Bound retained decoded image bytes as well as entry count.
            while len(self.runs) > 1 and (len(self.runs) > 32 or sum(len(r.drawing.png) for r in self.runs.values()) > 64 * 1024 * 1024):
                self.runs.popitem(last=False)
        return {**result.payload(), "run_id": identifier}

    def correction(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("run_id"), str):
            raise ValueError("Provide a review request and run ID")
        with self.lock:
            result = self.runs.get(data["run_id"])
        if result is None:
            raise ValueError("Assessment expired; inspect this drawing again")
        return review(result, data.get("boxes"), data.get("reviewer"), data.get("confirmed_complete"))

    def handle(self, handler: BaseHTTPRequestHandler) -> bool:
        """Return false for unrelated paths, allowing the viewer to dispatch them."""
        path = urlsplit(handler.path).path
        if path not in ("/upload", "/api/uploads", "/api/image-questions", "/api/image-reviews") and not path.startswith("/api/assets/"):
            return False

        def respond(status, payload, content_type="application/json"):
            if content_type == "application/json":
                payload = json.dumps(payload).encode()
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(payload)))
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            handler.wfile.write(payload)

        try:
            if handler.command == "GET" and path == "/upload":
                respond(200, Path(__file__).with_name("upload_page.html").read_bytes(), "text/html; charset=utf-8")
            elif handler.command == "GET" and path.startswith("/api/assets/"):
                respond(200, self.assets.get(path.removeprefix("/api/assets/")).png, "image/png")
            elif handler.command == "POST" and path in ("/api/uploads", "/api/image-questions", "/api/image-reviews"):
                # No cross-origin requests to the local inference service.
                origin = handler.headers.get("Origin")
                if origin and origin != f"http://{handler.headers.get('Host')}":
                    respond(403, {"error": "Open this page from the local server"})
                    return True
                maximum = MAX_BYTES if path == "/api/uploads" else 512 * 1024
                length = int(handler.headers.get("Content-Length", "-1"))
                if handler.headers.get("Transfer-Encoding") or not 0 < length <= maximum:
                    raise ValueError("Missing or oversized request body")
                payload = handler.rfile.read(length)
                if len(payload) != length:
                    raise ValueError("Incomplete request body")
                if path == "/api/uploads":
                    respond(201, self.assets.put(payload).metadata())
                else:
                    data = json.loads(payload)
                    respond(200, self.question(data) if path == "/api/image-questions" else self.correction(data))
            else:
                respond(405, {"error": "Unsupported method"})
        except (ValueError, OSError) as exc:
            # Filesystem paths and provider exceptions never enter HTTP errors.
            message = str(exc) if isinstance(exc, ValueError) else "Stored drawing is unavailable"
            respond(400, {"error": message})
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--assets", type=Path, default=Path(".cache/uploads"))
    args = parser.parse_args(argv)
    api = UploadAPI(args.assets)

    class Handler(BaseHTTPRequestHandler):
        def dispatch(self):
            if not api.handle(self):
                self.send_error(404)

        do_GET = do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.timeout = 1
    print(f"Upload integration preview: http://127.0.0.1:{server.server_port}/upload", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
