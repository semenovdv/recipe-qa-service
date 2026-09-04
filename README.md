# Recipe Q&A Service

## Status

The core backend and Docker Compose workflow are implemented and verified locally.
A public deployment, UI, CI/CD, and managed production database are still pending.
The root
[`SPEC.md`](SPEC.md) is the canonical entry point, and the normative text is
kept in [`docs/03_SPEC.md`](docs/03_SPEC.md), without a second copy.

Until the corpus EDA is done, a baseline of the `lowest stable recipe ID` is fixed
for equally relevant recipes after filtering. If EDA finds a better and reliable
comparable signal — for example, popularity, view count, or user likes — it may
replace the baseline. A signal cannot violate hard constraints; a strategy change
is recorded in an ADR and in deterministic tests. If no reliable signal exists,
the stable-ID baseline remains.

## Core scope

The mandatory MVP includes:

- a reproducible corpus of 40–60 recipes from the Wikibooks Cookbook;
- grounded `POST /ask` with a machine-readable response, citations, and refusals;
- a one-page TypeScript UI with the standard JSON mode;
- deterministic tests, a 12–15-question golden eval, Docker, and deployment.

Additional requirements, including streaming inline citations, are moved to
[`docs/03_SPEC_APPENDIX.md`](docs/03_SPEC_APPENDIX.md). They are implemented
only after the core, do not replace the mandatory API, UI, tests, eval, or
deployment, and use the same retrieval/grounding pipeline.

## Scope cuts

Within the 6–8 hour limit, authentication, accounts, multi-turn chat, saved
history, voice/image assistance, nutrition calculations, shopping lists, recipe
generation, and UI polish are intentionally excluded. These cuts reduce the risk
of leaving the core path unfinished. To bring any of these features back,
separate requirements, acceptance cases, tests, and a cost/latency estimate are
needed first.

## Run locally with Docker

Docker Compose starts PostgreSQL 16 with pgvector, waits for the database healthcheck,
runs the idempotent corpus seed, and then starts the API. The first clean start calls
the embeddings API for the 49 corpus records; later starts reuse embeddings for the
same corpus version.

```bash
cp .env.example .env
# Set OPENAI_API_KEY in .env
docker compose up --build
```

The API is available at `http://localhost:8000`; health is checked at
`http://localhost:8000/health`. The local database is exposed on port `5433` for
inspection, while the API connects to it internally as `db:5432`.

To stop the services while keeping the database volume:

```bash
docker compose down
```

The seed is safe to run repeatedly: it applies the schema, upserts only missing or
changed corpus records, removes stale records, and verifies the final count and
`corpus_version`.

## Long-chat policy for a future extension

The MVP is not a chat and stores no history. If multi-turn chat appears later,
the model context needs old history summarized, but the user's text and the full
transcript must be preserved and shown to the user in full. A summary must not
replace the original text in the UI or become the only audit trail.

## Quality, security and AI-assisted checks

Before merge, CI must run the formatter/linter, type checks, unit/contract tests,
dependency and secret scans, plus container/SAST checks where applicable.
Agent-assisted review (for example, CodeRabbit or an internal agent) is used as
an additional quality and vulnerability check: its findings are verified by a
human and are not the sole security gate. The final README must state the tools
actually chosen and the results of their runs.

## Deployment, cost and latency

The local Docker workflow is verified, but a public provider and production URLs have
not been selected yet. The current runtime uses `gpt-5.6-luna` for query planning and
answer generation, plus `text-embedding-3-small` for recipe and query vectors. The
dominant latency is the two LLM calls; the next optimization is request-level metrics
and golden-eval measurement before changing model tiers.

Production still requires a managed PostgreSQL+pgvector instance, platform-injected
`DATABASE_URL` and `OPENAI_API_KEY`, a public API/UI deployment, backups, and CI/CD.
No production credentials are stored in the repository. The API logs structured
request ID, status, latency, corpus version, model, prompt version, and refusal state
to container stdout so a bad answer can be traced through its plan, retrieval IDs, and
provider stages; persistent `request_logs` storage remains to be wired.

## AI usage notes

The repository must keep the instructions/prompts used and a short note on what
was accepted from the agent and what was rewritten independently. Responsibility
for architectural decisions and code remains with the developer.
