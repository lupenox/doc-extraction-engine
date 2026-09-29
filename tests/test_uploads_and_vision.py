import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import core.extractor as extractor
from api.main import create_app
from api.routes import safe_upload_name
from config import Settings, get_settings
from db.database import reset_engine

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
CLEAN = (SAMPLES / "invoice_clean.txt").read_bytes()
LLM_JSON = {
    "vendor_name": "Pixel Vendor",
    "invoice_number": "IMG-7",
    "line_items": [],
    "subtotal": "10.00",
    "tax": "0.00",
    "total": "10.00",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'extract.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("WORKER_BACKEND", "inline")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "2048")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens: heuristic path
    get_settings.cache_clear()
    reset_engine()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()
    reset_engine()


def _upload(client, name, data=CLEAN, content_type="text/plain"):
    return client.post("/extract", files={"file": (name, data, content_type)})


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("invoice.txt", "invoice.txt"),
        ("a/b.txt", "b.txt"),
        ("../evil.txt", "evil.txt"),
        ("../../../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\windows\\evil.txt", "evil.txt"),
        ("/abs/path/inv.pdf", "inv.pdf"),
        ("my invoice (1).pdf", "my_invoice_1_.pdf"),
        (".hidden.txt", "hidden.txt"),
    ],
)
def test_safe_upload_name(name, expected):
    assert safe_upload_name(name) == expected


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "../", "a/..", "\x00"])
def test_safe_upload_name_rejects_empty(name):
    with pytest.raises(Exception) as excinfo:
        safe_upload_name(name)
    assert getattr(excinfo.value, "status_code", None) == 400


def test_safe_upload_name_keeps_extension_when_truncating():
    name = safe_upload_name("x" * 500 + ".pdf")
    assert len(name) == 200 and name.endswith(".pdf")


@pytest.mark.parametrize("name", ["a/b.txt", "../evil.txt", "../../outside.txt"])
def test_path_like_filenames_no_longer_500(client, tmp_path, name):
    response = _upload(client, name)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]

    uploads = tmp_path / "uploads"
    stored = list(uploads.iterdir())
    assert [p.name for p in stored] == [f"{task_id}_{Path(name).name}"]
    # Nothing escaped the upload directory.
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "outside.txt").exists()

    status = client.get(f"/status/{task_id}").json()
    assert status["filename"] == Path(name).name
    assert status["status"] in {"completed", "review"}


def test_dotdot_filename_is_rejected(client):
    assert _upload(client, "..").status_code == 400


def test_disallowed_extension_is_rejected(client):
    response = _upload(client, "payload.exe", b"MZ...", "application/octet-stream")
    assert response.status_code == 415
    assert "Unsupported file type .exe" in response.json()["detail"]


def test_missing_extension_is_rejected(client):
    assert _upload(client, "README").status_code == 415


def test_oversized_upload_is_rejected(client, tmp_path):
    response = _upload(client, "big.txt", b"x" * 2049)
    assert response.status_code == 413
    assert not (tmp_path / "uploads").exists() or not any((tmp_path / "uploads").iterdir())


def test_empty_upload_is_rejected(client):
    assert _upload(client, "empty.txt", b"").status_code == 400


def _capture_llm(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(LLM_JSON)}}]}
        )

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(extractor.httpx, "Client", fake_client)
    return captured


def test_image_upload_is_sent_to_vision_model(tmp_path, monkeypatch):
    captured = _capture_llm(monkeypatch)
    image_bytes = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    image = tmp_path / "scan.png"
    image.write_bytes(image_bytes)
    settings = Settings(_env_file=None, vision_model="qwen2.5vl:7b")

    invoice = extractor.extract_invoice(image, settings)

    assert invoice.vendor_name == "Pixel Vendor"
    payload = captured["payload"]
    assert payload["model"] == "qwen2.5vl:7b"
    user_content = payload["messages"][1]["content"]
    assert isinstance(user_content, list)
    text_part = next(part for part in user_content if part["type"] == "text")
    image_part = next(part for part in user_content if part["type"] == "image_url")
    assert "attached as an image" in text_part["text"]
    expected = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    assert image_part["image_url"]["url"] == expected


def test_jpeg_uses_jpeg_mime_type(tmp_path, monkeypatch):
    captured = _capture_llm(monkeypatch)
    image = tmp_path / "scan.JPG"
    image.write_bytes(b"\xff\xd8\xff-fake")
    extractor.extract_invoice(image, Settings(_env_file=None))
    parts = captured["payload"]["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_text_upload_sends_text_only(tmp_path, monkeypatch):
    captured = _capture_llm(monkeypatch)
    doc = tmp_path / "invoice.txt"
    doc.write_bytes(CLEAN)
    extractor.extract_invoice(doc, Settings(_env_file=None))
    user_content = captured["payload"]["messages"][1]["content"]
    assert isinstance(user_content, str)
    assert "Document text:" in user_content
    assert "INV-1042" in user_content
