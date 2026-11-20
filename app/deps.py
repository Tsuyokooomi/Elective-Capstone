"""Shared FastAPI dependencies.

Sign-in is a placeholder for now: the caller sends the header X-Employee-Id.
Phase 5 replaces current_user() with real sign-in (tokens), and every endpoint that
uses require_roles() is then protected without further changes."""
import logging
from functools import lru_cache

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal, get_session
from app.llm import get_llm
from app.rag.retriever import HybridRetriever

logger = logging.getLogger("aihas")


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


def get_session_factory():
    return SessionLocal


def ready_retriever(retriever: HybridRetriever = Depends(get_retriever)) -> HybridRetriever:
    if not retriever.is_ready():
        raise HTTPException(
            status_code=503,
            detail="The knowledge base is empty. Run: docker compose exec api python -m app.rag.indexer",
        )
    return retriever


def current_user(x_employee_id: str | None = Header(default=None), session=Depends(get_session)) -> User:
    if not x_employee_id:
        raise HTTPException(status_code=401, detail="Missing X-Employee-Id header")
    user = session.scalar(select(User).where(User.employee_id == x_employee_id))
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown employee")
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your role cannot do this")
        return user
    return checker


STAFF = ("agent", "admin")
