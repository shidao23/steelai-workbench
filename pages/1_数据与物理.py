from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 数据与物理", "📊", show_title=False)
workspace_header(
    st,
    kicker="DATA & PHYSICS",
    title="数据与物理",
    description="从样品对比进入确定性计算、数据质控与可追溯统计；所有结果都保留来源和适用边界。",
    workflow=("样品比较", "物理计算", "数据质控", "统计报告"),
)
modules = {
    "样品比较": ("比较 B/R 样品", "先看两个样品的关键性能，再按成分、工艺、组织和性能查看明细。"),
    "物理计算": ("经验公式计算", "使用登记过版本和适用范围的公式；计算值不是实验真值。"),
    "数据接入与质控": ("数据门禁", "检查字段、单位和来源，只有人工批准后才允许进入标准化数据。"),
    "可追溯统计": ("组级统计报告", "从已核验的逐试样记录生成可复核、可重放的描述统计。"),
}
requested_section = {
    "samples": "样品比较",
    "physics": "物理计算",
    "quality": "数据接入与质控",
    "statistics": "可追溯统计",
}.get(st.query_params.get("module"))
if requested_section:
    st.session_state["data_module_selector"] = requested_section
    st.query_params.clear()
section = module_selector(st, modules, key="data_module_selector")
render_view({
    "样品比较": "sample_data_view.py",
    "物理计算": "physics_view.py",
    "数据接入与质控": "data_quality_panel.py",
    "可追溯统计": "steelstats_view.py",
}[section])
