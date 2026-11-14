"""Seam: stoa.viewer._safe — only existing files inside the dataset root may be served."""
import pytest

from stoa import viewer


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.pdf").write_bytes(b"x")
    (tmp_path.parent / "secret.txt").write_text("s")
    monkeypatch.setattr(viewer, "ROOT", tmp_path)
    return tmp_path


def test_serves_file_inside_root(root):
    assert viewer._safe("data/a.pdf") == (root / "data" / "a.pdf").resolve()


@pytest.mark.parametrize("rel", ["../secret.txt", "data/../../secret.txt", "/etc/passwd", "data", "data/missing.pdf", ""])
def test_rejects_escapes_dirs_and_missing(root, rel):
    assert viewer._safe(rel) is None


def test_rejects_symlink_pointing_outside(root):
    (root / "data" / "link.pdf").symlink_to(root.parent / "secret.txt")
    assert viewer._safe("data/link.pdf") is None


def test_evidence_paths_ignore_a_parent_named_data(tmp_path, monkeypatch):
    dataset = tmp_path / "data" / "preview"
    monkeypatch.setattr(viewer, "ROOT", dataset)
    assert viewer._rel(str(dataset / "data" / "swiss_dwellings" / "plan.pdf")) == "data/swiss_dwellings/plan.pdf"


# --- presentation + evidence smoke -------------------------------------------------------------

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from conftest import needs_data
from stoa import cli
from stoa.data import ROOT as DATA_ROOT

EXAMPLES = json.loads(viewer.EXAMPLES.read_text())


def test_abstention_never_looks_like_an_answer():
    p = viewer.present({"value": None, "unit": "m2", "lane": "swiss", "note": "declined: room 9.99 not found", "abstain": "declined",
                        "evidence": []}, "q")
    assert p["state"] == "abstain" and p["value"] is None and p["unit"] is None and "9.99" in p["reason"]


def test_lane_crash_is_an_error_state():
    assert viewer.present({"value": None, "lane": "swiss", "note": "error: ValueError: x", "evidence": []})["state"] == "error"


def test_ifc_note_supplies_scope_and_method():
    p = viewer.present({"value": 3, "unit": "count", "lane": "ifc", "note": "scope=model: M; method=IFC IfcDoor count", "evidence": []})
    assert p["scope"] == "model: M" and p["method"] == "IFC IfcDoor count" and p["state"] == "answer"


def test_evidence_is_numbered_dataset_relative_and_drawable_only_with_a_viewable_bbox():
    p = viewer.present({"value": 1, "lane": "vision", "evidence": [
        {"file": "/abs/dataset/data/cubicasa5k/a.png", "label": "door 1", "bbox": [1, 2, 3, 4]},
        {"file": "/abs/dataset/data/ifc_models/m.ifc", "label": "x", "bbox": None, "global_id": "G"},
        {"file": "/abs/dataset/data/swiss_dwellings/x.dxf", "label": "r", "bbox": [0, 0, 1, 1]}]})
    ev = p["evidence"]
    assert [e["n"] for e in ev] == [1, 2, 3] and ev[0]["source"] == "data/cubicasa5k/a.png"
    assert [e["drawable"] for e in ev] == [True, False, False]
    assert p["source"] == "data/cubicasa5k/a.png" and "CC BY-NC-SA" in p["licence"]


def test_raster_renders_at_pixel_scale_and_pdf_at_2x(tmp_path):
    import cv2, numpy as np
    png = tmp_path / "a.png"
    cv2.imwrite(str(png), np.zeros((50, 80, 3), np.uint8))
    assert viewer.zoom_for(png) == 1.0 and viewer.zoom_for(tmp_path / "a.pdf") == 2.0
    assert viewer.render(png)[1] == 1.0


def test_examples_cover_the_three_paths():
    assert {e["path"] for e in EXAMPLES} == {"swiss", "ifc", "vision"}


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), viewer.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return r.read(), r.headers


def png_size(b):
    import cv2, numpy as np
    h, w = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR).shape[:2]
    return w, h


def check_overlay(server, example, ans=None):
    """Ask through the real seam, then open the evidence source through the server: it must render and hold the boxes."""
    ans = ans if ans is not None else cli.ask(example["file"], example["question"])
    p = viewer.present(ans, example["question"])
    assert p["state"] == "answer", p["reason"]
    drawn = [e for e in p["evidence"] if e["drawable"] and e["source"] == p["source"]]
    assert drawn, "no drawable evidence"
    body, hdr = _get(f"{server}/api/render?file={p['source']}")
    w, h = png_size(body)
    zoom = float(hdr["X-Zoom"])
    for e in drawn:
        x0, y0, x1, y1 = e["bbox"]
        assert 0 <= x0 < x1 and 0 <= y0 < y1 and x1 * zoom <= w + 1 and y1 * zoom <= h + 1, (e["label"], e["bbox"], w, h)
    return p


@needs_data
def test_swiss_example_opens_pdf_and_overlays_room_boundary(server):
    p = check_overlay(server, next(e for e in EXAMPLES if e["path"] == "swiss"))
    assert p["source"].endswith(".pdf") and p["evidence"][0]["polygon"]


@needs_data
def test_ifc_example_opens_floor_plan_and_overlays_elements(server):
    p = check_overlay(server, next(e for e in EXAMPLES if e["path"] == "ifc"))
    assert p["source"].endswith(".pdf") and any(e["global_id"] for e in p["evidence"] if e["drawable"])


@needs_data
def test_raster_example_opens_image_and_numbers_markers(server, monkeypatch):
    from stoa.lanes import llm
    ex = next(e for e in EXAMPLES if e["path"] == "vision")
    w, h = png_size(_get(f"{server}/api/render?file={ex['file']}")[0])
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '{"detections":[{"box":[100,100,200,200]},{"box":[500,500,600,600]}]}')
    p = check_overlay(server, ex)
    assert [e["n"] for e in p["evidence"]] == [1, 2] and p["value"] == 2


def test_server_serves_examples_and_page(server):
    assert len(json.loads(_get(server + "/api/examples")[0])) == len(EXAMPLES)
    assert b"LICENSE.md" in _get(server + "/")[0]
