from __future__ import annotations


def setup_page(st, title: str, icon: str = "🧪", *, show_title: bool = True) -> None:
    embedded = bool(st.session_state.get("_steelai_embedded_view", False))
    router_configured = bool(st.session_state.get("_steelai_router_configured", False))
    if not embedded and not router_configured:
        st.set_page_config(page_title=f"{title} | SteelAI", page_icon=icon, layout="wide")
    st.markdown("""
    <style>
      :root {--steel-navy:#0b1f3a; --steel-blue:#2563eb; --steel-cyan:#0ea5a8; --steel-bg:#f4f7fb;}
      .stApp {background:linear-gradient(180deg,#f8fafc 0,#f4f7fb 42%,#f7f9fc 100%);}
      .block-container {padding-top: 1.35rem; padding-bottom: 3rem; max-width: 1320px;}
      h1 {font-size:2.25rem !important; letter-spacing:-0.025em; margin-bottom:.35rem !important;}
      h2 {font-size:1.55rem !important; margin-top:1.35rem !important;}
      h3 {font-size:1.18rem !important; margin-top:1.1rem !important;}
      [data-testid="stMetric"] {background:rgba(255,255,255,.9); border:1px solid #dce4ef; padding:16px 18px; border-radius:16px; box-shadow:0 8px 24px rgba(15,23,42,.045);}
      [data-testid="stMetricLabel"] {color:#64748b;}
      [data-testid="stMetricValue"] {color:var(--steel-navy); letter-spacing:-.025em;}
      [data-testid="stSidebar"] {background:#f0f4f8; border-right:1px solid #dce4ef;}
      [data-testid="stSidebarNav"] li {margin-bottom:.18rem;}
      [data-testid="stSidebarNav"] a {border-radius:10px;}
      [data-testid="stSidebarNav"] a[aria-current="page"] {background:#dce8fb; color:#123c73; font-weight:700;}
      [data-testid="stRadio"] > div {gap:.35rem;}
      [data-testid="stRadio"] label {background:#fff; border:1px solid #dce4ef; padding:.35rem .8rem; border-radius:999px;}
      [data-testid="stAppDeployButton"], #MainMenu {display:none;}
      .demo-banner {padding:10px 14px; border-radius:10px; background:#fff7ed; color:#9a3412; border:1px solid #fed7aa; margin-bottom:14px;}
      .small-note {color:#64748b; font-size:.9rem;}
      .steel-hero {position:relative; overflow:hidden; padding:34px 38px; border-radius:24px; color:#fff; background:linear-gradient(120deg,#081a32 0%,#103a66 58%,#0f6b78 100%); box-shadow:0 22px 55px rgba(8,26,50,.18); margin-bottom:18px;}
      .steel-hero:after {content:""; position:absolute; width:330px; height:330px; border-radius:50%; right:-95px; top:-185px; border:55px solid rgba(255,255,255,.07);}
      .steel-eyebrow {display:inline-flex; align-items:center; gap:8px; font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:#a7f3d0; margin-bottom:12px;}
      .steel-hero h1 {color:#fff !important; font-size:2.42rem !important; max-width:900px; line-height:1.12 !important; margin:0 0 12px !important;}
      .steel-hero p {max-width:780px; color:#dbeafe; font-size:1.02rem; line-height:1.7; margin:0;}
      .steel-chip {display:inline-block; margin:20px 8px 0 0; padding:7px 11px; border:1px solid rgba(255,255,255,.2); border-radius:999px; background:rgba(255,255,255,.08); color:#eff6ff; font-size:.82rem;}
      .section-kicker {color:#2563eb; font-size:.76rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; margin:1.55rem 0 .2rem;}
      .section-title {color:#0b1f3a; font-size:1.45rem; font-weight:750; letter-spacing:-.02em; margin:0 0 .85rem;}
      .flow-card {min-height:148px; padding:20px; border-radius:18px; background:#fff; border:1px solid #dce4ef; box-shadow:0 10px 30px rgba(15,23,42,.05);}
      .flow-step {color:#2563eb; font-size:.72rem; font-weight:800; letter-spacing:.09em;}
      .flow-title {color:#0b1f3a; font-weight:750; font-size:1.04rem; margin:9px 0 7px;}
      .flow-copy {color:#64748b; font-size:.86rem; line-height:1.55;}
      .flow-ok {display:inline-block; margin-top:12px; color:#047857; background:#ecfdf5; border-radius:999px; padding:4px 9px; font-size:.75rem; font-weight:700;}
      .sample-card {padding:20px 22px; border-radius:18px; background:linear-gradient(145deg,#fff,#f8fafc); border:1px solid #dce4ef; box-shadow:0 10px 28px rgba(15,23,42,.045);}
      .sample-id {color:#0b1f3a; font-size:1.25rem; font-weight:800; margin-bottom:4px;}
      .sample-meta {color:#64748b; font-size:.88rem; line-height:1.55;}
      .status-pill {display:inline-block; color:#1d4ed8; background:#eff6ff; border-radius:999px; padding:5px 10px; font-size:.75rem; font-weight:700; margin-top:10px;}
      div[data-testid="stLinkButton"] a {border-radius:12px; min-height:44px; font-weight:700;}
      div[data-testid="stButton"] button {border-radius:12px; min-height:44px; font-weight:700;}
      div[data-testid="stExpander"] {border:1px solid #dce4ef; border-radius:14px; background:rgba(255,255,255,.72);}
    </style>
    """, unsafe_allow_html=True)
    if not show_title:
        return
    if embedded:
        st.subheader(title.split("·")[-1].strip())
    else:
        st.title(title)


def demo_warning(st, rows: list[dict]) -> None:
    if any(str(row.get("is_demo", "")).lower() == "true" for row in rows):
        st.markdown('<div class="demo-banner">当前包含 DEMO 数据，仅用于验证应用流程，不得作为科研结论。</div>', unsafe_allow_html=True)
