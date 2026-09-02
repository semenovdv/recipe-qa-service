"""Recipe Q&A Service dataset ingestion CLI.

Usage (dataset/PLAN.md §10):

    python -m dataset.ingest build      # full pipeline, writes corpus/
    python -m dataset.ingest rebuild    # exact revisions from manifest.json
    python -m dataset.ingest validate   # contract-check committed corpus
    python -m dataset.ingest analyze    # EDA report
    python -m dataset.ingest verify     # rebuild in memory + diff vs committed
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import requests

from dataset import mw_api, parsing, select, validate

DATASET_DIR = Path(__file__).resolve().parent
CONFIG_PATH = DATASET_DIR / "config.json"
CORPUS_DIR = DATASET_DIR / "corpus"
RECIPES_DIR = CORPUS_DIR / "recipes"


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_committed_records() -> list[dict[str, Any]]:
    """Load the committed corpus from disk."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RECIPES_DIR.glob("*.json"))
    ]


def _corpus_version(records: list[dict[str, Any]], config: dict[str, Any]) -> str:
    """Deterministic content hash identifying this exact corpus build."""
    hasher = hashlib.sha256()
    hasher.update(str(config["config_version"]).encode())
    for record in sorted(records, key=lambda r: r["pageid"]):
        hasher.update(str(record["pageid"]).encode())
        hasher.update(str(record["revid"]).encode())
    return hasher.hexdigest()[:16]


def _record_from_page(page: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    record = parsing.parse_wikitext_page(page, fetched_at=fetched_at)
    errors = validate.validate_record(record)
    if errors:
        raise ValueError(
            f"record {record.get('pageid')} ({record.get('title')}) failed the "
            f"structure gate: {'; '.join(errors)}"
        )
    return record


def _write_corpus(records: list[dict[str, Any]], config: dict[str, Any]) -> str:
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    for old_file in RECIPES_DIR.glob("*.json"):
        old_file.unlink()

    for record in records:
        path = RECIPES_DIR / f"{record['pageid']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    category_counts: dict[str, int] = {}
    for record in records:
        for category in record["categories"]:
            category_counts[category] = category_counts.get(category, 0) + 1

    index = {
        "corpus_version": _corpus_version(records, config),
        "built_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_version": config["config_version"],
        "count": len(records),
        "category_counts": dict(sorted(category_counts.items())),
    }
    (CORPUS_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {str(record["pageid"]): record["revid"] for record in records}
    (CORPUS_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return str(index["corpus_version"])


def _select_candidates(
    session: requests.Session, config: dict[str, Any]
) -> list[select.Candidate]:
    candidates: list[select.Candidate] = []
    for entry in config["categories"]:
        category = entry["category"]
        members = mw_api.list_category_members(session, category)
        recipes = [m for m in members if m.get("ns") == 102]
        print(f"  {category}: {len(recipes)} cookbook pages", file=sys.stderr)
        candidates.extend(
            select.Candidate(pageid=m["pageid"], title=m["title"], category=category)
            for m in recipes
        )
    quotas = {entry["category"]: entry["quota"] for entry in config["categories"]}
    return select.select_candidates(
        candidates, quotas, config["target_count"], min_count=config["corpus_floor"]
    )


def cmd_build(config: dict[str, Any]) -> int:
    with requests.Session() as session:
        session.headers["User-Agent"] = mw_api.USER_AGENT
        print("listing categories...", file=sys.stderr)
        selected = _select_candidates(session, config)
        print(f"selected {len(selected)} candidate pages", file=sys.stderr)

        print("fetching page content...", file=sys.stderr)
        pageids = [c.pageid for c in selected]
        fetched_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        pages = mw_api.fetch_pages(session, pageids)

    records = _build_from_pages(pages, fetched_at)

    floor, ceiling = config["corpus_floor"], config["corpus_ceiling"]
    if not (floor <= len(records) <= ceiling):
        print(
            f"build failed: {len(records)} records passed the structure gate, "
            f"need {floor}-{ceiling} (CORP-03)",
            file=sys.stderr,
        )
        return 1

    errors = validate.validate_corpus(records, floor, ceiling)
    if errors:
        print("corpus contract violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    version = _write_corpus(records, config)
    print(f"build complete: corpus version {version}")
    return 0


def cmd_rebuild(config: dict[str, Any]) -> int:
    manifest_path = CORPUS_DIR / "manifest.json"
    if not manifest_path.exists():
        print("no manifest.json; run build first", file=sys.stderr)
        return 1
    manifest: dict[str, int] = {
        pageid: int(revid)
        for pageid, revid in json.loads(manifest_path.read_text()).items()
    }
    with requests.Session() as session:
        session.headers["User-Agent"] = mw_api.USER_AGENT
        pages = mw_api.fetch_pages(session, sorted(manifest))
    # pin exact revisions from the manifest (dataset/PLAN.md §5)
    for page in pages:
        page["revisions"] = [rev for rev in page["revisions"] if rev["revid"] == manifest[str(page["pageid"])]]
    pages = [page for page in pages if page.get("revisions")]
    fetched_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = _build_from_pages(pages, fetched_at)
    if len(records) != len(manifest):
        print(
            f"rebuild warning: {len(records)} of {len(manifest)} manifest pages "
            "still pass the structure gate (upstream edits may have occurred)",
            file=sys.stderr,
        )
    version = _write_corpus(records, config)
    print(f"rebuild complete: corpus version {version}")
    return 0


def cmd_validate(config: dict[str, Any]) -> int:
    records = load_committed_records()
    errors = validate.validate_corpus(
        records, config["corpus_floor"], config["corpus_ceiling"]
    )
    if errors:
        print(f"{len(records)} records, {len(errors)} violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"corpus valid: {len(records)} records")
    return 0


def cmd_verify(config: dict[str, Any]) -> int:
    """Rebuild in memory from manifest revisions and diff vs committed corpus."""
    manifest_path = CORPUS_DIR / "manifest.json"
    if not manifest_path.exists():
        print("no manifest.json; run build first", file=sys.stderr)
        return 1
    committed = {r["pageid"]: r for r in load_committed_records()}
    with requests.Session() as session:
        session.headers["User-Agent"] = mw_api.USER_AGENT
        pages = mw_api.fetch_pages(session, sorted(int(pid) for pid in manifest_path.read_text().strip("{}\" ,\n").split()))
    fetched_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = {r["pageid"]: r for r in _build_from_pages(pages, fetched_at)}

    diffs: list[str] = []
    for pageid, record in committed.items():
        other = fresh.get(pageid)
        if other is None:
            diffs.append(f"pageid {pageid}: no longer passes the structure gate")
            continue
        for key in ("revid", "title", "url", "summary", "ingredients", "steps"):
            if record.get(key) != other.get(key):
                diffs.append(f"pageid {pageid}: field {key!r} drifted upstream")
    if diffs:
        print("drift detected:", file=sys.stderr)
        for line in diffs:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"verified: {len(committed)} records match a fresh rebuild")
    return 0


def cmd_analyze(config: dict[str, Any]) -> int:
    records = load_committed_records()
    report = analyze_records(records, config)
    out_path = CORPUS_DIR / "eda_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"EDA report written: {out_path}")
    return 0


def analyze_records(records: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """EDA over the corpus: selection-signal decision input (dataset/PLAN.md §8)."""
    count = len(records)
    with_time = [r for r in records if r["summary"].get("time_minutes") is not None]
    with_rating = [r for r in records if r["summary"].get("rating") is not None]
    with_servings = [r for r in records if r["summary"].get("servings")]
    times = sorted(r["summary"]["time_minutes"] for r in with_time)
    ratings = sorted(r["summary"]["rating"] for r in with_rating)

    coverage = {
        "time_minutes": len(with_time),
        "rating": len(with_rating),
        "servings": len(with_servings),
    }
    # A candidate signal must cover most of the corpus and actually vary to be
    # usable for deterministic tie-breaking (spec §4.2, RET-08).
    decision_basis: dict[str, Any] = {}
    for signal, values in (
        ("rating", ratings),
        ("time_minutes", times),
    ):
        coverage_ratio = round(len(values) / count, 3) if count else 0.0
        distinct = len(set(values))
        usable = coverage_ratio >= 0.8 and distinct >= 2
        decision_basis[signal] = {
            "coverage": coverage_ratio,
            "distinct_values": distinct,
            "usable_as_selection_signal": usable,
        }

    verdict = (
        "stable_id_baseline"
        if not any(b["usable_as_selection_signal"] for b in decision_basis.values())
        else "candidate_signal_available"
    )

    return {
        "count": count,
        "coverage": coverage,
        "time_minutes_distribution": {
            "min": times[0] if times else None,
            "median": times[len(times) // 2] if times else None,
            "max": times[-1] if times else None,
        },
        "rating_distribution": {
            "min": ratings[0] if ratings else None,
            "median": ratings[len(ratings) // 2] if ratings else None,
            "max": ratings[-1] if ratings else None,
        },
        "selection_signal_decision": {
            "basis": decision_basis,
            "verdict": verdict,
            "note": (
                "usable signal requires >= 0.8 coverage and >= 2 distinct values; "
                "otherwise the lowest-stable-recipe-ID baseline remains (spec §4.2)"
            ),
        },
        "variant_groups": sorted(
            {r["variant_group"] for r in records if r["variant_group"]}
        ),
        "category_counts": {
            category: sum(1 for r in records if category in r["categories"])
            for category in sorted({c for r in records for c in r["categories"]})
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="dataset.ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="full ingestion pipeline")
    subparsers.add_parser("rebuild", help="rebuild from manifest revisions")
    subparsers.add_parser("validate", help="validate committed corpus")
    subparsers.add_parser("analyze", help="EDA report")
    subparsers.add_parser("verify", help="rebuild in memory and diff vs committed")
    args = parser.parse_args()

    config = load_config()
    commands = {
        "build": cmd_build,
        "rebuild": cmd_rebuild,
        "validate": cmd_validate,
        "analyze": cmd_analyze,
        "verify": cmd_verify,
    }
    return commands[args.command](config)


if __name__ == "__main__":
    raise SystemExit(main())
