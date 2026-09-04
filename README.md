# Recipe Q&A Service

## Status

The backend, Docker Compose workflow, streamed UI and golden evaluation are implemented and verified locally. Public deployment and managed production database remain the final external step.
The root
[`SPEC.md`](SPEC.md) is the canonical entry point, and the normative text is
kept in [`docs/03_SPEC.md`](docs/03_SPEC.md), without a second copy.

Retrieval first applies the QueryPlan's deterministic hard filters to the full corpus, then ranks the remaining records by query embedding and passes up to 15 nearest records to the answer model. This preserves recall for broad questions; the generator decides how many recipes to present and remains evidence-gated.

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
same corpus version. It also builds and serves the TypeScript UI through nginx.

```bash
cp .env.example .env
# Set OPENAI_API_KEY in .env
docker compose up --build
```

The UI is available at `http://localhost:3000`; the API is available at
`http://localhost:8000`; health is checked at `http://localhost:8000/health`.
The UI proxies `/ask`, `/ask/stream`, `/ask/advanced/stream` and `/health` to the API service. The local database is
exposed on port `5433` for inspection, while the API connects to it internally as
`db:5432`.

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

The review deployment runs on Northflank. Public URLs:

- UI: `https://p01--recipe-qa-ui--yjw6rjx4dx4m.code.run`
- API: `https://p01--recipe-qa-service--yjw6rjx4dx4m.code.run`
- API health: `https://p01--recipe-qa-service--yjw6rjx4dx4m.code.run/health`

Northflank project access is the selected container-level verification method:
the reviewer can inspect service status, deployments, logs and metrics in the
`recipe-qa-service` project. The current runtime uses `gpt-5.6-luna` for query planning and
answer generation, plus `text-embedding-3-small` for recipe and query vectors. The
dominant latency is the two LLM calls; the next optimization is request-level metrics
and golden-eval measurement before changing model tiers.

### Easiest low-cost deployment

For a review deployment, use Northflank (or an equivalent Docker PaaS) with one Postgres+pgvector service, one API service built from the root `Dockerfile`, one UI service built from `ui/Dockerfile`, and a one-shot seed job using `python -m scripts.db_seed --apply`. Set `OPENAI_API_KEY` and `DATABASE_URL` as platform secrets, wait for `/health`, then open the UI service URL. Free tiers and database persistence limits change, so confirm the provider's current allowance before choosing it; never put the API key in Git.

For an actually free small demo, use a free Docker web service plus a free Postgres provider that supports `pgvector`; this is usually more manual and may sleep or have storage limits.

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
