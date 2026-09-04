from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 组织与证据", "🔬")
section = st.radio(
    "功能模块",
    ["证据索引", "EBSD / MTEX"],
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()
render_view("evidence_index_view.py" if section == "证据索引" else "ebsd_view.py")
