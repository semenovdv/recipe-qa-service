"""Run the golden /ask evaluation against a running service.

Usage:
    python -m evals.run
    EVAL_BASE_URL=http://localhost:8000 python -m evals.run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app.schemas import AskResponse

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "evals" / "golden.json"
DEFAULT_BASE_URL = "http://localhost:8000"


def load_corpus() -> dict[int, dict]:
    records: dict[int, dict] = {}
    for path in sorted((ROOT / "dataset" / "enriched").glob("*.json")):
        if path.name == "report.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["pageid"]] = record
    return records


def call_ask(base_url: str, question: str) -> tuple[int, dict, float]:
    payload = json.dumps({"question": question}).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/ask",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=130) as response:
            status = response.status
            body = json.loads(response.read())
    except HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read())
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    return status, body, (time.perf_counter() - started) * 1000


def cited_pageids(body: dict, corpus: dict[int, dict]) -> tuple[set[int], list[str]]:
    by_url = {record["url"]: pageid for pageid, record in corpus.items()}
    by_title = {record["title"]: pageid for pageid, record in corpus.items()}
    ids: set[int] = set()
    errors: list[str] = []
    for citation in body.get("citations", []):
        pageid = by_url.get(citation.get("url"))
        if pageid is None:
            pageid = by_title.get(citation.get("title"))
        if pageid is None:
            errors.append(f"unknown citation: {citation}")
        else:
            ids.add(pageid)
    return ids, errors


def check_constraints(
    cited: set[int], constraints: dict, corpus: dict[int, dict]
) -> list[str]:
    errors: list[str] = []
    for pageid in cited:
        record = corpus[pageid]
        summary = record.get("summary") or {}
        time_minutes = summary.get("time_minutes")
        if "max_time_minutes" in constraints:
            if time_minutes is None or time_minutes > constraints["max_time_minutes"]:
                errors.append(f"pageid {pageid} does not satisfy max time")
        required_tag = constraints.get("required_diet_tag")
        if required_tag and required_tag not in (record.get("diet_tags") or []):
            errors.append(f"pageid {pageid} lacks diet tag {required_tag}")
        ingredients = " ".join(record.get("ingredients_normalized") or []).lower()
        required_ingredient = constraints.get("required_ingredient")
        if required_ingredient and required_ingredient.lower() not in ingredients:
            errors.append(f"pageid {pageid} lacks ingredient {required_ingredient}")
        excluded = constraints.get("excluded_ingredient")
        if excluded and excluded.lower() in ingredients:
            errors.append(f"pageid {pageid} contains excluded ingredient {excluded}")
    return errors


def validate_case(case: dict, status: int, body: dict, corpus: dict[int, dict]) -> list[str]:
    expected = case["expected"]
    errors: list[str] = []
    if status != expected["status"]:
        return [f"expected HTTP {expected['status']}, got {status}: {body}"]
    if status != 200:
        if not body.get("type", "").endswith(expected.get("error_slug", "")):
            errors.append(f"unexpected error body: {body}")
        return errors

    try:
        response = AskResponse.model_validate(body)
    except ValidationError as exc:
        return [f"response schema invalid: {exc.errors()[:2]}"]
    if response.refused != expected["refused"]:
        errors.append(f"expected refused={expected['refused']}, got {response.refused}")
    if response.refused:
        if response.refusal_reason != expected.get("refusal_reason"):
            errors.append(
                f"expected refusal_reason={expected.get('refusal_reason')}, "
                f"got {response.refusal_reason}"
            )
        if response.citations:
            errors.append("refusal must not contain citations")
        return errors

    cited, citation_errors = cited_pageids(body, corpus)
    errors.extend(citation_errors)
    any_of = set(expected.get("citation_any_of", []))
    all_of = set(expected.get("citation_all_of", []))
    if any_of and not cited.intersection(any_of):
        errors.append(f"none of expected sources cited: {sorted(any_of)}; got {sorted(cited)}")
    if all_of and not all_of.issubset(cited):
        errors.append(f"missing expected sources: {sorted(all_of - cited)}; got {sorted(cited)}")
    errors.extend(check_constraints(cited, expected.get("constraints", {}), corpus))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "report.json")
    args = parser.parse_args()

    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    corpus = load_corpus()
    results = []
    for case in cases:
        try:
            status, body, latency_ms = call_ask(args.base_url, case["question"])
            errors = validate_case(case, status, body, corpus)
            result = {
                "id": case["id"],
                "category": case["category"],
                "passed": not errors,
                "status": status,
                "latency_ms": round(latency_ms),
                "errors": errors,
            }
        except RuntimeError as exc:
            result = {
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "errors": [str(exc)],
            }
        results.append(result)
        marker = "PASS" if result["passed"] else "FAIL"
        print(f"{marker:4} {case['id']}")

    passed = sum(result["passed"] for result in results)
    report = {
        "base_url": args.base_url,
        "corpus_records": len(corpus),
        "cases": results,
        "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(results)} passed; report={args.output}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
