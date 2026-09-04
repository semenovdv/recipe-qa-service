from types import SimpleNamespace

import pytest

from app.pipeline import LunaPipeline, PipelineUnavailable
from app.query_plan import parse_plan


def record(pageid: int) -> dict:
    return {
        "pageid": pageid,
        "title": f"Cookbook:Recipe {pageid}",
        "source_url": f"https://en.wikibooks.org/wiki/Cookbook:Recipe_{pageid}",
        "source_text": "Recipe source text with ingredients and steps.",
    }


class FakeRetriever:
    class RetrievalError(Exception):
        pass

    def __init__(self, records):
        self.records = records

    def search(self, plan, query_vec, database_url):
        return self.records

    @staticmethod
    def relevant_records(records):
        return records

    @staticmethod
    def is_comparison_question(question):
        return "compare" in question.lower()

    @staticmethod
    def select_for_answer(question, records):
        if "compare" in question.lower():
            return records
        return [min(records, key=lambda item: item["pageid"])]


class FakeEmbeddings:
    def create(self, **kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])


class FakeClient:
    embeddings = FakeEmbeddings()


class ExplodingEmbeddings:
    def create(self, **kwargs):
        raise AssertionError("embedding must not be called for a non-recipe plan")


class NonRecipeClient:
    embeddings = ExplodingEmbeddings()


def make_pipeline(records):
    pipeline = object.__new__(LunaPipeline)
    pipeline._client = FakeClient()
    pipeline._retrieve = FakeRetriever(records)
    pipeline._settings = SimpleNamespace(database_url="db")
    pipeline._vocabularies = {}
    pipeline._log = SimpleNamespace(info=lambda *args, **kwargs: None)
    return pipeline


def test_safety_is_refused_after_llm_plan_before_any_downstream_call(monkeypatch):
    pipeline = make_pipeline([record(1)])
    pipeline._client = NonRecipeClient()
    calls = []
    monkeypatch.setattr(
        "app.extract.extract_plan",
        lambda *args, **kwargs: calls.append(args[0])
        or parse_plan(
            {
                "intent": "safety",
                "intent_reason": "the user asks for an allergy safety guarantee",
                "search_query": "",
                "requirements": [],
            }
        ),
    )
    out = pipeline.answer("Is this recipe nut-free?", "req-1")
    assert calls == ["Is this recipe nut-free?"]
    assert out["refused"] is True
    assert out["refusal_reason"] == "safety"


def test_out_of_domain_is_refused_after_llm_plan_before_any_downstream_call(
    monkeypatch,
):
    pipeline = make_pipeline([record(1)])
    pipeline._client = NonRecipeClient()
    calls = []
    monkeypatch.setattr(
        "app.extract.extract_plan",
        lambda *args, **kwargs: calls.append(args[0])
        or parse_plan(
            {
                "intent": "out_of_domain",
                "intent_reason": "the user asks about weather",
                "search_query": "",
                "requirements": [],
            }
        ),
    )
    out = pipeline.answer("What is the weather tomorrow?", "req-1")
    assert calls == ["What is the weather tomorrow?"]
    assert out["refused"] is True
    assert out["refusal_reason"] == "out_of_domain"


def test_unmatchable_constraint_is_a_business_refusal(monkeypatch):
    from app.extract import UnsupportedConstraintError

    pipeline = make_pipeline([record(1)])
    monkeypatch.setattr(
        "app.extract.extract_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            UnsupportedConstraintError("missing")
        ),
    )
    out = pipeline.answer("Find a Martian recipe", "req-1")
    assert out["refusal_reason"] == "out_of_corpus"


def test_singular_answer_receives_only_lowest_stable_id(monkeypatch):
    pipeline = make_pipeline([record(20), record(3)])
    captured = {}

    monkeypatch.setattr(
        "app.extract.extract_plan",
        lambda *args, **kwargs: parse_plan(
            {
                "intent": "recipe",
                "intent_reason": "the user asks how to cook",
                "search_query": "soup",
                "requirements": [],
            }
        ),
    )
    from app.schemas import AskResponse

    def fake_generate(question, records, client):
        captured["records"] = records
        return AskResponse(
            answer="supported",
            citations=[{"title": records[0]["title"], "url": records[0]["source_url"]}],
            refused=False,
            refusal_reason=None,
        )

    monkeypatch.setattr("app.generate.generate", fake_generate)
    out = pipeline.answer("How do I make soup?", "req-1")
    assert out["refused"] is False
    assert [r["pageid"] for r in captured["records"]] == [3]


def test_provider_failure_becomes_pipeline_unavailable(monkeypatch):
    pipeline = make_pipeline([record(1)])
    monkeypatch.setattr(
        "app.extract.extract_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    with pytest.raises(PipelineUnavailable):
        pipeline.answer("How do I cook soup?", "req-1")
