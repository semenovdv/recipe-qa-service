# Dataset Stage Completion Report

**Date:** 2026-09-02
**Scope:** Phase 1 dataset work (corpus planning, ingestion system, first build)
**Result:** ✅ Complete — all dataset requirements from `docs/00_TASK.md`,
`docs/01_PLAN.md` (Phase 1) and `docs/02_CHECKLIST.md` (CORP-*) are met.

---

## 1. Deliverables

| Artifact | Location | Status |
| --- | --- | --- |
| Dataset goals & contract | `dataset/README.md` | ✅ committed |
| Implementation plan + traceability matrix | `dataset/PLAN.md` (§1–§13) | ✅ committed |
| Pinned ingestion configuration | `dataset/config.json` (8 categories, quotas, target 50) | ✅ committed |
| Ingestion CLI (5 modes) | `dataset/ingest.py` — `build / rebuild / validate / analyze / verify` | ✅ committed |
| MediaWiki API client (isolated I/O) | `dataset/mw_api.py` — UA policy, timeouts, retries, continuation | ✅ committed |
| Pure parsing layer | `dataset/parsing.py` | ✅ committed |
| Deterministic selection | `dataset/select.py` — quotas, round-robin, meta-page filter, 40-record floor | ✅ committed |
| Corpus contract validator | `dataset/validate.py` — record + corpus + automated variety checks | ✅ committed |
| Test suite | `dataset/tests/` — 44 tests, network-free | ✅ all passing |
| Real API fixtures | `dataset/fixtures/` — Borscht, Apple Crisp I/II, category listing | ✅ committed |
| **Built corpus (49 recipes)** | `dataset/corpus/recipes/*.json` | ✅ committed |
| Corpus index | `dataset/corpus/index.json` — version `45af1c982923952a`, count, category counts | ✅ committed |
| Revision manifest | `dataset/corpus/manifest.json` — pageid → revid (exact-revision pinning) | ✅ committed |
| EDA report | `dataset/corpus/eda_report.json` — selection-signal decision | ✅ committed |

## 2. Requirement compliance

### Corpus requirements (assignment + spec §8.1 + checklist)

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| CORP-01 | Wikibooks Cookbook source | ✅ | All records from `en.wikibooks.org` |
| CORP-02 | MediaWiki API (not scraping) | ✅ | `w/api.php` (`list=categorymembers`, `prop=revisions`) |
| CORP-03 | 40–60 unique recipes | ✅ | **49** unique pageids; enforced by validator + tests |
| CORP-04 | Several categories | ✅ | 8 pinned categories, all contributing (see §3) |
| CORP-05 | Variety | ✅ | Diet/cuisine/type axes + automated variety assertions |
| CORP-06 | Different cuisines | ✅ | **15 distinct cuisine tags** (§3) |
| CORP-07 | Overlapping dishes | ✅ | Marinara I/II, Baingan Bartha I/II variant groups |
| CORP-08 | Different structure levels | ✅ | Source text 952–10,766 chars; mixed metadata coverage |
| CORP-09 | Ingestion script committed | ✅ | 10 granular commits (see §5) |
| CORP-10 | Corpus rebuildable from script alone | ✅ | `rebuild` fetches exact manifest revisions |
| CORP-11 | Reproducible build (SHOULD) | ✅ | Deterministic selection + `verify` diff mode |

### Constraint support for later phases

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| CON-01 | Time constraint support | ✅ | Task's example question answerable: 4 vegetarian recipes < 30 min (15/15/18/20 min) |
| CON-02 | Diet constraint support | ✅ | 14 vegetarian-tagged records |
| CON-03 | Ingredient constraint support | ✅ | Normalized ingredient lists; raw lines retained |
| RET-08 / AC-20 | EDA on selection signal; stable-ID baseline | ✅ | EDA verdict: `stable_id_baseline` (rating 2% coverage, time 47% — no usable signal) |
| AC-01 | Reproducible MediaWiki ingestion, 40–60 unique | ✅ | Rebuild + validate + tests green |
| AC-02 | Variety, overlap, structure, canonical URLs | ✅ | 0 malformed URLs; §3 below |
| SPEC §4.6 | Missing/ambiguous time never guessed | ✅ | Ranges, unit-less numbers, multi-phase totals → `null` (tested) |
| SPEC-02 / TEST-07 / AC-17 | Spec & tests before implementation | ✅ | Commit order: docs → failing tests → implementation |

## 3. Corpus facts (measured, not asserted)

- **49 unique recipes**; corpus version `45af1c982923952a`
- Distribution by selection category: Vegetarian 14, Dessert 12, Soup 9,
  Japanese 5, Italian 5, Indian 4, Mexican 3, Ukrainian 3
- 15 cuisine tags across Africa, Asia, Europe and the Americas
- 23/49 records with explicit total time (now that multi-phase totals are
  `null`); 29/49 with servings; structure gate dropped non-recipe pages
- 2 overlapping-dish groups retained deliberately for the conflicting-recipes
  policy (spec §9) and the deterministic single-recipe selection (§4.2)
- All 49 URLs canonical; `Cookbook:` colon preserved, spaces/naming encoded

## 4. Audit findings and fixes

| Finding | Severity | Resolution |
| --- | --- | --- |
| `Time = 30 minutes + 24 hours` (Marinara I) parsed as 1470 min — a false citable fact | **High** | Multi-phase totals now `null` per spec §4.6; regression test added; corpus rebuilt from pinned revisions (`8843c8f`) |
| Ukrainian recipes category holds only 3 pages live vs quota 4 | Low | Quota 4 → 3, soups/desserts 8 → 9; target 50 held; recorded in PLAN §13 |
| One structure-gate drop (Afghan Bread: no ingredient section) | Info | Expected gate behavior; 49 records kept the corpus in bounds |
| Affogato has a single step | Info | Genuine page content; kept for structure variety (CORP-08) |

## 5. Commit history (spec → tests → implementation → build → docs)

| Commit | Content |
| --- | --- |
| `5a7d396` | Planning docs (task, plan, checklist, spec, appendix, README) |
| `455f729` | Translate planning docs and README to English |
| `bc7d99f` | Dataset plan with goals + traceability matrix (gaps found & fixed) |
| `a774435` | **Test suite before implementation** + fixtures + requirements pinning |
| `ffef2eb` | Parsing layer implementation (tests to green) |
| `4cc36b7` | Deterministic selection implementation (test-first) |
| `72e3444` | MediaWiki client, CLI, validation, EDA |
| `e6a9982` | First real build: 49-recipe corpus + EDA report |
| `6c0c9a0` | Build instructions + implementation status in docs |
| `8843c8f` | Audit fix: multi-phase time totals → ambiguous/`null` |

## 6. Verification commands

```bash
.venv/bin/python -m pytest dataset/tests        # 44 passed
.venv/bin/python -m dataset.ingest validate     # corpus valid: 49 records
.venv/bin/python -m dataset.ingest verify       # committed == fresh rebuild
```

## 7. What this stage deliberately does NOT cover (next phases)

Per `docs/01_PLAN.md`: ADRs, retrieval/grounding pipeline, `POST /ask` + `/health`,
UI, eval harness, deployment. The record schema (`pageid`, `title`, `url`,
`summary.time_minutes`, `ingredients`, `steps`, …) already fixes the field names
the golden eval's expected-source checks will reference.
