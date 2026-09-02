"""Corpus contract validation (dataset/PLAN.md §2, §9).

Used by the build pipeline, the ``validate`` CLI mode and the committed-corpus
test. Pure functions over parsed records; no I/O.
"""

from __future__ import annotations

import re
from typing import Any

REQUIRED_KEYS = (
    "pageid",
    "revid",
    "title",
    "url",
    "fetched_at",
    "categories",
    "summary",
    "ingredients_raw",
    "ingredients",
    "steps",
    "description",
    "variant_group",
    "source_text",
)

_URL_RE = re.compile(r"^https://en\.wikibooks\.org/wiki/.+")


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of contract violations for one recipe record (empty = ok)."""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in record:
            errors.append(f"missing key: {key}")
    if errors:
        return errors

    if not isinstance(record["pageid"], int) or record["pageid"] <= 0:
        errors.append("pageid must be a positive int")
    if not isinstance(record["revid"], int) or record["revid"] <= 0:
        errors.append("revid must be a positive int")
    if not str(record["title"]).startswith("Cookbook:"):
        errors.append(f"title must start with 'Cookbook:': {record['title']!r}")
    if not _URL_RE.match(record["url"]):
        errors.append(f"url must be a canonical wikibooks URL: {record['url']!r}")

    summary = record["summary"]
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
    else:
        time_minutes = summary.get("time_minutes")
        if time_minutes is not None and (
            not isinstance(time_minutes, int) or time_minutes <= 0
        ):
            errors.append("summary.time_minutes must be a positive int or null")
        rating = summary.get("rating")
        if rating is not None and not isinstance(rating, int):
            errors.append("summary.rating must be an int or null")

    if not isinstance(record["ingredients"], list) or not record["ingredients"]:
        errors.append("ingredients must be a non-empty list")
    if not isinstance(record["steps"], list) or not record["steps"]:
        errors.append("steps must be a non-empty list (structure gate)")
    if not isinstance(record["source_text"], str) or len(record["source_text"]) < 200:
        errors.append("source_text must retain the raw wikitext (>= 200 chars)")
    return errors


def validate_corpus(
    records: list[dict[str, Any]],
    corpus_floor: int = 40,
    corpus_ceiling: int = 60,
) -> list[str]:
    """Return a list of contract violations for the whole corpus."""
    errors: list[str] = []
    count = len(records)
    if not (corpus_floor <= count <= corpus_ceiling):
        errors.append(
            f"corpus size {count} outside [{corpus_floor}, {corpus_ceiling}] (CORP-03)"
        )

    pageids = [record.get("pageid") for record in records]
    if len(pageids) != len(set(pageids)):
        errors.append("duplicate pageids in corpus")

    titles = [record.get("title") for record in records]
    if len(titles) != len(set(titles)):
        errors.append("duplicate titles in corpus")

    # Variety contract (CORP-05/06/07; stronger than the checklist's manual review)
    all_categories = {c for record in records for c in record.get("categories", [])}
    if len(all_categories) < 8:
        errors.append(
            f"variety: expected >= 8 distinct source categories, got {len(all_categories)}"
        )

    variant_groups = {record.get("variant_group") for record in records}
    overlapping = {group for group in variant_groups if group}
    if not overlapping:
        errors.append("variety: no overlapping/variant dish groups present (CORP-07)")

    structured = sum(
        1
        for record in records
        if record.get("summary", {}).get("time_minutes") is not None
    )
    if structured == 0:
        errors.append("variety: no record carries structured time metadata")
    if structured == count:
        errors.append(
            "variety: every record has time metadata — structure variety expected "
            "(CORP-08), check the category list"
        )

    for record in records:
        for violation in validate_record(record):
            errors.append(f"record {record.get('pageid')}: {violation}")
    return errors
