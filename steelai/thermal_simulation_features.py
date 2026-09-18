"""T74 governed feature extraction for approved double-hit loading segments."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from steelai.paths import ROOT
from steelai.thermal_simulation_analysis import (
    DOUBLE_HIT_POLICY_PATH,
    FORMULA_PATH,
    process_double_hit_curve,
)


FEATURE_POLICY_PATH = ROOT / "config" / "thermal_feature_extraction_v1.0.json"


def load_thermal_feature_policy(path: Path = FEATURE_POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "feature_version", "schema_version", "scope", "target_local_true_strains",
        "flow_stress_sampling", "formal_write",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise ValueError("热模拟特征规则缺少字段：" + ", ".join(missing))
    targets = [float(value) for value in policy["target_local_true_strains"]]
    if not targets or targets != sorted(set(targets)) or any(
        not math.isfinite(value) or value <= 0 for value in targets
    ):
        raise ValueError("指定局部真应变必须是递增、唯一的正数。")
    if policy["flow_stress_sampling"].get("extrapolation") != "forbidden":
        raise ValueError("热模拟特征规则必须禁止应变外推。")
    return policy


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _strain_label(value: float) -> str:
    return format(value, ".6g").replace("-", "m").replace(".", "p")


def _stress_at_local_strain(rows: list[dict[str, Any]], target: float) -> float:
    grouped: dict[float, list[float]] = {}
    for row in rows:
        strain = float(row["true_strain_local"])
        stress = float(row["stress_mpa_baseline_corrected"])
        grouped.setdefault(strain, []).append(stress)
    points = sorted((strain, float(median(stresses))) for strain, stresses in grouped.items())
    if not points or target < points[0][0] or target > points[-1][0]:
        raise ValueError(f"指定局部真应变 {target:g} 超出有效加载段，禁止外推。")
    for strain, stress in points:
        if math.isclose(strain, target, rel_tol=0.0, abs_tol=1e-12):
            return stress
    for (left_strain, left_stress), (right_strain, right_stress) in zip(points, points[1:]):
        if left_strain < target < right_strain:
            fraction = (target - left_strain) / (right_strain - left_strain)
            return left_stress + fraction * (right_stress - left_stress)
    raise ValueError(f"指定局部真应变 {target:g} 没有可用插值区间。")


def _points_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    selected = [{
        "interval_index": int(row["interval_index"]),
        "point_index": int(row["point_index"]),
        "time_s": float(row["time_s"]),
        "force_value_raw": float(row["force_value_raw"]),
        "stroke_cm": float(row["stroke_cm"]),
        "temperature_c": float(row["temperature_c"]),
    } for row in rows]
    return _canonical_sha256(selected)


def build_thermal_feature_preview(
    run: Mapping[str, str],
    points: Iterable[Mapping[str, str]],
    *,
    feature_policy_path: Path = FEATURE_POLICY_PATH,
    formula_path: Path = FORMULA_PATH,
    segment_policy_path: Path = DOUBLE_HIT_POLICY_PATH,
) -> dict[str, Any]:
    """Build one candidate feature row; this function never writes processed data."""
    feature_policy = load_thermal_feature_policy(feature_policy_path)
    processed = process_double_hit_curve(
        run, points, formula_path=formula_path, policy_path=segment_policy_path,
    )
    scope = feature_policy["scope"]
    if processed["formula"]["formula_id"] != scope["formula_id"]:
        raise ValueError("公式版本与 T74 特征规则不一致。")
    if processed["policy"]["policy_id"] != scope["segment_policy_id"]:
        raise ValueError("分段版本与 T74 特征规则不一致。")

    segment_rows: dict[int, list[dict[str, Any]]] = {}
    for row in processed["effective_rows"]:
        segment_rows.setdefault(int(row["interval_index"]), []).append(row)
    if sorted(segment_rows) != [1, 2]:
        raise ValueError("T74 只接受已识别出两道次的 DH 曲线。")

    row: dict[str, Any] = {
        "sample_id": str(run.get("sample_id", "")),
        "specimen_id": str(run.get("specimen_id", "")),
        "experiment_run_id": str(run.get("experiment_run_id", "")),
        "acquisition_id": str(run.get("acquisition_id", "")),
        "feature_version": str(feature_policy["feature_version"]),
        "test_type": str(run.get("test_type", "")),
        "effective_temperature_c": str(run.get("effective_temperature_c", "")),
        "run_effective_interpass_time_s": str(run.get("effective_interpass_time_s", "")),
        "formula_id": str(processed["formula"]["formula_id"]),
        "segment_policy_id": str(processed["policy"]["policy_id"]),
        "segment_review_status": "suggested_needs_human",
        "segment_reviewer_id": "",
        "segment_reviewed_at": "",
        "source_status": "derived_from_governed_thermal_points",
        "source_run_review_status": str(run.get("review_status", "")),
        "source_file_sha256": str(run.get("source_file_sha256", "")),
        "source_points_sha256": _points_digest(processed["rows"]),
        "formula_config_sha256": _file_sha256(formula_path),
        "segment_policy_sha256": _file_sha256(segment_policy_path),
        "feature_policy_sha256": _file_sha256(feature_policy_path),
    }

    for hit in (1, 2):
        rows = sorted(segment_rows[hit], key=lambda item: int(item["point_index"]))
        peak = max(rows, key=lambda item: float(item["stress_mpa_baseline_corrected"]))
        first, last = rows[0], rows[-1]
        prefix = f"hit{hit}_"
        row.update({
            prefix + "start_point_index": int(first["point_index"]),
            prefix + "end_point_index": int(last["point_index"]),
            prefix + "start_time_s": float(first["time_s"]),
            prefix + "end_time_s": float(last["time_s"]),
            prefix + "start_temperature_c": float(first["temperature_c"]),
            prefix + "mean_temperature_c": sum(float(item["temperature_c"]) for item in rows) / len(rows),
            prefix + "end_temperature_c": float(last["temperature_c"]),
            prefix + "peak_stress_mpa": float(peak["stress_mpa_baseline_corrected"]),
            prefix + "peak_local_true_strain": float(peak["true_strain_local"]),
            prefix + "peak_temperature_c": float(peak["temperature_c"]),
            prefix + "max_stroke_cm": max(float(item["stroke_cm"]) for item in rows),
            prefix + "max_displacement_from_contact_cm": (
                max(float(item["stroke_cm"]) for item in rows) - float(first["stroke_cm"])
            ),
            prefix + "max_local_true_strain": max(float(item["true_strain_local"]) for item in rows),
        })
        for target in feature_policy["target_local_true_strains"]:
            numeric_target = float(target)
            row[prefix + f"flow_stress_at_strain_{_strain_label(numeric_target)}_mpa"] = (
                _stress_at_local_strain(rows, numeric_target)
            )

    row["effective_deformation_gap_s"] = float(row["hit2_start_time_s"]) - float(row["hit1_end_time_s"])
    segment_snapshot = [{
        key: value for key, value in item.items()
        if key in {
            "interval_index", "contact_point_index", "end_point_index", "baseline_point_count",
            "baseline_force_raw", "contact_force_threshold_raw", "segment_policy_id",
        }
    } for item in processed["segments"]]
    row["segment_candidate_sha256"] = _canonical_sha256(segment_snapshot)
    row["feature_row_sha256"] = _canonical_sha256(row)
    preview = {
        "schema_version": "1.0",
        "status": "needs_human",
        "feature_version": feature_policy["feature_version"],
        "rows": [row],
        "segments": processed["segments"],
        "warnings": ["有效加载段尚未由具名人工复核；当前特征只能作为预览。"],
    }
    preview["preview_sha256"] = _canonical_sha256(preview)
    return preview


def build_thermal_feature_batch_preview(
    runs: Iterable[Mapping[str, str]], points: Iterable[Mapping[str, str]],
) -> dict[str, Any]:
    points_list = list(points)
    previews = [
        build_thermal_feature_preview(run, points_list)
        for run in runs if str(run.get("test_type", "")).upper() == "DH"
    ]
    return combine_thermal_feature_previews(previews)


def combine_thermal_feature_previews(previews: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    preview_list = list(previews)
    rows = [dict(row) for preview in preview_list for row in preview.get("rows", [])]
    result = {
        "schema_version": "1.0",
        "status": "needs_human" if rows else "blocked",
        "feature_version": preview_list[0]["feature_version"] if preview_list else "",
        "rows": rows,
        "segments": [dict(segment) for preview in preview_list for segment in preview.get("segments", [])],
        "run_count": len(rows),
        "segment_count": sum(len(preview.get("segments", [])) for preview in preview_list),
        "warnings": ["批次特征来自自动候选段；正式写入前必须逐采集目视复核。"],
    }
    result["preview_sha256"] = _canonical_sha256(result)
    return result


def feature_rows_csv_bytes(rows: list[Mapping[str, Any]]) -> bytes:
    if not rows:
        return b""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def approve_and_commit_thermal_features(
    preview: Mapping[str, Any], *, reviewer_id: str, rationale: str, confirmed: bool,
    project_root: Path = ROOT, decided_at: str | None = None,
) -> dict[str, Any]:
    """Approve exact candidate boundaries and append feature rows through the shared gate."""
    from steelai.data_intake import validate_intake_csv
    from steelai.data_intake_governance import commit_standard_intake_governed

    if preview.get("status") != "needs_human" or not preview.get("rows"):
        raise ValueError("没有可供人工批准的 T74 特征预览。")
    if not confirmed or not reviewer_id.strip() or not rationale.strip():
        raise ValueError("正式写入需要具名复核人、批准依据和明确确认。")
    expected_digest = _canonical_sha256({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })
    if preview.get("preview_sha256") != expected_digest:
        raise ValueError("特征预览内容已变化，请重新生成并复核。")
    timestamp = decided_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    approved_rows = []
    for source in preview["rows"]:
        row = dict(source)
        if row.get("segment_review_status") != "suggested_needs_human":
            raise ValueError("特征预览的分段状态不是待人工复核。")
        row["segment_review_status"] = "approved"
        row["segment_reviewer_id"] = reviewer_id.strip()
        row["segment_reviewed_at"] = timestamp
        row.pop("feature_row_sha256", None)
        row["feature_row_sha256"] = _canonical_sha256(row)
        approved_rows.append(row)

    report = validate_intake_csv(
        "thermal_simulation_features", feature_rows_csv_bytes(approved_rows), project_root=project_root,
    )
    if report["status"] != "ready":
        raise ValueError("T74 特征表校验失败：" + "；".join(report["errors"]))
    evidence = {
        "schema_version": "1.0",
        "preview_sha256": preview["preview_sha256"],
        "feature_version": preview.get("feature_version"),
        "segments": list(preview.get("segments", [])),
        "segment_reviewer_id": reviewer_id.strip(),
        "segment_reviewed_at": timestamp,
        "segment_review_rationale": rationale.strip(),
        "raw_source_files_copied": False,
    }
    return commit_standard_intake_governed(
        report,
        reviewer_id=reviewer_id,
        rationale=rationale,
        confirmed=True,
        route="thermal_simulation",
        source_id="THERMAL-FEATURE-" + str(preview["preview_sha256"])[:20].upper(),
        source_digest=str(preview["preview_sha256"]),
        project_root=project_root,
        extra_artifacts={"thermal_feature_review.json": evidence},
    )
