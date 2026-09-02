# Recipe Q&A Service — Behaviour Specification

**Version:** 1.1  
**Status:** Normative MVP specification  
**Date:** 2026-08-29

This document is the contract for implementation and evaluation of the Recipe Q&A
Service. It defines observable behaviour; implementation choices such as the web
framework, vector store, model provider and hosting provider remain open to the
ADRs unless this document says otherwise.

## 1. Product goal

The service answers natural-language questions about recipes using only a
reproducible corpus collected from the Wikibooks Cookbook through the MediaWiki
API. Every answer cites the Wikibooks recipe pages that support it. When the
corpus or the service's safety policy cannot support an answer, the service
refuses explicitly and in a machine-readable way.

The end-to-end user path is:

```text
question → validation/domain check → retrieval and hard filters
         → evidence gate → grounded answer generation → schema/citation validation
         → JSON response and UI rendering
```

The model is an answer formatter over retrieved evidence, not the source of
recipe knowledge. No answer may be generated from model memory when there is no
sufficient retrieved evidence.

## 2. Scope and non-goals



### In scope

- A corpus of 40–60 recipes from multiple Wikibooks Cookbook categories.
- Reproducible ingestion through the MediaWiki API (with versions).
- Corpus has variety: different cuisines, dishes that overlap, and different levels of structure.
- Natural-language recipe questions in the MVP's supported language: English.
- Retrieval, deterministic hard filtering, grounded answer generation, citations, refusals, and a minimal one-page TypeScript UI.
- `POST /ask`, `GET /health`, automated tests, a 12–15 question golden eval, Docker-based local execution, and a public deployment.
- Optional bonus requirements are maintained separately in
  [`03_SPEC_APPENDIX.md`](03_SPEC_APPENDIX.md) and must not block the core
  path.
- Stateless question-answer interaction in the UI: one submitted question produces one response; the UI does not maintain a chat transcript.
- The core UI uses `/ask` and shows the answer, citations and refusals. Bonus UI
  requirements are defined in the appendix.
- Previous UI result is cleared when a new question is submitted; only the current request and its result are shown.
- Direct recipe questions, recipe discovery, ingredient lookups, cooking steps,  
and explicit time/diet/ingredient constraints when the corpus supports them.
- Refusal mechanism with machine and human readable format and reason if question is out of corpus or out of domain.



### Explicitly out of scope for the MVP

- Authentication, user accounts, saved conversations, personalisation, and
conversation memory.
- Chat mode, multi-turn context, and message history. Bonus requirements are
  specified separately in `03_SPEC_APPENDIX.md`.
- Voice input, video and image-based cooking assistance, ratings, shopping lists, nutrition calculations, and recipe generation.
- Medical, dietary, allergy, contamination, or food-safety certification.
- Answers based on websites or knowledge sources other than the built corpus.
- Kubernetes or a multi-service deployment unless required by the selected
hosting provider.
- UI visual polish beyond clear input, loading, answer, citations, refusal and
error states.
- No caching requests to LLM.
- No UI for explicit recipe filtering.
- No auto AI-assisted code quality review for PR and deployments.

These non-goals are deliberate scope cuts for the 6–8 hour assignment. If any
one is later added, its behaviour and evaluation cases must be specified before
implementation.

## 3. Terms and source-of-truth rules

- **Corpus:** the versioned build output containing normalized recipe records
and their original Wikibooks metadata.
- **Recipe record:** one source page, including a stable record ID, title, URL,  
source text, parsed sections and any metadata that can be supported by that  
source text.
- **Citation:** the server-generated title and canonical URL of a retrieved  
recipe. The model must not invent citation URLs.

The corpus is the sole source of recipe facts. A model's general knowledge,
search results, user-provided unstated facts, and plausible culinary inferences
are not evidence.

## 4. Assumptions and decisions made explicit

1. The evaluator sends UTF-8 JSON and primarily uses English questions. The MVP
  does not promise multilingual retrieval; an unsupported-language recipe
   question is refused when reliable corpus support cannot be established.
2. The corpus is a build-time artifact, not a live web search. Each record keeps
  its Wikibooks title and URL, and ingestion records the corpus build/source
   version so a deployment can be tied to an exact corpus.
3. A valid but unanswerable user question is still a successful API operation:
  it returns HTTP `200` with the response contract, `refused: true`, and a
  non-null `refusal_reason`.
4. Empty, malformed, or structurally invalid requests are protocol validation
  failures, not content refusals. They return HTTP `400` and are never sent to
   retrieval or the LLM.
5. The corpus may contain several recipes for the same dish. Sources are kept
  separate; the service does not silently merge contradictory instructions. For
  a generic singular question, the service selects one best-supported recipe
  using a deterministic ranking and tie-break rule; it does not ask the user to
  choose a preferred recipe. Given the same corpus version and normalized
  question, the selected recipe must be stable. A comparison question may
  intentionally retrieve multiple recipes.
6. “Under N minutes” is strict (`total_time < N`); “N minutes or less” is
  inclusive (`total_time <= N`). A recipe qualifies only when total time is
   explicitly present or can be conservatively computed from both prep and cook
   times. Missing or ambiguous time metadata does not qualify for a hard time
   constraint.
7. Dietary labels are claims made only by a documented deterministic rule over
  the normalized ingredients/source text. Uncertainty excludes a recipe from a
  hard dietary match; it is never resolved by model intuition. For processed or
  ready-made products such as pastes, sauces, stocks and seasoning blends, the
  service must not infer the product's full ingredient list from its generic
  name. It should tell the user to check the product label for their own dietary
  needs; this reminder is not a safety certification.
8. “Nut-free”, “safe for my allergy”, “safe to eat”, cross-contamination,
  spoilage, doneness, pregnancy and medical-condition questions are treated as
   safety-sensitive and refused. The corpus cannot certify safety.
9. Fixed hosting costs are excluded from marginal per-question cost targets;
  LLM, embedding and variable request costs are included. The README must
   later report both the marginal estimate and fixed deployment cost separately.
10. No user authentication exists in the MVP, so public deployments must use
  HTTPS, request-size limits and a basic rate limit to reduce abuse.
11. The API is stateless Q&A, not a chat API. Each request is independent and
  contains one question only; previous requests are not sent to the backend or
  used as context. On every new UI submission, the previous answer, citations,
  refusal and error state are removed from the result area before the new
  request is rendered.
12. The assignment's minimal contract shows `answer` as `string | null`. This
  specification deliberately tightens it: `answer` is always a non-empty
  string, and a refusal's human-readable message lives in `answer` rather than
  in a nullable field. Machine detectability of a refusal comes from `refused`
  and `refusal_reason`; the non-empty `answer` requirement only removes the
  null case from the schema.



### 4.1 Internal refusal subreasons

The public response exposes only the three stable `refusal_reason` values from
§7.1. For internal observability and evaluation diagnostics, every business
refusal SHOULD also carry a controlled `refusal_subreason`. This field is for
logs and internal reports only: it MUST NOT be returned in the public API
response, displayed in the UI, accepted from the client, or used as a second
public contract.

The initial internal taxonomy is:


| Public `refusal_reason` | Internal `refusal_subreason` | Meaning                                                                                              |
| ----------------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------- |
| `out_of_corpus`         | `recipe_not_found`           | No relevant recipe record was retrieved.                                                             |
| `out_of_corpus`         | `attribute_missing`          | The requested fact is not explicit in the corpus.                                                    |
| `out_of_corpus`         | `constraint_unsatisfied`     | No recipe satisfies all hard constraints.                                                            |
| `out_of_corpus`         | `insufficient_evidence`      | A candidate exists, but evidence does not support the requested claim.                               |
| `out_of_corpus`         | `ambiguous_question`         | The question cannot be answered without guessing the user's intent.                                  |
| `out_of_corpus`         | `conflicting_sources`        | Sources conflict and the requested definitive answer cannot be represented safely.                   |
| `out_of_corpus`         | `unsupported_language`       | The recipe intent cannot be reliably matched in the supported language.                              |
| `out_of_corpus`         | `source_quality_failure`     | The source is present but incomplete, malformed or lacks citation-ready metadata.                    |
| `out_of_domain`         | `non_recipe_topic`           | The primary intent is unrelated to recipes or cooking.                                               |
| `out_of_domain`         | `unsupported_operation`      | The user requests generation, nutrition calculation, shopping list or another unsupported operation. |
| `out_of_domain`         | `internal_or_prompt_request` | The user requests system prompts, secrets or an override of service rules.                           |
| `safety`                | `allergy_certification`      | The user asks whether a recipe is allergen-free or safe for an allergy.                              |
| `safety`                | `medical_advice`             | The user asks for advice related to a medical condition, pregnancy or treatment.                     |
| `safety`                | `food_safety`                | The user asks about contamination, spoilage, doneness or whether food is safe to eat.                |
| `safety`                | `dangerous_instruction`      | The request would provide or validate dangerous cooking/food instructions.                           |


`refusal_subreason` is an extensible internal taxonomy. Adding a value does not
change the public response schema, but it must be documented and covered by an
internal test. Operational failures such as `validation_error`, `rate_limited`,
`corpus_unavailable`, `llm_timeout` and `llm_invalid_output` are not refusal
subreasons; they belong to the error/operations event taxonomy and must be
logged separately.

### 4.2 Single-recipe selection policy

When a generic singular question matches multiple recipes for the same dish,
the service MUST select exactly one source for the answer. It MUST NOT ask the
user to choose and MUST NOT select randomly or let the LLM choose an arbitrary
source. The selected source must be stable for the same normalized question,
corpus version and configuration.

Before exploratory data analysis (EDA) of the corpus, the service fixes
**first by stable recipe ID** as its baseline deterministic selection strategy.
After relevance and all hard-constraint filters are applied, it selects the
candidate with the lowest stable recipe ID. This baseline is reproducible,
auditable and independent of LLM output.

The EDA may replace this baseline with a better reliable signal when the corpus
provides one—for example, popularity, page-view count or user likes. The
signal may be used only after relevance and hard-constraint filtering, must be
available and comparable for the candidates, and must be versioned and
documented. If EDA finds no sufficiently reliable signal, the stable-ID
baseline remains in force. Any switch must be recorded in ADR-001 with updated
deterministic tests. The strategy name, signal/version, candidate IDs, selected
ID and tie-break result must be included in internal logs. The selection policy
must never override a hard user constraint.

## 5. User-visible behaviour



### 5.1 Answerable question

For a valid recipe question with sufficient evidence, the service MUST:

- return HTTP `200` and a response conforming to the schema in §7;
- answer only the supported part of the question;
- obey all detected hard constraints;
- cite at least one retrieved recipe supporting the answer;
- use the source's wording/values where a precise fact is requested; and
- say when sources describe alternatives or disagree.

The answer SHOULD be concise and useful. It MUST NOT present unsupported
ingredients, times, temperatures, substitutions, safety claims, or citations.

### 5.2 Valid but unanswerable question

If the question is about recipes but no corpus evidence meets the relevance and
constraint gates, return HTTP `200` with:

```json
{
  "answer": "I couldn't find a recipe in the corpus that supports that request.",
  "citations": [],
  "refused": true,
  "refusal_reason": "out_of_corpus"
}
```

The exact wording may vary, but it MUST be polite, explain the limitation
without pretending to answer, and remain machine-detectable through the fields.

### 5.3 Out-of-domain question

Questions whose primary intent is not recipe/cooking information (for example,
weather, politics, programming, finance, or general medical advice) return
HTTP `200` with `refusal_reason: "out_of_domain"`, `refused: true` and no
citations. The response MUST politely say that this service answers questions
about recipes in its corpus.

### 5.4 Safety-sensitive question

Safety-sensitive questions take precedence over ordinary retrieval. They return
HTTP `200` with `refusal_reason: "safety"`, `refused: true` and no citations
unless a citation is needed only to identify the recipe; the default MVP
behaviour is an empty citation list. The response MUST NOT say that a recipe is
allergy-free or safe merely because a listed allergen was not found.

Examples:

- “Is this nut-free?” → safety refusal.
- “Can I eat this with a peanut allergy?” → safety refusal.
- “What nuts are explicitly listed in the ingredients?” → may be answered as a
bounded ingredient lookup, phrased as “the listed ingredients contain …”; it
MUST NOT be phrased as a safety certification.



### 5.5 Validation failure

The following are invalid requests and return the error event described in
§7.3 with HTTP `400`:

- invalid JSON or a missing `Content-Type: application/json`;
- a missing `question` property;
- `question` not being a string;
- an empty or whitespace-only question; or
- a question longer than 1,000 Unicode characters.

Unexpected request properties are rejected. Validation failures do not invoke
the retriever or model and do not return a business refusal reason.

### 5.6 Interaction model: stateless Q&A, not chat

The product currently supports a single-turn question-answer flow only:

1. The user enters one question and submits it.
2. The UI clears the previous result area immediately and shows loading for the
  new request.
3. The browser sends exactly one `POST /ask` request containing only that
   question.
4. When the response arrives, the UI renders only the current answer, its
  citations, refusal state/reason, or the current error.
5. The user may type and submit another question, which replaces the previous
  result in the UI.

There is no conversation transcript, message list, follow-up context or chat
history. The backend MUST NOT
depend on cookies, session state or previous requests to answer a question. If
requests overlap because of a network race, the UI MUST ignore a stale response
and keep the result for the most recently submitted question.

## 6. Domain and intent policy

The supported domain is factual information about recipes in the corpus:

- how to prepare a named recipe;
- ingredients, quantities, steps, timing, yield or equipment explicitly present
in a recipe;
- finding recipes by a requested ingredient, cuisine/category, diet or time;
- comparing or explaining differences between retrieved recipes; and
- a substitution or variation only when the source itself explicitly provides
it.

A recipe-shaped question about an absent recipe or unsupported attribute is
`out_of_corpus`, not `out_of_domain`. Safety-sensitive intent is classified as
`safety` before this distinction. Ambiguous questions must be answered only if
the retrieved evidence supports the interpretation; otherwise they are refused
as `out_of_corpus` with a suggestion to ask for a named recipe or explicit
constraint.

## 7. API contract



### 7.1 `POST /ask`

**Request headers**

```text
Content-Type: application/json
Accept: application/json
```

**Request body**

```json
{
  "question": "What's a vegetarian dinner I can make in under 30 minutes?"
}
```

The request object MUST contain exactly one property, `question`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AskRequest",
  "type": "object",
  "additionalProperties": false,
  "required": ["question"],
  "properties": {
    "question": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1000
    }
  }
}
```

The service MUST trim leading/trailing whitespace for processing but MUST
preserve the original question only in transient request context; it is not
required in the response. A string that becomes empty after trimming fails
validation even though it satisfies the schema's character-level `minLength`.

**Successful response:** HTTP `200`, `Content-Type: application/json`.

`POST /ask` is the task-compatible non-streaming endpoint. The client MUST send
exactly `Accept: application/json`, and the response MUST be one complete JSON
object conforming to the schema below. It returns the answer and the citations
as separate fields. The core `/ask` answer is plain text and citation links are
supplied through the `citations` array, which is mandatory for every
non-refused answer.

The following JSON Schema is normative for the complete response from
`POST /ask`. The optional streaming bonus reuses this response schema for its
final event; its additional contract is defined in the appendix.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AskResponse",
  "type": "object",
  "additionalProperties": false,
  "required": ["answer", "citations", "refused", "refusal_reason"],
  "properties": {
    "answer": {
      "type": "string",
      "minLength": 1,
      "description": "A grounded answer or a polite refusal message."
    },
    "citations": {
      "type": "array",
      "items": {"$ref": "#/$defs/Citation"},
      "description": "Only Wikibooks recipe sources retrieved for this request."
    },
    "refused": {
      "type": "boolean"
    },
    "refusal_reason": {
      "type": ["string", "null"],
      "enum": ["out_of_corpus", "out_of_domain", "safety", null]
    }
  },
  "$defs": {
    "Citation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["title", "url"],
      "properties": {
        "title": {"type": "string", "minLength": 1},
        "url": {"type": "string", "format": "uri", "minLength": 1}
      }
    }
  }
}
```

Schema validity is necessary but not sufficient. These cross-field invariants
are also normative:


| Case          | `answer`                        | `citations`     | `refused` | `refusal_reason` |
| ------------- | ------------------------------- | --------------- | --------- | ---------------- |
| Answer        | non-empty grounded string       | at least 1      | `false`   | `null`           |
| Out of corpus | polite non-empty refusal string | `[]`            | `true`    | `out_of_corpus`  |
| Out of domain | polite non-empty refusal string | `[]`            | `true`    | `out_of_domain`  |
| Safety        | polite non-empty refusal string | `[]` by default | `true`    | `safety`         |


Every response MUST contain a non-empty string in `answer`. A response with
`refused: false` MUST never have a non-null `refusal_reason`; a response with
`refused: true` MUST have one of the three refusal reasons. A successful answer
MUST have at least one citation, and every citation MUST be a source actually
retrieved for that request. Citation title and URL are server-side metadata,
not untrusted model output. The array MUST be ordered by the first appearance
of each distinct source in the validated claim ledger, not by random internal
ID.

### 7.2 `GET /health`

`GET /health` is a liveness/readiness endpoint and does not invoke the model.
It returns HTTP `200` only when the service process is live and the configured
corpus is loadable:

```json
{
  "status": "ok",
  "corpus_version": "<build identifier>"
}
```

If the process is live but the corpus is unavailable, it returns HTTP `503`:

```json
{
  "status": "degraded",
  "corpus_version": null
}
```



### 7.3 Error response contract

Non-business errors use a safe, machine-readable RFC 9457-style object. For
`POST /ask`, the object is returned as a JSON response body. Errors MUST NOT
expose stack traces, prompts, API keys, provider responses, or local paths.

```json
{
  "type": "urn:recipe-qa:problem:invalid-request",
  "title": "Invalid request",
  "status": 400,
  "detail": "question must be a non-empty string",
  "request_id": "<opaque correlation id>"
}
```

Required fields are `type` (string), `title` (string), `status` (integer),
`detail` (string), and `request_id` (string). Expected statuses are `400` for
validation (including a question over 1,000 characters), `406` when the
request does not use the endpoint's required `Accept` value, `413` only for a
separately enforced oversized HTTP body, `429` for rate limiting, and `503` for
an unavailable corpus/model dependency. A provider
timeout or internal failure MUST NOT be misrepresented as a confident recipe
answer or as an `out_of_corpus` refusal.

## 8. Retrieval, filtering and grounding requirements



### 8.1 Corpus requirements

The ingestion pipeline MUST:

- call the Wikibooks Cookbook through the MediaWiki API rather than scrape a
manually prepared list;
- select multiple categories, with variety in cuisine, dish type, overlapping
dishes and source structure;
- produce 40–60 unique recipe records after normalization;
- retain title, canonical URL, raw/source text and parsed ingredients/steps when
available; and
- rebuild the same corpus shape from the committed script and its pinned
configuration, without manually edited production data.

The exact category list and normalization rules MUST be configuration or
versioned source files, not hidden constants in request handling.

### 8.2 Retrieval evidence gate

For each valid question the service MUST perform the following in order:

1. classify safety-sensitive and out-of-domain intent;
2. extract named recipe, requested attributes and hard constraints;
3. retrieve candidate recipe records using the chosen documented retrieval
  method;
4. apply all hard filters before answer generation;
5. reject the request if no candidate satisfies the relevance and evidence
  gates; and
6. pass only the selected records/passages and their server-side source IDs to
  the answer generator.

Evidence is sufficient for an answer when all of the following hold:

- at least one retrieved record is relevant to the primary intent;
- every required hard constraint is supported by explicit source text or
conservatively derived metadata;
- every factual claim the answer intends to make has a supporting passage or
field in one of the selected records; and
- at least one selected record has a valid title and canonical URL.

For a comparison question, at least two relevant records are required when two
distinct recipes are available and requested. If only one source can be found,
the answer must say that the comparison is unavailable or refuse as
`out_of_corpus`; it must not invent a second alternative.

The implementation may use lexical, embedding or hybrid retrieval, but it MUST
document the method, threshold/calibration and filter order in an ADR. A
retrieval score alone is not evidence: a candidate also needs source content
that supports the requested fact. An empty or below-threshold result MUST never
be sent to the LLM.

### 8.3 Constraint semantics

Constraints are conjunctive: a recipe proposed for a question with multiple
hard constraints must satisfy all of them.


| Constraint          | Required behaviour                                                                                                                                                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Time                | Apply §4's strict/inclusive interpretation. Use explicit total time or conservative prep+cook sum. Missing/ambiguous time excludes the record from a hard time match.                                                                                                     |
| Diet                | Use a documented ingredient/source-text rule. For vegetarian, exclude explicit meat, fish, poultry, gelatin and non-vegetarian stock; for vegan, also exclude explicit animal-derived ingredients. Unknown/ambiguous ingredients exclude a recipe from a hard diet match. |
| Required ingredient | Match a normalized ingredient in the ingredient section or explicit recipe text. Synonym/inflection normalization must be versioned and tested.                                                                                                                           |
| Excluded ingredient | Exclude when the normalized ingredient or an unambiguous derivative is present. If the source is too ambiguous to prove absence, do not claim the recipe meets the exclusion.                                                                                             |
| Vague preference    | “Quick”, “easy” or “healthy” may affect ranking only if the corpus explicitly supports the attribute; they are not silently converted into unsupported numeric or medical claims.                                                                                         |


If filtering leaves no eligible recipe, the response is an
`out_of_corpus` refusal. The model is not allowed to relax a hard constraint.

### 8.4 Grounded answer generation

The generator MUST receive a prompt/instruction that identifies the selected
source records and prohibits outside knowledge. The internal output and its
deterministic validation rules are defined in
[`03_SPEC_APPENDIX.md`](03_SPEC_APPENDIX.md). The implementation MUST:

- validate the model's structured output before constructing the API response;
- restrict model-selected source IDs to the retrieved source IDs;
- map source IDs to title/URL on the server;
- reject or regenerate output containing unsupported claims, missing sources,
  malformed fields or invented citations; and
- return a refusal or an operational error according to §7.3 when validation
cannot succeed within the request timeout.

The API response does not expose model confidence as a substitute for evidence.
The prompt, model name/version, corpus version and retrieval result IDs must be
identifiable in structured logs for debugging, without logging secrets.

## 9. Edge-case policies

The following matrix is the normative edge-case handling policy. Every case
must have an automated test or golden-eval case when its behaviour is observable
through the API.


| Edge case                               | Detection                                                                                                                | Handling                                                                                                                                        | Expected result                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Empty question                          | Missing, empty or whitespace-only `question`                                                                             | Reject before retrieval/model invocation                                                                                                        | HTTP `400` validation error                                 |
| Malformed JSON or wrong type            | Invalid JSON, missing content type, non-object body, or non-string `question`                                            | Reject and return safe error details; do not echo the payload                                                                                   | HTTP `400`                                                  |
| Unexpected fields                       | Request contains anything except `question`                                                                              | Reject strict request schema                                                                                                                    | HTTP `400`                                                  |
| Oversized question/body                 | More than 1,000 Unicode characters or hosting body limit exceeded                                                        | Reject before LLM call                                                                                                                          | HTTP `400` for question length, or `413` for body limit     |
| Out-of-domain question                  | Primary intent is not recipe/cooking information                                                                         | Do not retrieve or call the answer generator; explain service boundary politely                                                                 | HTTP `200`, `refused=true`, `out_of_domain`                 |
| Recipe absent from corpus               | Recipe intent is valid but no relevant recipe record is retrieved                                                        | Refuse; do not use web search or model memory                                                                                                   | HTTP `200`, `refused=true`, `out_of_corpus`                 |
| Attribute absent from corpus            | Requested fact (for example nutrition) is not explicit in evidence                                                       | State that the corpus does not support the fact; do not estimate or infer                                                                       | HTTP `200`, `refused=true`, `out_of_corpus`                 |
| Vague recipe request                    | “What should I cook?” or similar without usable constraints                                                              | Return a recommendation only when a candidate is supportable; otherwise ask for a dish, ingredient or constraint                                | Answer with citation, or `out_of_corpus`                    |
| Ambiguous intent                        | Several interpretations are possible and evidence cannot disambiguate them                                               | Do not guess; give a bounded refusal/request for clarification                                                                                  | HTTP `200`, `out_of_corpus`                                 |
| Conflicting recipes for one dish        | Multiple source records disagree on ingredients, time or steps                                                           | For a generic singular query select one deterministic, stable source and attribute it; for comparison expose alternatives; never silently merge | Grounded answer with source attribution, or `out_of_corpus` |
| Duplicate/near-duplicate source pages   | Same recipe appears under multiple source records                                                                        | Deduplicate only using a documented ingestion rule; retain canonical source metadata                                                            | No duplicate citations; stable retrieval                    |
| Missing time metadata                   | Hard time constraint but no reliable total/prep+cook time                                                                | Exclude the record from the match; never claim it satisfies the time limit                                                                      | Answer from eligible records, or `out_of_corpus`            |
| Unknown diet suitability                | Ingredients or preparation are ambiguous for the requested diet                                                          | Exclude from hard diet matches; do not call it vegetarian/vegan by assumption                                                                   | Answer from certain matches, or `out_of_corpus`             |
| Processed/ready-made ingredient         | Recipe uses a paste, sauce, stock, seasoning blend or other prepared product whose full composition is not in the corpus | Do not infer hidden ingredients or diet/allergen status; advise checking the product label when relevant                                        | Grounded bounded answer, or `out_of_corpus`/`safety`        |
| Required ingredient not proven          | Ingredient appears only ambiguously or outside a reliable ingredient field                                               | Do not claim presence; exclude from constrained results                                                                                         | Answer from proven matches, or `out_of_corpus`              |
| Excluded ingredient ambiguous           | Cannot establish that an excluded ingredient/derivative is absent                                                        | Do not claim the exclusion is satisfied; exclude the record                                                                                     | Answer from eligible records, or `out_of_corpus`            |
| Allergy/safety certification            | “Is it nut-free?”, allergy, contamination, doneness, spoilage, pregnancy or medical-safety claim                         | Refuse conservatively; never certify safety from ingredient absence                                                                             | HTTP `200`, `refused=true`, `safety`                        |
| Bounded ingredient lookup               | User asks what is explicitly listed, without asking whether it is safe                                                   | Answer only the listed fact and add no safety conclusion                                                                                        | Grounded answer with citation, or `out_of_corpus`           |
| Prompt injection                        | User asks the model to ignore corpus, reveal prompts, or invent an answer                                                | Treat injection as untrusted question text; preserve retrieval, citation and refusal gates                                                      | Normal grounded answer/refusal                              |
| Unsupported language                    | Recipe intent cannot be reliably matched in the MVP's supported language                                                 | Do not guess or translate from model memory                                                                                                     | HTTP `200`, `out_of_corpus`                                 |
| No retrieval results after filters      | Candidates exist but none satisfy all hard constraints                                                                   | Refuse rather than relax constraints                                                                                                            | HTTP `200`, `out_of_corpus`                                 |
| Model returns invalid/ungrounded output | Malformed output, unsupported claim, unknown source ID or invented URL                                                   | Reject/regenerate within timeout; fail closed if unsuccessful                                                                                   | Safe refusal or HTTP `503`, never fabricated answer         |
| LLM timeout/provider failure            | Upstream call exceeds timeout or fails                                                                                   | Return operational error; do not label infrastructure failure as corpus refusal                                                                 | HTTP `503` error contract                                   |
| Corpus unavailable                      | Corpus cannot load or is inconsistent                                                                                    | Do not serve answers; expose degraded health state                                                                                              | `/health` HTTP `503`; `/ask` HTTP `503`                     |
| Rate limit exceeded                     | Per-IP/request budget exceeded                                                                                           | Reject temporarily and show retryable UI error                                                                                                  | HTTP `429`                                                  |
| Rapid UI resubmission                   | Multiple requests in flight from one page                                                                                | Disable submit while loading and ignore stale responses by request sequence                                                                     | Only latest submitted result remains visible                |
| Refresh/navigation                      | Browser page is reloaded or left                                                                                         | Do not restore a transcript or previous answer                                                                                                  | Fresh empty Q&A screen                                      |




### Empty, vague and malformed questions

- Missing, non-string, empty or whitespace-only input → HTTP `400`.
- Very long input over 1,000 Unicode characters → HTTP `400` or `413`.
- A vague but non-empty recipe request (“What should I cook?”) may return a
corpus-backed recommendation only if at least one candidate can be justified;
otherwise it returns `out_of_corpus` and asks for a dish, ingredient or
constraint.
- Prompt injection text inside a question is treated as user text, not as an
instruction. It cannot expand the source set or bypass safety/grounding rules.



### Absent recipes and absent attributes

“How do I make sushi?” is `out_of_corpus` if no retrieved sushi recipe exists.
“What is the nutritional value?” is `out_of_corpus` when nutrition is not
explicitly present, even if a model could estimate it. The service must not
turn a plausible estimate into a corpus fact.

### Conflicting or overlapping recipes

When sources for the same dish disagree, the service MUST preserve source
attribution. For a generic singular question, it MUST select one recipe using
the documented deterministic ranking and tie-break rule, without asking the
user to choose and without switching sources arbitrarily between identical
requests. The answer must make the selected source clear and MUST NOT imply
that its instructions are the only version. For an explicit comparison, it may
present each source's method/time/ingredient as an alternative, with citations
attached to the relevant statement. It MUST NOT average or merge contradictory
values. If the question asks for one definitive value and the conflict cannot
be represented clearly, refuse as `out_of_corpus` and explain that the corpus
contains conflicting recipes.

### Allergy and safety

The service is an information lookup over listed recipe text, not a safety
authority. It must refuse safety certification even when retrieval finds a
recipe. The UI must visibly distinguish a safety refusal from an ordinary
no-result refusal using the machine-readable reason.

## 10. Minimal UI requirements

The frontend MUST be implemented in TypeScript as one page and MUST:

- provide a question input and submit action;
- send one request to `/ask` with `Accept: application/json`;
- show loading state and prevent confusing duplicate submissions;
- call the configured public API URL without exposing any secret;
- render the completed answer and then the citations list below it, in the
order returned by the API;
- render refusal text and its refusal reason distinctly; and
- show a recoverable error state for HTTP `400`, `429`, `503` and network
failures.

The UI is intentionally not a chat interface. It MUST NOT render a growing
message history or send previous questions/answers with a new request. On
submit, the old answer, citations, refusal and error state are cleared from the
screen before the new request starts. Only the latest question's answer state
is displayed. Additional UI requirements are maintained in the appendix.

Appearance is not an acceptance criterion beyond readability and usable states.

## 11. Non-functional requirements



### Performance and cost targets

Targets are measured with a warm service, loaded corpus, normal network
conditions, and questions no longer than 1,000 characters:


| Metric                                            | Target                                                |
| ------------------------------------------------- | ----------------------------------------------------- |
| Validation/domain/no-result refusal (if have one) | p95 ≤ 10s                                             |
| Answerable request end-to-end latency             | p50 ≤ 20s; p95 ≤ 40s                                  |
| Hard request timeout                              | 2 min                                                 |
| Marginal cost per answerable question             | ≤ USD 0.05 average                                    |
| Marginal cost for 1,000 questions                 | ≤ USD 50 average                                      |
| Contract correctness on automated tests           | 100%                                                  |
| Citation source validity on golden eval           | 100%                                                  |


The cost calculation must state token/request volume and model prices used. A
change in model, prompt size, retrieval method or traffic mix invalidates the
estimate and requires recalculation in the README. Ingestion and fixed hosting
costs are reported separately.

### Reliability and operability

- The service SHOULD achieve at least 99% monthly availability during the
evaluation period, excluding planned deployment windows and provider-wide
outages.
- Every request receives an opaque correlation/request ID, returned in error
responses and included in logs.
- Logs include request ID, endpoint, status, latency, corpus version, retrieval
method/version, candidate and selected record IDs, selection policy/version,
model/version, public refusal reason, internal refusal subreason and error
class. Do not log
API keys, prompts containing secrets, full provider credentials, raw citation
mappings or raw sensitive user data by default.
- `/health` must be usable by the hosting platform for readiness/liveness.
- Timeouts must exist for upstream model/API calls; errors must fail closed.
- Deployment configuration, dependency versions and corpus build configuration
  must be committed. Secrets are supplied only through environment/secret
  management.
- Deployment must be safe to repeat: applying the same committed configuration
  twice must not duplicate or corrupt the service.
- CI SHOULD run formatting, linting, type checks, automated tests, dependency
  and secret scans, and applicable static/container security checks. Agent-
  assisted review MAY provide additional quality and security findings, but it
  is advisory and MUST NOT be the sole security gate.



## 12. Testing and evaluation contract



### Automated tests

The test suite MUST cover deterministic logic without requiring an LLM for:

- MediaWiki response parsing, normalization and corpus count/uniqueness;
- retrieval relevance and no-result behaviour;
- time, diet and required/excluded ingredient filters;
- citation allow-listing and response invariants;
- request validation and HTTP status handling; and
- empty, out-of-domain, out-of-corpus, conflicting-source and safety paths.

At least one functional area MUST show test-first development in the commit
history: tests committed before its implementation. Tests must be runnable from
a clean checkout with one documented command.

### Golden eval

The repository MUST contain 12–15 golden questions and an automated runner
invoked by:

```text
python -m evals.run
```

Each case MUST define:

- the question;
- expected answer/refusal state and, for refusals, expected reason;
- expected recipe/source IDs or titles;
- expected time/diet/ingredient constraint behaviour; and
- a human-readable case category.

The runner MUST validate every returned JSON response against the response
schema, verify refusal correctness, verify citations belong to expected/retrieved
sources, and report pass/fail with enough context to diagnose a failure. The
set MUST include at least: direct recipe, ingredient lookup, time constraint,
diet constraint, combined constraints, overlapping/conflicting recipes,
out-of-corpus, out-of-domain, safety/allergy, absent attribute, vague question
and empty-input handling.

## 13. Acceptance criteria

The implementation is accepted only when all P0 criteria below pass. A criterion
is not satisfied by manual inspection alone when an automated check is specified.


| ID    | Acceptance criterion                                                                                                                                                                                                                                                                                                                 | Verification                                      |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| AC-01 | A reproducible MediaWiki ingestion script builds 40–60 unique Wikibooks recipe records from multiple categories.                                                                                                                                                                                                                     | Clean rebuild and corpus validation               |
| AC-02 | Corpus includes cuisine/dish variety, overlapping dishes and different source structures; title and canonical URL are retained.                                                                                                                                                                                                      | Corpus review plus fixture test                   |
| AC-03 | Valid `POST /ask` requests return HTTP `200`, JSON and exactly the documented response fields/types.                                                                                                                                                                                                                                 | API contract test                                 |
| AC-04 | Every non-refused answer is grounded in retrieved evidence, has at least one valid citation, and never has a model-invented URL.                                                                                                                                                                                                     | Retrieval/answer integration test and golden eval |
| AC-05 | No candidate/evidence means `refused=true`, `refusal_reason=out_of_corpus`, polite answer text and empty citations.                                                                                                                                                                                                                  | No-result golden cases                            |
| AC-06 | Non-recipe intent returns `out_of_domain` and is not sent to answer generation.                                                                                                                                                                                                                                                      | Domain/refusal tests                              |
| AC-07 | Allergy/safety certification questions return `safety` and never make an unsupported safety claim.                                                                                                                                                                                                                                   | Safety golden cases                               |
| AC-08 | Empty, missing, wrong-type and oversized questions return the documented validation error and do not invoke retrieval/LLM.                                                                                                                                                                                                           | Request-validation tests                          |
| AC-09 | Strict/inclusive time semantics, diet rules and required/excluded ingredient constraints are obeyed, including combined constraints.                                                                                                                                                                                                 | Deterministic filter tests and golden eval        |
| AC-10 | Conflicting recipes are attributed separately or refused; the service never silently merges contradictory values.                                                                                                                                                                                                                    | Conflict fixture/eval                             |
| AC-11 | Model output is schema-validated, source IDs are allow-listed, and provider/LLM failures fail closed without a fabricated answer.                                                                                                                                                                                                    | Generator and failure-path tests                  |
| AC-12 | TypeScript one-page UI accepts a question and displays loading, answer, citations, refusal reason and errors.                                                                                                                                                                                                                        | Build plus manual/E2E smoke test                  |
| AC-13 | Automated tests cover ingestion, retrieval, filters and API contract; the golden runner has 12–15 cases and produces a diagnostic report.                                                                                                                                                                                            | Test/eval run                                     |
| AC-14 | Docker/local startup, public UI and public API are documented; deployment configuration is committed, reproducible and repeatable.                                                                                                                                                                                                   | Clean deployment and external smoke tests         |
| AC-15 | Secrets are environment-managed, HTTPS is used publicly, request limits/timeouts exist, and logs expose enough correlation/retrieval/model metadata to investigate a bad answer without secrets.                                                                                                                                     | Configuration/security/operations review          |
| AC-16 | README documents provider choice, deployment and container access, model/cost/latency assumptions, current bottleneck, next optimization, production gaps and AI usage notes.                                                                                                                                                        | Documentation review                              |
| AC-17 | Git history shows specification before implementation, granular logical commits, and tests before implementation for at least one area.                                                                                                                                                                                              | Git history review                                |
| AC-18 | Measured warm-service latency and marginal cost are reported against the targets in §11; any gap is explicitly documented with a remediation plan.                                                                                                                                                                                   | Load/benchmark run and README review              |
| AC-19 | Every business refusal is logged with a public reason and an allowed internal subreason; validation and operational failures are not mislabeled as refusals.                                                                                                                                                                         | Structured-log test                               |
| AC-20 | For a generic singular question matching multiple recipes for one dish, selection uses the lowest stable recipe ID after relevance and hard-constraint filtering, and is repeatable.                                                                                                                                               | Deterministic selection test and ADR review       |




## 14. Traceability to source documents


| Source requirement                                                 | This specification       |
| ------------------------------------------------------------------ | ------------------------ |
| `00_TASK.md`: corpus-only answers and citations                    | §§1, 3, 5.1, 8.2, 8.4    |
| `00_TASK.md`: `POST /ask` minimum contract                         | §7.1                     |
| `00_TASK.md`: constraints and safety                               | §§5.4, 8.3, 9            |
| `00_TASK.md`: reproducible 40–60 recipe corpus                     | §8.1                     |
| `00_TASK.md`: TypeScript one-page UI                               | §10                      |
| `00_TASK.md`: deployment and operations                            | §11 and AC-14–15         |
| `00_TASK.md`: ADRs, tests, eval and README                         | §§11–13 and AC-13, AC-16 |
| `01_PLAN.md`: specification before code and vertical slice         | §§1, 7, 12, AC-17        |
| `01_PLAN.md`: test-first deterministic logic                       | §12 and AC-13, AC-17     |
| `02_CHECKLIST.md`: empty/out-of-domain/conflict/allergy edge cases | §§5, 6, 9                |
| `02_CHECKLIST.md`: latency/cost and no hidden behaviour            | §§4, 8, 11               |
| `02_CHECKLIST.md`: deployment, observability and AI workflow       | §§11, 13 and AC-14–17    |




## 15. Implementation freedom and change control

The following are intentionally implementation decisions for ADRs rather than
requirements of this document: lexical versus embedding versus hybrid
retrieval; chunking layout; LLM provider/model; cache design; frontend/build
framework; and hosting provider. Whichever option is selected must preserve all
observable rules above and document alternatives, criteria, trade-offs with
cost/latency estimates, and invalidation conditions in 2–3 ADRs.

Any change to response fields, refusal semantics, constraint interpretation,
safety policy, evidence gates, latency/cost targets or acceptance criteria is a
specification change. It must be made before implementation/eval updates, with
the affected golden cases and tests updated together.
