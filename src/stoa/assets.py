"""Validated application drawings, independent of benchmark paths and labels."""
from __future__ import annotations

import hashlib
import re
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DrawingError(ValueError):
    pass


@dataclass(frozen=True)
class Drawing:
    id: str
    width: int
    height: int
    png: bytes = field(repr=False, compare=False)

    def metadata(self) -> dict:
        return {"id": self.id, "width": self.width, "height": self.height,
                "media_type": "image/png", "url": f"/api/assets/{self.id}"}

    def pixels(self):
        return cv2.imdecode(np.frombuffer(self.png, np.uint8), cv2.IMREAD_COLOR)


def from_bytes(payload: bytes) -> Drawing:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise DrawingError("PNG exceeds the 25 MiB upload limit")
    if len(payload) < 33 or not payload.startswith(PNG_SIGNATURE) or payload[12:16] != b"IHDR":
        raise DrawingError("Provide a PNG image; its contents, not its filename, determine the format")
    width, height = struct.unpack(">II", payload[16:24])
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise DrawingError("PNG dimensions are invalid or exceed the 40 megapixel limit")
    try:
        image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_UNCHANGED)
    except cv2.error:
        raise DrawingError("PNG could not be decoded") from None
    if image is None or image.shape[:2] != (height, width):
        raise DrawingError("PNG could not be decoded")
    if image.dtype == np.uint16:
        image = np.rint(image.astype(np.float32) / 257).astype(np.uint8)
    if image.dtype != np.uint8:
        raise DrawingError("Unsupported PNG pixel format")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255
        image = np.rint(image[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    elif image.shape[2] != 3:
        raise DrawingError("Unsupported PNG channels")
    image = np.ascontiguousarray(image)
    digest = hashlib.sha256(struct.pack(">II", width, height) + image.tobytes()).hexdigest()
    ok, normalized = cv2.imencode(".png", image)
    if not ok:
        raise DrawingError("PNG normalization failed")
    if normalized.nbytes > MAX_BYTES:
        raise DrawingError("Normalized PNG exceeds the 25 MiB limit; provide a smaller drawing")
    # Normalize encoding and strip source metadata; inference sees only pixels.
    return Drawing(digest, width, height, normalized.tobytes())


def from_path(path: str | Path) -> Drawing:
    path = Path(path).expanduser()
    if not path.is_file():
        raise DrawingError("Drawing path is not an existing file")
    if path.stat().st_size > MAX_BYTES:
        raise DrawingError("PNG exceeds the 25 MiB upload limit")
    with path.open("rb") as stream:
        return from_bytes(stream.read(MAX_BYTES + 1))


class AssetStore:
    """Content-addressed uploads; HTTP callers supply IDs, never filesystem paths."""

    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()

    def put(self, payload: bytes) -> Drawing:
        drawing = from_bytes(payload)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{drawing.id}.png"
        with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".png", delete=False) as tmp:
            tmp.write(drawing.png)
            temporary = Path(tmp.name)
        temporary.replace(target)
        return drawing

    def get(self, identifier: str) -> Drawing:
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise DrawingError("Invalid drawing ID")
        path = self.directory / f"{identifier}.png"
        # A replaced/symlinked upload must not serve files outside this store.
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise DrawingError("Invalid stored drawing")
        drawing = from_path(path)
        if drawing.id != identifier:
            raise DrawingError("Stored drawing content has changed")
        return drawing
