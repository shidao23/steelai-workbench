from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.event_log import record_event, safe_output_filename, write_text_artifact
from steelai.paths import REPORTS
from steelai.research_agent import (
    AGENT_NAME,
    TOOL_DEFINITIONS,
    agent_status,
    run_research_agent,
)
from steelai.ui import setup_page


setup_page(st, "证据约束智能助手", "🤖")
st.caption("单Agent科研协调层：只读取结构化证据，调用现有确定性模块，并留下可审计工具轨迹。")

status = agent_status()
status_labels = {
    "online_ready": "在线可用",
    "offline_missing_key": "离线：未配置密钥",
    "offline_missing_package": "离线：缺少程序包",
    "disabled": "已关闭",
}

a, b, c, d = st.columns(4)
a.metric("Agent状态", status_labels.get(status.state, status.state))
b.metric("供应商", status.provider.capitalize())
c.metric("只读工具", len(TOOL_DEFINITIONS))
d.metric("模型", status.model)

if status.ready:
    st.success(status.message)
else:
    st.warning(status.message)
    if status.state == "offline_missing_key":
        st.info(
            f"系统主体仍可离线使用。要启用Agent，请在启动SteelAI前，把{status.api_key_env}配置为本机环境变量；"
            "不要把密钥写进项目文件、截图或聊天。"
        )

with st.expander("查看Agent权限边界与工具白名单"):
    st.markdown(
        "- 允许：读取processed样品数据、生成Physics Card、读取既有EBSD与AutoDimple结果。\n"
        "- 禁止：修改原始文件、启动MATLAB/GPU任务、运行任意代码、访问未登记路径。\n"
        "- 数据边界：不向模型发送原始图片和原始文件路径；低/高分辨率EBSD不混合。\n"
        "- 框架：当前使用供应商兼容接口和严格工具调用，暂不引入LangChain。"
    )
    tool_rows = [
        {"tool": item["name"], "description": item["description"]}
        for item in TOOL_DEFINITIONS
    ]
    st.dataframe(pd.DataFrame(tool_rows), hide_index=True, width="stretch")

st.subheader("向Research Agent提问")
examples = [
    "比较B-DQ与R-DQ的已确认性能差异，并严格区分判断和待验证假设。",
    "分别读取低分辨率和高分辨率EBSD结果，说明一致、不一致和不能合并之处。",
    "计算B-DQ和R-DQ的Physics Card，并指出公式警告和证据缺口。",
    "结合AutoDimple与性能数据，说明目前能得出什么、不能得出什么。",
]
selected = st.selectbox("示例问题", examples)
question = st.text_area(
    "研究问题",
    value=selected,
    height=110,
    help="Agent只回答当前项目中已有证据能够支持的问题。",
)

if st.button("运行只读分析", type="primary", disabled=not status.ready, use_container_width=True):
    with st.spinner("正在读取结构化证据并组织分析……"):
        result = run_research_agent(question, status=status)
    st.session_state["research_agent_last_result"] = result.to_dict()
    st.session_state["research_agent_last_question"] = question

saved_result = st.session_state.get("research_agent_last_result")
if saved_result:
    if saved_result.get("status") == "completed":
        st.subheader("分析结果")
        st.markdown(saved_result.get("answer", ""))

        trace = saved_result.get("tool_trace", [])
        usage = saved_result.get("usage", {})
        if usage:
            st.caption(
                f"Token记录：输入 {usage.get('input_tokens', 0)} · "
                f"输出 {usage.get('output_tokens', 0)} · 总计 {usage.get('total_tokens', 0)}"
            )
        with st.expander(f"查看工具调用轨迹（{len(trace)}次）"):
            if trace:
                st.dataframe(pd.DataFrame(trace), hide_index=True, width="stretch")
            else:
                st.caption("本次回答未调用工具。")

        if st.button("将本次分析保存为项目证据", use_container_width=True):
            saved_question = st.session_state.get("research_agent_last_question", "")
            trace_summary = json.dumps(trace, ensure_ascii=False, indent=2)
            content = (
                f"# {AGENT_NAME} 分析记录\n\n"
                f"## 研究问题\n\n{saved_question}\n\n"
                f"## Agent回答\n\n{saved_result.get('answer', '')}\n\n"
                f"## 工具调用轨迹\n\n```json\n{trace_summary}\n```\n"
            )
            artifact = write_text_artifact(
                REPORTS,
                safe_output_filename("research_agent_analysis"),
                content,
            )
            record_event(
                "agent_analysis",
                "Research Agent完成一次证据约束分析",
                saved_question,
                evidence={
                    "artifact": str(artifact.relative_to(artifact.parents[2])),
                    "model": saved_result.get("model", ""),
                    "tools": [item.get("tool", "") for item in trace],
                    "response_id": saved_result.get("response_id", ""),
                },
                tags=["research-agent", "auditable", "career-evidence"],
            )
            st.success(f"已保存：{artifact.name}")
    else:
        st.error(saved_result.get("error") or "Agent未完成本次分析。")

st.divider()
st.subheader("当前科学边界")
st.markdown(
    "- Agent负责证据编排，不替代Python确定性计算、MTEX晶体学分析或实验复核。\n"
    "- 一张EBSD视场不能当作独立试样重复；AutoDimple对象也不能当作独立试样重复。\n"
    "- 经验公式结果必须标记为模型估算，相关性不能写成因果。\n"
    "- 当前不开放自动改数据、自动跑模型和自动写入结论的权限。"
    "\n- 含本地路径或原始CTF/TIF文件名的问题会在API调用前被阻断。"
)
