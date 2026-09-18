from __future__ import annotations

import streamlit as st

from steelai.ui import setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 数据处理", "📥", show_title=False)
workspace_header(
    st,
    kicker="DATA INTAKE",
    title="数据处理",
    description="把外部实验文件转换为统一字段和单位；系统先预览和检查，只有人工确认后才追加到标准数据层。",
    workflow=("选择文件", "识别与映射", "质量检查", "人工确认", "正式写入"),
)
render_view("data_quality_panel.py")
