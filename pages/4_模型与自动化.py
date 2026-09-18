from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · AI 助手", "✨", show_title=False)
workspace_header(
    st,
    kicker="AI ASSISTANT",
    title="AI 助手",
    description="围绕当前课题和样品整理已核验的证据；助手只读，不修改数据、不替代计算或人工判断。",
    workflow=("提出问题", "读取证据", "调用工具", "人工复核"),
)
render_view("research_agent_view.py")
