import pandas as pd
import streamlit as st

from steelai.data import read_rows
from steelai.event_log import read_events, record_event
from steelai.paths import ensure_runtime_dirs
from steelai.research_session import research_session_dashboard
from steelai.settings import source_statuses
from steelai.ui import demo_warning, setup_page

ensure_runtime_dirs()
setup_page(st, "SteelAI Workbench · 科研总览", "🧭")

samples = read_rows("samples")
evidence = read_rows("evidence")
events = read_events()
session_dashboard = research_session_dashboard()
demo_warning(st, samples)

st.caption("耐磨钢科研闭环：数据与证据 → 物理计算 → 结构化分析 → 项目日志 → 求职作品集")

c1, c2, c3, c4 = st.columns(4)
c1.metric("样品", len(samples))
c2.metric("证据索引", len(evidence))
c3.metric("已沉淀事件", len(events))
indexed = sum(1 for row in evidence if row.get("file_path"))
c4.metric("真实路径已登记", f"{indexed}/{len(evidence)}" if evidence else "0/0")

st.subheader("日常科研会话")
s1, s2, s3, s4 = st.columns(4)
s1.metric("会话总数", session_dashboard["session_count"])
s2.metric("进行中", session_dashboard["active_count"])
s3.metric("被阻塞", session_dashboard["blocked_count"])
s4.metric("开放行动", session_dashboard["open_action_count"])
if session_dashboard["sessions"]:
    st.dataframe(
        pd.DataFrame(session_dashboard["sessions"][:8])[
            ["session_id", "title", "status", "progress", "current_stage", "open_actions", "updated_at"]
        ],
        width="stretch",
        hide_index=True,
    )
    if session_dashboard["open_actions"]:
        with st.expander("查看待处理科研行动"):
            st.dataframe(
                pd.DataFrame(session_dashboard["open_actions"])[
                    ["session_id", "session_title", "priority", "status", "text"]
                ],
                width="stretch",
                hide_index=True,
            )
else:
    st.info("尚无科研会话。可在“研究助手 → 科研会话”中从固定模板开始。")

st.subheader("当前状态")
left, right = st.columns([1.2, 1])
with left:
    if samples:
        st.dataframe(pd.DataFrame(samples), width="stretch", hide_index=True)
    else:
        st.info("尚无样品。请在 data/processed/samples.csv 中添加记录。")
with right:
    st.markdown("""
    **MVP 边界**

    - 原始实验文件不复制、不改动
    - 公式输出是经验估算，不是实验真值
    - GPT 只能重组当前选中的结构化证据
    - OM/SEM/EBSD/XRD 暂做索引与人工参数登记
    - 不包含生活管理，不训练 XGBoost/DeepXDE
    """)

st.subheader("原始资料路径映射")
st.dataframe(pd.DataFrame(source_statuses()), width="stretch", hide_index=True)
st.caption("在 config/settings.toml 中填写真实绝对路径。应用只检查并登记路径，不复制原始资料。")

st.subheader("数据完整度")
names = ["composition", "process", "microstructure", "properties"]
rows = []
for name in names:
    table = read_rows(name)
    for sample in samples:
        sid = sample["sample_id"]
        row = next((r for r in table if r.get("sample_id") == sid), {})
        values = [v for k, v in row.items() if k != "sample_id"]
        completed = sum(v not in ("", None) for v in values)
        rows.append({"sample_id": sid, "table": name, "filled_fields": completed, "total_fields": len(values)})
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

st.subheader("最近项目事件")
if events:
    st.dataframe(pd.DataFrame(events[-10:][::-1])[["created_at", "event_type", "title", "summary"]], width="stretch", hide_index=True)
else:
    st.info("尚无运行事件。生成一次研究报告或作品集后，这里会自动出现记录。")

with st.expander("快速记录一次数据、公式、决定或里程碑"):
    with st.form("quick_log", clear_on_submit=True):
        event_type = st.selectbox("类型", ["data_update", "formula_update", "decision", "milestone", "analysis_note"])
        event_title = st.text_input("标题")
        event_summary = st.text_area("摘要/理由/下一步")
        tag_text = st.text_input("标签（逗号分隔）")
        save_event = st.form_submit_button("写入 project log")
    if save_event:
        if not event_title or not event_summary:
            st.error("标题和摘要不能为空。")
        else:
            tags = [tag.strip() for tag in tag_text.split(",") if tag.strip()]
            record_event(event_type, event_title, event_summary, tags=tags)
            st.success("已写入 project_log/events.jsonl，可在 Career Portfolio 中继续沉淀。")
            st.rerun()
