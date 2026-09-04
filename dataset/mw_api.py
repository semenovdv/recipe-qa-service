"""Thin MediaWiki API client used by the ingestion pipeline.

I/O is intentionally isolated here (dataset/PLAN.md §2): every other module is
pure and testable without network. Politeness rules follow Wikimedia policy:
descriptive User-Agent, timeouts, bounded retries with backoff.
"""

from __future__ import annotations

import time
from typing import Any

import requests

API_URL = "https://en.wikibooks.org/w/api.php"
USER_AGENT = (
    "RecipeQAService-ingestion/1.0 "
    "(https://github.com/semenovdv/recipe-qa-service; take-home assignment) "
    "requests/" + requests.__version__
)
TIMEOUT_SECONDS = 15.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
DELAY_BETWEEN_REQUESTS_SECONDS = 0.5


class MediaWikiError(RuntimeError):
    """Raised when the API cannot be reached or returns an error response."""


def _get(session: requests.Session, params: dict[str, str]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise MediaWikiError(
                    f"API error: {payload['error'].get('info', payload['error'])}"
                )
            time.sleep(DELAY_BETWEEN_REQUESTS_SECONDS)
            return payload
        except (requests.RequestException, MediaWikiError, ValueError) as error:
            last_error = error
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
    raise MediaWikiError(f"request failed after {MAX_RETRIES} attempts: {last_error}")


def list_category_members(
    session: requests.Session, category: str, limit: int = 500
) -> list[dict[str, Any]]:
    """List all pages (namespace 102 = Cookbook) in one category.

    Handles API continuation. Returns raw member dicts with pageid/title/ns.
    """
    members: list[dict[str, Any]] = []
    continuation: dict[str, str] | None = None
    while True:
        params: dict[str, str] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "page",
            "cmnamespace": "102",  # Cookbook namespace
            "cmlimit": str(min(limit, 500)),
            "format": "json",
            "formatversion": "2",
        }
        if continuation:
            params.update(continuation)
        payload = _get(session, params)
        batch = payload.get("query", {}).get("categorymembers", [])
        members.extend(batch)
        continuation = payload.get("continue")
        if not continuation:
            return members


def fetch_pages(session: requests.Session, pageids: list[int]) -> list[dict[str, Any]]:
    """Fetch current revision content for the given pageids (batched)."""
    pages: list[dict[str, Any]] = []
    for start in range(0, len(pageids), 10):
        batch = pageids[start : start + 10]
        params: dict[str, str] = {
            "action": "query",
            "prop": "revisions",
            "pageids": "|".join(str(pageid) for pageid in batch),
            "rvprop": "content|ids|timestamp",
            "rvslots": "main",
            "format": "json",
            "formatversion": "2",
        }
        payload = _get(session, params)
        pages.extend(payload.get("query", {}).get("pages", []))
    return pages
