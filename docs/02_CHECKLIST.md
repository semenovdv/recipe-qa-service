# Constraints and Acceptance Criteria — Recipe Q&A Service

The goal is to get not just a list of **what needs to be done**, but a set of
requirements that can be used as:

- the basis for `SPEC.md`;
- a checklist during development;
- the basis for acceptance tests;
- pre-submission verification criteria;
- the basis for the golden eval;
- scope control within the limited 6–8 hours.

### Requirement types


| Type           | Meaning                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------- |
| **MUST**       | A hard requirement. Not meeting it means non-compliance with the assignment.                            |
| **SHOULD**     | An explicitly recommended approach / expectation. Affects quality and grading but allows a conscious compromise. |
| **PREFERENCE** | A preference of the assignment authors. Another option is acceptable with justification.                |
| **BONUS**      | An additional capability that does not replace core requirements.                                       |
| **ASSUMPTION** | A decision not dictated directly and that must be explicitly recorded by the developer.                 |



### Priorities


| Priority  | Meaning                            |
| --------- | ---------------------------------- |
| **P0**    | Critical for assignment compliance |
| **P1**    | Important for quality / grading    |
| **P2**    | An additional improvement          |


---


# 2. Core Product Behavior


| ID      | Type | Priority | Checklist | Requirement                                                      | How to verify                                                    |
| ------- | ---- | -------- | --------- | ---------------------------------------------------------------- | ---------------------------------------------------------------- |
| CORE-01 | MUST | P0       | ☐         | The service answers questions about recipes from a public corpus | Ask several questions via API/UI                                 |
| CORE-02 | MUST | P0       | ☐         | Answers must be based only on the corpus                         | Ask a question with no answer in the corpus; check the refusal   |
| CORE-03 | MUST | P0       | ☐         | Every successful answer must contain citations                   | Inspect the response                                             |
| CORE-04 | MUST | P0       | ☐         | A citation contains the recipe title and URL                     | JSON/schema validation                                           |
| CORE-05 | MUST | P0       | ☐         | If the corpus cannot answer, the service refuses                 | Golden out-of-corpus test                                        |
| CORE-06 | MUST | P0       | ☐         | The refusal must be polite                                       | Manual/eval review                                               |
| CORE-07 | MUST | P0       | ☐         | The refusal must be machine-readable                             | Check `refused` and `refusal_reason`                             |


---


# 3. API


## `POST /ask` (core)


| ID     | Type | Priority | Checklist | Requirement                                           | How to verify               |
| ------ | ---- | -------- | --------- | ----------------------------------------------------- | --------------------------- |
| API-01 | MUST | P0       | ☐         | `POST /ask` exists                                    | HTTP integration test       |
| API-02 | MUST | P0       | ☐         | The endpoint accepts a question                       | Send a valid request        |
| API-03 | MUST | P0       | ☐         | The response is structured JSON                       | JSON parsing + Content-Type |
| API-04 | MUST | P0       | ☐         | The full schema is defined in `SPEC.md`               | Check `SPEC.md`             |
| API-05 | MUST | P0       | ☐         | `answer` is a non-empty `string`                      | Schema validation           |
| API-06 | MUST | P0       | ☐         | The response contains `citations`                     | Schema validation           |
| API-07 | MUST | P0       | ☐         | Every citation contains `title` and `url`             | Schema validation           |
| API-08 | MUST | P0       | ☐         | The response contains `refused: boolean`              | Schema validation           |
| API-09 | MUST | P0       | ☐         | The response contains `refusal_reason`                | Schema validation           |
| API-10 | MUST | P0       | ☐         | `refusal_reason` is limited to the allowed values     | Enum validation             |
| API-11 | MUST | P0       | ☐         | A refusal is determined by structure, not text analysis | Contract test               |



### Minimal response contract

```
{
  "answer": "non-empty string",
  "citations": [
    {
      "title": "...",
      "url": "..."
    }
  ],
  "refused": false,
  "refusal_reason": "out_of_corpus | out_of_domain | safety | null"
}
```

---


# 4. Retrieval / Grounding

This is one of the most significant architectural constraints of the assignment.


| ID     | Type   | Priority | Checklist | Requirement                                                        | How to verify                                        |
| ------ | ------ | -------- | --------- | ------------------------------------------------------------------ | ---------------------------------------------------- |
| RET-01 | MUST   | P0       | ☐         | The answer must be based on the recipes the service retrieved       | E2E/golden test                                      |
| RET-02 | MUST   | P0       | ☐         | The model must not answer from its own memory                       | Create a question with information absent from the corpus |
| RET-03 | MUST   | P0       | ☐         | Retrieval must find the correct source                              | Golden set                                           |
| RET-04 | MUST   | P0       | ☐         | Citations must match the sources of the answer                      | Compare retrieved sources and citations              |
| RET-05 | MUST   | P0       | ☐         | The system must be able to detect corpus insufficiency              | Out-of-corpus eval                                   |
| RET-06 | SHOULD | P1       | ☐         | The retrieval method must be justified                              | ADR                                                  |
| RET-07 | SHOULD | P1       | ☐         | Constraints must be reflected in the retrieval/filtering architecture | Retrieval/filter tests + ADR                         |
| RET-08 | SHOULD | P1       | ☐         | Before EDA the stable-ID baseline is used; a better confirmed EDA signal may replace it | EDA + ADR + deterministic tests |



### Critical constraint

The system must not be built on the principle of:

> User question → LLM → answer

with a simple prompt requirement of "don't hallucinate".

Behavior must be tied to the **retrieved corpus**, not to the model's knowledge.


# 5. Constraints in the user's question

The system must obey the constraints contained in the question.


| ID     | Type | Priority | Checklist | Requirement                                            | How to verify                             |
| ------ | ---- | -------- | --------- | ------------------------------------------------------ | ----------------------------------------- |
| CON-01 | MUST | P0       | ☐         | Obey the time constraint                               | `"under 30 minutes"`                      |
| CON-02 | MUST | P0       | ☐         | Obey the diet constraint                               | `"vegetarian"`                            |
| CON-03 | MUST | P0       | ☐         | Obey the ingredient constraint                         | A question with an ingredient requirement/exclusion |
| CON-04 | MUST | P0       | ☐         | A constraint must not be ignored by the model          | Golden eval                               |
| CON-05 | MUST | P0       | ☐         | Acceptance criteria for constraints are defined in the SPEC | Review SPEC                               |


---


# 6. Refusal Policy


| ID     | Type   | Priority | Checklist | Requirement                                        | How to verify      |
| ------ | ------ | -------- | --------- | -------------------------------------------------- | ------------------ |
| REF-01 | MUST   | P0       | ☐         | Refuse out-of-corpus questions                     | Golden test        |
| REF-02 | MUST   | P0       | ☐         | Refuse out-of-domain questions                     | Golden test        |
| REF-03 | MUST   | P0       | ☐         | Refusal is machine-readable                        | Contract test      |
| REF-04 | MUST   | P0       | ☐         | The correct `refusal_reason` is used               | Golden test        |
| REF-05 | MUST   | P0       | ☐         | The refusal is phrased politely                    | Manual/eval review |
| REF-06 | SHOULD | P1       | ☐         | The refusal policy is explicitly described         | SPEC               |
| REF-07 | SHOULD | P1       | ☐         | The architectural decision on the refusal policy is explained | ADR                |
| REF-08 | MUST   | P0       | ☐         | The behavior for an empty question is defined      | SPEC + test        |


---


# 7. Safety / Allergy

The assignment specifically requires careful behavior for questions like:

> `"Is this nut-free?"`


| ID      | Type | Priority | Checklist | Requirement                                                            | How to verify |
| ------- | ---- | -------- | --------- | ---------------------------------------------------------------------- | ------------- |
| SAFE-01 | MUST | P0       | ☐         | The system must have a defined policy for allergy/safety questions     | SPEC          |
| SAFE-02 | MUST | P0       | ☐         | "Careful" must be defined by the developer                             | SPEC          |
| SAFE-03 | MUST | P0       | ☐         | A safety refusal must be machine-readable                              | Golden test   |
| SAFE-04 | MUST | P0       | ☐         | Unsupported safety/allergy claims are forbidden                        | Negative test |
| SAFE-05 | MUST | P0       | ☐         | The edge case `"Is this nut-free?"` must be handled explicitly         | SPEC + test   |



### Important point

The assignment **does not provide a ready-made allergy policy**.

Therefore this is an `ASSUMPTION`: the developer must make a decision and record
it in `SPEC.md`. Such logic must not remain hidden inside the code.


---


# 8. Corpus / Ingestion


| ID      | Type   | Priority | Checklist | Requirement                                                | How to verify              |
| ------- | ------ | -------- | --------- | ---------------------------------------------------------- | -------------------------- |
| CORP-01 | MUST   | P0       | ☐         | The Wikibooks Cookbook is used                             | Inspect ingestion          |
| CORP-02 | MUST   | P0       | ☐         | Data is obtained through the MediaWiki API                 | Code review                |
| CORP-03 | MUST   | P0       | ☐         | The corpus contains 40–60 recipes                          | Automated count            |
| CORP-04 | MUST   | P0       | ☐         | Several categories are used                                | Inspect ingestion config   |
| CORP-05 | MUST   | P0       | ☐         | The corpus has variety                                     | Corpus review              |
| CORP-06 | MUST   | P0       | ☐         | Different cuisines                                         | Corpus review              |
| CORP-07 | MUST   | P0       | ☐         | Overlapping dishes exist                                   | Corpus review              |
| CORP-08 | MUST   | P0       | ☐         | Different levels of structure exist                        | Corpus review              |
| CORP-09 | MUST   | P0       | ☐         | Ingestion script is committed                              | Git                        |
| CORP-10 | MUST   | P0       | ☐         | The corpus can be rebuilt from the script alone            | Clean checkout + rebuild   |
| CORP-11 | SHOULD | P1       | ☐         | Corpus build is reproducible                               | Repeated ingestion/build   |


---


# 9. Frontend


| ID    | Type         | Priority | Checklist | Requirement                          | How to verify           |
| ----- | ------------ | -------- | --------- | ------------------------------------ | ----------------------- |
| UI-01 | MUST         | P0       | ☐         | There is a web UI                    | Open the UI             |
| UI-02 | MUST         | P0       | ☐         | The frontend is written in TypeScript | Repository/build review |
| UI-03 | MUST         | P0       | ☐         | The UI is a single page              | Review                  |
| UI-04 | MUST         | P0       | ☐         | A question can be entered            | Manual E2E              |
| UI-05 | MUST         | P0       | ☐         | The UI shows the answer              | Manual E2E              |
| UI-06 | MUST         | P0       | ☐         | The UI shows citations               | Manual E2E              |
| UI-07 | MUST         | P0       | ☐         | The UI shows refusals                | Manual E2E              |
| UI-08 | MUST         | P0       | ☐         | The UI must function                 | E2E                     |
| UI-09 | NOT REQUIRED | —        | ☐         | UI appearance/polish is not graded   | Do not spend time       |
| UI-11 | MUST         | P0       | ☐         | The core UI sends a request to `/ask` | UI integration test     |
| UI-13 | MUST         | P0       | ☐         | The core UI shows the answer and the citations list | Manual/E2E |
| UI-16 | MUST         | P0       | ☐         | Raw Markdown syntax is not displayed to the user | UI security test |
| UI-17 | MUST         | P0       | ☐         | On a new question the previous result is cleared | Manual/E2E |


---


# 10. Deployment

A local run is not sufficient.


| ID     | Type   | Priority | Checklist | Requirement                                  | How to verify         |
| ------ | ------ | -------- | --------- | -------------------------------------------- | --------------------- |
| DEP-01 | MUST   | P0       | ☐         | The service is deployed                      | Deployment check      |
| DEP-02 | MUST   | P0       | ☐         | There is a public URL for the UI             | HTTP                  |
| DEP-03 | MUST   | P0       | ☐         | There is a public URL for the API            | HTTP                  |
| DEP-04 | MUST   | P0       | ☐         | The evaluator can use both                   | External E2E          |
| DEP-05 | MUST   | P0       | ☐         | There is container-level visibility          | Logs/status/dashboard |
| DEP-06 | MUST   | P0       | ☐         | The access method is recorded in the README  | README review         |
| DEP-07 | SHOULD | P1       | ☐         | Infrastructure as Code is used               | Repository review     |
| DEP-08 | MUST   | P0       | ☐         | Deployment files are committed               | Git                   |
| DEP-09 | MUST   | P0       | ☐         | A new deployment is possible without manual UI steps | Clean deployment |
| DEP-10 | MUST   | P0       | ☐         | Secrets are in the environment               | Secret scan           |
| DEP-11 | MUST   | P0       | ☐         | Secrets are absent from the repository       | Git/secret scan       |
| DEP-12 | SHOULD | P1       | ☐         | Builds are reproducible                      | Rebuild               |
| DEP-13 | SHOULD | P1       | ☐         | Docker is preferred                          | Repository            |
| DEP-14 | MUST   | P0       | ☐         | Deployment is safe to run twice              | Deploy twice          |
| DEP-15 | SHOULD | P1       | ☐         | Cheap/free tiers are acceptable              | Cost review           |



### Deployment must allow

```
clean repository
      ↓
deployment configuration
      ↓
deployment
      ↓
working UI + API
```

without any need to manually configure the system through the hosting UI.

---


# 11. `SPEC.md`

At the current stage the specification is kept in `docs/03_SPEC.md` as a
numbered working draft. The root `SPEC.md` is the canonical entry point that
references this file; a separate copy of the spec must not be maintained.


| ID      | Type | Priority | Checklist | Requirement                                                  | How to verify    |
| ------- | ---- | -------- | --------- | ------------------------------------------------------------ | ---------------- |
| SPEC-01 | MUST | P0       | ☐         | `SPEC.md` exists                                             | File check       |
| SPEC-02 | MUST | P0       | ☐         | The SPEC is written before the code                          | Git history      |
| SPEC-03 | MUST | P0       | ☐         | The full API contract is described                           | Review           |
| SPEC-04 | MUST | P0       | ☐         | The full response schema is defined                          | Review           |
| SPEC-05 | MUST | P0       | ☐         | There are acceptance criteria                                | Review           |
| SPEC-06 | MUST | P0       | ☐         | Empty question                                               | SPEC             |
| SPEC-07 | MUST | P0       | ☐         | Out-of-domain question                                       | SPEC             |
| SPEC-08 | MUST | P0       | ☐         | Disagreement between recipes                                 | SPEC             |
| SPEC-09 | MUST | P0       | ☐         | Allergy questions                                            | SPEC             |
| SPEC-10 | MUST | P0       | ☐         | Latency budget                                               | SPEC             |
| SPEC-11 | MUST | P0       | ☐         | Cost target / 1,000 questions                                | SPEC             |
| SPEC-12 | MUST | P0       | ☐         | Every ambiguity is either clarified or recorded as an assumption | Review        |
| SPEC-13 | MUST | P0       | ☐         | No hidden hardcoded behavior                                 | Code/spec review |
| SPEC-14 | MUST | P0       | ☐         | All inputs/outputs of the core `/ask` are described          | Review           |


---


# 12. ADRs

There must be **2–3 Architecture Decision Records**.


| ID     | Type | Priority | Checklist | Requirement                                              | How to verify |
| ------ | ---- | -------- | --------- | -------------------------------------------------------- | ------------- |
| ADR-01 | MUST | P0       | ☐         | There are 2–3 ADRs                                       | File count    |
| ADR-02 | MUST | P0       | ☐         | The ADRs describe important architectural choices        | Review        |
| ADR-03 | MUST | P0       | ☐         | Alternatives are listed                                  | Review        |
| ADR-04 | MUST | P0       | ☐         | Criteria are defined                                     | Review        |
| ADR-05 | MUST | P0       | ☐         | Trade-offs are described                                 | Review        |
| ADR-06 | MUST | P0       | ☐         | Real cost/latency numbers are present where possible     | Review        |
| ADR-07 | MUST | P0       | ☐         | Conditions that invalidate the decision are described    | Review        |


Possible topics:

- chunking strategy;
- retrieval method;
- metadata filters;
- model selection;
- refusal policy;
- caching;
- deployment target.

---


# 13. Eval Harness


| ID      | Type   | Priority | Checklist | Requirement                                                  | How to verify   |
| ------- | ------ | -------- | --------- | ------------------------------------------------------------ | --------------- |
| EVAL-01 | MUST   | P0       | ☐         | There is a golden set                                        | Repository      |
| EVAL-02 | MUST   | P0       | ☐         | 12–15 questions                                              | Count           |
| EVAL-03 | MUST   | P0       | ☐         | A correct source is expected for each                        | Golden data     |
| EVAL-04 | MUST   | P0       | ☐         | A refusal is expected for the right questions                | Golden data     |
| EVAL-05 | MUST   | P0       | ☐         | Expected behavior is set for constraint questions            | Golden data     |
| EVAL-06 | MUST   | P0       | ☐         | There is an automated script                                 | Run             |
| EVAL-07 | MUST   | P0       | ☐         | The script checks the JSON contract                          | Run             |
| EVAL-08 | MUST   | P0       | ☐         | The script produces results/a report                         | Run             |
| EVAL-09 | MUST   | P0       | ☐         | Manual tests are not the only proof                           | Review          |
| EVAL-10 | SHOULD | P1       | ☐         | The golden set covers core + refusals + constraints + safety | Coverage review |
| EVAL-11 | MUST   | P0       | ☐         | The `/ask` eval checks the standard JSON response contract    | Eval runner      |


---


# 14. Automated Tests


| ID      | Type   | Priority | Checklist | Requirement                                       | How to verify |
| ------- | ------ | -------- | --------- | ------------------------------------------------- | ------------- |
| TEST-01 | MUST   | P0       | ☐         | There are automated tests                         | Test runner   |
| TEST-02 | MUST   | P0       | ☐         | Ingestion is tested                               | Tests         |
| TEST-03 | MUST   | P0       | ☐         | Retrieval is tested                               | Tests         |
| TEST-04 | MUST   | P0       | ☐         | Filters are tested                                | Tests         |
| TEST-05 | MUST   | P0       | ☐         | The API contract is tested                        | Tests         |
| TEST-06 | MUST   | P0       | ☐         | There is a granular commit history                | Git log       |
| TEST-07 | SHOULD | P1       | ☐         | Some tests were committed before implementation   | Git history   |
| TEST-08 | MUST   | P0       | ☐         | Non-LLM logic is covered by automated tests       | Test review   |


---


# 15. [README.md](../README.md)


| ID        | Type   | Priority | Checklist | Requirement                                  | How to verify       |
| --------- | ------ | -------- | --------- | -------------------------------------------- | ------------------- |
| README-01 | MUST   | P0       | ☐         | `README.md` exists                           | File                |
| README-02 | MUST   | P0       | ☐         | The local run is described                   | Follow instructions |
| README-03 | SHOULD | P1       | ☐         | Docker is preferred                          | README              |
| README-04 | MUST   | P0       | ☐         | Deployment is described                      | README              |
| README-05 | MUST   | P0       | ☐         | The provider choice is explained             | README              |
| README-06 | MUST   | P0       | ☐         | The deployment process is described          | README              |
| README-07 | MUST   | P0       | ☐         | Cost of one question                         | README              |
| README-08 | MUST   | P0       | ☐         | Cost of 1,000 questions                      | README              |
| README-09 | MUST   | P0       | ☐         | Selected models are stated                   | README              |
| README-10 | MUST   | P0       | ☐         | Model selection is explained                 | README              |
| README-11 | MUST   | P0       | ☐         | Conditions for switching to a cheaper/more capable model | README |
| README-12 | MUST   | P0       | ☐         | Current bottleneck                           | README              |
| README-13 | MUST   | P0       | ☐         | Next optimization                            | README              |
| README-14 | MUST   | P0       | ☐         | Bad-answer investigation is described        | README              |
| README-15 | MUST   | P0       | ☐         | What is logged/traced is described           | README              |
| README-16 | MUST   | P0       | ☐         | Container-level access                       | README              |
| README-17 | MUST   | P0       | ☐         | Public UI URL                                | README              |
| README-18 | MUST   | P0       | ☐         | Public API URL                               | README              |


---


# 16. Observability / Operations


| ID     | Type   | Priority | Checklist | Requirement                                          | How to verify |
| ------ | ------ | -------- | --------- | ---------------------------------------------------- | ------------- |
| OPS-02 | MUST   | P0       | ☐         | A bad answer can be investigated                     | README + logs |
| OPS-03 | MUST   | P0       | ☐         | What is logged/traced is described                   | README        |
| OPS-04 | SHOULD | P1       | ☐         | The retrieval/model path can be understood during an investigation | Logs/review |


> The last item is an engineering interpretation of the production/operations
> requirement, not a verbatim requirement of the source text.


---


# 17. Cost & Latency


| ID      | Type   | Priority | Checklist | Requirement                                               | How to verify |
| ------- | ------ | -------- | --------- | --------------------------------------------------------- | ------------- |
| PERF-01 | MUST   | P0       | ☐         | The SPEC defines a latency budget                         | SPEC          |
| PERF-02 | MUST   | P0       | ☐         | The SPEC defines a cost target / 1,000 questions          | SPEC          |
| PERF-03 | MUST   | P0       | ☐         | The README contains cost / question                       | README        |
| PERF-04 | MUST   | P0       | ☐         | The README contains cost / 1,000 questions                | README        |
| PERF-05 | MUST   | P0       | ☐         | The README contains the current bottleneck                | README        |
| PERF-06 | MUST   | P0       | ☐         | The README contains the next optimization                 | README        |
| PERF-07 | SHOULD | P1       | ☐         | The ADRs contain real cost/latency numbers where possible | ADR review    |


---


# 18. AI Coding Workflow


| ID    | Type | Priority | Checklist | Requirement                                              | How to verify    |
| ----- | ---- | -------- | --------- | -------------------------------------------------------- | ---------------- |
| AI-01 | MUST | P0       | ☐         | Agent instructions are committed                         | Repo             |
| AI-02 | MUST | P0       | ☐         | `CLAUDE.md` / rule files are committed, if used          | Repo             |
| AI-03 | MUST | P0       | ☐         | Important prompts are committed                          | Repo             |
| AI-04 | MUST | P0       | ☐         | Relevant spec files are committed                        | Repo             |
| AI-05 | MUST | P0       | ☐         | Notes on what was accepted from the agent exist          | Repo             |
| AI-06 | MUST | P0       | ☐         | Notes on what was rewritten independently exist          | Repo             |
| AI-07 | MUST | P0       | ☐         | The developer is responsible for decisions and code      | Review/follow-up |


---


# 19. Production Engineering


| ID     | Type   | Priority | Checklist | Requirement                                                | How to verify   |
| ------ | ------ | -------- | --------- | ---------------------------------------------------------- | --------------- |
| ENG-01 | MUST   | P0       | ☐         | The service must be production-oriented, not a demo        | Overall review  |
| ENG-02 | MUST   | P0       | ☐         | Code quality practices                                     | Code review     |
| ENG-03 | MUST   | P0       | ☐         | Security practices                                         | Security review |
| ENG-04 | MUST   | P0       | ☐         | CI/CD practices                                            | CI/deployment   |
| ENG-05 | MUST   | P0       | ☐         | Operations practices                                       | Ops review      |
| ENG-06 | MUST   | P0       | ☐         | If production grade is not reached — the gap is recorded in the README | README |
| ENG-07 | MUST   | P0       | ☐         | What is needed to close the gap is described               | README          |
| ENG-08 | SHOULD | P1       | ☐         | Reproducible builds                                        | Rebuild         |
| ENG-09 | SHOULD | P1       | ☐         | Infrastructure as Code                                     | Repository      |
| ENG-10 | MUST   | P0       | ☐         | Deployment is idempotent                                   | Deploy twice    |
| ENG-11 | SHOULD | P1       | ☐         | CI includes quality/security scans; agent-assisted review is used as an advisory check | CI/review |


---


# 20. Scope Constraints

Time and scope are also part of the assignment.


| ID       | Type       | Priority | Checklist | Requirement                                             | How to verify |
| -------- | ---------- | -------- | --------- | ------------------------------------------------------- | ------------- |
| SCOPE-01 | MUST       | P0       | ☐         | Time budget: 6–8 hours of focused work                  | Process       |
| SCOPE-02 | MUST       | P0       | ☐         | No unnecessary polish                                   | Scope review  |
| SCOPE-03 | MUST       | P0       | ☐         | Scope cutting must be conscious                         | README        |
| SCOPE-04 | MUST       | P0       | ☐         | What is cut must be recorded                            | README        |
| SCOPE-05 | MUST       | P0       | ☐         | Core functions have priority                            | Review        |
| SCOPE-06 | MUST       | P0       | ☐         | Extra features do not replace an incomplete core        | Review        |
| SCOPE-07 | PREFERENCE | P1       | ☐         | Python is preferred for the backend                     | Stack         |
| SCOPE-08 | MUST       | P0       | ☐         | TypeScript is mandatory for the frontend                | Repository    |
| SCOPE-09 | PREFERENCE | P1       | ☐         | Docker is preferred                                     | Deployment    |


---


# 21. Submission


| ID     | Type | Priority | Checklist | Requirement                              | How to verify    |
| ------ | ---- | -------- | --------- | ---------------------------------------- | ---------------- |
| SUB-01 | MUST | P0       | ☐         | Private Git repository                   | Repository       |
| SUB-02 | MUST | P0       | ☐         | The evaluator received access            | Access test      |
| SUB-03 | MUST | P0       | ☐         | The deployed URL is stated               | README           |
| SUB-04 | MUST | P0       | ☐         | Container-level access is stated         | README           |
| SUB-05 | MUST | P0       | ☐         | All deliverables are in the repository   | Repository audit |


---


# 22. Final Acceptance Checklist


## 🔴 P0 — Core

- `POST /ask` works
- `/ask` returns task-compatible JSON
- The response conforms to the full JSON schema
- Answers are based only on the retrieved corpus
- The model does not answer from its own memory
- Every successful answer contains citations
- A citation contains title + URL
- Out-of-corpus → machine-readable refusal
- Out-of-domain → machine-readable refusal
- Safety → machine-readable refusal, when applicable
- A refusal has the correct `refusal_reason`
- An empty question has defined behavior
- The time constraint is obeyed
- The diet constraint is obeyed
- The ingredient constraint is obeyed
- A policy for conflicting recipes is defined
- An allergy policy is defined
- The UI works end-to-end
- The frontend is written in TypeScript
- The standard JSON UI sends a request to `/ask` and shows answer/citations/refusal


## 🔴 P0 — Corpus

- Wikibooks Cookbook
- MediaWiki API
- 40–60 recipes
- Several categories
- Different cuisines
- Overlapping dishes
- Different levels of structure
- Ingestion script committed
- The corpus can be rebuilt from the script


## 🔴 P0 — Specification

- `SPEC.md` exists
- `SPEC.md` was created before implementation
- Full API contract
- Inputs/outputs of the core endpoints
- Full response schema
- Acceptance criteria
- Empty question
- Out-of-domain
- Conflicting recipes
- Allergy questions
- Latency budget
- Cost target / 1,000 questions
- Every ambiguity is explicitly resolved or recorded as an assumption
- No hidden hardcoded behavior


## 🔴 P0 — ADRs

- 2–3 ADRs
- Alternatives
- Decision criteria
- Trade-offs
- Cost/latency numbers where possible
- Conditions for invalidation


## 🔴 P0 — Evaluation

- Golden set
- 12–15 questions
- Expected source for each
- Expected refusal where necessary
- Expected constraint behavior
- Automated eval script
- The script checks the JSON contract
- The script produces a report
- Manual testing is not the only proof


## 🔴 P0 — Tests

- Automated tests
- Ingestion tests
- Retrieval tests
- Filter tests
- API contract tests
- Granular commit history
- At least some tests committed before implementation


## 🔴 P0 — Deployment

- The service is deployed
- Public UI URL
- Public API URL
- Container-level access
- Access described in the README
- Deployment definition committed
- A new deployment without manual UI steps
- Secrets only in the environment
- Secrets absent from the repository
- Deployment is safe to run twice
- The build is reproducible


## 🔴 P0 — README

- Local run instructions
- Deployment provider
- Why this provider
- Deployment process
- Cost / question
- Cost / 1,000 questions
- Selected models
- Model selection rationale
- Conditions for model change
- Current bottleneck
- Next optimization
- Bad-answer investigation
- Logging/tracing strategy
- Container-level access
- UI URL
- API URL


## 🔴 P0 — AI Workflow

- Agent instructions committed
- Rule files / `CLAUDE.md`, if used
- Important prompts committed
- Relevant spec files committed
- Notes: what was accepted from AI
- Notes: what was rewritten independently


## 🟡 P1 — Quality

- Python backend
- Docker
- IaC
- Strong observability
- Cost/latency measurements
- Well-justified ADRs


## 🟢 P2 — Bonus

All bonus requirements are moved to
[`docs/03_SPEC_APPENDIX.md`](docs/03_SPEC_APPENDIX.md) and are graded only
after a complete core.


---


# 23. 10 requirements that are especially easy to miss

1. **Answers only from the corpus.**
  RAG must actually constrain answer generation.
2. **Machine-readable refusal.**
  Simply writing `"Sorry, I don't know"` in `answer` is not enough.
3. **Constraints must actually be obeyed.**
  Especially `time`, `diet`, `ingredient`.
4. **The allergy/safety policy must be your explicitly documented decision.**
5. **Define the behavior when two recipes contradict each other.**
6. **The corpus must be reproducible.**
  Not just committing the collected 50 recipes — you need an ingestion script
  through which the corpus can be built again.
7. **The eval harness is mandatory.**
  12–15 golden questions + automated verification are part of the proof that the
  system is correct.
8. **Deployment is mandatory.**
  A repository that works only locally does not meet the assignment.
9. **SPEC → ADR → Eval → Code** is effectively the expected workflow.
  The assignment authors separately grade the ability to first define the
  behavior and the way to verify it, and only then write the implementation.
10. **Do not try to do everything perfectly.**
  If production grade is not reached within the allotted time, honestly record
  the gap and describe what is required to close it.

Source of requirements: the original Take-Home Assignment, 00_TASK.md.
