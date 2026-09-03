"""Application settings via pydantic-settings.

Environment variables are the only secret transport (see .env.example and
the key-layout rules there). ``.env`` is read for local dev convenience;
real environment variables take precedence, so CI/platform injection and
test monkeypatching override the file.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI (extraction + generation + embeddings; ADR-001/002)
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"

    # Postgres + pgvector (ADR-003)
    database_url: str = ""

    # Corpus location for /health and vocabularies
    corpus_index_path: str = "dataset/corpus/index.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
