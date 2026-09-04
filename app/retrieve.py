"""Retriever — QueryPlan → filtered, hybrid-ranked records (ADR-001 D3,
ADR-003 D2).

Hard filters translate mechanically to SQL WHERE predicates (named
parameters only — no string interpolation of values). Ranking is hybrid:
one vector-ordered list (``embedding <=> :q``) and one FTS-ordered list
(``ts_rank`` over the generated ``search_tsv``), fused with weighted
Reciprocal Rank Fusion in Python. At 49 rows Postgres runs an exact scan,
so both lists are complete and the fusion is deterministic (AC-20).

Connection handling is intentionally tiny: the retriever opens a
connection per search (psycopg pools can come later; request volume here
does not justify one).
"""
from __future__ import annotations

import re
from typing import Any

from app.query_plan import QueryPlan

DENSE_DISTANCE_MAX = 0.70  # cosine similarity >= 0.30; ADR-001 initial gate

# Corpus-derived vocabularies for FilterSpec normalization (SQL side).
VOCAB_QUERY = """
SELECT 'cuisines' AS vocab, array_agg(DISTINCT cuisine) AS vals FROM recipes WHERE cuisine IS NOT NULL
UNION ALL
SELECT 'dish_types', array_agg(DISTINCT dish_type) FROM recipes WHERE dish_type IS NOT NULL
UNION ALL
SELECT 'diet_tags', array_agg(DISTINCT t) FROM recipes, unnest(diet_tags) AS t
"""

# FilterSpec (field, op) -> SQL predicate template with a named parameter.
_WHERE_TEMPLATES: dict[tuple[str, str], str] = {
    ("ingredients", "contains"): "EXISTS (SELECT 1 FROM unnest(ingredients) ing "
                                 "WHERE ing ILIKE %(req_{i})s)",
    ("ingredients", "not_contains"): "NOT EXISTS (SELECT 1 FROM unnest(ingredients) ing "
                                      "WHERE ing ILIKE %(req_{i})s)",
    ("cuisine", "eq"): "cuisine = %(req_{i})s",
    ("dish_type", "eq"): "dish_type = %(req_{i})s",
    ("diet_tags", "any"): "diet_tags && %(req_{i})s::text[]",
    ("diet_tags", "all"): "diet_tags @> %(req_{i})s::text[]",
    ("time_minutes", "lte"): "time_minutes <= %(req_{i})s",
    ("time_minutes", "gte"): "time_minutes >= %(req_{i})s",
    ("servings", "lte"): "servings <= %(req_{i})s",
    ("servings", "gte"): "servings >= %(req_{i})s",
    ("title", "contains"): "title ILIKE %(req_{i})s",
}

_PARAM_CASTS = {
    "diet_tags": "::text[]",
}


class RetrievalError(Exception):
    """The retriever could not produce results (infrastructure)."""


def plan_to_where(plan: QueryPlan) -> tuple[str, dict[str, Any]]:
    """Translate requirements to a WHERE fragment + named params (AND)."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for i, req in enumerate(plan.requirements):
        template = _WHERE_TEMPLATES.get((req.field, req.op))
        if template is None:
            raise RetrievalError(f"no SQL mapping for {req.field} {req.op}")
        cast = _PARAM_CASTS.get(req.field, "")
        clauses.append(template.replace("%(req_{i})s", f"%(req_{i})s{cast}"))
        value = req.value
        if isinstance(value, list):
            value = list(value)
        elif isinstance(value, str):
            if req.op in {"contains", "not_contains"}:
                value = f"%{value}%"
        params[f"req_{i}"] = value
    if not clauses:
        return "TRUE", {}
    return " AND ".join(clauses), params


def build_search_sql(plan: QueryPlan, embed_query: bool) -> str:
    """The hybrid search query: hard filters, then two ranked lists fused
    with weighted RRF (0.6 lexical / 0.4 dense)."""
    where, _ = plan_to_where(plan)
    vec_rank = (
        "ROW_NUMBER() OVER (ORDER BY embedding <=> %(query_vec)s::vector)"
        if embed_query else "NULL"
    )
    dense_distance = (
        "embedding <=> %(query_vec)s::vector" if embed_query else "NULL::float"
    )
    sql = f"""
    WITH filtered AS (
        SELECT pageid, title, source_url, time_minutes, servings,
               cuisine, dish_type, diet_tags, ingredients, source_text,
               embedding,
               {dense_distance} AS dense_distance,
               ts_rank(search_tsv, websearch_to_tsquery('english', %(search_query)s))
                   AS fts_rank
        FROM recipes
        WHERE {where}
    ),
    ranked AS (
        SELECT filtered.*,
            ROW_NUMBER() OVER (ORDER BY fts_rank DESC, pageid ASC) AS lex_rank,
            {vec_rank} AS vec_rank
        FROM filtered
    )
    SELECT pageid, title, source_url, time_minutes, servings,
           cuisine, dish_type, diet_tags, ingredients, source_text,
           fts_rank, dense_distance,
           COALESCE(
               0.6 / (60 + lex_rank) + 0.4 / (60 + vec_rank),
               1.0 / (60 + lex_rank)
           ) AS rrf_score
    FROM ranked
    WHERE fts_rank > 0 OR dense_distance <= {DENSE_DISTANCE_MAX}
    ORDER BY rrf_score DESC, pageid ASC
    LIMIT %(limit)s
    """
    return sql


def relevant_records(records: list[dict]) -> list[dict]:
    """Keep only records that pass the documented relevance gate."""
    return [
        record for record in records
        if (record.get("fts_rank") or 0) > 0
        or (
            record.get("dense_distance") is not None
            and record["dense_distance"] <= DENSE_DISTANCE_MAX
        )
    ]


_COMPARISON_RE = re.compile(
    r"\b(?:compare|comparison|difference|differences|versus|vs\.?|alternatives)\b",
    re.IGNORECASE,
)


def is_comparison_question(question: str) -> bool:
    return bool(_COMPARISON_RE.search(question))


def select_for_answer(question: str, records: list[dict]) -> list[dict]:
    """Apply the stable single-recipe policy after relevance filtering."""
    if is_comparison_question(question):
        return records
    if not records:
        return []
    return [min(records, key=lambda record: record["pageid"])]


def plan_to_params(
    plan: QueryPlan,
    where_params: dict[str, Any],
    embed_query: bool,
    limit: int = 8,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(where_params)
    params["search_query"] = plan.search_query
    params["limit"] = limit
    if embed_query:
        params["query_vec"] = None  # replaced by the caller with the embedding
    return params


# ---------------------------------------------------------------------------
# Live execution
# ---------------------------------------------------------------------------

def load_vocabularies(conn) -> dict[str, set[str]]:
    """Corpus-derived vocabularies for FilterSpec normalization (SQL side)."""
    with conn.cursor() as cur:
        cur.execute(VOCAB_QUERY)
        out: dict[str, set[str]] = {}
        for vocab, vals in cur.fetchall():
            out[vocab] = set(vals or [])
        return out


def load_corpus_version(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT min(corpus_version) FROM recipes")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def search(
    plan: QueryPlan,
    query_embedding: list[float] | None,
    database_url: str,
    limit: int = 8,
) -> list[dict]:
    """Execute the hybrid search; returns plain record dicts."""
    import psycopg
    from psycopg.rows import dict_row

    embed_query = query_embedding is not None
    sql = build_search_sql(plan, embed_query=embed_query)
    _, where_params = plan_to_where(plan)
    params = plan_to_params(plan, where_params, embed_query=embed_query, limit=limit)
    if embed_query:
        params["query_vec"] = query_embedding

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 — single honest boundary
        raise RetrievalError(f"search failed: {exc}") from exc


def check_corpus_version(committed_version: str, database_url: str) -> str | None:
    """Boot-time guard (ADR-003 D3): the DB must match the committed corpus."""
    import psycopg

    try:
        with psycopg.connect(database_url) as conn:
            return load_corpus_version(conn)
    except Exception as exc:  # noqa: BLE001
        raise RetrievalError(f"corpus version check failed: {exc}") from exc
