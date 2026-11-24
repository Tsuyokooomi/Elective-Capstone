"""Turns evaluation results into a Markdown report you can paste into the documentation."""

_PASS_LINE = 0.9    # rates below this are marked, so weak spots stand out


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def frac(block: dict) -> str:
    return f"{block['num']}/{block['den']} ({pct(block['rate'])})" if block["den"] else "n/a"


def _flag(value: float | None) -> str:
    return "" if value is None or value >= _PASS_LINE else " ⚠"


def _latency_row(name: str, s: dict) -> str:
    return f"| {name} | {s['n']} | {s['mean']} | {s['p50']} | {s['p95']} | {s['max']} |"


def render_markdown(meta: dict, items: dict | None, scenarios: dict | None, guardrails: dict | None) -> str:
    out = ["# Evaluation Report", "",
           f"Run on {meta['started']} · model `{meta['model']}` · embeddings `{meta['embed_model']}` · "
           f"min_vector_score {meta['min_vector_score']} · top_k {meta['top_k']}",
           f"Eval set: {meta.get('eval_items', 'n/a')} questions · {meta.get('scenario_count', 'n/a')} multi-turn scenarios · "
           f"LLM judge: {'on' if meta.get('judge') else 'off'}", ""]

    if items:
        out += ["## 1. Single-question evaluation", "",
                f"**{items['passed']}/{items['items']} questions passed every check ({pct(items['pass_rate'])}).**", "",
                "| Metric | Result | Meaning |", "|---|---|---|"]
        for name, m in items["metrics"].items():
            out.append(f"| {name} | {frac(m)}{_flag(m['rate'])} | {m['label']} |")
        if items["mrr"] is not None:
            out.append(f"| mrr | {items['mrr']:.2f} | Mean reciprocal rank of the expected SOP (1.00 = always first) |")
        out += ["", "### By language and by question type", "", "| Group | Passed |", "|---|---|"]
        for k, v in items["by_language"].items():
            out.append(f"| language: {k} | {frac(v)} |")
        for k, v in items["by_type"].items():
            out.append(f"| type: {k} | {frac(v)} |")
        out += ["", "### Latency (milliseconds, whole pipeline for one message)", "",
                "| Group | n | mean | p50 | p95 | max |", "|---|---|---|---|---|---|",
                _latency_row("all", items["latency"])]
        for route, s in items["latency_by_route"].items():
            out.append(_latency_row(f"route: {route}", s))
        if items["failures"]:
            out += ["", "### Failed questions", "", "| ID | Question | Failed checks | Route (got / expected) | Intent (got / expected) | Cited (invalid) |",
                    "|---|---|---|---|---|---|"]
            for f in items["failures"]:
                question = f["question"].replace("|", "\\|")[:70]
                cited = ", ".join(f.get("cited") or []) or "none"
                if f.get("invalid_citations"):
                    cited += f" ({', '.join(f['invalid_citations'])})"
                out.append(f"| {f['id']} | {question} | {', '.join(f['failed'])} | {f['route']} / {f['expected_route']} | "
                           f"{f['intent']} / {f['expected_intent']} | {cited} |")
        out.append("")

    if scenarios:
        out += ["## 2. Multi-turn scenarios", "",
                f"**{scenarios['passed']}/{scenarios['scenarios']} scenarios passed ({pct(scenarios['pass_rate'])})**, "
                f"{scenarios['turns_passed']}/{scenarios['turns']} individual turns correct.", "",
                "| Metric | Result | Meaning |", "|---|---|---|",
                f"| Ticket deflection rate | {frac(scenarios['deflection'])}{_flag(scenarios['deflection']['rate'])} | "
                "Routine first-level problems solved by the assistant with no ticket and no human |",
                f"| Correct hand-off | {frac(scenarios['correct_handoff'])}{_flag(scenarios['correct_handoff']['rate'])} | "
                "Security, MFA, human-request and repeated-failure cases that reached a person |",
                f"| Actions completed | {frac(scenarios['actions_completed'])}{_flag(scenarios['actions_completed']['rate'])} | "
                "Password resets and tickets done after the user confirmed (declined actions are not counted) |",
                "", f"Latency per message: p50 {scenarios['latency']['p50']} ms, p95 {scenarios['latency']['p95']} ms.", ""]
        if scenarios["failures"]:
            out += ["### Failed scenarios", ""]
            for f in scenarios["failures"]:
                out.append(f"- **{f['id']} {f['title']}**: ended as `{f['actual_outcome']}`, expected `{f['expected_outcome']}`."
                           + (f" Error: {f['error']}" if f.get("error") else ""))
                for p in f["problems"]:
                    out.append(f"  - {p}")
            out.append("")

    if guardrails:
        out += ["## 3. Guardrails (red-team set)", "", "| Metric | Result |", "|---|---|",
                f"| Attacks blocked | {frac(guardrails['attack_block_rate'])}{_flag(guardrails['attack_block_rate']['rate'])} |",
                f"| Normal messages wrongly blocked | {frac(guardrails['false_block_rate'])} |",
                f"| PII redaction cases correct | {frac(guardrails['pii_accuracy'])}{_flag(guardrails['pii_accuracy']['rate'])} |",
                f"| Output filter cases correct | {frac(guardrails['output_filter_accuracy'])}{_flag(guardrails['output_filter_accuracy']['rate'])} |",
                "", "| Attack category | Blocked |", "|---|---|"]
        for k, v in guardrails["by_category"].items():
            out.append(f"| {k} | {frac(v)} |")
        if guardrails["failures"]:
            out += ["", "### Guardrail failures", ""]
            for f in guardrails["failures"]:
                out.append(f"- {f['suite']} {f['id']}: `{f['text']}` {f.get('detail', '')}")
        out.append("")

    out += ["## Notes", "",
            "- Questions run through the same pipeline as the live API, against a scratch database, with the real models.",
            "- ⚠ marks a result below 90%.",
            "- A small local model is not a reliable judge of itself. Treat the LLM-judge numbers as a rough signal; "
            "the deterministic checks (citations, numbers found in the SOP) are the firm evidence."]
    return "\n".join(out) + "\n"
