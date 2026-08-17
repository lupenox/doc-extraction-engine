from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import get_settings


class Base(DeclarativeBase):
    pass


_ENGINE = None
_SESSION = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        if settings.database_url.startswith("sqlite"):
            from pathlib import Path

            db_path = settings.database_url.replace("sqlite:///", "", 1)
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _ENGINE = create_engine(settings.database_url, future=True, connect_args=connect_args)
    return _ENGINE


def get_session_factory():
    global _SESSION
    if _SESSION is None:
        _SESSION = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SESSION


def reset_engine() -> None:
    global _ENGINE, _SESSION
    _ENGINE = None
    _SESSION = None
