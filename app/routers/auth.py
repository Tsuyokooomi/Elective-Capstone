"""Sign-in and password reset endpoints.

POST /auth/login checks the employee ID and password and returns a token.
POST /auth/reset-password sets a new password using the one-time link from the reset email.
Protection against password guessing: after LOGIN_MAX_FAILURES wrong passwords for an account
within LOGIN_LOCK_MINUTES, that account refuses logins (even with the right password) until
older failures age out. Failures and successes are written to the audit log, which is also
where the lock is counted, so no extra table is needed."""
import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth import create_token, password_fingerprint, read_reset_token
from app.config import settings
from app.db.models import AuditLog, User, utcnow
from app.db.security import hash_password, verify_password
from app.db.session import get_session
from app.ratelimit import enforce
from app.tools.executor import audit
from app.tools.webhook import send_webhook

router = APIRouter(tags=["auth"])

# Checked when the employee ID does not exist, so a wrong ID and a wrong password take the same time
_DUMMY_HASH = hash_password("not-a-real-password")
WRONG_LOGIN = "Wrong employee ID or password"
BAD_RESET_LINK = "This reset link is invalid, expired, or already used"
MIN_PASSWORD_LENGTH = 10


class LoginRequest(BaseModel):
    employee_id: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=200)


class ResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=2000)
    new_password: str = Field(min_length=1, max_length=200)


def password_problem(password: str, employee_id: str) -> str | None:
    """Why this password is not allowed, or None if it is fine."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Use at least one letter and one number."
    if employee_id.lower() in password.lower():
        return "Do not put your employee ID in the password."
    return None


def recent_failures(session, user_id: int) -> int:
    """Wrong passwords for this account since its last successful login or password reset, inside the lock window."""
    cutoff = utcnow() - timedelta(minutes=settings.login_lock_minutes)
    last_ok = session.scalar(
        select(func.max(AuditLog.id)).where(
            AuditLog.user_id == user_id, AuditLog.action.in_(("auth.login_ok", "auth.password_reset")))
    ) or 0
    return session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.user_id == user_id, AuditLog.action == "auth.login_failed",
            AuditLog.created_at >= cutoff, AuditLog.id > last_ok,
        )
    ) or 0


def _user_out(user: User) -> dict:
    return {"employee_id": user.employee_id, "name": user.name, "role": user.role}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, session=Depends(get_session)):
    # Per IP address, so guesses at employee IDs that do not exist are limited too
    enforce(f"login:{client_ip(request)}", settings.login_per_minute, 60,
            "Too many sign-in attempts from this address. Try again in {seconds} seconds.")
    user = session.scalar(select(User).where(User.employee_id == body.employee_id))

    if user is not None and recent_failures(session, user.id) >= settings.login_max_failures:
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong passwords. This account is locked for up to {settings.login_lock_minutes} minutes.",
        )

    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not password_ok:
        if user is not None:
            audit(session, user.id, "auth.login_failed", "user", user.id)
            session.commit()
        raise HTTPException(status_code=401, detail=WRONG_LOGIN)

    audit(session, user.id, "auth.login_ok", "user", user.id)
    session.commit()
    return {
        "access_token": create_token(user.employee_id),
        "token_type": "bearer",
        "expires_in": settings.token_minutes * 60,
        "user": _user_out(user),
    }


@router.post("/auth/reset-password")
def reset_password(body: ResetRequest, request: Request, session=Depends(get_session)):
    enforce(f"reset:{client_ip(request)}", settings.reset_per_minute, 60,
            "Too many attempts from this address. Try again in {seconds} seconds.")
    parsed = read_reset_token(body.token)
    if parsed is None:
        raise HTTPException(status_code=400, detail=BAD_RESET_LINK)
    employee_id, fingerprint = parsed
    user = session.scalar(select(User).where(User.employee_id == employee_id))
    # The fingerprint comes from the old password hash. After a reset it no longer matches: single use.
    if user is None or not hmac.compare_digest(password_fingerprint(user.password_hash), fingerprint):
        raise HTTPException(status_code=400, detail=BAD_RESET_LINK)

    problem = password_problem(body.new_password, user.employee_id)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a password you are not using now.")

    user.password_hash = hash_password(body.new_password)
    audit(session, user.id, "auth.password_reset", "user", user.id)   # also lifts a login lock
    session.commit()
    send_webhook("password_reset.completed", {"employee_id": user.employee_id})
    return {"message": "Your password was changed. You can sign in now."}
