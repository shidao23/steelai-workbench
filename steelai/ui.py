from __future__ import annotations


def setup_page(st, title: str, icon: str = "🧪") -> None:
    embedded = bool(st.session_state.get("_steelai_embedded_view", False))
    router_configured = bool(st.session_state.get("_steelai_router_configured", False))
    if not embedded and not router_configured:
        st.set_page_config(page_title=f"{title} | SteelAI", page_icon=icon, layout="wide")
    st.markdown("""
    <style>
      .block-container {padding-top: 1.35rem; padding-bottom: 3rem; max-width: 1320px;}
      h1 {font-size:2.25rem !important; letter-spacing:-0.025em; margin-bottom:.35rem !important;}
      h2 {font-size:1.55rem !important; margin-top:1.35rem !important;}
      h3 {font-size:1.18rem !important; margin-top:1.1rem !important;}
      [data-testid="stMetric"] {background:#f7f8fa; border:1px solid #e5e7eb; padding:14px; border-radius:12px;}
      [data-testid="stSidebarNav"] li {margin-bottom:.18rem;}
      [data-testid="stSidebarNav"] a {border-radius:9px;}
      [data-testid="stSidebarNav"] a[aria-current="page"] {background:#eaf0ff; font-weight:600;}
      [data-testid="stRadio"] > div {gap:.35rem;}
      [data-testid="stRadio"] label {background:#f7f8fa; border:1px solid #e5e7eb; padding:.35rem .8rem; border-radius:999px;}
      [data-testid="stAppDeployButton"], #MainMenu {display:none;}
      .demo-banner {padding:10px 14px; border-radius:10px; background:#fff7ed; color:#9a3412; border:1px solid #fed7aa; margin-bottom:14px;}
      .small-note {color:#64748b; font-size:.9rem;}
    </style>
    """, unsafe_allow_html=True)
    if embedded:
        st.subheader(title.split("·")[-1].strip())
    else:
        st.title(title)


def demo_warning(st, rows: list[dict]) -> None:
    if any(str(row.get("is_demo", "")).lower() == "true" for row in rows):
        st.markdown('<div class="demo-banner">当前包含 DEMO 数据，仅用于验证应用流程，不得作为科研结论。</div>', unsafe_allow_html=True)
