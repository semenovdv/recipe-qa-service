# Recipe Q&A Service — Work Plan

Основной принцип:

> Сначала понять и формализовать требования → затем спроектировать решение → затем реализовать → затем проверить → затем задеплоить → затем провести финальный аудит.

## Phase 0 — Requirements + acceptance — **60–90 min**

1. Read assignment carefully.
2. Extract requirements.
3. Write `SPEC.md`.
  1. Define acceptance checklist.
  2. Record assumptions.
4. Create a traceable acceptance checklist mapping each assignment requirement to a verification method (test, eval, manual check, or deployment check).

Зафиксировать:

- answerable / out-of-corpus / out-of-domain;
- constraints: time, diet, ingredients;
- allergy/safety policy;
- conflicting recipes;
- empty/invalid questions;
- API schema;
- latency and cost targets.

Дополнительно зафиксировать:

- full JSON response schema as a machine-readable schema;
- what evidence is sufficient to consider a question answerable;
- assumptions for any ambiguous assignment requirements.



### Phase 1 — Architecture + corpus — **45–60 min**

1. Choose stack.
2. Write 2–3 ADRs.
3. Implement reproducible Wikibooks ingestion.
4. Build 40–60 recipe corpus.
5. Run EDA on the corpus to check whether a reliable selection signal exists.
6. Verify corpus variety.

ADRs examples:

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

Не добавлять отдельный design doc без необходимости. Архитектурные решения должны быть отражены в `SPEC.md` и ADRs.

**Не делать ручную подготовку данных, которую нельзя повторить.**

---



## Phase 2 — First vertical slice — **60–90 min**

Как можно раньше получить работающий путь:

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

> Один вопрос → корректный grounded answer → citation → valid JSON.

Сразу определить и реализовать `/ask` + `/health`.

Maintain small, meaningful commits throughout the project.

**test before implementation для части функций**.

## Phase 3 — Correctness + refusal — **60–90 min**

Улучшить:

- retrieval;
- constraint filtering;
- ingredient/diet/time handling;
- grounding;
- citations;
- refusal;
- allergy/safety behavior.

For every refusal path, verify that the response is machine-detectable through the JSON fields and does not rely on polite text alone.

## Phase 4 — Tests + Eval — **60–90 min**



### Tests

Покрыть deterministic logic:

- ingestion;
- normalization;
- retrieval;
- filters;
- API schema;
- refusals;
- edge cases.

Для части функциональности:

> test first → implementation.



### Commit discipline

- Keep commits small and logically focused.
- Commit tests before implementation for at least part of the functionality.
- Avoid large "implement everything" commits.
- Make the commit history show the progression from specification → tests → implementation → evaluation → deployment.



### Eval harness

Сделать **12–15 golden questions**:

- normal questions;
- constraints;
- ingredient queries;
- overlapping recipes;
- out-of-corpus;
- out-of-domain;
- allergy/safety;
- edge cases.

Автоматически проверять:

- JSON schema;
- refusal correctness;
- expected sources / retrieved source correctness;
- citations;
- constraints;
- that answerable questions are not refused;
- that unanswerable questions are refused;
- edge cases.

Одна команда:

```
python -m evals.run
```

The eval output should make failures easy to diagnose.

## Phase 5 — UI — **30–45 min**

Минимальный TypeScript UI:

- question input;
- loading/error;
- answer;
- citations;
- refusal.

**Не тратить время на UI polish.**

После завершения core можно рассмотреть дополнительные требования из
[`03_SPEC_APPENDIX.md`](03_SPEC_APPENDIX.md). Они не блокируют
выполнение задания и не должны отнимать время у `/ask`, обычного UI, тестов,
eval и deployment.

## Phase 6 — Production + Deploy — **60–90 min**

Минимум:

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
- verify deployment can be executed twice without breaking the service or duplicating resources;
- choose and document one container-level access method: hosting dashboard access OR logs/container status.

README должен объяснять:

- как запустить;
- как собрать corpus;
- как протестировать/evaluate;
- как deploy;
- где logs/container status;
- какие secrets нужны.

Если реализованы дополнительные требования из appendix, README также должен
отдельно описать их как дополнительные возможности и указать способ проверки.
Нельзя выдавать дополнительную фичу за обязательную часть задания.



## Phase 7 — README + final audit + submission check — 30–45 min

README обязательно содержит:

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
- что принял от агента;
- что переписал сам;
- важные решения.

Scope Cuts / Known Limitations;

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
- git history is granular enough to demonstrate engineering process.
