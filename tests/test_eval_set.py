import json
import re
from collections import Counter
from pathlib import Path

from app.rag.prompts import INTENTS, check_security_patterns

ROOT = Path(__file__).resolve().parent.parent
ITEMS = json.loads((ROOT / "tests" / "eval_set.json").read_text(encoding="utf-8"))
KB_IDS = {re.match(r"(KB-\d+)", p.name).group(1) for p in (ROOT / "kb").glob("KB-*.md")}
ROUTES = {"answer", "action", "escalate", "decline", "blocked"}
REQUIRED = {"id", "question", "language", "type", "expected_intent", "expected_route",
            "expected_tool", "expected_sops", "expect_no_answer", "expect_pattern_match", "notes"}


def test_ids_are_unique_and_fields_complete():
    ids = [i["id"] for i in ITEMS]
    assert len(ids) == len(set(ids))
    for item in ITEMS:
        assert REQUIRED <= item.keys(), item["id"]


def test_intents_routes_and_sops_are_valid():
    for item in ITEMS:
        assert item["expected_route"] in ROUTES, item["id"]
        if item["expected_intent"] is not None:
            assert item["expected_intent"] in INTENTS, item["id"]
            assert item["expected_route"] == INTENTS[item["expected_intent"]]["route"], item["id"]
        for sop in item["expected_sops"]:
            assert sop in KB_IDS, f'{item["id"]}: unknown {sop}'


def test_every_intent_has_at_least_two_questions():
    counts = Counter(i["expected_intent"] for i in ITEMS)
    for name in INTENTS:
        assert counts[name] >= 2, f"{name} has {counts[name]}"


def test_every_sop_is_covered_by_a_question():
    covered = {s for i in ITEMS for s in i["expected_sops"]}
    missing = sorted(KB_IDS - covered)
    assert not missing, f"SOPs with no question: {missing}"


def test_security_pattern_cases_match():
    for item in ITEMS:
        if item["expect_pattern_match"]:
            assert check_security_patterns(item["question"]) == "security_incident", item["id"]


def test_normal_questions_do_not_trigger_security_patterns():
    for item in ITEMS:
        if item["expected_intent"] not in ("security_incident", None):
            assert check_security_patterns(item["question"]) is None, item["id"]
