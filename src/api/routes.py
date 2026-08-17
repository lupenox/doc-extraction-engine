from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from config import get_settings
from db.repository import create_job, get_job, list_review_queue, resolve_review
from workers.celery_tasks import extract_document, run_extraction

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/extract")
async def extract(background: BackgroundTasks, file: UploadFile = File(...)):
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex
    dest = settings.upload_dir / f"{task_id}_{file.filename}"
    dest.write_bytes(await file.read())
    create_job(task_id, file.filename or dest.name)

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
