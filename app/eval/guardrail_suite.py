"""Deterministic guardrail tests from tests/eval_redteam.json: no LLM, no database, runs in seconds.

It checks four things: attacks are blocked, normal messages are not, personal data is redacted
(and support data is kept), and the output filter changes only what it should."""
from collections import defaultdict

from app.eval.metrics import rate
from app.guardrails.injection import detect_injection
from app.guardrails.output import filter_output
from app.guardrails.pii import redact_pii


def run_guardrail_suite(data: dict) -> dict:
    failures = []

    by_category = defaultdict(lambda: [0, 0])
    for attack in data["attacks"]:
        caught = detect_injection(attack["text"]) is not None
        by_category[attack["category"]][1] += 1
        by_category[attack["category"]][0] += caught
        if not caught:
            failures.append({"suite": "attack not blocked", "id": attack["id"], "text": attack["text"]})

    false_positives = [b for b in data["benign"] if detect_injection(b["text"]) is not None]
    for b in false_positives:
        failures.append({"suite": "normal message blocked", "id": b["id"], "text": b["text"],
                         "detail": detect_injection(b["text"])})

    pii_wrong = []
    for case in data["pii"]:
        _, found = redact_pii(case["text"])
        if set(found) != set(case["expect_tags"]):
            pii_wrong.append(case)
            failures.append({"suite": "PII", "id": case["id"], "text": case["text"],
                             "detail": f"expected {case['expect_tags']}, got {found}"})

    output_wrong = []
    for case in data["output"]:
        _, flags = filter_output(case["text"])
        if flags != case["expect_flags"]:
            output_wrong.append(case)
            failures.append({"suite": "output filter", "id": case["id"], "text": case["text"][:80],
                             "detail": f"expected {case['expect_flags']}, got {flags}"})

    caught_total = sum(n for n, _ in by_category.values())
    attack_total = sum(d for _, d in by_category.values())
    return {
        "attack_block_rate": {"num": caught_total, "den": attack_total, "rate": rate(caught_total, attack_total)},
        "by_category": {k: {"num": n, "den": d, "rate": rate(n, d)} for k, (n, d) in sorted(by_category.items())},
        "false_block_rate": {"num": len(false_positives), "den": len(data["benign"]),
                             "rate": rate(len(false_positives), len(data["benign"]))},
        "pii_accuracy": {"num": len(data["pii"]) - len(pii_wrong), "den": len(data["pii"]),
                         "rate": rate(len(data["pii"]) - len(pii_wrong), len(data["pii"]))},
        "output_filter_accuracy": {"num": len(data["output"]) - len(output_wrong), "den": len(data["output"]),
                                   "rate": rate(len(data["output"]) - len(output_wrong), len(data["output"]))},
        "failures": failures,
    }
