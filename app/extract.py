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
PROMPT_VERSION = "extract-v4"

_SYSTEM_PROMPT = (
    "You classify the user's primary intent and translate it into a structured recipe search plan.\n"
    "intent must be exactly one of: recipe, out_of_domain, safety.\n"
    "Use recipe for requests seeking cookbook recipes, ingredients, steps, or explicit facts "
    "about recipes. Use out_of_domain when the primary request is not about recipes or cooking, "
    "including unrelated topics or unsupported operations. Use safety for requests asking you "
    "to certify, guarantee, assess, or infer safety, allergens, contamination, spoilage, "
    "medical suitability, or safe doneness. Classify the meaning even when it is indirect, "
    "paraphrased, or does not use obvious keywords; do not rely on literal word matching.\n"
    "If a request mixes recipe help with a safety assessment, safety takes precedence.\n"
    "For intent=out_of_domain or intent=safety, set search_query to an empty string and "
    "requirements to an empty list. intent_reason is a short internal explanation.\n"
    "Allowed requirement fields EXACTLY as written (field | op | value shape):\n"
    "- ingredients | contains | one string (a single ingredient name)\n"
    "- ingredients | not_contains | one string (an excluded ingredient)\n"
    "- cuisine | eq | one string (e.g. Indian, Ukrainian, Italian)\n"
    "- dish_type | eq | one lowercase string (e.g. soup, dessert, side dish)\n"
    "- diet_tags | any or all | list of strings (vegetarian, vegan, gluten-free, halal, kosher)\n"
    "- time_minutes | lte or gte | one integer number\n"
    "- servings | lte or gte | one integer number\n"
    "- title | contains | one string\n"
    "Examples: 'under 30 minutes' -> time_minutes lte 30. 'vegetarian' -> "
    "diet_tags any [vegetarian]. 'with potatoes' -> ingredients contains potatoes.\n"
    "Extract requirements ONLY for constraints the question states explicitly; "
    "never invent them. For a dish the user names, use title contains instead of "
    "cuisine. Generic nouns like 'dish', 'meal', 'food', 'recipe', 'something to "
    "eat' are NOT dish_type constraints - only extract dish_type when the user "
    "names a concrete type such as soup, dessert, cake, cookie, pizza, sauce, "
    "pancake or beverage. search_query is a short keyword phrase for relevance ranking.\n"
    "For comparison questions about recipe variants, use the shortest common dish "
    "family in title contains (for example, 'Baingan Bartha'), not a variant-specific "
    "full title; the plan must preserve all matching alternatives.\n"
    "Examples of non-recipe plans: a weather question -> intent=out_of_domain; "
    "a question asking whether a dish is safe for an allergy -> intent=safety."
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


class UnsupportedConstraintError(ExtractionError):
    """A valid recipe constraint has no matching value in this corpus."""


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
                response_format=QueryPlan,
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

    message = f"extraction failed after {MAX_ATTEMPTS} attempts: {last_error}"
    if isinstance(last_error, FilterSpecError) and "not in the corpus vocabulary" in str(last_error):
        raise UnsupportedConstraintError(message)
    raise ExtractionError(message)
