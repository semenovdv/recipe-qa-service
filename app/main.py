"""Recipe Q&A Service — FastAPI application (SPEC §7)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from app import corpus_meta
from app import pipeline as pipeline_reg
from app.extract import PROMPT_VERSION as EXTRACT_PROMPT_VERSION
from app.generate import PROMPT_VERSION as GENERATE_PROMPT_VERSION
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
MAX_REQUEST_SECONDS = 120


def create_app(build_pipeline: bool = True) -> FastAPI:
    app = FastAPI(title="Recipe Q&A Service", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "https://p01--recipe-qa-ui--yjw6rjx4dx4m.code.run",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )
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

        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise invalid_request("Content-Type must be application/json")

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
        started = time.perf_counter()
        try:
            raw_result = await asyncio.wait_for(
                run_in_threadpool(pipeline.answer, question, request_id),
                timeout=MAX_REQUEST_SECONDS,
            )
            result = _validate_envelope(raw_result)
        except PipelineUnavailable as exc:
            logger.warning(
                "pipeline unavailable request_id=%s error_type=%s",
                request_id,
                type(exc).__name__,
            )
            _log_request(request_id, 503, started)
            raise dependency_unavailable("the answering pipeline is temporarily unavailable") from exc
        except asyncio.TimeoutError as exc:
            _log_request(request_id, 503, started)
            raise dependency_unavailable("the answering request timed out") from exc
        except Problem as exc:
            _log_request(request_id, exc.status, started)
            raise
        _log_request(request_id, 200, started, refused=result.refused,
                     refusal_reason=result.refusal_reason)
        return JSONResponse(result.model_dump())

    @app.post("/ask/stream")
    @app.post("/ask/advanced/stream")
    async def ask_stream(request: Request) -> StreamingResponse:
        """Stream safe pipeline progress for the operator-facing UI."""
        if request.headers.get("accept") != REQUIRED_ACCEPT:
            raise not_acceptable(f"this endpoint requires Accept: {REQUIRED_ACCEPT}")
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise invalid_request("Content-Type must be application/json")
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise payload_too_large("request body exceeds the size limit")
        question = _parse_and_validate(raw)
        pipeline = pipeline_reg.get_pipeline(request.app)
        if pipeline is None:
            raise dependency_unavailable("the answering pipeline is not available")

        request_id = uuid.uuid4().hex
        advanced = request.url.path == "/ask/advanced/stream"
        started = time.perf_counter()
        loop = asyncio.get_running_loop()
        events: asyncio.Queue[dict] = asyncio.Queue()

        def progress(steps: list[dict]) -> None:
            loop.call_soon_threadsafe(events.put_nowait, {"type": "trace", "steps": steps})

        async def run_pipeline() -> None:
            try:
                raw_result = await asyncio.wait_for(
                    run_in_threadpool(
                        pipeline.answer, question, request_id, progress, advanced
                    ),
                    timeout=MAX_REQUEST_SECONDS,
                )
                result = _validate_envelope(raw_result)
                await events.put({"type": "result", "response": result.model_dump()})
            except Exception as exc:  # noqa: BLE001 — stream never leaks internals
                logger.warning("stream failed request_id=%s error_type=%s", request_id, type(exc).__name__)
                await events.put({"type": "error", "detail": "The answering service is temporarily unavailable."})

        async def generate_events():
            from app.pipeline import _new_trace

            yield _ndjson({"type": "trace", "steps": _new_trace()})
            task = asyncio.create_task(run_pipeline())
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(events.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if task.done() and events.empty():
                            break
                        yield _ndjson({
                            "type": "heartbeat",
                            "elapsed_ms": round((time.perf_counter() - started) * 1000),
                        })
                        continue
                    yield _ndjson(event)
                    if event["type"] in {"result", "error"}:
                        break
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            generate_events(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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


def _ndjson(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False) + "\n"


def _log_request(
    request_id: str,
    status: int,
    started: float,
    refused: bool | None = None,
    refusal_reason: str | None = None,
) -> None:
    """Emit a structured, payload-free completion event for operations."""
    event: dict[str, object] = {
        "event": "request_complete",
        "request_id": request_id,
        "endpoint": "/ask",
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "corpus_version": corpus_meta.corpus_version(),
        "model": "gpt-5.6-luna",
        "prompt_version": f"{EXTRACT_PROMPT_VERSION}+{GENERATE_PROMPT_VERSION}",
    }
    if refused is not None:
        event["refused"] = refused
    if refusal_reason is not None:
        event["refusal_reason"] = refusal_reason
    logger.info("%s", json.dumps(event, sort_keys=True))


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
