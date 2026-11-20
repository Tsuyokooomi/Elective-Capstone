import logging
from collections import deque
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import select

from app.chat_service import NotFound, handle_chat
from app.db.models import AuditLog, KBDocument, Ticket
from app.db.session import get_session, init_db
from app.llm import get_llm
from app.rag.retriever import HybridRetriever
from app.schemas import ChatRequest, ChatResponse
from app.tools.executor import ticket_key

logger = logging.getLogger("aihas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Elective Capstone", lifespan=lifespan)


@lru_cache
def get_retriever() -> HybridRetriever:
    return HybridRetriever()


@lru_cache
def get_answer_llm():
    return get_llm(temperature=0.1)


@lru_cache
def get_classifier_llm():
    return get_llm(temperature=0.0, json_mode=True)


@lru_cache
def get_tool_llm():
    return get_llm(temperature=0.0)   # no JSON mode: JSON mode and tool calling do not mix


def ready_retriever(retriever: HybridRetriever = Depends(get_retriever)) -> HybridRetriever:
    if not retriever.is_ready():
        raise HTTPException(
            status_code=503,
            detail="The knowledge base is empty. Run: docker compose exec api python -m app.rag.indexer",
        )
    return retriever


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    session=Depends(get_session),
    retriever: HybridRetriever = Depends(ready_retriever),
    answer_llm=Depends(get_answer_llm),
    classifier_llm=Depends(get_classifier_llm),
    tool_llm=Depends(get_tool_llm),
):
    try:
        return handle_chat(session, req, retriever, answer_llm, classifier_llm, tool_llm)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat failed")
        raise HTTPException(
            status_code=502,
            detail=f"The LLM or vector service failed: {type(exc).__name__}. "
                   "Check that Ollama is running and the models are pulled.",
        )


@app.get("/kb")
def list_kb(session=Depends(get_session)):
    docs = session.scalars(select(KBDocument).order_by(KBDocument.sop_id)).all()
    return [
        {"sop_id": d.sop_id, "title": d.title, "category": d.category,
         "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None}
        for d in docs
    ]


@app.get("/kb/search")
def kb_search(
    q: str = Query(min_length=1),
    k: int = Query(4, ge=1, le=10),
    retriever: HybridRetriever = Depends(ready_retriever),
):
    """Debug endpoint: show what the hybrid search returns for a question."""
    result = retriever.search(q, top_k=k)
    return {
        "query": q,
        "best_vector_score": round(result.best_vector_score, 4),
        "chunks": [
            {
                "chunk_id": c.chunk_id, "sop_id": c.sop_id, "title": c.title,
                "fused_score": round(c.score, 5),
                "vector_score": None if c.vector_score is None else round(c.vector_score, 4),
                "bm25_score": None if c.bm25_score is None else round(c.bm25_score, 3),
                "text": c.text,
            }
            for c in result.chunks
        ],
    }


def ticket_out(t: Ticket) -> dict:
    return {
        "ticket_key": ticket_key(t.id), "id": t.id, "title": t.title, "priority": t.priority,
        "status": t.status, "requester": t.requester.employee_id,
        "assigned_to": t.assignee.employee_id if t.assignee else None,
        "conversation_id": t.conversation_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# Phase 5 adds sign-in and roles. Until then these read-only endpoints are open.
@app.get("/tickets")
def list_tickets(status: str | None = None, session=Depends(get_session)):
    stmt = select(Ticket).order_by(Ticket.id.desc())
    if status:
        stmt = stmt.where(Ticket.status == status)
    return [ticket_out(t) for t in session.scalars(stmt).all()]


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, session=Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket_out(ticket)


@app.get("/audit-logs")
def list_audit_logs(limit: int = Query(50, ge=1, le=200), session=Depends(get_session)):
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [
        {"id": r.id, "user_id": r.user_id, "action": r.action, "entity_type": r.entity_type,
         "entity_id": r.entity_id, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


# A tiny webhook receiver for demos. Set WEBHOOK_URL=http://localhost:8080/mock/webhook
# (or an n8n URL) to see the events that ticket and reset actions send.
WEBHOOK_EVENTS: deque = deque(maxlen=50)


@app.post("/mock/webhook")
async def receive_webhook(request: Request):
    WEBHOOK_EVENTS.appendleft(await request.json())
    return {"received": True}


@app.get("/mock/webhook/events")
def webhook_events():
    return list(WEBHOOK_EVENTS)
