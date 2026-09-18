"""T75 method-selection and resolution diagnostics for double-hit softening."""
from __future__ import annotations

import json
import csv
import hashlib
import io
import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from steelai.paths import ROOT
from steelai.thermal_simulation_analysis import process_double_hit_curve


METHOD_REGISTRY_PATH = ROOT / "config" / "thermal_softening_method_registry_v1.0.json"
FEATURES_PATH = Path("data/processed/thermal_simulation_features.csv")
SOFTENING_RESULTS_PATH = Path("data/processed/thermal_simulation_softening.csv")


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_softening_method_registry(path: Path = METHOD_REGISTRY_PATH) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "registry_id", "schema_version", "result_version", "common_equation",
        "selected_method_id", "sensitivity_method_id", "selection_status",
        "method_decision", "methods", "current_batch_resolution_rule", "references",
    }
    missing = sorted(required - set(registry))
    if missing:
        raise ValueError("T75 软化方法登记缺少字段：" + ", ".join(missing))
    method_ids = [str(item.get("method_id", "")) for item in registry["methods"]]
    if not method_ids or any(not value for value in method_ids) or len(method_ids) != len(set(method_ids)):
        raise ValueError("T75 软化方法编号为空或重复。")
    selected = registry.get("selected_method_id")
    sensitivity = registry.get("sensitivity_method_id")
    if selected is not None and selected not in method_ids:
        raise ValueError("selected_method_id 未在方法登记中定义。")
    if sensitivity is not None and sensitivity not in method_ids:
        raise ValueError("sensitivity_method_id 未在方法登记中定义。")
    decision = registry.get("method_decision", {})
    if registry.get("selection_status") == "approved" and (
        not selected or not sensitivity or decision.get("decision") != "approved"
        or not str(decision.get("reviewer_id", "")).strip()
        or not str(decision.get("decided_at", "")).strip()
    ):
        raise ValueError("T75 方法已标记批准，但缺少主方法、对照方法或具名决策记录。")
    return registry


def assess_softening_method_readiness(
    runs: Iterable[Mapping[str, str]],
    points: Iterable[Mapping[str, str]],
    *,
    registry_path: Path = METHOD_REGISTRY_PATH,
) -> dict[str, Any]:
    """Assess strain-grid resolution only; do not choose or compute a softening method."""
    registry = load_softening_method_registry(registry_path)
    points_list = list(points)
    increments: list[float] = []
    run_count = 0
    segment_count = 0
    for run in runs:
        if str(run.get("test_type", "")).upper() != "DH":
            continue
        processed = process_double_hit_curve(run, points_list)
        run_count += 1
        for interval in (1, 2):
            strains = sorted({
                round(float(row["true_strain_local"]), 12)
                for row in processed["effective_rows"]
                if int(row["interval_index"]) == interval
            })
            segment_count += 1
            increments.extend(
                right - left for left, right in zip(strains, strains[1:]) if right > left
            )
    if not increments:
        raise ValueError("没有可用于 T75 分辨率检查的 DH 有效加载段。")
    minimum_increment = min(increments)
    median_increment = median(increments)
    required_ratio = float(
        registry["current_batch_resolution_rule"]["minimum_offset_to_median_step_ratio"]
    )
    method_results = []
    for method in registry["methods"]:
        offset = method.get("offset_true_strain")
        if offset is None:
            ratio = None
            resolution_status = "not_offset_based"
        else:
            numeric_offset = float(offset)
            ratio = numeric_offset / median_increment
            resolution_status = "resolved" if ratio >= required_ratio else "under_resolved"
        method_results.append({
            "method_id": method["method_id"],
            "label": method["label"],
            "offset_true_strain": offset,
            "median_step_coverage": ratio,
            "resolution_status": resolution_status,
            "interpretation": method["interpretation"],
            "current_batch_note": method["current_batch_note"],
        })
    return {
        "schema_version": "1.0",
        "status": "needs_project_owner_decision" if registry.get("selected_method_id") is None else "method_selected",
        "registry_id": registry["registry_id"],
        "selected_method_id": registry.get("selected_method_id"),
        "sensitivity_method_id": registry.get("sensitivity_method_id"),
        "selection_status": registry.get("selection_status"),
        "run_count": run_count,
        "segment_count": segment_count,
        "observed_minimum_positive_strain_increment": minimum_increment,
        "observed_median_positive_strain_increment": median_increment,
        "method_results": method_results,
        "formal_softening_computed": False,
        "warning": "分辨率检查只提示数值可辨性，不代替冶金方法选择。",
    }


def _method_by_id(registry: Mapping[str, Any], method_id: str) -> dict[str, Any]:
    for item in registry["methods"]:
        if item.get("method_id") == method_id:
            return dict(item)
    raise ValueError(f"T75 方法 {method_id} 未登记。")


def _curve_points(rows: Iterable[Mapping[str, Any]], interval: int) -> list[tuple[float, float]]:
    grouped: dict[float, list[float]] = {}
    for row in rows:
        if int(row["interval_index"]) != interval:
            continue
        strain = round(float(row["true_strain_local"]), 12)
        stress = float(row["stress_mpa_baseline_corrected"])
        if math.isfinite(strain) and math.isfinite(stress) and strain >= 0:
            grouped.setdefault(strain, []).append(stress)
    result = sorted((strain, float(median(values))) for strain, values in grouped.items())
    if len(result) < 2:
        raise ValueError(f"第 {interval} 道次没有足够的非负局部应变点。")
    return result


def _linear_regression(points: list[tuple[float, float]]) -> dict[str, float | int]:
    count = len(points)
    x_mean = sum(x for x, _ in points) / count
    y_mean = sum(y for _, y in points) / count
    x_sum = sum((x - x_mean) ** 2 for x, _ in points)
    if x_sum <= 0:
        raise ValueError("线性拟合应变没有变化。")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / x_sum
    intercept = y_mean - slope * x_mean
    total = sum((y - y_mean) ** 2 for _, y in points)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    r_squared = 1.0 if total <= 0 and residual <= 0 else (1.0 - residual / total if total > 0 else 0.0)
    return {
        "point_count": count,
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "strain_min": min(x for x, _ in points),
        "strain_max": max(x for x, _ in points),
    }


def _offset_proof_stress(
    curve: list[tuple[float, float]], method: Mapping[str, Any], *, interval: int,
) -> dict[str, float | int | str]:
    rule = method["yield_extraction"]
    lower = float(rule["initial_linear_fit_min_true_strain_exclusive"])
    upper = float(rule["initial_linear_fit_max_true_strain_inclusive"])
    fit_points = [(x, y) for x, y in curve if lower < x <= upper]
    if len(fit_points) < int(rule["minimum_unique_fit_points"]):
        raise ValueError(f"第 {interval} 道次的 2% 偏移初始线性段点数不足。")
    fit = _linear_regression(fit_points)
    if float(fit["slope"]) <= 0:
        raise ValueError(f"第 {interval} 道次的 2% 偏移初始斜率不为正。")
    if float(fit["r_squared"]) < float(rule["minimum_fit_r_squared"]):
        raise ValueError(f"第 {interval} 道次的 2% 偏移初始线性拟合 R² 未达门槛。")

    offset = float(method["offset_true_strain"])
    candidates = []
    for strain, stress in curve:
        if strain >= offset:
            offset_stress = float(fit["intercept"]) + float(fit["slope"]) * (strain - offset)
            candidates.append((strain, stress, stress - offset_stress))
    for left, right in zip(candidates, candidates[1:]):
        if left[2] == 0:
            proof_strain, proof_stress = left[0], left[1]
            break
        if left[2] > 0 and right[2] <= 0:
            fraction = left[2] / (left[2] - right[2])
            proof_strain = left[0] + fraction * (right[0] - left[0])
            proof_stress = left[1] + fraction * (right[1] - left[1])
            break
    else:
        raise ValueError(f"第 {interval} 道次未找到 2% 偏移线与曲线的交点，禁止外推。")
    return {
        "status": "passed",
        "proof_true_strain": proof_strain,
        "proof_stress_mpa": proof_stress,
        "fit_point_count": int(fit["point_count"]),
        "fit_slope_mpa": float(fit["slope"]),
        "fit_intercept_mpa": float(fit["intercept"]),
        "fit_r_squared": float(fit["r_squared"]),
        "fit_strain_min": float(fit["strain_min"]),
        "fit_strain_max": float(fit["strain_max"]),
    }


def _hollomon_projection(
    curve: list[tuple[float, float]], method: Mapping[str, Any],
) -> dict[str, float | int | str]:
    rule = method["yield_extraction"]
    lower = float(rule["hollomon_fit_min_true_strain_inclusive"])
    fit_source = [(x, y) for x, y in curve if x >= lower and y > 0]
    if len(fit_source) < int(rule["minimum_unique_fit_points"]):
        raise ValueError("第一道次用于 5% 对照的 Hollomon 拟合点数不足。")
    log_fit = _linear_regression([(math.log(x), math.log(y)) for x, y in fit_source])
    if float(log_fit["r_squared"]) < float(rule["minimum_fit_r_squared"]):
        raise ValueError("第一道次用于 5% 对照的 Hollomon 拟合 R² 未达门槛。")
    exponent = float(log_fit["slope"])
    strength = math.exp(float(log_fit["intercept"]))
    observed_max = max(x for x, _ in curve)
    target = observed_max + float(rule["projection_increment_true_strain"])
    projected = strength * target ** exponent
    return {
        "status": "passed",
        "fit_point_count": len(fit_source),
        "fit_r_squared": float(log_fit["r_squared"]),
        "fit_strain_min": min(x for x, _ in fit_source),
        "fit_strain_max": observed_max,
        "strength_coefficient_k_mpa": strength,
        "strain_hardening_exponent_n": exponent,
        "projection_true_strain": target,
        "projected_stress_mpa": projected,
    }


def _softening_fraction(sigma_m: float, sigma_1: float, sigma_2: float) -> float:
    denominator = sigma_m - sigma_1
    if not math.isfinite(denominator) or denominator <= 0:
        raise ValueError("软化率分母 sigma_m-sigma_1 不大于 0。")
    value = (sigma_m - sigma_2) / denominator
    if not math.isfinite(value):
        raise ValueError("软化率结果不是有限数值。")
    return value


def _fraction_status(value: float) -> str:
    return "passed" if 0.0 <= value <= 1.0 else "warning_outside_unit_interval"


def softening_rows_csv_bytes(rows: list[Mapping[str, Any]]) -> bytes:
    if not rows:
        return b""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def build_softening_result_preview(
    runs: Iterable[Mapping[str, str]],
    points: Iterable[Mapping[str, str]],
    *,
    project_root: Path = ROOT,
    registry_path: Path = METHOD_REGISTRY_PATH,
) -> dict[str, Any]:
    """Calculate reviewable T75 rows from approved T74 features without writing data."""
    registry = load_softening_method_registry(registry_path)
    if registry.get("selection_status") != "approved":
        raise ValueError("T75 方法尚未由项目负责人批准。")
    primary_method = _method_by_id(registry, str(registry["selected_method_id"]))
    sensitivity_method = _method_by_id(registry, str(registry["sensitivity_method_id"]))
    if primary_method.get("method_id") != "offset_2p0_srx_focused":
        raise ValueError("当前 T75 实现只允许已批准的 2% 偏移主方法。")
    if sensitivity_method.get("method_id") != "fixed_true_strain_0p05":
        raise ValueError("当前 T75 实现只允许已批准的 5% 定真应变对照。")

    features = _read_csv(project_root / FEATURES_PATH)
    feature_by_run = {row.get("experiment_run_id", ""): row for row in features}
    if len(feature_by_run) != len(features):
        raise ValueError("T74 正式特征表存在重复 experiment_run_id。")
    points_list = list(points)
    from steelai.thermal_simulation_features import build_thermal_feature_preview

    decision = registry["method_decision"]
    registry_sha256 = _file_sha256(registry_path)
    rows: list[dict[str, Any]] = []
    for run in runs:
        if str(run.get("test_type", "")).upper() != "DH":
            continue
        run_id = str(run.get("experiment_run_id", ""))
        feature = feature_by_run.get(run_id)
        if not feature:
            raise ValueError(f"{run_id} 尚无 T74 正式特征。")
        if feature.get("segment_review_status") != "approved":
            raise ValueError(f"{run_id} 的 T74 分段尚未批准。")
        typed_feature = dict(build_thermal_feature_preview(run, points_list)["rows"][0])
        typed_feature["segment_review_status"] = "approved"
        typed_feature["segment_reviewer_id"] = feature["segment_reviewer_id"]
        typed_feature["segment_reviewed_at"] = feature["segment_reviewed_at"]
        typed_feature.pop("feature_row_sha256", None)
        expected_feature_hash = _canonical_sha256(typed_feature)
        if feature.get("feature_row_sha256") != expected_feature_hash:
            raise ValueError(f"{run_id} 的 T74 特征行哈希校验失败。")
        processed = process_double_hit_curve(run, points_list)
        if feature.get("formula_id") != processed["formula"].get("formula_id"):
            raise ValueError(f"{run_id} 的 T74 公式版本与当前曲线处理不一致。")
        if feature.get("segment_policy_id") != processed["policy"].get("policy_id"):
            raise ValueError(f"{run_id} 的 T74 分段版本与当前曲线处理不一致。")
        hit1 = _curve_points(processed["effective_rows"], 1)
        hit2 = _curve_points(processed["effective_rows"], 2)
        proof1 = _offset_proof_stress(hit1, primary_method, interval=1)
        proof2 = _offset_proof_stress(hit2, primary_method, interval=2)
        sigma_m = float(feature["hit1_peak_stress_mpa"])
        primary_fraction = _softening_fraction(
            sigma_m, float(proof1["proof_stress_mpa"]), float(proof2["proof_stress_mpa"]),
        )

        projection = _hollomon_projection(hit1, sensitivity_method)
        sensitivity_sigma_1 = float(feature["hit1_flow_stress_at_strain_0p05_mpa"])
        sensitivity_sigma_2 = float(feature["hit2_flow_stress_at_strain_0p05_mpa"])
        sensitivity_fraction = _softening_fraction(
            float(projection["projected_stress_mpa"]), sensitivity_sigma_1, sensitivity_sigma_2,
        )
        primary_status = _fraction_status(primary_fraction)
        sensitivity_status = _fraction_status(sensitivity_fraction)
        flags = []
        if primary_status != "passed":
            flags.append("primary_softening_outside_0_to_1")
        if sensitivity_status != "passed":
            flags.append("sensitivity_softening_outside_0_to_1")
        result_status = "passed" if not flags else "warning_needs_human_review"
        row: dict[str, Any] = {
            "sample_id": feature["sample_id"],
            "specimen_id": feature["specimen_id"],
            "experiment_run_id": run_id,
            "acquisition_id": feature["acquisition_id"],
            "softening_version": registry["result_version"],
            "feature_version": feature["feature_version"],
            "test_type": feature["test_type"],
            "method_registry_id": registry["registry_id"],
            "method_registry_sha256": registry_sha256,
            "primary_method_id": primary_method["method_id"],
            "sensitivity_method_id": sensitivity_method["method_id"],
            "method_selection_status": registry["selection_status"],
            "method_decision_reviewer_id": decision["reviewer_id"],
            "method_decided_at": decision["decided_at"],
            "result_review_status": "calculated_needs_human_review",
            "result_reviewer_id": "",
            "result_reviewed_at": "",
            "source_status": "derived_from_approved_thermal_features_and_governed_points",
            "source_feature_review_status": feature["segment_review_status"],
            "source_feature_reviewer_id": feature["segment_reviewer_id"],
            "source_feature_row_sha256": feature["feature_row_sha256"],
            "effective_temperature_c": float(feature["effective_temperature_c"]),
            "run_effective_interpass_time_s": float(feature["run_effective_interpass_time_s"]),
            "effective_deformation_gap_s": float(feature["effective_deformation_gap_s"]),
            "primary_sigma_m_mpa": sigma_m,
            "primary_sigma_1_mpa": float(proof1["proof_stress_mpa"]),
            "primary_sigma_2_mpa": float(proof2["proof_stress_mpa"]),
            "primary_softening_fraction_raw": primary_fraction,
            "primary_softening_percent_raw": primary_fraction * 100.0,
            "primary_result_status": primary_status,
            "hit1_offset_proof_true_strain": float(proof1["proof_true_strain"]),
            "hit1_offset_fit_point_count": int(proof1["fit_point_count"]),
            "hit1_offset_fit_slope_mpa": float(proof1["fit_slope_mpa"]),
            "hit1_offset_fit_intercept_mpa": float(proof1["fit_intercept_mpa"]),
            "hit1_offset_fit_r_squared": float(proof1["fit_r_squared"]),
            "hit1_offset_fit_strain_min": float(proof1["fit_strain_min"]),
            "hit1_offset_fit_strain_max": float(proof1["fit_strain_max"]),
            "hit2_offset_proof_true_strain": float(proof2["proof_true_strain"]),
            "hit2_offset_fit_point_count": int(proof2["fit_point_count"]),
            "hit2_offset_fit_slope_mpa": float(proof2["fit_slope_mpa"]),
            "hit2_offset_fit_intercept_mpa": float(proof2["fit_intercept_mpa"]),
            "hit2_offset_fit_r_squared": float(proof2["fit_r_squared"]),
            "hit2_offset_fit_strain_min": float(proof2["fit_strain_min"]),
            "hit2_offset_fit_strain_max": float(proof2["fit_strain_max"]),
            "sensitivity_sigma_m_mpa": float(projection["projected_stress_mpa"]),
            "sensitivity_sigma_1_mpa": sensitivity_sigma_1,
            "sensitivity_sigma_2_mpa": sensitivity_sigma_2,
            "sensitivity_softening_fraction_raw": sensitivity_fraction,
            "sensitivity_softening_percent_raw": sensitivity_fraction * 100.0,
            "sensitivity_result_status": sensitivity_status,
            "sensitivity_evaluation_true_strain": float(
                sensitivity_method["yield_extraction"]["evaluation_true_strain"]
            ),
            "hollomon_fit_point_count": int(projection["fit_point_count"]),
            "hollomon_fit_r_squared": float(projection["fit_r_squared"]),
            "hollomon_fit_strain_min": float(projection["fit_strain_min"]),
            "hollomon_fit_strain_max": float(projection["fit_strain_max"]),
            "hollomon_strength_coefficient_k_mpa": float(projection["strength_coefficient_k_mpa"]),
            "hollomon_strain_hardening_exponent_n": float(projection["strain_hardening_exponent_n"]),
            "hollomon_projection_true_strain": float(projection["projection_true_strain"]),
            "sensitivity_minus_primary_fraction": sensitivity_fraction - primary_fraction,
            "result_qc_status": result_status,
            "qc_flags": ";".join(flags),
        }
        row["softening_row_sha256"] = _canonical_sha256(row)
        rows.append(row)
    rows.sort(key=lambda item: int(item["acquisition_id"]))
    warning_count = sum(row["result_qc_status"] != "passed" for row in rows)
    preview = {
        "schema_version": "1.0",
        "status": "needs_human",
        "softening_version": registry["result_version"],
        "primary_method_id": primary_method["method_id"],
        "sensitivity_method_id": sensitivity_method["method_id"],
        "row_count": len(rows),
        "passed_count": len(rows) - warning_count,
        "warning_count": warning_count,
        "rows": rows,
        "warnings": [
            "软化率保留原始计算值，不把小于0或大于1的结果截断。",
            "5%定真应变对照的sigma_m来自已登记的Hollomon外推，不能当作实测点。",
        ],
    }
    preview["preview_sha256"] = _canonical_sha256(preview)
    return preview


def approve_and_commit_softening_results(
    preview: Mapping[str, Any], *, reviewer_id: str, rationale: str, confirmed: bool,
    project_root: Path = ROOT, decided_at: str | None = None,
) -> dict[str, Any]:
    """Approve exact T75 results and append them through the shared governance gate."""
    from steelai.data_intake import validate_intake_csv
    from steelai.data_intake_governance import commit_standard_intake_governed

    if preview.get("status") != "needs_human" or not preview.get("rows"):
        raise ValueError("没有可供人工批准的 T75 结果预览。")
    if not confirmed or not reviewer_id.strip() or not rationale.strip():
        raise ValueError("正式写入需要具名复核人、批准依据和明确确认。")
    expected = _canonical_sha256({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })
    if preview.get("preview_sha256") != expected:
        raise ValueError("T75 结果预览内容已变化，请重新生成并复核。")
    timestamp = decided_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    approved_rows = []
    for source in preview["rows"]:
        row = dict(source)
        if row.get("result_review_status") != "calculated_needs_human_review":
            raise ValueError("T75 结果状态不是待人工复核。")
        row["result_review_status"] = "approved"
        row["result_reviewer_id"] = reviewer_id.strip()
        row["result_reviewed_at"] = timestamp
        row.pop("softening_row_sha256", None)
        row["softening_row_sha256"] = _canonical_sha256(row)
        approved_rows.append(row)
    report = validate_intake_csv(
        "thermal_simulation_softening", softening_rows_csv_bytes(approved_rows),
        project_root=project_root,
    )
    if report["status"] != "ready":
        raise ValueError("T75 软化结果表校验失败：" + "；".join(report["errors"]))
    evidence = {
        "schema_version": "1.0",
        "preview_sha256": preview["preview_sha256"],
        "softening_version": preview.get("softening_version"),
        "primary_method_id": preview.get("primary_method_id"),
        "sensitivity_method_id": preview.get("sensitivity_method_id"),
        "result_reviewer_id": reviewer_id.strip(),
        "result_reviewed_at": timestamp,
        "result_review_rationale": rationale.strip(),
        "warning_count": preview.get("warning_count"),
        "raw_source_files_copied": False,
    }
    return commit_standard_intake_governed(
        report,
        reviewer_id=reviewer_id,
        rationale=rationale,
        confirmed=True,
        route="thermal_simulation",
        source_id="THERMAL-SOFTENING-" + str(preview["preview_sha256"])[:20].upper(),
        source_digest=str(preview["preview_sha256"]),
        project_root=project_root,
        extra_artifacts={"thermal_softening_review.json": evidence},
    )
