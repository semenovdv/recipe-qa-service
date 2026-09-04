"""Deterministic DB seeder — ADR-003 D3.

Loads the committed corpus + enriched artifacts, embeds each record, and
mirrors the corpus into Postgres (pgvector). The database is never
hand-edited: every run converges to exactly the committed corpus state
(upsert + stale-row cleanup + count verification).

Usage:
    python -m scripts.db_seed             # dry run: build rows, no DB writes
    python -m scripts.db_seed --apply     # apply schema + upsert + verify

Requires DATABASE_URL (see .env.example) and OPENAI_API_KEY for --apply.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from app.db import EMBEDDING_DIM, build_row, embedding_text, merge_sql

ROOT = Path(__file__).resolve().parent.parent
ENRICHED_DIR = ROOT / "dataset" / "enriched"
CORPUS_INDEX = ROOT / "dataset" / "corpus" / "index.json"
SCHEMA_PATH = ROOT / "db" / "schema.sql"


def load_records() -> tuple[str, list[dict]]:
    """Load enriched records merged with corpus summary fields."""
    index = json.loads(CORPUS_INDEX.read_text(encoding="utf-8"))
    corpus_version = index["corpus_version"]
    records = []
    for path in sorted(ENRICHED_DIR.glob("*.json")):
        if path.name == "report.json":
            continue
        enriched = json.loads(path.read_text(encoding="utf-8"))
        pageid = enriched.get("pageid")
        if pageid is None:
            raise ValueError(f"enriched record without pageid: {path.name}")
        summary = enriched.get("summary") or {}
        records.append({
            **enriched,
            "time_minutes": summary.get("time_minutes"),
            "servings": _parse_servings(summary.get("servings")),
        })
    return corpus_version, records


def _parse_servings(raw: object) -> int | None:
    """Servings like '4–6' are ambiguous ranges -> None (SPEC 4.6)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    if any(sep in text for sep in ("–", "-", "—", "/")):
        return None  # a range or fraction is ambiguous; honest None
    return int(digits)


def build_rows(records: list[dict], corpus_version: str,
               embeddings: dict[int, list[float]]) -> list[dict]:
    rows = []
    for rec in records:
        rows.append(build_row(
            rec, corpus_version=corpus_version,
            embedding=embeddings[rec["pageid"]],
        ))
    return rows


def fetch_embeddings(records: list[dict]) -> dict[int, list[float]]:
    """Embed each record via text-embedding-3-small (ADR-001 D3)."""
    from openai import OpenAI

    client = OpenAI()
    out: dict[int, list[float]] = {}
    batch: list[dict] = []
    texts: list[str] = []

    def flush():
        if not batch:
            return
        resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
        for rec, data in zip(batch, resp.data):
            if len(data.embedding) != EMBEDDING_DIM:
                raise ValueError("unexpected embedding dimension from provider")
            out[rec["pageid"]] = data.embedding
        batch.clear()
        texts.clear()

    for rec in records:
        batch.append(rec)
        texts.append(embedding_text(rec))
        if len(batch) >= 64:
            flush()
    flush()
    return out


def apply(corpus_version: str, records: list[dict]) -> None:
    from app.settings import get_settings

    url = get_settings().database_url
    if not url:
        sys.exit("DATABASE_URL is not set (see .env.example)")

    import psycopg

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        print("Applying schema...")
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        cur.execute("SELECT pageid, corpus_version FROM recipes")
        existing = {pageid: version for pageid, version in cur.fetchall()}
        records_to_embed = [
            record for record in records
            if existing.get(record["pageid"]) != corpus_version
        ]
        print(f"Embedding {len(records_to_embed)} new or changed records...")
        embeddings = fetch_embeddings(records_to_embed) if records_to_embed else {}
        rows = build_rows(records_to_embed, corpus_version, embeddings)
        print(f"Upserting {len(rows)} rows...")
        t0 = time.time()
        if rows:
            cur.executemany(merge_sql(), rows)
        # Stale-row cleanup: corpus may have shrunk since last seed.
        cur.execute(
            "DELETE FROM recipes WHERE corpus_version <> %s", (corpus_version,)
        )
        cur.execute("SELECT count(*), min(corpus_version) FROM recipes")
        count, version = cur.fetchone()
        if count != len(records) or version != corpus_version:
            sys.exit(f"verification failed: {count} rows, version {version}")
        conn.commit()
    print(f"Seeded {count} rows at corpus_version={corpus_version} "
          f"in {time.time() - t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="apply schema and write to the database")
    args = parser.parse_args()

    corpus_version, records = load_records()
    print(f"corpus_version={corpus_version}, records={len(records)}")

    if not args.apply:
        rows = build_rows(
            records, corpus_version,
            embeddings={r["pageid"]: [0.0] * EMBEDDING_DIM for r in records},
        )
        print(f"DRY RUN: would embed and upsert {len(rows)} rows "
              f"(no DB writes, no API calls)")
        return

    apply(corpus_version, records)


if __name__ == "__main__":
    main()
