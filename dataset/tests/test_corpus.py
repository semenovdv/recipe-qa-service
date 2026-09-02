"""Contract tests for the COMMITTED corpus (dataset/PLAN.md §9).

Keeps the checked-in dataset honest: if anyone edits corpus/ files by hand or
rebuilds with a drifted configuration, this test fails.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from dataset.validate import validate_corpus

CORPUS_DIR = pathlib.Path(__file__).parent.parent / "corpus"


def load_config() -> dict[str, Any]:
    return json.loads((CORPUS_DIR.parent / "config.json").read_text(encoding="utf-8"))


def load_records() -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((CORPUS_DIR / "recipes").glob("*.json"))
    ]


def test_corpus_exists_and_matches_index() -> None:
    config = load_config()
    records = load_records()
    index = json.loads((CORPUS_DIR / "index.json").read_text(encoding="utf-8"))
    assert index["count"] == len(records)
    assert config["corpus_floor"] <= len(records) <= config["corpus_ceiling"]


def test_corpus_satisfies_contract() -> None:
    config = load_config()
    records = load_records()
    errors = validate_corpus(
        records, config["corpus_floor"], config["corpus_ceiling"]
    )
    assert errors == [], "\n".join(errors)


def test_manifest_matches_records() -> None:
    records = load_records()
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert {str(r["pageid"]) for r in records} == set(manifest)
    for record in records:
        assert manifest[str(record["pageid"])] == record["revid"]
