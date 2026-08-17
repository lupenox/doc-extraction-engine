from __future__ import annotations

from pathlib import Path

from celery.utils.log import get_task_logger

from core.extractor import extract_invoice
from db.repository import complete_job, fail_job
from workers.celery_app import celery_app

logger = get_task_logger(__name__)


def run_extraction(task_id: str, path: str) -> dict:
    try:
        invoice = extract_invoice(Path(path))
        complete_job(task_id, invoice)
        return {"task_id": task_id, "needs_review": invoice.needs_review}
    except Exception as exc:  # noqa: BLE001
        logger.exception("extraction failed")
        fail_job(task_id, str(exc))
        raise


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def extract_document(self, task_id: str, path: str) -> dict:
    return run_extraction(task_id, path)
