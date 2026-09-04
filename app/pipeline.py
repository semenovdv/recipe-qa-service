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

    def answer(self, question: str, request_id: str) -> dict:
        from app.extract import ExtractionError, UnsupportedConstraintError, extract_plan
        from app.generate import GenerationError, generate

        try:
            plan = extract_plan(
                question, client=self._client, vocabularies=self._vocabularies
            )
            # §10 correlation: the extracted plan shapes everything downstream.
            self._log.info("request_id=%s plan=%s", request_id, plan.model_dump())

            # Intent is classified by the same structured LLM call as the plan.
            # These branches intentionally precede embeddings, retrieval and
            # answer generation; a non-recipe request never reaches the DB
            # search path or the generation model.
            if plan.intent == "safety":
                return _refusal(
                    "I can't certify that a recipe is safe or allergen-free. "
                    "Please check the full ingredient list and product labels.",
                    "safety",
                )
            if plan.intent == "out_of_domain":
                return _refusal(
                    "I can only answer questions about recipes in the cookbook corpus.",
                    "out_of_domain",
                )

            query_vec = self._client.embeddings.create(
                model="text-embedding-3-small", input=[plan.search_query]
            ).data[0].embedding
            records = self._retrieve.search(
                plan, query_vec, self._settings.database_url
            )
            self._log.info(
                "request_id=%s retrieval_ids=%s",
                request_id, [r["pageid"] for r in records],
            )
        except UnsupportedConstraintError:
            return _refusal(
                "No recipe in the cookbook corpus supports that constraint.",
                "out_of_corpus",
            )
        except (ExtractionError, self._retrieve.RetrievalError) as exc:
            raise PipelineUnavailable(
                f"{type(exc).__name__}: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — provider failures are 503s
            raise PipelineUnavailable(f"upstream request failed: {exc}") from exc

        records = self._retrieve.relevant_records(records)

        if not records:
            # No candidates survived the hard filters -> honest refusal (§9).
            return _refusal(
                "No recipe in the cookbook matches those requirements, so I "
                "won't stretch the constraints. Try relaxing a filter or "
                "asking about a different dish.",
                "out_of_corpus",
            )

        records = self._retrieve.select_for_answer(question, records)
        if not records or (
            self._retrieve.is_comparison_question(question) and len(records) < 2
        ):
            return _refusal(
                "I couldn't find enough recipes in the corpus to support that "
                "comparison.",
                "out_of_corpus",
            )

        try:
            return generate(question, records, client=self._client).model_dump()
        except GenerationError as exc:
            raise PipelineUnavailable(f"generation failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — provider failures are 503s
            raise PipelineUnavailable(f"upstream request failed: {exc}") from exc


def _refusal(answer: str, reason: str) -> dict:
    from app.schemas import AskResponse

    return AskResponse(
        answer=answer, citations=[], refused=True, refusal_reason=reason,
    ).model_dump()


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url)


def _committed_corpus_version(index_path: str) -> str | None:
    import json

    try:
        data = json.load(open(index_path, encoding="utf-8"))
        return data.get("corpus_version")
    except (OSError, ValueError):
        return None


def build_default_pipeline() -> "LunaPipeline | None":
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
