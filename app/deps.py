"""Shared FastAPI dependencies.

current_user() reads the login token from the header "Authorization: Bearer <token>"
(issued by POST /auth/login). require_roles() builds on it, so every protected endpoint
checks the token first and the role second."""
import logging
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth import read_token
from app.db.models import User
from app.db.session import SessionLocal, get_session
from app.llm import get_llm
from app.rag.retriever import HybridRetriever

logger = logging.getLogger("aihas")

bearer_scheme = HTTPBearer(auto_error=False)   # we raise our own 401 so the message is the same everywhere


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


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session=Depends(get_session),
) -> User:
    unauthorized = HTTPException(
        status_code=401, detail="Sign in required", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    employee_id = read_token(credentials.credentials)
    if employee_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    # Look the user up on every request, so a deleted account stops working at once
    user = session.scalar(select(User).where(User.employee_id == employee_id))
    if user is None:
        raise unauthorized
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your role cannot do this")
        return user
    return checker


STAFF = ("agent", "admin")
