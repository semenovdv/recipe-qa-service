"""Tests for the generation stage and refusal mapping (ADR-002, SPEC 7.1/7.3).

Offline: the OpenAI client is injected. Contract pinned here:

- Every citation quote must survive a verbatim (whitespace-collapsed)
  check against the retrieved record's source_text; unknown pageids are
  dropped.
- An answer whose citations all fail verification is retried once, then
  demoted to an honest out_of_corpus refusal (evidence gate) — never a
  confident answer.
- Invalid refusal reasons / malformed outputs are retried once, then
  GenerationError (mapped upstream to the 503 problem path per §7.3 —
  an infrastructure failure must not become a 200 refusal).
- Citations are ordered by first appearance of their quote in the answer.
- Provider/network errors propagate.
"""

from __future__ import annotations

import json

import pytest

from app.generate import GenerationError, build_messages, generate
from app.schemas import AskResponse

RECORDS = [
    {
        "pageid": 101,
        "title": "Cookbook:Borscht",
        "source_url": "https://en.wikibooks.org/wiki/Cookbook:Borscht",
        "source_text": "Borscht is a soup of Ukrainian origin. "
        "Cook time: about 75 minutes. Main ingredients: beets.",
    },
    {
        "pageid": 202,
        "title": "Cookbook:Tarator",
        "source_url": "https://en.wikibooks.org/wiki/Cookbook:Tarator",
        "source_text": "Tarator is a cold cucumber soup popular in Bulgaria.",
    },
]


def model_output(**over):
    d = {
        "kind": "answer",
        "answer": "Borscht is a soup of Ukrainian origin. It takes about 75 minutes. "
        "Tarator is a cold cucumber soup.",
        "refusal_reason": None,
        "refusal_subreason": "",
        "citations": [
            {"pageid": 101, "quote": "Borscht is a soup of Ukrainian origin."},
            {
                "pageid": 202,
                "quote": "Tarator is a cold cucumber soup popular in Bulgaria.",
            },
        ],
    }
    d.update(over)
    return d


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item

        class Resp:
            def __init__(self, parsed):
                self.choices = [
                    type("C", (), {"message": type("M", (), {"parsed": parsed})()})()
                ]

        return Resp(item)


class FakeClient:
    def __init__(self, responses):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(responses)


class TestHappyPath:
    def test_returns_ask_response_with_citations(self):
        out = generate(
            "tell me about borscht", RECORDS, client=FakeClient([model_output()])
        )
        assert isinstance(out, AskResponse)
        assert out.refused is False
        assert out.refusal_reason is None
        assert len(out.citations) == 2
        assert {c.url for c in out.citations} == {
            "https://en.wikibooks.org/wiki/Cookbook:Borscht",
            "https://en.wikibooks.org/wiki/Cookbook:Tarator",
        }

    def test_citations_ordered_by_first_appearance_in_answer(self):
        swapped = model_output(citations=list(reversed(model_output()["citations"])))
        out = generate("q", RECORDS, client=FakeClient([swapped]))
        urls = [c.url for c in out.citations]
        assert urls.index(
            "https://en.wikibooks.org/wiki/Cookbook:Borscht"
        ) < urls.index("https://en.wikibooks.org/wiki/Cookbook:Tarator")

    def test_duplicate_pageid_citations_deduplicated(self):
        doubled = model_output(
            citations=[
                {"pageid": 101, "quote": "Borscht is a soup of Ukrainian origin."},
                {"pageid": 101, "quote": "Cook time: about 75 minutes."},
            ]
        )
        out = generate("q", RECORDS, client=FakeClient([doubled]))
        assert len(out.citations) == 1


class TestEvidenceGate:
    def test_internal_markers_are_not_public(self):
        out = model_output(answer="Borscht is a soup. ⟦101⟧")
        result = generate("q", RECORDS, client=FakeClient([out]))
        assert "⟦" not in result.answer

    def test_internal_markers_are_not_public_on_refusal(self):
        out = model_output(
            kind="refusal",
            answer="I cannot answer this. ⟦101⟧",
            refusal_reason="out_of_corpus",
        )
        result = generate("q", RECORDS, client=FakeClient([out]))
        assert "⟦" not in result.answer

    def test_fabricated_quote_dropped_and_second_model_failure_is_operational(self):
        bad = model_output(
            citations=[{"pageid": 101, "quote": "Borscht was invented in 1832."}]
        )
        client = FakeClient([bad, bad])
        with pytest.raises(GenerationError):
            generate("q", RECORDS, client=client)
        assert len(client.chat.completions.calls) == 2

    def test_unknown_pageid_dropped(self):
        bad = model_output(citations=[{"pageid": 999, "quote": "anything"}])
        with pytest.raises(GenerationError):
            generate("q", RECORDS, client=FakeClient([bad, bad]))

    def test_one_bad_citation_keeps_the_valid_one(self):
        mixed = model_output(
            citations=[
                {"pageid": 101, "quote": "not in the source at all"},
                {
                    "pageid": 202,
                    "quote": "Tarator is a cold cucumber soup popular in Bulgaria.",
                },
            ]
        )
        out = generate("q", RECORDS, client=FakeClient([mixed]))
        assert out.refused is False
        assert [c.url for c in out.citations] == [
            "https://en.wikibooks.org/wiki/Cookbook:Tarator"
        ]

    def test_whitespace_collapsed_quotes_verify(self):
        ok = model_output(
            citations=[
                {"pageid": 101, "quote": "Borscht  is a soup\nof Ukrainian origin."},
            ]
        )
        out = generate("q", RECORDS, client=FakeClient([ok]))
        assert out.refused is False


class TestRefusals:
    def test_refusal_passthrough(self):
        out = generate(
            "what is the stock price",
            RECORDS,
            client=FakeClient(
                [
                    model_output(
                        kind="refusal",
                        answer="I can only answer recipe questions.",
                        refusal_reason="out_of_domain",
                    )
                ]
            ),
        )
        assert out.refused is True
        assert out.refusal_reason == "out_of_domain"
        assert out.citations == []

    def test_invalid_reason_retried_then_raises(self):
        client = FakeClient(
            [
                model_output(kind="refusal", refusal_reason="because"),
                model_output(kind="refusal", refusal_reason="also-bad"),
            ]
        )
        with pytest.raises(GenerationError):
            generate("q", RECORDS, client=client)
        assert len(client.chat.completions.calls) == 2

    def test_malformed_output_retried_then_raises(self):
        client = FakeClient([{"kind": "nonsense"}, {"kind": "still nonsense"}])
        with pytest.raises(GenerationError):
            generate("q", RECORDS, client=client)
        assert len(client.chat.completions.calls) == 2


class TestPromptAndErrors:
    def test_messages_contain_records_question_and_markers(self):
        msgs = build_messages("how long does borscht take?", RECORDS)
        blob = json.dumps(msgs, default=str, ensure_ascii=False)
        assert "Borscht is a soup of Ukrainian origin" in blob
        assert "how long does borscht take?" in blob
        assert "⟦101⟧" in blob

    def test_prompt_requires_a_marker_for_every_mentioned_recipe(self):
        prompt = build_messages("Find all desserts", RECORDS)[0]["content"]
        assert (
            "Every recipe or dish you mention MUST have its own source marker" in prompt
        )
        assert "one entry for every mentioned recipe" in prompt

    def test_medium_reasoning_and_response_model(self):
        client = FakeClient([model_output()])
        generate("q", RECORDS, client=client)
        call = client.chat.completions.calls[0]
        assert call["reasoning_effort"] == "medium"
        assert call["response_format"].__name__ == "GenerationOutput"

    def test_provider_error_propagates(self):
        with pytest.raises(RuntimeError):
            generate("q", RECORDS, client=FakeClient([RuntimeError("down")]))
