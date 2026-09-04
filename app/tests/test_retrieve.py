"""Tests for the retriever — QueryPlan → filtered hybrid-ranked records.

Offline: the SQL is generated and checked as text + params; execution is
faked. Live behavior was verified against the seeded pgvector container.
"""
from __future__ import annotations

import pytest

from app.extract import ExtractionError  # noqa: F401  (import-guard sanity)
from app.query_plan import FilterSpecError, parse_plan
from app.retrieve import (
    DENSE_DISTANCE_MAX,
    RetrievalError,
    build_search_sql,
    plan_to_params,
    plan_to_where,
    relevant_records,
    select_for_answer,
)


def plan(*requirements):
    return parse_plan({
        "intent": "recipe",
        "intent_reason": "the user asks about a recipe",
        "search_query": "dinner",
        "requirements": list(requirements),
    })


class TestPlanToWhere:
    def test_empty_requirements_gives_true(self):
        where, params = plan_to_where(plan())
        assert where == "TRUE"
        assert params == {}

    def test_ingredients_contains(self):
        where, params = plan_to_where(
            plan({"field": "ingredients", "op": "contains", "value": "salt"}))
        assert "ILIKE" in where
        assert params == {"req_0": "%salt%"}

    def test_ingredients_not_contains(self):
        where, params = plan_to_where(
            plan({"field": "ingredients", "op": "not_contains", "value": "peanut"}))
        assert "NOT EXISTS" in where
        assert params == {"req_0": "%peanut%"}

    def test_cuisine_eq(self):
        where, params = plan_to_where(
            plan({"field": "cuisine", "op": "eq", "value": "Ukrainian"}))
        assert "cuisine = %(req_0)s" in where
        assert params == {"req_0": "Ukrainian"}

    def test_diet_any_and_all(self):
        where, params = plan_to_where(plan(
            {"field": "diet_tags", "op": "any", "value": ["vegetarian"]},
            {"field": "diet_tags", "op": "all", "value": ["vegan", "halal"]},
        ))
        assert "diet_tags && %(req_0)s" in where
        assert "diet_tags @> %(req_1)s" in where
        assert params["req_0"] == ["vegetarian"]
        assert params["req_1"] == ["vegan", "halal"]

    def test_numeric_lte_gte(self):
        where, _ = plan_to_where(plan(
            {"field": "time_minutes", "op": "lte", "value": 30},
            {"field": "servings", "op": "gte", "value": 4},
        ))
        assert "time_minutes <= %(req_0)s" in where
        assert "servings >= %(req_1)s" in where

    def test_and_joined(self):
        where, params = plan_to_where(plan(
            {"field": "cuisine", "op": "eq", "value": "Indian"},
            {"field": "time_minutes", "op": "lte", "value": 45},
        ))
        assert where.count("AND") == 1
        assert set(params) == {"req_0", "req_1"}


class TestBuildSearchSql:
    def test_contains_vector_and_fts_branches(self):
        sql = build_search_sql(plan(), embed_query=True)
        assert "embedding <=> %(query_vec)s::vector" in sql
        assert "websearch_to_tsquery" in sql

    def test_no_vector_branch_when_not_embedding(self):
        sql = build_search_sql(plan(), embed_query=False)
        assert "query_vec" not in sql
        assert "ts_rank" in sql

    def test_where_is_embedded(self):
        p = plan({"field": "cuisine", "op": "eq", "value": "Indian"})
        where, _ = plan_to_where(p)
        sql = build_search_sql(p, embed_query=False)
        assert where in sql

    def test_orders_and_limits(self):
        sql = build_search_sql(plan(), embed_query=False)
        assert "LIMIT %(limit)s" in sql

    def test_relevance_gate_runs_before_limit(self):
        sql = build_search_sql(plan(), embed_query=True)
        assert "dense_distance <=" in sql
        assert sql.index("WHERE fts_rank > 0") < sql.index("LIMIT %(limit)s")


class TestRelevanceAndSelection:
    def test_relevance_gate_rejects_below_threshold(self):
        records = [
            {"pageid": 1, "fts_rank": 0, "dense_distance": 0.71},
            {"pageid": 2, "fts_rank": 0.2, "dense_distance": 0.99},
            {"pageid": 3, "fts_rank": 0, "dense_distance": 0.70},
        ]
        assert [r["pageid"] for r in relevant_records(records)] == [2, 3]

    def test_selection_passes_all_ranked_records_to_generation(self):
        records = [{"pageid": 20}, {"pageid": 3}, {"pageid": 11}]
        assert [r["pageid"] for r in select_for_answer("How do I make soup?", records)] == [20, 3, 11]

    def test_comparison_keeps_relevant_candidates_in_rank_order(self):
        records = [{"pageid": 20}, {"pageid": 3}]
        assert select_for_answer("Compare these recipes", records) == records


class TestPlanToParams:
    def test_merges_where_params_and_query_text(self):
        _, where_params = plan_to_where(
            plan({"field": "cuisine", "op": "eq", "value": "Indian"}))
        params = plan_to_params(
            plan({"field": "cuisine", "op": "eq", "value": "Indian"}),
            where_params, embed_query=False, limit=5,
        )
        assert params["req_0"] == "Indian"
        assert params["search_query"] == "dinner"
        assert params["limit"] == 5
        assert "query_vec" not in params
