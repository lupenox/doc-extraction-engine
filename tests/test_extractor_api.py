from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from config import get_settings
from core.extractor import heuristic_extract
from db.database import reset_engine


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_heuristic_extracts_clean_invoice():
    text = (SAMPLES / "invoice_clean.txt").read_text(encoding="utf-8")
    invoice = heuristic_extract(text)
    assert invoice.vendor_name == "Northline Supplies"
    assert invoice.invoice_number == "INV-1042"
    assert len(invoice.line_items) == 2
    assert invoice.needs_review is False


def test_heuristic_flags_mismatch_and_missing_vendor():
    mismatch = heuristic_extract((SAMPLES / "invoice_math_mismatch.txt").read_text(encoding="utf-8"))
    assert mismatch.needs_review
    missing = heuristic_extract((SAMPLES / "receipt_missing_vendor.txt").read_text(encoding="utf-8"))
    assert missing.vendor_name is None
    assert missing.needs_review


@pytest.fixture
def client(tmp_path, monkeypatch):
    get_settings.cache_clear()
    reset_engine()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'extract.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("WORKER_BACKEND", "inline")
    get_settings.cache_clear()
    reset_engine()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()
    reset_engine()


def test_extract_returns_202_and_review_queue(client: TestClient):
    files = {"file": ("invoice_math_mismatch.txt", (SAMPLES / "invoice_math_mismatch.txt").read_bytes(), "text/plain")}
    response = client.post("/extract", files=files)
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    status = client.get(f"/status/{task_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] in {"review", "completed"}
    assert body["needs_review"] is True

    queue = client.get("/review-queue").json()
    assert any(item["task_id"] == task_id for item in queue)
