from __future__ import annotations

import pandas as pd
import streamlit as st

from steelai.ebsd import (
    B_MATCHED_CTF,
    BR_B_OUTPUT,
    BR_COMPARISON_TABLE,
    BR_R_OUTPUT,
    EBSD_GRAINS,
    EBSD_OUTPUT_ROOT,
    PILOT_CTF,
    R_MATCHED_CTF,
    R_HIGHRES_CTF,
    HIGHRES_B_OUTPUT,
    HIGHRES_COMPARISON_TABLE,
    HIGHRES_R_OUTPUT,
    build_pilot_config,
    environment_status,
    launch_ebsd_pilot,
    launch_matched_pair,
    launch_highres_pair,
    read_ctf_header,
    read_ebsd_log,
    read_ebsd_status,
    read_ebsd_summary,
    read_matched_comparison,
    read_matched_pair_log,
    read_matched_pair_status,
    read_highres_comparison,
    read_highres_pair_log,
    read_highres_pair_status,
)
from steelai.ebsd_comparison import compare_ctf_headers
from steelai.ui import next_step_buttons, setup_page
from steelai.views.image_model_governance_panel import render_image_model_governance_panel


setup_page(st, "SteelAI Workbench · EBSD分析", "🧭")
st.caption("Python负责样品、任务和报告；MATLAB/MTEX负责晶体学计算。原始EBSD文件保持只读。")
render_image_model_governance_panel(st, "EBSD", key_prefix="ebsd_governance")

header = read_ctf_header()
runtime = environment_status()
status = read_ebsd_status()
config = build_pilot_config()

st.subheader("试点样品")
a, b, c, d = st.columns(4)
a.metric("样品", "B-DQ")
b.metric("扫描点", f"{header.get('x_cells', 0)} × {header.get('y_cells', 0)}")
c.metric("步长", f"{header.get('x_step_um', 0):.2f} μm")
d.metric("原始覆盖率", f"{header.get('coverage_percent', 0):.2f}%")
st.code(str(PILOT_CTF), language=None)

phase_text = "、".join(header.get("phases", [])) or "未读取"
st.info(f"检测到相：{phase_text}；文件大小：{header.get('file_size_mb', 0):.2f} MB。")

st.subheader("运行环境")
runtime_rows = [{"component": name, "available": available} for name, available in runtime.items()]
st.dataframe(pd.DataFrame(runtime_rows), hide_index=True, width="stretch")

st.subheader("基础分析参数 v0.1")
parameter_rows = [
    {"parameter": "目标相", "value": config["target_phase"], "meaning": "BCC取向数据"},
    {"parameter": "晶粒重构角", "value": f"{config['grain_angle_deg']}°", "meaning": "试点参数，不等同于PAG边界"},
    {"parameter": "最小晶粒", "value": f"{config['min_grain_pixels']} pixels", "meaning": "过滤极小对象"},
    {"parameter": "KAM", "value": f"order {config['kam_order']}, threshold {config['kam_threshold_deg']}°", "meaning": "局部取向差"},
    {"parameter": "LAGB/HAGB", "value": f"{config['lagb_min_deg']}–{config['hagb_min_deg']}° / ≥{config['hagb_min_deg']}°", "meaning": "按晶界长度统计"},
    {"parameter": "原奥氏体重构", "value": "关闭", "meaning": "待基础结果验收后启用"},
]
st.dataframe(pd.DataFrame(parameter_rows), hide_index=True, width="stretch")

status_name = str(status.get("status", "idle"))
left, right = st.columns(2)
with left:
    if st.button(
        "启动 B-DQ EBSD试点分析",
        type="primary",
        disabled=status_name == "running" or not all(runtime.values()),
        use_container_width=True,
    ):
        try:
            launch_ebsd_pilot()
        except (FileNotFoundError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success("MATLAB/MTEX任务已在后台启动，可以继续浏览其他页面。")
            st.rerun()
with right:
    if st.button("刷新EBSD状态", use_container_width=True):
        st.rerun()

st.metric("任务状态", status_name)
st.info(str(status.get("message", "")))
if status.get("started_at"):
    st.caption(f"开始：{status['started_at']}")
if status.get("finished_at"):
    st.caption(f"完成：{status['finished_at']}")

summary = read_ebsd_summary()
if summary:
    st.subheader("试点结果")
    p, q, r, s = st.columns(4)
    p.metric("MTEX索引率", f"{summary.get('indexed_fraction_percent', 0):.2f}%")
    q.metric("BCC占已索引点", f"{summary.get('target_phase_fraction_of_indexed_percent', 0):.2f}%")
    r.metric("FCC占已索引点", f"{summary.get('retained_phase_fraction_of_indexed_percent', 0):.2f}%")
    s.metric("BCC取向晶粒", int(summary.get("grain_count", 0)))

    x, y, z = st.columns(3)
    x.metric("内部晶粒中位直径", f"{summary.get('median_equivalent_diameter_um_interior', 0):.3f} μm")
    y.metric("KAM中位数", f"{summary.get('median_kam_deg', 0):.3f}°")
    z.metric("HAGB长度占比", f"{summary.get('hagb_length_fraction_percent', 0):.2f}%")

    figures = [
        ("ipf_map.png", "BCC IPF图"),
        ("grain_map.png", "BCC取向晶粒图"),
        ("kam_map.png", "KAM图"),
        ("grain_size_distribution.png", "晶粒等效直径分布"),
    ]
    for first, second in zip(figures[::2], figures[1::2]):
        col1, col2 = st.columns(2)
        for column, item in ((col1, first), (col2, second)):
            path = EBSD_OUTPUT_ROOT / item[0]
            if path.exists():
                column.image(str(path), caption=item[1])

    if EBSD_GRAINS.exists():
        with st.expander("查看晶粒明细表"):
            st.dataframe(pd.read_csv(EBSD_GRAINS), hide_index=True, width="stretch")

    for warning in summary.get("warnings", []):
        st.warning(warning)

st.divider()
st.subheader("B/R匹配EBSD对比")
st.caption("本组使用相同的1000×、0.5 μm步长、601×360点、20 kV和70°倾角；此前0.15 μm步长的B-DQ高分辨率试点不混入比较。")

pair_b_header = read_ctf_header(B_MATCHED_CTF)
pair_r_header = read_ctf_header(R_MATCHED_CTF)
pair_rows = [
    {
        "sample": "B-DQ",
        "region": "区3",
        "grid": f"{pair_b_header.get('x_cells', 0)} × {pair_b_header.get('y_cells', 0)}",
        "step_um": pair_b_header.get("x_step_um"),
        "magnification": pair_b_header.get("magnification"),
        "coverage_percent": pair_b_header.get("coverage_percent"),
        "path": str(B_MATCHED_CTF),
    },
    {
        "sample": "R-DQ",
        "region": "区1",
        "grid": f"{pair_r_header.get('x_cells', 0)} × {pair_r_header.get('y_cells', 0)}",
        "step_um": pair_r_header.get("x_step_um"),
        "magnification": pair_r_header.get("magnification"),
        "coverage_percent": pair_r_header.get("coverage_percent"),
        "path": str(R_MATCHED_CTF),
    },
]
st.dataframe(pd.DataFrame(pair_rows), hide_index=True, width="stretch")

pair_is_matched = compare_ctf_headers(pair_b_header, pair_r_header)["compatible"]
if pair_is_matched:
    st.success("采集参数匹配，可以进行同参数的探索性B/R场级对比。")
else:
    st.error("采集参数不匹配，系统将禁止生成直接B/R对比结论。")

pair_status = read_matched_pair_status()
pair_status_name = str(pair_status.get("status", "idle"))
pair_left, pair_right = st.columns(2)
with pair_left:
    if st.button(
        "启动匹配B/R EBSD分析",
        type="primary",
        disabled=pair_status_name == "running" or not pair_is_matched,
        use_container_width=True,
    ):
        try:
            launch_matched_pair()
        except (FileNotFoundError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success("B-DQ与R-DQ正在后台依次分析。")
            st.rerun()
with pair_right:
    if st.button("刷新B/R状态", use_container_width=True):
        st.rerun()

st.metric("B/R任务状态", pair_status_name)
st.info(str(pair_status.get("message", "")))

comparison = read_matched_comparison()
if comparison:
    st.subheader("B/R场级探索结果")
    comparison_table = pd.DataFrame(comparison.get("metrics", []))
    if not comparison_table.empty:
        display_table = comparison_table[["label", "unit", "B_DQ", "R_DQ", "R_minus_B", "R_vs_B_percent"]]
        st.dataframe(display_table, hide_index=True, width="stretch")

    b_image, r_image = st.columns(2)
    b_ipf = BR_B_OUTPUT / "ipf_map.png"
    r_ipf = BR_R_OUTPUT / "ipf_map.png"
    if b_ipf.exists():
        b_image.image(str(b_ipf), caption="B-DQ区3 · BCC IPF")
    if r_ipf.exists():
        r_image.image(str(r_ipf), caption="R-DQ区1 · BCC IPF")

    b_kam, r_kam = st.columns(2)
    b_kam_path = BR_B_OUTPUT / "kam_map.png"
    r_kam_path = BR_R_OUTPUT / "kam_map.png"
    if b_kam_path.exists():
        b_kam.image(str(b_kam_path), caption="B-DQ区3 · KAM")
    if r_kam_path.exists():
        r_kam.image(str(r_kam_path), caption="R-DQ区1 · KAM")

    if BR_COMPARISON_TABLE.exists():
        st.download_button(
            "下载B/R对比表",
            data=BR_COMPARISON_TABLE.read_bytes(),
            file_name="B_vs_R_EBSD_comparison.csv",
            mime="text/csv",
        )
    for limitation in comparison.get("limitations", []):
        st.warning(limitation)

with st.expander("B/R MATLAB/MTEX运行日志"):
    st.code(read_matched_pair_log() or "尚无B/R日志。", language=None)

st.divider()
st.subheader("B/R高分辨率EBSD对比")
st.caption("CTF记录：B-DQ区2为2005×、0.15 μm；R-DQ区3为1998×、0.150225 μm。倍率、步长和实际视场尺寸差异均小于1%。")

high_b_header = read_ctf_header(PILOT_CTF)
high_r_header = read_ctf_header(R_HIGHRES_CTF)
high_rows = [
    {
        "sample": "B-DQ",
        "region": "区2",
        "grid": f"{high_b_header.get('x_cells', 0)} × {high_b_header.get('y_cells', 0)}",
        "step_um": high_b_header.get("x_step_um"),
        "magnification": high_b_header.get("magnification"),
        "coverage_percent": high_b_header.get("coverage_percent"),
        "path": str(PILOT_CTF),
    },
    {
        "sample": "R-DQ",
        "region": "区3",
        "grid": f"{high_r_header.get('x_cells', 0)} × {high_r_header.get('y_cells', 0)}",
        "step_um": high_r_header.get("x_step_um"),
        "magnification": high_r_header.get("magnification"),
        "coverage_percent": high_r_header.get("coverage_percent"),
        "path": str(R_HIGHRES_CTF),
    },
]
st.dataframe(pd.DataFrame(high_rows), hide_index=True, width="stretch")
high_compatibility = compare_ctf_headers(high_b_header, high_r_header)
if high_compatibility["compatible"]:
    st.success("高分辨率采集参数和实际视场在1%容差内匹配，可以进行同尺度探索性对比。")
else:
    st.error("高分辨率采集条件不匹配，系统将禁止直接比较。")

high_status = read_highres_pair_status()
high_status_name = str(high_status.get("status", "idle"))
high_left, high_right = st.columns(2)
with high_left:
    if st.button(
        "启动高分辨率B/R EBSD分析",
        type="primary",
        disabled=high_status_name == "running" or not high_compatibility["compatible"],
        use_container_width=True,
    ):
        try:
            launch_highres_pair()
        except (FileNotFoundError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success("高分辨率B-DQ与R-DQ正在后台依次分析。")
            st.rerun()
with high_right:
    if st.button("刷新高分辨率状态", use_container_width=True):
        st.rerun()

st.metric("高分辨率任务状态", high_status_name)
st.info(str(high_status.get("message", "")))

high_comparison = read_highres_comparison()
if high_comparison:
    st.subheader("高分辨率B/R场级探索结果")
    high_table = pd.DataFrame(high_comparison.get("metrics", []))
    if not high_table.empty:
        st.dataframe(
            high_table[["label", "unit", "B_DQ", "R_DQ", "R_minus_B", "R_vs_B_percent"]],
            hide_index=True,
            width="stretch",
        )
    high_b_ipf, high_r_ipf = st.columns(2)
    if (HIGHRES_B_OUTPUT / "ipf_map.png").exists():
        high_b_ipf.image(str(HIGHRES_B_OUTPUT / "ipf_map.png"), caption="B-DQ区2 · 高分辨率BCC IPF")
    if (HIGHRES_R_OUTPUT / "ipf_map.png").exists():
        high_r_ipf.image(str(HIGHRES_R_OUTPUT / "ipf_map.png"), caption="R-DQ区3 · 高分辨率BCC IPF")
    if HIGHRES_COMPARISON_TABLE.exists():
        st.download_button(
            "下载高分辨率B/R对比表",
            data=HIGHRES_COMPARISON_TABLE.read_bytes(),
            file_name="B_vs_R_high_resolution_EBSD_comparison.csv",
            mime="text/csv",
        )
    for limitation in high_comparison.get("limitations", []):
        st.warning(limitation)

with st.expander("高分辨率B/R MATLAB/MTEX运行日志"):
    st.code(read_highres_pair_log() or "尚无高分辨率B/R日志。", language=None)

with st.expander("MATLAB/MTEX运行日志"):
    st.code(read_ebsd_log() or "尚无日志。", language=None)

st.warning(
    "当前统计对象是按3°阈值重构的BCC取向晶粒，不应直接称为马氏体block、packet或原奥氏体晶粒。"
)

next_step_buttons(
    st,
    [
        {
            "label": "进入证据验证",
            "url": "/analysis?module=validation",
        },
        {"label": "返回证据索引", "url": "/projects?module=evidence"},
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
    ],
    key_prefix="ebsd",
    note="组织分析结果需要与证据等级和取样限制一起进入结论验证。",
)
