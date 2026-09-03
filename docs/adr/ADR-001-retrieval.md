# ADR-001: Retrieval — two-stage query planning, deterministic hard filters, hybrid ranking

- **Status:** Accepted
- **Date:** 2026-09-03
- **Related:** SPEC §4.2, §8.1–8.2, §11; `dataset/PLAN.md` §8 (EDA verdict); AC-20; ADR-002 (generation), ADR-003 (storage/deployment)

## Context

The service answers recipe questions over a fixed corpus of 49 Wikibooks recipes
(`dataset/corpus/`, 15 cuisines, 2 overlapping-dish variant groups). Requirements that
shape retrieval:

- Hard constraints (diet, max time, ingredients) are **deterministic**: filters must be
  applied in code and must never be relaxed (SPEC §8, §9 — "no retrieval results after
  filters" must refuse, not loosen). An LLM may not decide constraints.
- The evidence gate (§8.2) requires source content, not just a retrieval score.
- Time data is honest-but-sparse: 22/49 records carry `time_minutes` (ambiguous values
  are `null` by design, §4.6). A `max_time` filter must treat `null` conservatively.
- The EDA verdict (`dataset/enriched/report.json`, corpus version `45af1c982923952a`):
  Rating coverage is 2% → **no usable selection signal → the stable-ID baseline
  (§4.2) remains in force** for tie-breaking, per RET-08 / AC-20.
- Latency targets (§11): refusals p95 ≤ 10 s; answers p50 ≤ 20 s, p95 ≤ 40 s.
- The assignment requires the retrieval method, threshold/calibration and filter order
  to be documented in an ADR (§8.1 "Implementation decisions for ADRs").

The pipeline shape (user-driven design decision):

1. User question → **fast extraction call** (`gpt-5.6-luna`, `reasoning_effort="none"`,
   Structured Outputs) → `QueryPlan { search_query, diet_tags, max_time_minutes,
   ingredients_any, category_hint? }`.
2. **Deterministic search** over the corpus using the QueryPlan: hard filters first,
   then hybrid ranking of survivors.
3. Surviving records (evidence-gated) → **generation call** (`gpt-5.6-luna`,
   `reasoning_effort="medium"`, see ADR-002).

## Decision

### D1. Two-stage LLM usage: plan with `none`, answer with `medium`

One model (`gpt-5.6-luna`) served at two reasoning tiers, both verified against the
live endpoint on 2026-09-03:

| Call | Effort | Structured output | Measured latency | Purpose |
|---|---|---|---|---|
| Query planning | `none` | strict JSON schema | ~1.9 s | normalize question → filters + search string |
| Answer generation | `medium` | strict JSON schema | budget ≤ ~15 s | grounded answer / refusal + citations |

Rationale: constraint extraction is a classification/normalization task — reasoning
adds latency and cost without accuracy gains. Answer generation needs the reasoning to
check evidence-to-claim support and citation correctness. One model (not two different
models) keeps prompt/tooling knowledge, evaluation surface and cost model simple.

### D2. Filters are deterministic and applied before ranking

Filter order (SPEC §8.1 requires documenting it):

1. **Domain/pre_filter** — non-recipe questions are refused before retrieval.
2. **Hard filters** from the QueryPlan, all in code:
   - `diet_tags`: record `diet_tags` (enriched layer) must include every requested tag;
     a record with `null` diet data only survives if no diet constraint was given
     (conservative).
   - `max_time_minutes`: record `time_minutes` must be ≤ the constraint; records with
     `time_minutes = null` are **excluded** when a time constraint is present (unknown
     ≠ fast; §4.6 forbids guessing).
   - `ingredients_any`: at least one requested ingredient appears in the record's
     `ingredients_normalized` list (string containment after normalization; synonym map
     versioned in code).
3. **Ranking** of survivors only (see D3).
4. **Selection policy** for a single winning record when the question is about one
   dish: relevance order, then **lowest stable `pageid`** tie-break (baseline §4.2,
   AC-20) — deterministic and repeatable, test-enforced.
5. **Evidence gate** (§8.2): a candidate is citable only if the claimed fact exists in
   its `source_text` (verbatim substring / parsed field). Retrieval score alone is
   never evidence.

The LLM never sees filter authority: if it emits different filters than the schema
validated, code wins. Query-plan JSON that fails schema validation → refuse with
`validation_error` (400) before any retrieval.

### D3. Hybrid ranking: BM25 + embeddings, fused

Corpus is 49 records — but the method must survive growth (spec targets a service, not
a demo) and must handle paraphrase ("eggplant dish" → `Baingan Bartha`). Decision:

- **Lexical**: BM25 (rank-bm25) over `title + ingredients_normalized + dish_type +
  cuisine` (the enriched fields; `source_text` is too noisy as a primary field).
- **Dense**: `text-embedding-3-small` (1536-dim, verified available on our key) over
  the same logical text; one embedding per record (recipe-level, not chunked — records
  average ~3 KB of source text; chunking adds nothing at this size and breaks the
  citation-per-record model).
- **Fusion**: weighted Reciprocal Rank Fusion (k=60), weights 0.6 lexical / 0.4 dense,
  tuned on a small labeled set from the golden cases; threshold: minimum fusion score
  for "relevant" is calibrated and recorded here after golden-eval tuning (placeholder
  resolved in Phase 4; initial gate = any nonzero BM25 hit OR cosine ≥ 0.30).
- **Cold-start**: embeddings for query come from the same model; index is rebuilt from
  the committed corpus at deploy startup (49 records → <1 s), so no vector store is
  required for correctness at this scale (storage decision in ADR-003).

### D4. Refusal paths preserved

- No candidates after hard filters → `out_of_scope` refusal (200, §9) — never relax
  filters.
- Candidates exist but evidence gate fails → `not_found` refusal.
- The off-topic/out-of-domain pre-check happens **before** the extraction call only as
  a cheap lexical/keyword guard; the primary domain gate is the generation stage's
  refusal decision (ADR-002).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Single LLM call decides everything (filters + answer) | Violates determinism of hard constraints (§8); untestable filter order; AC-20 repeatability impossible |
| LLM reads full corpus and picks (no retrieval) | 49 records ≈ 150 KB prompt — cost and latency explode; no citations stability; doesn't scale |
| Pure lexical (BM25 only) | Misses paraphrase ("aubergine" vs "eggplant") without a large synonym table; acceptable fallback if embeddings degrade, kept as a feature flag |
| Pure dense | BM25 is stronger for exact ingredient/time tokens; dense alone risks recall loss on rare ingredient names |
| Cross-encoder reranker | Adds a model + latency; no need at 49-record candidate pools |
| Third-party embedding/rerank services (Cohere, Voyage) | Extra vendor, key, cost; OpenAI embeddings already available on the same key (verified) |

## Consequences

- **Positive:** deterministic, testable filter pipeline; two-tier latency fits §11
  (measured extraction ~1.9 s; answer budget ~15 s); one model + one embedding model =
  simple cost model; stable-ID tie-break keeps AC-20 test-enforceable.
- **Negative:** LLM extraction errors propagate into filters (mitigation: schema
  validation + conservative null-handling; golden eval measures extraction accuracy);
  two embeddings of query per request add ~0.3 s and marginal cost.
- **Invalidation:** if corpus grows >1k records, or golden eval shows fusion ranking
  worse than pure lexical, revisit weights/method here (spec §12 change-control).
