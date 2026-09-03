"""Pipeline registry — the seam between HTTP and the AI stack.

The retrieval/generation pipeline (ADR-001/002) is not implemented yet.
Until it is wired, the default app has NO pipeline and /ask raises
dependency-unavailable (503) — an explicit, honest "AI not ready" state,
never disguised as an answer or refusal (SPEC §7.3).

Tests inject fakes via set_pipeline(); production will call set_pipeline()
once from the composition root with the real implementation.
"""
from __future__ import annotations

from typing import Protocol

# The three public refusal reasons (SPEC §7.1 enum).
REFUSAL_REASONS = frozenset({"out_of_corpus", "out_of_domain", "safety"})


class Pipeline(Protocol):
    def answer(self, question: str, request_id: str) -> dict:
        """Return an AskResponse-shaped dict (§7.1 envelope)."""
        ...


_pipeline: Pipeline | None = None


def set_pipeline(app, pipeline: Pipeline | None) -> None:
    """Wire (or clear) the pipeline on an app instance."""
    app.state.pipeline = pipeline


def get_pipeline(app) -> Pipeline | None:
    pipeline = getattr(app.state, "pipeline", None)
    if pipeline is not None:
        return pipeline
    return _pipeline


def set_default_pipeline(pipeline: Pipeline | None) -> None:
    """Module-level wiring for the composition root."""
    global _pipeline
    _pipeline = pipeline
