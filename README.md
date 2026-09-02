# Recipe Q&A Service

## Status

The repository is at the specification/planning stage. The service implementation,
public URLs, deployment provider, selected model, and measured cost/latency will be
recorded after the core implementation is complete. The root
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

These values are not yet defined because implementation and deployment have not
been selected. The final README must state the provider and the reason for the
choice, the public UI/API URLs, container-level access, the commands for local
and clean deployment, the selected models, the cost of one question and of 1,000
questions, latency, the current bottleneck, and the next optimization.

## AI usage notes

The repository must keep the instructions/prompts used and a short note on what
was accepted from the agent and what was rewritten independently. Responsibility
for architectural decisions and code remains with the developer.
