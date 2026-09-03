"""Corpus metadata loader for /health — SPEC §7.2.

Read-only view over the committed dataset artifacts. This is intentionally
separate from the (future) retrieval store: /health must answer without
touching any database or model.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

DEFAULT_INDEX_PATH = os.path.join("dataset", "corpus", "index.json")


@lru_cache(maxsize=1)
def _load_index(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    version = data.get("corpus_version")
    return data if isinstance(version, str) and version else None


def corpus_version() -> str | None:
    """Return the committed corpus version, or None if unavailable."""
    path = os.environ.get("CORPUS_INDEX_PATH", DEFAULT_INDEX_PATH)
    data = _load_index(path)
    return data["corpus_version"] if data else None
