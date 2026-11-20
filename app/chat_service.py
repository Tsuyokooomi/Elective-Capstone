import re
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import settings
from app.db.models import Conversation, KBDocument, Message, MessageSource, ToolCall, User, utcnow
from app.guardrails.injection import looks_like_injection
from app.guardrails.pii import redact_pii
from app.rag.classifier import classify
from app.rag.generator import Answer, generate_answer
from app.rag.prompts import (
    CONFIRM_PASSWORD_RESET_MESSAGE,
    COMPANY,
    ESCALATION_MESSAGE,
    INJECTION_BLOCKED_MESSAGE,
    INTENTS,
    OUT_OF_SCOPE_MESSAGE,
    PRIORITY_BY_INTENT,
    check_security_patterns,
)
from app.rag.retriever import SearchResult
from app.tools.executor import (
    CANCELLED_MESSAGE,
    CONFIRM_TICKET_MESSAGE,
    ESCALATION_REUSED_MESSAGE,
    FIRST_RESPONSE,
    RESET_DONE_MESSAGE,
    RESET_LIMIT_MESSAGE,
    TICKET_CREATED_MESSAGE,
    ToolError,
    audit,
    cancel_tool_call,
    count_recent_resets,
    escalate,
    execute_tool_call,
    find_pending,
    parse_confirmation,
    ticket_key,
)
from app.tools.function_calling import choose_tool
from app.tools.webhook import send_webhook

GREETING_REPLY = f"Hello! I'm the {COMPANY} IT helpdesk assistant. What can I help you with?"
THANKS_REPLY = "You're welcome! Tell me if you need anything else."
HANDOFF_ONLY = "I am connecting you to a human agent now. Please stay in this chat."


class NotFound(Exception):
    pass


@dataclass
class Outcome:
    reply: str = ""
    intent: str | None = None
    confidence: float | None = None
    route: str = "answer"
    tool: str | None = None
    search: SearchResult | None = None
    answer: Answer | None = None
    escalated: bool = False
    pending_confirmation: bool = False
    ticket_key: str | None = None
    tool_result: dict | None = None
    tool_source: str | None = None   # "llm" or "fallback" for proposed actions
    new_tool_calls: list[dict] = field(default_factory=list)   # saved after the assistant message exists
    events: list[tuple[str, dict]] = field(default_factory=list)  # webhook events, sent after commit


def _rag(question, retriever, answer_llm):
    search = retriever.search(question)
    return search, generate_answer(question, search, answer_llm)


def _handle_pending(session, pending, text, user, conversation, out: Outcome) -> bool:
    """Handle a reply to a confirmation question. Returns False if the message is a new request."""
    decision = parse_confirmation(text)
    if decision is None or check_security_patterns(text):
        cancel_tool_call(session, pending, user, "superseded by a new message")
        return False

    meta = pending.arguments or {}
    out.intent, out.route, out.tool = meta.get("intent"), "action", pending.tool_name

    if decision == "no":
        cancel_tool_call(session, pending, user, "declined by the user")
        out.reply = CANCELLED_MESSAGE
        return True

    pending.confirmed_at = utcnow()
    audit(session, user.id, "tool.confirmed", "tool_call", pending.id)
    try:
        result, events = execute_tool_call(session, pending, user, conversation)
    except ToolError as exc:
        out.reply = str(exc)
        return True

    out.tool_result, out.events = result, events
    if pending.tool_name == "reset_password":
        out.reply = RESET_DONE_MESSAGE.format(email=result["email"], minutes=result["expires_in_minutes"])
    else:
        out.ticket_key = result["ticket_key"]
        out.reply = TICKET_CREATED_MESSAGE.format(
            key=result["ticket_key"], priority=result["priority"], sla=FIRST_RESPONSE[result["priority"]])
    return True


def _propose_action(session, intent, clean, user, tool_llm, out: Outcome) -> bool:
    """Ask the LLM to pick the tool and its arguments, then ask the user to confirm.
    Returns False if the intent has no tool."""
    choice = choose_tool(tool_llm, intent, clean)
    if choice is None:
        return False
    out.tool, out.tool_source = choice.name, choice.source

    if choice.name == "reset_password":
        if count_recent_resets(session, user.id) >= settings.max_resets_per_hour:
            out.reply = RESET_LIMIT_MESSAGE.format(limit=settings.max_resets_per_hour)
            return True
        out.reply = CONFIRM_PASSWORD_RESET_MESSAGE.format(employee_id=user.employee_id)
    else:
        out.reply = CONFIRM_TICKET_MESSAGE.format(
            title=choice.args["title"], category=choice.args["category"], priority=choice.args["priority"])

    out.pending_confirmation = True
    out.new_tool_calls.append({
        "tool_name": choice.name,
        "arguments": {"args": choice.args, "intent": intent, "source": choice.source},
        "status": "pending_confirmation",
        "audit": "tool.proposed",
    })
    return True


def _handle_new(session, clean, user, conversation, retriever, answer_llm, classifier_llm, tool_llm,
                out: Outcome) -> None:
    if check_security_patterns(clean):
        out.intent, out.confidence = "security_incident", 1.0   # rule match, runs before the LLM
        source = "rules"
    else:
        result = classify(clean, classifier_llm)
        out.intent, out.confidence = result["intent"], result["confidence"]
        source = "classifier"
        if out.intent == "out_of_scope" and out.confidence < settings.classifier_min_confidence:
            out.intent = None   # classifier is unsure: let retrieval decide

    intent = out.intent
    spec = INTENTS.get(intent)
    if spec:
        out.route, out.tool = spec["route"], spec["tool"]

    if out.route == "decline":
        out.reply = OUT_OF_SCOPE_MESSAGE
    elif intent == "chitchat":
        thanks = re.search(r"\b(thanks|thank you|salamat)\b", clean.lower())
        out.reply = THANKS_REPLY if thanks else GREETING_REPLY
    elif out.route == "escalate":
        priority = PRIORITY_BY_INTENT.get(intent, "P3")
        ticket, created = escalate(session, user, conversation, clean[:150], priority)
        key = ticket_key(ticket.id)
        out.escalated, out.ticket_key = True, key
        template = ESCALATION_MESSAGE if created else ESCALATION_REUSED_MESSAGE
        handoff = template.format(priority=ticket.priority, ticket_id=key)
        if spec["sops"]:
            out.search, out.answer = _rag(clean, retriever, answer_llm)
            out.reply = out.answer.text + "\n\n" + handoff
        else:
            out.reply = handoff
        out.tool = "escalate_to_human"
        out.tool_result = {"ticket_key": key, "priority": ticket.priority, "reused": not created}
        out.new_tool_calls.append({
            "tool_name": "escalate_to_human",
            "arguments": {"args": {"reason": clean[:150], "priority": priority}, "intent": intent, "source": source},
            "status": "completed", "result": out.tool_result, "audit": "tool.completed",
        })
        if created:
            out.events.append(("ticket.escalated", {"ticket_key": key, "priority": ticket.priority,
                                                    "intent": intent, "employee_id": user.employee_id}))
    elif out.route == "action" and _propose_action(session, intent, clean, user, tool_llm, out):
        pass
    else:
        out.search, out.answer = _rag(clean, retriever, answer_llm)
        out.reply = out.answer.text


def handle_chat(session, req, retriever, answer_llm, classifier_llm, tool_llm=None, notify=send_webhook) -> dict:
    user = session.scalar(select(User).where(User.employee_id == req.employee_id))
    if user is None:
        raise NotFound("Unknown employee_id")

    if req.conversation_id is not None:
        conversation = session.get(Conversation, req.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise NotFound("Conversation not found")
    else:
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.flush()

    # Store only the redacted text
    clean, pii_found = redact_pii(req.message)
    session.add(Message(conversation_id=conversation.id, sender="user", content=clean))

    started = time.perf_counter()
    out = Outcome()

    if looks_like_injection(clean):
        out.route, out.reply = "blocked", INJECTION_BLOCKED_MESSAGE
        audit(session, user.id, "guardrail.blocked", "conversation", conversation.id)
    else:
        pending = find_pending(session, conversation.id)
        handled = bool(pending) and _handle_pending(session, pending, clean, user, conversation, out)
        if not handled:
            _handle_new(session, clean, user, conversation, retriever, answer_llm, classifier_llm,
                        tool_llm, out)

    latency_ms = int((time.perf_counter() - started) * 1000)

    assistant = Message(conversation_id=conversation.id, sender="assistant", content=out.reply,
                        intent=out.intent, latency_ms=latency_ms)
    session.add(assistant)
    session.flush()

    for record in out.new_tool_calls:
        call = ToolCall(message_id=assistant.id, tool_name=record["tool_name"], arguments=record["arguments"],
                        result=record.get("result"), status=record["status"])
        session.add(call)
        session.flush()
        audit(session, user.id, record["audit"], "tool_call", call.id)

    sources = []
    if out.answer is not None:
        for sop_id in out.answer.cited_sop_ids:
            chunk = next(c for c in out.search.chunks if c.sop_id == sop_id)   # best chunk of that SOP
            score = chunk.vector_score if chunk.vector_score is not None else chunk.score
            sources.append({"sop_id": sop_id, "title": chunk.title, "chunk_id": chunk.chunk_id,
                            "score": round(score, 4)})
            doc = session.scalar(select(KBDocument).where(KBDocument.sop_id == sop_id))
            if doc is not None:
                session.add(MessageSource(message_id=assistant.id, kb_document_id=doc.id,
                                          chunk_ref=chunk.chunk_id, score=score))
    session.commit()

    for event, payload in out.events:   # after commit, so a slow webhook cannot block the database
        notify(event, payload)

    return {
        "conversation_id": conversation.id,
        "message_id": assistant.id,
        "reply": out.reply,
        "intent": out.intent,
        "confidence": out.confidence,
        "route": out.route,
        "tool": out.tool,
        "sources": sources,
        "grounded": bool(out.answer and out.answer.grounded),
        "invalid_citations": out.answer.invalid_citations if out.answer else [],
        "escalated": out.escalated,
        "pending_confirmation": out.pending_confirmation,
        "ticket_key": out.ticket_key,
        "tool_result": out.tool_result,
        "tool_source": out.tool_source,
        "pii_redacted": bool(pii_found),
        "latency_ms": latency_ms,
    }
