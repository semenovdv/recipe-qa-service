"""Tests for Pydantic schemas (app/schemas.py) and schema generation.

Structured outputs requirement: the same Pydantic models that validate in
code must generate strict JSON schemas for the OpenAI API
(additionalProperties: false, all fields required).
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.query_plan import QueryPlan
from app.schemas import AskResponse, Citation


class TestAskResponse:
    def test_valid_answer(self):
        r = AskResponse(
            answer="Boil water.",
            citations=[Citation(title="Cookbook:Boiling", url="https://en.wikibooks.org/wiki/Cookbook:Boiling")],
            refused=False,
            refusal_reason=None,
        )
        assert r.refused is False

    def test_valid_refusal(self):
        r = AskResponse(answer="I can only answer recipe questions.", citations=[], refused=True,
                        refusal_reason="out_of_corpus")
        assert r.refusal_reason == "out_of_corpus"

    def test_refused_requires_reason(self):
        with pytest.raises(ValidationError):
            AskResponse(answer="x", citations=[], refused=True, refusal_reason=None)

    def test_refusal_reason_must_be_from_enum(self):
        with pytest.raises(ValidationError):
            AskResponse(answer="x", citations=[], refused=True, refusal_reason="because")

    def test_answer_requires_citations(self):
        with pytest.raises(ValidationError):
            AskResponse(answer="x", citations=[], refused=False, refusal_reason=None)

    def test_answer_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            AskResponse(answer="", citations=[Citation(title="t", url="u")], refused=False,
                        refusal_reason=None)

    def test_rejects_unknown_keys(self):
        with pytest.raises(ValidationError):
            AskResponse.model_validate({
                "answer": "x", "citations": [], "refused": True,
                "refusal_reason": "safety", "extra": 1,
            })


class TestStructuredOutputSchema:
    def test_ask_response_schema_is_strict(self):
        schema = AskResponse.model_json_schema()
        # extra=forbid -> additionalProperties false at object levels
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {"answer", "citations", "refused", "refusal_reason"}

    def test_query_plan_schema_is_strict_and_serializable(self):
        schema = QueryPlan.model_json_schema()
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {
            "intent", "intent_reason", "search_query", "requirements"
        }
        assert schema["properties"]["intent"]["enum"] == [
            "recipe", "out_of_domain", "safety"
        ]
        # must survive a JSON round-trip (what we hand to the API)
        json.dumps(schema)

    def test_requirement_schema_forbids_extra(self):
        schema = QueryPlan.model_json_schema()
        req = schema["$defs"]["Requirement"] if "$defs" in schema else schema["definitions"]["Requirement"]
        assert req["additionalProperties"] is False
