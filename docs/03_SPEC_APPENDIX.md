# Recipe Q&A Service — Grounded Generation Appendix

**Status:** Normative implementation appendix for the core `/ask` pipeline  
**Parent specification:** [`03_SPEC.md`](03_SPEC.md)

This appendix makes the grounding requirement operational. The model may
compose natural-language prose, but it may not introduce a factual claim that
has no attached evidence from the records selected by retrieval.

## 1. Internal generator contract

The answer generator receives only the selected recipe records/passages. Each
evidence block has a server-owned `source_id` and an exact source passage:

```text
[source_id=recipe-001]
Goulash takes 20 minutes to prepare and 60 minutes to cook.
[/source_id]
```

The generator returns an internal JSON object. This object is never returned
directly to the client:

```json
{
  "answer": "Goulash takes 20 minutes to prepare and 60 minutes to cook.",
  "claims": [
    {
      "text": "Goulash takes 20 minutes to prepare and 60 minutes to cook.",
      "source_id": "recipe-001",
      "evidence_quote": "Goulash takes 20 minutes to prepare and 60 minutes to cook."
    }
  ]
}
```

The internal schema MUST use `additionalProperties: false`. `answer` and every
claim `text` and `evidence_quote` MUST be non-empty strings. `source_id` MUST
be a string from the current request's retrieved-source allow-list. The model
MUST NOT return citation titles, URLs, HTML, Markdown links, or hidden/internal
fields as a substitute for `source_id`.

## 2. Deterministic validation

Before constructing the public `AskResponse`, the server MUST:

1. parse the model output as JSON and validate the internal schema;
2. reject every `source_id` that is not in the retrieved-source allow-list;
3. normalize whitespace only for comparison and verify that each
   `evidence_quote` is an exact contiguous substring of the supplied passage
   for that `source_id`;
4. verify that every factual answer sentence has a corresponding claim record;
5. verify that every claim `text` is an exact substring of `answer` after the
   same whitespace normalization, and that every source exposed in public
   `citations` is used by at least one claim; and
6. discard all model-provided citation metadata and map source IDs to title and
   canonical URL from the server-side corpus.

The core `/ask` response MUST contain plain answer text and a server-generated
ordered `citations` array. The model cannot add a URL or choose a citation
outside the retrieved set.

Exact substring validation proves that a claim is tied to supplied source
text; it does not prove full semantic entailment. Semantic quality is therefore
verified by deterministic fixtures, the golden eval and human review of the
small golden set. This limitation is explicit rather than hidden behind a
confidence score.

## 3. Failure policy

If parsing, schema validation, allow-listing, evidence matching or claim
coverage fails, the server may retry generation once with the same evidence and
a corrective instruction. If validation still fails, it MUST fail closed with
the operational error contract (`HTTP 503`) and MUST NOT return a fabricated
answer or relabel the failure as `out_of_corpus`.

The server MUST log the request ID, corpus version, retrieved/selected source
IDs, validator failure class and retry outcome. It MUST NOT log prompts that
contain secrets, raw credentials or the full user payload by default.

## 4. Relationship to the optional streaming bonus

The optional `/ask/stream` implementation reuses this same validated internal
draft. Its citation-marker parser may transform only allow-listed source IDs
into trusted title/URL events. Streaming does not weaken the evidence or
failure rules of the core `/ask` endpoint.

## 5. Optional streaming feature

This entire section is optional. It is implemented only after the core `/ask`,
UI, tests, evaluation and deployment are complete.

### 5.1 Endpoint and event model

`POST /ask/stream` accepts the same request body as `/ask` and requires
`Accept: text/event-stream`. It returns UTF-8 Server-Sent Events. The response
uses this lifecycle:

```text
start → zero or more text/citation events → exactly one done
```

An operational failure after the stream starts uses `error` instead of `done`:

```text
start → zero or more text/citation events → exactly one error
```

The only public event names are:

| Event | Payload | Meaning |
| --- | --- | --- |
| `start` | `{"request_id":"string"}` | Exactly once and first. |
| `text` | `{"text":"non-empty string"}` | Answer text fragment. |
| `citation` | `{"title":"string","url":"URI"}` | Trusted inline citation at the current answer position. |
| `done` | Core `AskResponse` | Final answer/refusal and ordered citations. |
| `error` | Core problem response | Post-start operational failure. |

The stream MUST NOT expose provider event names, raw provider objects, internal
markers, model URLs, model HTML, prompts, hidden source IDs or internal refusal
subreasons. A refusal may emit text followed by `done` with the core refusal
fields and an empty citations array. The final `citations` list is ordered by
first appearance of distinct sources in the stream.

### 5.2 Internal citation markers

The server assigns each selected source a request-scoped, collision-checked
five-digit ID and keeps a private mapping to trusted title/URL metadata. The
model may emit only an allow-listed marker in this format:

```text
⟦12345⟧
```

The marker is seven Unicode characters. The parser works across provider chunk
boundaries and keeps at most seven Unicode characters of lookahead after a
possible opening delimiter. A valid marker is consumed and becomes a trusted
`citation` event; it is never shown literally. Invalid, malformed or unknown
markers invalidate the stream and produce a generic recoverable error. The
parser MUST never construct a URL from model output.

The final `done.answer` may contain server-generated Markdown links in the
form `[Title](trusted-url)`, but the UI renders them as clean clickable title
links rather than literal Markdown. The citation URL always comes from the
same trusted corpus record as the final citations list.

### 5.3 Bonus UI requirements

The optional UI mode adds a clearly labelled toggle with `Standard JSON` and
`Streaming inline citations`. The toggle does not send a request and is
disabled while a request is in flight. Standard mode calls `/ask`; streaming
mode calls `/ask/stream`. Streaming renders text incrementally, displays
trusted inline title links and then the ordered citations list. Raw markers,
raw model URLs, HTML and Markdown syntax MUST NOT be visible to the user.

### 5.4 Bonus evaluation and tests

If the feature is implemented, the eval runner and automated tests MUST cover
event names, payloads, lifecycle and terminal events; marker parsing split
across chunks; seven-character lookahead; trusted links; final citation order;
and operational errors. These checks are additional to the core `/ask` eval.

### 5.5 Bonus checklist

The following former checklist items belong to this appendix and are not core
acceptance criteria:

| IDs | Bonus requirement | Verification |
| --- | --- | --- |
| BONUS-01, BONUS-02 | Streaming SSE contract, trusted inline citations, marker parsing and seven-character lookahead. | API/SSE/parser/UI integration tests |
| API-12–API-26 | Streaming endpoint, SSE headers/events/lifecycle, trusted citations and marker parser. | HTTP/SSE/parser/security tests |
| UI-10, UI-12, UI-14, UI-15 | Optional mode toggle, endpoint routing, inline links and request locking. | UI integration/E2E tests |
| SPEC-15–SPEC-18 | Bonus event contract, marker allow-list/lookahead, links and shared pipeline documented. | Documentation review |
| EVAL-12–EVAL-14 | Streaming event, final response and citation-order evaluation. | Eval runner |
| TEST-09–TEST-11 | SSE lifecycle, parser and trusted-link tests. | Automated tests |
| OPS-05–OPS-06 | Stream protocol/parser logging and stream-specific operational errors. | Logs/API review |

Bonus details are intentionally kept here so the core specification remains
focused on the mandatory take-home requirements.
