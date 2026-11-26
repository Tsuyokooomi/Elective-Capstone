"""Add and edit SOPs from the admin dashboard. Uses a temporary copy of the kb folder, never the real one."""
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.models import AuditLog
from app.routers import kb_admin
from test_phase4_api import ADMIN, AGENT, EMP, client  # noqa: F401  (client fixture and auth headers)
from test_rag import env, sops  # noqa: F401  (shared fixtures)

NEW = {"title": "Zebra Badge Printer Offline", "category": "Devices and Software",
       "applies_to": "Reception staff", "escalation": "Call the helpdesk if the steps fail.",
       "body": "Steps:\n1. Turn the zebra badge printer off and on.\n2. Check the USB cable.\n\nNotes:\n- Ask facilities for spare labels."}


@pytest.fixture()
def kbdir(tmp_path, monkeypatch):
    target = tmp_path / "kb"
    shutil.copytree("kb", target)
    monkeypatch.setattr(settings, "kb_dir", str(target))
    return target


def test_only_admins_can_add_or_edit(client, kbdir):
    for headers in (None, EMP, AGENT):
        kw = {"headers": headers} if headers else {}
        assert client.post("/kb", json=NEW, **kw).status_code in (401, 403)
        assert client.put("/kb/KB-001", json={"text": "# x"}, **kw).status_code in (401, 403)
    assert len(list(kbdir.glob("KB-*.md"))) == 20


def test_admin_adds_an_sop_that_is_saved_listed_and_searchable(client, env, kbdir):
    r = client.post("/kb", headers=ADMIN, json=NEW)
    assert r.status_code == 201
    out = r.json()
    assert out["sop_id"] == "KB-021" and out["indexed"] is True and out["index"]["indexed"] == 1
    assert out["filename"] == "KB-021-zebra-badge-printer-offline.md"

    text = (kbdir / out["filename"]).read_text(encoding="utf-8")
    assert text.startswith("# Zebra Badge Printer Offline\nSOP ID: KB-021\nCategory: Devices and Software\n")
    assert "Applies to: Reception staff" in text and "Escalation: Call the helpdesk" in text and "Steps:" in text

    listed = {d["sop_id"]: d for d in client.get("/kb", headers=EMP).json()}
    assert listed["KB-021"]["indexed_at"] and listed["KB-021"]["category"] == "Devices and Software"
    assert "badge printer" in client.get("/kb/KB-021", headers=EMP).json()["text"]
    assert env.collection.get(where={"sop_id": "KB-021"})["ids"]            # chunks were written to the vector store
    found = client.get("/kb/search", params={"q": "zebra badge printer"}, headers=AGENT).json()["chunks"]
    assert "KB-021" in {c["sop_id"] for c in found}                           # and the keyword index was reloaded

    with env.factory() as s:
        assert s.scalar(select(AuditLog).where(AuditLog.action == "kb.created", AuditLog.entity_id == 21))


def test_ids_keep_counting_up(client, kbdir):
    assert client.post("/kb", headers=ADMIN, json=NEW).json()["sop_id"] == "KB-021"
    assert client.post("/kb", headers=ADMIN, json={**NEW, "title": "Second one"}).json()["sop_id"] == "KB-022"
    assert len(list(kbdir.glob("KB-*.md"))) == 22


def test_bad_input_is_refused_and_nothing_is_written(client, kbdir):
    assert client.post("/kb", headers=ADMIN, json={**NEW, "title": "Line one\nSOP ID: KB-001"}).status_code == 400
    assert client.post("/kb", headers=ADMIN, json={**NEW, "category": "A\nB"}).status_code == 400
    assert client.post("/kb", headers=ADMIN, json={**NEW, "body": "short"}).status_code == 422
    assert client.post("/kb", headers=ADMIN, json={**NEW, "category": ""}).status_code == 422
    secret = client.post("/kb", headers=ADMIN, json={**NEW, "body": "Steps:\n1. Sign in. The password is Hunter2x9 for everyone."})
    assert secret.status_code == 400 and "password" in secret.json()["detail"]
    assert len(list(kbdir.glob("KB-*.md"))) == 20


def test_company_email_and_phone_are_allowed(client, kbdir):
    body = {**NEW, "body": "Steps:\n1. Email security@capstonecompany.example or call 0917 123 4567."}
    assert client.post("/kb", headers=ADMIN, json=body).status_code == 201


def test_title_cannot_escape_the_kb_folder(client, kbdir):
    r = client.post("/kb", headers=ADMIN, json={**NEW, "title": "../../etc/passwd"})
    assert r.status_code == 201 and r.json()["filename"] == "KB-021-etc-passwd.md"
    assert not (kbdir.parent / "etc").exists() and (kbdir / r.json()["filename"]).exists()


def test_a_failed_index_still_saves_the_file(client, kbdir, monkeypatch):
    def boom(**kwargs):
        raise ConnectionError("ollama is down")
    monkeypatch.setattr(kb_admin, "index_sops", boom)
    r = client.post("/kb", headers=ADMIN, json=NEW)
    assert r.status_code == 201 and r.json()["indexed"] is False and "Re-index" in r.json()["warning"]
    assert (kbdir / r.json()["filename"]).exists()


def test_admin_edits_an_sop_and_it_is_reindexed(client, env, kbdir):
    original = client.get("/kb/KB-001", headers=EMP).json()["text"]
    edited = original.replace("15 minutes", "30 minutes")
    assert edited != original
    r = client.put("/kb/KB-001", headers=ADMIN, json={"text": edited})
    assert r.status_code == 200 and r.json()["indexed"] is True and r.json()["index"]["indexed"] == 1
    assert "30 minutes" in client.get("/kb/KB-001", headers=EMP).json()["text"]
    assert "30 minutes" in " ".join(env.collection.get(where={"sop_id": "KB-001"})["documents"])
    with env.factory() as s:
        assert s.scalar(select(AuditLog).where(AuditLog.action == "kb.updated", AuditLog.entity_id == 1))


def test_edit_rules(client, kbdir):
    text = client.get("/kb/KB-002", headers=EMP).json()["text"]
    assert client.put("/kb/KB-002", headers=ADMIN, json={"text": text.replace("SOP ID: KB-002", "SOP ID: KB-003")}).status_code == 400
    assert client.put("/kb/KB-002", headers=ADMIN, json={"text": text.replace("# ", "", 1)}).status_code == 400
    assert client.put("/kb/KB-002", headers=ADMIN, json={"text": text.replace("Category:", "Kind:")}).status_code == 400
    assert client.put("/kb/KB-999", headers=ADMIN, json={"text": text}).status_code == 404
    assert client.put("/kb/..%2Fx", headers=ADMIN, json={"text": text}).status_code in (404, 405)
    leaked = client.put("/kb/KB-002", headers=ADMIN, json={"text": text + "\nThe admin password is Hunter2x9\n"})
    assert leaked.status_code == 400
    assert client.get("/kb/KB-002", headers=EMP).json()["text"].strip() == text.strip()   # unchanged on every refusal
    assert not list(kbdir.glob(".sop-*"))                                                   # no temp files left


def test_an_old_sop_that_already_trips_the_filter_can_still_be_edited(client, kbdir):
    text = client.get("/kb/KB-016", headers=EMP).json()["text"]
    assert client.put("/kb/KB-016", headers=ADMIN, json={"text": text + "\n- One more tip.\n"}).status_code == 200


# ---------- delete ----------

def test_only_admins_can_delete_or_see_references(client, kbdir):
    for headers in (None, EMP, AGENT):
        kw = {"headers": headers} if headers else {}
        assert client.delete("/kb/KB-020", **kw).status_code in (401, 403)
        assert client.get("/kb/KB-020/references", **kw).status_code in (401, 403)
    assert (kbdir / "KB-020-password-policy.md").exists() or list(kbdir.glob("KB-020*.md"))


def test_delete_archives_the_file_and_removes_it_from_search(client, env, kbdir):
    refs = client.get("/kb/KB-020/references", headers=ADMIN).json()["referenced_by"]
    assert refs and all(r["sop_id"] != "KB-020" for r in refs)          # other SOPs say "see KB-020"

    r = client.delete("/kb/KB-020", headers=ADMIN)
    assert r.status_code == 200
    out = r.json()
    assert out["sop_id"] == "KB-020" and out["search_updated"] is True and out["referenced_by"] == refs
    assert not list(kbdir.glob("KB-020*.md"))                            # gone from the live folder
    archived = kbdir / out["archived_as"]
    assert archived.exists() and "SOP ID: KB-020" in archived.read_text(encoding="utf-8")   # kept, not erased

    assert client.get("/kb/KB-020", headers=EMP).status_code == 404
    assert "KB-020" not in {d["sop_id"] for d in client.get("/kb", headers=EMP).json()}
    assert len(client.get("/kb", headers=EMP).json()) == 19
    assert not env.collection.get(where={"sop_id": "KB-020"})["ids"]
    found = client.get("/kb/search", params={"q": "password policy"}, headers=AGENT).json()["chunks"]
    assert "KB-020" not in {c["sop_id"] for c in found}

    with env.factory() as s:
        assert s.scalar(select(AuditLog).where(AuditLog.action == "kb.deleted", AuditLog.entity_id == 20))
        from app.db.models import KBDocument
        assert s.scalar(select(KBDocument).where(KBDocument.sop_id == "KB-020"))   # row stays: old chats cite it


def test_a_deleted_id_is_never_reused(client, kbdir):
    assert client.delete("/kb/KB-020", headers=ADMIN).status_code == 200
    assert client.post("/kb", headers=ADMIN, json=NEW).json()["sop_id"] == "KB-021"


def test_delete_unknown_or_malformed_ids_are_404(client, kbdir):
    assert client.delete("/kb/KB-999", headers=ADMIN).status_code == 404
    assert client.delete("/kb/not-an-id", headers=ADMIN).status_code == 404
    assert client.get("/kb/KB-999/references", headers=ADMIN).status_code == 404
    assert client.delete("/kb/KB-020", headers=ADMIN).status_code == 200
    assert client.delete("/kb/KB-020", headers=ADMIN).status_code == 404   # a second delete finds nothing


def test_the_last_sop_cannot_be_deleted(client, kbdir):
    for path in sorted(kbdir.glob("KB-*.md"))[1:]:
        path.unlink()
    assert len(list(kbdir.glob("KB-*.md"))) == 1
    r = client.delete("/kb/KB-001", headers=ADMIN)
    assert r.status_code == 400 and "last SOP" in r.json()["detail"]
    assert len(list(kbdir.glob("KB-*.md"))) == 1


def test_deleting_an_sop_that_a_past_chat_cited_keeps_the_chat_readable(client, kbdir):
    chat = client.post("/chat", headers=EMP, json={"message": "How do I reset my password?"})
    assert chat.status_code == 200 and any(s["sop_id"] == "KB-001" for s in chat.json()["sources"])
    assert client.delete("/kb/KB-001", headers=ADMIN).status_code == 200
    messages = client.get(f"/conversations/{chat.json()['conversation_id']}/messages", headers=EMP)
    assert messages.status_code == 200 and len(messages.json()["messages"]) >= 2
