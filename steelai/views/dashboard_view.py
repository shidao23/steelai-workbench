from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from steelai.data import read_rows
from steelai.event_log import read_events, record_event
from steelai.paths import ensure_runtime_dirs
from steelai.research_session import research_session_dashboard
from steelai.settings import source_statuses
from steelai.ui import demo_warning, setup_page


ensure_runtime_dirs()
setup_page(st, "SteelAI Workbench · 科研总览", "🧭", show_title=False)

samples = read_rows("samples")
evidence = read_rows("evidence")
events = read_events()
session_dashboard = research_session_dashboard()
demo_warning(st, samples)

st.markdown(
    """
    <section class="steel-hero">
      <div class="steel-eyebrow">STEELAI RESEARCH WORKBENCH · GRADUATION MVP</div>
      <h1>让每一条材料数据，都能解释它从哪里来</h1>
      <p>面向耐磨钢课题的个人科研工作台：把实验文件、人工审核、质量控制、组级统计与科研解释组织成一条可复核的证据链。</p>
      <span class="steel-chip">T40 旗舰演示已验收</span>
      <span class="steel-chip">公开合成演示</span>
      <span class="steel-chip">本地确定性处理</span>
    </section>
    """,
    unsafe_allow_html=True,
)

action_left, action_mid, action_right = st.columns([1.15, 1, 1])
with action_left:
    if st.button("▶ 查看端到端旗舰演示", type="primary", width="stretch"):
        st.session_state["research_module_selector"] = "旗舰演示"
        st.switch_page("pages/2_研究助手.py")
with action_mid:
    if st.button("开始一次科研会话", width="stretch"):
        st.session_state["research_module_selector"] = "科研会话"
        st.switch_page("pages/2_研究助手.py")
with action_right:
    if st.button("查看数据与统计", width="stretch"):
        st.switch_page("pages/1_数据与物理.py")

st.markdown(
    '<div class="section-kicker">SYSTEM SNAPSHOT</div>'
    '<div class="section-title">今天需要知道的四件事</div>',
    unsafe_allow_html=True,
)
m1, m2, m3, m4 = st.columns(4)
m1.metric("核心研究样品", len(samples), help="当前毕业主线中登记的研究样品")
m2.metric("可追溯事件", len(events), help="已进入项目日志的运行、决定与里程碑")
m3.metric("科研会话", session_dashboard["session_count"], help="可继续的结构化研究会话")
m4.metric("开放行动", session_dashboard["open_action_count"], help="尚待处理的人工行动")

st.markdown(
    '<div class="section-kicker">RESEARCH PIPELINE</div>'
    '<div class="section-title">已经走通的科研闭环</div>',
    unsafe_allow_html=True,
)
flow = (
    ("01 · INGEST", "实验数据入口", "识别陌生表格的字段、单位与来源摘要；不修改原始文件。"),
    ("02 · REVIEW", "人工审核门禁", "Agent 只给建议；字段、单位和物理试样身份由人确认。"),
    ("03 · QUALITY", "标准化与统计", "SteelData 执行 QC，SteelStats 按独立试样计算组级统计。"),
    ("04 · EXPLAIN", "可追溯解释", "SteelAI 组织描述性结论，同时保留证据、限制与失败案例。"),
)
columns = st.columns(4)
for column, (step, title, copy) in zip(columns, flow, strict=True):
    column.markdown(
        f'<div class="flow-card"><div class="flow-step">{step}</div>'
        f'<div class="flow-title">{title}</div><div class="flow-copy">{copy}</div>'
        '<span class="flow-ok">✓ 已接通</span></div>',
        unsafe_allow_html=True,
    )

st.markdown(
    '<div class="section-kicker">RESEARCH OBJECTS</div>'
    '<div class="section-title">当前毕业主线研究对象</div>',
    unsafe_allow_html=True,
)
sample_columns = st.columns(max(1, min(2, len(samples))))
if samples:
    for index, row in enumerate(samples[:2]):
        sample_id = escape(str(row.get("sample_id", "未编号")))
        steel = escape(str(row.get("steel", "—")))
        condition = escape(str(row.get("condition", "—")))
        batch = escape(str(row.get("batch", "—")))
        raw_status = str(row.get("data_status", ""))
        status = escape({
            "verified_from_source_note": "来源已核验（研究笔记）",
            "verified_from_source": "来源已核验",
            "manual_extraction_verified": "人工提取已核验",
        }.get(raw_status, raw_status or "待核验"))
        sample_columns[index % len(sample_columns)].markdown(
            f'<div class="sample-card"><div class="sample-id">{sample_id}</div>'
            f'<div class="sample-meta">钢种 {steel} · 状态 {condition}<br>研究批次 {batch}</div>'
            f'<span class="status-pill">{status}</span></div>',
            unsafe_allow_html=True,
        )
else:
    st.info("尚未登记研究样品。请从“数据与物理”进入数据质量页面。")

st.markdown(
    '<div class="section-kicker">DAILY WORK</div>'
    '<div class="section-title">科研进度与下一步</div>',
    unsafe_allow_html=True,
)
left, right = st.columns([1.35, 1])
with left:
    if session_dashboard["sessions"]:
        session_rows = pd.DataFrame(session_dashboard["sessions"][:5])
        st.dataframe(
            session_rows[["title", "status", "progress", "current_stage", "open_actions"]],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("还没有科研会话。建议从“研究助手 → 科研会话”用固定模板创建第一条研究主线。")
with right:
    if session_dashboard["open_actions"]:
        for item in session_dashboard["open_actions"][:4]:
            priority = escape(str(item.get("priority", "P2")))
            text = escape(str(item.get("text", "")))
            st.markdown(f"- **{priority}** · {text}")
    else:
        st.markdown(
            """
            **推荐下一步**

            1. 创建第一条 B/R 科研会话
            2. 把一次真实研究问题与证据关联
            3. 用旗舰演示准备答辩讲解
            """
        )

with st.expander("查看最近项目事件"):
    if events:
        event_rows = pd.DataFrame(events[-8:][::-1])
        st.dataframe(
            event_rows[["created_at", "event_type", "title", "summary"]],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("尚无运行事件。")

with st.expander("技术详情：数据表、完整度与本机路径"):
    st.caption("这些信息用于维护和排错，默认收起；本机绝对路径不会作为公开项目内容上传。")
    st.markdown("**当前样品原始表**")
    if samples:
        st.dataframe(pd.DataFrame(samples), width="stretch", hide_index=True)
    names = ["composition", "process", "microstructure", "properties"]
    completeness = []
    for name in names:
        table = read_rows(name)
        for sample in samples:
            sid = sample["sample_id"]
            row = next((item for item in table if item.get("sample_id") == sid), {})
            values = [value for key, value in row.items() if key != "sample_id"]
            completeness.append({
                "sample_id": sid,
                "table": name,
                "filled_fields": sum(value not in ("", None) for value in values),
                "total_fields": len(values),
            })
    st.markdown("**数据完整度明细**")
    st.dataframe(pd.DataFrame(completeness), width="stretch", hide_index=True)
    st.markdown("**本机来源路径状态**")
    st.dataframe(pd.DataFrame(source_statuses()), width="stretch", hide_index=True)

with st.expander("快速记录一次数据、决定或里程碑"):
    with st.form("quick_log", clear_on_submit=True):
        event_type = st.selectbox(
            "类型", ["data_update", "formula_update", "decision", "milestone", "analysis_note"]
        )
        event_title = st.text_input("标题")
        event_summary = st.text_area("摘要 / 理由 / 下一步")
        tag_text = st.text_input("标签（逗号分隔）")
        save_event = st.form_submit_button("写入项目日志")
    if save_event:
        if not event_title or not event_summary:
            st.error("标题和摘要不能为空。")
        else:
            record_event(
                event_type,
                event_title,
                event_summary,
                tags=[tag.strip() for tag in tag_text.split(",") if tag.strip()],
            )
            st.success("已写入项目日志，可在 Career Portfolio 中继续沉淀。")
            st.rerun()
