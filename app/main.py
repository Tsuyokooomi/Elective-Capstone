import logging
import secrets
from collections import deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from app.chat_service import NotFound, handle_chat
from app.config import settings
from app.ratelimit import enforce
from app.db.models import User
from app.db.session import get_session, init_db
from app.deps import (  # noqa: F401  (tests override these by name)
    STAFF, current_user, get_answer_llm, get_classifier_llm, get_retriever, get_tool_llm, ready_retriever,
    require_roles,
)
from app.rag.retriever import HybridRetriever
from app.routers import accounts, kb_admin
from app.routers import auth as auth_router
from app.routers import ops
from app.schemas import ChatBody, ChatRequest, ChatResponse
from app.tools.mock_email import OUTBOX

logger = logging.getLogger("aihas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Elective Capstone", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatBody,
    user: User = Depends(current_user),
    session=Depends(get_session),
    retriever: HybridRetriever = Depends(ready_retriever),
    answer_llm=Depends(get_answer_llm),
    classifier_llm=Depends(get_classifier_llm),
    tool_llm=Depends(get_tool_llm),
):
    enforce(f"chat:{user.id}", settings.chat_per_minute, 60,
            "You are sending messages too fast. Try again in {seconds} seconds.")
    # The caller's identity comes from the token. The request body cannot name another employee.
    req = ChatRequest(message=body.message, conversation_id=body.conversation_id, employee_id=user.employee_id)
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


@app.get("/kb/search")
def kb_search(
    q: str = Query(min_length=1),
    k: int = Query(4, ge=1, le=10),
    user: User = Depends(require_roles(*STAFF)),
    retriever: HybridRetriever = Depends(ready_retriever),
):
    """Debug endpoint for agents and admins: show what the hybrid search returns for a question."""
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


# A tiny webhook receiver for demos. Set WEBHOOK_URL=http://localhost:8080/mock/webhook
# (or an n8n URL) to see the events that ticket and reset actions send.
WEBHOOK_EVENTS: deque = deque(maxlen=50)


@app.post("/mock/webhook")
async def receive_webhook(request: Request):
    # If WEBHOOK_SECRET is set, only senders that know it are accepted
    if settings.webhook_secret and not secrets.compare_digest(
        request.headers.get("x-webhook-secret", "").encode(), settings.webhook_secret.encode()
    ):
        raise HTTPException(status_code=401, detail="Bad webhook secret")
    WEBHOOK_EVENTS.appendleft(await request.json())
    return {"received": True}


@app.get("/mock/webhook/events")
def webhook_events(user: User = Depends(require_roles("admin"))):
    return list(WEBHOOK_EVENTS)


@app.get("/mock/outbox")
def mock_outbox(user: User = Depends(require_roles("admin"))):
    """The fake email service: password reset emails appear here. Demo only."""
    return list(OUTBOX)


# Registered last, so fixed paths such as /kb/search win over /kb/{sop_id}
app.include_router(auth_router.router)
app.include_router(accounts.router)
app.include_router(kb_admin.router)
app.include_router(ops.router)
