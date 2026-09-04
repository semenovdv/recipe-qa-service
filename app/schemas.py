"""Pydantic API schemas — the single source of truth for structured shapes.

- ``AskResponse``/``Citation`` — the §7.1 envelope; the HTTP layer validates
  every pipeline result against these models before responding.
- ``QueryPlan`` (app/query_plan.py) — the extraction-call output; its
  ``model_json_schema()`` is handed to the OpenAI structured-outputs API.

extra="forbid" everywhere: strict-mode structured outputs require
``additionalProperties: false``, and the HTTP boundary must reject
malformed envelopes rather than pass them through.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The three public refusal reasons (SPEC §7.1 enum).
RefusalReason = Literal["out_of_corpus", "out_of_domain", "safety"]
TraceStatus = Literal["pending", "running", "complete", "skipped", "failed"]


class TraceStep(BaseModel):
    """Safe, payload-free timing information for one pipeline stage."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: TraceStatus
    duration_ms: int | None = Field(default=None, ge=0)
    detail: str = ""


class Citation(BaseModel):
    """One retrieved source backing the answer (§7.1 Citation)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)


class AskResponse(BaseModel):
    """The complete /ask response envelope (§7.1) with its cross-field
    invariants enforced in the model, not in handler code."""

    model_config = ConfigDict(extra="forbid")

    # No defaults: strict-mode structured outputs require every key, and a
    # pipeline result must always carry the complete envelope explicitly.
    answer: str = Field(min_length=1, description="Grounded answer or polite refusal.")
    citations: list[Citation]
    refused: bool
    refusal_reason: RefusalReason | None
    trace: list[TraceStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _envelope_invariants(self) -> AskResponse:
        if self.refused:
            if self.refusal_reason is None:
                raise ValueError(
                    "refused=true requires one of the three refusal reasons"
                )
        else:
            if self.refusal_reason is not None:
                raise ValueError("refusal_reason must be null for non-refusals")
            if not self.citations:
                raise ValueError("a successful answer requires at least one citation")
        return self
