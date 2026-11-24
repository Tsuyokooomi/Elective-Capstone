import logging
import re
import time
from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.config import settings
from app.db.models import Conversation, KBDocument, Message, MessageSource, ToolCall, User, utcnow
from app.guardrails.injection import detect_injection
from app.guardrails.output import filter_output
from app.guardrails.pii import redact_pii
from app.rag.classifier import classify
from app.rag.generator import Answer, generate_answer
from app.rag.history import Context, build_context, contextual_question, unresolved_complaint
from app.rag.prompts import (
    CONFIRM_PASSWORD_RESET_MESSAGE,
    COMPANY,
    ESCALATION_MESSAGE,
    INJECTION_BLOCKED_MESSAGE,
    INTENTS,
    NO_ANSWER_MESSAGE,
    NO_MATCH_TWICE_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    PRIORITY_BY_INTENT,
    UNRESOLVED_MESSAGE,
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
    find_open_ticket,
    find_pending,
    parse_confirmation,
    ticket_key,
)
from app.tools.function_calling import choose_tool
from app.tools.webhook import send_webhook

logger = logging.getLogger("aihas")

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
    guardrail_flags: list[str] = field(default_factory=list)      # what the output filter changed


def _resolved_by_assistant(session, conversation) -> bool:
    """True if the assistant answered something in this chat and no ticket or agent was involved."""
    if conversation.status == "escalated" or find_open_ticket(session, conversation.id) is not None:
        return False
    previous = session.scalars(
        select(Message).where(Message.conversation_id == conversation.id, Message.sender == "assistant")
    ).all()
    return any(m.intent not in (None, "chitchat") for m in previous)


def _agent_handling_response(conversation) -> dict:
    return {
        "conversation_id": conversation.id, "message_id": None, "reply": "", "intent": None,
        "confidence": None, "route": "agent", "tool": None, "sources": [], "grounded": False,
        "invalid_citations": [], "escalated": True, "agent_handling": True,
        "pending_confirmation": False, "ticket_key": None, "tool_result": None, "tool_source": None,
        "pii_redacted": False, "latency_ms": 0,
    }


def _rag(question, retriever, answer_llm, out: Outcome, query=None, history=None):
    """Search, answer, then check the answer. query is the text to search with (it can include the
    earlier question for a follow-up). history is the earlier turns given to the model."""
    search = retriever.search(query or question)
    answer = generate_answer(question, search, answer_llm, history=history)
    if answer.used_llm:   # only LLM text is filtered: our own fixed messages are trusted
        safe_text, flags = filter_output(answer.text)
        if flags:
            out.guardrail_flags = flags
            answer.text = safe_text
            if "prompt_leak" in flags or "asks_for_secret" in flags:   # the text was replaced, so nothing is cited
                answer.cited_sop_ids, answer.grounded = [], False
    return search, answer


def _sop_matches(retriever, query: str) -> bool:
    """True if the knowledge base has a good match. Same bar as the "no procedure found" rule."""
    search = retriever.search(query)
    return bool(search.chunks) and search.best_vector_score >= settings.min_vector_score


def _count_grounded(session, prior: list[Message]) -> int:
    """How many earlier assistant answers in this chat cited at least one SOP."""
    ids = [m.id for m in prior if m.sender == "assistant"]
    if not ids:
        return 0
    return session.scalar(
        select(func.count(func.distinct(MessageSource.message_id))).where(MessageSource.message_id.in_(ids))
    ) or 0


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


def _hand_off(session, user, conversation, reason_text, priority, intent, source, out: Outcome,
              prefix: str = "", rule: str | None = None) -> None:
    """Open (or reuse) a ticket and hand the chat to a human agent."""
    ticket, created = escalate(session, user, conversation, reason_text[:150], priority)
    key = ticket_key(ticket.id)
    out.escalated, out.ticket_key, out.tool = True, key, "escalate_to_human"
    template = ESCALATION_MESSAGE if created else ESCALATION_REUSED_MESSAGE
    handoff = template.format(priority=ticket.priority, ticket_id=key)
    out.reply = f"{prefix}\n\n{handoff}" if prefix else handoff
    out.tool_result = {"ticket_key": key, "priority": ticket.priority, "reused": not created}
    if rule:
        out.tool_result["rule"] = rule   # which escalation rule fired
    out.new_tool_calls.append({
        "tool_name": "escalate_to_human",
        "arguments": {"args": {"reason": reason_text[:150], "priority": priority}, "intent": intent, "source": source},
        "status": "completed", "result": out.tool_result, "audit": "tool.completed",
    })
    if created:
        out.events.append(("ticket.escalated", {"ticket_key": key, "priority": ticket.priority,
                                                "intent": intent, "employee_id": user.employee_id}))


def _handle_new(session, clean, user, conversation, retriever, answer_llm, classifier_llm, tool_llm,
                out: Outcome, ctx: Context) -> None:
    contextual = contextual_question(clean, ctx)   # earlier question + follow-up, or None
    rule = None

    if check_security_patterns(clean):
        out.intent, out.confidence = "security_incident", 1.0   # rule match, runs before the LLM
        source = "rules"
    elif unresolved_complaint(clean) and ctx.grounded_answers >= settings.max_unresolved_answers:
        # "it still does not work" after the assistant already answered twice: a person takes over
        rule, source, out.confidence = "unresolved_after_answers", "rule", 1.0
    else:
        result = classify(contextual or clean, classifier_llm)
        out.intent, out.confidence = result["intent"], result["confidence"]
        source = "classifier"
        if out.intent == "out_of_scope" and out.confidence < settings.classifier_min_confidence:
            out.intent = None   # classifier is unsure: let retrieval decide

    if rule:
        out.route = "escalate"
        _hand_off(session, user, conversation, contextual or clean, "P3", out.intent, source, out,
                  prefix=UNRESOLVED_MESSAGE, rule=rule)
        return

    intent = out.intent
    spec = INTENTS.get(intent)
    if spec:
        out.route, out.tool = spec["route"], spec["tool"]

    if out.route == "decline" and _sop_matches(retriever, contextual or clean):
        # The classifier said "not IT support", but an SOP matches strongly. If we have a procedure for
        # it, it is in scope: trust the knowledge base and answer from it.
        logger.info("Out-of-scope label overridden by an SOP match")
        intent = out.intent = None
        out.route, out.tool = "answer", None

    if out.route == "decline":
        out.reply = OUT_OF_SCOPE_MESSAGE
    elif intent == "chitchat":
        thanks = re.search(r"\b(thanks|thank you|salamat)\b", clean.lower())
        out.reply = THANKS_REPLY if thanks else GREETING_REPLY
        if thanks and _resolved_by_assistant(session, conversation):
            conversation.status, conversation.resolved_by_ai, conversation.ended_at = "resolved", True, utcnow()
    elif out.route == "escalate":
        priority = PRIORITY_BY_INTENT.get(intent, "P3")
        prefix = ""
        if spec["sops"]:
            out.search, out.answer = _rag(clean, retriever, answer_llm, out)
            prefix = out.answer.text
        _hand_off(session, user, conversation, clean, priority, intent, source, out, prefix=prefix)
    elif out.route == "action" and _propose_action(session, intent, clean, user, tool_llm, out):
        pass
    else:
        out.search, out.answer = _rag(clean, retriever, answer_llm, out, query=contextual, history=ctx.turns)
        out.reply = out.answer.text
        if out.answer.text == NO_ANSWER_MESSAGE and ctx.last_assistant == NO_ANSWER_MESSAGE:
            # no procedure found twice in a row: stop guessing and bring in a person
            out.route = "escalate"
            _hand_off(session, user, conversation, contextual or clean, "P3", intent, "rule", out,
                      prefix=NO_MATCH_TWICE_MESSAGE, rule="no_match_twice")


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

    if conversation.status == "resolved":   # the user came back, so the chat is open again
        conversation.status, conversation.resolved_by_ai, conversation.ended_at = "open", False, None

    # What was said earlier in this chat (stored text only, so it is already redacted)
    prior = session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)).all()
    ctx = build_context([(m.sender, m.content) for m in prior], _count_grounded(session, prior))

    # Store only the redacted text
    clean, pii_found = redact_pii(req.message)
    session.add(Message(conversation_id=conversation.id, sender="user", content=clean))

    # Human in the loop: once an agent has claimed the ticket, the bot stays silent.
    if conversation.status == "escalated":
        open_ticket = find_open_ticket(session, conversation.id)
        if open_ticket is not None and open_ticket.assigned_to is not None:
            session.commit()
            response = _agent_handling_response(conversation)
            response["pii_redacted"] = bool(pii_found)
            return response

    started = time.perf_counter()
    out = Outcome()

    attack = detect_injection(clean)
    if attack:
        out.route, out.reply = "blocked", INJECTION_BLOCKED_MESSAGE
        audit(session, user.id, "guardrail.blocked", "conversation", conversation.id)
        logger.warning("Blocked a message from %s: %s", user.employee_id, attack)
    else:
        pending = find_pending(session, conversation.id)
        handled = bool(pending) and _handle_pending(session, pending, clean, user, conversation, out)
        if not handled:
            _handle_new(session, clean, user, conversation, retriever, answer_llm, classifier_llm,
                        tool_llm, out, ctx)

    if out.guardrail_flags:
        audit(session, user.id, "guardrail.output_filtered", "conversation", conversation.id)
        logger.warning("Output filter changed a reply for %s: %s", user.employee_id, out.guardrail_flags)

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
        "guardrail_flags": out.guardrail_flags,
        "latency_ms": latency_ms,
    }
