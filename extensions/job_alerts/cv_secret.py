"""Prepare and decode compressed CV text stored as a GitHub secret."""

from __future__ import annotations

import base64
import gzip
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SECRET_NAME = "JOBFINDER_CV_GZIP_BASE64"


def encode_cv_text(text: str) -> str:
    if not text.strip():
        raise ValueError("CV text is empty")
    compressed = gzip.compress(text.encode("utf-8"), compresslevel=9)
    return base64.b64encode(compressed).decode("ascii")


def decode_cv_secret(value: str) -> str:
    if not value:
        return ""
    try:
        compressed = base64.b64decode(value, validate=True)
        return gzip.decompress(compressed).decode("utf-8")
    except Exception as exc:
        raise ValueError("JOBFINDER_CV_GZIP_BASE64 is not valid compressed CV text") from exc


def prepare_cv_file(path: Path | str) -> str:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from cv_analyzer import read_cv

    cv_path = Path(path)
    if not cv_path.is_file():
        raise FileNotFoundError(f"CV file not found: {cv_path}")
    text = read_cv(str(cv_path))
    return encode_cv_text(text)


def upload_cv_secret(path: Path | str, secret_name: str = DEFAULT_SECRET_NAME) -> None:
    encoded = prepare_cv_file(path)
    try:
        subprocess.run(
            ["gh", "secret", "set", secret_name],
            input=encoded,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "GitHub CLI (gh) is not installed; use --output to create a value for "
            "GitHub Settings > Secrets and variables > Actions"
        ) from exc
