from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from steelai.automation import (
    AUTODIMPLE_BATCH_MANIFEST,
    AUTODIMPLE_RESULT_ROOT,
    launch_autodimple_batch,
    read_job_status,
    read_log_tail,
)
from steelai.ui import setup_page


setup_page(st, "任务与结果", "⚙️")
st.caption("统一启动模型任务、查看运行状态、读取结构化结果；原始实验文件保持只读。")

st.subheader("系统运行链")
st.code(
    "原始数据路径 → 后台模型环境 → 自动质量规则 → 结构化结果 → 科研报告 → 项目日志 → Career Portfolio",
    language=None,
)

status = read_job_status()
status_name = str(status.get("status", "idle"))
a, b, c, d = st.columns(4)
a.metric("任务", "B/R AutoDimple")
b.metric("状态", status_name)
c.metric("运行方式", "后台 / GPU")
d.metric("逐对象人工校核", "关闭")

left, right = st.columns([1, 1])
with left:
    start_disabled = status_name == "running"
    if st.button("启动 B/R 十图自动分析", type="primary", disabled=start_disabled, use_container_width=True):
        try:
            launch_autodimple_batch()
        except (FileNotFoundError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success("任务已在后台启动。可以继续浏览其他页面。")
            st.rerun()
with right:
    if st.button("刷新任务状态", use_container_width=True):
        st.rerun()

st.info(str(status.get("message", "")))
if status.get("started_at"):
    st.caption(f"开始：{status['started_at']}")
if status.get("finished_at"):
    st.caption(f"完成：{status['finished_at']}")

if AUTODIMPLE_BATCH_MANIFEST.exists():
    manifest = json.loads(AUTODIMPLE_BATCH_MANIFEST.read_text(encoding="utf-8"))
    st.subheader("最新结果")
    x, y, z = st.columns(3)
    x.metric("图像数量", manifest.get("image_count", 0))
    y.metric("标准", manifest.get("standard_id", ""))
    z.metric("批处理状态", manifest.get("status", ""))

    summary_path = AUTODIMPLE_RESULT_ROOT / "br_image_summary_v0.1.csv"
    comparison_path = AUTODIMPLE_RESULT_ROOT / "br_comparison_v0.1.json"
    plot_path = AUTODIMPLE_RESULT_ROOT / "br_metric_boxplots_v0.1.png"
    report_path = AUTODIMPLE_RESULT_ROOT / "B_vs_R_AutoDimple_preliminary_report_v0.1.md"
    if comparison_path.exists():
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        metrics = comparison["metrics"]
        p, q, r = st.columns(3)
        p.metric("R候选数相对B", f"{metrics['estimated_true_candidates']['R_vs_B_percent']:.1f}%")
        q.metric("R中位直径相对B", f"+{metrics['median_equivalent_diameter_um']['R_vs_B_percent']:.1f}%")
        r.metric("R覆盖率相对B", f"+{metrics['candidate_coverage_percent']['R_vs_B_percent']:.1f}%")
    if plot_path.exists():
        st.image(str(plot_path), caption="B/R图像级探索性比较")
    if summary_path.exists():
        st.dataframe(pd.read_csv(summary_path), width="stretch", hide_index=True)
    if report_path.exists():
        with st.expander("查看自动科研报告"):
            st.markdown(report_path.read_text(encoding="utf-8"))

with st.expander("运行日志"):
    log_text = read_log_tail()
    st.code(log_text or "尚无日志。", language=None)

st.subheader("一体化演进路线")
st.markdown(
    """
    1. **数据中心**：样品、成分、工艺、组织、性能和证据路径统一编号。
    2. **计算中心**：Physics Engine、AutoDimple、EBSD、XRD和热力学模型作为独立后台任务。
    3. **分析中心**：以试样为统计单位，连接断口、组织和力学性能。
    4. **科研助手**：GPT只读取结构化结果，生成假设、证据边界和实验建议。
    5. **成果中心**：自动沉淀论文图表、项目日志、STAR素材和脱敏GitHub作品。
    """
)
st.warning("生活管理继续保留在Notion，不接入SteelAI科研数据权限域。")
