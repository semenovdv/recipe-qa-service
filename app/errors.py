"""RFC 9457-style problem objects — SPEC §7.3.

Errors must never expose stack traces, prompts, API keys, provider
responses, or local paths. Every problem carries an opaque request_id.
"""

from __future__ import annotations

import uuid

PROBLEM_BASE = "urn:recipe-qa:problem:"


class Problem(Exception):
    """An error with a normative HTTP mapping (§7.3)."""

    def __init__(self, status: int, slug: str, title: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.request_id = uuid.uuid4().hex


def problem_body(p: Problem) -> dict:
    return {
        "type": f"{PROBLEM_BASE}{p.slug}",
        "title": p.title,
        "status": p.status,
        "detail": p.detail,
        "request_id": p.request_id,
    }


# Canonical problems used across the app (§7.3 expected statuses)


def invalid_request(detail: str) -> Problem:
    return Problem(400, "invalid-request", "Invalid request", detail)


def not_acceptable(detail: str) -> Problem:
    return Problem(406, "not-acceptable", "Not acceptable", detail)


def payload_too_large(detail: str) -> Problem:
    return Problem(413, "payload-too-large", "Payload too large", detail)


def rate_limited(detail: str = "request rate limit exceeded") -> Problem:
    return Problem(429, "rate-limited", "Too many requests", detail)


def dependency_unavailable(detail: str) -> Problem:
    return Problem(503, "dependency-unavailable", "Dependency unavailable", detail)


def internal_error(detail: str = "An internal error occurred.") -> Problem:
    return Problem(500, "internal-error", "Internal error", detail)
