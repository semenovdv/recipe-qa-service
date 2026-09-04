import json

from evals.run import GOLDEN_PATH, load_corpus, validate_case


def test_golden_set_has_required_case_count_and_categories():
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert 12 <= len(cases) <= 15
    categories = {case["category"] for case in cases}
    assert {
        "direct recipe",
        "combined constraints",
        "out of domain",
        "safety/allergy",
    } <= categories


def test_eval_validates_response_contract_and_expected_source():
    corpus = load_corpus()
    case = {
        "expected": {"status": 200, "refused": False, "citation_any_of": [41709]},
    }
    body = {
        "answer": "supported",
        "citations": [
            {
                "title": corpus[41709]["title"],
                "url": corpus[41709]["url"],
            }
        ],
        "refused": False,
        "refusal_reason": None,
    }
    assert validate_case(case, 200, body, corpus) == []


def test_eval_rejects_wrong_refusal_reason():
    corpus = load_corpus()
    case = {
        "expected": {"status": 200, "refused": True, "refusal_reason": "safety"},
    }
    body = {
        "answer": "I cannot answer that.",
        "citations": [],
        "refused": True,
        "refusal_reason": "out_of_domain",
    }
    assert validate_case(case, 200, body, corpus)
