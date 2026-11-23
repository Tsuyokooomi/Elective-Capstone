"""Phase 5A tests: login tokens, sign-in endpoint, lockout, and who /chat believes you are."""
import base64
import json
import time
from datetime import timedelta
from types import SimpleNamespace

import jwt
from sqlalchemy import select

from app import auth as auth_module
from app.auth import create_token, read_token
from app.config import settings
from app.db.models import AuditLog, Conversation, User, utcnow
from app.routers.auth import WRONG_LOGIN
from app.tools.webhook import send_webhook
from test_phase4_api import auth, client  # noqa: F401  (client fixture and header helper)
from test_rag import env, sops  # noqa: F401  (shared fixtures)

PASSWORDS = {"E-1001": "Demo-Employee-123", "E-2001": "Demo-Agent-123", "E-3001": "Demo-Admin-123"}


def login(client, employee_id, password):
    return client.post("/auth/login", json={"employee_id": employee_id, "password": password})


def b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


# ---------- tokens ----------

def test_token_round_trip_and_every_kind_of_bad_token():
    token = create_token("E-1001")
    assert read_token(token) == "E-1001"
    assert read_token(create_token("E-1001", minutes=-1)) is None                # expired
    assert read_token("junk") is None

    header, _payload, signature = token.split(".")
    edited = f"{header}.{b64({'sub': 'E-3001', 'exp': int(time.time()) + 600})}.{signature}"
    assert read_token(edited) is None                                             # payload edited, old signature

    claims = {"sub": "E-3001", "exp": int(time.time()) + 600}
    assert read_token(jwt.encode(claims, "another-secret-key-of-enough-length-1", algorithm="HS256")) is None
    assert read_token(jwt.encode(claims, None, algorithm="none")) is None         # unsigned token
    assert read_token(jwt.encode({"sub": "E-3001"}, auth_module._secret(), algorithm="HS256")) is None   # no expiry


def test_api_rejects_missing_expired_and_garbage_tokens(client):
    assert client.get("/me").status_code == 401
    expired = {"Authorization": f"Bearer {create_token('E-1001', minutes=-1)}"}
    r = client.get("/me", headers=expired)
    assert r.status_code == 401 and r.json()["detail"] == "Invalid or expired token"
    assert client.get("/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/me", headers={"X-Employee-Id": "E-3001"}).status_code == 401   # the old header no longer works


# ---------- login ----------

def test_login_returns_a_token_that_works(client):
    r = login(client, "E-3001", PASSWORDS["E-3001"])
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == settings.token_minutes * 60
    assert body["user"] == {"employee_id": "E-3001", "name": "Adam Admin", "role": "admin"}
    me = client.get("/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == "admin"


def test_wrong_password_and_unknown_id_look_the_same(client):
    wrong = login(client, "E-1001", "not-the-password")
    unknown = login(client, "E-9999", "not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": WRONG_LOGIN}


def test_login_input_is_validated(client):
    assert client.post("/auth/login", json={"employee_id": "E-1001"}).status_code == 422
    assert login(client, "", "x").status_code == 422


# ---------- lockout ----------

def test_account_locks_after_too_many_wrong_passwords(client, env, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    for _ in range(3):
        assert login(client, "E-1001", "wrong").status_code == 401
    assert login(client, "E-1001", PASSWORDS["E-1001"]).status_code == 429       # even the right password is refused
    assert login(client, "E-2001", PASSWORDS["E-2001"]).status_code == 200       # other accounts are not affected
    with env.factory() as s:
        actions = [a.action for a in s.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions.count("auth.login_failed") == 3 and actions.count("auth.login_ok") == 1


def test_a_successful_login_resets_the_failure_count(client, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    for _ in range(2):
        login(client, "E-1001", "wrong")
    assert login(client, "E-1001", PASSWORDS["E-1001"]).status_code == 200
    for _ in range(2):
        assert login(client, "E-1001", "wrong").status_code == 401               # two more are still below the limit
    assert login(client, "E-1001", PASSWORDS["E-1001"]).status_code == 200


def test_old_failures_stop_counting(client, env, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 2)
    for _ in range(2):
        login(client, "E-1001", "wrong")
    assert login(client, "E-1001", PASSWORDS["E-1001"]).status_code == 429
    with env.factory() as s:                                                      # pretend it happened long ago
        for row in s.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")):
            row.created_at = utcnow() - timedelta(minutes=settings.login_lock_minutes + 5)
        s.commit()
    assert login(client, "E-1001", PASSWORDS["E-1001"]).status_code == 200


# ---------- /chat identity ----------

def test_chat_uses_the_token_and_ignores_an_employee_id_in_the_body(client, env):
    r = client.post("/chat", json={"message": "VPN help", "employee_id": "E-3001"}, headers=auth("E-1001"))
    assert r.status_code == 200
    with env.factory() as s:
        conversation = s.get(Conversation, r.json()["conversation_id"])
        owner = s.get(User, conversation.user_id)
    assert owner.employee_id == "E-1001"                                          # not E-3001


def test_chat_needs_a_token(client):
    assert client.post("/chat", json={"message": "hello"}).status_code == 401


# ---------- webhook protection ----------

def test_webhook_receiver_checks_the_secret_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    assert client.post("/mock/webhook", json={"event": "x"}).status_code == 401
    wrong = {"X-Webhook-Secret": "wrong"}
    assert client.post("/mock/webhook", json={"event": "x"}, headers=wrong).status_code == 401
    right = {"X-Webhook-Secret": "s3cret"}
    assert client.post("/mock/webhook", json={"event": "x"}, headers=right).json() == {"received": True}


def test_webhook_sender_includes_the_secret_only_when_configured(monkeypatch):
    seen = []

    def post(url, json, timeout, **extra):
        seen.append(extra)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(settings, "webhook_secret", "")
    send_webhook("e", {}, url="http://x", post=post)
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    send_webhook("e", {}, url="http://x", post=post)
    assert seen == [{}, {"headers": {"X-Webhook-Secret": "s3cret"}}]
