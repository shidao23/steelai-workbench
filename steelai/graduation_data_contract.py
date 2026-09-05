from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from steelai.paths import ROOT


CONTRACT_PATH = ROOT / "config" / "graduation_data_contract_v1.0.json"
REQUIRED_ID_ROLES = {
    "material_id", "heat_id", "sample_id", "specimen_id", "report_id", "observation_id",
}
REQUIRED_DEFERRED_ROLES = {
    "curve_series", "curve_point", "image_asset", "image_field", "ebsd_pixel",
}


def load_graduation_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Graduation contract must be a JSON object.")
    return value


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _add(problems: list[str], message: str) -> None:
    if message not in problems:
        problems.append(message)


def _positive_integer(value: str) -> bool:
    try:
        return bool(value) and int(value) > 0 and str(int(value)) == value
    except (TypeError, ValueError):
        return False


def validate_graduation_contract(
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Validate the frozen contract and its public synthetic example graph."""
    contract = load_graduation_contract(contract_path)
    problems: list[str] = []
    root = project_root.resolve()

    if contract.get("contract_id") != "SteelAI-Graduation-Core-v1.0":
        _add(problems, "Unexpected graduation contract_id.")
    if contract.get("schema_version") != "1.0" or contract.get("status") != "frozen":
        _add(problems, "Graduation contract v1.0 must be frozen.")
    if set(contract.get("identity_roles", {})) != REQUIRED_ID_ROLES:
        _add(problems, "Identity roles must distinguish material, heat, sample, specimen, report and observation.")
    if not REQUIRED_DEFERRED_ROLES.issubset(contract.get("deferred_object_roles", {})):
        _add(problems, "Curve, image-field and EBSD-pixel roles must remain explicit non-specimen objects.")

    table_specs = contract.get("tables", {})
    expected_tables = {"materials", "heats", "samples", "specimens", "reports", "observations"}
    if set(table_specs) != expected_tables:
        _add(problems, "Graduation contract must define exactly the six frozen core tables.")

    rows_by_table: dict[str, list[dict[str, str]]] = {}
    table_counts: dict[str, int] = {}
    for table_name in sorted(expected_tables):
        spec = table_specs.get(table_name, {})
        relative = Path(str(spec.get("path", "")))
        path = (root / relative).resolve()
        if not str(relative) or not path.is_relative_to(root):
            _add(problems, f"{table_name}: example path escapes project root.")
            rows_by_table[table_name] = []
            table_counts[table_name] = 0
            continue
        columns, rows = _read_csv(path)
        rows_by_table[table_name] = rows
        table_counts[table_name] = len(rows)
        if not columns:
            _add(problems, f"{table_name}: public example table is missing or empty.")
            continue
        required = list(spec.get("required_fields", []))
        optional = list(spec.get("optional_fields", []))
        nullable = set(spec.get("nullable_fields", []))
        missing = [field for field in required if field not in columns]
        unknown = [field for field in columns if field not in required + optional]
        if missing:
            _add(problems, f"{table_name}: missing columns {missing}.")
        if unknown:
            _add(problems, f"{table_name}: unregistered columns {unknown}.")
        for row_number, row in enumerate(rows, 2):
            for field in required:
                if field not in nullable and not str(row.get(field, "")).strip():
                    _add(problems, f"{table_name} row {row_number}: required value {field} is blank.")
            for field, allowed in spec.get("allowed_values", {}).items():
                if row.get(field, "") not in set(allowed):
                    _add(problems, f"{table_name} row {row_number}: unsupported {field}={row.get(field, '')}.")
            for field in spec.get("numeric_fields", []):
                try:
                    value = float(row.get(field, ""))
                    if not math.isfinite(value):
                        raise ValueError
                except (TypeError, ValueError):
                    _add(problems, f"{table_name} row {row_number}: {field} is not a finite number.")
        primary_key = list(spec.get("primary_key", []))
        keys = [tuple(row.get(field, "").strip() for field in primary_key) for row in rows]
        if not primary_key or any(not all(key) for key in keys):
            _add(problems, f"{table_name}: primary key is missing or blank.")
        if len(keys) != len(set(keys)):
            _add(problems, f"{table_name}: duplicate primary key.")

    materials = {row.get("material_id", "") for row in rows_by_table.get("materials", [])}
    heats = {row.get("heat_id", "") for row in rows_by_table.get("heats", [])}
    samples = {row.get("sample_id", "") for row in rows_by_table.get("samples", [])}
    specimens = {row.get("specimen_id", "") for row in rows_by_table.get("specimens", [])}
    reports = {row.get("report_id", ""): row for row in rows_by_table.get("reports", [])}

    for row in rows_by_table.get("heats", []):
        if row.get("material_id") not in materials:
            _add(problems, f"heats: unregistered material_id {row.get('material_id', '')}.")
    for row in rows_by_table.get("samples", []):
        if row.get("material_id") not in materials:
            _add(problems, f"samples: unregistered material_id {row.get('material_id', '')}.")
        if row.get("heat_id") and row.get("heat_id") not in heats:
            _add(problems, f"samples: unregistered heat_id {row.get('heat_id', '')}.")
    for row in rows_by_table.get("specimens", []):
        if row.get("sample_id") not in samples:
            _add(problems, f"specimens: unregistered sample_id {row.get('sample_id', '')}.")
    for row_number, row in enumerate(rows_by_table.get("reports", []), 2):
        if not re.fullmatch(r"[0-9a-f]{64}", row.get("source_sha256", "")):
            _add(problems, f"reports row {row_number}: source_sha256 must be lowercase SHA-256.")

    rules = contract.get("observation_rules", {})
    units = rules.get("quantity_units", {})
    subject_rules = rules.get("subject_types", {})
    allowed_statuses = set(rules.get("allowed_source_statuses", []))
    for row_number, row in enumerate(rows_by_table.get("observations", []), 2):
        report = reports.get(row.get("report_id", ""))
        if report is None:
            _add(problems, f"observations row {row_number}: unregistered report_id {row.get('report_id', '')}.")
        quantity = row.get("quantity", "")
        if quantity not in units:
            _add(problems, f"observations row {row_number}: quantity {quantity} is outside graduation v1 scope.")
        elif row.get("unit") != units[quantity]:
            _add(problems, f"observations row {row_number}: {quantity} requires unit {units[quantity]}.")
        source_status = row.get("source_status", "")
        if source_status not in allowed_statuses:
            _add(problems, f"observations row {row_number}: unsupported source_status {source_status}.")
        if report and rules.get("source_status_must_match_report") and report.get("source_status") != source_status:
            _add(problems, f"observations row {row_number}: source_status does not match report.")

        subject_type = row.get("subject_type", "")
        rule = subject_rules.get(subject_type)
        if rule is None:
            _add(problems, f"observations row {row_number}: subject_type {subject_type} is not a v1 measurement subject.")
            continue
        registry = specimens if rule.get("registry") == "specimens" else samples
        if row.get("subject_id") not in registry:
            _add(problems, f"observations row {row_number}: {subject_type} subject_id is not registered.")
        if row.get("statistic_type") not in set(rule.get("allowed_statistics", [])):
            _add(problems, f"observations row {row_number}: statistic_type does not match {subject_type}.")
        replicate_count = row.get("replicate_count", "").strip()
        if rule.get("replicate_count") == "blank_or_one" and replicate_count not in {"", "1"}:
            _add(problems, f"observations row {row_number}: individual observation cannot claim multiple replicates.")
        if rule.get("replicate_count") == "positive_integer_required" and not _positive_integer(replicate_count):
            _add(problems, f"observations row {row_number}: summary requires a positive integer replicate_count.")

    migrations = contract.get("migration_rules", [])
    if len(migrations) < 5 or not all(item.get("source") and item.get("target") and item.get("rule") for item in migrations):
        _add(problems, "Migration rules must cover current tables, SteelData, curves and images.")
    versioning = contract.get("versioning", {})
    if not all(versioning.get(key) for key in ("major_change", "minor_change", "patch_change", "activation_rule")):
        _add(problems, "Versioning and activation rules are incomplete.")

    contract_sha256 = hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "contract_id": contract.get("contract_id"),
        "contract_sha256": contract_sha256,
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "table_counts": table_counts,
        "scope": contract.get("scope", {}),
        "deferred_object_roles": contract.get("deferred_object_roles", {}),
    }
