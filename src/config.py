from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    worker_backend: str = "inline"
    redis_url: str = "redis://127.0.0.1:6379/0"
    database_url: str = "sqlite:///data/extraction.db"
    upload_dir: Path = Path("data/uploads")

    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    vision_model: str = "qwen2.5vl:7b"
    llm_api_key: str = "ollama"
    amount_tolerance: float = 0.01

    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
