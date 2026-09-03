# Dataset — Wikibooks Cookbook Corpus

This folder contains the corpus of the Recipe Q&A Service: the single source of
recipe facts the service is allowed to cite.

The requirements below are the dataset goals distilled from
[`docs/00_TASK.md`](../docs/00_TASK.md) (assignment) and
[`docs/03_SPEC.md`](../docs/03_SPEC.md) §8.1 (normative corpus requirements).

## Goals

1. **Source: Wikibooks Cookbook only.**
   All recipes come from <https://en.wikibooks.org/wiki/Cookbook>, fetched
   through the **MediaWiki API** — no manual scraping and no hand-prepared page
   lists (CORP-01, CORP-02).

2. **Size: 40–60 unique recipe records.**
   The ingestion pipeline produces 40–60 unique, normalized recipe records
   (CORP-03). The exact count is checked automatically after each build.

3. **Multiple categories with variety.**
   Recipes are selected from several Wikibooks Cookbook categories and must
   cover (CORP-04–CORP-08):
   - **different cuisines** (e.g., Indian, Italian, Japanese, Mexican, Russian);
   - **overlapping dishes** — several recipes for the same or a similar dish,
     so the conflicting-sources and single-recipe-selection policies (spec §4.2)
     can be exercised;
   - **different levels of structure** — pages range from well-structured
     (Ingredients / Procedure sections) to free-form prose.

4. **Reproducible rebuild.**
   A clean checkout plus the committed ingestion script and its pinned
   configuration rebuild the same corpus shape — no manually edited production
   data (CORP-09, CORP-10, CORP-11). Category lists and normalization rules are
   configuration/versioned files, not hidden constants.

5. **Rich recipe records.**
   Each record retains (spec §8.1):
   - title and canonical Wikibooks URL;
   - raw/source wikitext;
   - parsed ingredients and steps, where the source provides them;
   - ingestion metadata (categories, timestamps, corpus build/version id).

6. **Metadata for hard constraints.**
   Where the source supports it, records carry normalized fields used by
   deterministic filters (spec §8.3):
   - total time (or prep/cook times; missing/ambiguous time stays absent —
     it must never be guessed);
   - dietary signals derived only by documented rules over the source text;
   - normalized ingredient lists for required/excluded-ingredient matching
     (synonym/inflection normalization is versioned and tested).

7. **Deterministic, versioned output.**
   Ingestion records the corpus build/source version so a deployment can be
   tied to an exact corpus (spec §4 assumption 2). `/health` reports this
   `corpus_version`.

## Layout

```
dataset/
├── README.md          # this file — dataset goals and contract
├── PLAN.md            # implementation plan + traceability matrix
├── config.json        # pinned category list and quotas (config, not code)
├── enrich.py          # LLM enrichment CLI: plan | run | validate
├── enrich_config.json # enrichment model settings (gpt-luna-low, temp 0)
├── ingest.py          # CLI: build | rebuild | validate | analyze | verify
├── mw_api.py          # MediaWiki API client (the only I/O module)
├── parsing.py         # pure wikitext parsing
├── select.py          # deterministic candidate selection
├── validate.py        # corpus contract checks
├── fixtures/          # committed real API responses for tests
├── tests/             # pytest suite (network-free by default)
└── corpus/            # committed build output
    ├── recipes/*.json # normalized recipe records (one per pageid)
    ├── index.json     # corpus_version, count, category counts
    ├── manifest.json  # pageid -> revid pinning exact revisions
    └── eda_report.json# EDA: selection-signal decision

enriched/            # committed derived layer (git-tracked, production data)
    ├── <pageid>.json # corpus record + LLM-normalized fields + provenance
    └── report.json   # enrichment run summary: coverage + provenance counts
```

## How to build

From a clean checkout:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m dataset.ingest build      # full pipeline (hits the API)
.venv/bin/python -m dataset.ingest validate   # contract-check the corpus
.venv/bin/python -m dataset.ingest analyze    # regenerate the EDA report
.venv/bin/python -m dataset.ingest rebuild    # rebuild from pinned revisions
.venv/bin/python -m dataset.ingest verify     # diff a fresh rebuild vs committed
.venv/bin/python -m pytest dataset/tests      # network-free test suite
```

The committed `corpus/` is already valid: `validate` and the test suite pass
without network access. `rebuild` fetches exactly the manifest revisions, so
any machine reproduces the same corpus.

## LLM enrichment (optional derived layer)

`dataset/enrich.py` runs each corpus record through **gpt-5.6-luna** (reasoning
effort `low`, the fast/cheap tier) with **Structured Outputs** and writes
`dataset/enriched/<pageid>.json` — a derived layer on top of `corpus/`, which
stays untouched:

```bash
export OPENAI_API_KEY=sk-…                            # required for `run`
.venv/bin/python -m dataset.enrich plan               # what would be filled (no API)
.venv/bin/python -m dataset.enrich run --record 4991  # one record first
.venv/bin/python -m dataset.enrich run                # all records (~49 calls)
.venv/bin/python -m dataset.enrich validate           # contract-check enriched/
```

What the model adds: cleaner `ingredients_normalized`, `cuisine`, `dish_type`,
`diet_tags`, and `servings` fills. Every field carries a **provenance** entry
(`extracted` = verbatim quote from the source text, `inferred` = tagged model
inference for harmless fields only, `source_record` = deterministic parser
already knew it, `dropped` = rejected by a code-side guard).

**Guard rails (enforced in code, not just prompts):**

- **Time is never LLM-guessed** (spec §4.6): an LLM-proposed `time_minutes`
  survives only if its evidence quote parses deterministically to the same
  number *and* appears verbatim in the record's recipesummary window;
  otherwise it is dropped back to `null`. `inferred` time provenance is a
  contract violation.
- The base corpus is reproducible from the ingestion script alone (CORP-09/11);
  enrichment is a separate, auditable derived layer, so reproducibility is
  unaffected.
- Model settings live in `enrich_config.json` (`gpt-5.6-luna`, reasoning
  effort `low`); responses are schema-constrained via Structured Outputs.
  `run` is resumable: already-enriched records are skipped unless their file
  is deleted. `enriched/report.json` records coverage and provenance counts
  for the committed run.

## Non-goals

- No hand-curated or post-edited recipe content.
- No nutrition calculation, allergy certification, or safety claims from the
  corpus (spec §5.4 — those questions are refused).
- No live web search: the corpus is a build-time artifact, not a runtime source.
