import os
import time

import pandas as pd
import streamlit as st

import api

st.set_page_config(page_title="CapstoneCompany IT Helpdesk", page_icon="🛠️", layout="wide")

# Placeholder sign-in. Phase 5 replaces this with a real login form.
DEMO_USERS = {
    "E-1001 · Alex Employee": "E-1001",
    "E-2001 · Ana Agent": "E-2001",
    "E-3001 · Adam Admin": "E-3001",
}
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
                                              "latency_ms") if k in meta})


def load_conversation(employee_id: str, conversation_id: int):
    data = api.conversation_messages(employee_id, conversation_id)
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


def send(employee_id: str, text: str):
    st.session_state.history.append({"role": "user", "content": text})
    with st.chat_message("user"):
        st.markdown(text)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                resp = api.chat(employee_id, text, st.session_state.conversation_id)
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
    uid = user["employee_id"]
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
            convs = api.conversations(uid) if user["role"] == "employee" else []
        except api.ApiError:
            convs = []
        if convs:
            labels = {f"#{c['id']} · {c['status']} · {c['preview'] or '(empty)'}": c["id"] for c in convs}
            choice = st.selectbox("Open an earlier chat", ["—"] + list(labels), key="conv_picker")
            if choice != "—" and labels[choice] != st.session_state.conversation_id:
                load_conversation(uid, labels[choice])
                st.rerun()

    for item in st.session_state.history:
        render_message(item)

    if st.session_state.agent_handling:
        st.info("A human agent is handling this chat.")
        if st.button("Check for agent replies", key="refresh_chat"):
            load_conversation(uid, st.session_state.conversation_id)
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
    if text and send(uid, text):
        st.rerun()   # redraw so the Yes and No buttons match the new state


# ------------------------------------------------------------------ agent queue

def agent_view(user: dict):
    uid = user["employee_id"]
    st.title("Agent queue")

    left, right = st.columns([2, 1])
    # "active" is the default, so a ticket does not vanish from the list the moment you claim it
    status = left.selectbox("Show tickets", ["active", "open", "in_progress", "resolved", "closed", "all"],
                            key="ticket_filter")
    if right.button("Refresh", key="refresh_queue"):
        st.rerun()

    try:
        rows = api.tickets(uid)
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
            api.update_ticket(uid, ticket["id"], assign_to_me=True)
            st.rerun()
        if buttons[1].button("Resolve", key="resolve"):
            api.update_ticket(uid, ticket["id"], status="resolved")
            st.rerun()
        if buttons[2].button("Close", key="close"):
            api.update_ticket(uid, ticket["id"], status="closed")
            st.rerun()
        if buttons[3].button("Reopen", key="reopen"):
            api.update_ticket(uid, ticket["id"], status="in_progress")
            st.rerun()
    except api.ApiError as exc:
        show_error(exc)

    cid = ticket["conversation_id"]
    if cid is None:
        return st.caption("This ticket has no chat.")

    st.markdown("**Conversation**")
    try:
        data = api.conversation_messages(uid, cid)
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
                api.agent_reply(uid, cid, reply.strip())
                st.rerun()
            except api.ApiError as exc:
                show_error(exc)


# ------------------------------------------------------------------ dashboard

def pct(value):
    return "n/a" if value is None else f"{value:.0%}"


def dashboard_view(user: dict):
    uid = user["employee_id"]
    st.title("Dashboard")
    if st.button("Refresh", key="refresh_dashboard"):
        st.rerun()
    try:
        m = api.metrics(uid)
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
        logs = api.audit_logs(uid, 30)
        if logs:
            st.dataframe(pd.DataFrame(logs)[["created_at", "action", "entity_type", "entity_id", "user_id"]],
                         hide_index=True, width="stretch")
    except api.ApiError as exc:
        show_error(exc)


# ------------------------------------------------------------------ knowledge base

def kb_view(user: dict):
    uid = user["employee_id"]
    st.title("Knowledge base")
    try:
        docs = api.kb_list(uid)
    except api.ApiError as exc:
        return show_error(exc)

    pending = sum(1 for d in docs if not d["indexed_at"])
    st.caption(f"{len(docs)} SOPs, {pending} not indexed yet.")
    st.dataframe(pd.DataFrame(docs), hide_index=True, width="stretch")

    col1, col2, _ = st.columns([1, 1, 3])
    if col1.button("Re-index changed SOPs", key="reindex"):
        try:
            with st.spinner("Indexing..."):
                st.success(f"Done: {api.kb_reindex(uid)}")
        except api.ApiError as exc:
            show_error(exc)
    if col2.button("Rebuild everything", key="reindex_force"):
        try:
            with st.spinner("Indexing..."):
                st.success(f"Done: {api.kb_reindex(uid, force=True)}")
        except api.ApiError as exc:
            show_error(exc)

    pick = st.selectbox("Preview an SOP", [f"{d['sop_id']} · {d['title']}" for d in docs], key="sop_pick")
    try:
        st.markdown(api.kb_doc(uid, pick.split(" · ")[0])["text"])
    except api.ApiError as exc:
        show_error(exc)


# ------------------------------------------------------------------ main

def main():
    with st.sidebar:
        st.header("CapstoneCompany IT")
        who = st.selectbox("Sign in as (demo)", list(DEMO_USERS), key="who")
    employee_id = DEMO_USERS[who]

    try:
        user = api.request("GET", "/me", employee_id)
    except api.ApiError as exc:
        return show_error(exc)

    if st.session_state.get("signed_in_as") != employee_id:   # switching user starts fresh
        st.session_state.signed_in_as = employee_id
        st.session_state.pop("view", None)   # land on the first screen for the new role
        reset_chat()

    views = VIEWS_BY_ROLE[user["role"]]
    with st.sidebar:
        st.caption(f"Role: {user['role']}")
        view = st.radio("Go to", views, key="view")

    {"Chat": chat_view, "Agent queue": agent_view, "Dashboard": dashboard_view,
     "Knowledge base": kb_view}[view](user)


main()
