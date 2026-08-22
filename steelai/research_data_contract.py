from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from steelai.evidence_validation import validation_summary
from steelai.paths import ROOT


CONTRACT_PATH = ROOT / "config" / "research_data_contract_v1.0.json"


def load_research_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _present(value: Any) -> bool:
    return value not in (None, "", "NA", "N/A", "nan")


def _ratio(row: dict[str, str], fields: list[str]) -> tuple[int, int, float]:
    total = len(fields)
    present = sum(_present(row.get(field)) for field in fields)
    return present, total, round(present / total, 3) if total else 1.0


def _table_status(required: bool, exists: bool, errors: list[str], essential_ratio: float, recommended_ratio: float) -> str:
    if not exists:
        return "missing" if required else "not_started_optional"
    if errors:
        return "blocked"
    if essential_ratio < 1.0:
        return "incomplete"
    if recommended_ratio >= 0.75:
        return "structured"
    return "partial"


def validate_research_data_contract(
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    contract = load_research_contract(contract_path)
    problems: list[str] = []
    tables: list[dict[str, Any]] = []
    table_rows: dict[str, list[dict[str, str]]] = {}
    sample_ids: set[str] = set()

    table_specs = contract.get("tables", {})
    if not table_specs:
        problems.append("数据契约未定义表。")

    for table_name, spec in table_specs.items():
        relative_path = str(spec.get("path", ""))
        path = project_root / relative_path
        columns, rows = _read_csv(path)
        table_rows[table_name] = rows
        required = bool(spec.get("required", False))
        essential = list(spec.get("essential_fields", []))
        recommended = list(spec.get("recommended_fields", []))
        missing_columns = [field for field in essential if path.exists() and field not in columns]
        errors = [f"缺少必要列：{', '.join(missing_columns)}"] if missing_columns else []

        ids = [row.get("sample_id", "") for row in rows if row.get("sample_id")]
        duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
        one_to_many = table_name in {
            "composition_observations", "process_steps", "microstructure_observations",
            "property_observations", "physics_observations",
        }
        if duplicate_ids and not one_to_many:
            errors.append("sample_id重复：" + ", ".join(duplicate_ids))

        primary_key = list(spec.get("primary_key", []))
        if primary_key and rows and all(field in columns for field in primary_key):
            keys = [" | ".join(row.get(field, "").strip() for field in primary_key) for row in rows]
            duplicate_keys = sorted({value for value in keys if value and keys.count(value) > 1})
            if duplicate_keys:
                errors.append("主键重复：" + ", ".join(duplicate_keys))

        numeric_errors = []
        for row_number, row in enumerate(rows, start=2):
            for field in spec.get("numeric_fields", []):
                value = row.get(field)
                if not _present(value):
                    continue
                try:
                    float(value)
                except (TypeError, ValueError):
                    numeric_errors.append(f"第{row_number}行 {field} 不是数值")
        errors.extend(numeric_errors)

        if table_name == "physics_observations" and rows:
            allowed_types = set(spec.get("allowed_measurement_types", []))
            invalid_types = sorted({
                row.get("measurement_type", "") for row in rows
                if row.get("measurement_type", "") not in allowed_types
            })
            if invalid_types:
                errors.append("measurement_type不受支持：" + ", ".join(invalid_types))

        if table_name == "samples":
            sample_ids = set(ids)
        row_essential = [_ratio(row, essential)[2] for row in rows]
        row_recommended = [_ratio(row, recommended)[2] for row in rows]
        essential_ratio = round(sum(row_essential) / len(row_essential), 3) if row_essential else 0.0
        recommended_ratio = round(sum(row_recommended) / len(row_recommended), 3) if row_recommended else 0.0
        tables.append({
            "layer": table_name,
            "required": required,
            "exists": path.exists(),
            "row_count": len(rows),
            "essential_completeness": essential_ratio,
            "recommended_completeness": recommended_ratio,
            "missing_columns": missing_columns,
            "errors": errors,
            "status": _table_status(required, path.exists(), errors, essential_ratio, recommended_ratio),
        })
        if required and not path.exists():
            problems.append(f"必需表不存在：{relative_path}")
        problems.extend(f"{table_name}: {error}" for error in errors)

    for table_name, rows in table_rows.items():
        if table_name == "samples":
            continue
        orphans = sorted({row.get("sample_id", "") for row in rows if row.get("sample_id") not in sample_ids})
        if orphans:
            message = f"{table_name}存在未登记样品：{', '.join(orphans)}"
            problems.append(message)
            table_result = next(item for item in tables if item["layer"] == table_name)
            table_result["errors"].append(message)
            table_result["status"] = "blocked"

    declared_samples = set(contract.get("scope", {}).get("included_samples", []))
    undeclared_samples = sorted(sample_ids - declared_samples)
    missing_declared_samples = sorted(declared_samples - sample_ids)
    if undeclared_samples:
        problems.append("样品超出当前契约范围，请先更新契约：" + ", ".join(undeclared_samples))
    if missing_declared_samples:
        problems.append("契约声明的样品缺失：" + ", ".join(missing_declared_samples))

    sample_matrix = []
    for sample_id in sorted(sample_ids):
        for table_name in ("samples", "composition", "process", "microstructure", "properties"):
            spec = table_specs[table_name]
            row = next((item for item in table_rows.get(table_name, []) if item.get("sample_id") == sample_id), {})
            essential = list(spec.get("essential_fields", []))
            recommended = list(spec.get("recommended_fields", []))
            ep, et, er = _ratio(row, essential)
            rp, rt, rr = _ratio(row, recommended)
            status = _table_status(True, bool(row), [], er, rr)
            sample_matrix.append({
                "sample_id": sample_id,
                "layer": table_name,
                "status": status,
                "essential": f"{ep}/{et}",
                "recommended": f"{rp}/{rt}",
                "essential_ratio": er,
                "recommended_ratio": rr,
                "missing_essential": [field for field in essential if not _present(row.get(field))],
                "missing_recommended": [field for field in recommended if not _present(row.get(field))],
            })

    evidence = validation_summary()
    next_actions = []
    layer_map = {row["layer"]: row for row in tables}
    if layer_map.get("process", {}).get("status") != "structured":
        next_actions.append("补齐逐道次温度、压下量/总压下率、终轧与冷却参数，并保留来源状态。")
    if layer_map.get("composition_observations", {}).get("status") == "not_started_optional":
        next_actions.append("新增成分逐元素观测长表，保留炉次、检测方法和不确定度；重复读数不得冒充独立炉次。")
    if layer_map.get("process_steps", {}).get("status") == "not_started_optional":
        next_actions.append("工艺数据增加process_steps长表，逐步记录真实工序顺序，避免把多道次压缩成单个标签。")
    if layer_map.get("microstructure", {}).get("status") != "structured":
        next_actions.append("按匹配尺度登记PAG/packet/block、HAGB、KAM、GND；多视场不得冒充独立试样。")
    if layer_map.get("microstructure_observations", {}).get("status") == "not_started_optional":
        next_actions.append("组织数据增加observation_id、field_id、方法和采集尺度的长表，汇总值与原始视场层级分开。")
    if layer_map.get("property_observations", {}).get("status") == "not_started_optional":
        next_actions.append("性能数据增加独立specimen_id长表后再做推断统计；当前均值±标准差只支持方向性判断。")
    if layer_map.get("physics_observations", {}).get("status") == "not_started_optional":
        next_actions.append("获得热膨胀/热模拟结果后新增physics_observations.csv，分开保存实验值、模型值与残差。")

    return {
        "contract_id": contract.get("contract_id"),
        "schema_version": contract.get("schema_version"),
        "contract_status": "passed" if not problems else "failed",
        "problems": problems,
        "sample_count": len(sample_ids),
        "tables": tables,
        "sample_matrix": sample_matrix,
        "scientific_readiness": {
            "overall": evidence.get("overall_readiness"),
            "causal_inference_ready": evidence.get("causal_inference_ready"),
            "machine_learning_ready": evidence.get("machine_learning_ready"),
        },
        "scope": contract.get("scope", {}),
        "physics_model_requirements": contract.get("physics_model_requirements", []),
        "future_model_families": contract.get("future_model_families", []),
        "next_actions": next_actions,
    }


def contract_report_markdown(report: dict[str, Any] | None = None) -> str:
    data = report or validate_research_data_contract()
    lines = [
        "# SteelAI Research Data Contract Report",
        "",
        f"- Contract: `{data['contract_id']}`",
        f"- Contract status: `{data['contract_status']}`",
        f"- Samples: {data['sample_count']}",
        f"- Scientific readiness: `{data['scientific_readiness']['overall']}`",
        f"- Causal inference ready: `{data['scientific_readiness']['causal_inference_ready']}`",
        f"- Machine learning ready: `{data['scientific_readiness']['machine_learning_ready']}`",
        "",
        "## Layer Status",
        "",
    ]
    for row in data["tables"]:
        lines.append(
            f"- {row['layer']}: `{row['status']}`; essential={row['essential_completeness']:.1%}; "
            f"recommended={row['recommended_completeness']:.1%}; rows={row['row_count']}"
        )
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {item}" for item in data["next_actions"])
    lines.extend([
        "",
        "## Boundary",
        "",
        "- Blank values are missing, not zero.",
        "- Experiments 1-14 remain excluded.",
        "- Model estimates are not experimental truth.",
        "- The current B/R dataset supports directional evidence only.",
    ])
    return "\n".join(lines).strip() + "\n"
