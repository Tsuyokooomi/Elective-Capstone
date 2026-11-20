"""Endpoints for the chat history, the agent queue, tickets, metrics, and the knowledge base."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import (
    TICKET_STATUSES, AuditLog, Conversation, KBDocument, Message, Ticket, User, utcnow,
)
from app.db.session import get_session
from app.deps import STAFF, current_user, get_retriever, get_session_factory, require_roles
from app.guardrails.pii import redact_pii
from app.metrics import compute_metrics
from app.rag.chunking import load_sops
from app.rag.indexer import index_sops
from app.rag.retriever import HybridRetriever
from app.tools.executor import audit, find_open_ticket, ticket_key

router = APIRouter()


class AgentReply(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class TicketUpdate(BaseModel):
    status: str | None = None
    assign_to_me: bool = False
    assigned_to: str | None = None   # employee ID of an agent or admin


def _iso(value):
    return value.isoformat() if value else None


def ticket_out(t: Ticket) -> dict:
    return {
        "ticket_key": ticket_key(t.id), "id": t.id, "title": t.title, "priority": t.priority,
        "status": t.status, "requester": t.requester.employee_id,
        "assigned_to": t.assignee.employee_id if t.assignee else None,
        "conversation_id": t.conversation_id, "created_at": _iso(t.created_at),
        "resolved_at": _iso(t.resolved_at),
    }


def _visible(user: User, conversation: Conversation | None) -> bool:
    return conversation is not None and (user.role in STAFF or conversation.user_id == user.id)


# ---------- who am I ----------

@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"employee_id": user.employee_id, "name": user.name, "role": user.role}


# ---------- conversations ----------

@router.get("/conversations")
def list_conversations(status: str | None = None, user: User = Depends(current_user),
                       session=Depends(get_session)):
    stmt = select(Conversation).order_by(Conversation.id.desc())
    if user.role not in STAFF:
        stmt = stmt.where(Conversation.user_id == user.id)
    if status:
        stmt = stmt.where(Conversation.status == status)
    out = []
    for c in session.scalars(stmt).all():
        first = session.scalars(select(Message).where(Message.conversation_id == c.id, Message.sender == "user")
                                .order_by(Message.id)).first()
        ticket = session.scalars(select(Ticket).where(Ticket.conversation_id == c.id)
                                 .order_by(Ticket.id.desc())).first()
        out.append({
            "id": c.id, "status": c.status, "employee_id": c.user.employee_id,
            "preview": (first.content[:60] if first else ""), "started_at": _iso(c.started_at),
            "ticket_key": ticket_key(ticket.id) if ticket else None,
        })
    return out


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int, user: User = Depends(current_user), session=Depends(get_session)):
    conversation = session.get(Conversation, conversation_id)
    if not _visible(user, conversation):
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = session.scalars(select(Message).where(Message.conversation_id == conversation_id)
                           .order_by(Message.id)).all()
    return {
        "conversation_id": conversation_id, "status": conversation.status,
        "messages": [{"id": m.id, "sender": m.sender, "content": m.content, "intent": m.intent,
                      "created_at": _iso(m.created_at)} for m in rows],
    }


@router.post("/conversations/{conversation_id}/agent-reply")
def agent_reply(conversation_id: int, body: AgentReply, agent: User = Depends(require_roles(*STAFF)),
                session=Depends(get_session)):
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status != "escalated":
        raise HTTPException(status_code=409, detail="This conversation is not escalated")

    text, _ = redact_pii(body.message)
    message = Message(conversation_id=conversation_id, sender="agent", content=text)
    session.add(message)
    ticket = find_open_ticket(session, conversation_id)
    if ticket is not None and ticket.assigned_to is None:   # the first reply claims the ticket
        ticket.assigned_to = agent.id
        ticket.status = "in_progress"
        audit(session, agent.id, "ticket.assigned", "ticket", ticket.id)
    audit(session, agent.id, "agent.replied", "conversation", conversation_id)
    session.commit()
    return {"message_id": message.id, "ticket_key": ticket_key(ticket.id) if ticket else None}


# ---------- tickets ----------

@router.get("/tickets")
def list_tickets(status: str | None = None, user: User = Depends(current_user), session=Depends(get_session)):
    stmt = select(Ticket).order_by(Ticket.id.desc())
    if user.role not in STAFF:
        stmt = stmt.where(Ticket.user_id == user.id)
    if status:
        stmt = stmt.where(Ticket.status == status)
    return [ticket_out(t) for t in session.scalars(stmt).all()]


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, user: User = Depends(current_user), session=Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None or (user.role not in STAFF and ticket.user_id != user.id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket_out(ticket)


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, body: TicketUpdate, agent: User = Depends(require_roles(*STAFF)),
                  session=Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if body.status is not None and body.status not in TICKET_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(TICKET_STATUSES)}")

    if body.assign_to_me:
        ticket.assigned_to = agent.id
    elif body.assigned_to:
        target = session.scalar(select(User).where(User.employee_id == body.assigned_to))
        if target is None or target.role not in STAFF:
            raise HTTPException(status_code=400, detail="assigned_to must be an agent or admin")
        ticket.assigned_to = target.id
    if body.assign_to_me or body.assigned_to:
        audit(session, agent.id, "ticket.assigned", "ticket", ticket.id)
        if body.status is None and ticket.status == "open":
            ticket.status = "in_progress"

    if body.status is not None:
        ticket.status = body.status
        conversation = session.get(Conversation, ticket.conversation_id) if ticket.conversation_id else None
        if body.status in ("resolved", "closed"):
            ticket.resolved_at = ticket.resolved_at or utcnow()
            if conversation is not None:
                conversation.status, conversation.ended_at = "resolved", utcnow()
        else:
            ticket.resolved_at = None
            if conversation is not None:
                conversation.status, conversation.ended_at = "escalated", None
        audit(session, agent.id, "ticket.updated", "ticket", ticket.id)

    session.commit()
    return ticket_out(ticket)


# ---------- dashboard ----------

@router.get("/metrics/summary")
def metrics_summary(user: User = Depends(require_roles(*STAFF)), session=Depends(get_session)):
    return compute_metrics(session)


@router.get("/audit-logs")
def list_audit_logs(limit: int = Query(50, ge=1, le=200), user: User = Depends(require_roles("admin")),
                    session=Depends(get_session)):
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [
        {"id": r.id, "user_id": r.user_id, "action": r.action, "entity_type": r.entity_type,
         "entity_id": r.entity_id, "created_at": _iso(r.created_at)}
        for r in rows
    ]


# ---------- knowledge base ----------

@router.get("/kb")
def list_kb(user: User = Depends(current_user), session=Depends(get_session)):
    docs = session.scalars(select(KBDocument).order_by(KBDocument.sop_id)).all()
    return [{"sop_id": d.sop_id, "title": d.title, "category": d.category, "indexed_at": _iso(d.indexed_at)}
            for d in docs]


@router.get("/kb/{sop_id}")
def get_sop(sop_id: str, user: User = Depends(current_user)):
    if not re.fullmatch(r"KB-\d{3}", sop_id):
        raise HTTPException(status_code=404, detail="SOP not found")
    for sop in load_sops():
        if sop["sop_id"] == sop_id:
            return {"sop_id": sop_id, "title": sop["title"], "category": sop["category"], "text": sop["text"]}
    raise HTTPException(status_code=404, detail="SOP not found")


@router.post("/kb/reindex")
def reindex(force: bool = False, admin: User = Depends(require_roles("admin")),
            retriever: HybridRetriever = Depends(get_retriever), factory=Depends(get_session_factory)):
    try:
        summary = index_sops(force=force, embed_model=retriever.embed_model,
                             collection=retriever.collection, session_factory=factory)
        retriever.reload()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Re-indexing failed: {type(exc).__name__}")
    return summary
