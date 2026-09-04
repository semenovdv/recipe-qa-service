"""Tests for the extraction stage — question → QueryPlan (ADR-001 D1/D2).

Offline: the OpenAI client is injected as a fake. The stage must call
structured outputs with reasoning_effort="none", retry once on an invalid
plan (with the validator error appended per ADR-001), apply corpus
vocabulary normalization, and raise ExtractionError when retries are
exhausted (mapped to the 503 dependency path, never a fake answer).
"""

from __future__ import annotations

import pytest

from app.extract import (
    ExtractionError,
    UnsupportedConstraintError,
    build_messages,
    extract_plan,
)


class FakeCompletions:
    """Scripted stand-in for client.chat.completions.parse."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item

        class Msg:
            def __init__(self, parsed):
                self.parsed = parsed

        class Choice:
            def __init__(self, parsed):
                self.message = Msg(parsed)

        class Resp:
            def __init__(self, parsed):
                self.choices = [Choice(parsed)]

        return Resp(item)


class FakeClient:
    def __init__(self, responses):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(responses)


def plan_dict(**over):
    d = {
        "intent": "recipe",
        "intent_reason": "the user wants a recipe",
        "search_query": "quick vegetarian dinner",
        "requirements": [
            {"field": "diet_tags", "op": "any", "value": ["vegetarian"]},
            {"field": "time_minutes", "op": "lte", "value": 30},
        ],
    }
    d.update(over)
    return d


class TestExtractPlan:
    def test_happy_path_returns_validated_plan(self):
        client = FakeClient([plan_dict()])
        plan = extract_plan("vegetarian dinner under 30 minutes", client=client)
        assert plan.intent == "recipe"
        assert plan.intent_reason == "the user wants a recipe"
        assert plan.search_query == "quick vegetarian dinner"
        assert len(plan.requirements) == 2

    def test_llm_plan_can_classify_safety_without_search_payload(self):
        client = FakeClient(
            [
                plan_dict(
                    intent="safety",
                    intent_reason="the user asks for an allergy safety assessment",
                    search_query="",
                    requirements=[],
                )
            ]
        )
        plan = extract_plan("Could this be safe for a peanut allergy?", client=client)
        assert plan.intent == "safety"
        assert plan.search_query == ""
        assert plan.requirements == ()

    def test_uses_none_reasoning_and_response_model(self):
        client = FakeClient([plan_dict()])
        extract_plan("q", client=client)
        call = client.chat.completions.calls[0]
        assert call["reasoning_effort"] == "none"
        assert call["response_format"].__name__ == "QueryPlan"

    def test_messages_contain_question(self):
        msgs = build_messages("how to cook borscht?")
        assert any("how to cook borscht?" in str(m) for m in msgs)

    def test_invalid_first_response_retried_once(self):
        client = FakeClient(
            [
                {
                    "intent": "recipe",
                    "intent_reason": "recipe request",
                    "search_query": "x",
                    "requirements": [{"field": "cuisine", "op": "eq", "value": 42}],
                },  # invalid
                plan_dict(),
            ]
        )
        plan = extract_plan("q", client=client)
        assert plan.search_query == "quick vegetarian dinner"
        assert len(client.chat.completions.calls) == 2
        # the retry must carry the validator error hint
        retry_msgs = client.chat.completions.calls[1]["messages"]
        assert any("rejected" in str(m).lower() for m in retry_msgs)

    def test_exhausted_retries_raise_extraction_error(self):
        client = FakeClient(
            [
                {
                    "intent": "recipe",
                    "intent_reason": "recipe request",
                    "search_query": "",
                    "requirements": [],
                },
                {
                    "intent": "recipe",
                    "intent_reason": "recipe request",
                    "search_query": "",
                    "requirements": [],
                },
            ]
        )
        with pytest.raises(ExtractionError):
            extract_plan("q", client=client)
        assert len(client.chat.completions.calls) == 2

    def test_provider_error_not_swallowed_as_plan_error(self):
        client = FakeClient([RuntimeError("connection down")])
        with pytest.raises(RuntimeError):
            extract_plan("q", client=client)

    def test_vocabulary_normalization_applied(self):
        client = FakeClient(
            [
                plan_dict(
                    requirements=[
                        {"field": "cuisine", "op": "eq", "value": "ukrainian"}
                    ]
                )
            ]
        )
        plan = extract_plan(
            "q", client=client, vocabularies={"cuisines": {"Ukrainian", "Indian"}}
        )
        assert plan.requirements[0].value == "Ukrainian"

    def test_out_of_vocabulary_retried_then_raises(self):
        client = FakeClient(
            [
                plan_dict(
                    requirements=[{"field": "cuisine", "op": "eq", "value": "Martian"}]
                ),
                plan_dict(
                    requirements=[{"field": "cuisine", "op": "eq", "value": "Atlantis"}]
                ),
            ]
        )
        with pytest.raises(UnsupportedConstraintError):
            extract_plan(
                "q", client=client, vocabularies={"cuisines": {"Ukrainian", "Indian"}}
            )
        assert len(client.chat.completions.calls) == 2
