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
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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

logger = logging.getLogger("recipe_qa")

MAX_QUESTION_CHARS = 1000          # §7.1
MAX_BODY_BYTES = 64 * 1024         # §7.3: separately enforced body limit → 413
REQUIRED_ACCEPT = "application/json"  # §7.1: client MUST send exactly this


def create_app() -> FastAPI:
    app = FastAPI(title="Recipe Q&A Service", version="0.1.0")
    _register_error_handlers(app)

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
            # AI stack not wired yet: honest 503, never a fake answer (§7.3).
            raise dependency_unavailable("the answering pipeline is not available")

        request_id = uuid.uuid4().hex
        result = pipeline.answer(question, request_id)
        _validate_envelope(result)
        return JSONResponse(result)

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


def _validate_envelope(result: Any) -> None:
    """Enforce the §7.1 envelope + cross-field invariants at the boundary."""
    expected_keys = {"answer", "citations", "refused", "refusal_reason"}
    if not isinstance(result, dict) or set(result.keys()) != expected_keys:
        raise internal_error("pipeline returned a malformed response envelope")

    answer = result["answer"]
    if not isinstance(answer, str) or not answer:
        raise internal_error("answer must be a non-empty string")
    if not isinstance(result["refused"], bool):
        raise internal_error("refused must be a boolean")
    if not isinstance(result["citations"], list):
        raise internal_error("citations must be a list")

    refused = result["refused"]
    reason = result["refusal_reason"]
    if refused:
        if reason not in pipeline_reg.REFUSAL_REASONS:
            raise internal_error("refusal_reason must be one of the contract values")
    else:
        if reason is not None:
            raise internal_error("refusal_reason must be null for non-refusals")
        if not result["citations"]:
            raise internal_error("a successful answer requires at least one citation")
        for citation in result["citations"]:
            if (
                not isinstance(citation, dict)
                or not isinstance(citation.get("title"), str)
                or not citation["title"]
                or not isinstance(citation.get("url"), str)
                or not citation["url"]
            ):
                raise internal_error("each citation requires a title and a url")


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
