"""Phase 5A tests: the password reset link flow (request in chat, choose the new password with the link)."""
from datetime import timedelta

from sqlalchemy import select

from app.auth import create_reset_token, create_token, read_reset_token, read_token
from app.config import settings
from app.db.models import AuditLog, User, utcnow
from app.tools.mock_email import OUTBOX
from test_phase4_api import ADMIN, EMP, client  # noqa: F401  (client fixture and headers)
from test_rag import env, sops  # noqa: F401  (shared fixtures)
from test_tools import FakeToolLLM, chat  # noqa: F401

NEW_PASSWORD = "Brand-New-Pass-42"
OLD_PASSWORD = "Demo-Employee-123"


def request_reset(chat):
    """Ask the bot for a reset and confirm it. Returns the reset token from the mock email."""
    OUTBOX.clear()
    chat.send("I forgot my password", intent="password_reset",
              tool_llm=FakeToolLLM("reset_password", {"reason": "forgot it"}))
    result = chat.send("yes")
    assert len(OUTBOX) == 1
    link = OUTBOX[0]["link"]
    assert "reset_token=" in link
    return link.split("reset_token=")[1], result


def token_for(env, employee_id="E-1001", minutes=None):
    with env.factory() as s:
        user = s.scalar(select(User).where(User.employee_id == employee_id))
        return create_reset_token(employee_id, user.password_hash, minutes)


def reset(client, token, password=NEW_PASSWORD):
    return client.post("/auth/reset-password", json={"token": token, "new_password": password})


def login(client, employee_id, password):
    return client.post("/auth/login", json={"employee_id": employee_id, "password": password})


# ---------- requesting a reset ----------

def test_reset_request_emails_a_link_and_leaves_the_password_alone(chat):
    before = chat.user().password_hash
    token, result = request_reset(chat)
    assert chat.user().password_hash == before
    mail = OUTBOX[0]
    assert mail["to"] == "alex@capstonecompany.example" and mail["link"].startswith(settings.frontend_url)
    assert read_reset_token(token) is not None
    assert token not in str(result)                       # the token is only in the email, not in the chat answer or tool result


# ---------- token separation ----------

def test_reset_and_login_tokens_cannot_be_swapped(client):
    reset_token = create_reset_token("E-1001", "some-hash")
    assert read_token(reset_token) is None
    assert client.get("/me", headers={"Authorization": f"Bearer {reset_token}"}).status_code == 401
    assert read_reset_token(create_token("E-1001")) is None
    assert reset(client, create_token("E-1001")).status_code == 400    # a login token does not reset anything


# ---------- choosing the new password ----------

def test_full_flow_old_password_stops_and_new_one_works(chat, client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "")
    token, _ = request_reset(chat)
    assert login(client, "E-1001", OLD_PASSWORD).status_code == 200      # still valid until the link is used

    r = reset(client, token)
    assert r.status_code == 200 and "changed" in r.json()["message"]
    assert login(client, "E-1001", OLD_PASSWORD).status_code == 401
    assert login(client, "E-1001", NEW_PASSWORD).status_code == 200
    assert "auth.password_reset" in chat.actions()


def test_a_reset_link_works_only_once(chat, client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "")
    token, _ = request_reset(chat)
    assert reset(client, token).status_code == 200
    again = reset(client, token, "Another-Pass-77")
    assert again.status_code == 400 and "already used" in again.json()["detail"]
    assert login(client, "E-1001", NEW_PASSWORD).status_code == 200      # the second attempt changed nothing


def test_bad_links_are_refused(env, client):
    assert reset(client, "garbage").status_code == 400
    assert reset(client, token_for(env, minutes=-1)).status_code == 400                 # expired
    assert reset(client, create_reset_token("E-1001", "not-the-current-hash")).status_code == 400
    assert reset(client, create_reset_token("E-9999", "x")).status_code == 400          # no such employee
    assert login(client, "E-1001", OLD_PASSWORD).status_code == 200                     # nothing changed


def test_weak_passwords_are_refused_and_the_link_still_works_afterwards(env, client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "")
    token = token_for(env)
    for weak, hint in [("Short1", "at least"), ("onlyletterslong", "letter and one number"),
                       ("1234567890123", "letter and one number"), ("Xx-E-1001-Xx9", "employee ID"),
                       (OLD_PASSWORD, "not using now")]:
        r = reset(client, token, weak)
        assert r.status_code == 400 and hint in r.json()["detail"], (weak, r.json())
    assert reset(client, token).status_code == 200                                      # refusals did not use up the link


def test_a_reset_lifts_a_login_lock(env, client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_url", "")
    monkeypatch.setattr(settings, "login_max_failures", 2)
    for _ in range(2):
        login(client, "E-1001", "wrong")
    assert login(client, "E-1001", OLD_PASSWORD).status_code == 429
    assert reset(client, token_for(env)).status_code == 200
    assert login(client, "E-1001", NEW_PASSWORD).status_code == 200


# ---------- the mock outbox ----------

def test_outbox_is_admin_only(chat, client):
    request_reset(chat)
    assert client.get("/mock/outbox").status_code == 401
    assert client.get("/mock/outbox", headers=EMP).status_code == 403
    mails = client.get("/mock/outbox", headers=ADMIN).json()
    assert mails[0]["to"] == "alex@capstonecompany.example" and "reset_token=" in mails[0]["link"]
