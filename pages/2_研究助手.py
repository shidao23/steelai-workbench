from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 研究助手", "🧠", show_title=False)
workspace_header(
    st,
    kicker="RESEARCH ASSISTANT",
    title="研究助手",
    description="围绕一个科研问题组织任务、证据、人工决定和结果；智能助手只在已授权的证据边界内工作。",
)
modules = {
    "科研会话": ("日常科研主线", "保存研究问题、阶段进度、发现和下一步行动。"),
    "研究任务": ("端到端任务", "把数据检查、物理计算、组织分析与报告串成一次可复现运行。"),
    "智能助手": ("证据约束问答", "调用云端模型整理已登记证据，不允许越权修改数据或执行任务。"),
    "助手评测": ("可靠性评测", "用固定案例检查准确性、权限边界和失败处理。"),
    "旗舰演示": ("毕业作品演示", "重放已经验收的 T40 合成数据全链路。"),
    "证据验证": ("结论边界检查", "核对证据等级、冲突、限制与可说/不可说的结论。"),
}
requested = st.query_params.get("module")
if "research_module_selector" not in st.session_state:
    st.session_state["research_module_selector"] = (
        "旗舰演示" if requested == "flagship" else "科研会话"
    )
elif requested == "flagship":
    st.session_state["research_module_selector"] = "旗舰演示"
section = module_selector(st, modules, key="research_module_selector")
view = {
    "科研会话": "research_session_view.py",
    "研究任务": "research_case_view.py",
    "智能助手": "research_agent_view.py",
    "助手评测": "agent_evaluation_view.py",
    "旗舰演示": "flagship_demo_view.py",
    "证据验证": "validation_view.py",
}[section]
render_view(view)
