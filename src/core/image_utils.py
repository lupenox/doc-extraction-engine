from __future__ import annotations

import base64
from pathlib import Path


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def looks_like_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_MIME_TYPES


def image_mime_type(path: Path) -> str:
    return IMAGE_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def to_data_url(data: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{to_base64(data)}"


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
