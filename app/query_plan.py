"""QueryPlan / FilterSpec v1 — ADR-001 D2.

The extraction call (gpt-5.6-luna @ none, Structured Outputs) translates a
user question into a QueryPlan: a free-text ranking query plus a list of
typed requirements. This module is the *contract* for that object:

- ``parse_plan``      — structural validation (whitelisted field/op pairs,
                        strict value typing, no unknown keys).
- ``normalize_plan``  — categorical values checked against corpus
                        vocabularies (case/trim normalized). Out-of-
                        vocabulary values raise: hard constraints are never
                        fuzzy-matched.
- ``evaluate_requirement`` / ``filter_records`` — deterministic evaluation
                        against records; unknown data fails conservatively
                        (None is never fast/vegetarian/anything).

The LLM has zero filter authority: it only emits the typed format, code
decides everything. These functions are pure and offline-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Whitelist: field -> allowed ops -> expected value shape.
# Scalar categorical: eq; scalar numeric: lte/gte; list categorical: any/all;
# text: contains (case-insensitive substring).
FIELD_OPS: dict[str, dict[str, str]] = {
    "ingredients": {"contains": "string"},
    "cuisine": {"eq": "string"},
    "dish_type": {"eq": "string"},
    "diet_tags": {"any": "list_of_strings", "all": "list_of_strings"},
    "time_minutes": {"lte": "number", "gte": "number"},
    "servings": {"lte": "number", "gte": "number"},
    "title": {"contains": "string"},
}

# Fields whose values must exist in a corpus-derived vocabulary after
# normalization (lowercase + strip compare).
VOCAB_FIELDS = ("cuisine", "dish_type", "diet_tags")


class FilterSpecError(ValueError):
    """A QueryPlan violated FilterSpec v1 (structural or vocabulary)."""


@dataclass(frozen=True)
class Requirement:
    field: str
    op: str
    value: object


@dataclass(frozen=True)
class QueryPlan:
    search_query: str
    requirements: tuple[Requirement, ...] = field(default=())


# ---------------------------------------------------------------------------
# Parsing — structural validation only (no corpus knowledge)
# ---------------------------------------------------------------------------

def _check_value_shape(field: str, op: str, value: object) -> None:
    shape = FIELD_OPS[field][op]
    if shape == "string":
        if not isinstance(value, str) or not value.strip():
            raise FilterSpecError(
                f"{field} {op} requires a non-empty string value"
            )
    elif shape == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FilterSpecError(f"{field} {op} requires a number")
        if value < 0:
            raise FilterSpecError(f"{field} {op} requires a non-negative number")
    elif shape == "list_of_strings":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(v, str) and v.strip() for v in value)
        ):
            raise FilterSpecError(
                f"{field} {op} requires a non-empty list of non-empty strings"
            )


def parse_plan(data: object) -> QueryPlan:
    if not isinstance(data, dict):
        raise FilterSpecError("query plan must be a JSON object")
    if set(data.keys()) != {"search_query", "requirements"}:
        raise FilterSpecError(
            "query plan must have exactly search_query and requirements"
        )
    search_query = data["search_query"]
    if not isinstance(search_query, str) or not search_query.strip():
        raise FilterSpecError("search_query must be a non-empty string")

    raw_reqs = data["requirements"]
    if not isinstance(raw_reqs, list):
        raise FilterSpecError("requirements must be a list")

    requirements = []
    for raw in raw_reqs:
        if not isinstance(raw, dict) or set(raw.keys()) != {"field", "op", "value"}:
            raise FilterSpecError(
                "each requirement must have exactly field, op, value"
            )
        f, op = raw["field"], raw["op"]
        if f not in FIELD_OPS:
            raise FilterSpecError(f"unknown field: {f!r}")
        if op not in FIELD_OPS[f]:
            raise FilterSpecError(f"op {op!r} not allowed for field {f!r}")
        _check_value_shape(f, op, raw["value"])
        requirements.append(Requirement(f, op, raw["value"]))

    return QueryPlan(search_query=search_query.strip(), requirements=tuple(requirements))


# ---------------------------------------------------------------------------
# Normalization — categorical values against corpus vocabularies
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.strip().lower()


def normalize_plan(plan: QueryPlan, vocabularies: dict[str, set[str] | list[str]]) -> QueryPlan:
    """Normalize/validate categorical values.

    ``vocabularies`` maps a vocabulary name to canonical values, e.g.
    ``{"cuisines": {"Indian", ...}, "diet_tags": ["vegetarian", ...]}``.
    Vocabulary key convention: field ``cuisine`` -> key ``cuisines``;
    ``dish_type`` -> ``dish_types``; ``diet_tags`` -> ``diet_tags``.
    """
    key_for = {"cuisine": "cuisines", "dish_type": "dish_types", "diet_tags": "diet_tags"}
    out = []
    for req in plan.requirements:
        if req.field in VOCAB_FIELDS:
            vocab = vocabularies.get(key_for[req.field])
            values = req.value if isinstance(req.value, list) else [req.value]
            normalized = []
            for v in values:
                match = next(
                    (c for c in (vocab or []) if _norm(c) == _norm(v)), None
                )
                if match is None:
                    raise FilterSpecError(
                        f"value {v!r} for field {req.field!r} "
                        f"is not in the corpus vocabulary"
                    )
                normalized.append(match)
            value = normalized if isinstance(req.value, list) else normalized[0]
            out.append(Requirement(req.field, req.op, value))
        else:
            out.append(req)
    return QueryPlan(plan.search_query, tuple(out))


# ---------------------------------------------------------------------------
# Evaluation — deterministic, conservative unknowns
# ---------------------------------------------------------------------------

def _norm_ci(v: object) -> str:
    return str(v).strip().lower()


def evaluate_requirement(req: Requirement, record: dict) -> bool:
    f, op, value = req.field, req.op, req.value

    if f == "ingredients":
        items = record.get("ingredients")
        if not items:
            return False  # unknown/empty ingredients: conservative fail
        needle = _norm_ci(value)
        return any(needle in _norm_ci(i) for i in items)

    if f == "title":
        title = record.get("title")
        return bool(title) and _norm_ci(value) in _norm_ci(title)

    if f in ("time_minutes", "servings"):
        actual = record.get(f)
        if actual is None:
            return False  # unknown never satisfies a numeric constraint
        if op == "lte":
            return actual <= value
        if op == "gte":
            return actual >= value
        raise FilterSpecError(f"op {op!r} not allowed for field {f!r}")

    if f in ("cuisine", "dish_type"):
        actual = record.get(f)
        return actual is not None and _norm_ci(actual) == _norm_ci(value)

    if f == "diet_tags":
        actual = record.get("diet_tags")
        if not actual:
            return False  # unknown/empty diet data fails any/all conservatively
        have = {_norm_ci(t) for t in actual}
        want = {_norm_ci(v) for v in value}
        return want <= have if op == "all" else bool(want & have)

    raise FilterSpecError(f"unknown field: {f!r}")


def filter_records(plan: QueryPlan, records: list[dict]) -> list[dict]:
    """AND-combined hard filtering; order preserved (deterministic)."""
    return [
        r for r in records
        if all(evaluate_requirement(req, r) for req in plan.requirements)
    ]
