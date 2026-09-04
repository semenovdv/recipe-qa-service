-- Recipe Q&A Service — database schema (ADR-003 rev.2)
-- Applied by scripts/db_seed.py (idempotent). Postgres 16 + pgvector.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Corpus: seeded deterministically from dataset/corpus + dataset/enriched.
-- The database is NEVER hand-edited; git is the source of truth (ADR-003 D3).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recipes (
    pageid         integer PRIMARY KEY,          -- stable ID (AC-20 tie-break)
    title          text NOT NULL,
    source_url     text NOT NULL,
    corpus_version text NOT NULL,
    time_minutes   integer,
    servings       integer,
    cuisine        text,
    dish_type      text,
    diet_tags      text[],
    ingredients    text[],
    source_text    text NOT NULL,
    -- Composed by the seeder (title + ingredients); kept as a plain column
    -- because array_to_string is only STABLE and cannot appear in a
    -- generated-column expression.
    search_text    text NOT NULL,
    search_tsv     tsvector GENERATED ALWAYS AS (
        to_tsvector('english', search_text)
    ) STORED,
    embedding      vector(1536) NOT NULL
);

-- Vector search (cosine). At 49 rows the planner uses a sequential scan
-- (exact, perfect recall with hard filters); HNSW serves growth.
CREATE INDEX IF NOT EXISTS recipes_embedding_hnsw
    ON recipes USING hnsw (embedding vector_cosine_ops);

-- Full-text search: lexical half of hybrid ranking (ADR-001 D3), and a real
-- FTS feature later (ranking, highlighting, websearch syntax).
CREATE INDEX IF NOT EXISTS recipes_search_tsv_gin
    ON recipes USING gin (search_tsv);

-- Filter-supporting indexes for growth (no-ops at 49 rows, cheap to keep):
CREATE INDEX IF NOT EXISTS recipes_cuisine_idx   ON recipes (cuisine);
CREATE INDEX IF NOT EXISTS recipes_dish_type_idx ON recipes (dish_type);
CREATE INDEX IF NOT EXISTS recipes_time_idx      ON recipes (time_minutes);

-- ---------------------------------------------------------------------------
-- Operational logs (SPEC §10): request ID, endpoint, status, latency,
-- corpus version, retrieval IDs, model/prompt version. Append-only.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS request_logs (
    id             bigserial PRIMARY KEY,
    ts             timestamptz NOT NULL DEFAULT now(),
    request_id     text,
    endpoint       text,
    status         integer,
    latency_ms     integer,
    corpus_version text,
    retrieval_ids  integer[],
    model          text,
    prompt_version text,
    refused        boolean,
    refusal_reason text,
    error_class    text
);

ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS refused boolean;
ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS refusal_reason text;
ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS error_class text;

CREATE INDEX IF NOT EXISTS request_logs_ts_idx ON request_logs (ts DESC);
