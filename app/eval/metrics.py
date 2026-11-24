"""Scoring functions for the evaluation (Phase 5D).

Everything here is plain Python: no database, no LLM, no network. The runner (run_eval.py) gathers
the results, and these functions turn them into numbers. That keeps the maths easy to test."""
import json
import re
import statistics
from collections import defaultdict

from app.rag.prompts import NO_ANSWER_MESSAGE

# What each check measures, in the words used in the report
LABELS = {
    "route": "Routing accuracy (answer / action / escalate / decline / blocked)",
    "intent": "Intent classification accuracy",
    "tool": "Tool choice (the right action is proposed and waits for YES)",
    "escalated": "Escalation recall (cases that must reach a person did)",
    "retrieval": "Retrieval hit rate (expected SOP among the retrieved chunks)",
    "cited": "Grounded answers (cites a correct SOP)",
    "no_invalid_citation": "Answers free of made-up citations",
    "no_answer": "Honest \"I don't have a procedure\" replies",
    "blocked": "Injection attempts blocked",
    "no_false_block": "Normal messages not blocked",
    "pii_redacted": "Personal data redacted",
    "numbers_supported": "Numbers in answers found in the cited SOP",
    "faithful": "Faithfulness (LLM judge)",
    "relevant": "Relevance (LLM judge)",
}
JUDGE_CHECKS = ("faithful", "relevant")   # subjective, so they never decide whether an item passed

_CITATION = re.compile(r"\[KB-\d+\]")
_LIST_NUMBER = re.compile(r"(?m)^\s*\d+[.)]\s+")
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")


# ---------------------------------------------------------------- small helpers

def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p * (len(ordered) - 1))))
    return float(ordered[index])


def rate(num: int, den: int) -> float | None:
    return num / den if den else None


def latency_summary(values_ms: list[float]) -> dict:
    if not values_ms:
        return {"n": 0, "mean": 0, "p50": 0, "p95": 0, "max": 0}
    return {"n": len(values_ms), "mean": round(statistics.mean(values_ms)), "p50": round(percentile(values_ms, 0.5)),
            "p95": round(percentile(values_ms, 0.95)), "max": round(max(values_ms))}


def reciprocal_rank(retrieved: list[str], expected: list[str]) -> float:
    """1 / rank of the first expected SOP in the retrieved list (0 if it is missing)."""
    for rank, sop_id in enumerate(retrieved, start=1):
        if sop_id in expected:
            return 1 / rank
    return 0.0


def unsupported_numbers(answer: str, source_text: str) -> list[str]:
    """Numbers in the answer that do not appear in the SOP text it cites (list numbering and
    [KB-xxx] tags are ignored). A cheap, strict check for invented times, limits and amounts."""
    text = _LIST_NUMBER.sub("", _CITATION.sub("", answer))
    missing = []
    for number in dict.fromkeys(_NUMBER.findall(text)):
        if not re.search(rf"(?<![\d.,:]){re.escape(number)}(?!\d)", source_text):
            missing.append(number)
    return missing


def parse_judge(raw: str) -> dict | None:
    """Read the judge model's JSON verdict. Returns {"faithful": bool, "relevant": bool, "reason": str} or None."""
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    def as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        return None

    faithful, relevant = as_bool(data.get("faithful")), as_bool(data.get("relevant"))
    if faithful is None or relevant is None:
        return None
    return {"faithful": faithful, "relevant": relevant, "reason": str(data.get("reason", ""))[:200]}


# ---------------------------------------------------------------- one question

def check_item(item: dict, result: dict, retrieved: list[str]) -> dict[str, bool]:
    """Which checks apply to this eval item, and did the pipeline pass each one?
    item: a row of tests/eval_set.json. result: the handle_chat response. retrieved: SOP ids in rank order."""
    kind, route = item["type"], item["expected_route"]
    expected = set(item["expected_sops"])
    checks: dict[str, bool] = {"route": result["route"] == route}

    if item["expected_intent"] is not None:
        checks["intent"] = result["intent"] == item["expected_intent"]
    if route == "action" and item["expected_tool"]:
        checks["tool"] = result["tool"] == item["expected_tool"] and bool(result["pending_confirmation"])
    if route == "escalate":
        checks["escalated"] = bool(result["escalated"])
    if kind == "injection":
        checks["blocked"] = result["route"] == "blocked"
    else:
        checks["no_false_block"] = result["route"] != "blocked"
    if kind == "pii":
        checks["pii_redacted"] = bool(result["pii_redacted"])
    if item["expect_no_answer"]:
        checks["no_answer"] = result["reply"] == NO_ANSWER_MESSAGE and not result["sources"]
    elif expected and route != "blocked":
        checks["retrieval"] = bool(expected & set(retrieved))
        if route == "answer":
            cited = {s["sop_id"] for s in result["sources"]}
            checks["cited"] = bool(result["grounded"]) and bool(cited & expected)
            checks["no_invalid_citation"] = not result["invalid_citations"]
    return checks


def passed(checks: dict[str, bool]) -> bool:
    return all(ok for name, ok in checks.items() if name not in JUDGE_CHECKS)


def summarize_items(rows: list[dict]) -> dict:
    """rows: one dict per eval item with keys id, type, language, route, latency_ms, checks, rr, error, ..."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_language: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    latencies, latency_by_route, reciprocal, failures = [], defaultdict(list), [], []
    ok_total = 0

    for row in rows:
        if row.get("error"):
            ok = False
        else:
            for name, ok_check in row["checks"].items():
                totals[name][1] += 1
                totals[name][0] += bool(ok_check)
            ok = passed(row["checks"])
            latencies.append(row["latency_ms"])
            latency_by_route[row["route"]].append(row["latency_ms"])
            if row.get("rr") is not None:
                reciprocal.append(row["rr"])
        ok_total += ok
        by_language[row["language"]][0] += ok
        by_language[row["language"]][1] += 1
        by_type[row["type"]][0] += ok
        by_type[row["type"]][1] += 1
        if not ok:
            failed = [n for n, v in row.get("checks", {}).items() if not v and n not in JUDGE_CHECKS]
            failures.append({"id": row["id"], "question": row["question"], "failed": failed or ["error"],
                             "expected_route": row.get("expected_route"), "route": row.get("route"),
                             "expected_intent": row.get("expected_intent"), "intent": row.get("intent"),
                             "error": row.get("error")})

    metrics = {name: {"label": LABELS.get(name, name), "num": n, "den": d, "rate": rate(n, d)}
               for name, (n, d) in totals.items()}
    return {
        "items": len(rows), "passed": ok_total, "pass_rate": rate(ok_total, len(rows)),
        "metrics": metrics,
        "mrr": statistics.mean(reciprocal) if reciprocal else None,
        "by_language": {k: {"num": n, "den": d, "rate": rate(n, d)} for k, (n, d) in sorted(by_language.items())},
        "by_type": {k: {"num": n, "den": d, "rate": rate(n, d)} for k, (n, d) in sorted(by_type.items())},
        "latency": latency_summary(latencies),
        "latency_by_route": {r: latency_summary(v) for r, v in sorted(latency_by_route.items())},
        "failures": failures,
    }


# ---------------------------------------------------------------- conversations

def check_turn(expect: dict, result: dict, extras: dict) -> list[str]:
    """Compare one turn of a scenario with what the pipeline did. Returns a list of problems."""
    problems: list[str] = []

    def want(key, actual):
        if key in expect and expect[key] != actual:
            problems.append(f"{key}: expected {expect[key]!r}, got {actual!r}")

    tool_result = result.get("tool_result") or {}
    want("route", result["route"])
    want("intent", result["intent"])
    want("tool", result["tool"])
    want("escalated", bool(result["escalated"]))
    want("grounded", bool(result["grounded"]))
    want("pending_confirmation", bool(result["pending_confirmation"]))
    want("pii_redacted", bool(result["pii_redacted"]))
    want("ticket", result["ticket_key"] is not None)
    want("rule", tool_result.get("rule"))
    want("no_answer", result["reply"] == NO_ANSWER_MESSAGE)
    want("email_sent", bool(extras.get("email_sent")))
    for key in expect.get("tool_result_has", []):
        if key not in tool_result:
            problems.append(f"tool_result is missing {key!r}")
    reply = result["reply"].lower()
    for text in expect.get("reply_contains", []):
        if text.lower() not in reply:
            problems.append(f"reply should contain {text!r}")
    for text in expect.get("reply_not_contains", []):
        if text.lower() in reply:
            problems.append(f"reply should not contain {text!r}")
    if "sop_any" in expect and not ({s["sop_id"] for s in result["sources"]} & set(expect["sop_any"])):
        problems.append(f"no cited SOP among {expect['sop_any']}")
    return problems


def classify_outcome(facts: dict) -> str:
    """How a conversation ended. facts: status, resolved_by_ai, grounded_messages, tools_completed,
    tools_cancelled, blocked (counts or flags read from the database)."""
    if facts["status"] == "escalated":
        return "escalated"
    if facts["tools_completed"]:
        return "action_done"
    if facts["tools_cancelled"]:
        return "cancelled"
    if facts["resolved_by_ai"]:
        return "resolved"
    if facts["blocked"] and facts["grounded_messages"]:
        return "blocked_then_answered"
    if facts["grounded_messages"]:
        return "answered"
    return "declined"


def summarize_scenarios(results: list[dict]) -> dict:
    """results: id, title, kind, expected_outcome, actual_outcome, turn_problems (list of lists), latencies, error."""
    def scenario_ok(r):
        return not r.get("error") and r["actual_outcome"] == r["expected_outcome"] and not any(r["turn_problems"])

    turns = [t for r in results if not r.get("error") for t in r["turn_problems"]]
    routine = [r for r in results if r["kind"] == "routine"]
    escalation = [r for r in results if r["kind"] == "escalation"]
    action = [r for r in results if r["kind"] == "action"]
    deflected = [r for r in routine if r.get("actual_outcome") in ("resolved", "answered")]
    handed_off = [r for r in escalation if r.get("actual_outcome") == "escalated"]
    done = [r for r in action if r.get("actual_outcome") == "action_done"]
    latencies = [ms for r in results for ms in r.get("latencies", [])]
    return {
        "scenarios": len(results), "passed": sum(scenario_ok(r) for r in results),
        "pass_rate": rate(sum(scenario_ok(r) for r in results), len(results)),
        "turns": len(turns), "turns_passed": sum(not t for t in turns), "turn_pass_rate": rate(sum(not t for t in turns), len(turns)),
        "deflection": {"num": len(deflected), "den": len(routine), "rate": rate(len(deflected), len(routine))},
        "correct_handoff": {"num": len(handed_off), "den": len(escalation), "rate": rate(len(handed_off), len(escalation))},
        "actions_completed": {"num": len(done), "den": len(action), "rate": rate(len(done), len(action))},
        "latency": latency_summary(latencies),
        "failures": [{"id": r["id"], "title": r["title"], "expected_outcome": r["expected_outcome"],
                      "actual_outcome": r.get("actual_outcome"), "problems": [p for t in r["turn_problems"] for p in t],
                      "error": r.get("error")} for r in results if not scenario_ok(r)],
    }
