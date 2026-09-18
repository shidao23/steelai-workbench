from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from steelai.data import read_rows
from steelai.event_log import read_events, record_event
from steelai.paths import PROCESSED, ensure_runtime_dirs
from steelai.research_session import research_session_dashboard
from steelai.run_center import collect_run_records
from steelai.settings import source_statuses
from steelai.ui import demo_warning, setup_page


ensure_runtime_dirs()
setup_page(st, "SteelAI Workbench · 首页", "🏠", show_title=False)

samples = read_rows("samples")
thermal_runs_path = PROCESSED / "thermal_simulation_runs.csv"
thermal_run_count = len(pd.read_csv(thermal_runs_path)) if thermal_runs_path.exists() else 0
events = read_events()
session_dashboard = research_session_dashboard()
run_records = collect_run_records()
run_counts = {
    state: sum(record.state_group == state for record in run_records)
    for state in ("needs_human", "blocked", "invalidated", "completed")
}
pending_total = run_counts["needs_human"] + run_counts["blocked"] + run_counts["invalidated"]
demo_warning(st, samples)

st.markdown(
    f"""
    <section class="steel-hero">
      <div class="steel-eyebrow">STEELAI · B/R 耐磨钢研究</div>
      <h1>继续处理当前实验，而不是先寻找功能</h1>
      <p>从样品出发完成文件导入、人工确认、确定性分析和结果复核。系统保留来源与边界，但把技术细节留在需要时查看。</p>
      <span class="steel-chip">{len(samples)} 个核心样品</span>
      <span class="steel-chip">{thermal_run_count} 条热模拟运行</span>
      <span class="steel-chip">当前仅支持方向性证据</span>
    </section>
    """,
    unsafe_allow_html=True,
)

action_left, action_data, action_analysis, action_right = st.columns([1.15, 1, 1, 1])
with action_left:
    if st.button("继续查看当前样品", type="primary", width="stretch"):
        st.session_state["project_module_selector"] = "样品总览"
        st.switch_page("pages/1_数据与物理.py")
with action_data:
    if st.button("导入实验文件", width="stretch"):
        st.switch_page("pages/2_研究助手.py")
with action_analysis:
    action_label = f"处理 {pending_total} 项待办" if pending_total else "查看运行与成果"
    if st.button(action_label, width="stretch"):
        st.session_state["analysis_module_selector"] = "运行与成果"
        st.switch_page("pages/3_组织与证据.py")
with action_right:
    if st.button("询问 AI 助手", width="stretch"):
        st.switch_page("pages/4_模型与自动化.py")

st.markdown(
    '<div class="section-kicker">SYSTEM SNAPSHOT</div>'
    '<div class="section-title">当前任务状态</div>',
    unsafe_allow_html=True,
)
m1, m2, m3, m4 = st.columns(4)
m1.metric("核心样品", len(samples), help="当前课题中登记的研究样品")
m2.metric("待人工确认", run_counts["needs_human"], help="需要你明确接纳或拒绝的候选结果")
m3.metric("阻断或失效", run_counts["blocked"] + run_counts["invalidated"], help="未满足前置条件或完整性检查失败的运行")
m4.metric("已完成运行", run_counts["completed"], help="已完成但仍应结合证据边界使用的运行")

if pending_total:
    st.warning(
        f"当前有 {pending_total} 项结果需要处理：先查看待确认、阻断或失效原因，再决定是否进入报告。",
        icon="⚠️",
    )
else:
    st.success("当前没有待处理的运行异常。", icon="✅")

st.markdown(
    '<div class="section-kicker">RESEARCH OBJECTS</div>'
    '<div class="section-title">当前研究对象</div>',
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
    st.info("尚未登记研究样品。请先进入“数据处理”导入并确认样品数据。")

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
        st.info("还没有科研会话。可在“项目与样品 → 科研会话”创建第一条研究主线。")
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

            1. 在“项目与样品”选择本次研究对象
            2. 导入一组逐试样实验数据并完成人工确认
            3. 在“分析与报告”检查结果和证据边界
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
            st.success("已写入项目日志，可在“作品集与发布”中继续整理。")
            st.rerun()
