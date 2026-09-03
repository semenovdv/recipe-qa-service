"""LLM enrichment of corpus records via GPT Luna Low + Structured Outputs.

Produces ``dataset/enriched/`` — a **derived layer** on top of the
deterministic Wikibooks corpus (``dataset/corpus/``), which stays untouched:

- CORP-09/10/11 (script-only reproducibility) keep holding: the base corpus
  is still rebuilt by ``python -m dataset.ingest build`` alone.
- Spec §4.6 (missing/ambiguous time is never guessed) is enforced **in code**,
  not just in the prompt: any LLM-provided ``time_minutes`` is only kept when
  the record's deterministic parser could have produced it from an unambiguous
  recipesummary value; otherwise it is dropped back to ``null``.
- Every filled field carries a provenance entry: ``extracted`` (verbatim quote
  from source_text), ``inferred`` (tagged model inference, harmless fields
  only), or ``source_record`` (value already known deterministically).

CLI:
    python -m dataset.enrich plan          # show which fields would be filled, no API calls
    python -m dataset.enrich run           # enrich all records -> enriched/
    python -m dataset.enrich run --record 4991
    python -m dataset.enrich validate      # contract-check the enriched layer
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from dataset.parsing import parse_time_minutes

CORPUS_DIR = Path(__file__).parent / "corpus"
ENRICHED_DIR = Path(__file__).parent / "enriched"
CONFIG_PATH = Path(__file__).parent / "enrich_config.json"

# Model + API settings (overridable via enrich_config.json)
DEFAULT_MODEL = "gpt-luna-low"
DEFAULT_TEMPERATURE = 0.0
MAX_OUTPUT_TOKENS = 1200
REQUEST_DELAY_SECONDS = 0.3  # politeness between calls
MAX_RETRIES = 3

SCHEMA_VERSION = 1

# Typed alias for an enriched record (kept as a plain dict for JSON round-trips).
EnrichedRecord = dict[str, Any]

# Fields whose provenance may be "inferred" (harmless, tagged, non-constraint).
# time_minutes is NOT on this list: provenance for time is extracted-or-dropped.
INFERRABLE_FIELDS = {"cuisine", "dish_type", "diet_tags"}

# The three provenance sources (validate_enriched enforces this enum)
PROVENANCE_SOURCES = {"extracted", "inferred", "source_record", "dropped", "absent"}

ENRICHMENT_SYSTEM_PROMPT = """You are a data curator for a recipe corpus. You receive one recipe \
record (title, wikitext excerpts, already-parsed fields) from Wikibooks Cookbook and must return \
a strict JSON object with the requested fields.

Rules:
- NEVER invent facts. If a value is not present in the provided text, return null.
- time_minutes: only fill it if the record's summary/time text states a single unambiguous total \
(e.g. "45 minutes", "1 hour 15 minutes"). Ranges ("30-60 minutes"), multi-phase totals \
("30 minutes + 24 hours"), unit-less numbers and prose like "varies" MUST yield null.
- servings: copy the summary servings text verbatim if present; otherwise null.
- cuisine / dish_type: the culinary tradition and dish category, using only hints from the text \
(category links, title, description). If unsure, null.
- diet_tags: lowercase tags from this set only: vegetarian, vegan, gluten-free, dairy-free, \
halal, kosher. Only if supported by the text; otherwise [].
- ingredients_normalized: clean ingredient names (no quantities, no markup), same order as given.
- For every field you filled, provide a *_evidence sibling: a VERBATIM quote (<= 200 chars) \
from the provided text supporting the value, or null when you could not fill the field.
Return JSON only."""

# ---------------------------------------------------------------------------
# Evidence windows: exact, bounded slices of source_text per field
# ---------------------------------------------------------------------------


def _summary_window(source_text: str, field_hint: str, limit: int = 400) -> str:
    """Bounded slice of the recipesummary template around a field hint."""
    match = re.search(r"\{\{\s*recipe[\s_-]*summary\s*\|.*?\}\}", source_text,
                      re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    body = match.group(0)
    idx = body.find(field_hint)
    if idx == -1:
        return body[:limit]
    start = max(0, idx - 40)
    return body[start:idx + limit]


def _ingredients_window(source_text: str, limit: int = 1600) -> str:
    """Window includes the heading itself so quotes stay unambiguous."""
    match = re.search(r"==+\s*Ingredients\s*==+.*?(?=={2,}|\Z)",
                      source_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group(0)[:limit]


def _metadata_window(source_text: str, limit: int = 900) -> str:
    """Category links + first prose paragraph: the hints for cuisine/dish_type/diet."""
    categories = "\n".join(sorted(
        m.group(0) for m in
        re.finditer(r"\[\[\s*Category\s*:[^\]]+\]\]", source_text, re.IGNORECASE)
    ))[:limit // 2]
    prose_match = re.search(r"^(.*?)(?=={2,})", source_text, re.DOTALL)
    prose = prose_match.group(1)[:limit // 2] if prose_match else ""
    return f"{prose}\n{categories}".strip()


def derived_fields(record: dict[str, Any]) -> list[dict[str, str]]:
    """Exact text windows per field, sent to the model as bounded evidence."""
    source = record.get("source_text", "")
    return [
        {
            "name": "time_minutes",
            "source_text_window": _summary_window(source, "time"),
        },
        {
            "name": "servings",
            "source_text_window": _summary_window(source, "servings"),
        },
        {
            "name": "ingredients_normalized",
            "source_text_window": _ingredients_window(source),
        },
        {
            "name": "cuisine",
            "source_text_window": _metadata_window(source),
        },
        {
            "name": "dish_type",
            "source_text_window": _metadata_window(source),
        },
        {
            "name": "diet_tags",
            "source_text_window": _metadata_window(source),
        },
    ]


# ---------------------------------------------------------------------------
# JSON schema for Structured Outputs (strict mode)
# ---------------------------------------------------------------------------

def _str_field(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


def response_schema() -> dict[str, Any]:
    """Strict JSON schema for the OpenAI Structured Outputs response_format."""
    props: dict[str, Any] = {
        "ingredients_normalized": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Clean ingredient names, no quantities, no markup.",
        },
        "cuisine": _str_field("Culinary tradition (e.g. Indian, Italian) or null."),
        "dish_type": _str_field("Dish category (e.g. soup, dessert, side dish) or null."),
        "diet_tags": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "vegetarian", "vegan", "gluten-free", "dairy-free", "halal", "kosher",
            ]},
            "description": "Diet tags supported by the text; [] when none.",
        },
        "time_minutes": {
            "type": ["integer", "null"],
            "description": "Single unambiguous total minutes from summary, else null.",
        },
        "servings": _str_field("Servings text verbatim from summary, else null."),
        "time_evidence": _str_field("Verbatim quote for time_minutes, or null."),
        "servings_evidence": _str_field("Verbatim quote for servings, or null."),
        "notes": _str_field("Optional short note about ambiguity, else null."),
    }
    return {
        "name": "recipe_enrichment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": props,
            "required": list(props.keys()),
            "additionalProperties": False,
        },
    }


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def build_messages(
    record: dict[str, Any], fields: list[dict[str, str]]
) -> list[dict[str, str]]:
    """System + user message pair for one record."""
    user_payload = {
        "title": record["title"],
        "url": record["url"],
        "known_summary": {
            "time_minutes": record["summary"].get("time_minutes"),
            "servings": record["summary"].get("servings"),
            "rating": record["summary"].get("rating"),
        },
        "known_ingredients": record["ingredients"],
        "evidence_windows": fields,
        "instructions": (
            "Fill the schema fields using ONLY the evidence windows. "
            "known_summary values are already trusted: keep them, do not contradict them. "
            "If a value cannot be supported by the evidence, use null (or [] for diet_tags)."
        ),
    }
    return [
        {"role": "system", "content": ENRICHMENT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


# ---------------------------------------------------------------------------
# Post-processing: coercion + provenance + time guard (all in code)
# ---------------------------------------------------------------------------


def coerce_llm_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw structured response into the expected shape. Never raises."""
    out: dict[str, Any] = {
        "ingredients_normalized": payload.get("ingredients_normalized"),
        "cuisine": payload.get("cuisine"),
        "dish_type": payload.get("dish_type"),
        "diet_tags": payload.get("diet_tags", []),
        "time_minutes": payload.get("time_minutes"),
        "servings": payload.get("servings"),
        "time_evidence": payload.get("time_evidence"),
        "servings_evidence": payload.get("servings_evidence"),
        "notes": payload.get("notes"),
    }
    if not isinstance(out["ingredients_normalized"], list):
        out["ingredients_normalized"] = None
    if not isinstance(out["diet_tags"], list):
        out["diet_tags"] = []
    else:
        out["diet_tags"] = [str(tag).lower() for tag in out["diet_tags"]]
    # time must be a positive int or None
    tm = out["time_minutes"]
    if isinstance(tm, bool) or not isinstance(tm, int) or tm <= 0:
        out["time_minutes"] = None
    if out["servings"] is not None:
        out["servings"] = str(out["servings"])
    return out


def file_slug(title: str) -> str:
    """Deterministic filename for an enriched record."""
    text = title.removeprefix("Cookbook:").strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "_", text).strip("_").lower()


def _window_supports(value: str, window: str) -> bool:
    """Loose containment check: the value must appear in the window."""
    if not value or not window:
        return False
    return value.strip().lower() in window.lower()


def _matched_quote(value: str, window: str) -> str | None:
    """Return the actual verbatim substring of the window matching value."""
    if not value or not window:
        return None
    needle = value.strip().lower()
    idx = window.lower().find(needle)
    if idx == -1:
        return None
    return window[idx:idx + len(value.strip())]


def _time_guard(record: dict[str, Any], payload: dict[str, Any]) -> tuple[str, Any]:
    """Spec §4.6 enforcement in code.

    Returns (provenance_source, final_time_minutes).
    """
    source_time = record["summary"].get("time_minutes")
    if source_time is not None:
        return "source_record", source_time

    llm_time = payload.get("time_minutes")
    if llm_time is None:
        return "absent", None

    evidence = payload.get("time_evidence") or ""
    time_window = next(
        (f["source_text_window"] for f in _time_field_windows(record)), ""
    )

    # The quote must actually support the value: parse the quote deterministically
    # and require it to yield exactly the LLM's number.
    quoted_total = parse_time_minutes(evidence)
    if quoted_total is None or quoted_total != llm_time:
        return "dropped", None
    # The quoted text must come from the actual source window
    if not _window_supports(evidence, time_window):
        return "dropped", None
    return "extracted", llm_time


def _time_field_windows(record: dict[str, Any]) -> list[dict[str, str]]:
    return [f for f in derived_fields(record) if f["name"] == "time_minutes"]


def make_enriched_record(
    record: dict[str, Any], payload: dict[str, Any], model: str
) -> dict[str, Any]:
    """Merge an LLM payload into a record under the provenance invariants."""
    clean = coerce_llm_payload(payload)
    windows = {f["name"]: f["source_text_window"] for f in derived_fields(record)}

    # --- time: guarded -----------------------------------------------------
    time_source, final_time = _time_guard(record, clean)
    time_quote = clean["time_evidence"] if time_source == "extracted" else None

    # --- servings ----------------------------------------------------------
    source_servings = record["summary"].get("servings")
    if source_servings:
        servings_value, servings_source = source_servings, "source_record"
    elif clean["servings"] and _window_supports(clean["servings"] or "",
                                                windows["servings"]):
        servings_value, servings_source = clean["servings"], "extracted"
    else:
        servings_value, servings_source = None, "absent"
    servings_quote = (clean["servings_evidence"]
                      if servings_source == "extracted" else None)

    # --- ingredients -------------------------------------------------------
    # extracted only when every normalized name is verbatim in the source;
    # otherwise keep the LLM list but tag it honestly as inferred.
    ingredients_value = record["ingredients"]
    ingredients_source = "source_record"
    ingredients_quote = None
    if clean["ingredients_normalized"]:
        quotes = [_matched_quote(item, windows["ingredients_normalized"])
                  for item in clean["ingredients_normalized"]]
        if all(quotes):
            ingredients_value = clean["ingredients_normalized"]
            ingredients_source = "extracted"
            ingredients_quote = ", ".join(quotes)
        else:
            ingredients_value = clean["ingredients_normalized"]
            ingredients_source = "inferred"

    # --- cuisine / dish_type / diet_tags: extracted when supported, else inferred
    def classify(field: str, value: Any) -> tuple[Any, str]:
        if value is None or value == []:
            return value, "absent"
        if _window_supports(str(value), windows[field]):
            return value, "extracted"
        if field in INFERRABLE_FIELDS:
            return value, "inferred"
        return None, "dropped"

    def classify_quoted(field: str, value: Any) -> tuple[Any, str, str | None]:
        """Extracted (with verbatim quote) / inferred / absent."""
        if value is None or value == []:
            return value, "absent", None
        quote = _matched_quote(str(value), windows[field])
        if quote is not None:
            return value, "extracted", quote
        if field in INFERRABLE_FIELDS:
            return value, "inferred", None
        return None, "dropped", None

    cuisine_value, cuisine_source, cuisine_quote = classify_quoted(
        "cuisine", clean["cuisine"])
    dish_value, dish_source, dish_quote = classify_quoted(
        "dish_type", clean["dish_type"])
    # diet_tags: filter each tag individually
    diet_value: list[str] = []
    diet_quotes: list[str] = []
    diet_source = "absent"
    for tag in clean["diet_tags"]:
        kept, tag_source, tag_quote = classify_quoted("diet_tags", tag)
        if tag_source in ("extracted", "inferred"):
            diet_value.append(tag)
            if tag_quote:
                diet_quotes.append(tag_quote)
            if tag_source == "extracted":
                diet_source = "extracted"
            elif diet_source == "absent":
                diet_source = "inferred"
    diet_quote = ", ".join(diet_quotes) if diet_source == "extracted" else None

    return {
        "pageid": record["pageid"],
        "revid": record["revid"],
        "source_revid": record["revid"],
        "title": record["title"],
        "url": record["url"],
        "fetched_at": record["fetched_at"],
        "categories": record["categories"],
        "summary": {
            "category": record["summary"].get("category"),
            "servings": servings_value,
            "time_minutes": final_time,
            "rating": record["summary"].get("rating"),
        },
        "ingredients_raw": record["ingredients_raw"],
        "ingredients": record["ingredients"],
        "ingredients_normalized": ingredients_value,
        "steps": record["steps"],
        "description": record["description"],
        "variant_group": record["variant_group"],
        "cuisine": cuisine_value,
        "dish_type": dish_value,
        "diet_tags": diet_value,
        "source_text": record["source_text"],
        "enrichment": {
            "model": model,
            "schema_version": SCHEMA_VERSION,
            "provenance": {
                "ingredients_normalized": {
                    "source": ingredients_source,
                    "source_quote": ingredients_quote,
                },
                "cuisine": {
                    "source": cuisine_source,
                    "source_quote": cuisine_quote,
                },
                "dish_type": {
                    "source": dish_source,
                    "source_quote": dish_quote,
                },
                "diet_tags": {
                    "source": diet_source,
                    "source_quote": diet_quote,
                },
                "time_minutes": {
                    "source": time_source,
                    "source_quote": time_quote,
                },
                "servings": {
                    "source": servings_source,
                    "source_quote": servings_quote,
                },
            },
            "notes": clean["notes"],
        },
    }


# ---------------------------------------------------------------------------
# Enriched-layer contract
# ---------------------------------------------------------------------------

ENRICHED_REQUIRED_KEYS = (
    "pageid", "revid", "source_revid", "title", "url", "fetched_at",
    "categories", "summary", "ingredients_raw", "ingredients",
    "ingredients_normalized", "steps", "description", "variant_group",
    "cuisine", "dish_type", "diet_tags", "source_text", "enrichment",
)
PROVENANCE_FIELDS = {
    "ingredients_normalized", "cuisine", "dish_type", "diet_tags",
    "time_minutes", "servings",
}
QUOTED_SOURCES = {"extracted"}


def validate_enriched(record: dict[str, Any]) -> list[str]:
    """Contract violations for one enriched record (empty = ok)."""
    errors: list[str] = []
    for key in ENRICHED_REQUIRED_KEYS:
        if key not in record:
            errors.append(f"missing key: {key}")
    if errors:
        return errors

    enrichment = record["enrichment"]
    if not isinstance(enrichment, dict) or "provenance" not in enrichment:
        return ["enrichment.provenance missing"]
    prov = enrichment["provenance"]
    if set(prov.keys()) != PROVENANCE_FIELDS:
        errors.append(
            f"provenance fields mismatch: {sorted(prov.keys())}"
        )
    for field, entry in prov.items():
        if entry.get("source") not in PROVENANCE_SOURCES:
            errors.append(f"provenance.{field}: invalid source {entry.get('source')!r}")
        if entry.get("source") in QUOTED_SOURCES and not entry.get("source_quote"):
            errors.append(f"provenance.{field}: source_quote required for "
                          f"{entry.get('source')}")
    if record["enrichment"].get("model") is None:
        errors.append("enrichment.model missing")
    if not isinstance(record["diet_tags"], list):
        errors.append("diet_tags must be a list")
    time_val = record["summary"]["time_minutes"]
    if time_val is not None and (isinstance(time_val, bool)
                                 or not isinstance(time_val, int) or time_val <= 0):
        errors.append("summary.time_minutes must be a positive int or null")
    if prov.get("time_minutes", {}).get("source") == "inferred":
        errors.append("time_minutes provenance 'inferred' is forbidden (spec §4.6)")
    return errors


# ---------------------------------------------------------------------------
# OpenAI call (the only network code in this module)
# ---------------------------------------------------------------------------


def enrich_record_via_api(
    record: dict[str, Any],
    model: str,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict[str, Any]:
    """Call the model with structured outputs and merge the result."""
    from openai import OpenAI  # imported lazily: offline tests never need it

    client = OpenAI()  # reads OPENAI_API_KEY
    messages = build_messages(record, derived_fields(record))
    response = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=MAX_OUTPUT_TOKENS,
        response_format={"type": "json_schema", "json_schema": response_schema()},
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    return make_enriched_record(record, payload, model)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"model": DEFAULT_MODEL, "temperature": DEFAULT_TEMPERATURE}


def _load_corpus() -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    for path in sorted((CORPUS_DIR / "recipes").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["pageid"]] = record
    return records


def _cmd_plan() -> int:
    """Show which fields would be enriched, without any API calls."""
    records = _load_corpus()
    fillable = {
        "time_minutes": 0, "servings": 0, "cuisine": 0,
        "dish_type": 0, "diet_tags": 0, "ingredients_normalized": 0,
    }
    for record in records.values():
        if record["summary"].get("time_minutes") is None:
            fillable["time_minutes"] += 1
        if not record["summary"].get("servings"):
            fillable["servings"] += 1
    print(f"records: {len(records)}")
    print("fields the LLM may fill (already-known values are kept as-is):")
    for field, count in sorted(fillable.items()):
        print(f"  {field:<24} {count:>3} records currently null/missing")
    return 0


def _cmd_run(model: str, temperature: float, only_pageid: int | None) -> int:
    records = _load_corpus()
    if only_pageid is not None:
        if only_pageid not in records:
            print(f"pageid {only_pageid} not in corpus", file=sys.stderr)
            return 1
        records = {only_pageid: records[only_pageid]}

    ENRICHED_DIR.mkdir(exist_ok=True)
    failures = 0
    for index, (pageid, record) in enumerate(sorted(records.items()), start=1):
        print(f"[{index}/{len(records)}] {record['title']} …", flush=True)
        enriched: dict[str, Any] | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                enriched = enrich_record_via_api(record, model, temperature)
                break
            except Exception as exc:  # noqa: BLE001 — log, backoff, retry
                print(f"    attempt {attempt} failed: {exc}", flush=True)
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)
        if enriched is None:
            failures += 1
            print("    SKIPPED after retries", flush=True)
            continue

        errors = validate_enriched(enriched)
        if errors:
            failures += 1
            print(f"    CONTRACT VIOLATIONS: {errors}", flush=True)
            continue

        out_path = ENRICHED_DIR / f"{pageid}.json"
        out_path.write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        prov = enriched["enrichment"]["provenance"]
        summary = ", ".join(f"{k}={v['source']}" for k, v in sorted(prov.items()))
        print(f"    ok -> {out_path.name} ({summary})", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    if failures:
        print(f"\n{failures} record(s) failed; enriched layer is incomplete.",
              file=sys.stderr)
        return 1
    print(f"\nDone: {len(records)} record(s) enriched into {ENRICHED_DIR}")
    return 0


def _cmd_validate() -> int:
    if not ENRICHED_DIR.exists():
        print("no enriched/ layer yet — run `python -m dataset.enrich run` first")
        return 1
    errors_total = 0
    paths = sorted(ENRICHED_DIR.glob("*.json"))
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        for error in validate_enriched(record):
            errors_total += 1
            print(f"{path.name}: {error}")
    print(f"{len(paths)} enriched records checked, {errors_total} violation(s)")
    return 1 if errors_total else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="show fillable fields without API calls")
    run = sub.add_parser("run", help="enrich records via GPT Luna Low")
    run.add_argument("--record", type=int, default=None, help="enrich one pageid")
    run.add_argument("--model", default=None)
    sub.add_parser("validate", help="validate the enriched layer")
    args = parser.parse_args(argv)

    config = _load_config()
    model = getattr(args, "model", None) or config.get("model", DEFAULT_MODEL)
    temperature = config.get("temperature", DEFAULT_TEMPERATURE)

    if args.command == "plan":
        return _cmd_plan()
    if args.command == "run":
        return _cmd_run(model, temperature, getattr(args, "record", None))
    if args.command == "validate":
        return _cmd_validate()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
