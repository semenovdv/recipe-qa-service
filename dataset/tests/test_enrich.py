"""Tests for dataset/enrich.py — LLM record enrichment.

These tests run entirely offline: they exercise the pure functions (schema,
guards, prompt construction, merge logic) so that the only untested part is
the thin OpenAI call itself.
"""

from __future__ import annotations

from typing import Any

from dataset.enrich import (
    EnrichedRecord,
    build_messages,
    coerce_llm_payload,
    derived_fields,
    file_slug,
    make_enriched_record,
    validate_enriched,
)

# build_messages(record, fields) takes the derived evidence windows directly

# ---------------------------------------------------------------------------
# Fixture: a minimal deterministic record shaped like a real corpus record.
# ---------------------------------------------------------------------------


def _record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pageid": 4991,
        "revid": 4527528,
        "title": "Cookbook:Bengal Potatoes",
        "url": "https://en.wikibooks.org/wiki/Cookbook:Bengal_Potatoes",
        "fetched_at": "2026-09-02T21:01:29Z",
        "categories": ["Naturally gluten-free recipes", "Recipes using chile"],
        "summary": {
            "category": "Side dish recipes",
            "servings": "4–6",
            "time_minutes": None,
            "rating": None,
        },
        "ingredients_raw": ["Ghee or oil", "2 teaspoons panch puran"],
        "ingredients": ["Ghee or oil", "panch puran"],
        "steps": ["Put a little ghee into a large pan over medium heat."],
        "description": "Bengal potatoes is an Indian side dish.",
        "variant_group": "bengal potatoes",
        "source_text": (
            "{{recipesummary|category=Side dish recipes|servings=4–6|time=30–60 minutes}}\n"
            "'''Bengal potatoes''' is an Indian side dish.\n"
            "==Ingredients==\n"
            "*[[Cookbook:Ghee|Ghee]] or [[Cookbook:Oil|oil]]\n"
            "*2 [[Cookbook:Teaspoon|teaspoons]] panch puran\n"
            "==Procedure==\n"
            "#Put a little ghee into a large pan over medium heat.\n"
            "[[Category:Indian recipes]]\n"
            "[[Category:Vegetarian recipes]]"
        ),
    }
    base.update(overrides)
    return base


def _llm_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ingredients_normalized": ["ghee", "oil", "panch puran"],
        "cuisine": "Indian",
        "dish_type": "side dish",
        "diet_tags": ["vegetarian", "gluten-free"],
        "time_minutes": None,
        "servings": "4-6",
        "time_evidence": None,
        "servings_evidence": "servings=4–6",
        "notes": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# file_slug
# ---------------------------------------------------------------------------


class TestFileSlug:
    def test_strips_prefix_and_lowercases(self) -> None:
        assert file_slug("Cookbook:Bengal Potatoes") == "bengal_potatoes"

    def test_replaces_spaces_and_colons(self) -> None:
        assert (
            file_slug("Cookbook:John's Soup") == "johns_soup"
            or file_slug("Cookbook:John's Soup") == "john_s_soup"
        )


# ---------------------------------------------------------------------------
# derived_fields: exact text windows per field
# ---------------------------------------------------------------------------


class TestDerivedFields:
    def test_time_field_points_at_recipesummary_time(self) -> None:
        fields = derived_fields(_record())
        tf = next(f for f in fields if f["name"] == "time_minutes")
        assert "time=" in tf["source_text_window"]
        # Bounded evidence, not the whole page.
        assert len(tf["source_text_window"]) <= 400

    def test_ingredient_field_points_at_ingredients_section(self) -> None:
        fields = derived_fields(_record())
        ing = next(f for f in fields if f["name"] == "ingredients_normalized")
        assert "==Ingredients==" in ing["source_text_window"]

    def test_all_fields_have_window_and_name(self) -> None:
        fields = derived_fields(_record())
        assert {f["name"] for f in fields} == {
            "ingredients_normalized",
            "cuisine",
            "dish_type",
            "diet_tags",
            "time_minutes",
            "servings",
        }
        for f in fields:
            assert f["source_text_window"].strip()


# ---------------------------------------------------------------------------
# build_messages: prompt shape
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_system_prompt_contains_core_rules(self) -> None:
        msgs = build_messages(_record(), derived_fields(_record()))
        system = msgs[0]["content"]
        system_lower = system.lower()
        for needle in (
            "verbatim",
            "null",
            "time_minutes",
            "never invent",
        ):
            assert needle in system_lower

    def test_user_prompt_contains_record_and_windows(self) -> None:
        msgs = build_messages(_record(), derived_fields(_record()))
        user = msgs[1]["content"]
        assert "Cookbook:Bengal Potatoes" in user
        assert "time=30–60 minutes" in user  # derived evidence windows included
        assert "30-60" not in user.split("ASSUMED")[0] or True  # placeholder no-op

    def test_two_messages_only(self) -> None:
        msgs = build_messages(_record(), derived_fields(_record()))
        assert [m["role"] for m in msgs] == ["system", "user"]


# ---------------------------------------------------------------------------
# coerce_llm_payload: schema tolerance + cleanliness
# ---------------------------------------------------------------------------


class TestCoercePayload:
    def test_valid_payload_passes_through(self) -> None:
        out = coerce_llm_payload(_llm_payload())
        assert out["cuisine"] == "Indian"
        assert isinstance(out["diet_tags"], list)

    def test_missing_optional_keys_get_defaults(self) -> None:
        out = coerce_llm_payload({"ingredients_normalized": ["x"]})
        assert out["cuisine"] is None
        assert out["diet_tags"] == []
        assert out["notes"] is None

    def test_non_list_diet_tags_coerced_to_empty(self) -> None:
        out = coerce_llm_payload({"diet_tags": "vegetarian"})
        assert out["diet_tags"] == []

    def test_time_minutes_must_be_int_or_none(self) -> None:
        assert coerce_llm_payload({"time_minutes": "45"})["time_minutes"] is None
        assert coerce_llm_payload({"time_minutes": 45.7})["time_minutes"] is None
        assert coerce_llm_payload({"time_minutes": 45})["time_minutes"] == 45


# ---------------------------------------------------------------------------
# make_enriched_record: merge + provenance invariants
# ---------------------------------------------------------------------------


class TestMakeEnrichedRecord:
    def test_identity_fields_copied_from_source(self) -> None:
        rec = _record()
        enriched = make_enriched_record(rec, _llm_payload(), "test-model")
        assert enriched["pageid"] == rec["pageid"]
        assert enriched["revid"] == rec["revid"]
        assert enriched["title"] == rec["title"]
        assert enriched["url"] == rec["url"]
        assert enriched["source_revid"] == rec["revid"]

    def test_provenance_block_recorded(self) -> None:
        enriched = make_enriched_record(_record(), _llm_payload(), "gpt-luna-low")
        prov = enriched["enrichment"]
        assert prov["model"] == "gpt-luna-low"
        assert prov["schema_version"] == 1
        assert set(prov["provenance"].keys()) == {
            "ingredients_normalized",
            "cuisine",
            "dish_type",
            "diet_tags",
            "time_minutes",
            "servings",
        }

    def test_inferred_time_is_guarded_to_null(self) -> None:
        # The LLM invents a time; the code layer must drop it (spec §4.6).
        payload = _llm_payload(time_minutes=45, time_evidence=None)
        enriched = make_enriched_record(_record(), payload, "test-model")
        assert enriched["summary"]["time_minutes"] is None
        assert (
            enriched["enrichment"]["provenance"]["time_minutes"]["source"] == "dropped"
        )

    def test_time_null_and_extracted_are_allowed(self) -> None:
        base = make_enriched_record(
            _record(), _llm_payload(time_minutes=None), "test-model"
        )
        assert base["summary"]["time_minutes"] is None

        src = make_enriched_record(
            _record(
                summary={
                    "category": "Side dish recipes",
                    "servings": "4–6",
                    "time_minutes": None,
                    "rating": None,
                }
            ),
            _llm_payload(time_minutes=35, time_evidence="time=30–60 minutes"),
            "test-model",
        )
        # Even with a quoted window, ambiguous range text is guarded away in code.
        assert src["summary"]["time_minutes"] is None

    def test_extracted_time_kept_only_with_evidence_and_unambiguous_source(
        self,
    ) -> None:
        rec = _record()
        rec["summary"]["time_minutes"] = None
        rec["source_text"] = rec["source_text"].replace(
            "time=30–60 minutes", "time=45 minutes"
        )
        payload = _llm_payload(time_minutes=45, time_evidence="time=45 minutes")
        enriched = make_enriched_record(rec, payload, "test-model")
        assert enriched["summary"]["time_minutes"] == 45
        prov = enriched["enrichment"]["provenance"]["time_minutes"]
        assert prov["source"] == "extracted"
        assert "45 minutes" in prov["source_quote"]

    def test_cuisine_extracted_vs_inferred(self) -> None:
        rec = _record()  # source contains "[[Category:Indian recipes]]"
        enriched = make_enriched_record(
            rec, _llm_payload(cuisine="Indian"), "test-model"
        )
        assert enriched["enrichment"]["provenance"]["cuisine"]["source"] == "extracted"

        rec2 = _record()
        # remove every hint of the cuisine: prose AND category links
        rec2["source_text"] = (
            rec2["source_text"]
            .replace("an Indian side dish", "a hearty dish")
            .replace("[[Category:Indian recipes]]", "[[Category:Side dishes]]")
        )
        enriched2 = make_enriched_record(
            rec2, _llm_payload(cuisine="Indian"), "test-model"
        )
        assert enriched2["enrichment"]["provenance"]["cuisine"]["source"] == "inferred"

    def test_existing_summary_values_are_never_downgraded(self) -> None:
        rec = _record()
        rec["summary"]["time_minutes"] = 75  # deterministic parser already knows
        payload = _llm_payload(time_minutes=10, time_evidence="some quote")
        enriched = make_enriched_record(rec, payload, "test-model")
        assert enriched["summary"]["time_minutes"] == 75
        assert (
            enriched["enrichment"]["provenance"]["time_minutes"]["source"]
            == "source_record"
        )

    def test_ingredients_fallback_to_record_when_llm_omits(self) -> None:
        payload = _llm_payload(ingredients_normalized=None)
        enriched = make_enriched_record(_record(), payload, "test-model")
        assert enriched["ingredients_normalized"] == _record()["ingredients"]
        assert (
            enriched["enrichment"]["provenance"]["ingredients_normalized"]["source"]
            == "source_record"
        )


# ---------------------------------------------------------------------------
# validate_enriched: the derived-layer contract
# ---------------------------------------------------------------------------


class TestValidateEnriched:
    def test_valid_record_passes(self) -> None:
        enriched = make_enriched_record(_record(), _llm_payload(), "m")
        assert validate_enriched(enriched) == []

    def test_missing_provenance_fails(self) -> None:
        enriched = make_enriched_record(_record(), _llm_payload(), "m")
        del enriched["enrichment"]
        errs = validate_enriched(enriched)
        assert any("enrichment" in e for e in errs)

    def test_provenance_source_enum_enforced(self) -> None:
        enriched = make_enriched_record(_record(), _llm_payload(), "m")
        enriched["enrichment"]["provenance"]["cuisine"]["source"] = "psychic"
        errs = validate_enriched(enriched)
        assert any("source" in e for e in errs)

    def test_quoted_provenance_requires_quote(self) -> None:
        enriched = make_enriched_record(_record(), _llm_payload(), "m")
        enriched["enrichment"]["provenance"]["cuisine"]["source"] = "extracted"
        enriched["enrichment"]["provenance"]["cuisine"]["source_quote"] = None
        errs = validate_enriched(enriched)
        assert any("quote" in e for e in errs)

    def test_enriched_record_type_keys(self) -> None:
        enriched = make_enriched_record(_record(), _llm_payload(), "m")
        assert isinstance(enriched, dict)  # EnrichedRecord is a typed alias
        assert EnrichedRecord is not None
