from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.event_log import record_event
from steelai.research_data_contract import validate_research_data_contract
from steelai.research_session import (
    ACTION_STATUSES,
    FINDING_CATEGORIES,
    SESSION_STATUSES,
    STAGE_STATUSES,
    add_finding,
    add_next_action,
    continue_session,
    create_session,
    list_sessions,
    research_session_dashboard,
    session_summary,
    template_by_id,
    update_action_status,
    update_session_status,
    update_stage,
    validate_session_contract,
    workflow_templates,
)
from steelai.ui import setup_page


setup_page(st, "科研会话与日常工作流", "🗂️")
st.caption("把一次科研问题保存为可继续的本地会话：模板 → 阶段 → 发现 → 下一步行动 → 运行引用。")

contract = validate_session_contract()
dashboard = research_session_dashboard()
data_report = validate_research_data_contract()

if contract["status"] != "passed":
    st.error("科研会话契约未通过：" + "；".join(contract["problems"]))
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("科研会话", dashboard["session_count"])
m2.metric("进行中", dashboard["active_count"])
m3.metric("被阻塞", dashboard["blocked_count"])
m4.metric("待办行动", dashboard["open_action_count"])

templates = workflow_templates()
template_labels = {item["template_id"]: item["label"] for item in templates}

with st.expander("新建科研会话", expanded=not bool(dashboard["session_count"])):
    selected_template_id = st.selectbox(
        "工作流模板",
        [item["template_id"] for item in templates],
        format_func=lambda template_id: template_labels[template_id],
        key="new_session_template",
    )
    selected_template = template_by_id(selected_template_id)
    st.caption(selected_template["description"])
    with st.form("create_research_session", clear_on_submit=False):
        title = st.text_input(
            "会话标题",
            value=selected_template["label"],
            key=f"new_session_title_{selected_template_id}",
        )
        question = st.text_area(
            "研究问题",
            value=selected_template["default_question"],
            height=90,
            key=f"new_session_question_{selected_template_id}",
        )
        sample_ids = st.multiselect("研究样品", ["B-DQ", "R-DQ"], default=["B-DQ", "R-DQ"])
        create_clicked = st.form_submit_button("创建并设为当前会话", type="primary")
    if create_clicked:
        try:
            created = create_session(title, question, selected_template_id, sample_ids)
            st.session_state["active_research_session_id"] = created["session_id"]
            st.success(f"已创建科研会话：{created['session_id']}")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

sessions = list_sessions()
if not sessions:
    st.info("尚无科研会话。创建后即可保存进度、研究发现和下一步行动。")
    st.stop()

session_map = {item["session_id"]: item for item in sessions}
default_id = st.session_state.get("active_research_session_id")
if default_id not in session_map:
    default_id = sessions[0]["session_id"]
selected_id = st.selectbox(
    "当前科研会话",
    list(session_map),
    index=list(session_map).index(default_id),
    format_func=lambda session_id: f"{session_map[session_id]['title']} · {session_map[session_id]['status']} · {session_id}",
    key="research_session_selector",
)
st.session_state["active_research_session_id"] = selected_id
session = session_map[selected_id]
summary = session_summary(session)

s1, s2, s3, s4 = st.columns(4)
s1.metric("状态", summary["status"])
s2.metric("阶段进度", summary["progress"])
s3.metric("关联运行", summary["run_count"])
s4.metric("开放行动", summary["open_actions"])
st.info(f"下一阶段：{summary['current_stage']}")

continue_col, complete_col, archive_col = st.columns(3)
if continue_col.button("开始 / 继续会话", use_container_width=True):
    continue_session(selected_id)
    st.rerun()
if complete_col.button("标记会话完成", use_container_width=True, disabled=session["status"] == "completed"):
    completed = update_session_status(selected_id, "completed")
    record_event(
        "research_session_completed",
        completed["title"],
        completed["research_question"],
        evidence={
            "session_id": completed["session_id"],
            "template_id": completed["workflow_template_id"],
            "run_count": len(completed["run_references"]),
            "finding_count": len(completed["findings"]),
        },
        tags=["daily-research", "reproducibility", "career-evidence"],
    )
    st.rerun()
if archive_col.button("归档会话", use_container_width=True, disabled=session["status"] == "archived"):
    update_session_status(selected_id, "archived")
    st.rerun()

progress_tab, findings_tab, actions_tab, context_tab = st.tabs(["阶段进度", "科研发现", "下一步行动", "会话上下文"])

with progress_tab:
    stage_rows = [{
        "阶段": item["label"],
        "状态": item["status"],
        "必要": item["required"],
        "备注": item.get("notes", ""),
    } for item in session["stages"]]
    st.dataframe(pd.DataFrame(stage_rows), hide_index=True, width="stretch")
    with st.form("update_research_stage"):
        stage_id = st.selectbox(
            "更新阶段",
            [item["stage_id"] for item in session["stages"]],
            format_func=lambda value: next(item["label"] for item in session["stages"] if item["stage_id"] == value),
        )
        stage_status = st.selectbox("阶段状态", STAGE_STATUSES)
        stage_notes = st.text_area("阶段备注（使用运行编号或证据编号，不粘贴本地路径）")
        stage_clicked = st.form_submit_button("保存阶段进度")
    if stage_clicked:
        try:
            update_stage(selected_id, stage_id, stage_status, stage_notes)
            st.success("阶段进度已保存。")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with findings_tab:
    if session["findings"]:
        st.dataframe(pd.DataFrame(session["findings"]), hide_index=True, width="stretch")
    else:
        st.info("尚未记录科研发现。事实、判断和假设应分开保存。")
    with st.form("add_research_finding", clear_on_submit=True):
        finding_category = st.selectbox("发现类别", FINDING_CATEGORIES)
        finding_text = st.text_area("内容")
        evidence_text = st.text_input("证据引用（逗号分隔，例如 run_id、observation_id）")
        finding_clicked = st.form_submit_button("添加科研发现")
    if finding_clicked:
        try:
            references = [item.strip() for item in evidence_text.split(",") if item.strip()]
            add_finding(selected_id, finding_category, finding_text, references)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with actions_tab:
    if session["next_actions"]:
        st.dataframe(pd.DataFrame(session["next_actions"]), hide_index=True, width="stretch")
        with st.form("update_research_action"):
            action_id = st.selectbox(
                "选择行动",
                [item["action_id"] for item in session["next_actions"]],
                format_func=lambda value: next(item["text"] for item in session["next_actions"] if item["action_id"] == value),
            )
            action_status = st.selectbox("行动状态", ACTION_STATUSES)
            action_update_clicked = st.form_submit_button("更新行动状态")
        if action_update_clicked:
            update_action_status(selected_id, action_id, action_status)
            st.rerun()
    else:
        st.info("尚无下一步行动。")
    with st.form("add_research_action", clear_on_submit=True):
        action_text = st.text_area("新增行动")
        action_priority = st.selectbox("优先级", ["high", "medium", "low"], index=1)
        action_clicked = st.form_submit_button("添加下一步行动")
    if action_clicked:
        try:
            add_next_action(selected_id, action_text, action_priority)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with context_tab:
    st.write("**研究问题**")
    st.write(session["research_question"])
    st.write("**研究范围**", "、".join(session["sample_ids"]))
    st.write("**工作流模板**", template_labels.get(session["workflow_template_id"], session["workflow_template_id"]))
    if session["run_references"]:
        st.write("**关联运行**")
        st.dataframe(pd.DataFrame(session["run_references"]), hide_index=True, width="stretch")
    with st.expander("当前数据契约建议补齐项"):
        for index, action in enumerate(data_report["next_actions"], start=1):
            st.write(f"{index}. {action}")
    st.download_button(
        "下载会话JSON",
        json.dumps(session, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{selected_id}_research_session.json",
        mime="application/json",
    )
    st.caption("会话只保存结构化科研记录和相对运行引用；原始文件继续由外部只读目录与证据索引管理。")
