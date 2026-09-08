from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from steelai.data import read_rows, sample_bundle
from steelai.ui import demo_warning, next_step_buttons, setup_page


FIELD_LABELS = {
    "steel": "钢种", "condition": "状态", "batch": "研究批次", "data_status": "数据状态",
    "is_demo": "演示数据", "notes": "备注", "C": "C / 碳（质量分数）", "Mn": "Mn / 锰（质量分数）",
    "Si": "Si / 硅（质量分数）", "Cr": "Cr / 铬（质量分数）", "Ni": "Ni / 镍（质量分数）",
    "Mo": "Mo / 钼（质量分数）", "Nb": "Nb / 铌（质量分数）", "V": "V / 钒（质量分数）",
    "Ti": "Ti / 钛（质量分数）", "Al": "Al / 铝（质量分数）", "Cu": "Cu / 铜（质量分数）",
    "P": "P / 磷（质量分数）", "S": "S / 硫（质量分数）", "N": "N / 氮（质量分数）",
    "B": "B / 硼（质量分数）", "As": "As / 砷（质量分数）", "Sn": "Sn / 锡（质量分数）",
    "Sb": "Sb / 锑（质量分数）", "O": "O / 氧（质量分数）", "W": "W / 钨（质量分数）",
    "reheat_temp_c": "加热温度（℃）", "roughing_temp_c": "粗轧温度（℃）",
    "rolling_passes": "轧制道次", "finish_temp_c": "终轧温度（℃）",
    "total_reduction_pct": "总压下率（%）", "cooling_route": "冷却路径", "quench_medium": "淬火介质",
    "tempering_temp_c": "回火温度（℃）", "tempering_time_min": "回火时间（min）",
    "pag_size_um": "原奥氏体晶粒尺寸（μm）", "packet_size_um": "板条束尺寸（μm）",
    "block_size_um": "块尺寸（μm）", "hagb_pct": "大角度晶界比例（%）",
    "kam_mean_deg": "KAM 均值（°）", "gnd_m2": "GND 密度（m⁻²）", "manual_notes": "人工组织记录",
    "ys_mpa": "屈服强度（MPa）", "ys_std_mpa": "屈服强度标准差（MPa）",
    "uts_mpa": "抗拉强度（MPa）", "uts_std_mpa": "抗拉强度标准差（MPa）",
    "elongation_pct": "伸长率（%）", "elongation_std_pct": "伸长率标准差（%）",
    "reduction_area_pct": "断面收缩率（%）", "reduction_area_std_pct": "断面收缩率标准差（%）",
    "impact_minus40_j": "−40℃ 冲击功（J）", "impact_std_j": "冲击功标准差（J）",
    "impact_toughness_j_cm2": "冲击韧性（J/cm²）", "hv": "维氏硬度（HV）",
    "replicates": "独立试样数", "source_status": "来源状态",
}

STATUS_LABELS = {
    "verified_from_source_note": "来源已核验（研究笔记）",
    "verified_partial_from_source_note": "部分来源已核验",
    "manual_extraction_verified": "人工提取已核验",
    "true": "是", "false": "否",
}


def _display(value: object) -> str:
    if value is None or str(value).strip() == "":
        return "未录入"
    raw = str(value)
    return STATUS_LABELS.get(raw, raw)


def _comparison_frame(a: dict, b: dict, a_id: str, b_id: str, *, differences_only: bool = False) -> pd.DataFrame:
    order = {name: index for index, name in enumerate(FIELD_LABELS)}
    rows = []
    for key in sorted(set(a) | set(b), key=lambda item: order.get(item, 999)):
        if key == "sample_id":
            continue
        av, bv = _display(a.get(key)), _display(b.get(key))
        if differences_only and av == bv:
            continue
        rows.append({"指标": FIELD_LABELS.get(key, key), a_id: av, b_id: bv})
    return pd.DataFrame(rows)


def _number(row: dict, key: str) -> float | None:
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return None


setup_page(st, "样品比较", "🔬")
samples = read_rows("samples")
demo_warning(st, samples)
ids = [row["sample_id"] for row in samples]

if not ids:
    st.warning("还没有可比较的样品。请先完成数据接入与人工审核。")
    st.stop()

st.caption("选择两个样品，先看关键性能差值，再按数据分区查看来源字段。差值只做描述，不代表优劣或因果。")
selector_left, selector_right = st.columns(2)
a_id = selector_left.selectbox("基准样品", ids, index=0)
b_id = selector_right.selectbox("比较样品", ids, index=min(1, len(ids) - 1))
a, b = sample_bundle(a_id), sample_bundle(b_id)

st.markdown(
    f'<div class="comparison-note">当前所有差值均按 <strong>{escape(b_id)} − {escape(a_id)}</strong> 计算；'
    '空白字段统一显示为“未录入”，不会当作 0。</div>',
    unsafe_allow_html=True,
)

properties_a, properties_b = a["properties"], b["properties"]
summary_metrics = (
    ("屈服强度差值（MPa）", "ys_mpa"), ("抗拉强度差值（MPa）", "uts_mpa"),
    ("伸长率差值（%）", "elongation_pct"), ("−40℃ 冲击功差值（J）", "impact_minus40_j"),
)
metric_columns = st.columns(4)
for column, (label, key) in zip(metric_columns, summary_metrics, strict=True):
    av, bv = _number(properties_a, key), _number(properties_b, key)
    if av is None or bv is None:
        column.metric(label, "数据不足")
    else:
        column.metric(label, f"{bv - av:+.2f}")
        column.caption(f"{a_id} {av:g} ｜ {b_id} {bv:g}")

tabs = st.tabs(["样品概况", "化学成分", "工艺", "微观组织", "力学性能", "仅看差异"])
with tabs[0]:
    cards = st.columns(2)
    for column, sample_id, row in zip(cards, (a_id, b_id), (a["samples"], b["samples"]), strict=True):
        column.markdown(
            '<div class="sample-card">'
            f'<div class="sample-id">{escape(sample_id)}</div>'
            f'<div class="sample-meta">钢种 {escape(_display(row.get("steel")))} · 状态 {escape(_display(row.get("condition")))}<br>'
            f'研究批次 {escape(_display(row.get("batch")))}<br>{escape(_display(row.get("notes")))}</div>'
            f'<span class="status-pill">{escape(_display(row.get("data_status")))}</span>'
            '</div>',
            unsafe_allow_html=True,
        )

for tab, key in zip(tabs[1:5], ("composition", "process", "microstructure", "properties"), strict=True):
    with tab:
        st.dataframe(_comparison_frame(a[key], b[key], a_id, b_id), width="stretch", hide_index=True)

with tabs[5]:
    changed = []
    section_labels = {"composition": "化学成分", "process": "工艺", "microstructure": "微观组织", "properties": "力学性能"}
    for key, label in section_labels.items():
        frame = _comparison_frame(a[key], b[key], a_id, b_id, differences_only=True)
        if not frame.empty:
            frame.insert(0, "数据分区", label)
            changed.append(frame)
    st.dataframe(pd.concat(changed, ignore_index=True) if changed else pd.DataFrame(), width="stretch", hide_index=True)

st.caption("数据状态说明：来源核验表示字段可追溯到当前研究记录，不等于完成实验方法学复核。")

next_step_buttons(
    st,
    [
        {"label": "进入物理计算", "state": {"data_module_selector": "物理计算"}},
        {"label": "检查数据质量", "state": {"data_module_selector": "数据接入与质控"}},
    ],
    key_prefix="sample_compare",
    note="确认样品差异后，可以继续做经验公式计算，或先检查字段、单位与来源。",
)
