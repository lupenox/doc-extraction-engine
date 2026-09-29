from __future__ import annotations

import re
import uuid
from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from config import get_settings
from db.repository import create_job, get_job, list_review_queue, resolve_review
from workers.celery_tasks import extract_document, run_extraction

router = APIRouter()

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_upload_name(filename: str | None) -> str:
    """Reduce a client-supplied filename to a safe basename, or raise 400."""
    raw = (filename or "").replace("\x00", "")
    # Strip any POSIX or Windows directory components ("a/b.txt", "..\\x.txt").
    name = PureWindowsPath(Path(raw).name).name.strip()
    name = _UNSAFE_CHARS.sub("_", name).lstrip(".")
    if not name:
        raise HTTPException(status_code=400, detail="A filename is required")
    if len(name) > 200:
        path = Path(name)
        name = path.stem[: 200 - len(path.suffix)] + path.suffix
    return name


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/extract")
async def extract(background: BackgroundTasks, file: UploadFile = File(...)):
    settings = get_settings()
    filename = safe_upload_name(file.filename)
    suffix = Path(filename).suffix.lower()
    allowed = {ext.lower() for ext in settings.allowed_extensions}
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {suffix or '(none)'}; allowed: {', '.join(sorted(allowed))}",
        )

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds {settings.max_upload_bytes} bytes"
        )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    upload_dir = settings.upload_dir.resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex
    dest = (upload_dir / f"{task_id}_{filename}").resolve()
    if dest.parent != upload_dir:  # defence in depth; safe_upload_name already prevents this
        raise HTTPException(status_code=400, detail="Invalid filename")
    dest.write_bytes(data)
    create_job(task_id, filename)

    if settings.worker_backend == "celery":
        extract_document.delay(task_id, str(dest))
    else:
        background.add_task(run_extraction, task_id, str(dest))

    return JSONResponse(status_code=202, content={"task_id": task_id, "status": "queued"})


@router.get("/status/{task_id}")
async def status(task_id: str) -> dict:
    job = get_job(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown task")
    return job


@router.get("/review-queue")
async def review_queue() -> list[dict]:
    return list_review_queue()


@router.post("/review-queue/{item_id}/resolve")
async def resolve(item_id: int) -> dict:
    if not resolve_review(item_id):
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"id": item_id, "status": "resolved"}
