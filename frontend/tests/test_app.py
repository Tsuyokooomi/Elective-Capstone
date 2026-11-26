"""Smoke tests for the Streamlit screens. The backend is replaced by a fake."""
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api  # noqa: E402

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
USERS = {"E-1001": ("Alex Employee", "employee"), "E-2001": ("Ana Agent", "agent"), "E-3001": ("Adam Admin", "admin")}
PASSWORDS = {"E-1001": "Demo-Employee-123", "E-2001": "Demo-Agent-123", "E-3001": "Demo-Admin-123"}
LOGIN_TITLE = "CapstoneCompany IT Helpdesk"


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
        # The third argument is the login token. In this fake the token is simply the employee ID.
        self.calls.append((method, path, employee_id, kw))
        if path == "/auth/login":
            who, password = kw["json"]["employee_id"], kw["json"]["password"]
            if who not in USERS or PASSWORDS[who] != password:
                raise api.ApiError("Wrong employee ID or password", 401)
            name, role = USERS[who]
            return {"access_token": who, "token_type": "bearer", "expires_in": 3600,
                    "user": {"employee_id": who, "name": name, "role": role}}
        if path == "/auth/reset-password":
            if kw["json"]["token"] != "good-token":
                raise api.ApiError("This reset link is invalid, expired, or already used", 400)
            return {"message": "Your password was changed. You can sign in now."}
        if path == "/mock/outbox":
            return [{"to": "alex@capstonecompany.example", "subject": "Reset your CapstoneCompany password",
                     "link": "http://localhost:8501/?reset_token=good-token", "body": "x",
                     "sent_at": "2026-11-22T10:00:00+00:00"}]
        if (method, path) == ("GET", "/users"):
            return [{"employee_id": "E-3001", "name": "Adam Admin", "email": "adam@capstonecompany.example",
                     "role": "admin", "created_at": "2026-11-20"}]
        if (method, path) == ("POST", "/users"):
            if kw["json"]["employee_id"] == "E-3001":
                raise api.ApiError("That employee ID is already in use.", 409)
            return {**{k: v for k, v in kw["json"].items() if k != "password"}, "created_at": "2026-11-26"}
        if path == "/health":
            return {"status": "ok"}
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
        if (method, path) == ("POST", "/kb"):
            if kw["json"]["title"] == "Rejected":
                raise api.ApiError("This text looks like it contains a password.", 400)
            return {"sop_id": "KB-021", "title": kw["json"]["title"], "category": kw["json"]["category"],
                    "filename": "KB-021-x.md", "indexed": True, "index": {"indexed": 1}}
        if (method, path) == ("PUT", "/kb/KB-001"):
            if "FAIL" in kw["json"]["text"]:
                return {"sop_id": "KB-001", "title": "Password Reset", "category": "Accounts", "filename": "KB-001.md",
                        "indexed": False, "index": None, "warning": "Saved, but indexing failed."}
            return {"sop_id": "KB-001", "title": "Password Reset", "category": "Accounts", "filename": "KB-001.md",
                    "indexed": True, "index": {"indexed": 1}}
        if (method, path) == ("GET", "/kb/KB-001/references"):
            return {"sop_id": "KB-001", "referenced_by": [{"sop_id": "KB-002", "title": "Account Locked Out"}]}
        if (method, path) == ("DELETE", "/kb/KB-001"):
            return {"sop_id": "KB-001", "title": "Password Reset", "archived_as": ".deleted/KB-001-x.md",
                    "referenced_by": [], "search_updated": True}
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


def login(at, employee_id, password=None):
    at.text_input(key="login_id").set_value(employee_id)
    at.text_input(key="login_password").set_value(password or PASSWORDS[employee_id])
    at.get("form_submit_button")[0].click().run()   # the Sign in button sits inside a form
    return at


def start(user="E-1001", view=None):
    """Open the app and sign in through the login form."""
    at = AppTest.from_file(APP, default_timeout=20).run()
    login(at, user)
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


def test_new_agent_reply_appears_without_clicking_refresh(backend):
    at = start()
    at.chat_input[0].set_value("agent please").run()
    assert not any("Come to my desk" in m.value for m in at.markdown)
    backend.messages.append({"id": 3, "sender": "agent", "content": "Come to my desk", "intent": None, "created_at": "x"})
    at.run()   # the watcher runs on every page run and on its timer; no button is clicked
    assert any("Come to my desk" in m.value for m in at.markdown)


def test_agent_screen_shows_new_employee_message_after_a_refresh(backend):
    at = start("E-2001")
    assert not any("Still stuck" in m.value for m in at.markdown)
    backend.messages.append({"id": 4, "sender": "user", "content": "Still stuck", "intent": None, "created_at": "x"})
    at.run()
    assert any("Still stuck" in m.value for m in at.markdown)


def test_api_error_is_shown_not_raised(backend, monkeypatch):
    def boom(method, path, employee_id=None, **kw):
        if path == "/auth/login":
            return {"access_token": "E-1001", "token_type": "bearer", "expires_in": 3600,
                    "user": {"employee_id": "E-1001", "name": "Alex", "role": "employee"}}
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
    at = start("E-2001")
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
    at = start("E-2001")
    at.selectbox(key="ticket_pick").select("CC-0001").run()
    at.text_area[0].set_value("Hello, I am Ana.")
    at.get("form_submit_button")[0].click().run()   # the Send reply button sits inside a form
    assert ("POST", "/conversations/7/agent-reply", "E-2001", {"json": {"message": "Hello, I am Ana."}}) in backend.calls


def test_admin_dashboard_shows_the_numbers(backend):
    at = start("E-3001")
    assert at.sidebar.radio(key="view").value == "Dashboard"
    values = {m.label: m.value for m in at.metric}
    assert values["Ticket deflection"] == "25%" and values["Escalation rate"] == "25%"
    assert values["MTTR (minutes)"] == "12.5" and values["p95 latency (ms)"] == "9000"
    assert values["Blocked messages"] == "2"


def test_admin_knowledge_base_page(backend):
    at = start("E-3001", view="Knowledge base")
    assert "1 not indexed" in at.caption[0].value
    at.button(key="reindex").click().run()
    assert any("indexed" in s.value for s in at.success)
    assert ("POST", "/kb/reindex", "E-3001", {"params": {"force": False}}) in backend.calls
    assert any("Password Reset" in m.value for m in at.markdown)


def test_admin_account_management_page(backend):
    at = start("E-3001", view="Account Management")
    assert at.title[0].value == "Account Management"
    at.text_input[0].set_value("E-4001")
    at.text_input[1].set_value("Nora New")
    at.text_input[2].set_value("nora@capstonecompany.example")
    at.selectbox[0].set_value("agent")
    at.text_input[3].set_value("Fresh-Pass-2026")
    at.text_input[4].set_value("Fresh-Pass-2026")
    at.button(key="create_account").click().run()
    posts = [c for c in backend.calls if c[:2] == ("POST", "/users")]
    assert len(posts) == 1 and posts[0][3]["json"]["role"] == "agent"
    assert any("E-4001" in s.value for s in at.success)


def test_account_management_rejects_mismatched_passwords_and_duplicates(backend):
    at = start("E-3001", view="Account Management")
    for i, value in enumerate(["E-4001", "Nora New", "nora@capstonecompany.example"]):
        at.text_input[i].set_value(value)
    at.text_input[3].set_value("Fresh-Pass-2026")
    at.text_input[4].set_value("Different-Pass-1")
    at.button(key="create_account").click().run()
    assert any("do not match" in e.value for e in at.error)
    assert not [c for c in backend.calls if c[:2] == ("POST", "/users")]

    at.text_input[0].set_value("E-3001")        # an ID that already exists
    at.text_input[4].set_value("Fresh-Pass-2026")
    at.button(key="create_account").click().run()
    assert any("already in use" in e.value for e in at.error)


def test_only_admins_see_account_management(backend):
    assert "Account Management" in start("E-3001").sidebar.radio(key="view").options
    assert "Account Management" not in start("E-2001").sidebar.radio(key="view").options


def test_admin_adds_an_sop(backend):
    at = start("E-3001", view="Knowledge base")
    at.text_input(key="sop_title_0").set_value("Zebra Badge Printer Offline")
    at.text_area(key="sop_body_0").set_value("Steps:\n1. Turn it off and on.\n2. Check the cable.")
    at.button(key="sop_save_0").click().run()
    posts = [c for c in backend.calls if c[:2] == ("POST", "/kb")]
    assert len(posts) == 1
    sent = posts[0][3]["json"]
    assert sent["title"] == "Zebra Badge Printer Offline" and sent["category"] == "Accounts" and "Steps:" in sent["body"]
    assert any("KB-021" in s.value and "indexed" in s.value for s in at.success)
    assert at.text_input(key="sop_title_1").value == ""          # the form starts empty again


def test_adding_an_sop_needs_a_title_and_real_content_and_shows_backend_errors(backend):
    at = start("E-3001", view="Knowledge base")
    at.button(key="sop_save_0").click().run()                     # empty title, template body
    assert any("Enter a title" in e.value for e in at.error)
    assert not [c for c in backend.calls if c[:2] == ("POST", "/kb")]

    at.text_input(key="sop_title_0").set_value("Rejected")
    at.text_area(key="sop_body_0").set_value("Steps:\n1. The password is Hunter2x9")
    at.button(key="sop_save_0").click().run()
    assert any("password" in e.value for e in at.error)


def test_admin_edits_an_sop(backend):
    at = start("E-3001", view="Knowledge base")
    original = at.text_area(key="sop_edit_KB-001").value
    assert "Password Reset" in original
    at.button(key="sop_edit_save_KB-001").click().run()
    assert any("Nothing changed" in i.value for i in at.info)    # saving an untouched text sends nothing
    assert not [c for c in backend.calls if c[:2] == ("PUT", "/kb/KB-001")]

    at.text_area(key="sop_edit_KB-001").set_value(original + "\n- A new tip.")
    at.button(key="sop_edit_save_KB-001").click().run()
    puts = [c for c in backend.calls if c[:2] == ("PUT", "/kb/KB-001")]
    assert len(puts) == 1 and "A new tip." in puts[0][3]["json"]["text"]
    assert any("KB-001" in s.value for s in at.success)


def test_a_saved_but_not_indexed_sop_shows_a_warning(backend):
    at = start("E-3001", view="Knowledge base")
    at.text_area(key="sop_edit_KB-001").set_value("# Password Reset\nSOP ID: KB-001\nCategory: Accounts\nFAIL")
    at.button(key="sop_edit_save_KB-001").click().run()
    assert any("indexing failed" in w.value for w in at.warning)


def test_admin_deletes_an_sop_only_after_ticking_the_box(backend):
    at = start("E-3001", view="Knowledge base")
    assert at.button(key="sop_del_KB-001").disabled                       # locked until the admin confirms
    assert any("KB-002" in w.value for w in at.warning)                   # shows which SOPs still mention it
    at.checkbox(key="sop_del_ok_KB-001").check().run()
    assert not at.button(key="sop_del_KB-001").disabled
    at.button(key="sop_del_KB-001").click().run()
    assert ("DELETE", "/kb/KB-001", "E-3001", {}) in backend.calls
    assert any("Deleted KB-001" in s.value and ".deleted/KB-001-x.md" in s.value for s in at.success)


def test_signing_out_and_in_as_someone_else_starts_a_fresh_chat(backend):
    at = start()
    at.chat_input[0].set_value("How do I install the VPN?").run()
    assert len(at.chat_message) >= 2
    at.sidebar.button(key="sign_out").click().run()
    assert at.title[0].value == LOGIN_TITLE                                   # back at the login screen
    login(at, "E-3001")
    at.sidebar.radio(key="view").set_value("Chat").run()
    assert len(at.chat_message) == 0


def test_login_screen_comes_first_and_a_wrong_password_is_rejected(backend):
    at = AppTest.from_file(APP, default_timeout=20).run()
    assert not at.exception and at.title[0].value == LOGIN_TITLE
    assert len(at.sidebar.radio) == 0                                         # no app screens before signing in
    login(at, "E-1001", "wrong-password")
    assert any("Wrong employee ID or password" in e.value for e in at.error)
    assert not [c for c in backend.calls if c[1] == "/me"]                    # it never got in


def test_the_token_not_the_employee_id_is_sent_to_the_api(backend):
    at = start("E-2001")
    profile = [e.proto.body for e in at.sidebar.get("html") if 'class="profile"' in e.proto.body]
    assert profile and "Ana Agent" in profile[0] and ">agent<" in profile[0]
    me_calls = [c for c in backend.calls if c[1] == "/me"]
    assert me_calls and me_calls[0][2] == "E-2001"        # fake token; the real one is a signed JWT
    login_calls = [c for c in backend.calls if c[1] == "/auth/login"]
    assert login_calls[0][2] is None                       # logging in sends no token


def test_an_expired_token_sends_you_back_to_the_login_screen(backend, monkeypatch):
    at = start()
    working = api.request

    def expired(method, path, token=None, **kw):
        if path == "/me":
            raise api.ApiError("Invalid or expired token", 401)
        return working(method, path, token, **kw)

    monkeypatch.setattr(api, "request", expired)
    at.chat_input[0].set_value("hello").run()
    assert not at.exception and at.title[0].value == LOGIN_TITLE
    assert any("session ended" in w.value for w in at.warning)


def open_reset_link(token):
    at = AppTest.from_file(APP, default_timeout=20)
    at.query_params["reset_token"] = token
    return at.run()


def test_reset_link_lets_the_user_choose_a_new_password(backend):
    at = open_reset_link("good-token")
    assert not at.exception and at.title[0].value == "Choose a new password"
    at.text_input(key="reset_new").set_value("Brand-New-Pass-42")
    at.text_input(key="reset_confirm").set_value("Brand-New-Pass-42")
    at.get("form_submit_button")[0].click().run()
    assert not at.exception and at.title[0].value == LOGIN_TITLE
    assert any("password was changed" in s.value for s in at.success)
    call = [c for c in backend.calls if c[1] == "/auth/reset-password"][0]
    assert call[3]["json"] == {"token": "good-token", "new_password": "Brand-New-Pass-42"}


def test_reset_form_checks_the_two_passwords_match_and_shows_api_errors(backend):
    at = open_reset_link("good-token")
    at.text_input(key="reset_new").set_value("Brand-New-Pass-42")
    at.text_input(key="reset_confirm").set_value("Different-Pass-42")
    at.get("form_submit_button")[0].click().run()
    assert any("do not match" in e.value for e in at.error)
    assert not [c for c in backend.calls if c[1] == "/auth/reset-password"]      # nothing was sent

    at = open_reset_link("expired-token")
    at.text_input(key="reset_new").set_value("Brand-New-Pass-42")
    at.text_input(key="reset_confirm").set_value("Brand-New-Pass-42")
    at.get("form_submit_button")[0].click().run()
    assert any("expired" in e.value for e in at.error) and at.title[0].value == "Choose a new password"


def test_admin_dashboard_shows_the_mock_outbox(backend):
    at = start("E-3001")
    assert any("reset_token=good-token" in c.value for c in at.code)
