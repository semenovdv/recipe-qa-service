"""Offline tests for the DB seeding layer — ADR-003 D3.

Everything here runs without a database or network: the seeder's pure parts
(row building, embedding-text composition, merge SQL) are pinned first,
then exercised live in scripts/db_seed.py.
"""
from __future__ import annotations

import pytest

from app.db import (
    build_row,
    embedding_text,
    merge_sql,
    search_text,
    vocabularies_from_records,
)


def base_record(**kw):
    r = {
        "pageid": 4991,
        "title": "Cookbook:Baingan Bartha",
        "url": "https://en.wikibooks.org/wiki/Cookbook:Baingan_Bartha",
        "time_minutes": None,
        "servings": None,
        "ingredients_normalized": ["Ghee or oil", "panch puran", "potatoes"],
        "source_text": "==Ingredients==\nGhee, potatoes.",
        "cuisine": "Indian",
        "dish_type": "side dish",
        "diet_tags": ["vegetarian", "gluten-free"],
    }
    r.update(kw)
    return r


class TestEmbeddingText:
    def test_composes_title_ingredients_metadata(self):
        text = embedding_text(base_record())
        assert "Baingan Bartha" in text
        assert "Ghee or oil" in text
        assert "Indian" in text
        assert "side dish" in text
        assert "vegetarian" in text

    def test_handles_missing_optional_fields(self):
        text = embedding_text(base_record(
            cuisine=None, dish_type=None, diet_tags=None,
            ingredients_normalized=None))
        assert "Baingan Bartha" in text  # never crashes, always has title

    def test_deterministic(self):
        assert embedding_text(base_record()) == embedding_text(base_record())


class TestSearchText:
    def test_title_plus_ingredients(self):
        text = search_text(base_record())
        assert text == "Cookbook:Baingan Bartha Ghee or oil panch puran potatoes Indian side dish"

    def test_handles_missing_ingredients(self):
        assert search_text(base_record(ingredients_normalized=None)) == "Cookbook:Baingan Bartha Indian side dish"


class TestBuildRow:
    def test_maps_all_columns(self):
        row = build_row(base_record(), corpus_version="abc123",
                        embedding=[0.1] * 1536)
        assert row["pageid"] == 4991
        assert row["title"] == "Cookbook:Baingan Bartha"
        assert row["source_url"].startswith("https://en.wikibooks.org/wiki/")
        assert row["corpus_version"] == "abc123"
        assert row["cuisine"] == "Indian"
        assert row["diet_tags"] == ["vegetarian", "gluten-free"]
        assert row["ingredients"] == ["Ghee or oil", "panch puran", "potatoes"]
        assert row["search_text"].startswith("Cookbook:Baingan Bartha")
        assert len(row["embedding"]) == 1536

    def test_missing_diet_tags_become_empty_list(self):
        row = build_row(base_record(diet_tags=None), corpus_version="x",
                        embedding=[0.0] * 1536)
        assert row["diet_tags"] == []

    def test_rejects_missing_pageid(self):
        with pytest.raises(KeyError):
            build_row({"title": "x"}, corpus_version="x", embedding=[0.0] * 1536)


class TestMergeSql:
    def test_upsert_sql_is_idempotent_and_parameterized(self):
        sql = merge_sql()
        assert "INSERT INTO recipes" in sql
        assert "ON CONFLICT (pageid) DO UPDATE" in sql
        # every column is a placeholder — no string interpolation of data
        assert "%(" in sql
        assert "corpus_version = EXCLUDED.corpus_version" in sql


class TestVocabularies:
    def test_collects_case_preserving_values(self):
        records = [
            base_record(pageid=1, cuisine="Indian", dish_type="soup",
                        diet_tags=["vegetarian"]),
            base_record(pageid=2, cuisine="Ukrainian", dish_type="soup",
                        diet_tags=["vegan", "gluten-free"]),
            base_record(pageid=3, cuisine=None, dish_type=None, diet_tags=None),
        ]
        v = vocabularies_from_records(records)
        assert v["cuisines"] == {"Indian", "Ukrainian"}
        assert v["dish_types"] == {"soup"}
        assert v["diet_tags"] == {"vegetarian", "vegan", "gluten-free"}
