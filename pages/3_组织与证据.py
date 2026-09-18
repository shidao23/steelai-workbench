from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 分析与报告", "📊", show_title=False)
workspace_header(
    st,
    kicker="ANALYSIS & REPORTS",
    title="分析与报告",
    description="对已确认的数据执行确定性计算与统计，组织实验和模型证据，再形成带边界的报告。",
    workflow=("选择对象", "确定性分析", "人工复核", "形成报告"),
)
modules = {
    "物理计算": ("经验公式计算", "使用登记过版本和适用范围的公式；计算值不是实验真值。"),
    "可追溯统计": ("独立试样统计", "从已核验的逐试样记录生成可复核、可重放的描述统计。"),
    "组织分析": ("显微与衍射结果", "查看已有 EBSD/SEM 结果、尺度配对和 B/R 描述性比较。"),
    "研究报告": ("端到端研究任务", "把数据检查、物理计算、组织分析与报告串成一次可复现运行。"),
    "证据验证": ("结论边界检查", "核对证据等级、冲突、限制与可说或不可说的结论。"),
    "运行与成果": ("任务和审核中心", "集中查看待确认、阻断、失效、已完成和已验收结果。"),
}
requested_section = {
    "physics": "物理计算",
    "statistics": "可追溯统计",
    "ebsd": "组织分析",
    "research": "研究报告",
    "validation": "证据验证",
    "runs": "运行与成果",
}.get(st.query_params.get("module"))
if requested_section:
    st.session_state["analysis_module_selector"] = requested_section
    st.query_params.clear()
section = module_selector(st, modules, key="analysis_module_selector")
render_view({
    "物理计算": "physics_view.py",
    "可追溯统计": "steelstats_view.py",
    "组织分析": "ebsd_view.py",
    "研究报告": "research_case_view.py",
    "证据验证": "validation_view.py",
    "运行与成果": "run_center_view.py",
}[section])
