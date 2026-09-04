"""QueryPlan / FilterSpec v1 — ADR-001 D2.

The extraction call (gpt-5.6-luna @ none, Structured Outputs) translates a
user question into a QueryPlan. Pydantic v2 models are the single source of
truth: the same classes validate the plan in code AND generate the strict
JSON schema handed to the OpenAI structured-outputs API.

- ``parse_plan``      — structural validation (whitelisted field/op pairs,
                        strict value typing, no unknown keys via extra=forbid).
- ``normalize_plan``  — categorical values checked against corpus
                        vocabularies; out-of-vocabulary values raise
                        FilterSpecError (hard constraints are never
                        fuzzy-matched).
- ``evaluate_requirement`` / ``filter_records`` — deterministic evaluation
                        against records; unknown data fails conservatively
                        (None is never fast/vegetarian/anything).

``FilterSpecError`` remains the public error type: Pydantic ValidationErrors
are bridged into it so callers need one exception.
"""

from __future__ import annotations

from typing import Any, Literal, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# Whitelist: field -> allowed ops -> expected value shape.
FIELD_OPS: dict[str, dict[str, str]] = {
    "ingredients": {"contains": "string", "not_contains": "string"},
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

VocabularyKey = Literal["cuisines", "dish_types", "diet_tags"]
IntentKind = Literal["recipe", "out_of_domain", "safety"]
VOCAB_KEY_FOR_FIELD: dict[str, VocabularyKey] = {
    "cuisine": "cuisines",
    "dish_type": "dish_types",
    "diet_tags": "diet_tags",
}


class FilterSpecError(ValueError):
    """A QueryPlan violated FilterSpec v1 (structural or vocabulary)."""


class Requirement(BaseModel):
    """One typed hard constraint, e.g. ``cuisine EQ ukrainian``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Literal types: the JSON schema exposes the whitelist to the model as
    # enums, so invalid fields/ops are rejected before custom validators.
    field: Literal[
        "ingredients",
        "cuisine",
        "dish_type",
        "diet_tags",
        "time_minutes",
        "servings",
        "title",
    ]
    op: Literal["contains", "not_contains", "eq", "any", "all", "lte", "gte"]
    # Closed union (not Any): OpenAI strict mode requires a concrete type
    # for every property. Per-field/op legality is enforced below.
    value: str | list[str] | int | float

    def __init__(self, field: str, op: str, value: Any) -> None:
        # Positional bridge so both Requirement("f", "op", v) and
        # Requirement(field=..., op=..., value=...) work.
        super().__init__(field=field, op=op, value=value)

    @model_validator(mode="after")
    def _validate_shape(self) -> "Requirement":
        allowed = FIELD_OPS.get(self.field)
        if allowed is None:
            raise ValueError(f"unknown field: {self.field!r}")
        shape = allowed.get(self.op)
        if shape is None:
            raise ValueError(f"op {self.op!r} not allowed for field {self.field!r}")

        v = self.value
        if shape == "string":
            if not isinstance(v, str) or not v.strip():
                raise ValueError(
                    f"{self.field} {self.op} requires a non-empty string value"
                )
        elif shape == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"{self.field} {self.op} requires a number")
            if v < 0:
                raise ValueError(
                    f"{self.field} {self.op} requires a non-negative number"
                )
        else:  # list_of_strings
            if (
                not isinstance(v, list)
                or not v
                or not all(isinstance(s, str) and s.strip() for s in v)
            ):
                raise ValueError(
                    f"{self.field} {self.op} requires a non-empty list of non-empty strings"
                )
        return self


class QueryPlan(BaseModel):
    """The extraction call's output: intent, ranking query and hard filters.

    Intent is deliberately part of this LLM-produced plan. Natural-language
    safety and domain boundaries are too broad for a reliable keyword/regex
    gate. Non-recipe plans terminate in the pipeline before embeddings,
    retrieval and answer generation.

    ``model_json_schema()`` on this class is the strict schema used for the
    OpenAI structured-outputs call (extra=forbid -> additionalProperties:
    false, as strict mode requires).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: IntentKind
    intent_reason: str = Field(min_length=1, max_length=240)
    search_query: str
    # Required (no default): strict-mode structured outputs require every
    # key, and a plan without an explicit requirements list is a contract
    # violation, not an empty filter set.
    requirements: Tuple[Requirement, ...]

    @field_validator("search_query")
    @classmethod
    def _search_query_trim(cls, v: str) -> str:
        return v.strip()

    @field_validator("intent_reason")
    @classmethod
    def _intent_reason_trim(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("intent_reason must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _intent_plan_consistency(self) -> "QueryPlan":
        if self.intent == "recipe" and not self.search_query:
            raise ValueError("recipe plans require a non-empty search_query")
        if self.intent != "recipe" and (self.search_query or self.requirements):
            raise ValueError(
                "non-recipe plans must have an empty search_query and no requirements"
            )
        return self


# ---------------------------------------------------------------------------
# Parsing — structural validation only (no corpus knowledge)
# ---------------------------------------------------------------------------


def parse_plan(data: object) -> QueryPlan:
    """Validate raw JSON (e.g. an LLM structured output) into a QueryPlan."""
    try:
        plan = QueryPlan.model_validate(data)
    except ValidationError as exc:
        raise FilterSpecError(_first_message(exc)) from exc
    sq = plan.search_query.strip()
    if sq != plan.search_query:
        plan = plan.model_copy(update={"search_query": sq})
    return plan


def _first_message(exc: ValidationError) -> str:
    """Compact error text including the location (fed to retry hints)."""
    errs = exc.errors()
    if not errs:
        return "invalid query plan"
    err = errs[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = str(err.get("msg") or "invalid")
    return f"{loc}: {msg}" if loc else msg


# ---------------------------------------------------------------------------
# Normalization — categorical values against corpus vocabularies
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    return s.strip().lower()


def normalize_plan(
    plan: QueryPlan, vocabularies: dict[str, set[str] | list[str]]
) -> QueryPlan:
    """Normalize/validate categorical values against the corpus vocabularies.

    ``vocabularies`` maps vocabulary keys (``cuisines``/``dish_types``/
    ``diet_tags``) to canonical (case-preserving) values, as returned by
    ``app.db.vocabularies_from_records`` or loaded from the DB.
    """
    out: list[Requirement] = []
    for req in plan.requirements:
        if req.field in VOCAB_FIELDS:
            vocab = vocabularies.get(VOCAB_KEY_FOR_FIELD[req.field])
            values = req.value if isinstance(req.value, list) else [req.value]
            normalized = []
            for v in values:
                match = next((c for c in (vocab or []) if _norm(c) == _norm(v)), None)
                if match is None:
                    raise FilterSpecError(
                        f"value {v!r} for field {req.field!r} "
                        f"is not in the corpus vocabulary"
                    )
                normalized.append(match)
            value = normalized if isinstance(req.value, list) else normalized[0]
            out.append(req.model_copy(update={"value": value}))
        else:
            out.append(req)
    return plan.model_copy(update={"requirements": tuple(out)})


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
        found = any(needle in _norm_ci(i) for i in items)
        return not found if op == "not_contains" else found

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
        r
        for r in records
        if all(evaluate_requirement(req, r) for req in plan.requirements)
    ]
