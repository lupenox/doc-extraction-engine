from __future__ import annotations

from celery import Celery

from config import get_settings

settings = get_settings()
celery_app = Celery("doc_extraction", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    include=["workers.celery_tasks"],
)
