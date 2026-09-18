from __future__ import annotations

import streamlit as st

from steelai.ui import module_selector, setup_page, workspace_header
from steelai.view_loader import render_view


setup_page(st, "SteelAI Workbench · 实验室与高级功能", "⚙️", show_title=False)
workspace_header(
    st,
    kicker="LAB & ADVANCED",
    title="实验室与高级功能",
    description="这里放置不属于日常数据整理的模型试验、自动化、智能体评测和演示工具；候选结果不会自动进入正式科研数据。",
    workflow=("隔离试验", "检查结果", "人工复核", "决定是否接纳"),
)
modules = {
    "模型实验室": ("模型与人工复核", "管理图像模型和 GPU 试验候选，保留参数、版本和人工复核。"),
    "真实数据案例": ("公开工业数据实验", "重放 UCI 钢板缺陷分类基线、改进模型和错误分析。"),
    "自动化任务": ("任务状态与输出", "查看既有自动化任务和失败信息，不直接改写科研主数据。"),
    "多智能体协作": ("受控科研编排", "五类职责按固定契约交接，保留人工关口和失败关闭。"),
    "助手评测": ("可靠性与权限评测", "用固定案例检查答案、工具选择、权限边界和失败处理。"),
    "旗舰演示": ("毕业作品演示", "重放已经验收的 T40 合成数据成功链路和失败门禁。"),
}
requested_section = {
    "model_lab": "模型实验室",
    "real_data": "真实数据案例",
    "automation": "自动化任务",
    "multi_agent": "多智能体协作",
    "evaluation": "助手评测",
    "flagship": "旗舰演示",
}.get(st.query_params.get("module"))
if requested_section:
    st.session_state["advanced_module_selector"] = requested_section
    st.query_params.clear()
section = module_selector(st, modules, key="advanced_module_selector", compact=True)
render_view({
    "模型实验室": "model_lab_view.py",
    "真实数据案例": "real_data_case_view.py",
    "自动化任务": "automation_view.py",
    "多智能体协作": "multi_agent_view.py",
    "助手评测": "agent_evaluation_view.py",
    "旗舰演示": "flagship_demo_view.py",
}[section])
