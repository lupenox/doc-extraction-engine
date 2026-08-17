from __future__ import annotations

import json
from datetime import datetime, timezone

from db.database import get_engine, get_session_factory
from db.models import Base, ExtractedRecord, ReviewItem
from schemas.invoice import ExtractedInvoice


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def create_job(task_id: str, filename: str) -> ExtractedRecord:
    init_db()
    session = get_session_factory()()
    record = ExtractedRecord(task_id=task_id, filename=filename, status="queued")
    session.add(record)
    session.commit()
    session.refresh(record)
    session.close()
    return record


def complete_job(task_id: str, invoice: ExtractedInvoice) -> ExtractedRecord:
    session = get_session_factory()()
    record = session.query(ExtractedRecord).filter_by(task_id=task_id).one()
    record.status = "review" if invoice.needs_review else "completed"
    record.needs_review = 1 if invoice.needs_review else 0
    record.payload = invoice.model_dump_json()
    record.updated_at = datetime.now(timezone.utc)
    if invoice.needs_review:
        reasons = "; ".join(issue.message for issue in invoice.issues)
        session.add(ReviewItem(task_id=task_id, reason=reasons))
    session.commit()
    session.refresh(record)
    session.close()
    return record


def fail_job(task_id: str, error: str) -> None:
    session = get_session_factory()()
    record = session.query(ExtractedRecord).filter_by(task_id=task_id).one()
    record.status = "failed"
    record.error = error
    record.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.close()


def get_job(task_id: str) -> dict | None:
    init_db()
    session = get_session_factory()()
    record = session.query(ExtractedRecord).filter_by(task_id=task_id).one_or_none()
    session.close()
    if record is None:
        return None
    return {
        "task_id": record.task_id,
        "filename": record.filename,
        "status": record.status,
        "needs_review": bool(record.needs_review),
        "result": json.loads(record.payload) if record.payload else {},
        "error": record.error,
    }


def list_review_queue() -> list[dict]:
    init_db()
    session = get_session_factory()()
    items = session.query(ReviewItem).filter_by(status="open").order_by(ReviewItem.id.desc()).all()
    session.close()
    return [
        {"id": item.id, "task_id": item.task_id, "reason": item.reason, "status": item.status}
        for item in items
    ]


def resolve_review(item_id: int) -> bool:
    session = get_session_factory()()
    item = session.query(ReviewItem).filter_by(id=item_id).one_or_none()
    if item is None:
        session.close()
        return False
    item.status = "resolved"
    record = session.query(ExtractedRecord).filter_by(task_id=item.task_id).one_or_none()
    if record is not None:
        record.status = "completed"
        record.needs_review = 0
    session.commit()
    session.close()
    return True
