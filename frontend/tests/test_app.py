"""Smoke tests for the Streamlit screens. The backend is replaced by a fake."""
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api  # noqa: E402

USERS = {"E-1001": ("Alex Employee", "employee"), "E-2001": ("Ana Agent", "agent"), "E-3001": ("Adam Admin", "admin")}


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.ticket_status = "open"
        self.messages = [{"id": 1, "sender": "user", "content": "I clicked a phishing link", "intent": None, "created_at": "x"},
                         {"id": 2, "sender": "assistant", "content": "Reset your password now.", "intent": "security_incident", "created_at": "x"}]

    def chat_reply(self, text):
        base = {"conversation_id": 7, "message_id": 9, "intent": "x", "confidence": 0.9, "route": "answer", "tool": None,
                "sources": [], "grounded": False, "invalid_citations": [], "escalated": False, "agent_handling": False,
                "pending_confirmation": False, "ticket_key": None, "tool_result": None, "tool_source": None,
                "pii_redacted": False, "latency_ms": 1200}
        if text == "I forgot my password":
            return {**base, "reply": "I can reset the password for E-1001. Reply YES to confirm, or NO to cancel.",
                    "route": "action", "tool": "reset_password", "tool_source": "llm", "pending_confirmation": True}
        if text == "yes":
            return {**base, "reply": "Done. I sent a password reset link to a***@capstonecompany.example."}
        if text == "agent please":
            return {**base, "reply": "", "message_id": None, "route": "agent", "agent_handling": True, "escalated": True}
        return {**base, "reply": "Install CapstoneVPN from Software Center.",
                "sources": [{"sop_id": "KB-007", "title": "VPN Setup on Windows", "chunk_id": "KB-007#0", "score": 0.75}]}

    def __call__(self, method, path, employee_id=None, **kw):
        self.calls.append((method, path, employee_id, kw))
        if path == "/me":
            name, role = USERS[employee_id]
            return {"employee_id": employee_id, "name": name, "role": role}
        if path == "/chat":
            return self.chat_reply(kw["json"]["message"])
        if (method, path) == ("GET", "/conversations"):
            return [{"id": 7, "status": "open", "employee_id": "E-1001", "preview": "VPN help", "started_at": "x", "ticket_key": None}]
        if path == "/conversations/7/messages":
            return {"conversation_id": 7, "status": "escalated", "messages": self.messages}
        if (method, path) == ("GET", "/tickets"):
            return [{"ticket_key": "CC-0002", "id": 2, "title": "Jira access", "priority": "P4", "status": "open",
                     "requester": "E-1001", "assigned_to": None, "conversation_id": None, "created_at": "x", "resolved_at": None},
                    {"ticket_key": "CC-0001", "id": 1, "title": "Escalation: phishing", "priority": "P1", "status": self.ticket_status,
                     "requester": "E-1001", "assigned_to": None, "conversation_id": 7, "created_at": "x", "resolved_at": None}]
        if method == "PATCH" and path == "/tickets/1":
            self.ticket_status = kw["json"].get("status", "in_progress")
            return {}
        if path == "/conversations/7/agent-reply":
            self.messages.append({"id": 3, "sender": "agent", "content": kw["json"]["message"], "intent": None, "created_at": "x"})
            return {"message_id": 3, "ticket_key": "CC-0001"}
        if path == "/metrics/summary":
            return {"conversations": 4, "messages": 9, "resolved_by_ai": 1, "deflection_rate": 0.25, "no_ticket_rate": 0.75,
                    "escalations": 1, "escalation_rate": 0.25, "guardrail_blocks": 2,
                    "tickets": {"total": 2, "by_status": {"open": 2}, "by_priority": {"P1": 1, "P4": 1}},
                    "mttr_minutes": 12.5, "latency_ms": {"count": 5, "avg": 4100, "p50": 3900, "p95": 9000},
                    "intents": {"vpn_help": 3, "policy_info": 2},
                    "tool_calls": [{"tool": "create_ticket", "status": "completed", "count": 1}],
                    "messages_per_day": [{"day": f"2026-11-{14 + i}", "messages": i} for i in range(7)]}
        if path == "/audit-logs":
            return [{"id": 1, "user_id": 1, "action": "ticket.created", "entity_type": "ticket", "entity_id": 1, "created_at": "x"}]
        if (method, path) == ("GET", "/kb"):
            return [{"sop_id": "KB-001", "title": "Password Reset", "category": "Accounts", "indexed_at": "2026-11-20"},
                    {"sop_id": "KB-002", "title": "Account Locked Out", "category": "Accounts", "indexed_at": None}]
        if path.startswith("/kb/KB-"):
            return {"sop_id": path[-6:], "title": "t", "category": "c", "text": "# Password Reset\nSteps: 1. Open the portal"}
        if (method, path) == ("POST", "/kb/reindex"):
            return {"indexed": 1, "skipped": 1, "chunks": 1, "removed": 0}
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture()
def backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(api, "request", fake)
    monkeypatch.setenv("STREAM_DELAY", "0")
    return fake


def start(user="E-1001 · Alex Employee", view=None):
    at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=20).run()
    if user != "E-1001 · Alex Employee":
        at.sidebar.selectbox(key="who").select(user).run()
    if view:
        at.sidebar.radio(key="view").set_value(view).run()
    assert not at.exception, at.exception
    return at


def test_employee_only_gets_the_chat(backend):
    at = start()
    assert at.sidebar.radio(key="view").options == ["Chat"]
    assert at.title[0].value == "IT Helpdesk Assistant"


def test_chat_answer_shows_sources(backend):
    at = start()
    at.chat_input[0].set_value("How do I install the VPN?").run()
    assert not at.exception
    texts = [m.markdown[0].value for m in at.chat_message]
    assert "Install CapstoneVPN from Software Center." in texts
    assert any("KB-007" in c.value for c in at.caption)
    sent = [c for c in backend.calls if c[1] == "/chat"][0]
    assert sent[2] == "E-1001" and sent[3]["json"]["conversation_id"] is None


def test_confirmation_buttons_appear_and_send_yes(backend):
    at = start()
    at.chat_input[0].set_value("I forgot my password").run()
    assert [b.key for b in at.button if b.key and b.key.startswith("quick_")] == ["quick_yes", "quick_no"]
    at.button(key="quick_yes").click().run()
    assert not at.exception
    sent = [c[3]["json"]["message"] for c in backend.calls if c[1] == "/chat"]
    assert sent == ["I forgot my password", "yes"]
    assert [c[3]["json"]["conversation_id"] for c in backend.calls if c[1] == "/chat"] == [None, 7]
    assert not [b for b in at.button if b.key == "quick_yes"]                 # buttons are gone after the answer
    assert any("reset link" in m.markdown[0].value for m in at.chat_message)


def test_agent_handling_banner(backend):
    at = start()
    at.chat_input[0].set_value("agent please").run()
    assert any("human agent is handling" in i.value for i in at.info)
    assert [b for b in at.button if b.key == "refresh_chat"]


def test_api_error_is_shown_not_raised(backend, monkeypatch):
    def boom(method, path, employee_id=None, **kw):
        if path == "/me":
            return {"employee_id": "E-1001", "name": "Alex", "role": "employee"}
        if path == "/chat":
            raise api.ApiError("The LLM or vector service failed: ConnectError", 502)
        return []
    monkeypatch.setattr(api, "request", boom)
    at = start()
    at.chat_input[0].set_value("hello").run()
    assert not at.exception and any("ConnectError" in e.value for e in at.error)


def test_agent_queue_sorts_by_priority_and_acts_on_a_ticket(backend):
    at = start("E-2001 · Ana Agent")
    assert at.sidebar.radio(key="view").value == "Agent queue"
    table = at.dataframe[0].value
    assert list(table["ticket_key"]) == ["CC-0001", "CC-0002"]                 # P1 first
    at.selectbox(key="ticket_pick").select("CC-0001").run()
    assert any("phishing" in m.markdown[0].value for m in at.chat_message)
    at.button(key="assign_me").click().run()
    assert ("PATCH", "/tickets/1", "E-2001", {"json": {"assign_to_me": True}}) in backend.calls
    at.button(key="resolve").click().run()
    assert ("PATCH", "/tickets/1", "E-2001", {"json": {"status": "resolved"}}) in backend.calls
    assert "CC-0001" not in list(at.dataframe[0].value["ticket_key"])        # resolved tickets leave the active list
    at.selectbox(key="ticket_filter").select("resolved").run()
    assert list(at.dataframe[0].value["ticket_key"]) == ["CC-0001"]


def test_agent_can_send_a_reply(backend):
    at = start("E-2001 · Ana Agent")
    at.selectbox(key="ticket_pick").select("CC-0001").run()
    at.text_area[0].set_value("Hello, I am Ana.")
    at.get("form_submit_button")[0].click().run()   # the Send reply button sits inside a form
    assert ("POST", "/conversations/7/agent-reply", "E-2001", {"json": {"message": "Hello, I am Ana."}}) in backend.calls


def test_admin_dashboard_shows_the_numbers(backend):
    at = start("E-3001 · Adam Admin")
    assert at.sidebar.radio(key="view").value == "Dashboard"
    values = {m.label: m.value for m in at.metric}
    assert values["Ticket deflection"] == "25%" and values["Escalation rate"] == "25%"
    assert values["MTTR (minutes)"] == "12.5" and values["p95 latency (ms)"] == "9000"
    assert values["Blocked messages"] == "2"


def test_admin_knowledge_base_page(backend):
    at = start("E-3001 · Adam Admin", view="Knowledge base")
    assert "1 not indexed" in at.caption[0].value
    at.button(key="reindex").click().run()
    assert any("indexed" in s.value for s in at.success)
    assert ("POST", "/kb/reindex", "E-3001", {"params": {"force": False}}) in backend.calls
    assert any("Password Reset" in m.value for m in at.markdown)


def test_switching_user_starts_a_fresh_chat(backend):
    at = start()
    at.chat_input[0].set_value("How do I install the VPN?").run()
    assert len(at.chat_message) >= 2
    at.sidebar.selectbox(key="who").select("E-3001 · Adam Admin").run()
    at.sidebar.radio(key="view").set_value("Chat").run()
    assert len(at.chat_message) == 0
