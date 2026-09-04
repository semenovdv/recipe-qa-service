"""API contract tests for /ask and /health — SPEC §7.

The pipeline is injected where the HTTP boundary is tested so these tests
remain hermetic; pipeline-specific behavior is covered separately.

- The 200-envelope behavior is tested against an injected fake pipeline,
  proving the HTTP layer honors the §7.1 schema and cross-field invariants.
- The default app may be unavailable in a test environment: /ask must return
  an explicit §7.3 dependency-unavailable problem, never a disguised answer
  or an out_of_corpus refusal.

Contract design:

Validation / Accept / body-limit behavior is pipeline-independent: it must
reject before ever reaching the pipeline (AC-08).
"""
from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app.main import create_app

    # Hermetic: no real pipeline construction (no settings/DB access).
    # The 503 not-ready state is exactly what these tests pin down.
    return TestClient(create_app(build_pipeline=False), raise_server_exceptions=False)


def ask(client, question="How do I boil water?", accept="application/json", **kwargs):
    headers = {}
    if accept is not None:
        headers["Accept"] = accept
    if question is not None:
        kwargs["json"] = {"question": question}
    return client.post("/ask", headers=headers, **kwargs)


def problem(body: dict) -> dict:
    """Assert RFC 9457-style shape and return required fields."""
    for field in ("type", "title", "status", "detail", "request_id"):
        assert field in body, f"problem object missing {field!r}"
    assert isinstance(body["status"], int)
    assert body["type"].startswith("urn:recipe-qa:problem:")
    return body


# ---------------------------------------------------------------------------
# POST /ask — 200 envelope, driven by an injected fake pipeline
# ---------------------------------------------------------------------------

class TestAskEnvelopeWithFakePipeline:
    @pytest.fixture()
    def fake_client(self):
        from app.main import create_app
        from app.pipeline import set_pipeline

        app = create_app(build_pipeline=False)
        set_pipeline(app, FakePipeline())
        return TestClient(app, raise_server_exceptions=False)

    def test_answer_envelope_exact_fields(self, fake_client):
        r = ask(fake_client)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        body = r.json()
        assert set(body.keys()) == {"answer", "citations", "refused", "refusal_reason"}
        assert body["answer"] == "Boil water by heating it to 100 C."
        assert body["refused"] is False
        assert body["refusal_reason"] is None
        assert body["citations"] == [
            {"title": "Cookbook:Boiling", "url": "https://en.wikibooks.org/wiki/Cookbook:Boiling"}
        ]

    def test_refusal_envelope_invariants(self, fake_client):
        from app.pipeline import set_pipeline

        set_pipeline(fake_client.app, FakePipeline(refused=True, reason="out_of_corpus"))
        r = ask(fake_client, "What is the stock price of Apple?")
        assert r.status_code == 200
        body = r.json()
        assert body["refused"] is True
        assert body["refusal_reason"] == "out_of_corpus"
        assert body["citations"] == []
        assert isinstance(body["answer"], str) and body["answer"]

    def test_refusal_reason_must_be_one_of_three(self, fake_client):
        from app.pipeline import set_pipeline

        set_pipeline(fake_client.app, FakePipeline(refused=True, reason="because"))
        r = ask(fake_client)
        # HTTP layer must never emit an off-contract refusal reason (§7.1 enum)
        assert r.status_code == 500
        problem(r.json())


class FakePipeline:
    """Minimal stand-in implementing the pipeline protocol."""

    def __init__(self, refused=False, reason=None):
        self._refused = refused
        self._reason = reason

    def answer(self, question: str, request_id: str) -> dict:
        if self._refused:
            return {
                "answer": "I can only answer recipe questions.",
                "citations": [],
                "refused": True,
                "refusal_reason": self._reason,
            }
        return {
            "answer": "Boil water by heating it to 100 C.",
            "citations": [
                {
                    "title": "Cookbook:Boiling",
                    "url": "https://en.wikibooks.org/wiki/Cookbook:Boiling",
                }
            ],
            "refused": False,
            "refusal_reason": None,
        }


# ---------------------------------------------------------------------------
# POST /ask — AI not wired yet: explicit dependency-unavailable (§7.3)
# ---------------------------------------------------------------------------

class TestAskPipelineNotReady:
    def test_default_app_returns_503_problem(self, client):
        r = ask(client)
        assert r.status_code == 503
        body = problem(r.json())
        assert body["type"] == "urn:recipe-qa:problem:dependency-unavailable"
        assert body["status"] == 503

    def test_not_disguised_as_refusal(self, client):
        # Must NOT be a 200 out_of_corpus refusal — that would misrepresent
        # an infrastructure state as a business answer (§7.3).
        r = ask(client)
        assert r.status_code != 200

    def test_pipeline_timeout_is_503(self, monkeypatch):
        from app.main import create_app
        from app.pipeline import set_pipeline

        class SlowPipeline:
            def answer(self, question, request_id):
                time.sleep(0.05)
                return FakePipeline().answer(question, request_id)

        monkeypatch.setattr("app.main.MAX_REQUEST_SECONDS", 0.001)
        app = create_app(build_pipeline=False)
        set_pipeline(app, SlowPipeline())
        r = ask(TestClient(app, raise_server_exceptions=False))
        assert r.status_code == 503
        assert problem(r.json())["type"] == "urn:recipe-qa:problem:dependency-unavailable"


# ---------------------------------------------------------------------------
# POST /ask — validation errors, rejected before the pipeline (AC-08)
# ---------------------------------------------------------------------------

class TestAskValidation:
    def test_missing_question_is_400(self, client):
        r = client.post("/ask", json={}, headers={"Accept": "application/json"})
        assert r.status_code == 400
        body = problem(r.json())
        assert body["type"] == "urn:recipe-qa:problem:invalid-request"

    def test_whitespace_only_is_400(self, client):
        r = ask(client, question="   ")
        assert r.status_code == 400

    def test_empty_string_is_400(self, client):
        r = ask(client, question="")
        assert r.status_code == 400

    def test_wrong_type_is_400(self, client):
        r = client.post("/ask", json={"question": 42}, headers={"Accept": "application/json"})
        assert r.status_code == 400

    def test_oversized_question_is_400(self, client):
        r = ask(client, question="a" * 1001)
        assert r.status_code == 400

    def test_max_length_question_passes_validation(self, client):
        # Exactly 1000 chars is valid per §7.1; with no injected pipeline the
        # observable outcome is the 503, not a 400.
        r = ask(client, question="a" * 1000)
        assert r.status_code == 503

    def test_extra_property_is_400(self, client):
        r = client.post(
            "/ask",
            json={"question": "x", "extra": True},
            headers={"Accept": "application/json"},
        )
        assert r.status_code == 400

    def test_non_json_body_is_400(self, client):
        r = client.post(
            "/ask",
            content=b"not json",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        assert r.status_code == 400

    def test_missing_content_type_is_400(self, client):
        r = client.post(
            "/ask",
            content=b'{"question": "How do I cook borscht?"}',
            headers={"Accept": "application/json"},
        )
        assert r.status_code == 400

    def test_missing_body_is_400(self, client):
        r = client.post("/ask", headers={"Accept": "application/json"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /ask — protocol errors
# ---------------------------------------------------------------------------

class TestAskProtocol:
    def test_wrong_accept_is_406(self, client):
        r = ask(client, accept="text/html")
        assert r.status_code == 406
        body = problem(r.json())
        assert body["type"] == "urn:recipe-qa:problem:not-acceptable"

    def test_oversized_body_is_413(self, client):
        big = "a" * (64 * 1024)  # 64 KB body, question alone would pass 400-check
        r = client.post(
            "/ask",
            content=b'{"question": "' + big.encode() + b'"}',
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        assert r.status_code == 413
        problem(r.json())


# ---------------------------------------------------------------------------
# GET /health — §7.2
# ---------------------------------------------------------------------------

class TestHealth:
    def test_healthy(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body == {"status": "ok", "corpus_version": "45af1c982923952a"}

    def test_degraded_when_corpus_unavailable(self, monkeypatch):
        from app.main import create_app

        monkeypatch.setenv("CORPUS_INDEX_PATH", "/nonexistent/index.json")
        app = create_app(build_pipeline=False)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/health")
        assert r.status_code == 503
        assert r.json() == {"status": "degraded", "corpus_version": None}
