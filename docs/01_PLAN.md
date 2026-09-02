# Recipe Q&A Service — Work Plan

Core principle:

> First understand and formalize the requirements → then design the solution →
> then implement → then verify → then deploy → then run the final audit.

## Phase 0 — Requirements + acceptance — **60–90 min**

1. Read the assignment carefully.
2. Extract requirements.
3. Write `SPEC.md`.
  1. Define the acceptance checklist.
  2. Record assumptions.
4. Create a traceable acceptance checklist mapping each assignment requirement to
a verification method (test, eval, manual check, or deployment check).

Fix down:

- answerable / out-of-corpus / out-of-domain;
- constraints: time, diet, ingredients;
- allergy/safety policy;
- conflicting recipes;
- empty/invalid questions;
- API schema;
- latency and cost targets.

Additionally fix down:

- the full JSON response schema as a machine-readable schema;
- what evidence is sufficient to consider a question answerable;
- assumptions for any ambiguous assignment requirements.


### Phase 1 — Architecture + corpus — **45–60 min**

1. Choose the stack.
2. Write 2–3 ADRs.
3. Implement reproducible Wikibooks ingestion.
4. Build the 40–60 recipe corpus.
5. Run EDA on the corpus to check whether a reliable selection signal exists.
6. Verify corpus variety.

ADR examples:

- **ADR-001:** Retrieval + constraints + post-EDA recipe selection signal
- **ADR-002:** Answer generation + grounding/refusal
- **ADR-003:** Deployment + observability
- ADR-004: LLM provider choice
- ADR-005: vector store choice

Each ADR must contain:

- alternatives examined;
- decision criteria;
- trade-offs;
- real cost and latency numbers where possible;
- conditions that would invalidate the decision.

Do not add a separate design doc without need. Architectural decisions must be
reflected in `SPEC.md` and the ADRs.

**Do not do manual data preparation that cannot be reproduced.**

---


## Phase 2 — First vertical slice — **60–90 min**

Get a working path as early as possible:

```
question
  ↓
retrieval
  ↓
relevant recipes
  ↓
LLM
  ↓
structured JSON
  ↓
POST /ask
```

Milestone:

> One question → correct grounded answer → citation → valid JSON.

Define and implement `/ask` + `/health` right away.

Maintain small, meaningful commits throughout the project.

**Test before implementation for part of the functionality.**

## Phase 3 — Correctness + refusal — **60–90 min**

Improve:

- retrieval;
- constraint filtering;
- ingredient/diet/time handling;
- grounding;
- citations;
- refusal;
- allergy/safety behavior.

For every refusal path, verify that the response is machine-detectable through
the JSON fields and does not rely on polite text alone.

## Phase 4 — Tests + Eval — **60–90 min**


### Tests

Cover deterministic logic:

- ingestion;
- normalization;
- retrieval;
- filters;
- API schema;
- refusals;
- edge cases.

For part of the functionality:

> test first → implementation.


### Commit discipline

- Keep commits small and logically focused.
- Commit tests before implementation for at least part of the functionality.
- Avoid large "implement everything" commits.
- Make the commit history show the progression from specification → tests →
implementation → evaluation → deployment.


### Eval harness

Build **12–15 golden questions**:

- normal questions;
- constraints;
- ingredient queries;
- overlapping recipes;
- out-of-corpus;
- out-of-domain;
- allergy/safety;
- edge cases.

Automatically verify:

- JSON schema;
- refusal correctness;
- expected sources / retrieved source correctness;
- citations;
- constraints;
- that answerable questions are not refused;
- that unanswerable questions are refused;
- edge cases.

One command:

```
python -m evals.run
```

The eval output should make failures easy to diagnose.

## Phase 5 — UI — **30–45 min**

Minimal TypeScript UI:

- question input;
- loading/error;
- answer;
- citations;
- refusal.

**Do not spend time on UI polish.**

After the core is complete, the additional requirements from
[`docs/03_SPEC_APPENDIX.md`](docs/03_SPEC_APPENDIX.md) may be considered. They
do not block the assignment and must not take time away from `/ask`, the
standard UI, tests, eval, and deployment.


## Phase 6 — Production + Deploy — **60–90 min**

Minimum:

- Docker;
- environment-based secrets;
- input/request/LLM timeouts;
- structured logs;
- `/health`;
- reproducible dependencies;
- CI;
- IaC;
- public UI + API;
- safe/idempotent deployment;
- container-level operational access.

Deployment verification:

- deploy from a clean repository;
- verify UI and API publicly;
- verify the deployment can be executed twice without breaking the service or
duplicating resources;
- choose and document one container-level access method: hosting dashboard
access OR logs/container status.

The README must explain:

- how to run it;
- how to build the corpus;
- how to test/evaluate;
- how to deploy;
- where the logs/container status are;
- which secrets are needed.

If additional requirements from the appendix are implemented, the README must
also describe them separately as additional capabilities and state how to verify
them. An extra feature must not be presented as a mandatory part of the
assignment.



## Phase 7 — README + final audit + submission check — 30–45 min

The README must contain:

- Architecture;
- Local Development;
- Evaluation;
- Deployment;
- Cost & Latency;
- Production Limitations;
- Observability;
- AI Usage.

Cost section:

- model;
- cost/question;
- cost/1,000 questions;
- latency;
- current bottleneck;
- next optimization.

AI usage:

- prompts/instructions;
- what was accepted from the agent;
- what was rewritten independently;
- key decisions.

Scope Cuts / Known Limitations:

- what was intentionally not implemented because of the 6–8 hour budget;
- why it was cut;
- what would be required to close the gap.

Final audit:

- every TASK requirement has a corresponding implementation or explicit scope cut;
- every acceptance criterion has a verification method;
- all required files are committed;
- public UI URL works;
- public API URL works;
- container-level access is available;
- deployment is reproducible;
- deployment is safe to repeat;
- README contains cost, latency, bottleneck, observability and limitations;
- AI usage artifacts are committed;
- git history is granular enough to demonstrate the engineering process.
