"""Tests for the wikitext parsing layer (dataset/parsing.py).

Written BEFORE the implementation (test-first, TEST-07). All inputs are
committed real API responses from dataset/fixtures/, so tests are
deterministic and network-free.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from dataset.parsing import (
    canonical_url,
    extract_categories,
    extract_description,
    extract_ingredient_lines,
    extract_ingredients,
    extract_steps,
    extract_summary,
    extract_title,
    normalize_variant_group,
    page_content,
    parse_time_minutes,
    parse_wikitext_page,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


BORSCHT = load_fixture("page_borscht.json")
APPLE_VARIANTS = load_fixture("pages_apple_crisp_variants.json")
UKRAINIAN_CATEGORY = load_fixture("category_ukrainian_recipes.json")


# ---------------------------------------------------------------------------
# raw accessors
# ---------------------------------------------------------------------------


class TestPageContent:
    def test_extracts_wikitext_from_borscht_fixture(self) -> None:
        content = page_content(BORSCHT, pageid=6470)
        assert "recipesummary" in content.lower()
        assert "==Ingredients==" in content

    def test_missing_page_raises(self) -> None:
        with pytest.raises(KeyError):
            page_content(BORSCHT, pageid=999999)


# ---------------------------------------------------------------------------
# summary template
# ---------------------------------------------------------------------------


class TestSummary:
    def test_extracts_time_servings_rating(self) -> None:
        summary = extract_summary(page_content(BORSCHT, 6470))
        assert summary["time_minutes"] == 75
        assert summary["servings"] == "about 6"
        assert summary["rating"] == 2
        assert summary["category"] == "Soup recipes"

    def test_missing_optional_fields_are_none(self) -> None:
        content = page_content(
            APPLE_VARIANTS, 93175
        )  # Apple Crisp I: no Time/Servings/Rating
        summary = extract_summary(content)
        assert summary["time_minutes"] is None
        assert summary["servings"] is None
        assert summary["rating"] is None
        assert summary["category"] == "Recipes for dessert"

    def test_summary_template_variant_with_spaces(self) -> None:
        # Apple Crisp II uses "{{Recipe summary" with a space and capital S.
        content = page_content(APPLE_VARIANTS, 462329)
        summary = extract_summary(content)
        assert summary["servings"] == "8"
        assert summary["category"] == "Recipes for dessert"

    def test_no_summary_template(self) -> None:
        summary = extract_summary("==Ingredients==\n* salt")
        assert summary == {
            "category": None,
            "servings": None,
            "time_minutes": None,
            "rating": None,
        }


class TestTimeParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("75 minutes", 75),
            ("90 min", 90),
            ("1 hour", 60),
            ("1 1/2 hours", 90),
            ("1–2 hours", None),  # range without single total -> ambiguous
            ("30 minutes + 24 hours", None),  # multi-phase total -> ambiguous
            ("varies", None),
            ("", None),
            ("2", None),  # bare number without a unit is ambiguous
            ("45", None),
            ("30 minutes", 30),
        ],
    )
    def test_time_values(self, raw: str, expected: int | None) -> None:
        assert parse_time_minutes(raw) == expected

    def test_none_input(self) -> None:
        assert parse_time_minutes(None) is None


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


class TestSections:
    def test_ingredient_lines_from_borscht(self) -> None:
        content = page_content(BORSCHT, 6470)
        lines = extract_ingredient_lines(content)
        assert any("potato" in line.lower() for line in lines)
        assert any("beet" in line.lower() for line in lines)
        # ingredient lines come from the Ingredients section only
        assert not any("simmer" in line.lower() for line in lines)

    def test_ingredients_normalized(self) -> None:
        content = page_content(BORSCHT, 6470)
        ingredients = extract_ingredients(content)
        # normalization keeps the preparation word but drops quantities and
        # parenthetical notes: "1½ cups thinly-sliced potatoes (about 3 …)"
        # -> "thinly-sliced potatoes"
        assert "thinly-sliced potatoes" in ingredients
        assert "thinly-sliced beets" in ingredients
        assert "water" in ingredients
        # markup must not leak into normalized names
        assert not any("[" in item or "{" in item for item in ingredients)
        # quantities are stripped from the front of every name
        assert not any(item[0].isdigit() for item in ingredients)

    def test_steps_from_borscht(self) -> None:
        content = page_content(BORSCHT, 6470)
        steps = extract_steps(content)
        assert len(steps) >= 4
        assert "saucepan" in steps[0].lower()

    def test_pages_without_procedure_yield_no_steps(self) -> None:
        assert extract_steps("==Ingredients==\n* salt") == []


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_categories_extracted(self) -> None:
        content = page_content(APPLE_VARIANTS, 462329)  # Apple Crisp II
        categories = extract_categories(content)
        assert "Recipes for dessert" in categories
        assert "Recipes using apple" in categories

    def test_description_extracted(self) -> None:
        content = page_content(BORSCHT, 6470)
        description = extract_description(content)
        assert description is not None
        assert "beetroot" in description

    def test_title_from_page(self) -> None:
        page = BORSCHT["query"]["pages"][0]
        assert extract_title(page) == "Cookbook:Borscht"

    def test_canonical_url(self) -> None:
        assert (
            canonical_url("Cookbook:Borscht")
            == "https://en.wikibooks.org/wiki/Cookbook:Borscht"
        )

    def test_canonical_url_encodes_spaces_and_non_ascii(self) -> None:
        assert (
            canonical_url("Cookbook:Borscht Ø")
            == "https://en.wikibooks.org/wiki/Cookbook:Borscht_%C3%98"
        )

    def test_variant_group(self) -> None:
        assert normalize_variant_group("Cookbook:Apple Crisp I") == "apple crisp"
        assert normalize_variant_group("Cookbook:Apple Crisp II") == "apple crisp"
        assert normalize_variant_group("Cookbook:Borscht") == "borscht"
        assert (
            normalize_variant_group("Cookbook:Palatschinken (Czech/Austrian Crepes)")
            == "palatschinken"
        )


# ---------------------------------------------------------------------------
# full page parse
# ---------------------------------------------------------------------------


class TestFullParse:
    def test_borscht_end_to_end(self) -> None:
        page = BORSCHT["query"]["pages"][0]
        record = parse_wikitext_page(page)
        assert record["pageid"] == 6470
        assert record["title"] == "Cookbook:Borscht"
        assert record["revid"] == page["revisions"][0]["revid"]
        assert record["url"].startswith(
            "https://en.wikibooks.org/wiki/Cookbook:Borscht"
        )
        assert record["summary"]["time_minutes"] == 75
        assert len(record["ingredients"]) >= 5
        assert len(record["steps"]) >= 4
        assert record["description"] and "beetroot" in record["description"]
        assert "Borscht or borshch" in record["source_text"]
        assert record["variant_group"] == "borscht"

    def test_variant_pages_share_group_but_differ(self) -> None:
        r1 = parse_wikitext_page(APPLE_VARIANTS["query"]["pages"][0])
        r2 = parse_wikitext_page(APPLE_VARIANTS["query"]["pages"][1])
        assert r1["variant_group"] == r2["variant_group"] == "apple crisp"
        assert r1["pageid"] != r2["pageid"]
        assert r1["ingredients"] != r2["ingredients"]

    def test_unstructured_page_has_nulls_not_guessed_values(self) -> None:
        r2 = parse_wikitext_page(APPLE_VARIANTS["query"]["pages"][1])  # no Time field
        assert r2["summary"]["time_minutes"] is None
