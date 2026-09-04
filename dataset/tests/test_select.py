"""Tests for deterministic corpus selection from category candidates.

Test-first (TEST-07): written before dataset/select.py exists. Selection must
be deterministic (same candidates -> same corpus), respect per-category quotas,
dedupe by pageid, exclude meta pages, and stay within the 40–60 record bounds
(CORP-03/04/05, dataset/PLAN.md §3/§6).
"""

from __future__ import annotations

import pytest

from dataset.select import (
    Candidate,
    filter_candidates,
    select_candidates,
)


def cand(pageid: int, title: str, category: str) -> Candidate:
    return Candidate(pageid=pageid, title=title, category=category)


UKRAINIAN = [
    cand(
        85867, "Cookbook:Cabbage Rolls in Tomato Sauce (Holubtsi)", "Ukrainian recipes"
    ),
    cand(16649, "Cookbook:Ukrainian Cabbage Soup (Kapusniak)", "Ukrainian recipes"),
    cand(18447, "Cookbook:Ukrainian Cornmeal Stuffing (Nachynka)", "Ukrainian recipes"),
]
INDIAN = [
    cand(101, "Cookbook:Baingan Bartha I", "Indian recipes"),
    cand(102, "Cookbook:Chicken Curry I", "Indian recipes"),
    cand(103, "Cookbook:Chole", "Indian recipes"),
]
DESSERTS = [
    cand(201, "Cookbook:Apple Crisp I", "Dessert recipes"),
    cand(202, "Cookbook:Apple Crisp II", "Dessert recipes"),
    cand(203, "Cookbook:Anzac Biscuits I", "Dessert recipes"),
]
META = [
    cand(300, "Cookbook:Ingredients", "Dessert recipes"),
    cand(301, "Cookbook:Standard Units of Measurements", "Dessert recipes"),
    cand(302, "Cookbook:Conversion tables", "Dessert recipes"),
]


class TestFilterCandidates:
    def test_meta_pages_excluded(self) -> None:
        candidates = DESSERTS + META
        kept = filter_candidates(candidates)
        assert all(
            c.title
            not in {
                "Cookbook:Ingredients",
                "Cookbook:Standard Units of Measurements",
                "Cookbook:Conversion tables",
            }
            for c in kept
        )
        assert {c.pageid for c in kept} == {201, 202, 203}

    def test_case_insensitive_meta_match(self) -> None:
        kept = filter_candidates([cand(303, "Cookbook:INGREDIENTS", "Soup recipes")])
        assert kept == []


class TestSelectCandidates:
    def test_quota_limits_per_category(self) -> None:
        quotas = {"Ukrainian recipes": 2, "Indian recipes": 2, "Dessert recipes": 2}
        pool = UKRAINIAN + INDIAN + DESSERTS
        selected = select_candidates(pool, quotas, target_count=6, min_count=0)
        counts: dict[str, int] = {}
        for c in selected:
            counts[c.category] = counts.get(c.category, 0) + 1
        assert counts == {
            "Ukrainian recipes": 2,
            "Indian recipes": 2,
            "Dessert recipes": 2,
        }

    def test_target_count_overall(self) -> None:
        quotas = {"Ukrainian recipes": 3, "Indian recipes": 3, "Dessert recipes": 3}
        pool = UKRAINIAN + INDIAN + DESSERTS
        selected = select_candidates(pool, quotas, target_count=7, min_count=0)
        assert len(selected) == 7

    def test_small_category_gets_filled_from_larger_ones(self) -> None:
        # Ukrainian has only 3 candidates; target 8 must still be met from others
        quotas = {"Ukrainian recipes": 3, "Indian recipes": 6, "Dessert recipes": 6}
        pool = UKRAINIAN + INDIAN + DESSERTS
        selected = select_candidates(pool, quotas, target_count=8, min_count=0)
        assert len(selected) == 8

    def test_dedupe_by_pageid(self) -> None:
        # same page listed under two categories (cabbage rolls in both)
        duplicated = UKRAINIAN + [
            cand(16649, "Cookbook:Ukrainian Cabbage Soup (Kapusniak)", "Soup recipes")
        ]
        extra = [
            cand(401, "Cookbook:Kapusniak II", "Soup recipes"),
            cand(402, "Cookbook:Borscht", "Soup recipes"),
            cand(501, "Cookbook:Pasta", "Italian recipes"),
        ]
        quotas = {"Ukrainian recipes": 3, "Soup recipes": 4, "Italian recipes": 1}
        pool = duplicated + extra
        selected = select_candidates(pool, quotas, target_count=6, min_count=0)
        pageids = [c.pageid for c in selected]
        assert len(pageids) == len(set(pageids))
        # the deduped page appears once, attributed to its first category
        # (sorted category order: Italian < Soup < Ukrainian)
        assert sum(1 for c in selected if c.pageid == 16649) == 1

    def test_deterministic_ordering(self) -> None:
        quotas = {"Ukrainian recipes": 2, "Indian recipes": 2, "Dessert recipes": 2}
        pool = list(reversed(UKRAINIAN + INDIAN + DESSERTS))
        selected_a = select_candidates(pool, quotas, target_count=6, min_count=0)
        selected_b = select_candidates(list(pool), quotas, target_count=6, min_count=0)
        assert selected_a == selected_b

    def test_round_robin_spreads_across_categories(self) -> None:
        quotas = {"Ukrainian recipes": 3, "Indian recipes": 3, "Dessert recipes": 3}
        pool = UKRAINIAN + INDIAN + DESSERTS
        selected = select_candidates(pool, quotas, target_count=6, min_count=0)
        # first six picks must touch all three categories, in sorted category
        # order (Dessert < Indian < Ukrainian)
        categories_in_order = []
        for c in selected:
            if c.category not in categories_in_order:
                categories_in_order.append(c.category)
        assert categories_in_order == [
            "Dessert recipes",
            "Indian recipes",
            "Ukrainian recipes",
        ]

    def test_target_below_floor_raises(self) -> None:
        quotas = {"Ukrainian recipes": 3}
        with pytest.raises(ValueError):
            select_candidates(UKRAINIAN, quotas, target_count=30)

    def test_unreachable_target_raises(self) -> None:
        quotas = {"Ukrainian recipes": 3}
        with pytest.raises(ValueError):
            select_candidates(UKRAINIAN, quotas, target_count=50)
