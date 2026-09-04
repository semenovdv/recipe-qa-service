# ADR-002: Generation and refusal — one Luna model, two reasoning tiers

- **Status:** Accepted
- **Date:** 2026-09-03
- **Related:** SPEC §4.1/§4.6, §7.1, §8.2, §11–12; ADR-001; `docs/03_SPEC_APPENDIX.md` (citation markers)

## Context

The generation stage receives the QueryPlan (ADR-001), the filtered/ranked candidate
records (already evidence-gated per §8.2) and must produce either a grounded answer
with citations or a refusal — under these contract constraints:

- Public `refusal_reason` is exactly 3 values: `out_of_corpus`, `out_of_domain`,
  `safety`
  (§4.1/§7.1). Internal `refusal_subreason` taxonomy stays off the API.
- `answer` is a non-empty string (assumption §4.12).
- Citations use verbatim-evidence markers `⟦<pageid>⟧` (appendix §2); at least one
  valid citation per non-refused answer (AC-04); never a model-invented URL (AC-04).
- Missing/ambiguous facts are never guessed (§4.6) — this applies to the generator,
  not just ingestion.
- Latency: answers p50 ≤ 20 s / p95 ≤ 40 s (§11).
- Prompt, model name/version, corpus version and retrieval IDs must be logged (§10).

## Decision

### D1. One model, two reasoning tiers

`gpt-5.6-luna` is the only generation model (verified available on our API key):

- **Query planning** call at `reasoning_effort="none"` + Structured Outputs — measured
  ~1.9 s end-to-end (ADR-001 D1).
- **Answer generation** call at `reasoning_effort="medium"` + Structured Outputs.
  Reasoning is needed here to verify claim-to-evidence support and pick correct
  citations; `none` is too weak for faithful citing, `high` is too slow for the §11
  budget (initial estimate; remeasured in Phase 4 benchmarking).

### D2. Structured output schema for generation

The response is a single strict-schema object:

```json
{
  "kind": "answer" | "refusal",
  "answer": "string (non-empty; friendly refusal text when kind=refusal)",
  "refusal_reason": "out_of_corpus | out_of_domain | safety",
  "refusal_subreason": "string (internal, may be empty)",
  "citations": [ { "pageid": 12345, "quote": "verbatim source substring" } ]
}
```

Code-side enforcement (mirrors the enrichment guards that already proved themselves):

- `kind="answer"` with zero valid citations → retried once, then returned as an
  operational HTTP 503 if evidence still fails; the second model never creates
  a business refusal.
- Every citation's `quote` must be a verbatim substring of that pageid's gated
  `source_text`; otherwise the citation is dropped; answer with no surviving
  citations → `out_of_corpus` refusal.
- `refusal_reason` outside the 3-value enum is impossible by schema; the subreason is
  logged but never returned publicly.
- Empty `answer` string → schema violation at generation time → one bounded retry,
  then an HTTP 503 problem (this is an infrastructure failure, honestly reported).

### D3. Prompt contract (versioned)

- System prompt states: answer only from provided records; use one `⟦pageid⟧`
  marker per recipe immediately after the last supported passage for that recipe;
  if records do not support an answer, refuse with the matching reason; never
  output URLs; never guess missing fields (time/servings).
- The prompt is versioned by `PROMPT_VERSION` constants in
  `app/extract.py` and `app/generate.py`, and the versions are logged with
  each request (§10).
- Input per request: up to 15 gated records with title, ingredients, time/servings,
  diet tags and `source_text` (the corpus is small enough for full records).

### D4. Refusal mapping

| Situation | `refusal_reason` | Notes |
|---|---|---|
| Non-recipe / off-domain question | `out_of_domain` | LLM-classified intent in QueryPlan; no retrieval or generation |
| Safety-sensitive question | `safety` | LLM-classified intent in QueryPlan; no retrieval or generation |
| Recipe-domain but no candidate passes hard filters | `out_of_corpus` | Refuse rather than relax constraints |
| Candidates exist but evidence/citations fail | HTTP `503` | Evidence gate fails closed rather than letting the second model create a refusal |
| Extraction/schema/infra failure, retries exhausted | HTTP 503 problem | Operational failure is never a business refusal |

Safety-refusal questions (§4.x safety precedence) map to `safety` and never reach
retrieval or generation.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Two different models (small extractor + big generator) | Two vendors/configs to test and monitor; Luna covers both tiers with one integration; revisit if quality gaps appear |
| Free-text generation parsed after the fact | Citation/evidence integrity requires schema-constrained output; post-hoc parsing is exactly the failure mode §8.2 forbids |
| `reasoning_effort="high"` for generation | Better citation fidelity in theory, but risks the p50 ≤ 20 s target; medium measured sufficient in smoke tests; escalate only if golden eval shows citation errors |
| Streaming generation (appendix bonus) | Quarantined as bonus; structured outputs + streaming conflict; decision deferred, does not block core |

## Consequences

- **Positive:** single-model ops; machine-checkable citations (verbatim quotes) make
  AC-04 test-enforceable; refusal contract enforced by schema, not prose; prompt
  versioning satisfies §10 logging.
- **Negative:** structured outputs slightly constrain phrasing quality; verbatim-quote
  citations make the model sometimes over-quote (acceptable); medium reasoning adds
  ~5–10 s vs none — still within budget, verified in benchmarking phase.
- **Invalidation:** if golden eval shows >5 % citation errors or p95 latency breaches
  §11, revisit tier choice/schema here (spec §12).
