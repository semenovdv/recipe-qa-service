"""Tests for QueryPlan / FilterSpec v1 — ADR-001 D2.

The extraction call emits a typed requirement list; this module must
validate it structurally (fields/ops whitelists, value types), normalize
categorical values against corpus vocabularies, and evaluate requirements
against records with conservative unknown semantics (None fails).
"""
from __future__ import annotations

import pytest

from app.query_plan import (
    FilterSpecError,
    QueryPlan,
    Requirement,
    evaluate_requirement,
    filter_records,
    normalize_plan,
    parse_plan,
)


def rec(**kw):
    base = {
        "pageid": 1,
        "title": "Borscht",
        "ingredients": ["beets", "salt", "water"],
        "cuisine": "Ukrainian",
        "dish_type": "soup",
        "diet_tags": ["vegetarian", "gluten-free"],
        "time_minutes": 75,
        "servings": 6,
    }
    base.update(kw)
    return base


class TestParsing:
    def test_valid_plan_parses(self):
        plan = parse_plan({
            "search_query": "borscht",
            "requirements": [
                {"field": "diet_tags", "op": "any", "value": ["vegetarian"]},
                {"field": "time_minutes", "op": "lte", "value": 30},
            ],
        })
        assert isinstance(plan, QueryPlan)
        assert plan.search_query == "borscht"
        assert len(plan.requirements) == 2

    def test_empty_requirements_allowed(self):
        plan = parse_plan({"search_query": "borscht", "requirements": []})
        assert plan.requirements == ()  # frozen dataclass stores a tuple

    def test_unknown_field_rejected(self):
        with pytest.raises(FilterSpecError, match="field"):
            parse_plan({"search_query": "x", "requirements": [
                {"field": "color", "op": "eq", "value": "red"}]})

    def test_op_not_allowed_for_field_rejected(self):
        # ingredients only supports `contains`; eq must be rejected
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x", "requirements": [
                {"field": "ingredients", "op": "eq", "value": "salt"}]})

    def test_numeric_field_requires_number(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x", "requirements": [
                {"field": "time_minutes", "op": "lte", "value": "fast"}]})

    def test_numeric_field_rejects_negative(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x", "requirements": [
                {"field": "time_minutes", "op": "lte", "value": -5}]})

    def test_list_field_requires_list_value(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x", "requirements": [
                {"field": "diet_tags", "op": "any", "value": "vegetarian"}]})

    def test_scalar_field_rejects_list_value(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x", "requirements": [
                {"field": "cuisine", "op": "eq", "value": ["Indian"]}]})

    def test_empty_search_query_rejected(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "   ", "requirements": []})

    def test_unknown_top_level_key_rejected(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x", "requirements": [], "limit": 5})

    def test_missing_requirements_key_rejected(self):
        with pytest.raises(FilterSpecError):
            parse_plan({"search_query": "x"})


class TestNormalization:
    def test_cuisine_normalized_and_validated_against_vocabulary(self):
        plan = parse_plan({"search_query": "x", "requirements": [
            {"field": "cuisine", "op": "eq", "value": "  ukrainian "}]})
        plan = normalize_plan(plan, {"cuisines": ["Ukrainian", "Indian"]})
        assert plan.requirements[0].value == "Ukrainian"

    def test_cuisine_outside_vocabulary_raises(self):
        plan = parse_plan({"search_query": "x", "requirements": [
            {"field": "cuisine", "op": "eq", "value": "Martian"}]})
        with pytest.raises(FilterSpecError, match="vocabulary"):
            normalize_plan(plan, {"cuisines": ["Ukrainian", "Indian"]})

    def test_diet_tags_normalized(self):
        plan = parse_plan({"search_query": "x", "requirements": [
            {"field": "diet_tags", "op": "any", "value": ["Vegetarian", "VEGAN"]}]})
        plan = normalize_plan(plan, {"diet_tags": ["vegetarian", "vegan"]})
        assert plan.requirements[0].value == ["vegetarian", "vegan"]

    def test_diet_tag_outside_vocabulary_raises(self):
        plan = parse_plan({"search_query": "x", "requirements": [
            {"field": "diet_tags", "op": "any", "value": ["carnivore"]}]})
        with pytest.raises(FilterSpecError, match="vocabulary"):
            normalize_plan(plan, {"diet_tags": ["vegetarian", "vegan"]})

    def test_unknown_vocabulary_fields_pass_through_untouched(self):
        plan = parse_plan({"search_query": "x", "requirements": [
            {"field": "time_minutes", "op": "lte", "value": 30},
            {"field": "ingredients", "op": "contains", "value": "salt flakes"},
        ]})
        out = normalize_plan(plan, {"cuisines": ["Indian"]})
        assert out.requirements[0].value == 30
        assert out.requirements[1].value == "salt flakes"


class TestEvaluation:
    def test_ingredients_contains_case_insensitive(self):
        r = Requirement("ingredients", "contains", "SALT")
        assert evaluate_requirement(r, rec()) is True

    def test_ingredients_contains_substring_match(self):
        # normalized lists carry descriptive names; containment is substring-based
        r = Requirement("ingredients", "contains", "salt")
        assert evaluate_requirement(r, rec(ingredients=["sea salt flakes", "water"])) is True

    def test_cuisine_eq_exact_after_normalization(self):
        assert evaluate_requirement(Requirement("cuisine", "eq", "Ukrainian"), rec()) is True
        assert evaluate_requirement(Requirement("cuisine", "eq", "Indian"), rec()) is False

    def test_diet_any(self):
        r = Requirement("diet_tags", "any", ["gluten-free", "halal"])
        assert evaluate_requirement(r, rec()) is True  # rec has gluten-free
        r2 = Requirement("diet_tags", "any", ["vegan", "halal"])
        assert evaluate_requirement(r2, rec()) is False

    def test_diet_all(self):
        r = Requirement("diet_tags", "all", ["vegetarian", "gluten-free"])
        assert evaluate_requirement(r, rec()) is True
        r2 = Requirement("diet_tags", "all", ["vegetarian", "vegan"])
        assert evaluate_requirement(r2, rec()) is False

    def test_time_lte(self):
        assert evaluate_requirement(Requirement("time_minutes", "lte", 75), rec()) is True
        assert evaluate_requirement(Requirement("time_minutes", "lte", 30), rec()) is False

    def test_time_gte(self):
        assert evaluate_requirement(Requirement("time_minutes", "gte", 80), rec()) is False

    def test_unknown_time_fails_conservatively(self):
        # None must fail lte/gte: unknown is not fast (SPEC 4.6)
        r = Requirement("time_minutes", "lte", 30)
        assert evaluate_requirement(r, rec(time_minutes=None)) is False
        r2 = Requirement("time_minutes", "gte", 10)
        assert evaluate_requirement(r2, rec(time_minutes=None)) is False

    def test_unknown_diet_fails_conservatively(self):
        r = Requirement("diet_tags", "any", ["vegetarian"])
        assert evaluate_requirement(r, rec(diet_tags=None)) is False
        r2 = Requirement("diet_tags", "all", ["vegetarian"])
        assert evaluate_requirement(r2, rec(diet_tags=[])) is False

    def test_servings_gte_with_unknown(self):
        assert evaluate_requirement(Requirement("servings", "gte", 4), rec()) is True
        assert evaluate_requirement(Requirement("servings", "gte", 4), rec(servings=None)) is False

    def test_title_contains_case_insensitive(self):
        assert evaluate_requirement(Requirement("title", "contains", "BORSCHT"), rec()) is True
        assert evaluate_requirement(Requirement("title", "contains", "katsu"), rec()) is False


class TestFilterRecords:
    def test_and_combination(self):
        plan = parse_plan({"search_query": "dinner", "requirements": [
            {"field": "diet_tags", "op": "any", "value": ["vegetarian"]},
            {"field": "time_minutes", "op": "lte", "value": 30},
        ]})
        records = [
            rec(pageid=1, time_minutes=20),             # passes both
            rec(pageid=2, time_minutes=60),             # fails time
            rec(pageid=3, time_minutes=None),           # unknown time -> fails
            rec(pageid=4, time_minutes=10, diet_tags=["vegan"]),  # fails diet
        ]
        out = filter_records(plan, records)
        assert [r["pageid"] for r in out] == [1]

    def test_no_requirements_returns_everything(self):
        plan = parse_plan({"search_query": "soup", "requirements": []})
        records = [rec(pageid=i) for i in (3, 1, 2)]
        assert [r["pageid"] for r in filter_records(plan, records)] == [3, 1, 2]
