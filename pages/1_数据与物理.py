from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 项目与样品", "🧬", show_title=False)
workspace_header(
    st,
    kicker="PROJECT & SAMPLES",
    title="项目与样品",
    description="围绕当前课题和样品查看数据、科研会话与原始证据位置；先明确研究对象，再进入处理和分析。",
    workflow=("选择样品", "查看数据", "关联证据", "继续研究"),
)
modules = {
    "样品总览": ("样品数据与差异", "查看当前样品的成分、工艺、组织和性能，并与另一研究样品做描述性比较。"),
    "科研会话": ("研究问题与进度", "保存研究问题、阶段发现、待办和运行引用，让工作可以从上次位置继续。"),
    "证据索引": ("实验文件与样品关系", "登记 OM、SEM、EBSD、XRD 等原始证据的位置和样品身份，不复制原始文件。"),
}
requested_section = {
    "samples": "样品总览",
    "session": "科研会话",
    "evidence": "证据索引",
}.get(st.query_params.get("module"))
if requested_section:
    st.session_state["project_module_selector"] = requested_section
    st.query_params.clear()
section = module_selector(st, modules, key="project_module_selector")
render_view({
    "样品总览": "sample_data_view.py",
    "科研会话": "research_session_view.py",
    "证据索引": "evidence_index_view.py",
}[section])
