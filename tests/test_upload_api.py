"""Exercise upload routes over in-memory HTTP, with a controlled detector."""
import io
import json
from email.message import Message

from stoa.upload_api import UploadAPI
from test_image_runtime import image, reply


class Request:
    def __init__(self, path, body=b"", method="POST", **headers):
        self.path, self.command = path, method
        self.headers = Message()
        for key, value in {"Content-Length": str(len(body)), "Host": "127.0.0.1:8091", **headers}.items():
            self.headers[key] = value
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.response_headers = {}

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass

    def json(self):
        return json.loads(self.wfile.getvalue())


def call(api, path, data):
    request = Request(path, json.dumps(data).encode())
    assert api.handle(request)
    return request


def test_upload_question_evidence_and_corrections_roundtrip_without_dataset(tmp_path):
    api = UploadAPI(tmp_path, detect=lambda *args: reply([[100, 100, 200, 200]]))
    upload = Request("/api/uploads", image())
    assert api.handle(upload) and upload.code == 201
    drawing = upload.json()
    opened = Request(drawing["url"], method="GET")
    assert api.handle(opened) and opened.code == 200
    assert opened.response_headers["Content-Type"] == "image/png"
    result = call(api, "/api/image-questions", {"drawing": drawing["id"], "question": "Count windows"})
    assert result.code == 200 and result.json()["answer"]["value"] == 1
    assessment = result.json()
    assert assessment["answer"]["evidence"][0]["file"] == drawing["url"]
    assert assessment["detections"][0]["box"] == [20, 12, 40, 24]
    corrected = call(api, "/api/image-reviews", {"run_id": assessment["run_id"], "boxes": [], "reviewer": "Human", "confirmed_complete": True})
    assert corrected.code == 200 and corrected.json()["review"]["count"] == 0
    assert corrected.json()["machine"]["answer"]["value"] == 1
    assert api.runs[assessment["run_id"]].answer.value == 1


def test_bad_upload_budget_and_cross_origin_requests_are_rejected(tmp_path):
    api = UploadAPI(tmp_path, detect=lambda *args: reply())
    invalid = Request("/api/uploads", b"invalid")
    api.handle(invalid)
    assert invalid.code == 400
    external = Request("/api/uploads", image(), Origin="https://example.com")
    api.handle(external)
    assert external.code == 403 and not list(tmp_path.iterdir())
    invalid_budget = call(api, "/api/image-questions", {"max_requests": True})
    assert invalid_budget.code == 400
    assert "budget" in invalid_budget.json()["error"]
    expired = call(api, "/api/image-reviews", {"run_id": "expired"})
    assert expired.code == 400


def test_mount_and_page_are_independent_of_benchmark_viewer(tmp_path):
    api = UploadAPI(tmp_path)
    assert not api.handle(Request("/api/projects", method="GET"))
    page = Request("/upload", method="GET")
    assert api.handle(page) and page.code == 200
    assert b"Unreviewed model proposal" in page.wfile.getvalue()
    assert b"/api/image-reviews" in page.wfile.getvalue()
