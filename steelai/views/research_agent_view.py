from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.agent_evidence_gateway import (
    ALLOWED_AGENT_TOOLS,
    AgentGatewayError,
    preview_agent_send_summary,
)
from steelai.event_log import record_event, safe_output_filename, write_text_artifact
from steelai.paths import REPORTS
from steelai.research_agent import (
    AGENT_NAME,
    TOOL_DEFINITIONS,
    agent_status,
    run_research_agent,
)
from steelai.ui import next_step_buttons, setup_page


setup_page(st, "证据约束问答", "🤖")
st.caption("围绕当前样品整理已核验的结构化证据。助手只读，回答需要人工复核。")

status = agent_status()
status_labels = {
    "online_ready": "在线可用",
    "offline_missing_key": "离线：未配置密钥",
    "offline_missing_package": "离线：缺少程序包",
    "offline_missing_proxy_dependency": "离线：代理依赖缺失",
    "disabled": "已关闭",
}

a, b, c = st.columns(3)
a.metric("AI 连接", status_labels.get(status.state, status.state))
b.metric("当前样品", st.session_state.get("active_sample_id", "未选择"))
c.metric("操作权限", "只读")

if status.ready:
    st.success(status.message)
else:
    st.warning(status.message)
    if status.state == "offline_missing_key":
        st.info(
            f"系统主体仍可离线使用。要启用Agent，请在启动SteelAI前，把{status.api_key_env}配置为本机环境变量；"
            "不要把密钥写进项目文件、截图或聊天。"
        )

with st.expander("连接与权限详情", expanded=False):
    x, y, z = st.columns(3)
    x.metric("供应商", status.provider.capitalize())
    y.metric("模型", status.model)
    z.metric("可用只读工具", len(TOOL_DEFINITIONS))
    st.markdown(
        "- 允许：读取通过共享治理内核核验的数据、Physics Card及已完成人工复核的图像模型结果。\n"
        "- 禁止：修改原始文件、启动MATLAB/GPU任务、运行任意代码、访问未登记路径。\n"
        "- 数据边界：不向模型发送问题原文的审计副本、原始图片、原始文件名或本地绝对路径。\n"
        "- 结论边界：回答固定分为事实、判断、假设、局限和下一步；始终需要人工复核。\n"
        "- 框架：当前使用供应商兼容接口和严格工具调用，暂不引入LangChain。"
    )
    tool_rows = [
        {"tool": item["name"], "description": item["description"]}
        for item in TOOL_DEFINITIONS
    ]
    st.dataframe(pd.DataFrame(tool_rows), hide_index=True, width="stretch")

st.subheader("提出研究问题")
examples = [
    "比较B-DQ与R-DQ的已确认性能差异，并严格区分判断和待验证假设。",
    "分别读取低分辨率和高分辨率EBSD结果，说明一致、不一致和不能合并之处。",
    "计算B-DQ和R-DQ的Physics Card，并指出公式警告和证据缺口。",
    "结合AutoDimple与性能数据，说明目前能得出什么、不能得出什么。",
]
selected = st.selectbox("快速开始", examples)
question = st.text_area(
    "研究问题",
    value=selected,
    height=110,
    help="Agent只回答当前项目中已有证据能够支持的问题。",
)

preview_error = ""
try:
    send_preview = preview_agent_send_summary(
        question,
        provider=status.provider,
        model=status.model,
        allowed_tools=tuple(sorted(ALLOWED_AGENT_TOOLS)),
    )
except AgentGatewayError:
    send_preview = {}
    preview_error = "问题含本地路径、受保护文件名、疑似密钥或其他越界内容，网关不会发送。"

with st.expander("发送前检查 · 技术详情", expanded=False):
    if preview_error:
        st.error(preview_error)
    else:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("供应商", send_preview.get("provider", ""))
        p2.metric("模型", send_preview.get("model", ""))
        p3.metric("问题字符", send_preview.get("question_character_count", 0))
        p4.metric("只读工具", len(send_preview.get("allowed_tools", [])))
        st.caption(f"问题摘要指纹：{send_preview.get('question_sha256', '')[:16]}…")
        st.info("原文、工具参数和证据载荷不写入审计；本地路径、受保护文件名及疑似密钥在发送前阻断。")

if st.button(
    "开始证据约束分析",
    type="primary",
    disabled=not status.ready or bool(preview_error),
    use_container_width=True,
):
    with st.spinner("正在读取结构化证据并组织分析……"):
        result = run_research_agent(question, status=status)
    st.session_state["research_agent_last_result"] = result.to_dict()

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
        if saved_result.get("gateway_id"):
            st.success(
                f"证据网关审计已完成：{saved_result.get('gateway_id')}。"
                "该记录只含摘要、哈希、证据身份和权限边界。"
            )
        structured = saved_result.get("structured_output", {})
        with st.expander("查看受限解释结构"):
            if structured:
                st.json(structured)
            else:
                st.caption("本次没有可用的结构化解释。")
        with st.expander(f"查看工具调用轨迹（{len(trace)}次）"):
            if trace:
                st.dataframe(pd.DataFrame(trace), hide_index=True, width="stretch")
            else:
                st.caption("本次回答未调用工具。")

        if st.button("保存为待人工复核的 Agent 草稿", use_container_width=True):
            trace_summary = json.dumps(trace, ensure_ascii=False, indent=2)
            structured_summary = json.dumps(structured, ensure_ascii=False, indent=2)
            content = (
                f"# {AGENT_NAME} 待人工复核草稿\n\n"
                f"> 网关：{saved_result.get('gateway_id', '')}\n\n"
                "> 此文件不是审批记录、正式数据或科研结论，必须经过人工复核。\n\n"
                f"## 受限解释结构\n\n```json\n{structured_summary}\n```\n\n"
                f"## 工具调用轨迹\n\n```json\n{trace_summary}\n```\n"
            )
            artifact = write_text_artifact(
                REPORTS,
                safe_output_filename("research_agent_review_draft"),
                content,
            )
            record_event(
                "agent_draft_saved",
                "Research Agent草稿已保存并等待人工复核",
                "仅保存受限解释结构和脱敏工具轨迹，不构成正式科研结论。",
                evidence={
                    "artifact": str(artifact.relative_to(artifact.parents[2])),
                    "gateway_id": saved_result.get("gateway_id", ""),
                    "model": saved_result.get("model", ""),
                    "tools": [item.get("tool", "") for item in trace],
                    "manifest_sha256": saved_result.get("manifest_sha256", ""),
                    "human_review_required": True,
                },
                tags=["research-agent", "review-draft", "t55-gateway"],
            )
            st.success(f"待复核草稿已保存：{artifact.name}")
    else:
        st.error(saved_result.get("error") or "Agent未完成本次分析。")

with st.expander("科学边界与禁止事项", expanded=False):
    st.markdown(
        "- 助手负责证据编排，不替代 Python 确定性计算、MTEX 晶体学分析或实验复核。\n"
        "- 一张 EBSD 视场不能当作独立试样重复；AutoDimple 对象也不能当作独立试样重复。\n"
        "- 经验公式结果必须标记为模型估算，相关性不能写成因果。\n"
        "- 当前不开放自动改数据、自动跑模型和自动写入结论的权限。\n"
        "- 含本地路径、受保护原始文件名或疑似密钥的问题会在调用前被阻断。"
    )

next_step_buttons(
    st,
    [
        {"label": "进入证据验证", "url": "/analysis?module=validation"},
        {"label": "检查助手评测", "url": "/advanced?module=evaluation"},
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
    ],
    key_prefix="research_agent",
    note="助手回答不能直接成为结论；先验证证据，再检查固定评测中的权限与失败模式。",
)
