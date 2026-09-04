from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 研究助手", "🧠")
section = st.radio(
    "功能模块",
    ["科研会话", "端到端研究任务", "Research Agent", "Agent评测", "证据验证"],
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()
view = {
    "科研会话": "research_session_view.py",
    "端到端研究任务": "research_case_view.py",
    "Research Agent": "research_agent_view.py",
    "Agent评测": "agent_evaluation_view.py",
    "证据验证": "validation_view.py",
}[section]
render_view(view)
