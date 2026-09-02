# Dataset Ingestion Script — Implementation Plan

This plan describes how `dataset/ingest.py` and its supporting modules are
built so the corpus satisfies the assignment
([`../docs/00_TASK.md`](../docs/00_TASK.md)), the normative spec §8.1/§8.3
([`../docs/03_SPEC.md`](../docs/03_SPEC.md)) and checklist items CORP-01–11,
TEST-02, RET-08, AC-01, AC-02, AC-20.

## 1. Requirements the script must satisfy

| ID       | Requirement                                             | How the script satisfies it                                  |
| -------- | ------------------------------------------------------- | ------------------------------------------------------------ |
| CORP-01/02 | Wikibooks Cookbook via MediaWiki API, not scraping     | All data from `https://en.wikibooks.org/w/api.php`            |
| CORP-03  | 40–60 unique records                                    | Post-build validator fails the build outside 40–60            |
| CORP-04  | Several categories                                      | Pinned category list with per-category quotas in `config.json` |
| CORP-05–08 | Variety: cuisines, overlapping dishes, structure levels | Category axes span diet/cuisine/type; variant pages ("… I/II") retained; structure gate does not demand perfect structure |
| CORP-09/10 | Script committed; corpus rebuildable from script alone | Clean checkout + `python -m dataset.ingest build`             |
| CORP-11  | Reproducible build                                      | Deterministic selection + revision-ID manifest (see §5)       |
| RET-08 / AC-20 | EDA on corpus; stable-ID baseline until a signal is proven | `analyze` mode produces the EDA report                 |
| SPEC §8.1 | Retain title, canonical URL, raw text, parsed ingredients/steps | Record schema §7                                    |
| SPEC §4.6 | Missing/ambiguous time stays missing, never guessed     | Tolerant time parser returns `null` on ambiguity              |
| TEST-02/07 | Ingestion tested; tests committed before implementation | Fixture-based tests for parsers/selection, written first     |

## 2. Architecture

```
dataset/
├── README.md          # goals (done)
├── PLAN.md            # this file
├── __init__.py
├── config.json        # pinned configuration: categories, quotas, API params
├── ingest.py          # CLI entry: build | rebuild | validate | analyze | verify
├── mw_api.py          # thin MediaWiki API client (requests, UA, timeout, retries)
├── parsing.py         # pure functions: wikitext → fields (no I/O)
├── select.py          # pure functions: candidates → deterministic corpus selection
├── validate.py        # corpus contract checks (used by build, validate, tests)
├── analyze.py         # EDA report (selection-signal decision input)
├── fixtures/          # committed real API response samples for tests
├── corpus/            # committed build output (recipes + manifest)
└── raw/               # git-ignored raw responses cache
```

Rationale: all logic that can be wrong (parsing, selection, validation) is
pure and unit-testable without network; I/O lives in one small client.

## 3. Pipeline (build mode)

```
1. load config.json                     (categories, quotas, target count)
2. list category members                (action=query, list=categorymembers,
                                         cmtype=page, cmnamespace=102, cmlimit=max)
3. filter candidates                    (Cookbook: prefix, not in exclude list,
                                         has minimal recipe structure)
4. deterministic selection              (round-robin quotas, stable sort by title,
                                         pick target_count candidates)
5. fetch content per selected page      (prop=revisions, rvslots=main,
                                         rvprop=content|ids|timestamp)
6. parse + normalize each page          (recipesummary fields, sections,
                                         ingredients, time, metadata)
7. validation gate                      (structure check; drop & log failures;
                                         count must stay in 40–60 else build fails)
8. write corpus/                        (recipes/*.json, manifest.json,
                                         index.json with corpus_version)
```

Politeness/robustness: descriptive User-Agent (Wikimedia policy), 15 s timeout,
3 retries with exponential backoff, small delay between content requests,
continuation handling for large category listings.

## 4. Parsing rules (deterministic, versioned, tested)

- **recipesummary**: extract `Category`, `Time`, `Servings`, `Rating` (and any
  `Additional time`) from the `{{recipesummary|...}}` template; unknown/absent
  field → `null`. Field names matched case-insensitively; values never guessed.
- **Time → minutes**: accepts `"75 minutes"`, `"1 hour"`, `"1 1/2 hours"`,
  `"90 min"`. Ambiguous ("varies", ranges without a single total, missing) →
  `null`. Spec §4.6: a recipe with `null` time can never match a hard time
  constraint.
- **Sections**: split on `==Heading==`; locate Ingredients (incl. `===…===`
  sub-blocks) and Procedure/Steps. Pages without both some ingredient-like
  bullets and some steps are dropped by the structure gate (this also filters
  meta-pages like `Cookbook:Ingredients`).
- **Ingredient normalization**: `[[Cookbook:Potato|potato]]` → `potato`;
  strip templates/markup/quantity formatting for the normalized string; keep
  the raw bullet line alongside. The synonym/inflection map used later by
  filters is a separate versioned file — ingestion only normalizes display text.
- **Links/duplication**: dedupe by `pageid`. Near-duplicate variant pages
  (`X I`, `X II`) are kept deliberately as separate recipes (the corpus needs
  overlapping dishes) and tagged `variant_group: "x"` in metadata. This rule is
  documented here and asserted by tests.
- **Canonical URL**: built as `https://en.wikibooks.org/wiki/<title>` with
  spaces replaced by underscores and non-ASCII characters percent-encoded
  (MediaWiki canonical form), e.g. `Cookbook:Borscht_Ø` →
  `https://en.wikibooks.org/wiki/Cookbook:Borscht_%C3%98`.

## 5. Reproducibility model

- Selection depends only on: committed `config.json` + the category listing +
  the deterministic rules. Same inputs → same page set.
- Wiki content drifts, so each record stores `revid` + `timestamp`, and the
  build writes `manifest.json` (pageid → revid).
- `rebuild` mode fetches exactly the manifest revisions → bit-identical corpus
  from any clean checkout. `verify` mode rebuilds in memory and diffs against
  the committed corpus.
- `corpus_version` (config version + build date + content hashes) is written to
  `index.json` and later reported by `/health` (spec assumption 2).

## 6. Proposed pinned category list (`config.json`, ~8 categories, quota each)

| Category                    | Axis    | Quota | Why                                        |
| --------------------------- | ------- | ----- | ------------------------------------------ |
| `Vegetarian recipes`        | diet    | 8     | diet-constraint questions; overlaps        |
| `Indian recipes`            | cuisine | 6     | cuisine variety                            |
| `Italian recipes`           | cuisine | 6     | carbonara & pasta overlaps                 |
| `Japanese recipes`          | cuisine | 5     | cuisine variety                            |
| `Mexican recipes`           | cuisine | 5     | cuisine variety                            |
| `Ukrainian recipes`         | cuisine | 4     | borscht; Eastern European                  |
| `Soup recipes`              | type    | 8     | type axis; overlaps with diets/cuisines    |
| `Dessert recipes`           | type    | 8     | type axis; structure variance              |

Target: 50 selected → 40–60 after the validation gate. The list is
configuration, not code (spec §8.1); changing it changes `corpus_version`.

## 7. Record schema (`corpus/recipes/<pageid>.json`)

```json
{
  "pageid": 6470,
  "revid": 123456,
  "title": "Cookbook:Borscht",
  "url": "https://en.wikibooks.org/wiki/Cookbook:Borscht",
  "fetched_at": "2026-09-02T12:00:00Z",
  "categories": ["Soup recipes", "Ukrainian recipes", "Vegetarian recipes"],
  "summary": {"category": "Soup recipes", "servings": "about 6",
               "time_minutes": 75, "rating": 2},
  "ingredients_raw": ["*1½ cups thinly-sliced potatoes …"],
  "ingredients": ["potatoes", "beets", "water", "butter", "…"],
  "steps": ["Place the potatoes, beets, and water …", "…"],
  "description": "Borscht or borshch is a hearty beetroot vegetable soup …",
  "variant_group": null,
  "source_text": "…full raw wikitext…"
}
```

`index.json`: `{corpus_version, built_at, config_version, count,
category_counts, tool_versions}`. `manifest.json`: `{pageid: revid}`.

## 8. EDA (`analyze` mode → `corpus/eda_report.json`)

Computes: category counts, % pages with explicit time, time distribution,
`Rating` coverage/distribution, structure completeness, variant-group list.
Conclusion recorded in the report: does a reliable, comparable selection
signal exist (e.g., Rating)? If not, the stable-ID baseline (spec §4.2, AC-20)
remains and ADR-001 records that. The report is committed.

## 9. Tests (written before the implementations they cover)

- `test_parsing.py`: fixtures from `fixtures/` (real Borscht-like response) —
  recipesummary fields, time parsing incl. ambiguous → `null`, section split,
  link cleaning, variant grouping.
- `test_select.py`: quota round-robin, stable ordering, dedupe by pageid,
  exclusion of meta-pages, count bounds.
- `test_validate.py`: contract checks (count, required fields, URL shape,
  uniqueness) pass on fixtures and fail on broken fixtures.
- `test_corpus.py`: validates the **committed** `corpus/` against the contract
  (keeps the checked-in corpus honest).
- `test_mw_api.py`: retries/timeout behavior with a stubbed HTTP layer.
- Live API tests are marked `@pytest.mark.live` and skipped by default
  (CI stays deterministic; run manually when needed).

## 10. CLI

```
python -m dataset.ingest build      # full pipeline, writes corpus/
python -m dataset.ingest rebuild    # exact revisions from manifest.json
python -m dataset.ingest validate   # contract-check committed corpus
python -m dataset.ingest analyze    # EDA report
python -m dataset.ingest verify     # rebuild in memory + diff vs committed
```

Dependencies: `requests`, `pytest` (pinned in `requirements.txt` at repo root).
Python 3.11+.

## 11. Commit sequence (granular, test-first where required)

1. `dataset/README.md` + `PLAN.md` (this file)
2. `requirements.txt` + `fixtures/` (real API samples)
3. failing `test_parsing.py` → `parsing.py` implementation
4. failing `test_select.py` → `select.py` implementation
5. `mw_api.py` + `ingest.py` CLI (I/O + orchestration)
6. first `build` run → commit `config.json`, `corpus/`, `manifest.json`
7. `validate.py` + `analyze.py` → commit `eda_report.json`
8. README updates (corpus build instructions)

## 12. Risks and mitigations

| Risk                                             | Mitigation                                                        |
| ------------------------------------------------ | ----------------------------------------------------------------- |
| Meta/non-recipe pages in categories               | Structure gate + explicit exclude list in config                  |
| `recipesummary` field name/value variants         | Tolerant case-insensitive parser; unknown → `null`, never guessed |
| Ratings sparse → EDA finds no signal              | Expected outcome: stable-ID baseline stays; documented in ADR-001 |
| Category listing drift changes selection          | Manifest + `rebuild`/`verify` pin exact revisions                 |
| Rate limiting / API hiccups                       | UA per policy, timeouts, retries with backoff, ~60 requests only  |
| Corpus count drops below 40 after validation gate | Quota headroom (target 50); build fails loudly if < 40            |

## 13. Traceability — coverage of 00_TASK, 01_PLAN, 02_CHECKLIST

**Implementation status (updated after the first build):** all steps of §11 are
complete. The corpus is built, committed and validated: 49 records, corpus
version `45af1c982923952a`, EDA verdict `stable_id_baseline`. Ukrainian recipes
yielded only 3 pages live, so its quota was lowered to 3 and soups/desserts
raised to 9 (config_version stays 1; the change is recorded here and in the
commit history).

The plan is checked against every requirement in the source documents that
could plausibly apply to the dataset stage. Items outside the dataset's scope
are explicitly marked N/A (they belong to later phases and must not be silently
forgotten).

### From `docs/00_TASK.md` (assignment)

| Assignment requirement                          | Plan coverage                          |
| ----------------------------------------------- | -------------------------------------- |
| Corpus from Wikibooks Cookbook (40–60 recipes)  | §1 (CORP-01/03), §3, §6, §7            |
| Several categories, variety, cuisines, overlap, structure levels | §4, §6 (diet/cuisine/type axes, variant pages kept) |
| MediaWiki API ingestion; commit the script; rebuildable corpus | §1 (CORP-02/09/10), §3, §5, §10 CLI |
| “We must be able to build the corpus again from only the script” | §5 manifest + `rebuild`/`verify`    |

Dataset-adjacent items owned by later phases (NOT covered here by design):
retrieval/grounding (Phase 2–3), eval golden set (Phase 4), UI (Phase 5),
deployment (Phase 6). The golden eval's expected-source fields (EVAL-03) will
reference `pageid`/`title` produced by this script, so the record schema (§7)
fixes those names now.

### From `docs/01_PLAN.md` (work plan)

| Plan requirement (Phase 1)                      | Plan coverage                          |
| ------------------------------------------------ | -------------------------------------- |
| Implement reproducible Wikibooks ingestion       | §3, §5, §10                            |
| Build 40–60 recipe corpus                        | §3 step 7 (validation gate), §6 quotas |
| Run EDA to check for a reliable selection signal | §8 `analyze` mode → `corpus/eda_report.json` |
| Verify corpus variety                            | §6 axes; §9 `test_corpus.py` asserts variety contract |
| “Do not do manual data preparation that cannot be repeated” | §4 normalization rules are code, §5 manifest; no hand-edited data |
| ADR-001 topic: retrieval + post-EDA selection signal | §8 feeds ADR-001; ratings sparsity → stable-ID baseline |
| Test-first for part of functionality (Phase 4 discipline, applied early) | §9 tests written before implementations (TEST-07) |
| Granular commit history                          | §11 commit sequence                    |

### From `docs/02_CHECKLIST.md` (constraints & acceptance criteria)

| Checklist item | Requirement                                             | Plan coverage |
| -------------- | ------------------------------------------------------- | ------------- |
| CORP-01 (MUST) | Wikibooks Cookbook used                                 | §1, §3        |
| CORP-02 (MUST) | Data via MediaWiki API                                  | §1, §3        |
| CORP-03 (MUST) | 40–60 recipes                                           | §1, §3 gate, §6 |
| CORP-04 (MUST) | Several categories                                      | §6 (8 categories, quotas in config) |
| CORP-05 (MUST) | Corpus variety                                          | §6 axes       |
| CORP-06 (MUST) | Different cuisines                                      | §6 (5 cuisine categories) |
| CORP-07 (MUST) | Overlapping dishes                                      | §4 (variant pages kept, `variant_group`) |
| CORP-08 (MUST) | Different structure levels                              | §4 (structure gate tolerant to prose-style pages) |
| CORP-09 (MUST) | Ingestion script committed                              | §11 commit sequence |
| CORP-10 (MUST) | Corpus rebuildable from script alone                    | §5 (`rebuild`, `verify`) |
| CORP-11 (SHOULD)| Build reproducible                                     | §5           |
| RET-08 (SHOULD)| Stable-ID baseline until EDA proves a signal            | §8 EDA report |
| SPEC-06 (MUST) | Empty question behavior — **N/A dataset** (Phase 2/3)   | —             |
| TEST-02 (MUST) | Ingestion tested                                        | §9            |
| TEST-06/07     | Granular history; tests before implementation           | §9, §11       |
| SCOPE-07 (PREF)| Python backend                                          | §10 Python 3.11+ |
| AC-01          | Reproducible MediaWiki ingestion builds 40–60 unique records | §3, §5, §9 (`test_corpus.py`) |
| AC-02          | Variety, overlap, structure; title + canonical URL retained | §6, §7     |
| AC-20          | Selection by lowest stable ID after EDA                 | §8 (baseline decision input) |

### Gaps identified by this review

1. **`requests` pinning**: the plan named dependencies but not where they are
   pinned → fixed: pinned in `requirements.txt` at repo root (§10), committed
   in step 2 of §11.
2. **URL canonicalization**: AC-02 requires canonical URLs; §7 already stores
   `https://en.wikibooks.org/wiki/<title>`, underscore/percent-encoding rule
   added to §4 parsing rules.
3. **Variety assertion**: CORP-05/06 were listed as “corpus review” (manual) in
   the checklist; the plan now asserts them automatically in `test_corpus.py`
   (min distinct categories/cuisines, variant groups present) — stronger than
   the checklist asks.

No other gaps: every MUST/SHOULD item that applies to the dataset stage is
covered by a concrete section of this plan; all remaining requirements are
owned by later phases and referenced above so they cannot be lost.
