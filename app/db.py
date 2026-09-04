"""Pure database layer — ADR-003 D3.

No connections here: these are the deterministic pieces the seeder (and,
later, the retriever) share — embedding text, row mapping, idempotent
upsert SQL, and corpus vocabularies. Connection handling lives in
scripts/db_seed.py; SQL translation of FilterSpec arrives with the
retriever (tested there).
"""

from __future__ import annotations

EMBEDDING_DIM = 1536  # text-embedding-3-small

_COLUMNS = (
    "pageid",
    "title",
    "source_url",
    "corpus_version",
    "time_minutes",
    "servings",
    "cuisine",
    "dish_type",
    "diet_tags",
    "ingredients",
    "source_text",
    "search_text",
    "embedding",
)


def embedding_text(record: dict) -> str:
    """The logical text embedded per record (ADR-001 D3: recipe-level)."""
    parts = [
        record.get("title") or "",
        " ".join(record.get("ingredients_normalized") or []),
        record.get("cuisine") or "",
        record.get("dish_type") or "",
        " ".join(record.get("diet_tags") or []),
    ]
    return " ".join(p for p in parts if p).strip()


def search_text(record: dict) -> str:
    """Text fed to Postgres FTS (title + normalized metadata)."""
    parts = [
        record.get("title") or "",
        " ".join(record.get("ingredients_normalized") or []),
        record.get("cuisine") or "",
        record.get("dish_type") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def build_row(record: dict, corpus_version: str, embedding: list[float]) -> dict:
    """Map a merged corpus+enriched record to a `recipes` row dict."""
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"embedding must be {EMBEDDING_DIM}-dimensional")
    return {
        "pageid": record["pageid"],
        "title": record["title"],
        "source_url": record["url"],
        "corpus_version": corpus_version,
        "time_minutes": record.get("time_minutes"),
        "servings": record.get("servings"),
        "cuisine": record.get("cuisine"),
        "dish_type": record.get("dish_type"),
        "diet_tags": list(record.get("diet_tags") or []),
        "ingredients": list(record.get("ingredients_normalized") or []),
        "source_text": record.get("source_text") or "",
        "search_text": search_text(record),
        "embedding": embedding,
    }


def merge_sql() -> str:
    """Idempotent, fully parameterized upsert for the recipes table."""
    cols = ", ".join(_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS if c != "pageid")
    return (
        f"INSERT INTO recipes ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (pageid) DO UPDATE SET {updates}"
    )


def vocabularies_from_records(records: list[dict]) -> dict[str, set[str]]:
    """Derive FilterSpec vocabularies from the corpus (ADR-001 D2).

    Canonical (case-preserving) values as they appear in the enriched layer.
    """
    cuisines: set[str] = set()
    dish_types: set[str] = set()
    diet_tags: set[str] = set()
    for r in records:
        if r.get("cuisine"):
            cuisines.add(r["cuisine"])
        if r.get("dish_type"):
            dish_types.add(r["dish_type"])
        diet_tags.update(r.get("diet_tags") or [])
    return {"cuisines": cuisines, "dish_types": dish_types, "diet_tags": diet_tags}
