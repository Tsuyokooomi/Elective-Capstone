import re
import time

from sqlalchemy import select

from app.config import settings
from app.db.models import Conversation, KBDocument, Message, MessageSource, User
from app.guardrails.injection import looks_like_injection
from app.guardrails.pii import redact_pii
from app.rag.classifier import classify
from app.rag.generator import generate_answer
from app.rag.prompts import (
    COMPANY,
    INJECTION_BLOCKED_MESSAGE,
    INTENTS,
    OUT_OF_SCOPE_MESSAGE,
    check_security_patterns,
)

GREETING_REPLY = f"Hello! I'm the {COMPANY} IT helpdesk assistant. What can I help you with?"
THANKS_REPLY = "You're welcome! Tell me if you need anything else."
HANDOFF_ONLY = "I am connecting you to a human agent now. Please stay in this chat."
HANDOFF_NOTE = "\n\nI have also asked a human agent to join this chat."


class NotFound(Exception):
    pass


def _rag(question, retriever, answer_llm):
    search = retriever.search(question)
    answer = generate_answer(question, search, answer_llm)
    return search, answer


def handle_chat(session, req, retriever, answer_llm, classifier_llm) -> dict:
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
    intent = confidence = tool = None
    route = "answer"
    reply = ""
    search = None
    answer = None
    escalated = False

    if looks_like_injection(clean):
        route, reply = "blocked", INJECTION_BLOCKED_MESSAGE
    else:
        if check_security_patterns(clean):
            intent, confidence = "security_incident", 1.0   # rule match, runs before the LLM
        else:
            result = classify(clean, classifier_llm)
            intent, confidence = result["intent"], result["confidence"]
            if intent == "out_of_scope" and confidence < settings.classifier_min_confidence:
                intent = None   # classifier is unsure: let retrieval decide

        spec = INTENTS.get(intent)
        if spec:
            route, tool = spec["route"], spec["tool"]

        if route == "decline":
            reply = OUT_OF_SCOPE_MESSAGE
        elif intent == "chitchat":
            thanks = re.search(r"\b(thanks|thank you|salamat)\b", clean.lower())
            reply = THANKS_REPLY if thanks else GREETING_REPLY
        elif route == "escalate":
            escalated = True
            conversation.status = "escalated"
            if spec["sops"]:
                search, answer = _rag(clean, retriever, answer_llm)
                reply = answer.text + HANDOFF_NOTE
            else:
                reply = HANDOFF_ONLY
        else:
            search, answer = _rag(clean, retriever, answer_llm)
            reply = answer.text

    latency_ms = int((time.perf_counter() - started) * 1000)

    assistant = Message(
        conversation_id=conversation.id, sender="assistant", content=reply,
        intent=intent, latency_ms=latency_ms,
    )
    session.add(assistant)
    session.flush()

    sources = []
    if answer is not None:
        for sop_id in answer.cited_sop_ids:
            chunk = next(c for c in search.chunks if c.sop_id == sop_id)   # best chunk of that SOP
            score = chunk.vector_score if chunk.vector_score is not None else chunk.score
            sources.append({"sop_id": sop_id, "title": chunk.title, "chunk_id": chunk.chunk_id,
                            "score": round(score, 4)})
            doc = session.scalar(select(KBDocument).where(KBDocument.sop_id == sop_id))
            if doc is not None:
                session.add(MessageSource(message_id=assistant.id, kb_document_id=doc.id,
                                          chunk_ref=chunk.chunk_id, score=score))
    session.commit()

    return {
        "conversation_id": conversation.id,
        "message_id": assistant.id,
        "reply": reply,
        "intent": intent,
        "confidence": confidence,
        "route": route,
        "tool": tool,
        "sources": sources,
        "grounded": bool(answer and answer.grounded),
        "invalid_citations": answer.invalid_citations if answer else [],
        "escalated": escalated,
        "pii_redacted": bool(pii_found),
        "latency_ms": latency_ms,
    }