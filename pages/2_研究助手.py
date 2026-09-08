from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 研究助手", "🧠")
options = ["科研会话", "端到端研究任务", "Research Agent", "Agent评测", "旗舰演示", "证据验证"]
requested = st.query_params.get("module")
if "research_module_selector" not in st.session_state:
    st.session_state["research_module_selector"] = (
        "旗舰演示" if requested == "flagship" else "科研会话"
    )
elif requested == "flagship":
    st.session_state["research_module_selector"] = "旗舰演示"
section = st.radio(
    "功能模块",
    options,
    key="research_module_selector",
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()
view = {
    "科研会话": "research_session_view.py",
    "端到端研究任务": "research_case_view.py",
    "Research Agent": "research_agent_view.py",
    "Agent评测": "agent_evaluation_view.py",
    "旗舰演示": "flagship_demo_view.py",
    "证据验证": "validation_view.py",
}[section]
render_view(view)
