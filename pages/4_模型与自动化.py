from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 模型与自动化", "⚙️")
section = st.radio(
    "功能模块",
    ["Open Model Lab", "任务与结果"],
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()
render_view("model_lab_view.py" if section == "Open Model Lab" else "automation_view.py")
