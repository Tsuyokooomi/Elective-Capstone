"""Look and feel: the global stylesheet, the animated logo, and small HTML building blocks.

Everything here is presentation only. The screens in app.py still use regular Streamlit
widgets for anything a user clicks or types into, so the behaviour stays testable.
"""
import base64
from html import escape

import streamlit as st

# Colours shared by the stylesheet and the charts
ACCENT = "#7c5cff"
ACCENT_2 = "#22d3ee"
SERIES = "#338ced"           # single-series charts (dataviz reference blue, dark step)
SURFACE = "#111a2e"
TEXT = "#e6e9f5"
TEXT_MUTED = "#98a2c3"
GRID = "rgba(255,255,255,0.07)"
# Priorities are a status scale, so they use the fixed status colours and always carry their label
PRIORITY_COLORS = {"P1": "#dc3c3d", "P2": "#f18a59", "P3": "#fbb315", "P4": "#0aac23"}
STATUS_COLORS = {"open": "#338ced", "in_progress": "#fbb315", "resolved": "#0aac23", "closed": "#98a2c3",
                 "escalated": "#f18a59"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --accent: #7c5cff;
  --accent-2: #22d3ee;
  --accent-3: #f472b6;
  --bg: #070b18;
  --glass: rgba(255,255,255,0.045);
  --glass-strong: rgba(255,255,255,0.075);
  --border: rgba(255,255,255,0.09);
  --text: #e6e9f5;
  --muted: #98a2c3;
}

html, body, .stApp, [class*="css"] { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }

/* ---------- animated backdrop: drifting aurora blobs over a faint grid ---------- */
.stApp {
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(124,92,255,0.18), transparent 60%),
    radial-gradient(900px 500px at 110% 10%, rgba(34,211,238,0.12), transparent 60%),
    var(--bg);
  color: var(--text);
}
.stApp::before, .stApp::after {
  content: ""; position: fixed; z-index: 0; pointer-events: none;
  width: 46vmax; height: 46vmax; border-radius: 50%; filter: blur(90px); opacity: .35;
}
.stApp::before { background: #7c5cff; top: -18vmax; left: -12vmax; animation: drift1 26s ease-in-out infinite alternate; }
.stApp::after  { background: #0ea5e9; bottom: -22vmax; right: -14vmax; animation: drift2 32s ease-in-out infinite alternate; }
@keyframes drift1 { to { transform: translate(18vmax, 14vmax) scale(1.15); } }
@keyframes drift2 { to { transform: translate(-16vmax, -10vmax) scale(.9); } }
[data-testid="stAppViewContainer"]::before {
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 50% 0%, #000 30%, transparent 80%);
}
[data-testid="stAppViewContainer"] > * { position: relative; z-index: 1; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stAppDeployButton"], #MainMenu, footer { display: none !important; }
.block-container { padding-top: 2.2rem; max-width: 1200px; }

/* ---------- entrance motion ---------- */
@keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@keyframes pop  { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: none; } }
.block-container [data-testid="stVerticalBlock"] > div { animation: rise .55s cubic-bezier(.2,.7,.2,1) both; }
.block-container [data-testid="stVerticalBlock"] > div:nth-child(2) { animation-delay: .05s; }
.block-container [data-testid="stVerticalBlock"] > div:nth-child(3) { animation-delay: .10s; }
.block-container [data-testid="stVerticalBlock"] > div:nth-child(4) { animation-delay: .15s; }
.block-container [data-testid="stVerticalBlock"] > div:nth-child(5) { animation-delay: .20s; }
.block-container [data-testid="stVerticalBlock"] > div:nth-child(n+6) { animation-delay: .25s; }

/* ---------- headings ---------- */
h1 {
  font-weight: 800 !important; letter-spacing: -0.03em;
  background: linear-gradient(90deg, #fff 0%, #c4b5fd 30%, #67e8f9 60%, #fff 100%);
  background-size: 250% auto; -webkit-background-clip: text; background-clip: text; color: transparent !important;
  animation: shimmer 8s linear infinite;
}
@keyframes shimmer { to { background-position: -250% center; } }
h2, h3 { letter-spacing: -0.02em; }
.hd-sub { color: var(--muted); margin: -0.6rem 0 1.4rem; font-size: 1.02rem; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(17,24,48,0.92), rgba(8,12,26,0.96));
  border-right: 1px solid var(--border);
  backdrop-filter: blur(18px);
}
[data-testid="stSidebar"] .stRadio > div { gap: 4px; }
[data-testid="stSidebar"] .stRadio label {
  padding: 9px 12px; border-radius: 12px; border: 1px solid transparent; width: 100%;
  transition: background .2s, border-color .2s, transform .2s;
}
[data-testid="stSidebar"] .stRadio label:hover { background: var(--glass-strong); transform: translateX(3px); }
[data-testid="stSidebar"] .stRadio label:has(input:checked) {
  background: linear-gradient(90deg, rgba(124,92,255,0.28), rgba(34,211,238,0.10));
  border-color: rgba(124,92,255,0.45);
}

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: 12px; border: 1px solid var(--border); background: var(--glass);
  color: var(--text); font-weight: 600; transition: transform .18s, box-shadow .25s, border-color .25s, background .25s;
}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
  transform: translateY(-2px); border-color: rgba(124,92,255,0.6);
  box-shadow: 0 10px 30px -10px rgba(124,92,255,0.55); color: #fff;
}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"], [data-testid="stFormSubmitButton"] > button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, #7c5cff, #4f8bff 55%, #22d3ee); border: none; color: #fff;
  background-size: 200% 200%; animation: flow 6s ease infinite;
  box-shadow: 0 8px 26px -10px rgba(124,92,255,0.8);
}
@keyframes flow { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }

/* suggestion cards on the empty chat screen */
[class*="st-key-suggest_"] button {
  min-height: 84px; text-align: left; justify-content: flex-start; padding: 14px 16px;
  background: linear-gradient(160deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
}
[class*="st-key-suggest_"] button p { font-size: .95rem; line-height: 1.35; }
[class*="st-key-suggest_"] button:hover { background: linear-gradient(160deg, rgba(124,92,255,0.22), rgba(34,211,238,0.06)); }

/* ---------- inputs, forms, expanders, tables ---------- */
[data-testid="stForm"], [data-testid="stExpander"] details, .glass-box {
  background: var(--glass); border: 1px solid var(--border) !important; border-radius: 18px;
  backdrop-filter: blur(14px);
}
[data-testid="stForm"] { padding: 1.4rem 1.4rem 1rem; box-shadow: 0 30px 80px -40px rgba(0,0,0,0.8); }
.stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {
  border-radius: 12px !important; background: rgba(5,8,20,0.55) !important; border-color: var(--border) !important;
  transition: border-color .2s, box-shadow .2s;
}
.stTextInput input:focus, .stTextArea textarea:focus { border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(124,92,255,0.25) !important; }
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid var(--border); }
[data-testid="stAlert"] { border-radius: 14px; border: 1px solid var(--border); backdrop-filter: blur(10px); animation: pop .35s both; }

/* ---------- metric tiles ---------- */
[data-testid="stMetric"] {
  position: relative; overflow: hidden;
  background: linear-gradient(160deg, rgba(255,255,255,0.065), rgba(255,255,255,0.02));
  border: 1px solid var(--border); border-radius: 18px; padding: 16px 18px;
  transition: transform .25s, border-color .25s, box-shadow .25s;
}
[data-testid="stMetric"]::before {
  content: ""; position: absolute; inset: 0 0 auto 0; height: 3px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2), var(--accent-3));
}
[data-testid="stMetric"]:hover { transform: translateY(-4px); border-color: rgba(124,92,255,0.5); box-shadow: 0 18px 40px -22px rgba(124,92,255,0.7); }
[data-testid="stMetricValue"] { font-weight: 800; letter-spacing: -0.02em; }
[data-testid="stMetricLabel"] { color: var(--muted); }

/* ---------- chat ---------- */
[data-testid="stChatMessage"] {
  background: var(--glass); border: 1px solid var(--border); border-radius: 18px;
  padding: 14px 16px; margin-bottom: 10px; animation: rise .45s cubic-bezier(.2,.7,.2,1) both;
  backdrop-filter: blur(12px);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  flex-direction: row-reverse; margin-left: auto; max-width: 82%;
  background: linear-gradient(135deg, rgba(124,92,255,0.30), rgba(79,139,255,0.18));
  border-color: rgba(124,92,255,0.35);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) { max-width: 92%; }
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
  border-radius: 12px; color: #fff;
}
[data-testid="stChatMessageAvatarUser"] { background: linear-gradient(135deg, #f472b6, #7c5cff); }
[data-testid="stChatMessageAvatarAssistant"] { background: linear-gradient(135deg, #7c5cff, #22d3ee); box-shadow: 0 0 18px rgba(34,211,238,0.45); }
[data-testid="stBottomBlockContainer"], [data-testid="stBottom"] > div { background: transparent; }
[data-testid="stChatInput"] {
  border-radius: 18px; border: 1px solid rgba(124,92,255,0.45); background: rgba(10,14,32,0.85);
  box-shadow: 0 0 0 0 rgba(124,92,255,0.5); animation: glow 3.5s ease-in-out infinite; backdrop-filter: blur(16px);
}
@keyframes glow { 50% { box-shadow: 0 0 28px -4px rgba(124,92,255,0.55); } }

/* typing indicator */
.typing { display: inline-flex; gap: 6px; align-items: center; padding: 6px 2px; color: var(--muted); font-size: .9rem; }
.typing span.dot { width: 8px; height: 8px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--accent-2)); animation: bounce 1.2s infinite ease-in-out; }
.typing span.dot:nth-child(2) { animation-delay: .15s; }
.typing span.dot:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 0%, 80%, 100% { transform: translateY(0); opacity: .45; } 40% { transform: translateY(-7px); opacity: 1; } }

/* ---------- small building blocks ---------- */
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
  font-size: .78rem; font-weight: 600; color: var(--text); background: var(--glass-strong); border: 1px solid var(--border);
}
.chip.src { background: rgba(34,211,238,0.10); border-color: rgba(34,211,238,0.35); color: #a5f3fc; }
.chip .bar { width: 46px; height: 6px; border-radius: 4px; background: rgba(255,255,255,0.12); overflow: hidden; }
.chip .bar i { display: block; height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px; font-size: .76rem; font-weight: 700; border: 1px solid; }
.badge::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }

.card {
  background: linear-gradient(160deg, rgba(255,255,255,0.065), rgba(255,255,255,0.02));
  border: 1px solid var(--border); border-radius: 18px; padding: 16px 18px; height: 100%;
  transition: transform .25s, border-color .25s, box-shadow .25s; animation: pop .45s both;
}
.card:hover { transform: translateY(-4px); border-color: rgba(124,92,255,0.5); box-shadow: 0 18px 40px -22px rgba(124,92,255,0.7); }
.card .k { color: var(--muted); font-size: .82rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }
.card .v { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; margin-top: 2px; }
.card .ic { float: right; font-size: 1.4rem; opacity: .9; }
.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 1rem; }
@media (max-width: 800px) { .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; margin: .6rem 0 1.2rem; }
.kb-card .id { font-family: ui-monospace, monospace; color: #a5b4fc; font-size: .8rem; }
.kb-card .t { font-weight: 700; margin: 4px 0 10px; }

.ticket-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.ticket-head .key { font-family: ui-monospace, monospace; font-size: 1.15rem; font-weight: 700; }
.ticket-meta { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin-top: 12px; }
.ticket-meta div { color: var(--muted); font-size: .8rem; }
.ticket-meta b { display: block; color: var(--text); font-size: .95rem; margin-top: 2px; }

.profile { display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 16px; background: var(--glass); border: 1px solid var(--border); margin: 6px 0 4px; }
.avatar { width: 42px; height: 42px; border-radius: 13px; display: grid; place-items: center; font-weight: 800; color: #fff;
  background: linear-gradient(135deg, #7c5cff, #22d3ee); box-shadow: 0 0 20px rgba(124,92,255,0.5); }
.profile .n { font-weight: 700; }
.role { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #c4b5fd; font-weight: 700; }
.status { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: .82rem; margin: 8px 2px 14px; }
.pulse { width: 9px; height: 9px; border-radius: 50%; background: #0aac23; box-shadow: 0 0 0 0 rgba(10,172,35,.7); animation: pulse 2s infinite; }
.pulse.down { background: #dc3c3d; box-shadow: 0 0 0 0 rgba(220,60,61,.7); }
@keyframes pulse { 70% { box-shadow: 0 0 0 9px rgba(0,0,0,0); } 100% { box-shadow: 0 0 0 0 rgba(0,0,0,0); } }

.brand { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 1.08rem; letter-spacing: -0.01em; }
.brand small { display: block; font-weight: 500; color: var(--muted); font-size: .75rem; }

/* login hero */
.hero { padding: 1.2rem 0; }
.hero .tag { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: .78rem; font-weight: 700; color: #c4b5fd;
  background: rgba(124,92,255,0.14); border: 1px solid rgba(124,92,255,0.4); margin-bottom: 14px; }
.hero p.lead { color: var(--muted); font-size: 1.08rem; line-height: 1.6; max-width: 34rem; }
.feat { display: flex; gap: 12px; align-items: flex-start; margin: 14px 0; animation: rise .6s both; }
.feat:nth-child(2) { animation-delay: .1s; } .feat:nth-child(3) { animation-delay: .2s; } .feat:nth-child(4) { animation-delay: .3s; }
.feat .i { flex: none; width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; font-size: 1.1rem;
  background: linear-gradient(135deg, rgba(124,92,255,0.35), rgba(34,211,238,0.18)); border: 1px solid var(--border); }
.feat b { display: block; } .feat span { color: var(--muted); font-size: .92rem; }

.hero-art { position: relative; height: 300px; margin: 6px 0 10px; }
.hero-art .orb { position: absolute; left: 50%; top: 50%; margin: -70px 0 0 -70px; filter: drop-shadow(0 0 40px rgba(124,92,255,.55)); }
.hero-art .card { position: absolute; height: auto; padding: 10px 12px; }
.logo { display: inline-block; vertical-align: middle; }
.welcome { text-align: center; padding: 1.5rem 0 1rem; }
.welcome h3 { margin: .6rem 0 .2rem; }
.welcome p { color: var(--muted); }

/* animated logo */
.float { animation: float 6s ease-in-out infinite; }
@keyframes float { 50% { transform: translateY(-10px); } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
"""


def inject_css():
    st.html(CSS)


_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<style>
.r1{transform-origin:50px 50px;animation:s 14s linear infinite}
.r2{transform-origin:50px 50px;animation:s 9s linear infinite reverse}
.c{transform-origin:50px 50px;animation:b 3.2s ease-in-out infinite}
.d{animation:t 1.4s ease-in-out infinite}.d2{animation-delay:.2s}.d3{animation-delay:.4s}
@keyframes s{to{transform:rotate(360deg)}}
@keyframes b{50%{transform:scale(1.08)}}
@keyframes t{0%,100%{opacity:.35}50%{opacity:1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>
<defs>
<linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#22d3ee"/></linearGradient>
<linearGradient id="b" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f472b6"/><stop offset="1" stop-color="#7c5cff"/></linearGradient>
<radialGradient id="g" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#a78bfa"/><stop offset=".6" stop-color="#5b5bf6"/><stop offset="1" stop-color="#0e7490"/></radialGradient>
</defs>
<circle class="r1" cx="50" cy="50" r="45" fill="none" stroke="url(#a)" stroke-width="3" stroke-dasharray="60 16 8 16" stroke-linecap="round"/>
<circle class="r2" cx="50" cy="50" r="36" fill="none" stroke="url(#b)" stroke-width="2.5" stroke-dasharray="4 10" stroke-linecap="round"/>
<g class="c">
<circle cx="50" cy="50" r="25" fill="url(#g)"/>
<path d="M39 42h22a4 4 0 0 1 4 4v9a4 4 0 0 1-4 4H49l-7 5v-5h-3a4 4 0 0 1-4-4v-9a4 4 0 0 1 4-4z" fill="#fff" opacity=".95"/>
<circle class="d" cx="44" cy="50.5" r="2" fill="#5b5bf6"/><circle class="d d2" cx="50" cy="50.5" r="2" fill="#5b5bf6"/><circle class="d d3" cx="56" cy="50.5" r="2" fill="#5b5bf6"/>
</g>
</svg>"""
_LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(_LOGO_SVG.encode()).decode()


def logo(size: int = 40) -> str:
    """Animated orb: two counter-rotating dashed rings around a breathing core with a chat glyph.
    Served as an image because st.html strips inline SVG; the animation lives inside the SVG."""
    return f'<img class="logo" src="{_LOGO_URI}" width="{size}" height="{size}" alt="">'


def hero_illustration() -> str:
    """Login page art: the big logo with floating 'chat', 'ticket' and 'resolved' cards around it."""
    return f"""
<div class="hero-art">
  <div class="orb float">{logo(140)}</div>
  <div class="card float" style="left:0;top:10px;width:165px;animation-delay:-1s">
    <div class="k">Assistant</div><div style="font-size:.88rem;margin-top:4px">VPN setup steps <span class="chip src">KB-007</span></div>
  </div>
  <div class="card float" style="right:0;top:110px;width:160px;animation-delay:-3s">
    <div class="k">Ticket</div><div style="font-size:.88rem;margin-top:4px"><span class="badge" style="color:#fbb315;border-color:#fbb31555">P3</span> CC-0042 opened</div>
  </div>
  <div class="card float" style="left:0;bottom:0;width:165px;animation-delay:-4.5s">
    <div class="k">Status</div><div style="font-size:.88rem;margin-top:4px"><span class="badge" style="color:#0aac23;border-color:#0aac2355">resolved</span> 4 min</div>
  </div>
</div>"""


def subtitle(text: str):
    st.html(f'<div class="hd-sub">{escape(text)}</div>')


def badge(text: str, color: str) -> str:
    return f'<span class="badge" style="color:{color};border-color:{color}66;background:{color}1a">{escape(text)}</span>'


def priority_badge(priority: str) -> str:
    return badge(priority, PRIORITY_COLORS.get(priority, TEXT_MUTED))


def status_badge(status: str) -> str:
    return badge(status.replace("_", " "), STATUS_COLORS.get(status, TEXT_MUTED))


def stat_cards(items: list[tuple[str, str, str]]) -> str:
    """items: (icon, label, value)."""
    cells = "".join(
        f'<div class="card" style="animation-delay:{i * 0.06:.2f}s"><span class="ic">{icon}</span>'
        f'<div class="k">{escape(label)}</div><div class="v">{escape(str(value))}</div></div>'
        for i, (icon, label, value) in enumerate(items)
    )
    return f'<div class="stat-grid">{cells}</div>'


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


TYPING = '<div class="typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span>&nbsp; Thinking</div>'
