from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 模型与自动化", "⚙️", show_title=False)
workspace_header(
    st,
    kicker="MODELS & AUTOMATION",
    title="模型与自动化",
    description="把模型试验与正式科研数据隔离：先看状态、再人工复核、最后决定是否接纳结果。",
    workflow=("隔离试验", "人工复核", "接纳或拒绝", "记录结果"),
)
modules = {
    "模型实验室": ("模型与人工复核", "管理 GPU 试验、SEM 分割候选和人工复核证据。"),
    "任务与结果": ("自动化任务中心", "查看任务状态、输出和失败信息，不直接改写科研主数据。"),
}
section = module_selector(st, modules, key="model_module_selector")
render_view("model_lab_view.py" if section == "模型实验室" else "automation_view.py")
