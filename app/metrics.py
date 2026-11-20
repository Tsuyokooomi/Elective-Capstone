"""Numbers for the admin dashboard."""
from collections import Counter
from datetime import timedelta

from sqlalchemy import select

from app.db.models import AuditLog, Conversation, Message, Ticket, ToolCall, utcnow


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p * (len(ordered) - 1))))
    return ordered[index]


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def compute_metrics(session) -> dict:
    conversations = session.scalars(select(Conversation)).all()
    messages = session.scalars(select(Message)).all()
    tickets = session.scalars(select(Ticket)).all()
    tool_calls = session.scalars(select(ToolCall)).all()
    audits = session.scalars(select(AuditLog)).all()

    total = len(conversations)
    ticket_conversation_ids = {t.conversation_id for t in tickets if t.conversation_id is not None}
    resolved_by_ai = sum(1 for c in conversations if c.resolved_by_ai)
    escalations = sum(1 for a in audits if a.action == "chat.escalated")
    blocked = sum(1 for a in audits if a.action == "guardrail.blocked")

    # Mean time to resolution, in minutes
    durations = [
        (t.resolved_at - t.created_at).total_seconds() / 60
        for t in tickets if t.resolved_at is not None and t.created_at is not None
    ]

    latencies = [m.latency_ms for m in messages if m.sender == "assistant" and m.latency_ms is not None]

    today = utcnow().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    per_day = Counter(m.created_at.date().isoformat() for m in messages
                      if m.sender == "user" and m.created_at is not None)

    return {
        "conversations": total,
        "messages": sum(1 for m in messages if m.sender == "user"),
        # Deflection: the user ended the chat satisfied and no human or ticket was needed
        "resolved_by_ai": resolved_by_ai,
        "deflection_rate": _rate(resolved_by_ai, total),
        # A looser view: chats that never produced a ticket
        "no_ticket_rate": _rate(total - len(ticket_conversation_ids & {c.id for c in conversations}), total),
        "escalations": escalations,
        "escalation_rate": _rate(escalations, total),
        "guardrail_blocks": blocked,
        "tickets": {
            "total": len(tickets),
            "by_status": dict(Counter(t.status for t in tickets)),
            "by_priority": dict(sorted(Counter(t.priority for t in tickets).items())),
        },
        "mttr_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        "latency_ms": {
            "count": len(latencies),
            "avg": round(sum(latencies) / len(latencies)) if latencies else None,
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
        },
        "intents": dict(Counter(m.intent for m in messages if m.sender == "assistant" and m.intent).most_common()),
        "tool_calls": [
            {"tool": tool, "status": status, "count": n}
            for (tool, status), n in sorted(Counter((c.tool_name, c.status) for c in tool_calls).items())
        ],
        "messages_per_day": [{"day": d, "messages": per_day.get(d, 0)} for d in days],
    }
