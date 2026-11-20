import logging
from collections import deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from app.chat_service import NotFound, handle_chat
from app.db.session import get_session, init_db
from app.deps import (  # noqa: F401  (tests override these by name)
    get_answer_llm, get_classifier_llm, get_retriever, get_tool_llm, ready_retriever,
)
from app.rag.retriever import HybridRetriever
from app.routers import ops
from app.schemas import ChatRequest, ChatResponse

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


# Registered last, so fixed paths such as /kb/search win over /kb/{sop_id}
app.include_router(ops.router)
