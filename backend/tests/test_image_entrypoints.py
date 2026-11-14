"""User entry points must work without benchmark paths or reference records."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from stoa import cli, viewer
from stoa.assets import AssetStore
from stoa.upload_api import UploadAPI
from test_image_runtime import image, reply


def test_cli_opens_external_png_by_contents_and_keeps_evidence_accessible(tmp_path, monkeypatch):
    from stoa.lanes import llm
    monkeypatch.setattr(cli, "ROOT", tmp_path / "no-dataset")
    monkeypatch.setattr(cli, "DEFAULT_DIRECTORY", tmp_path / "assets")
    monkeypatch.setattr(cli, "route", lambda *args: (_ for _ in ()).throw(AssertionError("PNG must bypass benchmark routing")))
    monkeypatch.setattr(llm, "chat", lambda *args, **kwargs: reply([[100, 100, 200, 200]]))
    file = tmp_path / "ifc_models" / "new drawing.bin"
    file.parent.mkdir()
    file.write_bytes(image())
    answer = cli.ask(str(file), "Count windows", max_requests=1)
    assert answer["value"] == 1 and answer["status"] == "unreviewed"
    identifier = answer["drawing"]["id"]
    assert AssetStore(tmp_path / "assets").get(identifier).width == 200
    assert answer["evidence"][0]["file"] == f"/api/assets/{identifier}"


def test_cli_clarifies_door_unit_then_uses_confirmation(tmp_path, monkeypatch):
    from stoa.lanes import llm
    monkeypatch.setattr(cli, "DEFAULT_DIRECTORY", tmp_path / "assets")
    calls = []
    monkeypatch.setattr(llm, "chat", lambda *args, **kwargs: calls.append(1) or reply())
    file = tmp_path / "drawing.png"
    file.write_bytes(image())
    first = cli.ask(str(file), "Count doors")
    assert first["value"] is None and first["choices"] == ("door_leaf",) and not calls
    confirmed = cli.ask(str(file), "Count doors", confirmation="door_leaf")
    assert confirmed["value"] == 0 and calls == [1]


def test_shared_viewer_mounts_upload_inspection_and_review(tmp_path, monkeypatch):
    monkeypatch.setattr(viewer.H, "uploads", UploadAPI(tmp_path, detect=lambda *args: reply([[100, 100, 200, 200]])))
    server = ThreadingHTTPServer(("127.0.0.1", 0), viewer.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, data=None):
        payload = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
        with urllib.request.urlopen(urllib.request.Request(base + path, data=payload)) as response:
            return response.read()

    try:
        assert b"Open a floor plan" in request("/upload")
        assert b'href="/upload"' in request("/")
        drawing = json.loads(request("/api/uploads", image()))
        assert request(drawing["url"]).startswith(b"\x89PNG")
        machine = json.loads(request("/api/image-questions", {"drawing": drawing["id"], "question": "Count windows"}))
        corrected = json.loads(request("/api/image-reviews", {"run_id": machine["run_id"], "boxes": [], "reviewer": "Human", "confirmed_complete": True}))
        assert corrected["review"]["count"] == 0 and corrected["machine"]["answer"]["value"] == 1
    finally:
        server.shutdown()
        server.server_close()
