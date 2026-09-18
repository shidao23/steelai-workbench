from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from steelai.event_log import record_event
from steelai.governance import GovernanceError
from steelai.intake_request import (
    folder_reference_selection,
    register_intake_request,
    uploaded_file_selection,
)
from steelai.paths import OUTPUTS
from steelai.thermal_simulation_analysis import (
    derive_compression_curve,
    load_standardized_thermal_data,
    paired_runs,
    process_double_hit_curve,
)
from steelai.thermal_simulation_intake import (
    build_thermal_standardization_preview,
    commit_thermal_preview_governed,
    inspect_thermal_simulation_batch,
    read_plan_csv,
    read_thermal_simulation_folder,
    save_thermal_preview_package,
)
from steelai.thermal_simulation_features import (
    approve_and_commit_thermal_features,
    build_thermal_feature_preview,
    combine_thermal_feature_previews,
    feature_rows_csv_bytes,
)
from steelai.thermal_softening_analysis import (
    approve_and_commit_softening_results,
    assess_softening_method_readiness,
    build_softening_result_preview,
    softening_rows_csv_bytes,
)


PLAN_COLUMNS = [
    "acquisition_id", "sample_id", "specimen_id", "test_type",
    "planned_temperature_c", "planned_interpass_time_s", "strain_1", "strain_2",
    "strain_rate_s", "specimen_diameter_mm", "specimen_height_mm", "plan_source_status",
]


def _plan_template() -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerow(PLAN_COLUMNS)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    if not rows:
        return b""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _batch_from_uploads(uploads: list) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for upload in uploads:
        name = Path(str(upload.name)).name
        if name in files:
            raise ValueError(f"上传文件名重复：{name}")
        files[name] = upload.getvalue()
    return files


def _derived_csv(rows: list[dict]) -> bytes:
    return _csv_bytes(rows)


def _line_chart(
    data: pd.DataFrame,
    *,
    x: str,
    y: str,
    series: str,
    x_title: str,
    y_title: str,
) -> None:
    st.vega_lite_chart(
        data,
        {
            "mark": {"type": "line", "clip": True},
            "encoding": {
                "x": {"field": x, "type": "quantitative", "title": x_title},
                "y": {"field": y, "type": "quantitative", "title": y_title, "scale": {"zero": False}},
                "color": {"field": series, "type": "nominal", "title": "曲线"},
                "order": {"field": "sequence", "type": "quantitative"},
                "tooltip": [
                    {"field": series, "type": "nominal", "title": "曲线"},
                    {"field": x, "type": "quantitative", "title": x_title, "format": ".5f"},
                    {"field": y, "type": "quantitative", "title": y_title, "format": ".4f"},
                ],
            },
        },
        width="stretch",
    )


def _raw_frame(run_ids: set[str], points: list[dict[str, str]]) -> pd.DataFrame:
    rows = [row for row in points if row.get("experiment_run_id") in run_ids]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for column in (
        "interval_index", "point_index", "time_s", "force_value_raw",
        "stroke_value_raw", "stroke_mm", "control_temperature_c",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["sequence"] = range(len(frame))
    frame["series"] = frame["sample_id"] + " · I" + frame["interval_index"].astype("Int64").astype(str)
    return frame


def _render_curve_panels(
    frame: pd.DataFrame,
    derived: pd.DataFrame | None,
    effective: pd.DataFrame | None,
) -> None:
    stress_tab, temperature_tab, raw_tab = st.tabs(["应力—应变", "温度—时间", "原始力与位移"])
    with stress_tab:
        if derived is None or derived.empty:
            st.info("当前选择不适用 Φ10×15 mm DH 压缩公式，只显示原始曲线。")
        else:
            curve_mode = st.radio(
                "曲线口径",
                ["文献分析视图（自动建议）", "公式全路径（原始保留）"],
                horizontal=True,
                key="thermal_curve_basis",
            )
            if curve_mode.startswith("文献") and effective is not None and not effective.empty:
                _line_chart(
                    effective,
                    x="true_strain_local",
                    y="stress_mpa_baseline_corrected",
                    series="series",
                    x_title="本道次局部真应变",
                    y_title="基线修正应力 (MPa)",
                )
                st.caption(
                    "每个 hit 从自动识别的接触点重新置零；仅显示接触至最大 Stroke 的加载段。"
                    "这是待人工复核的分段建议，不是已批准软化率。"
                )
            else:
                _line_chart(
                    derived, x="true_strain", y="stress_mpa", series="series",
                    x_title="累计真应变", y_title="公式应力 (MPa)",
                )
                st.caption("曲线按仪器采集顺序连接；负力值和卸载段不被自动删除或平滑。")
    with temperature_tab:
        _line_chart(
            frame, x="time_s", y="control_temperature_c", series="series",
            x_title="时间 (s)", y_title="控制温度 (°C)",
        )
    with raw_tab:
        force_col, stroke_col = st.columns(2)
        with force_col:
            _line_chart(
                frame, x="time_s", y="force_value_raw", series="series",
                x_title="时间 (s)", y_title="仪器 Force (Kg 原值)",
            )
        with stroke_col:
            _line_chart(
                frame, x="time_s", y="stroke_value_raw", series="series",
                x_title="时间 (s)", y_title="Stroke (cm 原值)",
            )


def _render_standardized_curve_visualization() -> None:
    st.markdown("#### 已入库曲线可视化")
    try:
        runs, points = load_standardized_thermal_data()
    except (OSError, ValueError) as exc:
        st.error("标准化曲线读取失败：" + str(exc))
        return
    if not runs or not points:
        st.info("标准数据层尚无热模拟曲线。先完成下面的新批次接入。")
        return

    run_by_id = {row["experiment_run_id"]: row for row in runs}
    mode = st.radio("查看方式", ["单采集", "B/R 对比"], horizontal=True, key="thermal_chart_mode")
    derived_rows: list[dict] = []
    effective_rows: list[dict] = []
    segment_summaries: list[dict] = []
    feature_previews: list[dict] = []
    selected_runs: list[dict[str, str]] = []
    if mode == "单采集":
        options = [row["experiment_run_id"] for row in runs]
        labels = {
            row["experiment_run_id"]: (
                f"A{row['acquisition_id']} · {row['sample_id']} · {row['test_type']} · {row['specimen_id']}"
            ) for row in runs
        }
        default = next((index for index, value in enumerate(options) if run_by_id[value].get("test_type") == "DH"), 0)
        selected_id = st.selectbox(
            "选择采集", options, index=default, format_func=lambda value: labels[value],
            key="thermal_chart_run",
        )
        selected_runs = [run_by_id[selected_id]]
    else:
        pairs = [item for item in paired_runs(runs) if item["key"][0].upper() == "DH"]
        if not pairs:
            st.warning("当前标准数据中没有完成身份核对的 B/R 成对 DH 采集。")
            return
        pair_index = st.selectbox(
            "选择成对条件", range(len(pairs)), format_func=lambda index: pairs[index]["label"],
            key="thermal_chart_pair",
        )
        selected_runs = [pairs[pair_index]["B-DQ"], pairs[pair_index]["R-DQ"]]

    raw = _raw_frame({row["experiment_run_id"] for row in selected_runs}, points)
    if raw.empty:
        st.warning("所选运行没有标准化曲线点。")
        return
    summaries = []
    for run in selected_runs:
        if run.get("test_type", "").upper() != "DH":
            continue
        try:
            result = derive_compression_curve(run, points)
        except ValueError as exc:
            st.warning(str(exc))
            continue
        rows = result["rows"]
        for sequence, row in enumerate(rows):
            row["sequence"] = sequence
            row["series"] = row["sample_id"] + " · I" + str(row["interval_index"])
        derived_rows.extend(rows)
        try:
            processed = process_double_hit_curve(run, points)
        except ValueError as exc:
            st.warning("有效加载段自动识别失败：" + str(exc))
        else:
            for sequence, row in enumerate(processed["effective_rows"]):
                row["sequence"] = sequence
                row["series"] = row["sample_id"] + " · I" + str(row["interval_index"])
            effective_rows.extend(processed["effective_rows"])
            segment_summaries.extend(processed["segments"])
            try:
                feature_previews.append(build_thermal_feature_preview(run, points))
            except ValueError as exc:
                st.warning("T74 特征预览生成失败：" + str(exc))
        summaries.append({
            "样品": run["sample_id"], "采集号": "A" + run["acquisition_id"],
            "试样": run["specimen_id"], "峰值应力 (MPa)": round(result["peak_stress_mpa"], 3),
            "最大真应变": round(result["max_true_strain"], 5), "数据点": result["point_count"],
        })
    derived = pd.DataFrame(derived_rows) if derived_rows else None
    effective = pd.DataFrame(effective_rows) if effective_rows else None

    if summaries:
        st.dataframe(pd.DataFrame(summaries), hide_index=True, width="stretch")
    if segment_summaries:
        with st.expander("查看两道次有效加载段建议", expanded=True):
            display_segments = [{
                "采集": "A" + str(item["acquisition_id"]),
                "样品": item["sample_id"],
                "道次": item["interval_index"],
                "接触点": item["contact_point_index"],
                "加载终点": item["end_point_index"],
                "局部最大真应变": round(item["max_local_true_strain"], 5),
                "基线力 (Kg原值)": round(item["baseline_force_raw"], 4),
                "复核状态": "待人工复核",
            } for item in segment_summaries]
            st.dataframe(pd.DataFrame(display_segments), hide_index=True, width="stretch")
            st.warning("自动识别只生成候选段；未经过曲线目视复核前，不生成正式软化率。")
    _render_curve_panels(raw, derived, effective)
    if derived_rows:
        download_left, download_right = st.columns(2)
        download_left.download_button(
            "下载公式全路径数据",
            _derived_csv(derived_rows),
            file_name="thermal_stress_strain_full_path.csv",
            mime="text/csv",
            width="stretch",
            key="thermal_download_derived",
        )
        download_right.download_button(
            "下载有效加载段建议",
            _derived_csv(effective_rows),
            file_name="thermal_double_hit_effective_segments_suggested.csv",
            mime="text/csv",
            width="stretch",
            disabled=not bool(effective_rows),
            key="thermal_download_effective",
        )
    if feature_previews:
        feature_preview = combine_thermal_feature_previews(feature_previews)
        feature_rows = feature_preview["rows"]
        st.markdown("#### T74 热模拟特征表")
        st.caption("把数千个曲线点压缩成一行一个采集；当前所选分段仍待人工复核，因此先显示候选特征。")
        feature_summary = [{
            "采集": "A" + str(row["acquisition_id"]),
            "样品": row["sample_id"],
            "实际温度 (°C)": round(float(row["effective_temperature_c"]), 3),
            "有效变形间隔 (s)": round(float(row["effective_deformation_gap_s"]), 5),
            "第一道峰值 (MPa)": round(float(row["hit1_peak_stress_mpa"]), 3),
            "第一道峰值应变": round(float(row["hit1_peak_local_true_strain"]), 5),
            "第二道峰值 (MPa)": round(float(row["hit2_peak_stress_mpa"]), 3),
            "第二道峰值应变": round(float(row["hit2_peak_local_true_strain"]), 5),
            "状态": "待人工复核",
        } for row in feature_rows]
        st.dataframe(pd.DataFrame(feature_summary), hide_index=True, width="stretch")
        with st.expander("查看完整 T74 特征与哈希", expanded=False):
            st.dataframe(pd.DataFrame(feature_rows), hide_index=True, width="stretch")
            st.caption(
                "定点流动应力默认提取局部真应变 0.05、0.10、0.15、0.20；"
                "只在有效段内线性插值，禁止外推。"
            )
        st.download_button(
            "下载候选 thermal_simulation_features.csv",
            feature_rows_csv_bytes(feature_rows),
            file_name="thermal_simulation_features_candidate.csv",
            mime="text/csv",
            width="stretch",
            key="thermal_download_features",
        )
        with st.expander("人工复核并写入正式特征表", expanded=False):
            st.warning(
                "这一步表示你已目视核对当前选择的每个采集、两道次接触点和终点。"
                "批准后将只追加写入 data/processed/thermal_simulation_features.csv。"
            )
            feature_reviewer = st.text_input(
                "分段复核人标识", placeholder="例如姓名、工号或 project_owner",
                key="thermal_feature_reviewer",
            )
            feature_rationale = st.text_area(
                "分段批准依据",
                placeholder="说明已核对加载起点、卸载前终点、曲线方向和异常点。",
                key="thermal_feature_rationale",
            )
            feature_confirmed = st.checkbox(
                "我已目视复核当前选择的全部有效加载段，并批准用于 T74 特征提取",
                key="thermal_feature_confirmed",
            )
            can_commit_features = bool(
                feature_reviewer.strip() and feature_rationale.strip() and feature_confirmed
            )
            if st.button(
                "批准分段并写入正式特征表",
                type="primary",
                disabled=not can_commit_features,
                width="stretch",
                key="thermal_commit_features",
            ):
                try:
                    feature_result = approve_and_commit_thermal_features(
                        feature_preview,
                        reviewer_id=feature_reviewer,
                        rationale=feature_rationale,
                        confirmed=True,
                    )
                    record_event(
                        "thermal_feature_extraction",
                        "T74 热模拟特征正式写入",
                        f"{len(feature_rows)} 个采集的有效加载段获批并生成特征行",
                        {
                            "feature_version": feature_preview["feature_version"],
                            "governance_intake_id": feature_result["governance_intake_id"],
                        },
                        ["thermal_simulation", "feature_table", "human_approved"],
                    )
                except (GovernanceError, OSError, ValueError) as exc:
                    st.error("T74 正式写入失败：" + str(exc))
                else:
                    st.success(
                        "T74 正式特征已追加。治理记录："
                        + feature_result["governance_intake_id"]
                    )
    st.markdown("#### T75 双道次软化分析")
    try:
        softening_readiness = assess_softening_method_readiness(runs, points)
    except ValueError as exc:
        st.warning("T75 方法检查暂不可用：" + str(exc))
    else:
        step = softening_readiness["observed_median_positive_strain_increment"]
        st.caption(
            f"本批 {softening_readiness['run_count']} 个 DH 采集、"
            f"{softening_readiness['segment_count']} 个有效段；局部真应变中位正步长为 {step:.6f}。"
        )
        method_labels = {
            "resolved": "数值上可辨",
            "under_resolved": "低于当前分辨率",
            "not_offset_based": "非偏移法",
        }
        method_table = [{
            "候选方法": item["label"],
            "偏移真应变": (
                "—" if item["offset_true_strain"] is None
                else f"{float(item['offset_true_strain']):.3f}"
            ),
            "约合中位采样步数": (
                "—" if item["median_step_coverage"] is None
                else f"{float(item['median_step_coverage']):.2f}"
            ),
            "当前数据分辨率": method_labels[item["resolution_status"]],
            "解释范围": item["interpretation"],
        } for item in softening_readiness["method_results"]]
        st.dataframe(pd.DataFrame(method_table), hide_index=True, width="stretch")
        if softening_readiness["selection_status"] != "approved":
            st.warning(
                "尚未冻结软化率方法，所以系统不会自动计算正式结果。"
                "本批建议以 2% 偏移法为主、5% 定应变法做敏感性对照；需要项目负责人明确确认。"
            )
        else:
            st.success("方法已冻结：2% 偏移法为主，5% 定真应变法为敏感性对照。")
            try:
                softening_preview = build_softening_result_preview(runs, points)
            except ValueError as exc:
                st.error("T75 软化率计算停止：" + str(exc))
            else:
                metric_a, metric_b, metric_c = st.columns(3)
                metric_a.metric("候选结果", softening_preview["row_count"])
                metric_b.metric("QC 通过", softening_preview["passed_count"])
                metric_c.metric("需要复核", softening_preview["warning_count"])
                display_rows = [{
                    "采集": "A" + str(row["acquisition_id"]),
                    "样品": row["sample_id"],
                    "实际温度 (°C)": round(float(row["effective_temperature_c"]), 2),
                    "实际间隔 (s)": round(float(row["effective_deformation_gap_s"]), 4),
                    "σm (MPa)": round(float(row["primary_sigma_m_mpa"]), 3),
                    "σ1 · 2% (MPa)": round(float(row["primary_sigma_1_mpa"]), 3),
                    "σ2 · 2% (MPa)": round(float(row["primary_sigma_2_mpa"]), 3),
                    "主软化率 (%)": round(float(row["primary_softening_percent_raw"]), 2),
                    "5% 对照 (%)": round(float(row["sensitivity_softening_percent_raw"]), 2),
                    "差值 (百分点)": round(
                        float(row["sensitivity_minus_primary_fraction"]) * 100.0, 2
                    ),
                    "QC": "通过" if row["result_qc_status"] == "passed" else "需复核",
                } for row in softening_preview["rows"]]
                st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")

                chart_rows = []
                for row in softening_preview["rows"]:
                    for method_label, value in (
                        ("2% 偏移主结果", row["primary_softening_percent_raw"]),
                        ("5% 定真应变对照", row["sensitivity_softening_percent_raw"]),
                    ):
                        chart_rows.append({
                            "采集": "A" + str(row["acquisition_id"]),
                            "样品": row["sample_id"],
                            "方法": method_label,
                            "实际温度": float(row["effective_temperature_c"]),
                            "实际间隔": float(row["effective_deformation_gap_s"]),
                            "软化率": float(value),
                        })
                st.vega_lite_chart(
                    pd.DataFrame(chart_rows),
                    {
                        "mark": {"type": "point", "filled": True, "size": 90},
                        "encoding": {
                            "x": {
                                "field": "实际间隔", "type": "quantitative",
                                "title": "实际变形间隔 (s)",
                            },
                            "y": {
                                "field": "软化率", "type": "quantitative",
                                "title": "软化率原始值 (%)", "scale": {"zero": False},
                            },
                            "color": {"field": "方法", "type": "nominal", "title": "方法"},
                            "shape": {"field": "样品", "type": "nominal", "title": "B/R"},
                            "tooltip": [
                                {"field": "采集", "type": "nominal"},
                                {"field": "样品", "type": "nominal"},
                                {"field": "实际温度", "type": "quantitative", "format": ".2f"},
                                {"field": "实际间隔", "type": "quantitative", "format": ".4f"},
                                {"field": "方法", "type": "nominal"},
                                {"field": "软化率", "type": "quantitative", "format": ".2f"},
                            ],
                        },
                    },
                    width="stretch",
                )
                st.caption(
                    "图中保留原始计算值。超过 100% 或低于 0% 的值不会截断，必须结合曲线、"
                    "拟合 R² 和实验波动复核。"
                )
                st.download_button(
                    "下载 T75 候选软化结果",
                    softening_rows_csv_bytes(softening_preview["rows"]),
                    file_name="thermal_simulation_softening_candidate.csv",
                    mime="text/csv",
                    width="stretch",
                    key="thermal_download_softening",
                )
                with st.expander("查看拟合诊断与完整追溯字段", expanded=False):
                    st.dataframe(
                        pd.DataFrame(softening_preview["rows"]), hide_index=True, width="stretch",
                    )
                    st.caption(
                        "2% 偏移拟合使用 0<局部真应变≤0.02 的唯一应变点；"
                        "同应变重复点先取应力中位数。5% 对照的 σm 由第一道次 ε≥0.05 段"
                        "进行 Hollomon 拟合并向后投影 0.05 真应变。"
                    )
                with st.expander("人工复核并写入正式软化结果表", expanded=False):
                    st.warning(
                        "请重点检查标为‘需复核’的采集。确认后将只追加写入 "
                        "data/processed/thermal_simulation_softening.csv；系统不覆盖同版本结果。"
                    )
                    result_reviewer = st.text_input("结果复核人", key="thermal_softening_reviewer")
                    result_rationale = st.text_area(
                        "结果批准依据", key="thermal_softening_rationale",
                        placeholder="例如：已检查16个采集的偏移交点、拟合R²和超界值，批准按原始值入库。",
                    )
                    result_confirmed = st.checkbox(
                        "我确认当前精确结果和警告状态可以正式入库",
                        key="thermal_softening_confirmed",
                    )
                    can_commit = bool(
                        result_reviewer.strip() and result_rationale.strip() and result_confirmed
                    )
                    if st.button(
                        "批准并写入正式软化结果表",
                        type="primary",
                        disabled=not can_commit,
                        width="stretch",
                        key="thermal_commit_softening",
                    ):
                        try:
                            result = approve_and_commit_softening_results(
                                softening_preview,
                                reviewer_id=result_reviewer,
                                rationale=result_rationale,
                                confirmed=True,
                            )
                        except (GovernanceError, OSError, ValueError) as exc:
                            st.error("T75 正式写入失败：" + str(exc))
                        else:
                            record_event(
                                "thermal_softening_analysis",
                                "T75 双道次软化结果正式写入",
                                f"{softening_preview['row_count']} 个采集的软化率结果获批",
                                {
                                    "softening_version": softening_preview["softening_version"],
                                    "governance_intake_id": result["governance_intake_id"],
                                },
                                ["thermal_simulation", "softening", "human_approved"],
                            )
                            st.success("T75 正式结果已追加。治理记录：" + result["governance_intake_id"])
    with st.expander("公式与边界", expanded=False):
        st.code(
            "应力 (MPa) = 0.083 × Force × (1.5 − Stroke)\n"
            "真应变 = ln[1.5 ÷ (1.5 − Stroke)]",
            language="text",
        )
        st.caption(
            "仅适用于已登记的 Φ10×15 mm DH 压缩试样。Force 使用仪器 Kg 原值，Stroke 使用 cm 原值；"
            "公式全路径不自动删除负值和卸载段。文献分析视图按道次做力基线修正和局部应变归零；"
            "不做平滑、摩擦修正或绝热升温修正。"
        )
        st.markdown(
            "**T75 已批准软化率口径**  "
            "\n$X=(\\sigma_m-\\sigma_2)/(\\sigma_m-\\sigma_1)$；"
            "主方法的 $\\sigma_1$、$\\sigma_2$ 采用 2% 偏移法，$\\sigma_m$ 取第一道次峰值应力；"
            "5% 定真应变法作为敏感性对照，0.2% 偏移法仅保留为未来选项。"
        )
        st.caption(
            "接触点阈值不是统一文献标准，而是版本化项目规则：前 10%（20–40 点）估计基线，"
            "以峰值力增量 2% 与 6×MAD 噪声阈值中的较大者判定，连续 5 点超过阈值才算接触。"
        )


def render_thermal_simulation_intake() -> None:
    st.subheader("热模拟仪器曲线标准化")
    st.caption("适用于 ZHT.A75 这类文本导出：原文件只读，先解析与 QC，再核对计划和试样身份，最后才允许进入标准数据层。")
    st.info("仪器文件、计划照片和标准数据分开保存证据状态；计划值不会覆盖实测值，空值不会补成 0。")

    _render_standardized_curve_visualization()
    st.divider()
    st.markdown("#### 新批次标准化接入")

    source_mode = st.radio(
        "1. 数据来自哪里？", ["选择多个文件", "输入本机文件夹"], horizontal=True,
        key="thermal_source_mode",
    )
    files: dict[str, bytes] | None = None
    intake_request = None
    if source_mode == "选择多个文件":
        uploads = st.file_uploader(
            "选择热模拟导出文件（可多选）", type=None, accept_multiple_files=True,
            key="thermal_simulation_uploads",
        )
        if uploads:
            try:
                intake_request = register_intake_request(
                    st.session_state,
                    route="thermal_simulation_files",
                    selection=uploaded_file_selection(uploads),
                )
                files = _batch_from_uploads(uploads)
            except (OSError, ValueError) as exc:
                st.error("无法登记或读取数据选择；未执行导入：" + str(exc))
                return
    else:
        folder_text = st.text_input(
            "本机文件夹完整路径", placeholder=r"例如 D:\实验数据\double-hit",
            key="thermal_simulation_folder",
        )
        st.caption("只有点击“读取并预检”后才扫描这一层目录；不递归、不修改源文件、不上传到云端。")
        if folder_text.strip():
            try:
                intake_request = register_intake_request(
                    st.session_state,
                    route="thermal_simulation_folder",
                    selection=folder_reference_selection(folder_text),
                )
            except (OSError, ValueError) as exc:
                st.error("无法登记文件夹选择；未扫描目录：" + str(exc))
                return
            if intake_request.created:
                st.session_state.pop("thermal_folder_files", None)
        else:
            st.session_state.pop("thermal_folder_files", None)
        if st.button("读取并预检", type="primary", key="thermal_read_folder"):
            try:
                st.session_state["thermal_folder_files"] = read_thermal_simulation_folder(Path(folder_text))
            except (OSError, ValueError) as exc:
                st.error("文件夹读取失败：" + str(exc))
                st.session_state.pop("thermal_folder_files", None)
        files = st.session_state.get("thermal_folder_files")

    if intake_request is not None:
        st.caption(
            f"请求已登记：{intake_request.identity.request_id} · "
            f"任务：{intake_request.identity.task_id}（尚未执行）"
        )

    if not files:
        st.markdown("#### 当前状态")
        st.info("尚未选择热模拟文件。")
        return
    try:
        batch = inspect_thermal_simulation_batch(files)
    except ValueError as exc:
        st.error("批次读取失败：" + str(exc))
        return

    st.markdown("#### 2. 仪器文件解析与 QC")
    a, b, c = st.columns(3)
    a.metric("曲线文件", batch["file_count"])
    b.metric("数据点", batch["point_count"])
    c.metric("解析状态", "通过" if batch["status"] == "parsed" else "阻塞")
    summaries = []
    for item in batch["files"]:
        summaries.append({
            "文件": item["file_name"], "采集号": item["acquisition_id"],
            "分段": item["declared_interval_count"], "数据点": item["point_count"],
            "Period原值": item["period_value_raw"], "两段边界差原值": item["measured_interval_gap_raw"],
            "状态": item["status"], "SHA256": item["source_sha256"][:12].upper(),
        })
    st.dataframe(pd.DataFrame(summaries), hide_index=True, width="stretch")
    if batch["errors"]:
        st.error("\n\n".join(f"• {item}" for item in batch["errors"]))
    if batch["warnings"]:
        st.warning("\n\n".join(f"• {item}" for item in batch["warnings"]))

    st.markdown("#### 3. 计划、身份和单位确认")
    left, right = st.columns([2, 1])
    plan_upload = left.file_uploader(
        "上传计划映射 CSV（必须有真实 sample_id 和 specimen_id）", type=["csv"],
        key="thermal_plan_upload",
    )
    right.download_button(
        "下载计划映射模板", _plan_template(), file_name="thermal_simulation_plan_mapping.csv",
        mime="text/csv", use_container_width=True,
    )
    plan_rows: list[dict[str, str]] = []
    if plan_upload is not None:
        try:
            plan_rows = read_plan_csv(plan_upload.getvalue())
        except ValueError as exc:
            st.error("计划表读取失败：" + str(exc))
            return

    time_confirmed = st.checkbox(
        "我已根据仪器说明/实验记录确认 Time 与 Period 的单位为秒（s）",
        key="thermal_time_confirmed",
    )
    force_choice_label = st.selectbox(
        "Force [Kg] 的物理含义", [
            "尚未确认（force_n 留空）",
            "已确认是仪器 kg 力值（保留原值，不换算 N）",
            "已根据仪器依据确认是 kilogram-force（kgf）",
        ],
        key="thermal_force_unit",
    )
    mapping_confirmed = st.checkbox(
        "我已逐行核对 acquisition、sample_id、specimen_id 和计划参数的真实对应关系",
        disabled=not plan_rows, key="thermal_mapping_confirmed",
    )
    actual_over_plan = st.checkbox(
        "计划参数与曲线冲突时，保留计划值作为历史记录，并以仪器实际曲线作为本批有效实验数据",
        disabled=not plan_rows or not mapping_confirmed,
        key="thermal_actual_over_plan",
    )
    if "仪器 kg 力值" in force_choice_label:
        force_interpretation = "instrument_kg_force"
    elif "kilogram-force" in force_choice_label:
        force_interpretation = "kgf"
    else:
        force_interpretation = ""
    preview = build_thermal_standardization_preview(
        batch,
        plan_rows,
        time_unit_confirmed=time_confirmed,
        force_unit_interpretation=force_interpretation,
        specimen_mapping_confirmed=mapping_confirmed,
        accept_instrument_over_plan=actual_over_plan,
    )

    st.markdown("#### 4. 标准化预览")
    x, y, z = st.columns(3)
    labels = {"ready": "可进入审批", "needs_human": "需人工确认", "blocked": "阻塞"}
    x.metric("治理状态", labels[preview["status"]])
    y.metric("运行记录", preview["file_count"])
    z.metric("曲线点记录", preview["point_count"])
    if preview["errors"]:
        st.error("\n\n".join(f"• {item}" for item in preview["errors"]))
    if preview["decisions_needed"]:
        st.warning("待处理：\n\n" + "\n\n".join(f"• {item}" for item in preview["decisions_needed"]))
    if preview["warnings"]:
        st.warning("\n\n".join(f"• {item}" for item in preview["warnings"]))
    if preview["comparisons"]:
        st.caption("计划值与仪器曲线对照")
        st.dataframe(pd.DataFrame(preview["comparisons"]), hide_index=True, width="stretch")
    with st.expander("查看标准化运行表和曲线点", expanded=False):
        st.dataframe(pd.DataFrame(preview["run_rows"]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(preview["point_rows"][:200]), hide_index=True, width="stretch")
        st.caption("曲线点只显示前 200 行；下载文件保留全部数据点。")

    run_download, point_download, manifest_download = st.columns(3)
    run_download.download_button(
        "下载运行表预览", _csv_bytes(preview["run_rows"]),
        file_name="thermal_simulation_runs_preview.csv", mime="text/csv", use_container_width=True,
    )
    point_download.download_button(
        "下载曲线点预览", _csv_bytes(preview["point_rows"]),
        file_name="thermal_simulation_points_preview.csv", mime="text/csv", use_container_width=True,
    )
    manifest_download.download_button(
        "下载 QC 清单", json.dumps({
            key: value for key, value in preview.items() if key not in {"run_rows", "point_rows"}
        }, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="thermal_simulation_review_manifest.json", mime="application/json",
        use_container_width=True,
    )

    st.markdown("#### 5. 保存审查包")
    st.caption("审查包写入 outputs，不复制原始仪器文件，也不会写入正式 processed 数据表。")
    if st.button("保存本次预录入审查包", key="thermal_save_review", use_container_width=True):
        try:
            paths = save_thermal_preview_package(preview, OUTPUTS / "thermal_simulation_intake")
        except (OSError, ValueError) as exc:
            st.error("保存失败：" + str(exc))
            return
        st.success(f"已保存审查包：{paths['package']}。正式入库仍需把上面的待确认项全部解决。")

    st.markdown("#### 6. 人工批准并正式入库")
    st.caption("系统会在同一把接入锁下重新校验运行表和曲线点表，再一起追加；任一表失败都会回退本次写入。")
    reviewer_id = st.text_input(
        "复核人标识", placeholder="例如姓名、工号或 project_owner",
        key="thermal_reviewer_id",
    )
    rationale = st.text_area(
        "批准依据",
        placeholder="说明试样映射、单位依据，以及计划值与仪器实测冲突时采用哪一项。",
        key="thermal_approval_rationale",
    )
    confirmed = st.checkbox(
        "我确认本次会向 thermal_simulation_runs 和 thermal_simulation_points 追加正式记录",
        key="thermal_commit_confirmed",
    )
    can_commit = (
        preview["status"] == "ready"
        and bool(reviewer_id.strip())
        and bool(rationale.strip())
        and confirmed
    )
    if st.button(
        "批准并写入 SteelAI 标准数据层",
        type="primary",
        disabled=not can_commit,
        use_container_width=True,
        key="thermal_commit",
    ):
        try:
            result = commit_thermal_preview_governed(
                preview,
                reviewer_id=reviewer_id,
                rationale=rationale,
                confirmed=True,
                workflow_identity=intake_request.identity if intake_request is not None else None,
            )
            record_event(
                "data_intake",
                "热模拟曲线正式接入",
                f"{preview['file_count']} 个采集、{preview['point_count']} 个曲线点完成治理入库",
                {
                    "transaction_id": result["transaction_id"],
                    "governance_intake_id": result["governance_intake_id"],
                    "tables": result["tables"],
                    "request_id": result["request_id"],
                    "task_id": result["task_id"],
                    "run_id": result["run_id"],
                    "task_revision": result["task_revision"],
                },
                ["thermal_simulation", "data_standardization", "governed_intake"],
            )
        except (GovernanceError, OSError, ValueError) as exc:
            st.error("正式入库失败：" + str(exc))
            return
        st.success(
            "正式入库完成。事务编号："
            + result["transaction_id"]
            + "；治理记录："
            + result["governance_intake_id"]
        )
        st.json({"tables": result["tables"], "governance_package": result["governance_package"]})
