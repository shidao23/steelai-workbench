from __future__ import annotations

from html import escape
from urllib.parse import parse_qs, urlsplit


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
      [data-testid="stSidebarNavSeparator"] {margin-top:1rem; color:#64748b; font-size:.72rem; letter-spacing:.08em; text-transform:uppercase;}
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
      .sample-card {padding:20px 22px; border-radius:18px; background:linear-gradient(145deg,#fff,#f8fafc); border:1px solid #dce4ef; box-shadow:0 10px 28px rgba(15,23,42,.045);}
      .sample-id {color:#0b1f3a; font-size:1.25rem; font-weight:800; margin-bottom:4px;}
      .sample-meta {color:#64748b; font-size:.88rem; line-height:1.55;}
      .status-pill {display:inline-block; color:#1d4ed8; background:#eff6ff; border-radius:999px; padding:5px 10px; font-size:.75rem; font-weight:700; margin-top:10px;}
      div[data-testid="stLinkButton"] a {border-radius:12px; min-height:44px; font-weight:700;}
      div[data-testid="stButton"] button {border-radius:12px; min-height:44px; font-weight:700;}
      div[data-testid="stExpander"] {border:1px solid #dce4ef; border-radius:14px; background:rgba(255,255,255,.72);}
      [data-testid="stDataFrame"] {border:1px solid #dce4ef; border-radius:14px; overflow:hidden; background:#fff;}
      [data-testid="stForm"] {background:rgba(255,255,255,.78); border:1px solid #dce4ef; border-radius:16px; padding:18px;}
      [data-testid="stTabs"] [data-baseweb="tab-list"] {gap:.4rem; border-bottom:1px solid #dce4ef;}
      [data-testid="stTabs"] button[role="tab"] {padding:.65rem .85rem;}
      .workspace-head {padding:8px 0 18px; border-bottom:1px solid #dce4ef; margin-bottom:16px;}
      .workspace-kicker {color:#0f766e; font-size:.75rem; font-weight:800; letter-spacing:.09em; text-transform:uppercase; margin-bottom:7px;}
      .workspace-title {color:#0b1f3a; font-size:2.05rem; font-weight:800; letter-spacing:-.03em; line-height:1.18; margin-bottom:9px;}
      .workspace-copy {color:#64748b; font-size:.98rem; line-height:1.65; max-width:800px;}
      .module-note {height:100%; min-height:76px; padding:12px 15px; border-radius:14px; background:#eef5ff; border:1px solid #dbeafe; color:#475569; font-size:.88rem; line-height:1.55;}
      .module-note strong {display:block; color:#123c73; font-size:.95rem; margin-bottom:2px;}
      .research-context {display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:-3px 0 18px; padding:10px 13px; border:1px solid #dce4ef; border-radius:12px; background:rgba(255,255,255,.78); color:#64748b; font-size:.82rem;}
      .research-context strong {color:#0b1f3a;}
      .research-context span {display:inline-flex; align-items:center; gap:5px;}
      .context-dot {width:5px; height:5px; border-radius:50%; background:#94a3b8;}
      [data-testid="stSegmentedControl"] {margin:.15rem 0 .65rem;}
      [data-testid="stSegmentedControl"] button {min-height:39px; border-radius:10px; font-weight:650;}
      .comparison-note {padding:12px 15px; border-left:3px solid #0ea5a8; background:#f0fdfa; color:#335b61; border-radius:0 12px 12px 0; margin:.35rem 0 1rem;}
      .workflow-strip {display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:-2px 0 18px; color:#64748b; font-size:.8rem;}
      .workflow-step {padding:6px 10px; border-radius:999px; background:#fff; border:1px solid #dce4ef;}
      .workflow-arrow {color:#94a3b8;}
      .feature-head {display:flex; align-items:center; gap:12px; margin:22px 0 8px;}
      .feature-title {color:#0b1f3a; font-size:1.35rem; font-weight:780; letter-spacing:-.02em;}
      .next-panel {margin-top:28px; padding:18px 20px 8px; border-radius:18px; background:linear-gradient(135deg,#eef5ff,#f0fdfa); border:1px solid #d6e6f5;}
      .next-kicker {color:#2563eb; font-size:.72rem; font-weight:800; letter-spacing:.09em; text-transform:uppercase;}
      .next-title {color:#0b1f3a; font-size:1.15rem; font-weight:780; margin:4px 0 2px;}
      .next-copy {color:#64748b; font-size:.86rem; margin-bottom:10px;}
    </style>
    """, unsafe_allow_html=True)
    if not show_title:
        if not embedded:
            research_context_sidebar(st)
        return
    if embedded:
        st.markdown(
            '<div class="feature-head">'
            f'<div class="feature-title">{escape(title.split("·")[-1].strip())}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.title(title)
    if not embedded:
        research_context_sidebar(st)


def research_context_sidebar(st) -> None:
    """Keep the active research object visible without exposing local paths."""
    from steelai.data import read_rows

    samples = read_rows("samples")
    sample_ids = [row.get("sample_id", "") for row in samples if row.get("sample_id")]
    st.sidebar.divider()
    st.sidebar.caption("当前研究对象")
    st.sidebar.markdown("**B/R 耐磨钢研究**")
    if not sample_ids:
        st.sidebar.caption("尚未登记样品")
        return
    active = st.session_state.get("active_sample_id")
    if active not in sample_ids:
        st.session_state["active_sample_id"] = sample_ids[0]
    st.sidebar.selectbox(
        "当前样品",
        sample_ids,
        key="active_sample_id",
        help="后续页面默认围绕这个样品组织信息；正式写入仍需逐项人工确认。",
    )


def research_context_bar(st) -> None:
    """Show the active project/sample at the top of task pages."""
    from steelai.data import read_rows

    samples = read_rows("samples")
    active_id = st.session_state.get("active_sample_id")
    active = next((row for row in samples if row.get("sample_id") == active_id), {})
    status = {
        "verified_from_source_note": "来源可追溯，方法学仍待完善",
        "verified_from_source": "来源已核验",
        "manual_extraction_verified": "人工提取已核验",
    }.get(str(active.get("data_status", "")), "待核验")
    st.markdown(
        '<div class="research-context">'
        '<span><strong>课题</strong> B/R 耐磨钢研究</span>'
        '<span class="context-dot"></span>'
        f'<span><strong>当前样品</strong> {escape(str(active_id or "未选择"))}</span>'
        '<span class="context-dot"></span>'
        f'<span><strong>数据状态</strong> {escape(status)}</span>'
        '</div>',
        unsafe_allow_html=True,
    )


def workspace_header(
    st,
    *,
    kicker: str,
    title: str,
    description: str,
    workflow: tuple[str, ...] = (),
) -> None:
    """Render a consistent, compact heading for top-level workspaces."""
    st.markdown(
        '<section class="workspace-head">'
        f'<div class="workspace-kicker">{escape(kicker)}</div>'
        f'<div class="workspace-title">{escape(title)}</div>'
        f'<div class="workspace-copy">{escape(description)}</div>'
        '</section>',
        unsafe_allow_html=True,
    )
    if workflow:
        parts = []
        for index, label in enumerate(workflow):
            if index:
                parts.append('<span class="workflow-arrow">→</span>')
            parts.append(f'<span class="workflow-step">{escape(label)}</span>')
        st.markdown('<div class="workflow-strip">' + "".join(parts) + '</div>', unsafe_allow_html=True)
    research_context_bar(st)


def module_selector(
    st,
    modules: dict[str, tuple[str, str]],
    *,
    key: str,
    compact: bool = False,
) -> str:
    """Select a user task while keeping implementation modules out of navigation."""
    labels = list(modules)
    if st.session_state.get(key) not in labels:
        st.session_state[key] = labels[0]
    if compact:
        selected = st.selectbox("当前功能", labels, key=key)
    else:
        st.caption("选择当前任务")
        selected = st.segmented_control(
            "当前任务",
            labels,
            key=key,
            label_visibility="collapsed",
        ) or labels[0]
    short_title, description = modules[selected]
    st.markdown(
        '<div class="module-note">'
        f'<strong>{escape(short_title)}</strong>{escape(description)}'
        '</div>',
        unsafe_allow_html=True,
    )
    return selected


def next_step_buttons(
    st,
    actions: list[dict[str, object]],
    *,
    key_prefix: str,
    note: str = "根据当前结果继续，不需要返回侧栏重新寻找入口。",
) -> None:
    """Render consistent cross-module next-step buttons."""
    st.markdown(
        '<div class="next-panel">'
        '<div class="next-kicker">NEXT STEP</div>'
        '<div class="next-title">下一步做什么</div>'
        f'<div class="next-copy">{escape(note)}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    def activate(action: dict[str, object]) -> None:
        for state_key, state_value in dict(action.get("state", {})).items():
            st.session_state[str(state_key)] = state_value

    def navigate(url: str) -> None:
        parsed = urlsplit(url)
        module = parse_qs(parsed.query).get("module", [""])[0]
        routes = {
            "/": ("steelai/views/dashboard_view.py", "", {}),
            "/projects": ("pages/1_数据与物理.py", "project_module_selector", {
                "samples": "样品总览", "session": "科研会话", "evidence": "证据索引",
            }),
            "/intake": ("pages/2_研究助手.py", "", {}),
            "/analysis": ("pages/3_组织与证据.py", "analysis_module_selector", {
                "physics": "物理计算", "statistics": "可追溯统计", "ebsd": "组织分析",
                "research": "研究报告", "validation": "证据验证", "runs": "运行与成果",
            }),
            "/assistant": ("pages/4_模型与自动化.py", "", {}),
            "/portfolio": ("pages/5_Career_Portfolio.py", "", {}),
            "/advanced": ("pages/6_高级功能.py", "advanced_module_selector", {
                "model_lab": "模型实验室", "real_data": "真实数据案例",
                "automation": "自动化任务", "multi_agent": "多智能体协作",
                "evaluation": "助手评测", "flagship": "旗舰演示",
            }),
        }
        page, state_key, module_map = routes[parsed.path]
        if state_key and module in module_map:
            st.session_state[state_key] = module_map[module]
        st.switch_page(page)

    columns = st.columns(len(actions))
    for index, (column, action) in enumerate(zip(columns, actions, strict=True)):
        label = str(action["label"])
        url = action.get("url")
        if url and str(url).startswith("/") and urlsplit(str(url)).path in {
            "/", "/projects", "/intake", "/analysis", "/assistant", "/portfolio", "/advanced",
        }:
            if column.button(
                label,
                key=f"{key_prefix}_next_{index}",
                type="primary" if index == 0 else "secondary",
                width="stretch",
            ):
                activate(action)
                navigate(str(url))
            continue
        if url:
            column.link_button(label, str(url), width="stretch")
            continue
        column.button(
            label,
            key=f"{key_prefix}_next_{index}",
            type="primary" if index == 0 else "secondary",
            width="stretch",
            on_click=activate,
            args=(action,),
        )


def demo_warning(st, rows: list[dict]) -> None:
    if any(str(row.get("is_demo", "")).lower() == "true" for row in rows):
        st.markdown('<div class="demo-banner">当前包含 DEMO 数据，仅用于验证应用流程，不得作为科研结论。</div>', unsafe_allow_html=True)
