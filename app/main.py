"""Recipe Q&A Service — FastAPI application (SPEC §7).

HTTP layer only: request validation, the §7.1 response envelope, and the
§7.3 problem contract. The answering pipeline is injected via app.pipeline;
until the AI stack (ADR-001/002) is wired, /ask returns an explicit 503
dependency-unavailable problem — never a disguised answer or refusal.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app import corpus_meta
from app import pipeline as pipeline_reg
from app.errors import (
    Problem,
    dependency_unavailable,
    internal_error,
    invalid_request,
    not_acceptable,
    payload_too_large,
    problem_body,
)
from app.schemas import AskResponse
from app.pipeline import PipelineUnavailable

logger = logging.getLogger("recipe_qa")
if not logging.getLogger().handlers:
    # §10: app logs go to stdout (PaaS-collected); uvicorn configures only
    # its own loggers, so give the root a basic handler for local runs.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

MAX_QUESTION_CHARS = 1000          # §7.1
MAX_BODY_BYTES = 64 * 1024         # §7.3: separately enforced body limit → 413
REQUIRED_ACCEPT = "application/json"  # §7.1: client MUST send exactly this


def create_app(build_pipeline: bool = True) -> FastAPI:
    app = FastAPI(title="Recipe Q&A Service", version="0.1.0")
    _register_error_handlers(app)
    if build_pipeline:
        from app.pipeline import build_default_pipeline, set_pipeline

        # None (config missing / DB mismatch) keeps the honest 503 state.
        set_pipeline(app, build_default_pipeline())

    @app.get("/health")
    async def health() -> JSONResponse:
        version = corpus_meta.corpus_version()
        if version is None:
            return JSONResponse(
                {"status": "degraded", "corpus_version": None}, status_code=503
            )
        return JSONResponse({"status": "ok", "corpus_version": version})

    @app.post("/ask")
    async def ask(request: Request) -> JSONResponse:
        if request.headers.get("accept") != REQUIRED_ACCEPT:
            raise not_acceptable(
                f"this endpoint requires Accept: {REQUIRED_ACCEPT}"
            )

        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise payload_too_large("request body exceeds the size limit")

        question = _parse_and_validate(raw)

        pipeline = pipeline_reg.get_pipeline(request.app)
        if pipeline is None:
            # AI stack unavailable (not configured / DB mismatch): honest 503,
            # never a fake answer (§7.3).
            raise dependency_unavailable("the answering pipeline is not available")

        request_id = uuid.uuid4().hex
        try:
            result = _validate_envelope(pipeline.answer(question, request_id))
        except PipelineUnavailable as exc:
            raise dependency_unavailable(str(exc)) from exc
        return JSONResponse(result.model_dump())

    return app


def _parse_and_validate(raw: bytes) -> str:
    """Validate the /ask body per §7.1 and return the trimmed question."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise invalid_request("request body must be valid JSON")
    if not isinstance(data, dict):
        raise invalid_request("request body must be a JSON object")

    if "question" not in data:
        raise invalid_request("question is required")
    if set(data.keys()) != {"question"}:
        raise invalid_request("request must contain exactly one property: question")

    question = data["question"]
    if not isinstance(question, str):
        raise invalid_request("question must be a string")
    if len(question) > MAX_QUESTION_CHARS:
        raise invalid_request(f"question exceeds {MAX_QUESTION_CHARS} characters")
    if not question.strip():
        raise invalid_request("question must be a non-empty string")
    return question.strip()


def _validate_envelope(result: object) -> AskResponse:
    """Validate the pipeline result against the §7.1 Pydantic model.

    Cross-field invariants (refusal enum, citations required for answers)
    live in the model, not here; a violating pipeline becomes an internal
    problem instead of a bad response. Details are logged, never returned.
    """
    try:
        return AskResponse.model_validate(result)
    except ValidationError as exc:
        logger.warning("pipeline envelope violation: %s", exc.errors()[:3])
        raise internal_error("pipeline returned a malformed response envelope") from exc


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem) -> JSONResponse:
        logger.warning(
            "problem status=%s type=%s request_id=%s",
            exc.status, exc.slug, exc.request_id,
        )
        return JSONResponse(problem_body(exc), status_code=exc.status)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals (§7.3): no stack traces, prompts, or paths.
        logger.exception("unhandled error")
        problem = internal_error()
        return JSONResponse(problem_body(problem), status_code=problem.status)


app = create_app()
