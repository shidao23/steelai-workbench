"""Deterministic intake for text exports from thermal-simulation instruments.

The source files are never edited.  Parsing, unit-preserving normalization and
QC are deterministic; physical specimen identity and ambiguous units remain
human decisions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from steelai.workflow_identity import WorkflowIdentity


MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_BATCH_FILES = 200
MAX_BATCH_BYTES = 200 * 1024 * 1024
SOURCE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\.A\d+$", re.IGNORECASE)
PROGRAM_LINE = re.compile(r"^-1\s+Program:\s*(\S+)\s+Acquisition:\s*(\d+)\s*$")
CHANNEL_LINE = re.compile(
    r"^-2\s+(\d+)\s+(.+?)\s{2,}(\S+)\s+(-?\d+(?:\.\d+)?)\s*$"
)
PERIOD_LINE = re.compile(r"^-3\s+(-?\d+(?:\.\d+)?)\s*$")
COUNTS_LINE = re.compile(r"^-4\s+(\d+)\s+(\d+)\s*$")
INTERVAL_LINE = re.compile(r"^0\s+Interval\s+#(\d+)\s*$", re.IGNORECASE)
DATA_LINE = re.compile(
    r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s*$"
)

REQUIRED_CHANNELS = {
    1: ("Force", "Kg"),
    2: ("Stroke", "cm"),
    3: ("Control Temperature", "Celsius"),
}


def _decode_source(content: bytes) -> str:
    for encoding in ("utf-8-sig", "ascii", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("热模拟文件编码无法识别。")


def _safe_source_name(file_name: str) -> str:
    name = Path(str(file_name)).name
    if name != file_name or not SOURCE_NAME.fullmatch(name):
        raise ValueError("文件名不符合热模拟导出格式（例如 ZHT.A75）。")
    return name


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def parse_thermal_simulation_file(file_name: str, content: bytes) -> dict[str, Any]:
    """Parse one instrument export and return source-preserving rows plus QC."""
    name = _safe_source_name(file_name)
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ValueError("热模拟文件为空或超过 5 MiB。")
    text = _decode_source(content)
    source_sha256 = hashlib.sha256(content).hexdigest()
    program = ""
    acquisition_id = ""
    period_value: float | None = None
    declared_intervals: int | None = None
    declared_points: int | None = None
    channels: dict[int, dict[str, Any]] = {}
    current_interval: int | None = None
    points: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if match := PROGRAM_LINE.match(line):
            program, acquisition_id = match.groups()
            continue
        if match := CHANNEL_LINE.match(line):
            index, channel_name, unit, offset = match.groups()
            channels[int(index)] = {
                "index": int(index), "name": channel_name.strip(), "unit": unit,
                "time_offset_raw": float(offset),
            }
            continue
        if match := PERIOD_LINE.match(line):
            period_value = float(match.group(1))
            continue
        if match := COUNTS_LINE.match(line):
            declared_intervals, declared_points = (int(value) for value in match.groups())
            continue
        if match := INTERVAL_LINE.match(line):
            current_interval = int(match.group(1))
            continue
        if match := DATA_LINE.match(line):
            if current_interval is None:
                _append_unique(errors, f"第{line_number}行数据没有所属 interval")
                continue
            point_index, time_value, force, stroke, temperature = match.groups()
            values = [float(time_value), float(force), float(stroke), float(temperature)]
            if not all(math.isfinite(value) for value in values):
                _append_unique(errors, f"第{line_number}行存在非有限数值")
                continue
            points.append({
                "interval_index": current_interval,
                "point_index": int(point_index),
                "time_value_raw": values[0],
                "force_value_raw": values[1],
                "stroke_value_raw": values[2],
                "control_temperature_raw": values[3],
            })

    if not program or not acquisition_id:
        errors.append("缺少 Program/Acquisition 文件头。")
    suffix_acquisition = re.search(r"\.A(\d+)$", name, re.IGNORECASE)
    if suffix_acquisition and acquisition_id and suffix_acquisition.group(1) != acquisition_id:
        errors.append("文件名 acquisition 与文件头不一致。")
    if period_value is None or period_value <= 0:
        errors.append("Period 缺失或不是正数。")
    if declared_intervals is None or declared_intervals <= 0:
        errors.append("Intervals 缺失或不是正整数。")
    if declared_points is None or declared_points <= 0:
        errors.append("Points Per Channel 缺失或不是正整数。")
    if not points:
        errors.append("没有解析到曲线数据点。")

    for index, expected in REQUIRED_CHANNELS.items():
        actual = channels.get(index)
        if actual is None:
            errors.append(f"缺少 Channel {index}: {expected[0]}。")
        elif (actual["name"], actual["unit"]) != expected:
            errors.append(
                f"Channel {index} 实际为 {actual['name']} [{actual['unit']}]，"
                f"与所需 {expected[0]} [{expected[1]}] 不一致。"
            )

    interval_ids = sorted({row["interval_index"] for row in points})
    if declared_intervals is not None and len(interval_ids) != declared_intervals:
        errors.append(f"声明 {declared_intervals} 个 interval，实际解析到 {len(interval_ids)} 个。")
    if declared_points is not None and len(points) != declared_points:
        errors.append(f"声明 {declared_points} 个点，实际解析到 {len(points)} 个。")

    intervals: list[dict[str, Any]] = []
    for interval_id in interval_ids:
        rows = [row for row in points if row["interval_index"] == interval_id]
        indices = [row["point_index"] for row in rows]
        expected_indices = list(range(len(rows)))
        if indices != expected_indices:
            errors.append(f"Interval {interval_id} 点号不连续或顺序异常。")
        times = [row["time_value_raw"] for row in rows]
        if any(second <= first for first, second in zip(times, times[1:])):
            errors.append(f"Interval {interval_id} 时间列不是严格递增。")
        temperatures = [row["control_temperature_raw"] for row in rows]
        intervals.append({
            "interval_index": interval_id,
            "point_count": len(rows),
            "first_time_raw": times[0],
            "last_time_raw": times[-1],
            "temperature_mean_c": sum(temperatures) / len(temperatures),
            "temperature_min_c": min(temperatures),
            "temperature_max_c": max(temperatures),
        })
    all_times = [row["time_value_raw"] for row in points]
    if any(second <= first for first, second in zip(all_times, all_times[1:])):
        errors.append("跨 interval 的时间列不是严格递增。")

    measured_gap_raw: float | None = None
    if len(intervals) == 2:
        measured_gap_raw = intervals[1]["first_time_raw"] - intervals[0]["last_time_raw"]
        if measured_gap_raw <= 0:
            errors.append("两个 interval 之间的时间差不是正数。")
    elif len(intervals) > 2:
        warnings.append("存在两个以上 interval；当前只保留逐段信息，不生成单一道次间隔摘要。")

    return {
        "schema_version": "1.0",
        "file_name": name,
        "source_sha256": source_sha256,
        "source_size_bytes": len(content),
        "program": program,
        "acquisition_id": acquisition_id,
        "period_value_raw": period_value,
        "declared_interval_count": declared_intervals,
        "declared_point_count": declared_points,
        "channels": [channels[index] for index in sorted(channels)],
        "intervals": intervals,
        "measured_interval_gap_raw": measured_gap_raw,
        "points": points,
        "point_count": len(points),
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "status": "blocked" if errors else "parsed",
    }


def inspect_thermal_simulation_batch(files: Mapping[str, bytes]) -> dict[str, Any]:
    """Parse a non-recursive in-memory batch and check acquisition uniqueness."""
    if not files or len(files) > MAX_BATCH_FILES:
        raise ValueError(f"请选择 1–{MAX_BATCH_FILES} 个热模拟文件。")
    if sum(len(content) for content in files.values()) > MAX_BATCH_BYTES:
        raise ValueError("热模拟批次总大小超过 200 MiB。")
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for name in sorted(files, key=str.casefold):
        try:
            item = parse_thermal_simulation_file(name, files[name])
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue
        parsed.append(item)
        errors.extend(f"{name}: {value}" for value in item["errors"])
        warnings.extend(f"{name}: {value}" for value in item["warnings"])
    acquisitions = [item["acquisition_id"] for item in parsed if item["acquisition_id"]]
    duplicates = sorted({value for value in acquisitions if acquisitions.count(value) > 1}, key=int)
    if duplicates:
        errors.append("批次 acquisition 重复：" + ", ".join(duplicates))
    digest_payload = [{"file_name": item["file_name"], "sha256": item["source_sha256"]} for item in parsed]
    batch_sha256 = hashlib.sha256(json.dumps(
        digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {
        "schema_version": "1.0",
        "batch_sha256": batch_sha256,
        "file_count": len(parsed),
        "point_count": sum(item["point_count"] for item in parsed),
        "files": parsed,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "status": "blocked" if errors else "parsed",
    }


def read_thermal_simulation_folder(folder: Path) -> dict[str, bytes]:
    """Read supported files from one explicitly selected folder, never recursively."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("所选热模拟文件夹不存在。")
    result: dict[str, bytes] = {}
    for path in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
        if path.is_symlink() or not path.is_file() or not SOURCE_NAME.fullmatch(path.name):
            continue
        result[path.name] = path.read_bytes()
    if not result:
        raise ValueError("文件夹中没有识别到类似 ZHT.A75 的热模拟导出文件。")
    return result


def read_plan_csv(content: bytes) -> list[dict[str, str]]:
    """Read an explicit plan mapping; no OCR or ID invention occurs here."""
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ValueError("计划表 CSV 为空或超过 5 MiB。")
    text = _decode_source(content)
    reader = csv.DictReader(io.StringIO(text))
    required = {
        "acquisition_id", "sample_id", "specimen_id", "test_type",
        "planned_temperature_c", "planned_interpass_time_s", "strain_1",
        "strain_2", "strain_rate_s", "plan_source_status",
    }
    columns = {str(value or "").strip() for value in (reader.fieldnames or [])}
    missing = sorted(required - columns)
    if missing:
        raise ValueError("计划表缺少列：" + ", ".join(missing))
    rows = [{str(key).strip(): str(value or "").strip() for key, value in row.items() if key}
            for row in reader]
    return [row for row in rows if any(row.values())]


def _finite_optional(row: Mapping[str, str], field: str, errors: list[str], acquisition: str) -> float | None:
    value = str(row.get(field, "")).strip()
    if not value:
        return None
    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError
        return parsed
    except ValueError:
        errors.append(f"A{acquisition} 计划字段 {field} 不是有限数值。")
        return None


def build_thermal_standardization_preview(
    batch: Mapping[str, Any],
    plan_rows: Iterable[Mapping[str, str]] = (),
    *,
    time_unit_confirmed: bool = False,
    force_unit_interpretation: str = "",
    specimen_mapping_confirmed: bool = False,
    accept_instrument_over_plan: bool = False,
    temperature_tolerance_c: float = 20.0,
    interval_tolerance_s: float = 0.02,
) -> dict[str, Any]:
    """Build normalized run/point previews and explicit human-decision gates."""
    errors = list(batch.get("errors", []))
    warnings = list(batch.get("warnings", []))
    decisions_needed: list[str] = []
    plan_by_acquisition: dict[str, dict[str, str]] = {}
    for source in plan_rows:
        row = {str(key): str(value).strip() for key, value in source.items()}
        acquisition = row.get("acquisition_id", "")
        if not acquisition:
            errors.append("计划表存在空 acquisition_id。")
            continue
        if acquisition in plan_by_acquisition:
            errors.append(f"计划表 acquisition_id 重复：{acquisition}")
        plan_by_acquisition[acquisition] = row

    if not time_unit_confirmed:
        decisions_needed.append("确认仪器 Time 与 Period 的数值单位是否为 s。")
    if force_unit_interpretation not in {"", "instrument_kg_force", "kgf"}:
        errors.append("Force [Kg] 只支持保留为仪器 kg 力值，或经仪器依据确认解释为 kgf。")
    if not force_unit_interpretation:
        decisions_needed.append("确认仪器 Force [Kg] 的物理含义；未确认前 force_n 保持空白。")
    if plan_by_acquisition and not specimen_mapping_confirmed:
        decisions_needed.append("核对计划表中的 sample_id、specimen_id 与 acquisition 对应关系。")
    if not plan_by_acquisition:
        decisions_needed.append("提供或录入 acquisition 与真实 sample_id/specimen_id 的计划表。")

    run_rows: list[dict[str, str]] = []
    point_rows: list[dict[str, str]] = []
    comparisons: list[dict[str, Any]] = []
    found_acquisitions: set[str] = set()
    for item in batch.get("files", []):
        acquisition = str(item.get("acquisition_id", ""))
        found_acquisitions.add(acquisition)
        plan = plan_by_acquisition.get(acquisition, {})
        planned_temperature = _finite_optional(plan, "planned_temperature_c", errors, acquisition)
        planned_interval = _finite_optional(plan, "planned_interpass_time_s", errors, acquisition)
        measured_gap = item.get("measured_interval_gap_raw")
        interval_summaries = list(item.get("intervals", []))
        test_type = plan.get("test_type", "").strip().upper()
        # A PAG baseline export contains the full heating/cooling history, so its
        # whole-curve mean is not the planned peak temperature.  A DH export is
        # captured around deformation and is compared using interval-1 mean.
        if test_type == "PAG" and interval_summaries:
            measured_temperature = max(value["temperature_max_c"] for value in interval_summaries)
            temperature_metric = "curve_max"
        elif test_type == "DH" and interval_summaries:
            measured_temperature = interval_summaries[0]["temperature_mean_c"]
            temperature_metric = "interval_1_mean"
        else:
            measured_temperature = None
            temperature_metric = "not_compared"
        temperature_difference = (
            measured_temperature - planned_temperature
            if measured_temperature is not None and planned_temperature is not None else None
        )
        interval_difference_raw = (
            measured_gap - planned_interval
            if measured_gap is not None and planned_interval is not None else None
        )
        interval_difference = interval_difference_raw if time_unit_confirmed else None
        comparison_status = "not_compared"
        comparison_issues: list[str] = []
        if plan:
            comparison_status = "matched"
            if temperature_difference is not None and abs(temperature_difference) > temperature_tolerance_c:
                comparison_status = "needs_human"
                comparison_issues.append(
                    f"计划温度 {planned_temperature:g} °C，曲线分段均温约 {measured_temperature:.1f} °C"
                )
            if interval_difference_raw is not None and abs(interval_difference_raw) > interval_tolerance_s:
                comparison_status = "needs_human"
                if time_unit_confirmed:
                    comparison_issues.append(
                        f"计划道次间隔 {planned_interval:g} s，文件两段边界差约 {measured_gap:.4f} s"
                    )
                else:
                    comparison_issues.append(
                        f"计划道次间隔 {planned_interval:g} s，文件两段边界差原值约 {measured_gap:.4f}；"
                        "须确认时间单位和记录对应关系"
                    )
            if not plan.get("sample_id") or not plan.get("specimen_id"):
                comparison_status = "needs_human"
                comparison_issues.append("sample_id 或 specimen_id 为空")
        if comparison_issues:
            if accept_instrument_over_plan and specimen_mapping_confirmed:
                comparison_status = "deviation_accepted_actual_instrument"
            else:
                decisions_needed.append(f"A{acquisition}: " + "；".join(comparison_issues))

        experiment_run_id = f"EXP-{item.get('program', 'THERMAL')}-A{acquisition}"
        offsets = {value["name"]: value["time_offset_raw"] for value in item.get("channels", [])}
        run_rows.append({
            "sample_id": plan.get("sample_id", ""),
            "specimen_id": plan.get("specimen_id", ""),
            "experiment_run_id": experiment_run_id,
            "program": str(item.get("program", "")),
            "acquisition_id": acquisition,
            "test_type": plan.get("test_type", ""),
            "planned_temperature_c": plan.get("planned_temperature_c", ""),
            "planned_interpass_time_s": plan.get("planned_interpass_time_s", ""),
            "strain_1": plan.get("strain_1", ""),
            "strain_2": plan.get("strain_2", ""),
            "strain_rate_s": plan.get("strain_rate_s", ""),
            "specimen_diameter_mm": plan.get("specimen_diameter_mm", ""),
            "specimen_height_mm": plan.get("specimen_height_mm", ""),
            "interval_count": str(item.get("declared_interval_count", "")),
            "point_count": str(item.get("point_count", "")),
            "period_value_raw": format(item["period_value_raw"], ".15g"),
            "sampling_period_s": format(item["period_value_raw"], ".15g") if time_unit_confirmed else "",
            "measured_interval_gap_raw": format(measured_gap, ".15g") if measured_gap is not None else "",
            "measured_interval_gap_s": format(measured_gap, ".15g") if time_unit_confirmed and measured_gap is not None else "",
            "measured_reference_temperature_c": (
                format(measured_temperature, ".15g") if measured_temperature is not None else ""
            ),
            "temperature_measurement_metric": temperature_metric,
            "effective_temperature_c": (
                format(measured_temperature, ".15g")
                if accept_instrument_over_plan and measured_temperature is not None
                else plan.get("planned_temperature_c", "")
            ),
            "effective_interpass_time_s": (
                format(measured_gap, ".15g")
                if accept_instrument_over_plan and time_unit_confirmed and measured_gap is not None
                else plan.get("planned_interpass_time_s", "")
            ),
            "time_unit_interpretation": "s" if time_unit_confirmed else "",
            "force_unit_interpretation": force_unit_interpretation,
            "force_time_offset_raw": format(offsets["Force"], ".15g") if "Force" in offsets else "",
            "stroke_time_offset_raw": format(offsets["Stroke"], ".15g") if "Stroke" in offsets else "",
            "temperature_time_offset_raw": (
                format(offsets["Control Temperature"], ".15g")
                if "Control Temperature" in offsets else ""
            ),
            "source_file_sha256": str(item.get("source_sha256", "")),
            "plan_source_status": plan.get("plan_source_status", ""),
            "source_status": "instrument_export",
            "review_status": comparison_status,
            "notes": "；".join(comparison_issues),
        })
        for point in item.get("points", []):
            force_raw = float(point["force_value_raw"])
            point_rows.append({
                "sample_id": plan.get("sample_id", ""),
                "specimen_id": plan.get("specimen_id", ""),
                "experiment_run_id": experiment_run_id,
                "interval_index": str(point["interval_index"]),
                "point_index": str(point["point_index"]),
                "time_value_raw": format(point["time_value_raw"], ".15g"),
                "time_s": format(point["time_value_raw"], ".15g") if time_unit_confirmed else "",
                "force_value_raw": format(force_raw, ".15g"),
                "force_unit_raw": "Kg",
                "force_n": format(force_raw * 9.80665, ".15g") if force_unit_interpretation == "kgf" else "",
                "stroke_value_raw": format(float(point["stroke_value_raw"]), ".15g"),
                "stroke_unit_raw": "cm",
                "stroke_mm": format(float(point["stroke_value_raw"]) * 10.0, ".15g"),
                "control_temperature_raw": format(float(point["control_temperature_raw"]), ".15g"),
                "control_temperature_unit_raw": "Celsius",
                "control_temperature_c": format(float(point["control_temperature_raw"]), ".15g"),
                "source_status": "instrument_export",
            })
        comparisons.append({
            "acquisition_id": acquisition,
            "sample_id": plan.get("sample_id", ""),
            "specimen_id": plan.get("specimen_id", ""),
            "planned_temperature_c": planned_temperature,
            "measured_temperature_mean_c": round(measured_temperature, 3) if measured_temperature is not None else None,
            "temperature_metric": temperature_metric,
            "temperature_difference_c": round(temperature_difference, 3) if temperature_difference is not None else None,
            "planned_interpass_time_s": planned_interval,
            "measured_interval_gap_raw": round(measured_gap, 6) if measured_gap is not None else None,
            "measured_interval_gap_s": round(measured_gap, 6) if time_unit_confirmed and measured_gap is not None else None,
            "interval_difference_s": round(interval_difference, 6) if interval_difference is not None else None,
            "status": comparison_status,
            "issues": comparison_issues,
        })

    unused_plan = sorted(set(plan_by_acquisition) - found_acquisitions, key=lambda value: int(value) if value.isdigit() else value)
    if unused_plan:
        warnings.append("计划表中这些 acquisition 没有对应文件：" + ", ".join(unused_plan))
    acceptable_reviews = {"matched", "deviation_accepted_actual_instrument"}
    ready = not errors and not decisions_needed and all(
        row["review_status"] in acceptable_reviews for row in run_rows
    )
    result = {
        "schema_version": "1.0",
        "batch_sha256": batch.get("batch_sha256", ""),
        "status": "ready" if ready else ("blocked" if errors else "needs_human"),
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "decisions_needed": list(dict.fromkeys(decisions_needed)),
        "run_rows": run_rows,
        "point_rows": point_rows,
        "comparisons": comparisons,
        "file_count": len(run_rows),
        "point_count": len(point_rows),
        "human_decisions": {
            "time_unit": "s" if time_unit_confirmed else "unconfirmed",
            "force_unit_interpretation": force_unit_interpretation or "unconfirmed",
            "specimen_mapping_confirmed": specimen_mapping_confirmed,
            "instrument_data_overrides_conflicting_plan": accept_instrument_over_plan,
        },
        "transformations": [
            {"source": "Stroke [cm]", "target": "stroke_mm", "formula": "cm × 10"},
            {"source": "Control Temperature [Celsius]", "target": "control_temperature_c", "formula": "identity"},
            {"source": "Time/Period", "target": "time_s/sampling_period_s", "formula": "identity after unit confirmation"},
            {"source": "Force [Kg]", "target": "force_n", "formula": "kgf × 9.80665 after interpretation confirmation"},
        ],
    }
    result["preview_sha256"] = hashlib.sha256(json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return result


def _rows_csv_bytes(rows: list[dict[str, str]]) -> bytes:
    if not rows:
        raise ValueError("标准化候选没有记录。")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_thermal_intake_reports(
    preview: Mapping[str, Any], *, project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate both normalized tables against the shared research contract."""
    from steelai.data_intake import validate_intake_csv
    from steelai.paths import ROOT

    if preview.get("status") != "ready" or preview.get("errors") or preview.get("decisions_needed"):
        raise ValueError("热模拟预览尚未完成全部人工确认，不能生成正式入库报告。")
    root = project_root or ROOT
    reports = [
        validate_intake_csv("thermal_simulation_runs", _rows_csv_bytes(list(preview.get("run_rows", []))),
                            project_root=root),
        validate_intake_csv("thermal_simulation_points", _rows_csv_bytes(list(preview.get("point_rows", []))),
                            project_root=root),
    ]
    problems = [f"{report['table_name']}: {problem}" for report in reports for problem in report["errors"]]
    if problems:
        raise ValueError("；".join(problems))
    return reports


def commit_thermal_preview_governed(
    preview: Mapping[str, Any], *, reviewer_id: str, rationale: str, confirmed: bool,
    project_root: Path | None = None,
    workflow_identity: WorkflowIdentity | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Transactionally append run/point tables and publish one governance receipt."""
    from steelai.data_intake_governance import commit_intake_batch_governed
    from steelai.paths import ROOT

    root = project_root or ROOT
    reports = build_thermal_intake_reports(preview, project_root=root)
    preview_digest = str(preview.get("preview_sha256", ""))
    if len(preview_digest) != 64:
        raise ValueError("热模拟预览缺少有效摘要，请重新预检。")
    table_summary = [{
        "table_name": report["table_name"], "row_count": report["row_count"],
        "destination": report["destination"], "content_sha256": report["content_sha256"],
    } for report in reports]
    batch_report = {
        "schema_version": "1.0",
        "table_name": "thermal_simulation_batch",
        "destination": "data/processed/thermal_simulation_runs.csv + thermal_simulation_points.csv",
        "content_sha256": preview_digest,
        "columns": ["batch_sha256", "run_count", "point_count", "source_status"],
        "rows": [{
            "batch_sha256": str(preview.get("batch_sha256", "")),
            "run_count": str(preview.get("file_count", 0)),
            "point_count": str(preview.get("point_count", 0)),
            "source_status": "instrument_export",
        }],
        "row_count": 1,
        "status": "ready",
        "errors": [],
        "warnings": [],
    }
    evidence = {
        "schema_version": "1.0",
        "preview_sha256": preview_digest,
        "batch_sha256": preview.get("batch_sha256"),
        "human_decisions": dict(preview.get("human_decisions", {})),
        "transformations": list(preview.get("transformations", [])),
        "comparisons": list(preview.get("comparisons", [])),
        "tables": table_summary,
        "source_files_copied": False,
    }
    return commit_intake_batch_governed(
        reports,
        batch_report,
        reviewer_id=reviewer_id,
        rationale=rationale,
        confirmed=confirmed,
        source_id="THERMAL-" + str(preview.get("batch_sha256", ""))[:20].upper(),
        source_digest=str(preview.get("batch_sha256", "")),
        project_root=root,
        extra_artifacts={"thermal_standardization_record.json": evidence},
        workflow_identity=workflow_identity,
    )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if columns:
            writer.writeheader()
            writer.writerows(rows)


def save_thermal_preview_package(preview: Mapping[str, Any], output_root: Path) -> dict[str, Path]:
    """Save an ignored, non-committed review package without source-file copies."""
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    package = Path(output_root) / f"TSI-{stamp}-{str(preview.get('batch_sha256', ''))[:8].upper()}"
    package.mkdir(parents=True, exist_ok=False)
    manifest = {
        key: value for key, value in preview.items() if key not in {"run_rows", "point_rows"}
    }
    manifest["created_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    manifest["commit_status"] = "not_committed"
    manifest_path = package / "review_manifest.json"
    runs_path = package / "thermal_simulation_runs_preview.csv"
    points_path = package / "thermal_simulation_points_preview.csv"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(runs_path, list(preview.get("run_rows", [])))
    _write_csv(points_path, list(preview.get("point_rows", [])))
    return {"package": package, "manifest": manifest_path, "runs": runs_path, "points": points_path}
