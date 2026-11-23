"""Signed tokens: login tokens and one-time password reset tokens.

Both are JWTs (JSON Web Tokens) signed with SECRET_KEY. The role is NOT stored in a login
token: current_user() reads it from the database on every request, so a role change or a
deleted account takes effect immediately.

A reset token carries purpose="password_reset" and a fingerprint of the current password hash.
Once the password changes, the fingerprint no longer matches, so the link stops working. That
makes it single-use without storing anything. A reset token can never be used to sign in, and a
login token can never be used to reset a password."""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt

from app.config import settings

logger = logging.getLogger("aihas")
ALGORITHM = "HS256"
RESET_PURPOSE = "password_reset"


@lru_cache
def _secret() -> str:
    if settings.secret_key:
        return settings.secret_key
    logger.warning("SECRET_KEY is not set, so a random key is used. Everyone is signed out whenever "
                   "the API restarts. Set SECRET_KEY in .env to keep logins across restarts.")
    return secrets.token_urlsafe(32)


def _encode(claims: dict, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({**claims, "iat": now, "exp": now + timedelta(minutes=minutes)}, _secret(), algorithm=ALGORITHM)


def _decode(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None


# ---------- login tokens ----------

def create_token(employee_id: str, minutes: int | None = None) -> str:
    return _encode({"sub": employee_id}, settings.token_minutes if minutes is None else minutes)


def read_token(token: str) -> str | None:
    """Return the employee ID if this is a genuine, unexpired LOGIN token, otherwise None."""
    data = _decode(token)
    if data is None or "purpose" in data:      # reset tokens must never sign anyone in
        return None
    subject = data.get("sub")
    return subject if isinstance(subject, str) and subject else None


# ---------- password reset tokens ----------

def password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_reset_token(employee_id: str, password_hash: str, minutes: int | None = None) -> str:
    claims = {"sub": employee_id, "purpose": RESET_PURPOSE, "ph": password_fingerprint(password_hash)}
    return _encode(claims, settings.reset_link_minutes if minutes is None else minutes)


def read_reset_token(token: str) -> tuple[str, str] | None:
    """Return (employee ID, password fingerprint) for a genuine, unexpired RESET token, otherwise None."""
    data = _decode(token)
    if data is None or data.get("purpose") != RESET_PURPOSE:
        return None
    subject, fingerprint = data.get("sub"), data.get("ph")
    if isinstance(subject, str) and subject and isinstance(fingerprint, str) and fingerprint:
        return subject, fingerprint
    return None
