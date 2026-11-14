"""Locate repository resources while keeping installed CLI paths predictable."""
import os
from pathlib import Path

def project_root():
    override = os.environ.get("STOA_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "backend").is_dir():
            return parent
    return Path.cwd()

ROOT = project_root()
