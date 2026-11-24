import os
import time

import pandas as pd
import streamlit as st

import api

st.set_page_config(page_title="CapstoneCompany IT Helpdesk", page_icon="🛠️", layout="wide")

# Shown under the login form so the demo is easy. Set SHOW_DEMO_LOGINS=0 to hide it.
SHOW_DEMO_LOGINS = os.getenv("SHOW_DEMO_LOGINS", "1") != "0"
DEMO_ACCOUNTS = [
    ("E-1001", "Demo-Employee-123", "Employee"),
    ("E-2001", "Demo-Agent-123", "Agent"),
    ("E-3001", "Demo-Admin-123", "Admin"),
]
VIEWS_BY_ROLE = {
    "employee": ["Chat"],
    "agent": ["Agent queue", "Chat"],
    "admin": ["Dashboard", "Agent queue", "Knowledge base", "Chat"],
}
STREAM_DELAY = float(os.getenv("STREAM_DELAY", "0.012"))   # seconds per word; 0 turns the effect off
PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}


def typewriter(text: str):
    for word in text.split(" "):
        yield word + " "
        time.sleep(STREAM_DELAY)


def show_error(exc: api.ApiError):
    st.error(str(exc))


# ------------------------------------------------------------------ chat

def render_message(item: dict):
    with st.chat_message(item["role"]):
        if item.get("label"):
            st.caption(item["label"])
        st.markdown(item["content"])
        meta = item.get("meta")
        if meta:
            if meta.get("ticket_key"):
                st.success(f"Ticket {meta['ticket_key']}")
            if meta.get("sources"):
                st.caption("Sources: " + ", ".join(f"{s['sop_id']} {s['title']}" for s in meta["sources"]))
            with st.expander("Details"):
                st.json({k: meta[k] for k in ("intent", "confidence", "route", "tool", "tool_source", "grounded",
                                              "guardrail_flags", "latency_ms") if k in meta})


def load_conversation(token: str, conversation_id: int):
    data = api.conversation_messages(token, conversation_id)
    history = []
    for m in data["messages"]:
        if m["sender"] == "user":
            history.append({"role": "user", "content": m["content"]})
        else:
            label = "Human agent" if m["sender"] == "agent" else None
            history.append({"role": "assistant", "content": m["content"], "label": label})
    st.session_state.history = history
    st.session_state.conversation_id = conversation_id
    st.session_state.pending = False
    st.session_state.agent_handling = data["status"] == "escalated"


def reset_chat():
    st.session_state.history, st.session_state.conversation_id = [], None
    st.session_state.pending, st.session_state.agent_handling = False, False


def send(token: str, text: str):
    st.session_state.history.append({"role": "user", "content": text})
    with st.chat_message("user"):
        st.markdown(text)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                resp = api.chat(token, text, st.session_state.conversation_id)
            except api.ApiError as exc:
                show_error(exc)
                return False
        st.session_state.conversation_id = resp["conversation_id"]
        st.session_state.pending = resp["pending_confirmation"]
        st.session_state.agent_handling = bool(resp.get("agent_handling"))
        if resp.get("agent_handling"):
            st.info("A human agent is handling this chat. They will reply here.")
            return True
        if STREAM_DELAY > 0:
            st.write_stream(typewriter(resp["reply"]))
        else:
            st.markdown(resp["reply"])
        if resp.get("ticket_key"):
            st.success(f"Ticket {resp['ticket_key']}")
        if resp["sources"]:
            st.caption("Sources: " + ", ".join(f"{s['sop_id']} {s['title']}" for s in resp["sources"]))
    st.session_state.history.append({"role": "assistant", "content": resp["reply"], "meta": resp})
    return True


def chat_view(user: dict):
    token = user["token"]
    for key, default in (("history", []), ("conversation_id", None), ("pending", False),
                         ("agent_handling", False)):
        st.session_state.setdefault(key, default)

    st.title("IT Helpdesk Assistant")

    with st.sidebar:
        st.subheader("Conversations")
        if st.button("New chat", key="new_chat", width="stretch"):
            reset_chat()
            st.rerun()
        try:
            convs = api.conversations(token) if user["role"] == "employee" else []
        except api.ApiError:
            convs = []
        if convs:
            labels = {f"#{c['id']} · {c['status']} · {c['preview'] or '(empty)'}": c["id"] for c in convs}
            choice = st.selectbox("Open an earlier chat", ["—"] + list(labels), key="conv_picker")
            if choice != "—" and labels[choice] != st.session_state.conversation_id:
                load_conversation(token, labels[choice])
                st.rerun()

    for item in st.session_state.history:
        render_message(item)

    if st.session_state.agent_handling:
        st.info("A human agent is handling this chat.")
        if st.button("Check for agent replies", key="refresh_chat"):
            load_conversation(token, st.session_state.conversation_id)
            st.rerun()

    quick = None
    if st.session_state.pending:
        yes_col, no_col, _ = st.columns([1, 1, 4])
        if yes_col.button("Yes, go ahead", key="quick_yes", type="primary"):
            quick = "yes"
        if no_col.button("No, cancel", key="quick_no"):
            quick = "no"

    prompt = st.chat_input("Describe your IT problem")
    text = prompt or quick
    if text and send(token, text):
        st.rerun()   # redraw so the Yes and No buttons match the new state


# ------------------------------------------------------------------ agent queue

def agent_view(user: dict):
    token = user["token"]
    st.title("Agent queue")

    left, right = st.columns([2, 1])
    # "active" is the default, so a ticket does not vanish from the list the moment you claim it
    status = left.selectbox("Show tickets", ["active", "open", "in_progress", "resolved", "closed", "all"],
                            key="ticket_filter")
    if right.button("Refresh", key="refresh_queue"):
        st.rerun()

    try:
        rows = api.tickets(token)
    except api.ApiError as exc:
        return show_error(exc)
    if status == "active":
        rows = [t for t in rows if t["status"] in ("open", "in_progress")]
    elif status != "all":
        rows = [t for t in rows if t["status"] == status]
    rows.sort(key=lambda t: (PRIORITY_ORDER.get(t["priority"], 9), t["id"]))
    if not rows:
        st.info("No tickets with this status.")
        return

    table = pd.DataFrame(rows)[["ticket_key", "priority", "title", "requester", "status", "assigned_to"]]
    st.dataframe(table, hide_index=True, width="stretch")

    key = st.selectbox("Open a ticket", [t["ticket_key"] for t in rows], key="ticket_pick")
    ticket = next(t for t in rows if t["ticket_key"] == key)
    st.subheader(f"{ticket['ticket_key']} · {ticket['priority']} · {ticket['status']}")
    st.write(ticket["title"])

    buttons = st.columns(4)
    try:
        if buttons[0].button("Assign to me", key="assign_me"):
            api.update_ticket(token, ticket["id"], assign_to_me=True)
            st.rerun()
        if buttons[1].button("Resolve", key="resolve"):
            api.update_ticket(token, ticket["id"], status="resolved")
            st.rerun()
        if buttons[2].button("Close", key="close"):
            api.update_ticket(token, ticket["id"], status="closed")
            st.rerun()
        if buttons[3].button("Reopen", key="reopen"):
            api.update_ticket(token, ticket["id"], status="in_progress")
            st.rerun()
    except api.ApiError as exc:
        show_error(exc)

    cid = ticket["conversation_id"]
    if cid is None:
        return st.caption("This ticket has no chat.")

    st.markdown("**Conversation**")
    try:
        data = api.conversation_messages(token, cid)
    except api.ApiError as exc:
        return show_error(exc)
    for m in data["messages"]:
        role = "user" if m["sender"] == "user" else "assistant"
        with st.chat_message(role):
            st.caption({"user": "Employee", "assistant": "Assistant", "agent": "Agent"}.get(m["sender"], m["sender"]))
            st.markdown(m["content"])

    with st.form(f"reply_{cid}", clear_on_submit=True):
        reply = st.text_area("Reply to the employee", key=f"reply_text_{cid}")
        if st.form_submit_button("Send reply") and reply.strip():
            try:
                api.agent_reply(token, cid, reply.strip())
                st.rerun()
            except api.ApiError as exc:
                show_error(exc)


# ------------------------------------------------------------------ dashboard

def pct(value):
    return "n/a" if value is None else f"{value:.0%}"


def dashboard_view(user: dict):
    token = user["token"]
    st.title("Dashboard")
    if st.button("Refresh", key="refresh_dashboard"):
        st.rerun()
    try:
        m = api.metrics(token)
    except api.ApiError as exc:
        return show_error(exc)

    a, b, c, d = st.columns(4)
    a.metric("Conversations", m["conversations"])
    b.metric("Ticket deflection", pct(m["deflection_rate"]),
             help="Chats the assistant resolved: the user said thanks and no ticket or agent was needed.")
    c.metric("Escalation rate", pct(m["escalation_rate"]))
    d.metric("MTTR (minutes)", "n/a" if m["mttr_minutes"] is None else m["mttr_minutes"],
             help="Mean time from ticket creation to resolution.")

    e, f, g, h = st.columns(4)
    lat = m["latency_ms"]
    e.metric("Avg latency (ms)", lat["avg"] if lat["avg"] is not None else "n/a")
    f.metric("p95 latency (ms)", lat["p95"] if lat["p95"] is not None else "n/a")
    g.metric("Tickets", m["tickets"]["total"])
    h.metric("Blocked messages", m["guardrail_blocks"])

    left, right = st.columns(2)
    with left:
        st.markdown("**Messages per day**")
        st.bar_chart(pd.DataFrame(m["messages_per_day"]).set_index("day"))
        st.markdown("**Tickets by priority**")
        if m["tickets"]["by_priority"]:
            st.bar_chart(pd.Series(m["tickets"]["by_priority"], name="tickets"))
        else:
            st.caption("No tickets yet.")
    with right:
        st.markdown("**Intents**")
        if m["intents"]:
            st.bar_chart(pd.Series(m["intents"], name="messages"))
        else:
            st.caption("No messages yet.")
        st.markdown("**Tool calls**")
        if m["tool_calls"]:
            st.dataframe(pd.DataFrame(m["tool_calls"]), hide_index=True, width="stretch")
        else:
            st.caption("No tool calls yet.")

    st.markdown("**Latest audit log**")
    try:
        logs = api.audit_logs(token, 30)
        if logs:
            st.dataframe(pd.DataFrame(logs)[["created_at", "action", "entity_type", "entity_id", "user_id"]],
                         hide_index=True, width="stretch")
    except api.ApiError as exc:
        show_error(exc)

    with st.expander("Mock email outbox (demo)"):
        st.caption("The email service is mocked. Password reset links appear here instead of in a real inbox.")
        try:
            mails = api.outbox(token)
        except api.ApiError as exc:
            show_error(exc)
        else:
            if not mails:
                st.caption("No emails sent yet.")
            for mail in mails[:5]:
                st.markdown(f"**To {mail['to']}** · {mail['subject']} · {mail['sent_at']}")
                st.code(mail["link"], language=None)


# ------------------------------------------------------------------ knowledge base

def kb_view(user: dict):
    token = user["token"]
    st.title("Knowledge base")
    try:
        docs = api.kb_list(token)
    except api.ApiError as exc:
        return show_error(exc)

    pending = sum(1 for d in docs if not d["indexed_at"])
    st.caption(f"{len(docs)} SOPs, {pending} not indexed yet.")
    st.dataframe(pd.DataFrame(docs), hide_index=True, width="stretch")

    col1, col2, _ = st.columns([1, 1, 3])
    if col1.button("Re-index changed SOPs", key="reindex"):
        try:
            with st.spinner("Indexing..."):
                st.success(f"Done: {api.kb_reindex(token)}")
        except api.ApiError as exc:
            show_error(exc)
    if col2.button("Rebuild everything", key="reindex_force"):
        try:
            with st.spinner("Indexing..."):
                st.success(f"Done: {api.kb_reindex(token, force=True)}")
        except api.ApiError as exc:
            show_error(exc)

    pick = st.selectbox("Preview an SOP", [f"{d['sop_id']} · {d['title']}" for d in docs], key="sop_pick")
    try:
        st.markdown(api.kb_doc(token, pick.split(" · ")[0])["text"])
    except api.ApiError as exc:
        show_error(exc)


# ------------------------------------------------------------------ sign in

SESSION_KEYS = ("token", "signed_in_as", "view", "history", "conversation_id", "pending", "agent_handling",
                "conv_picker")


def sign_out(notice: str | None = None):
    for key in SESSION_KEYS:
        st.session_state.pop(key, None)
    if notice:
        st.session_state["notice"] = notice


def login_view():
    st.title("CapstoneCompany IT Helpdesk")
    notice = st.session_state.pop("notice", None)
    if notice:
        st.warning(notice)
    done = st.session_state.pop("login_success", None)
    if done:
        st.success(done)

    with st.form("login"):
        employee_id = st.text_input("Employee ID", key="login_id")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            result = api.login(employee_id.strip(), password)
        except api.ApiError as exc:
            show_error(exc)
        else:
            st.session_state.token = result["access_token"]
            st.rerun()

    if SHOW_DEMO_LOGINS:
        with st.expander("Demo accounts"):
            st.markdown("\n".join(f"- **{role}**: `{who}` / `{pw}`" for who, pw, role in DEMO_ACCOUNTS))


def reset_view(reset_token: str):
    """Opened from the link in the reset email: ?reset_token=..."""
    st.title("Choose a new password")
    with st.form("reset"):
        new_password = st.text_input("New password", type="password", key="reset_new")
        confirm = st.text_input("Repeat the new password", type="password", key="reset_confirm")
        submitted = st.form_submit_button("Change password", type="primary")
    st.caption("At least 10 characters, with a letter and a number. The link works once.")
    if submitted:
        if new_password != confirm:
            st.error("The two passwords do not match.")
        else:
            try:
                api.reset_password(reset_token, new_password)
            except api.ApiError as exc:
                show_error(exc)
            else:
                st.query_params.clear()
                st.session_state["reset_done"] = True   # ignore the old link even if the address bar still has it
                st.session_state["login_success"] = "Your password was changed. Sign in with the new password."
                st.rerun()
    if st.button("Back to sign in", key="reset_cancel"):
        st.query_params.clear()
        st.session_state["reset_done"] = True
        st.rerun()


# ------------------------------------------------------------------ main

def main():
    reset_token = None if st.session_state.get("reset_done") else st.query_params.get("reset_token")
    if reset_token:
        return reset_view(reset_token)

    token = st.session_state.get("token")
    if not token:
        return login_view()

    try:
        user = api.request("GET", "/me", token)
    except api.ApiError as exc:
        if exc.status == 401:   # the token expired or the account no longer exists
            sign_out("Your session ended. Please sign in again.")
            st.rerun()
        return show_error(exc)
    user["token"] = token

    if st.session_state.get("signed_in_as") != user["employee_id"]:   # a different person starts fresh
        st.session_state.signed_in_as = user["employee_id"]
        st.session_state.pop("view", None)   # land on the first screen for the role
        reset_chat()

    views = VIEWS_BY_ROLE[user["role"]]
    with st.sidebar:
        st.header("CapstoneCompany IT")
        st.caption(f"{user['name']} · {user['role']}")
        if st.button("Sign out", key="sign_out"):
            sign_out()
            st.rerun()
        view = st.radio("Go to", views, key="view")

    {"Chat": chat_view, "Agent queue": agent_view, "Dashboard": dashboard_view,
     "Knowledge base": kb_view}[view](user)


main()
