import os
import time
from datetime import datetime
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

import api
import ui

st.set_page_config(page_title="CapstoneCompany IT Helpdesk", page_icon="🛠️", layout="wide")
ui.inject_css()

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

# One-click prompts on the empty chat screen. Each matches an SOP in kb/.
SUGGESTIONS = [
    ("🔑", "I forgot my password"),
    ("🌐", "How do I set up the VPN on Windows?"),
    ("📶", "My Wi-Fi keeps disconnecting"),
    ("📧", "Outlook is not syncing my email"),
    ("🖨️", "How do I add a printer?"),
    ("🎣", "I think I clicked a phishing link"),
]
RESOLVED_TEXT = "Thanks, that worked"
UNRESOLVED_TEXT = "It still does not work"
INTENT_LABELS = {
    "password_reset": "Password reset", "account_locked": "Account locked", "vpn_help": "VPN",
    "access_request": "Access request", "hardware_request": "Hardware", "security_incident": "Security incident",
    "policy_info": "Policy", "how_to": "How-to", "greeting": "Greeting", "out_of_scope": "Out of scope",
}


def typewriter(text: str):
    for word in text.split(" "):
        yield word + " "
        time.sleep(STREAM_DELAY)


def show_error(exc: api.ApiError):
    st.error(str(exc))


def nice(name: str | None) -> str:
    return INTENT_LABELS.get(name or "", (name or "").replace("_", " ").capitalize())


# ------------------------------------------------------------------ chat

def sources_caption(sources: list[dict]):
    """The SOPs an answer came from, as clickable-looking chips. Plain text stays in the caption for screen readers."""
    chips = "".join(f'<span class="chip src">📄 {escape(s["sop_id"])} · {escape(s["title"])}</span>' for s in sources)
    st.caption(f'Sources: <span class="chip-row">{chips}</span>', unsafe_allow_html=True)


def insight_chips(meta: dict):
    """Intent, confidence, route and response time under an assistant answer."""
    chips = []
    if meta.get("intent"):
        chips.append(f'<span class="chip">🎯 {escape(nice(meta["intent"]))}</span>')
    if meta.get("confidence") is not None:
        pct_value = max(0, min(100, round(float(meta["confidence"]) * 100)))
        chips.append(f'<span class="chip">Confidence <span class="bar"><i style="width:{pct_value}%"></i></span> {pct_value}%</span>')
    if meta.get("grounded"):
        chips.append('<span class="chip">✅ Grounded in SOPs</span>')
    if meta.get("tool"):
        chips.append(f'<span class="chip">🛠️ {escape(meta["tool"].replace("_", " "))}</span>')
    if meta.get("latency_ms"):
        chips.append(f'<span class="chip">⚡ {meta["latency_ms"] / 1000:.1f}s</span>')
    if chips:
        st.html(f'<div class="chip-row">{"".join(chips)}</div>')


def render_message(item: dict):
    with st.chat_message(item["role"]):
        if item.get("label"):
            st.caption(item["label"])
        st.markdown(item["content"])
        meta = item.get("meta")
        if meta:
            if meta.get("ticket_key"):
                st.success(f"Ticket {meta['ticket_key']} created. An agent will pick it up.", icon="🎫")
            if meta.get("sources"):
                sources_caption(meta["sources"])
            insight_chips(meta)
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
        typing = st.empty()
        typing.html(ui.TYPING)
        try:
            resp = api.chat(token, text, st.session_state.conversation_id)
        except api.ApiError as exc:
            typing.empty()
            show_error(exc)
            return False
        typing.empty()
        st.session_state.conversation_id = resp["conversation_id"]
        st.session_state.pending = resp["pending_confirmation"]
        st.session_state.agent_handling = bool(resp.get("agent_handling"))
        if resp.get("agent_handling"):
            st.info("A human agent is handling this chat. They will reply here.", icon="🧑‍💻")
            return True
        if STREAM_DELAY > 0:
            st.write_stream(typewriter(resp["reply"]))
        else:
            st.markdown(resp["reply"])
        if resp.get("ticket_key"):
            st.success(f"Ticket {resp['ticket_key']} created. An agent will pick it up.", icon="🎫")
        if resp["sources"]:
            sources_caption(resp["sources"])
    st.session_state.history.append({"role": "assistant", "content": resp["reply"], "meta": resp})
    return True


def transcript(user: dict) -> str:
    lines = [f"# IT Helpdesk chat", f"{user['name']} ({user['employee_id']}) · {datetime.now():%Y-%m-%d %H:%M}", ""]
    for item in st.session_state.history:
        who = "You" if item["role"] == "user" else (item.get("label") or "Assistant")
        lines.append(f"**{who}:** {item['content']}")
        sources = (item.get("meta") or {}).get("sources") or []
        if sources:
            lines.append("Sources: " + ", ".join(f"{s['sop_id']} {s['title']}" for s in sources))
        lines.append("")
    return "\n".join(lines)


def welcome(token: str) -> str | None:
    """Empty-chat screen: a greeting and one-click suggestions. Returns the picked suggestion, if any."""
    st.html(f'<div class="welcome"><div class="float" style="display:inline-block">{ui.logo(96)}</div>'
            '<h3>How can I help today?</h3>'
            '<p>Ask about passwords, VPN, Wi-Fi, email, printers or security. I answer from company SOPs, '
            'reset passwords and open tickets for you.</p></div>')
    picked = None
    cols = st.columns(3)
    for i, (icon, text) in enumerate(SUGGESTIONS):
        if cols[i % 3].button(f"{icon}  {text}", key=f"suggest_{i}", width="stretch"):
            picked = text
    return picked


def last_answer_meta() -> dict | None:
    if not st.session_state.history:
        return None
    last = st.session_state.history[-1]
    return last.get("meta") if last["role"] == "assistant" else None


def chat_view(user: dict):
    token = user["token"]
    for key, default in (("history", []), ("conversation_id", None), ("pending", False),
                         ("agent_handling", False)):
        st.session_state.setdefault(key, default)

    st.title("IT Helpdesk Assistant")
    ui.subtitle("Answers from CapstoneCompany SOPs, with sources. Password resets and tickets in one chat.")

    with st.sidebar:
        st.subheader("Conversations")
        if st.button("✨ New chat", key="new_chat", width="stretch"):
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
        if st.session_state.history:
            st.download_button("⬇️ Download transcript", transcript(user), file_name="helpdesk-chat.md",
                               mime="text/markdown", key="download_chat", width="stretch")

    quick = None
    if not st.session_state.history:
        quick = welcome(token)

    for item in st.session_state.history:
        render_message(item)

    if st.session_state.agent_handling:
        st.info("A human agent is handling this chat.", icon="🧑‍💻")
        if st.button("🔄 Check for agent replies", key="refresh_chat"):
            load_conversation(token, st.session_state.conversation_id)
            st.rerun()

    if st.session_state.pending:
        yes_col, no_col, _ = st.columns([1, 1, 4])
        if yes_col.button("✅ Yes, go ahead", key="quick_yes", type="primary"):
            quick = "yes"
        if no_col.button("✖️ No, cancel", key="quick_no"):
            quick = "no"
    else:
        meta = last_answer_meta()
        if meta and meta.get("grounded") and not st.session_state.agent_handling:
            st.caption("Did this solve your problem?")
            good, bad, _ = st.columns([1, 1, 3])
            if good.button("👍 That fixed it", key="fb_yes", width="stretch"):
                quick = RESOLVED_TEXT
            if bad.button("👎 Still not working", key="fb_no", width="stretch"):
                quick = UNRESOLVED_TEXT

    prompt = st.chat_input("Describe your IT problem…")
    text = prompt or quick
    if text and send(token, text):
        st.rerun()   # redraw so the Yes and No buttons match the new state


# ------------------------------------------------------------------ agent queue

def ticket_card(ticket: dict) -> str:
    def when(value):
        return escape(str(value or "—")[:16].replace("T", " "))

    return f"""
<div class="card" style="margin:.4rem 0 1rem">
  <div class="ticket-head">
    <span class="key">{escape(ticket['ticket_key'])}</span>
    {ui.priority_badge(ticket['priority'])} {ui.status_badge(ticket['status'])}
  </div>
  <div style="font-size:1.1rem;font-weight:700;margin-top:10px">{escape(ticket['title'])}</div>
  <div class="ticket-meta">
    <div>Requester<b>{escape(ticket.get('requester') or '—')}</b></div>
    <div>Assigned to<b>{escape(str(ticket.get('assigned_to') or 'Unassigned'))}</b></div>
    <div>Created<b>{when(ticket.get('created_at'))}</b></div>
    <div>Resolved<b>{when(ticket.get('resolved_at'))}</b></div>
  </div>
</div>"""


def agent_view(user: dict):
    token = user["token"]
    st.title("Agent queue")
    ui.subtitle("Tickets sorted by priority. Claim one, talk to the employee, and close it out.")

    left, right = st.columns([2, 1], vertical_alignment="bottom")
    # "active" is the default, so a ticket does not vanish from the list the moment you claim it
    status = left.selectbox("Show tickets", ["active", "open", "in_progress", "resolved", "closed", "all"],
                            key="ticket_filter")
    if right.button("🔄 Refresh", key="refresh_queue", width="stretch"):
        st.rerun()

    try:
        all_rows = api.tickets(token)
    except api.ApiError as exc:
        return show_error(exc)

    active = [t for t in all_rows if t["status"] in ("open", "in_progress")]
    st.html(ui.stat_cards([
        ("📥", "Open", sum(t["status"] == "open" for t in all_rows)),
        ("⏳", "In progress", sum(t["status"] == "in_progress" for t in all_rows)),
        ("🚨", "Urgent (P1–P2)", sum(t["priority"] in ("P1", "P2") for t in active)),
        ("🙋", "Unassigned", sum(not t.get("assigned_to") for t in active)),
    ]))

    if status == "active":
        rows = active
    elif status != "all":
        rows = [t for t in all_rows if t["status"] == status]
    else:
        rows = list(all_rows)
    rows.sort(key=lambda t: (PRIORITY_ORDER.get(t["priority"], 9), t["id"]))
    if not rows:
        st.info("No tickets with this status. Nice work! 🎉")
        return

    table = pd.DataFrame(rows)[["ticket_key", "priority", "title", "requester", "status", "assigned_to"]]
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "ticket_key": st.column_config.TextColumn("Ticket", width="small"),
        "priority": st.column_config.TextColumn("Priority", width="small"),
        "title": st.column_config.TextColumn("Title", width="large"),
        "requester": "Requester", "status": "Status", "assigned_to": "Assigned to",
    })

    key = st.selectbox("Open a ticket", [t["ticket_key"] for t in rows], key="ticket_pick")
    ticket = next(t for t in rows if t["ticket_key"] == key)
    st.html(ticket_card(ticket))

    buttons = st.columns(4)
    try:
        if buttons[0].button("🙋 Assign to me", key="assign_me", width="stretch"):
            api.update_ticket(token, ticket["id"], assign_to_me=True)
            st.rerun()
        if buttons[1].button("✅ Resolve", key="resolve", width="stretch", type="primary"):
            api.update_ticket(token, ticket["id"], status="resolved")
            st.rerun()
        if buttons[2].button("🔒 Close", key="close", width="stretch"):
            api.update_ticket(token, ticket["id"], status="closed")
            st.rerun()
        if buttons[3].button("↩️ Reopen", key="reopen", width="stretch"):
            api.update_ticket(token, ticket["id"], status="in_progress")
            st.rerun()
    except api.ApiError as exc:
        show_error(exc)

    cid = ticket["conversation_id"]
    if cid is None:
        return st.caption("This ticket has no chat.")

    st.subheader("💬 Conversation")
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
        reply = st.text_area("Reply to the employee", key=f"reply_text_{cid}", placeholder="Type your reply…")
        if st.form_submit_button("📨 Send reply", type="primary") and reply.strip():
            try:
                api.agent_reply(token, cid, reply.strip())
                st.rerun()
            except api.ApiError as exc:
                show_error(exc)


# ------------------------------------------------------------------ dashboard

def pct(value):
    return "n/a" if value is None else f"{value:.0%}"


def _chart_style(chart: alt.Chart, height: int = 240) -> alt.Chart:
    """Dark, recessive axes and grid so the data marks carry the colour."""
    return (chart.properties(height=height, background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor=ui.TEXT_MUTED, titleColor=ui.TEXT_MUTED, gridColor=ui.GRID,
                            domainColor=ui.GRID, tickColor=ui.GRID, labelFont="Inter", titleFont="Inter")
            .configure_legend(labelColor=ui.TEXT, titleColor=ui.TEXT_MUTED))


def messages_chart(rows: list[dict]):
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    base = alt.Chart(df).encode(x=alt.X("day:T", title=None, axis=alt.Axis(format="%b %d", grid=False)))
    area = base.mark_area(
        line={"color": ui.SERIES, "strokeWidth": 2}, interpolate="monotone",
        color=alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                           stops=[alt.GradientStop(color="rgba(51,140,237,0.02)", offset=0),
                                  alt.GradientStop(color="rgba(51,140,237,0.45)", offset=1)]),
    ).encode(y=alt.Y("messages:Q", title=None))
    hover = alt.selection_point(fields=["day"], nearest=True, on="pointerover", empty=False)
    points = base.mark_circle(size=90, color=ui.SERIES, stroke=ui.SURFACE, strokeWidth=2).encode(
        y="messages:Q",
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("day:T", title="Day", format="%b %d"), alt.Tooltip("messages:Q", title="Messages")],
    ).add_params(hover)
    rule = base.mark_rule(color=ui.TEXT_MUTED, strokeDash=[3, 3]).encode(
        opacity=alt.condition(hover, alt.value(0.6), alt.value(0))).transform_filter(hover)
    st.altair_chart(_chart_style(area + rule + points), width="stretch")


def bar_chart(series: dict, label: str, colors: dict | None = None, sort_desc: bool = True):
    df = pd.DataFrame({"name": list(series), "count": list(series.values())})
    df["label"] = df["name"].map(nice) if not colors else df["name"]
    order = df.sort_values("count", ascending=not sort_desc)["label"].tolist() if sort_desc else df["label"].tolist()
    color = (alt.Color("name:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None)
             if colors else alt.value(ui.SERIES))
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height={"band": 0.62}).encode(
        y=alt.Y("label:N", sort=order, title=None, axis=alt.Axis(grid=False, labelLimit=160)),
        x=alt.X("count:Q", title=None, axis=alt.Axis(tickMinStep=1)),
        color=color,
        tooltip=[alt.Tooltip("label:N", title=label), alt.Tooltip("count:Q", title="Count")],
    )
    text = chart.mark_text(align="left", dx=6, fontWeight=600).encode(text="count:Q", color=alt.value(ui.TEXT))
    st.altair_chart(_chart_style(chart + text, height=max(120, 38 * len(df))), width="stretch")


def section(title: str):
    st.markdown(f"#### {title}")


def dashboard_view(user: dict):
    token = user["token"]
    st.title("Dashboard")
    ui.subtitle("How the assistant is doing: deflection, escalations, speed and safety.")
    if st.button("🔄 Refresh", key="refresh_dashboard"):
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

    left, right = st.columns(2, gap="large")
    with left:
        with st.container(border=True):
            section("📈 Messages per day")
            if m["messages_per_day"]:
                messages_chart(m["messages_per_day"])
            else:
                st.caption("No messages yet.")
        with st.container(border=True):
            section("🚦 Tickets by priority")
            if m["tickets"]["by_priority"]:
                by_priority = {p: m["tickets"]["by_priority"][p] for p in sorted(m["tickets"]["by_priority"])}
                bar_chart(by_priority, "Priority", colors={p: ui.PRIORITY_COLORS.get(p, ui.SERIES) for p in by_priority},
                          sort_desc=False)
            else:
                st.caption("No tickets yet.")
    with right:
        with st.container(border=True):
            section("🎯 What people ask about")
            if m["intents"]:
                bar_chart(m["intents"], "Intent")
            else:
                st.caption("No messages yet.")
        with st.container(border=True):
            section("🛠️ Tool calls")
            if m["tool_calls"]:
                st.dataframe(pd.DataFrame(m["tool_calls"]), hide_index=True, width="stretch")
            else:
                st.caption("No tool calls yet.")

    section("🧾 Latest audit log")
    try:
        logs = api.audit_logs(token, 30)
        if logs:
            st.dataframe(pd.DataFrame(logs)[["created_at", "action", "entity_type", "entity_id", "user_id"]],
                         hide_index=True, width="stretch")
    except api.ApiError as exc:
        show_error(exc)

    with st.expander("📬 Mock email outbox (demo)"):
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

def kb_cards(docs: list[dict]) -> str:
    cells = []
    for i, d in enumerate(docs):
        state = (ui.badge("indexed", "#0aac23") if d.get("indexed_at") else ui.badge("not indexed", "#fbb315"))
        cells.append(
            f'<div class="card kb-card" style="animation-delay:{min(i, 12) * 0.03:.2f}s">'
            f'<div class="id">{escape(d["sop_id"])} · {escape(d.get("category") or "")}</div>'
            f'<div class="t">{escape(d["title"])}</div>{state}</div>')
    return f'<div class="kb-grid">{"".join(cells)}</div>'


def kb_view(user: dict):
    token = user["token"]
    st.title("Knowledge base")
    try:
        docs = api.kb_list(token)
    except api.ApiError as exc:
        return show_error(exc)

    pending = sum(1 for d in docs if not d["indexed_at"])
    st.caption(f"{len(docs)} SOPs, {pending} not indexed yet.")

    search_col, cat_col = st.columns([2, 1])
    query = search_col.text_input("Search SOPs", key="kb_search", placeholder="🔎  Search by ID or title…")
    categories = sorted({d.get("category") or "Other" for d in docs})
    category = cat_col.selectbox("Category", ["All"] + categories, key="kb_category")
    shown = [d for d in docs
             if (category == "All" or (d.get("category") or "Other") == category)
             and (not query or query.lower() in f"{d['sop_id']} {d['title']}".lower())]
    if shown:
        st.html(kb_cards(shown))
    else:
        st.info("No SOP matches that search.")

    col1, col2, _ = st.columns([1, 1, 2])
    if col1.button("⚡ Re-index changed SOPs", key="reindex", width="stretch", type="primary"):
        try:
            with st.spinner("Indexing..."):
                st.success(index_summary(api.kb_reindex(token)), icon="✅")
        except api.ApiError as exc:
            show_error(exc)
    if col2.button("♻️ Rebuild everything", key="reindex_force", width="stretch"):
        try:
            with st.spinner("Indexing..."):
                st.success(index_summary(api.kb_reindex(token, force=True)), icon="✅")
        except api.ApiError as exc:
            show_error(exc)

    pool = shown or docs
    pick = st.selectbox("Preview an SOP", [f"{d['sop_id']} · {d['title']}" for d in pool], key="sop_pick")
    try:
        with st.container(border=True):
            st.markdown(api.kb_doc(token, pick.split(" · ")[0])["text"])
    except api.ApiError as exc:
        show_error(exc)


def index_summary(result: dict) -> str:
    if not isinstance(result, dict):
        return f"Done: {result}"
    return (f"Done: re-indexed {result.get('indexed', 0)} SOPs, skipped {result.get('skipped', 0)}, "
            f"{result.get('chunks', 0)} chunks written, {result.get('removed', 0)} removed.")


# ------------------------------------------------------------------ sign in

SESSION_KEYS = ("token", "signed_in_as", "view", "history", "conversation_id", "pending", "agent_handling",
                "conv_picker")
FEATURES = [
    ("📚", "Answers you can check", "Every answer cites the company SOP it came from."),
    ("⚡", "Fixes, not just advice", "Password resets and tickets happen right in the chat."),
    ("🧑‍💻", "A human when it matters", "Urgent or stuck issues go straight to an agent."),
]


def sign_out(notice: str | None = None):
    for key in SESSION_KEYS:
        st.session_state.pop(key, None)
    if notice:
        st.session_state["notice"] = notice


def fill_demo(employee_id: str, password: str):
    st.session_state.login_id = employee_id
    st.session_state.login_password = password


def login_view():
    hero, form_col = st.columns([1.15, 1], gap="large")
    with hero:
        st.html(f'<div class="hero"><span class="tag">● AI-powered IT support</span></div>')
        st.title("CapstoneCompany IT Helpdesk")
        feats = "".join(f'<div class="feat"><div class="i">{i}</div><div><b>{escape(t)}</b><span>{escape(d)}</span></div></div>'
                        for i, t, d in FEATURES)
        st.html('<div class="hero"><p class="lead">Get unstuck in seconds. Ask in plain words and the assistant '
                f'answers from company procedures, around the clock.</p>{feats}</div>')

    with form_col:
        st.html(ui.hero_illustration())
        notice = st.session_state.pop("notice", None)
        if notice:
            st.warning(notice)
        done = st.session_state.pop("login_success", None)
        if done:
            st.success(done)

        with st.form("login"):
            st.markdown("##### Sign in")
            employee_id = st.text_input("Employee ID", key="login_id", placeholder="E-1001")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Sign in →", type="primary", width="stretch")
        if submitted:
            try:
                result = api.login(employee_id.strip(), password)
            except api.ApiError as exc:
                show_error(exc)
            else:
                st.session_state.token = result["access_token"]
                st.rerun()

        if SHOW_DEMO_LOGINS:
            st.caption("Demo accounts: click one to fill in the form.")
            cols = st.columns(len(DEMO_ACCOUNTS))
            for col, (who, pw, role) in zip(cols, DEMO_ACCOUNTS):
                col.button(f"{role}\n\n`{who}`", key=f"demo_{who}", width="stretch",
                           on_click=fill_demo, args=(who, pw))


def reset_view(reset_token: str):
    """Opened from the link in the reset email: ?reset_token=..."""
    _, mid, _ = st.columns([1, 1.6, 1])
    with mid:
        st.html(f'<div style="text-align:center" class="float">{ui.logo(110)}</div>')
        st.title("Choose a new password")
        with st.form("reset"):
            new_password = st.text_input("New password", type="password", key="reset_new")
            confirm = st.text_input("Repeat the new password", type="password", key="reset_confirm")
            submitted = st.form_submit_button("Change password", type="primary", width="stretch")
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
        if st.button("← Back to sign in", key="reset_cancel"):
            st.query_params.clear()
            st.session_state["reset_done"] = True
            st.rerun()


# ------------------------------------------------------------------ main

def api_online() -> bool:
    try:
        return api.health().get("status") == "ok"
    except (api.ApiError, AttributeError):
        return False


def sidebar(user: dict, views: list[str]) -> str:
    with st.sidebar:
        st.html(f'<div class="brand">{ui.logo(38)}<div>CapstoneCompany IT<small>Helpdesk assistant</small></div></div>')
        st.html(f'<div class="profile"><div class="avatar">{escape(ui.initials(user["name"]))}</div>'
                f'<div><div class="n">{escape(user["name"])}</div><div class="role">{escape(user["role"])}</div></div></div>')
        online = api_online()
        st.html(f'<div class="status"><span class="pulse{"" if online else " down"}"></span>'
                f'{"All systems online" if online else "API not responding"}</div>')
        view = st.radio("Go to", views, key="view")
        if st.button("↪ Sign out", key="sign_out", width="stretch"):
            sign_out()
            st.rerun()
    return view


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

    view = sidebar(user, VIEWS_BY_ROLE[user["role"]])
    {"Chat": chat_view, "Agent queue": agent_view, "Dashboard": dashboard_view,
     "Knowledge base": kb_view}[view](user)


main()
