from __future__ import annotations

import base64
from pathlib import Path


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def looks_like_image(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def extract_text(path: Path) -> str:
    """Best-effort text view of the uploaded file. Images stay as a placeholder label."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".html", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    if looks_like_image(path):
        return f"[image:{path.name}]"
    return path.read_text(encoding="utf-8", errors="replace")
