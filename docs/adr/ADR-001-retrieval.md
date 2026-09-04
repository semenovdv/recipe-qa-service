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
   Structured Outputs) → `QueryPlan`: an LLM-classified `intent` plus a **typed
   requirement list** in a fixed predicate format (FilterSpec v1, defined in D2) and
   a free-text ranking query. Example:
   *"quick vegetarian dinner under 30 minutes that uses eggplant"* →
   requirements `[diet_tags ANY [vegetarian], time_minutes LTE 30,
   ingredients CONTAINS eggplant]` + `search_query "quick vegetarian eggplant dinner"`.
2. **Deterministic search** over the corpus by applying the extracted requirements as
   hard filters (e.g. `ingredients CONTAINS salt`, `cuisine EQ ukrainian`,
   `time_minutes LTE 30`), then hybrid ranking of the survivors.
3. Surviving records (evidence-gated) → **generation call** (`gpt-5.6-luna`,
   `reasoning_effort="medium"`, see ADR-002).

## Decision

### D1. Two-stage LLM usage: plan with `none`, answer with `medium`

One model (`gpt-5.6-luna`) served at two reasoning tiers, both verified against the
live endpoint on 2026-09-03:

| Call | Effort | Structured output | Measured latency | Purpose |
|---|---|---|---|---|
| Query planning | `none` | strict JSON schema | ~1.9 s | classify intent and translate question → typed requirements + ranking query |
| Answer generation | `medium` | strict JSON schema | budget ≤ ~15 s | grounded answer / refusal + citations |

Rationale: constraint extraction is a classification/normalization task — reasoning
adds latency and cost without accuracy gains. Answer generation needs the reasoning to
check evidence-to-claim support and citation correctness. One model (not two different
models) keeps prompt/tooling knowledge, evaluation surface and cost model simple.

### D2. Requirements are extracted in a typed filter format, then applied as hard filters

The extraction call must emit requirements in a fixed predicate format (**FilterSpec
v1**). Natural-language fragments map to typed predicates: *"salt in ingredients"* →
`{field: ingredients, op: contains, value: salt}`; *"cuisine == ukrainian"* →
`{field: cuisine, op: eq, value: ukrainian}`.

```json
{
  "intent": "recipe",
  "intent_reason": "the user requests a quick vegetarian recipe",
  "search_query": "quick vegetarian eggplant dinner",
  "requirements": [
    { "field": "diet_tags",    "op": "any",      "value": ["vegetarian"] },
    { "field": "time_minutes", "op": "lte",      "value": 30 },
    { "field": "ingredients",  "op": "contains", "value": "eggplant" }
  ]
}
```

Whitelisted fields — each maps to one concrete record field (enriched layer preferred,
corpus fallback):

| Field | Record source | Allowed ops | Matching semantics |
|---|---|---|---|
| `ingredients` | `ingredients_normalized` | `contains` | value appears in the normalized ingredient list (containment after normalization; synonym map versioned in code) |
| `cuisine` | `cuisine` (enriched) | `eq` | exact match against the corpus cuisine vocabulary after lowercasing/trimming |
| `dish_type` | `dish_type` (enriched) | `eq` | same as cuisine, against the dish-type vocabulary |
| `diet_tags` | `diet_tags` (enriched) | `any` / `all` | set membership over tags |
| `time_minutes` | `time_minutes` | `lte` / `gte` | numeric comparison |
| `servings` | `servings` | `lte` / `gte` | numeric comparison |
| `title` | `title` | `contains` | case-insensitive substring |

Semantics:

- Requirements are **AND-combined**; each is a hard constraint. Top-level OR is
  deliberately not supported in v1 — it keeps refusals honest and filters testable;
  questions that would need OR are answered from ranking alone, without a hard
  constraint.
- Unknown data is conservative: a record with `time_minutes = null` fails any
  `lte/gte` time requirement (unknown ≠ fast, §4.6); empty `diet_tags` fails any
  `any/all` diet requirement.
- Categorical values normalize against controlled vocabularies derived from the corpus
  (e.g. cuisine values from the enriched layer). A value outside the vocabulary matches
  nothing → empty candidate set → refusal (§9: refuse rather than relax — never
  fuzzy-match a hard constraint).
- `search_query` carries **no filter authority**; it is only the ranking input (D3).
  The LLM classifies intent and translates recipe constraints into the typed format;
  code evaluates every recipe requirement.

Filter order (SPEC §8.1 requires documenting it):

1. **LLM intent gate** — the extraction call classifies intent; safety and
   out-of-domain plans are refused before embeddings and retrieval.
2. **Requirement application** — all recipe requirements are evaluated in code, per record.
3. **Ranking** of survivors only (see D3).
4. **Selection policy** for a single winning record when the question is about one
   dish: relevance order, then **lowest stable `pageid`** tie-break (baseline §4.2,
   AC-20) — deterministic and repeatable, test-enforced.
5. **Evidence gate** (§8.2): a candidate is citable only if the claimed fact exists in
   its `source_text` (verbatim substring / parsed field). Retrieval score alone is
   never evidence.

Validation and failure handling:

- `field`/`op` outside the whitelist, or a wrongly-typed value, is impossible by the
  response JSON schema. A *semantically* invalid value (unknown cuisine, non-numeric
  time) triggers **one extraction retry** with the validator error appended; if it
  still fails, the request is refused with `error` (subreason `query_plan_invalid`).
  Requirements are never silently dropped — dropping one would relax a hard constraint
  (§9). HTTP 400 `validation_error` stays reserved for malformed user input (empty /
  oversized question), not for extraction failures.
### D3. Hybrid ranking: BM25 + embeddings, fused

Corpus is 49 records — but the method must survive growth (spec targets a service, not
a demo) and must handle paraphrase ("eggplant dish" → `Baingan Bartha`). Decision:

- **Lexical**: BM25 (rank-bm25) over `title + ingredients_normalized + dish_type +
  cuisine` (the enriched fields; `source_text` is too noisy as a primary field).
- **Dense**: `text-embedding-3-small` (1536-dim, verified available on our key) over
  the same logical text; one embedding per record (recipe-level, not chunked — records
  average ~3 KB of source text; chunking adds nothing at this size and breaks the
  citation-per-record model).
- **Fusion**: weighted Reciprocal Rank Fusion (k=60), weights 0.6 lexical / 0.4 dense.
  The initial relevance gate is a positive FTS rank or cosine similarity ≥ 0.30
  (cosine distance ≤ 0.70), implemented in `app/retrieve.py` and subject to
  calibration against the golden eval.
- **Cold-start**: embeddings for query come from the same model; the served corpus is
  a committed, versioned artifact loaded into Postgres+pgvector by a deterministic
  seeder with a boot-time `corpus_version` check (storage decision in ADR-003).

### D4. Refusal paths preserved

- No candidates after hard filters → `out_of_corpus` refusal (200, §9) — never relax
  filters.
- Candidates exist but evidence gate fails → `out_of_corpus` refusal.
- The LLM intent classification happens inside extraction. Safety and out-of-domain
  plans are returned **before** embedding, retrieval and generation; no regex or
  keyword allow/deny list is used for this boundary.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Single LLM call decides everything (filters + answer) | Violates determinism of hard constraints (§8); untestable filter order; AC-20 repeatability impossible |
| Free-form filter JSON without a field/op whitelist | The model could invent filter semantics per request; untestable, unverifiable, and constraint relaxation becomes invisible |
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
