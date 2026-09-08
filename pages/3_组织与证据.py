from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 组织与证据", "🔬", show_title=False)
workspace_header(
    st,
    kicker="MICROSTRUCTURE & EVIDENCE",
    title="组织与证据",
    description="登记显微与衍射证据的位置、样品身份、分析方法和人工复核状态，不复制或修改原始文件。",
    workflow=("登记来源", "组织分析", "人工复核", "进入结论"),
)
modules = {
    "证据索引": ("原始证据登记", "把 OM、SEM、EBSD、XRD 文件与样品、描述和人工参数关联。"),
    "EBSD 分析": ("双尺度组织分析", "查看已有 MTEX 结果、尺度配对与 B/R 描述性比较。"),
}
section = module_selector(st, modules, key="evidence_module_selector")
render_view("evidence_index_view.py" if section == "证据索引" else "ebsd_view.py")
