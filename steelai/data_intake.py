from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from steelai.paths import OUTPUTS, ROOT
from steelai.research_data_contract import CONTRACT_PATH, load_research_contract


ID_POLICY_PATH = ROOT / "config" / "research_id_policy_v1.0.json"
INTAKE_OUTPUTS = OUTPUTS / "data_intake"
ID_FIELDS = {
    "material_id", "heat_id", "batch_id", "sample_id", "specimen_id",
    "field_id", "observation_id", "run_id", "experiment_run_id", "step_id",
}
STANDARD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def load_id_policy(path: Path = ID_POLICY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _allowed_columns(spec: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    for group in ("essential_fields", "recommended_fields", "optional_fields", "numeric_fields"):
        for field in spec.get(group, []):
            if field not in ordered:
                ordered.append(field)
    return ordered


def template_columns(table_name: str, contract_path: Path = CONTRACT_PATH) -> list[str]:
    contract = load_research_contract(contract_path)
    spec = contract.get("tables", {}).get(table_name)
    if not spec:
        raise KeyError(f"Unknown intake table: {table_name}")
    return _allowed_columns(spec)


def template_csv_bytes(table_name: str, contract_path: Path = CONTRACT_PATH) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerow(template_columns(table_name, contract_path))
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV编码无法识别，请另存为UTF-8 CSV。")


def _primary_key(spec: dict[str, Any], table_name: str) -> list[str]:
    configured = list(spec.get("primary_key", []))
    if configured:
        return configured
    return ["sample_id"] if table_name in {"samples", "composition", "process", "microstructure", "properties"} else []


def _key_text(row: dict[str, str], fields: list[str]) -> str:
    return " | ".join(str(row.get(field, "")).strip() for field in fields)


def _read_existing(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def validate_intake_csv(
    table_name: str,
    content: bytes,
    *,
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
    id_policy_path: Path = ID_POLICY_PATH,
) -> dict[str, Any]:
    contract = load_research_contract(contract_path)
    policy = load_id_policy(id_policy_path)
    spec = contract.get("tables", {}).get(table_name)
    if not spec:
        raise KeyError(f"Unknown intake table: {table_name}")

    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = _decode_csv(content)
    except ValueError as exc:
        return {
            "table_name": table_name, "status": "blocked", "errors": [str(exc)], "warnings": [],
            "columns": [], "rows": [], "row_count": 0, "content_sha256": hashlib.sha256(content).hexdigest(),
        }

    reader = csv.DictReader(io.StringIO(text))
    raw_columns = [str(item or "").strip() for item in (reader.fieldnames or [])]
    if not raw_columns:
        errors.append("CSV没有表头。")
    if len(raw_columns) != len(set(raw_columns)):
        errors.append("CSV存在重复列名。")

    aliases = policy.get("column_aliases", {})
    columns = [aliases.get(column, column) for column in raw_columns]
    if len(columns) != len(set(columns)):
        errors.append("列名映射后发生重复，请检查中英文列名。")

    allowed = set(_allowed_columns(spec))
    unknown = sorted(set(columns) - allowed)
    if unknown:
        errors.append("存在未登记列（可能是拼写错误）：" + ", ".join(unknown))
    missing_columns = [field for field in spec.get("essential_fields", []) if field not in columns]
    if missing_columns:
        errors.append("缺少必要列：" + ", ".join(missing_columns))

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        if None in raw_row and any(str(value).strip() for value in raw_row[None]):
            errors.append("CSV存在超出表头的单元格；请修正后重新导入，系统不会丢弃这些值。")
        normalized = {
            aliases.get(str(key or "").strip(), str(key or "").strip()): str(value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        if any(value != "" for value in normalized.values()):
            rows.append(normalized)
    if not rows:
        errors.append("CSV只有表头，没有可导入记录。")

    numeric_fields = set(spec.get("numeric_fields", []))
    essential = list(spec.get("essential_fields", []))
    allowed_units = set(spec.get("allowed_units", []))
    allowed_types = set(spec.get("allowed_measurement_types", []))
    scoped_samples = set(contract.get("scope", {}).get("included_samples", []))
    sample_registry = project_root / str(contract.get("tables", {}).get("samples", {}).get("path", ""))
    _, registered_sample_rows = _read_existing(sample_registry)
    registered_samples = {row.get("sample_id", "") for row in registered_sample_rows if row.get("sample_id")}
    provisional = str(policy.get("provisional_status", "provisional_unverified"))

    for row_number, row in enumerate(rows, start=2):
        missing_values = [field for field in essential if row.get(field, "") == ""]
        if missing_values:
            errors.append(f"第{row_number}行必要值为空：{', '.join(missing_values)}")
        for field in numeric_fields:
            value = row.get(field, "")
            if value == "":
                continue
            try:
                parsed = float(value)
                if not math.isfinite(parsed):
                    raise ValueError
            except ValueError:
                errors.append(f"第{row_number}行 {field} 不是有限数值")
        for field in ID_FIELDS.intersection(row):
            value = row.get(field, "")
            if value and not STANDARD_ID.fullmatch(value):
                warnings.append(f"第{row_number}行 {field} 不符合建议的英文编号格式")
        sample_id = row.get("sample_id", "")
        # The frozen B/R samples stay in scope, while an explicitly reviewed
        # samples.csv intake is the only route for registering a new sample.
        # Other tables must reference either the frozen scope or that registry.
        if table_name != "samples" and sample_id and sample_id not in scoped_samples | registered_samples:
            errors.append(f"第{row_number}行样品 {sample_id} 超出当前B/R契约范围或尚未登记")
        if allowed_units and row.get("unit") and row["unit"] not in allowed_units:
            errors.append(f"第{row_number}行单位 {row['unit']} 未登记；在人工确认正确单位前不得标准化或统计")
        if allowed_types and row.get("measurement_type") not in allowed_types:
            errors.append(f"第{row_number}行 measurement_type 不受支持：{row.get('measurement_type', '')}")
        if row.get("source_status") == provisional:
            warnings.append(f"第{row_number}行仍为临时编号/未核验来源")

    destination = project_root / str(spec.get("path", ""))
    existing_columns, existing_rows = _read_existing(destination)
    # Shared by manual CSV and SteelData; also checked inside the commit lock.
    origin_pattern = re.compile(r"steeldata-origin:([0-9a-f]{64})")
    origins = [origin for row in rows for origin in origin_pattern.findall(row.get("notes", ""))]
    existing_origins = {origin for row in existing_rows
                        for origin in origin_pattern.findall(row.get("notes", ""))}
    if len(origins) != len(set(origins)) or set(origins) & existing_origins:
        errors.append("同一 SteelData 来源单元格重复或已接入；不能通过更改 sample_id 或重跑绕过检查。")
    primary_key = _primary_key(spec, table_name)
    if primary_key:
        uploaded_keys = [_key_text(row, primary_key) for row in rows]
        duplicates = sorted({key for key in uploaded_keys if key and uploaded_keys.count(key) > 1})
        if duplicates:
            errors.append("本次文件主键重复：" + ", ".join(duplicates))
        existing_keys = {_key_text(row, primary_key) for row in existing_rows}
        conflicts = sorted({key for key in uploaded_keys if key and key in existing_keys})
        if conflicts:
            errors.append("与processed现有记录冲突（系统不会覆盖）：" + ", ".join(conflicts))

    if table_name != "samples":
        sample_path = project_root / contract["tables"]["samples"]["path"]
        _, sample_rows = _read_existing(sample_path)
        registered = {row.get("sample_id", "") for row in sample_rows}
        orphans = sorted({row.get("sample_id", "") for row in rows if row.get("sample_id", "") not in registered})
        if orphans:
            errors.append("样品尚未在samples.csv登记：" + ", ".join(orphans))

    return {
        "schema_version": "1.0",
        "contract_id": contract.get("contract_id"),
        "policy_id": policy.get("policy_id"),
        "table_name": table_name,
        "status": "ready" if not errors else "blocked",
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "primary_key": primary_key,
        "destination": str(spec.get("path", "")),
        "existing_row_count": len(existing_rows),
        "existing_columns": existing_columns,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "policy_boundaries": list(policy.get("principles", [])),
    }


def _safe_report(report: dict[str, Any], *, include_rows: bool) -> dict[str, Any]:
    result = {key: value for key, value in report.items() if key not in {"rows", "existing_columns"}}
    if include_rows:
        result["rows"] = report.get("rows", [])
    return result


def save_intake_package(report: dict[str, Any], *, output_root: Path = INTAKE_OUTPUTS) -> dict[str, Any]:
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    intake_id = f"DI-{stamp}-{uuid.uuid4().hex[:6]}"
    package = output_root / intake_id
    package.mkdir(parents=True, exist_ok=False)
    manifest = _safe_report(report, include_rows=False)
    manifest.update({"intake_id": intake_id, "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")})
    (package / "validation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    normalized_path = None
    if report.get("status") == "ready":
        normalized_path = package / "normalized_staging.csv"
        columns = list(report.get("columns", []))
        with normalized_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(report.get("rows", []))
    return {
        "intake_id": intake_id,
        "package": package,
        "manifest": package / "validation_manifest.json",
        "normalized_staging": normalized_path,
    }


def finalize_intake_package(package_info: dict[str, Any], commit_result: dict[str, Any]) -> Path:
    package = Path(package_info["package"])
    path = package / "commit_result.json"
    payload = {
        **commit_result,
        "intake_id": package_info["intake_id"],
        "committed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def commit_intake(
    report: dict[str, Any], *, project_root: Path = ROOT,
    contract_path: Path = CONTRACT_PATH, id_policy_path: Path = ID_POLICY_PATH,
) -> dict[str, Any]:
    """Both import routes use one locked, freshly validated append gate.

    The lock coordinates this application's writers, not arbitrary external editors.
    A preview from an earlier rerun is never itself authorization to bypass validation.
    """
    if report.get("status") != "ready":
        raise ValueError("Blocked intake cannot be committed.")
    spec = load_research_contract(contract_path)["tables"].get(report.get("table_name"))
    if not spec or report.get("destination") != spec.get("path"):
        raise ValueError("Destination does not match the registered data contract.")
    processed = (project_root / "data" / "processed").resolve()
    destination = (project_root / str(spec["path"])).resolve()
    if not processed.is_relative_to(project_root.resolve()) or not destination.is_relative_to(processed):
        raise ValueError("Destination is outside data/processed.")
    processed.mkdir(parents=True, exist_ok=True)
    lock = processed / ".intake.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("另一个导入正在提交。请稍后重新预检；不要重复点击。") from exc
    try:
        with handle:
            handle.write("SteelAI intake in progress\n")
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=report["columns"])
        writer.writeheader()
        writer.writerows(report["rows"])
        fresh = validate_intake_csv(
            report["table_name"], buffer.getvalue().encode("utf-8"),
            project_root=project_root, contract_path=contract_path, id_policy_path=id_policy_path,
        )
        if fresh["status"] != "ready":
            raise ValueError("提交前重新校验失败：" + "；".join(fresh["errors"]))
        fresh["content_sha256"] = report.get("content_sha256")
        return _append_validated_intake(fresh, project_root=project_root)
    finally:
        lock.unlink(missing_ok=True)


def commit_intake_batch(
    reports: list[dict[str, Any]], *, project_root: Path = ROOT,
    contract_path: Path = CONTRACT_PATH, id_policy_path: Path = ID_POLICY_PATH,
) -> dict[str, Any]:
    """Append several validated contract tables under one lock with rollback.

    CSV cannot provide a database transaction across files.  This function
    therefore prepares every complete replacement first, keeps same-filesystem
    backups, and restores already replaced destinations if any replace fails.
    """
    if not reports:
        raise ValueError("At least one intake report is required.")
    table_names = [str(report.get("table_name", "")) for report in reports]
    if len(table_names) != len(set(table_names)):
        raise ValueError("Batch intake tables must be unique.")
    if any(report.get("status") != "ready" for report in reports):
        raise ValueError("Every batch intake report must be ready.")
    contract = load_research_contract(contract_path)
    processed = (project_root / "data" / "processed").resolve()
    processed.mkdir(parents=True, exist_ok=True)
    lock = processed / ".intake.lock"
    try:
        lock_handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("另一个导入正在提交。请稍后重新预检；不要重复点击。") from exc

    transaction_id = uuid.uuid4().hex
    prepared: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    try:
        with lock_handle:
            lock_handle.write("SteelAI batch intake in progress\n")
        for report in reports:
            table_name = str(report["table_name"])
            spec = contract.get("tables", {}).get(table_name)
            if not spec or report.get("destination") != spec.get("path"):
                raise ValueError(f"{table_name} destination does not match the registered contract.")
            destination = (project_root / str(spec["path"])).resolve()
            if not destination.is_relative_to(processed):
                raise ValueError(f"{table_name} destination is outside data/processed.")
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=report["columns"])
            writer.writeheader()
            writer.writerows(report["rows"])
            fresh = validate_intake_csv(
                table_name, buffer.getvalue().encode("utf-8"), project_root=project_root,
                contract_path=contract_path, id_policy_path=id_policy_path,
            )
            if fresh["status"] != "ready":
                raise ValueError(f"{table_name} 提交前重新校验失败：" + "；".join(fresh["errors"]))
            fresh["content_sha256"] = report.get("content_sha256")
            existing_columns, existing_rows = _read_existing(destination)
            columns = list(existing_columns)
            for column in fresh["columns"]:
                if column not in columns:
                    columns.append(column)
            if not columns:
                columns = list(fresh["columns"])
            all_rows = [*existing_rows, *fresh["rows"]]
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + f".{transaction_id}.tmp")
            backup = destination.with_name(destination.name + f".{transaction_id}.bak")
            with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                output = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                output.writeheader()
                output.writerows(all_rows)
            prepared.append({
                "report": fresh, "destination": destination, "temporary": temporary,
                "backup": backup, "existed": destination.exists(), "total_rows": len(all_rows),
            })

        fresh_by_table = {item["report"]["table_name"]: item["report"] for item in prepared}
        thermal_runs = fresh_by_table.get("thermal_simulation_runs")
        thermal_points = fresh_by_table.get("thermal_simulation_points")
        if thermal_runs is not None or thermal_points is not None:
            if thermal_runs is None or thermal_points is None:
                raise ValueError("热模拟运行表和曲线点表必须在同一批次提交。")
            run_lookup = {
                row["experiment_run_id"]: (row.get("sample_id", ""), row.get("specimen_id", ""))
                for row in thermal_runs["rows"]
            }
            point_counts: dict[str, int] = {}
            for row in thermal_points["rows"]:
                run_id = row.get("experiment_run_id", "")
                identity = run_lookup.get(run_id)
                if identity is None:
                    raise ValueError(f"曲线点引用了本批运行表中不存在的 experiment_run_id：{run_id}")
                if identity != (row.get("sample_id", ""), row.get("specimen_id", "")):
                    raise ValueError(f"曲线点与运行表的试样身份不一致：{run_id}")
                point_counts[run_id] = point_counts.get(run_id, 0) + 1
            for row in thermal_runs["rows"]:
                run_id = row["experiment_run_id"]
                if point_counts.get(run_id, 0) != int(float(row["point_count"])):
                    raise ValueError(f"运行表声明点数与曲线点表不一致：{run_id}")

        for item in prepared:
            destination = item["destination"]
            if item["existed"]:
                shutil.copy2(destination, item["backup"])
            item["temporary"].replace(destination)
            replaced.append(item)

        results = []
        for item in prepared:
            destination = item["destination"]
            results.append({
                "status": "committed", "table_name": item["report"]["table_name"],
                "rows_added": len(item["report"]["rows"]), "total_rows": item["total_rows"],
                "destination": str(destination.relative_to(project_root)).replace("\\", "/"),
                "content_sha256": item["report"].get("content_sha256"),
                "destination_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            })
        return {"status": "committed", "transaction_id": transaction_id, "tables": results}
    except Exception:
        for item in reversed(replaced):
            destination = item["destination"]
            backup = item["backup"]
            if backup.exists():
                backup.replace(destination)
            elif not item["existed"]:
                destination.unlink(missing_ok=True)
        raise
    finally:
        for item in prepared:
            item["temporary"].unlink(missing_ok=True)
            item["backup"].unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def _append_validated_intake(report: dict[str, Any], *, project_root: Path) -> dict[str, Any]:
    relative_destination = Path(str(report["destination"]))
    destination = (project_root / relative_destination).resolve()
    resolved_root = project_root.resolve()
    if resolved_root not in destination.parents:
        raise ValueError("Destination is outside the project root.")

    existing_columns, existing_rows = _read_existing(destination)
    upload_columns = list(report.get("columns", []))
    columns = list(existing_columns)
    for column in upload_columns:
        if column not in columns:
            columns.append(column)
    if not columns:
        columns = upload_columns
    rows = [*existing_rows, *report.get("rows", [])]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "status": "committed",
        "table_name": report["table_name"],
        "rows_added": len(report.get("rows", [])),
        "total_rows": len(rows),
        "destination": str(relative_destination).replace("\\", "/"),
        "content_sha256": report.get("content_sha256"),
    }
