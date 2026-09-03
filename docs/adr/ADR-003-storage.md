# ADR-003: Data storage — PostgreSQL + pgvector as the single datastore

- **Status:** Accepted (rev. 2 — supersedes the same-day "no DB, in-process index" decision)
- **Date:** 2026-09-03
- **Related:** SPEC §8.1 (storage is an ADR-level decision), §10 (logging), §11; ADR-001 (retrieval), ADR-002 (generation); CORP-09/10/11 (reproducibility); `.env.example` (secret layout)

## Context

The service needs to store and query:

1. **Application data** — the recipe corpus: 49 immutable records
   (`dataset/corpus/`), the derived enriched layer (`dataset/enriched/`), and
   embeddings for hybrid retrieval (ADR-001: `text-embedding-3-small`, 1536-dim,
   49 vectors ≈ 0.3 MB). Writes happen only at deploy/seed time; the request path is
   read-only.
2. **Operational data** — request logs with request ID, endpoint, status, latency,
   corpus version, retrieval IDs, model/prompt version (§10). Append-only.
3. **Future, explicitly planned**: backend tables (users, feedback, sessions), richer
   full-text search, and caching.

An earlier revision of this ADR chose "no DB server — committed files + in-process
BM25/numpy index". That option is cheapest at exactly 49 records, but it was revised:
it hard-codes a second storage migration into the project's future (backend tables and
caching would each trigger one), gives no full-text story beyond BM25, and its "log to
stdout only" answer is a documented production gap. **Postgres + pgvector** is barely
harder to implement now and removes all three future migrations.

Requirements that decide the choice:

- **Hard-constraint filtering is the core of retrieval** (ADR-001 FilterSpec v1,
  SPEC §8/§9): typed requirements (`ingredients CONTAINS salt`, `cuisine EQ ukrainian`,
  `time_minutes LTE 30`) must be applied deterministically, and unknown data must fail
  conservatively.
- Reproducibility is graded (CORP-09/10/11) — the corpus source of truth must stay in
  git regardless of where the runtime store lives.
- Latency budget (§11) is dominated by two LLM calls (~2 s + ~5–15 s); storage must
  add ~zero.
- Solo-dev ops budget: at most one managed service, $0-tier viable.
- Live research (Gravity Index, 2026-09-03) surveyed managed Postgres providers
  (Render, Supabase, Neon, Tiger Cloud) — all serve Postgres + pgvector with free
  tiers (Render's free Postgres tier expires after 30 days; Neon/Supabase free tiers
  are persistent and sufficient for this stage).

## Decision

### D1. PostgreSQL with the `vector` extension is the single datastore

One database, one engine, four jobs:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE recipes (
  pageid         integer PRIMARY KEY,      -- stable ID (AC-20 tie-break)
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
  search_tsv     tsvector GENERATED ALWAYS AS (
                   to_tsvector('english', coalesce(title, '') || ' ' ||
                               coalesce(array_to_string(ingredients, ' '), ''))
                 ) STORED,
  embedding      vector(1536) NOT NULL
);
CREATE INDEX ON recipes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON recipes USING gin (search_tsv);

CREATE TABLE request_logs (           -- §10 correlation fields
  id             bigserial PRIMARY KEY,
  ts             timestamptz NOT NULL DEFAULT now(),
  request_id     uuid,
  endpoint       text,
  status         integer,
  latency_ms     integer,
  corpus_version text,
  retrieval_ids  integer[],
  model          text,
  prompt_version text
);
```

- **Corpus/recipes store** — the tables above; seeded deterministically from the
  committed artifacts (D3).
- **Vector store** — pgvector, `vector(1536)` + HNSW (cosine).
- **Full-text store** — native `tsvector` + GIN; the lexical half of hybrid ranking
  today, and a real FTS feature (ranking, highlighting, websearch syntax) for free
  later — no BM25 library needed.
- **Operational log store** — `request_logs` (stdout logging stays as the PaaS-level
  copy; the table is the queryable record). Caching later reuses the same engine
  (cache table / unlogged tables / advisory locks / LISTEN-NOTIFY), which is the
  realistic "Redis replacement" for a single-service deploy.

### D2. Filtered search: requirements translate to SQL `WHERE` — and Postgres satisfies the requirement, verified against Qdrant's model

The user-level question: *can Postgres filter by metadata during vector search the way
Qdrant can?* Answer, checked against current docs/known behavior:

- **Qdrant** integrates payload filters into the HNSW graph ("filterable HNSW").
- **pgvector** applies `WHERE` during the index walk (post-filtering within the scan);
  with very selective filters an HNSW walk can under-return. pgvector 0.8.0 added
  **iterative index scans** (`hnsw.iterative_scan`) that keep walking until the LIMIT
  is satisfied, closing that gap for large tables.
- **At this scale neither applies**: 49 rows means the planner uses a **sequential
  scan → exact (perfect-recall) search** — `WHERE <hard filters> ORDER BY embedding <=>
  :query LIMIT k` returns *all* matching rows ranked, regardless of filter selectivity.
  Exact filtered search is strictly more correct than ANN-with-filters; the HNSW index
  exists for growth, with `iterative_scan` enabled when the table outgrows exact scans.

Concretely, FilterSpec v1 (ADR-001 D2) translates mechanically to SQL — typed ops map
to typed predicates:

| FilterSpec requirement | SQL predicate |
|---|---|
| `ingredients CONTAINS v` | `EXISTS (SELECT 1 FROM unnest(ingredients) i WHERE i ILIKE '%' \|\| :v \|\| '%')` |
| `cuisine EQ v` | `cuisine = :v` (vocabulary-checked before query) |
| `diet_tags ANY ts` | `diet_tags && :ts::text[]` |
| `diet_tags ALL ts` | `diet_tags @> :ts::text[]` |
| `time_minutes LTE v` | `time_minutes <= :v` |
| `servings GTE v` | `servings >= :v` |
| `title CONTAINS v` | `title ILIKE '%' \|\| :v \|\| '%'` |

Two properties come for free and matter for the contract:

- **SQL three-valued logic gives the conservative unknown handling**: for a record with
  `time_minutes = NULL`, `time_minutes <= 30` evaluates to `NULL` (not true) → the row
  is filtered out. "Unknown ≠ fast" (§4.6) is the database's native behavior, not
  extra code.
- **Filters are pre-filters** (evaluated before ranking on the exact scan) — constraint
  relaxation is structurally impossible; no survivors → refusal per §9.

Hybrid ranking per ADR-001 (RRF k=60, weights 0.6 lexical / 0.4 dense) runs on two
SQL-ordered lists over the filtered set: one `ORDER BY embedding <=> :q`, one
`ORDER BY ts_rank(search_tsv, websearch_to_tsquery(:search_query))` — fused in the
retrieval layer. Exact lists make the fusion deterministic and repeatable (AC-20).

The `Retriever.search(plan)` interface boundary is unchanged: FilterSpec → SQL lives in
one module; the rest of the app never sees SQL.

### D3. Git stays the source of truth; the database is seeded, never hand-edited

CORP-09/10/11 remain intact:

- The committed corpus + manifest are the only source of recipe facts.
- A committed idempotent seeder (`python -m scripts.db_seed`) loads `corpus/` +
  `enriched/` into `recipes`, embedding each record via `text-embedding-3-small`, and
  stamps `corpus_version`.
- **On boot the API checks `corpus_version` in the DB against the committed corpus and
  refuses to serve (503) on mismatch** — a stale index cannot produce answers. This
  turns "DB state can drift from repo state" (the main objection in rev. 1) into a
  fail-fast guarantee.
- Runbook: fresh environment = create DB → run seeder → boot. No hidden state.

### D4. Operations

- **Provider**: managed Postgres + pgvector on a free tier — Neon or Supabase for dev;
  prod on the same provider (or Render) with the prod credentials living only in the
  platform's secret store (`DATABASE_URL`), per the key-layout rules in `.env.example`.
- **Local dev**: Docker (`pgvector/pgvector:pg16`) or the provider's dev branch;
  `DATABASE_URL` in `.env` (git-ignored).
- **Migrations**: plain committed SQL files applied by the seeder/startup (schema above
  is v1); a migration tool is deliberately deferred — schema changes will be rare and
  reviewable.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **No DB — committed files + in-process index** (rev. 1 of this ADR) | Genuinely fine at 49 records (documented honest trade-off), but forces three separate future migrations (backend tables, FTS, cache) and leaves logs as a stdout-only gap. Postgres+pgvector costs ~one extra env var and a seeder — cheaper over the project's life. Kept as the documented fallback if the DB must be dropped. |
| **SQLite + file-based vectors** | Zero-service and close contender for a single process, but no pgvector story (vectors live outside SQL), no networked multi-instance access, weaker ops story for "prod database" ambitions. |
| **Qdrant Cloud / Turbopuffer (dedicated vector DB)** | Filtered search is first-class (Qdrant's filterable HNSW is excellent), but it stores *only* vectors+payload — recipes table, logs, FTS, and future backend tables would still need a second store. A dedicated vector DB earns its keep at millions of vectors / multi-tenant scale (see Invalidation). |
| **MongoDB Atlas Vector Search** | Document model fits records; vector search needs a paid tier (M10) — heaviest option for the need. |
| **Redis** | Great cache, wrong primary store for relational recipe data; its cache role is covered by Postgres tables/unlogged tables at this scale. |
| **Chroma/FAISS in-process** | Same "one job only" problem as Qdrant plus an embedded dependency to operate inside the app. |

## Consequences

- **Positive:** one managed service covers corpus + vectors + FTS + logs + future
  backend tables + caching; filtered retrieval is exact at this scale and degrades
  gracefully (iterative scans) as data grows; conservative NULL semantics come from
  SQL itself; `corpus_version` boot-check turns reproducibility into a runtime
  guarantee; ops surface is one `DATABASE_URL`.
- **Negative / managed costs:** a second stateful dependency to provision (mitigated:
  free tier + committed seed + boot check); embeddings must be recomputed on corpus
  change (minutes, scripted); secrets now include `DATABASE_URL` (documented in
  `.env.example`); HNSW needs `iterative_scan` awareness when filters get selective at
  scale — recorded here.
- **Cost:** $0/month at this stage (Neon/Supabase free tiers; Render free Postgres
  expires after 30 days — fine for CI, not for prod).
- **Invalidation:** if vector corpus exceeds ~1M rows or multi-tenant isolation is
  required, move vectors to a dedicated engine (Qdrant/Turbopuffer) behind the same
  `Retriever` interface; if the deploy target forbids external DBs, revert to rev. 1
  (in-process index) — kept possible by the interface boundary (spec §12).
