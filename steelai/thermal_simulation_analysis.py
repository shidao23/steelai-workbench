"""Deterministic visualization data for governed thermal-simulation curves."""
from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from steelai.paths import ROOT


FORMULA_PATH = ROOT / "config" / "thermal_compression_formula_v1.0.json"
DOUBLE_HIT_POLICY_PATH = ROOT / "config" / "thermal_double_hit_processing_v1.0.json"
RUNS_PATH = Path("data/processed/thermal_simulation_runs.csv")
POINTS_PATH = Path("data/processed/thermal_simulation_points.csv")


def load_thermal_formula(path: Path = FORMULA_PATH) -> dict[str, Any]:
    formula = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "formula_id", "applicable_test_type", "specimen_diameter_mm",
        "initial_height_mm", "initial_height_cm", "force_input_unit",
        "stroke_input_unit", "stress_coefficient", "stress_formula", "strain_formula",
    }
    missing = sorted(required - set(formula))
    if missing:
        raise ValueError("热模拟应力应变公式登记缺少字段：" + ", ".join(missing))
    numbers = (
        float(formula["specimen_diameter_mm"]), float(formula["initial_height_mm"]),
        float(formula["initial_height_cm"]), float(formula["stress_coefficient"]),
    )
    if not all(math.isfinite(value) and value > 0 for value in numbers):
        raise ValueError("热模拟应力应变公式的几何或系数无效。")
    return formula


def load_double_hit_policy(path: Path = DOUBLE_HIT_POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {"policy_id", "schema_version", "scope", "segmentation", "analysis"}
    missing = sorted(required - set(policy))
    if missing:
        raise ValueError("double-hit 处理规则缺少字段：" + ", ".join(missing))
    segmentation = policy["segmentation"]
    required_segmentation = {
        "baseline_fraction", "baseline_min_points", "baseline_max_points",
        "contact_peak_fraction", "contact_mad_multiplier", "minimum_consecutive_points",
        "end_rule", "expected_interval_count",
    }
    missing_segmentation = sorted(required_segmentation - set(segmentation))
    if missing_segmentation:
        raise ValueError("double-hit 分段规则缺少字段：" + ", ".join(missing_segmentation))
    if not 0 < float(segmentation["baseline_fraction"]) < 0.5:
        raise ValueError("baseline_fraction 必须在 0 和 0.5 之间。")
    if not 0 < float(segmentation["contact_peak_fraction"]) < 1:
        raise ValueError("contact_peak_fraction 必须在 0 和 1 之间。")
    if int(segmentation["minimum_consecutive_points"]) < 1:
        raise ValueError("minimum_consecutive_points 必须大于 0。")
    return policy


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_standardized_thermal_data(
    project_root: Path = ROOT,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Read only the two governed standardized tables; never read raw files."""
    runs = _read_csv(project_root / RUNS_PATH)
    points = _read_csv(project_root / POINTS_PATH)
    run_ids = {row.get("experiment_run_id", "") for row in runs}
    unknown = sorted({row.get("experiment_run_id", "") for row in points} - run_ids)
    if unknown:
        raise ValueError("曲线点存在未登记运行：" + ", ".join(unknown))
    return runs, points


def derive_compression_curve(
    run: Mapping[str, str],
    points: Iterable[Mapping[str, str]],
    *,
    formula_path: Path = FORMULA_PATH,
) -> dict[str, Any]:
    """Apply the project-owner supplied Phi10x15 formula without altering source values."""
    formula = load_thermal_formula(formula_path)
    run_id = str(run.get("experiment_run_id", ""))
    if str(run.get("test_type", "")).upper() != str(formula["applicable_test_type"]).upper():
        raise ValueError("当前公式只适用于 DH 压缩采集。")
    diameter = float(str(run.get("specimen_diameter_mm", "") or "nan"))
    height = float(str(run.get("specimen_height_mm", "") or "nan"))
    if not math.isclose(diameter, float(formula["specimen_diameter_mm"]), abs_tol=1e-9):
        raise ValueError("试样直径不是公式登记的 10 mm。")
    if not math.isclose(height, float(formula["initial_height_mm"]), abs_tol=1e-9):
        raise ValueError("试样初始长度不是公式登记的 15 mm。")

    initial_height_cm = float(formula["initial_height_cm"])
    coefficient = float(formula["stress_coefficient"])
    derived: list[dict[str, Any]] = []
    for row in points:
        if str(row.get("experiment_run_id", "")) != run_id:
            continue
        if row.get("force_unit_raw") != formula["force_input_unit"]:
            raise ValueError(f"{run_id} Force 单位不是公式登记的 Kg。")
        if row.get("stroke_unit_raw") != formula["stroke_input_unit"]:
            raise ValueError(f"{run_id} Stroke 单位不是公式登记的 cm。")
        try:
            force = float(str(row.get("force_value_raw", "")))
            stroke = float(str(row.get("stroke_value_raw", "")))
            time_s = float(str(row.get("time_s", "")))
            temperature = float(str(row.get("control_temperature_c", "")))
        except ValueError as exc:
            raise ValueError(f"{run_id} 存在缺失或非数值的公式输入。") from exc
        current_height_cm = initial_height_cm - stroke
        if not all(math.isfinite(value) for value in (force, stroke, time_s, temperature)):
            raise ValueError(f"{run_id} 存在非有限公式输入。")
        if current_height_cm <= 0:
            raise ValueError(f"{run_id} 的 Stroke 导致当前长度不大于 0，公式停止。")
        derived.append({
            "sample_id": str(row.get("sample_id", "")),
            "specimen_id": str(row.get("specimen_id", "")),
            "experiment_run_id": run_id,
            "acquisition_id": str(run.get("acquisition_id", "")),
            "interval_index": int(str(row.get("interval_index", ""))),
            "point_index": int(str(row.get("point_index", ""))),
            "time_s": time_s,
            "temperature_c": temperature,
            "force_value_raw": force,
            "force_unit_raw": str(row.get("force_unit_raw", "")),
            "stroke_cm": stroke,
            "stroke_mm": float(str(row.get("stroke_mm", ""))),
            "current_height_cm": current_height_cm,
            "stress_mpa": coefficient * force * current_height_cm,
            "true_strain": math.log(initial_height_cm / current_height_cm),
            "formula_id": str(formula["formula_id"]),
        })
    if not derived:
        raise ValueError(f"{run_id} 没有可用于绘图的标准化曲线点。")
    return {
        "schema_version": "1.0",
        "formula": formula,
        "run": dict(run),
        "rows": derived,
        "point_count": len(derived),
        "peak_stress_mpa": max(row["stress_mpa"] for row in derived),
        "max_true_strain": max(row["true_strain"] for row in derived),
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def process_double_hit_curve(
    run: Mapping[str, str],
    points: Iterable[Mapping[str, str]],
    *,
    formula_path: Path = FORMULA_PATH,
    policy_path: Path = DOUBLE_HIT_POLICY_PATH,
) -> dict[str, Any]:
    """Create reviewable loading-segment candidates without changing governed raw data.

    The literature establishes separate hit coordinates and the later 0.2% offset
    softening calculation. Contact detection is explicitly a versioned SteelAI
    project rule because published double-hit work does not define one universal
    instrument-force threshold.
    """
    policy = load_double_hit_policy(policy_path)
    curve = derive_compression_curve(run, points, formula_path=formula_path)
    if str(run.get("test_type", "")).upper() != str(policy["scope"]["test_type"]).upper():
        raise ValueError("当前 double-hit 处理规则只适用于 DH 采集。")

    segmentation = policy["segmentation"]
    rows = [dict(row) for row in curve["rows"]]
    interval_ids = sorted({int(row["interval_index"]) for row in rows})
    expected = int(segmentation["expected_interval_count"])
    if len(interval_ids) != expected:
        raise ValueError(f"double-hit 应包含 {expected} 个 interval，当前为 {len(interval_ids)} 个。")

    summaries: list[dict[str, Any]] = []
    for interval_id in interval_ids:
        members = [row for row in rows if int(row["interval_index"]) == interval_id]
        members.sort(key=lambda row: int(row["point_index"]))
        minimum_consecutive = int(segmentation["minimum_consecutive_points"])
        if len(members) <= minimum_consecutive + 2:
            raise ValueError(f"interval {interval_id} 点数不足，无法识别有效加载段。")

        desired_baseline = round(len(members) * float(segmentation["baseline_fraction"]))
        baseline_count = max(int(segmentation["baseline_min_points"]), desired_baseline)
        baseline_count = min(int(segmentation["baseline_max_points"]), baseline_count, len(members) - 1)
        baseline_force_values = [float(row["force_value_raw"]) for row in members[:baseline_count]]
        baseline_force = _median(baseline_force_values)
        absolute_deviations = [abs(value - baseline_force) for value in baseline_force_values]
        robust_sigma = 1.4826 * _median(absolute_deviations)
        peak_force = max(float(row["force_value_raw"]) for row in members)
        dynamic_force = peak_force - baseline_force
        if not math.isfinite(dynamic_force) or dynamic_force <= 0:
            raise ValueError(f"interval {interval_id} 没有可识别的正向加载力增量。")
        threshold_increment = max(
            float(segmentation["contact_peak_fraction"]) * dynamic_force,
            float(segmentation["contact_mad_multiplier"]) * robust_sigma,
        )
        contact_threshold = baseline_force + threshold_increment

        max_stroke = max(float(row["stroke_cm"]) for row in members)
        end_position = next(
            index for index, row in enumerate(members)
            if math.isclose(float(row["stroke_cm"]), max_stroke, rel_tol=0.0, abs_tol=1e-12)
        )
        start_position: int | None = None
        latest_start = end_position - minimum_consecutive + 1
        for index in range(max(0, baseline_count - 1), max(0, latest_start + 1)):
            window = members[index:index + minimum_consecutive]
            if len(window) == minimum_consecutive and all(
                float(row["force_value_raw"]) >= contact_threshold for row in window
            ):
                start_position = index
                break
        if start_position is None or start_position >= end_position:
            raise ValueError(f"interval {interval_id} 未找到稳定接触点；必须人工复核。")

        contact_strain = float(members[start_position]["true_strain"])
        segment_point_count = end_position - start_position + 1
        for position, row in enumerate(members):
            zeroed_force = float(row["force_value_raw"]) - baseline_force
            row["force_baseline_raw"] = baseline_force
            row["force_baseline_corrected"] = zeroed_force
            row["stress_mpa_formula_raw"] = float(row["stress_mpa"])
            row["stress_mpa_baseline_corrected"] = (
                float(curve["formula"]["stress_coefficient"])
                * zeroed_force
                * float(row["current_height_cm"])
            )
            row["true_strain_cumulative"] = float(row["true_strain"])
            row["true_strain_local"] = float(row["true_strain"]) - contact_strain
            row["in_effective_loading_segment"] = start_position <= position <= end_position
            row["segment_policy_id"] = str(policy["policy_id"])
            row["segment_review_status"] = "suggested_needs_human"

        segment_rows = members[start_position:end_position + 1]
        local_strain_max = max(float(row["true_strain_local"]) for row in segment_rows)
        summaries.append({
            "experiment_run_id": str(run.get("experiment_run_id", "")),
            "acquisition_id": str(run.get("acquisition_id", "")),
            "sample_id": str(run.get("sample_id", "")),
            "interval_index": interval_id,
            "contact_point_index": int(members[start_position]["point_index"]),
            "end_point_index": int(members[end_position]["point_index"]),
            "contact_time_s": float(members[start_position]["time_s"]),
            "end_time_s": float(members[end_position]["time_s"]),
            "baseline_point_count": baseline_count,
            "baseline_force_raw": baseline_force,
            "contact_force_threshold_raw": contact_threshold,
            "segment_point_count": segment_point_count,
            "max_local_true_strain": local_strain_max,
            "peak_baseline_corrected_stress_mpa": max(
                float(row["stress_mpa_baseline_corrected"]) for row in segment_rows
            ),
            "segment_policy_id": str(policy["policy_id"]),
            "review_status": "suggested_needs_human",
        })

    all_segment_rows = [row for row in rows if row["in_effective_loading_segment"]]
    return {
        "schema_version": "1.0",
        "policy": policy,
        "formula": curve["formula"],
        "run": dict(run),
        "rows": rows,
        "effective_rows": all_segment_rows,
        "segments": summaries,
        "review_status": "suggested_needs_human",
        "warning": "自动分段是待复核建议；未批准前不得作为正式软化率输入。",
    }


def paired_runs(runs: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Pair B/R runs by reviewed plan condition without inferring specimen identity."""
    groups: dict[tuple[str, str, str], dict[str, dict[str, str]]] = {}
    for source in runs:
        row = {str(key): str(value) for key, value in source.items()}
        key = (
            row.get("test_type", ""), row.get("planned_temperature_c", ""),
            row.get("planned_interpass_time_s", ""),
        )
        groups.setdefault(key, {})[row.get("sample_id", "")] = row
    result = []
    for key, samples in groups.items():
        if "B-DQ" not in samples or "R-DQ" not in samples:
            continue
        test_type, _, _ = key
        b_run, r_run = samples["B-DQ"], samples["R-DQ"]
        label = f"{test_type} · A{b_run.get('acquisition_id')}/A{r_run.get('acquisition_id')}"
        b_temperature, r_temperature = b_run.get("effective_temperature_c", ""), r_run.get("effective_temperature_c", "")
        if b_temperature and r_temperature:
            label += f" · 有效温度 {float(b_temperature):.1f}/{float(r_temperature):.1f} °C"
        b_interval, r_interval = b_run.get("effective_interpass_time_s", ""), r_run.get("effective_interpass_time_s", "")
        if b_interval and r_interval:
            label += f" · 有效间隔 {float(b_interval):.3g}/{float(r_interval):.3g} s"
        result.append({"key": key, "label": label, "B-DQ": b_run, "R-DQ": r_run})
    return sorted(result, key=lambda item: int(item["B-DQ"].get("acquisition_id", "0")))
