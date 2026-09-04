"""Deterministic selection of which candidate pages enter the corpus.

Pure functions (dataset/PLAN.md §2). Selection depends only on the candidate
list and the committed configuration — same inputs yield the same corpus
(dataset/PLAN.md §5).
"""

from __future__ import annotations

from dataclasses import dataclass

# Meta/service pages that appear in recipe categories but are not recipes
# (dataset/PLAN.md §12 risk 1). Matched case-insensitively on the full title.
META_PAGE_TITLES = frozenset(
    {
        "cookbook:ingredients",
        "cookbook:standard units of measurements",
        "cookbook:conversion tables",
        "cookbook:units of measurements",
        "cookbook:kitchen equipment",
        "cookbook:basic food substitutions",
        "cookbook:help",
    }
)

CORPUS_FLOOR = 40  # CORP-03: the corpus must hold at least 40 recipes


@dataclass(frozen=True)
class Candidate:
    """A recipe page candidate discovered in a category listing."""

    pageid: int
    title: str
    category: str


def filter_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Drop meta/service pages that are not recipes."""
    return [c for c in candidates if c.title.strip().lower() not in META_PAGE_TITLES]


def select_candidates(
    candidates: list[Candidate],
    quotas: dict[str, int],
    target_count: int,
    min_count: int = CORPUS_FLOOR,
) -> list[Candidate]:
    """Pick ``target_count`` candidates deterministically.

    Algorithm (dataset/PLAN.md §3 step 4, §6):

    1. filter meta pages, order by (category, title), dedupe by pageid;
    2. walk categories round-robin in sorted order; each pass takes one unused
       candidate from every category that still has unused quota;
    3. repeat passes until the target is met, all quotas are consumed, or no
       category can contribute.

    ``target_count`` must not be below ``min_count`` (the corpus floor, 40 in
    production; tests pass 0 for small pools).

    Raises ValueError when the target is below the floor or unreachable with
    the given pool and quotas.
    """
    if target_count < min_count:
        raise ValueError(
            f"target_count {target_count} is below the corpus floor of "
            f"{min_count} (CORP-03)"
        )

    ordered = sorted(filter_candidates(candidates), key=lambda c: (c.category, c.title))

    by_category: dict[str, list[Candidate]] = {}
    seen_pageids: set[int] = set()
    total_unique = 0
    for candidate in ordered:
        if candidate.pageid not in seen_pageids:
            seen_pageids.add(candidate.pageid)
            total_unique += 1
        by_category.setdefault(candidate.category, []).append(candidate)

    if target_count > total_unique:
        raise ValueError(
            f"target_count {target_count} unreachable: only {total_unique} unique "
            "candidates available after filtering"
        )

    # Per-category cursor and quota usage.
    cursor = {category: 0 for category in by_category}
    quota_left = {
        category: min(quota, len(by_category.get(category, [])))
        for category, quota in quotas.items()
    }
    selected_pageids: set[int] = set()
    selected: list[Candidate] = []

    progressed = True
    while len(selected) < target_count and progressed:
        progressed = False
        for category in sorted(by_category):
            if len(selected) >= target_count:
                break
            if quota_left.get(category, 0) <= 0:
                continue
            members = by_category[category]
            # find the next member of this category not already selected
            while (
                cursor[category] < len(members)
                and members[cursor[category]].pageid in selected_pageids
            ):
                cursor[category] += 1
            if cursor[category] >= len(members):
                # every member either selected or exhausted: this category is done
                quota_left[category] = 0
                continue
            candidate = members[cursor[category]]
            selected.append(candidate)
            selected_pageids.add(candidate.pageid)
            cursor[category] += 1
            quota_left[category] -= 1
            progressed = True

    if len(selected) < target_count:
        raise ValueError(
            f"target_count {target_count} unreachable under quotas: "
            f"only {len(selected)} selectable"
        )

    return selected
