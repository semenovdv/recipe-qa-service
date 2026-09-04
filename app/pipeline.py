"""Pipeline — the seam between HTTP and the AI stack (ADR-001/002).

``LunaPipeline`` is the real composition: extraction (luna @ none) →
query embedding → hybrid retrieval (pgvector) → generation (luna @ medium)
with the verbatim-citation evidence gate. Construction fails fast if the
corpus version in the DB does not match the committed corpus (ADR-003 D3).

If configuration is missing (no OPENAI_API_KEY / DATABASE_URL) or
construction fails, the app keeps ``pipeline = None`` and /ask answers
with the honest 503 dependency-unavailable problem (§7.3) — never a
disguised answer or refusal. Tests inject fakes via set_pipeline().
"""

from __future__ import annotations

import time
from typing import Protocol

# The three public refusal reasons (SPEC §7.1 enum).
REFUSAL_REASONS = frozenset({"out_of_corpus", "out_of_domain", "safety"})


class Pipeline(Protocol):
    def answer(
        self, question: str, request_id: str, progress=None, advanced: bool = False
    ) -> dict:
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


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------


class PipelineUnavailable(Exception):
    """An infrastructure dependency failed (extraction/retrieval/generation).

    Mapped by the HTTP layer to the 503 problem path — never to a 200
    business refusal (§7.3: provider failures must not masquerade as
    confident answers).
    """


class LunaPipeline:
    """The ADR-001/002 two-tier pipeline over the pgvector corpus."""

    def __init__(self, settings) -> None:
        import logging

        self._log = logging.getLogger("recipe_qa")
        from openai import OpenAI

        from app import retrieve

        self._settings = settings
        self._retrieve = retrieve
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.upstream_timeout_seconds,
            max_retries=0,
        )

        committed = _committed_corpus_version(settings.corpus_index_path)
        with _connect(settings.database_url) as conn:
            self._vocabularies = retrieve.load_vocabularies(conn)
            db_version = retrieve.load_corpus_version(conn)
        if not db_version or db_version != committed:
            raise RuntimeError(
                f"corpus version mismatch: db={db_version!r} committed={committed!r}"
            )

    def answer(
        self, question: str, request_id: str, progress=None, advanced: bool = False
    ) -> dict:
        from app.extract import (
            ExtractionError,
            UnsupportedConstraintError,
            extract_plan,
        )
        from app.generate import GenerationError, generate

        trace = _new_trace()
        try:
            plan = _timed(
                trace,
                "extract",
                lambda: extract_plan(
                    question, client=self._client, vocabularies=self._vocabularies
                ),
                progress,
            )
            _set_trace_detail(trace, "extract", _plan_summary(plan))
            _notify(progress, trace)
            # §10 correlation: the extracted plan shapes everything downstream.
            self._log.info("request_id=%s plan=%s", request_id, plan.model_dump())

            # Intent is classified by the same structured LLM call as the plan.
            # These branches intentionally precede embeddings, retrieval and
            # answer generation; a non-recipe request never reaches the DB
            # search path or the generation model.
            if plan.intent == "safety":
                _skip_after(trace, "extract")
                return _refusal(
                    "I can't certify that a recipe is safe or allergen-free. "
                    "Please check the full ingredient list and product labels.",
                    "safety",
                    trace,
                )
            if plan.intent == "out_of_domain":
                _skip_after(trace, "extract")
                return _refusal(
                    "I can only answer questions about recipes in the cookbook corpus.",
                    "out_of_domain",
                    trace,
                )

            query_vec = _timed(
                trace,
                "embed",
                lambda: self._client.embeddings.create(
                    model="text-embedding-3-small", input=[plan.search_query]
                )
                .data[0]
                .embedding,
                progress,
            )
            records = _timed(
                trace,
                "retrieve",
                lambda: self._retrieve.search(
                    plan, query_vec, self._settings.database_url
                ),
                progress,
            )
            self._log.info(
                "request_id=%s retrieval_ids=%s",
                request_id,
                [r["pageid"] for r in records],
            )
        except UnsupportedConstraintError:
            _skip_after(trace, "extract")
            return _refusal(
                "No recipe in the cookbook corpus supports that constraint.",
                "out_of_corpus",
                trace,
            )
        except (ExtractionError, self._retrieve.RetrievalError) as exc:
            raise PipelineUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except Exception as exc:
            raise PipelineUnavailable(f"upstream request failed: {exc}") from exc

        if not records:
            _skip_after(trace, "retrieve")
            # No candidates survived the hard filters -> honest refusal (§9).
            return _refusal(
                "No recipe in the cookbook matches those requirements, so I "
                "won't stretch the constraints. Try relaxing a filter or "
                "asking about a different dish.",
                "out_of_corpus",
                trace,
            )

        records = self._retrieve.select_for_answer(question, records)
        if not records or (
            self._retrieve.is_comparison_question(question) and len(records) < 2
        ):
            _skip_after(trace, "retrieve")
            return _refusal(
                "I couldn't find enough recipes in the corpus to support that "
                "comparison.",
                "out_of_corpus",
                trace,
            )

        try:
            response = _timed(
                trace,
                "generate",
                lambda: (
                    generate(question, records, client=self._client, inline_links=True)
                    if advanced
                    else generate(question, records, client=self._client)
                ),
                progress,
            )
            return {**response.model_dump(), "trace": trace}
        except GenerationError as exc:
            raise PipelineUnavailable(f"generation failed: {exc}") from exc
        except Exception as exc:
            raise PipelineUnavailable(f"upstream request failed: {exc}") from exc


def _refusal(answer: str, reason: str, trace: list[dict] | None = None) -> dict:
    from app.schemas import AskResponse

    return AskResponse(
        answer=answer,
        citations=[],
        refused=True,
        refusal_reason=reason,
        trace=trace or [],
    ).model_dump()


def _new_trace() -> list[dict]:
    return [
        {
            "key": "extract",
            "label": "First LLM request · query plan",
            "status": "pending",
            "duration_ms": None,
            "detail": "",
        },
        {
            "key": "embed",
            "label": "LLM embeddings",
            "status": "pending",
            "duration_ms": None,
            "detail": "",
        },
        {
            "key": "retrieve",
            "label": "Database · top 15 by embedding",
            "status": "pending",
            "duration_ms": None,
            "detail": "",
        },
        {
            "key": "generate",
            "label": "Second LLM request · answer",
            "status": "pending",
            "duration_ms": None,
            "detail": "",
        },
    ]


def _timed(trace: list[dict], key: str, operation, progress=None):
    step = next(item for item in trace if item["key"] == key)
    step["status"] = "running"
    _notify(progress, trace)
    started = time.perf_counter()
    try:
        result = operation()
    except Exception:
        step["status"] = "failed"
        step["duration_ms"] = round((time.perf_counter() - started) * 1000)
        _notify(progress, trace)
        raise
    step["status"] = "complete"
    step["duration_ms"] = round((time.perf_counter() - started) * 1000)
    _notify(progress, trace)
    return result


def _notify(progress, trace: list[dict]) -> None:
    if progress is not None:
        progress([dict(step) for step in trace])


def _set_trace_detail(trace: list[dict], key: str, detail: str) -> None:
    next(item for item in trace if item["key"] == key)["detail"] = detail


def _plan_summary(plan) -> str:
    """Compact, operator-readable QueryPlan summary without the full prompt."""
    filters = [f"{req.field} {req.op}={req.value}" for req in plan.requirements]
    query = plan.search_query or "—"
    suffix = "; ".join(filters) if filters else "no filters"
    return f"intent={plan.intent}; query={query}; {suffix}"[:240]


def _skip_after(trace: list[dict], key: str) -> None:
    reached = False
    for step in trace:
        if step["key"] == key:
            reached = True
            continue
        if reached and step["status"] == "pending":
            step["status"] = "skipped"
            step["detail"] = "Not needed for this request"


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url)


def _committed_corpus_version(index_path: str) -> str | None:
    import json

    try:
        with open(index_path, encoding="utf-8") as index_file:
            data = json.load(index_file)
        return data.get("corpus_version")
    except (OSError, ValueError):
        return None


def build_default_pipeline() -> LunaPipeline | None:
    """Composition root: build the real pipeline or report why not."""
    from app.settings import get_settings

    settings = get_settings()
    if not settings.openai_api_key or not settings.database_url:
        return None
    try:
        return LunaPipeline(settings)
    except Exception as exc:  # noqa: BLE001 — construction is fail-fast
        import logging

        logging.getLogger("recipe_qa").error("pipeline unavailable: %s", exc)
        return None
