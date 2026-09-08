from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 数据与物理", "📊")
section = st.radio(
    "功能模块",
    ["样品与B/R对比", "Physics Engine", "数据质量与扩展准备", "可追溯统计"],
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()
view_map = {
    "样品与B/R对比": "sample_data_view.py",
    "Physics Engine": "physics_view.py",
    "数据质量与扩展准备": "data_quality_panel.py",
    "可追溯统计": "steelstats_view.py",
}
render_view(view_map[section])
