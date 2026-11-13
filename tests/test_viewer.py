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
