"""Extraction stage — question → QueryPlan (ADR-001 D1/D2).

`gpt-5.6-luna` at `reasoning_effort="none"` with Structured Outputs; the
response model is the Pydantic ``QueryPlan`` (single source of truth — the
same class validates and generates the strict schema).

Failure handling per ADR-001 D2: an invalid or out-of-vocabulary plan gets
**one** retry with the validator error appended to the conversation; a
second failure raises ``ExtractionError`` — mapped upstream to the honest
503 ``error`` path, never to a fabricated answer or refusal. Provider
errors (network, auth) are not converted into plan errors; they propagate.
"""
from __future__ import annotations

from typing import Any

from app.query_plan import FilterSpecError, QueryPlan, normalize_plan, parse_plan

MAX_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "You translate a user's cooking question into a structured search plan. "
    "Extract hard requirements ONLY when the question states them explicitly: "
    "diet (vegetarian/vegan/gluten-free/halal/kosher), maximum cooking time in "
    "minutes, specific ingredients that must be present, cuisine, dish type, "
    "or servings. Use the typed requirement format: field/op/value. "
    "For time expressions like 'under 30 minutes' use time_minutes lte. "
    "Never invent requirements the user did not state. "
    "search_query is a short keyword phrase for relevance ranking, not a sentence."
)


def build_messages(question: str, error_hint: str | None = None) -> list[dict]:
    """Conversation for the extraction call; error_hint feeds the retry."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    if error_hint:
        messages.append({
            "role": "user",
            "content": f"Your previous plan was rejected: {error_hint}. "
                       f"Return a corrected plan in the same JSON format.",
        })
    return messages


class ExtractionError(Exception):
    """The model could not produce a valid in-vocabulary QueryPlan."""


def _validate(raw: Any, vocabularies: dict[str, set[str]] | None) -> QueryPlan:
    plan = parse_plan(raw)
    if vocabularies:
        plan = normalize_plan(plan, vocabularies)
    return plan


def extract_plan(
    question: str,
    client: Any | None = None,
    vocabularies: dict[str, set[str]] | None = None,
) -> QueryPlan:
    """Run the extraction call and return a validated, normalized plan.

    ``client`` is an OpenAI-compatible client (injected for tests; defaults
    to a real ``OpenAI()`` instance configured via app.settings).
    """
    if client is None:
        from openai import OpenAI

        from app.settings import get_settings

        settings = get_settings()
        client = OpenAI(api_key=settings.openai_api_key or None)

    error_hint: str | None = None
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.chat.completions.parse(
                model="gpt-5.6-luna",
                messages=build_messages(question, error_hint),
                response_model=QueryPlan,
                reasoning_effort="none",
            )
            return _validate(response.choices[0].message.parsed, vocabularies)
        except (FilterSpecError, ValueError) as exc:
            # Invalid plan shape or out-of-vocabulary value: one fed retry.
            error_hint = str(exc)
            last_error = exc
        except (TypeError, KeyError) as exc:
            # Provider SDK contract violated — treat as infrastructure.
            raise RuntimeError(f"extraction call failed: {exc}") from exc

    raise ExtractionError(
        f"extraction failed after {MAX_ATTEMPTS} attempts: {last_error}"
    )
