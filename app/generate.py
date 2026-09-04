"""Generation stage — grounded answer / refusal (ADR-002, SPEC §7.1/§7.3/§8.2).

`gpt-5.6-luna` at `reasoning_effort="medium"` with Structured Outputs.
Code enforces the evidence gate: every citation quote must appear verbatim
(whitespace-collapsed) in the cited record's ``source_text``; unknown
pageids are dropped. An answer left without valid citations is retried
once and then demoted to an honest ``out_of_corpus`` refusal — the model
never gets the last word on its own evidence.

Failure mapping (§7.3): malformed model outputs or invalid refusal reasons
are retried once, then ``GenerationError`` — upstream converts it to the
503 problem path, because an infrastructure failure must never be
misrepresented as a confident 200 refusal. Provider/network errors
propagate.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas import AskResponse, Citation

MAX_ATTEMPTS = 2
PROMPT_VERSION = "generate-v5"

_SYSTEM_PROMPT = (
    "You answer cooking questions using ONLY the provided recipe records. "
    "The provided records are already hard-filtered and ranked by the server. "
    "Use all relevant records in the context; for a request asking for all "
    "matching dishes, include every matching record rather than selecting "
    "only the first one. "
    "Cite supporting records using their markers "
    "⟦pageid⟧, and list every cited pageid in the citations array with the "
    "exact quote from that record's source_text supporting the claim. "
    "Use each source record marker at most once in the answer: place it after "
    "the last sentence or paragraph supported by that article, never repeat "
    "the same marker after every step or factual sentence. "
    "Every citations.quote must be copied as one contiguous substring from "
    "the matching source_text, including its original wording; do not write "
    "a paraphrase as a quote. "
    "If the records do not contain the answer, refuse with refusal_reason "
    "out_of_corpus. If the question is not about food/cooking/recipes, refuse "
    "with out_of_domain. Never invent facts, URLs, times, or ingredients. "
    "If the user explicitly asks for a field that is absent from the records "
    "(e.g. rating, awards or Michelin stars), refuse with out_of_corpus rather "
    "than guessing or answering a nearby question. A recipe title alone is not "
    "evidence for an attribute that is not present in the supplied source_text."
)


class GenerationCitation(BaseModel):
    """A model-proposed citation: record + supporting verbatim quote."""

    model_config = ConfigDict(extra="forbid")
    pageid: int
    quote: str = Field(min_length=1)


class GenerationOutput(BaseModel):
    """Strict schema for the generation call (response_model)."""

    model_config = ConfigDict(extra="forbid")
    kind: str  # validated below: "answer" | "refusal"
    answer: str = Field(min_length=1)
    refusal_reason: str | None = None
    refusal_subreason: str = ""
    citations: list[GenerationCitation] = Field(default_factory=list)


VALID_REFUSALS = {"out_of_corpus", "out_of_domain", "safety"}
_PUBLIC_MARKER_RE = re.compile(r"⟦[^⟧]*⟧")
_MARKER_RE = re.compile(r"⟦(\d+)⟧")


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _public_answer(answer: str) -> str:
    """Remove request-scoped citation markers from the public answer text."""
    return _PUBLIC_MARKER_RE.sub("", answer).strip()


def _inline_answer(answer: str, citations: dict[int, Citation]) -> str:
    """Keep citation positions and turn model markers into safe Markdown links."""
    linked: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        pageid = int(match.group(1))
        citation = citations.get(pageid)
        if citation is None:
            return ""
        if pageid in linked:
            return ""
        linked.add(pageid)
        return f"[{citation.title}]({citation.url})"

    return _MARKER_RE.sub(replace, answer).strip()


def build_messages(question: str, records: list[dict],
                   error_hint: str | None = None) -> list[dict]:
    record_blocks = []
    for r in records:
        record_blocks.append(
            f"⟦{r['pageid']}⟧ {r['title']}\n"
            f"cuisine={r.get('cuisine')} dish_type={r.get('dish_type')} "
            f"time_minutes={r.get('time_minutes')} servings={r.get('servings')} "
            f"diet_tags={r.get('diet_tags')}\n"
            f"source_text:\n{r.get('source_text') or ''}"
        )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "Recipe records:\n\n" + "\n\n".join(record_blocks)},
        {"role": "user", "content": f"Question: {question}"},
    ]
    if error_hint:
        messages.append({
            "role": "user",
            "content": f"Your previous response was rejected: {error_hint}. "
                       "Return a corrected response in the same JSON format. "
                       "Copy a short, contiguous quote exactly from source_text "
                       "and use each source marker at most once.",
        })
    return messages


class GenerationError(Exception):
    """The model could not produce a contract-valid output after retries."""


def _citation_order(answer: str, citations: list[GenerationCitation]) -> list[int]:
    """Order kept pageids by first appearance of their quote in the answer.

    Quotes the answer paraphrases (not found verbatim) order last, stable
    by pageid — they are still valid citations (verified against the
    source), just not positionable in the claim ledger."""
    answer_ws = _ws(answer)
    first_pos: dict[int, int] = {}
    for c in citations:
        pos = answer_ws.find(_ws(c.quote))
        if c.pageid not in first_pos and pos >= 0:
            first_pos[c.pageid] = pos
    default = len(answer_ws) + 1
    return sorted({c.pageid for c in citations},
                  key=lambda pid: (first_pos.get(pid, default), pid))


def _to_response(out: GenerationOutput, records: list[dict], inline_links: bool = False) -> AskResponse | None:
    """Validate + convert a model output; None means contract-invalid (retry)."""
    by_pageid = {r["pageid"]: r for r in records}

    if out.kind == "refusal":
        if out.refusal_reason not in VALID_REFUSALS:
            return None  # invalid enum -> retry
        answer = _public_answer(out.answer)
        if not answer:
            return None
        return AskResponse(
            answer=answer, citations=[], refused=True,
            refusal_reason=out.refusal_reason,
        )

    if out.kind != "answer":
        return None

    # Evidence gate: keep only citations whose quote is verbatim in the
    # cited record's source_text.
    kept = []
    for c in out.citations:
        rec = by_pageid.get(c.pageid)
        if rec is None:
            continue
        source = _ws(rec.get("source_text") or "")
        if _ws(c.quote) in source:
            kept.append(c)
    if not kept:
        return "demote"  # answer without evidence -> retry, then refusal

    ordered = _citation_order(out.answer, kept)
    seen: set[int] = set()
    citations = [
        Citation(title=by_pageid[pid]["title"], url=by_pageid[pid]["source_url"])
        for pid in ordered if not (pid in seen or seen.add(pid))
    ]
    citation_by_pageid = {
        pid: Citation(title=by_pageid[pid]["title"], url=by_pageid[pid]["source_url"])
        for pid in ordered if pid in by_pageid
    }
    answer = _inline_answer(out.answer, citation_by_pageid) if inline_links else _public_answer(out.answer)
    if not answer:
        return None
    return AskResponse(
        answer=answer,
        citations=citations,
        refused=False,
        refusal_reason=None,
    )


def generate(
    question: str,
    records: list[dict],
    client: Any | None = None,
    inline_links: bool = False,
) -> AskResponse:
    """Produce the final §7.1 response from the retrieved records."""
    if client is None:
        from openai import OpenAI

        from app.settings import get_settings

        settings = get_settings()
        client = OpenAI(api_key=settings.openai_api_key or None)

    error_hint: str | None = None
    demote = False
    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.chat.completions.parse(
                model="gpt-5.6-luna",
                messages=build_messages(question, records, error_hint),
                response_format=GenerationOutput,
                reasoning_effort="medium",
            )
            out = GenerationOutput.model_validate(response.choices[0].message.parsed)
        except ValidationError as exc:
            error_hint = f"schema violation: {exc.errors()[0].get('msg')}"
            continue

        result = _to_response(out, records, inline_links=inline_links)
        if result == "demote":
            demote = True
            error_hint = "no citation survived the verbatim evidence check"
            continue
        if result is None:
            error_hint = "invalid kind or refusal_reason"
            continue
        return result

    if demote:
        # Evidence gate, final answer: honest refusal instead of unsupported
        # claims (SPEC §7.3 — must not misrepresent failure as confidence).
        return AskResponse(
            answer="I could not verify an answer against the recipe sources "
                   "for this question, so I won't guess. Try rephrasing or "
                   "asking about a recipe that exists in the cookbook.",
            citations=[], refused=True, refusal_reason="out_of_corpus",
        )
    raise GenerationError("generation failed after retries with invalid outputs")
