"""Account management tests: only admins can list or create users, and a new user can sign in."""
from sqlalchemy import select

from app.db.models import AuditLog, User
from test_phase4_api import ADMIN, AGENT, EMP, client  # noqa: F401  (client fixture and auth headers)
from test_rag import env, sops  # noqa: F401  (shared fixtures)

NEW = {"employee_id": "E-4001", "name": "Nora New", "email": "Nora@CapstoneCompany.example",
       "role": "agent", "password": "Fresh-Pass-2026"}


def test_only_admins_can_list_or_create_users(client):
    assert client.get("/users").status_code == 401
    assert client.get("/users", headers=EMP).status_code == 403
    assert client.get("/users", headers=AGENT).status_code == 403
    assert client.post("/users", headers=EMP, json=NEW).status_code == 403
    assert client.post("/users", headers=AGENT, json=NEW).status_code == 403
    r = client.get("/users", headers=ADMIN)
    assert r.status_code == 200
    assert {u["employee_id"] for u in r.json()} >= {"E-1001", "E-2001", "E-3001"}
    assert all("password" not in u and "password_hash" not in u for u in r.json())


def test_admin_creates_a_user_who_can_sign_in(client, env):
    r = client.post("/users", headers=ADMIN, json=NEW)
    assert r.status_code == 201
    body = r.json()
    assert body["employee_id"] == "E-4001" and body["role"] == "agent"
    assert body["email"] == "nora@capstonecompany.example"   # stored in lower case
    assert "password" not in body and "password_hash" not in body

    login = client.post("/auth/login", json={"employee_id": "E-4001", "password": NEW["password"]})
    assert login.status_code == 200 and login.json()["user"]["role"] == "agent"

    with env.factory() as s:
        stored = s.scalar(select(User).where(User.employee_id == "E-4001"))
        assert stored.password_hash != NEW["password"] and stored.password_hash.startswith("pbkdf2_sha256$")
        entry = s.scalar(select(AuditLog).where(AuditLog.action == "user.created"))
        assert entry is not None and entry.entity_id == stored.id
        assert NEW["password"] not in repr(entry.__dict__)


def test_duplicate_id_and_email_are_409(client):
    assert client.post("/users", headers=ADMIN, json=NEW).status_code == 201
    same_id = {**NEW, "email": "other@capstonecompany.example"}
    assert client.post("/users", headers=ADMIN, json=same_id).status_code == 409
    same_email = {**NEW, "employee_id": "E-4002"}
    assert client.post("/users", headers=ADMIN, json=same_email).status_code == 409


def test_bad_input_is_400(client):
    for change in (
        {"role": "superuser"},                 # not a real role
        {"password": "short1"},                # too short
        {"password": "onlyletterspassword"},   # no number
        {"password": "Has-E-4001-inside9"},    # contains the employee ID
        {"email": "not-an-email"},
        {"employee_id": "bad id!"},
    ):
        r = client.post("/users", headers=ADMIN, json={**NEW, **change})
        assert r.status_code == 400, change
    assert client.get("/users", headers=ADMIN).json().__len__() == 3   # nothing was created
