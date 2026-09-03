# ADR-003: Data storage — no DB server; committed artifacts + in-process search index

- **Status:** Accepted
- **Date:** 2026-09-03
- **Related:** SPEC §8.1 (storage is an ADR-level decision), §11; ADR-001 (retrieval), ADR-002 (generation); CORP-09/10/11 (reproducibility); `.env.example` (secret layout)

## Context

The service needs to store and query two kinds of data:

1. **Application data** — the recipe corpus: 49 immutable records (`dataset/corpus/`,
   ~0.3 MB) + the derived enriched layer (`dataset/enriched/`), plus the derived
   embeddings for hybrid retrieval (ADR-001 D3: 49 × 1536 float32 ≈ **0.3 MB**).
   Writes happen only at deploy time (corpus is rebuilt from the committed manifest);
   the request path is **read-only**.
2. **Operational data** — request logs with request ID, latency, corpus version,
   retrieval IDs, model/prompt version (§10). Append-only, single-process traffic
   (take-home scale), no cross-request state.

Constraints that decide this:

- **Reproducibility is graded** (CORP-09/10/11): corpus must be rebuildable from the
  committed script + manifest anywhere. A database as the source of truth would fight
  this — git is the source of truth.
- **Scale is tiny**: 49 records now, growth path to ~1k. Full-text and vector search
  over this is milliseconds in-process.
- **Latency budget** (§11): refusals p95 ≤ 10 s, answers p50 ≤ 20 s — already
  dominated by two LLM calls (~2 s + ~5–15 s measured/estimated). Storage must add
  ~zero.
- **Ops budget is solo-dev**: one PaaS container (Render/Fly), no second managed
  service to provision, back up, or pay for.
- The assignment explicitly lists cache design and storage as ADR-level decisions, and
  requires cost/latency reasoning.

Live research (Gravity Index, 2026-09-03) surveyed the realistic managed options for
this stack: Supabase and Neon (managed Postgres, pgvector), Turbopuffer (serverless
vector-first), MongoDB Atlas (vector search), Render/Fly managed Postgres, Tiger Cloud
(PG + vectors). All are viable products; none is *needed* at this scale — and each adds
a credential, a network hop, and an ops surface the assignment doesn't pay for.

## Decision

### D1. No database server. Git-committed files are the datastore; the API process builds an in-memory index at startup.

- **Corpus + enriched layer**: loaded from committed JSON at boot into Python objects.
  Validated by the existing contract validators (`dataset/validate.py`, enriched
  contract) — fail fast on corruption.
- **Vector store**: embeddings are precomputed by a committed script
  (`scripts/build_index.py`) into `index/embeddings.npz` + `index/meta.json`
  (pageid-ordered rows), committed to the repo. At boot the API loads the `.npz` into
  a numpy matrix; cosine search is one matrix multiply over 49 rows (microseconds).
  Rebuild is deterministic from `corpus/` (same corpus_version in/out).
- **Lexical index**: BM25 (`rank-bm25`) built in memory at boot from the same records
  (~ms). Nothing persisted.
- **Operational logs**: structured JSON to **stdout** — the PaaS collects them. No log
  store at this stage; §10 correlation fields live in each line. This is a documented
  production gap (see Consequences).

### D2. The migration path is written down, not built

The API's retrieval boundary is a thin interface (`Retriever.search(plan) -> list[Record]`).
If the corpus grows past ~1k records or traffic needs persistence/sessions:

| Trigger | Migration |
|---|---|
| Corpus > ~1k records, embeddings > ~10 MB in repo | Postgres + **pgvector** on the same PaaS (Render/Neon/Supabase all serve it; free tiers exist on Supabase/Neon) — one engine for rows + vectors, HNSW index, metadata filtering in SQL |
| Need zero-config serverless vector store only | **Turbopuffer** (serverless, simple Python SDK, no credit card) |
| Need request/session persistence or analytics | Same Postgres as above |

The interface (not the implementation) is the decision — swapping the store then
touches one module and one ADR revision.

### D3. Cache design (explicitly in scope for ADRs)

- **Embedding cache**: query embeddings are the only runtime OpenAI embedding calls;
  identical-query caching is unnecessary at this traffic (embedding ~0.3 s, $0.00002).
  Not built.
- **Response cache**: none — every answer must carry fresh citations, and the golden
  eval requires deterministic behavior. A future LLM response cache keyed by
  `(question_hash, corpus_version, prompt_version)` is the first optimization if cost
  matters (documented, not built).

## Alternatives considered

| Alternative | Why rejected (for now) |
|---|---|
| **Managed Postgres + pgvector** (Supabase / Neon / Render / Tiger) | The right *growth* answer (D2), but at 49 records it adds: a second service + credential + connection management + backup duty, network latency on every request, and a reproducibility story worse than git (DB state ≠ repo state). Cost $0 tiers exist but the ops cost is real. |
| **Turbopuffer** (serverless vector DB) | Great fit for vector-only scale-out; still an extra service + key + hop for 0.3 MB of vectors that fit in RAM. Revisit at D2 trigger. |
| **MongoDB Atlas Vector Search** | Document model fits records nicely, but vector search needs a paid tier (M10); heaviest option for the need. |
| **SQLite file (committed or mounted)** | Closest contender: zero-service, SQL, FTS5. Rejected because vectors would live outside it anyway (no pgvector), so it wouldn't consolidate anything; JSON + numpy is fewer moving parts. Revisit if relational queries over records appear. |
| **Redis / in-memory cache service** | Solves caching we don't have; adds a service. |
| **Chroma/FAISS in-process** | FAISS oversized for 49×1536 (numpy suffices); Chroma brings a client/server dependency for the same in-RAM result. numpy keeps the dependency list at zero for search. |

## Consequences

- **Positive:** deploy = one stateless container; request-path storage latency ≈ 0
  (in-RAM), protecting the §11 budget for the LLM calls that deserve it; zero DB
  credentials (`.env.example` stays one variable: `OPENAI_API_KEY`); reproducibility
  story is exactly the graded one (git + manifest); index rebuild is deterministic and
  testable.
- **Negative / documented production gaps:** no persistent log store (stdout only) —
  production remediation: ship logs to a managed sink (PaaS log drains); no runtime
  writes means any future user-data feature (feedback, sessions) triggers the D2
  Postgres migration; embeddings in-repo couple index freshness to deploys (fine —
  corpus only changes via ingestion commits).
- **Cost:** $0/month for storage at this stage; growth path priced in the D2 table
  (Postgres free tiers → ~$0–7/mo; Turbopuffer usage-based).
- **Invalidation:** any D2 trigger, or if boot-time index build exceeds a few seconds,
  revisits this ADR (spec §12 change-control).
