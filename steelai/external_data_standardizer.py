"""Deterministic external flat-file standardization for the daily intake UI.

The module reads uploaded bytes in memory, maps source columns to the existing
research-data contract, performs explicit unit conversion, and hands the result
to the existing governed append-only intake gate.  It never edits the source.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from steelai.data_intake import _allowed_columns, validate_intake_csv
from steelai.research_data_contract import CONTRACT_PATH, load_research_contract


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 500
SUPPORTED_SUFFIXES = {".csv", ".tsv", ".xlsx"}
FORMULA_WARNING = "源文件含公式单元格；当前读取其缓存显示值，提交前必须与原表核对。"

COMMON_ALIASES = {
    "sample": "sample_id", "sampleid": "sample_id", "样品": "sample_id",
    "样品号": "sample_id", "样品编号": "sample_id",
    "specimen": "specimen_id", "specimenid": "specimen_id", "试样": "specimen_id",
    "试样号": "specimen_id", "试样编号": "specimen_id",
    "batch": "batch_id", "batchid": "batch_id", "批次": "batch_id", "批次号": "batch_id",
    "observation": "observation_id", "observationid": "observation_id",
    "element": "element", "元素": "element", "property": "property", "性能": "property",
    "metric": "metric", "指标": "metric", "value": "value", "result": "value", "数值": "value",
    "unit": "unit", "单位": "unit", "method": "method", "方法": "method",
    "source": "source_status", "sourcestatus": "source_status", "来源状态": "source_status",
    "note": "notes", "notes": "notes", "备注": "notes",
    "ys": "ys_mpa", "yieldstrength": "ys_mpa", "屈服强度": "ys_mpa",
    "uts": "uts_mpa", "tensilestrength": "uts_mpa", "抗拉强度": "uts_mpa",
    "elongation": "elongation_pct", "el": "elongation_pct", "延伸率": "elongation_pct",
}


def _safe_name(file_name: str) -> str:
    name = Path(str(file_name)).name
    if name != file_name or not name or len(name) > 200 or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("仅支持安全命名的 CSV、TSV 或 XLSX 文件。")
    return name


def _text_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).casefold())


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文件编码无法识别；请另存为 UTF-8 CSV/TSV。")


def _dedupe_headers(values: list[str]) -> list[str]:
    headers = [str(value).strip() for value in values]
    if not headers or not any(headers):
        raise ValueError("没有找到表头。")
    if any(not value for value in headers):
        raise ValueError("表头中存在空列名。")
    if len(headers) != len(set(headers)):
        raise ValueError("表头存在重复列名。")
    if len(headers) > MAX_COLUMNS:
        raise ValueError(f"列数超过 {MAX_COLUMNS}，请拆分文件。")
    return headers


def _rows_from_matrix(matrix: list[list[Any]]) -> tuple[list[str], list[dict[str, str]]]:
    while matrix and not any(str(value).strip() for value in matrix[0]):
        matrix.pop(0)
    if not matrix:
        raise ValueError("文件没有可读取的数据。")
    headers = _dedupe_headers([str(value) for value in matrix[0]])
    rows: list[dict[str, str]] = []
    for values in matrix[1:]:
        if len(values) > len(headers) and any(str(value).strip() for value in values[len(headers):]):
            raise ValueError("存在超出表头的单元格；系统不会静默丢弃。")
        padded = [*values[:len(headers)], *([""] * max(0, len(headers) - len(values)))]
        row = {header: str(value).strip() for header, value in zip(headers, padded, strict=True)}
        if any(row.values()):
            rows.append(row)
    if not rows:
        raise ValueError("文件只有表头，没有可导入记录。")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"记录数超过 {MAX_ROWS}，请拆分批次。")
    return headers, rows


def _read_delimited(file_name: str, content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = _decode_text(content)
    if Path(file_name).suffix.lower() == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:16_384], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return _rows_from_matrix([list(row) for row in reader])


def _xlsx_parts(content: bytes) -> tuple[zipfile.ZipFile, dict[str, str], list[tuple[str, str]]]:
    archive = zipfile.ZipFile(io.BytesIO(content))
    infos = archive.infolist()
    if len(infos) > 10_000 or sum(item.file_size for item in infos) > MAX_XLSX_UNCOMPRESSED:
        archive.close()
        raise ValueError("XLSX 解压规模异常，请拆分或另存为 CSV。")
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    sheets = []
    for node in workbook.findall("m:sheets/m:sheet", ns):
        relationship = node.attrib.get(f"{{{ns['r']}}}id", "")
        target = rel_map.get(relationship, "")
        if not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = str(PurePosixPath("xl") / PurePosixPath(target))
        path = str(PurePosixPath(path))
        if not path.startswith("xl/worksheets/"):
            continue
        sheets.append((node.attrib.get("name", ""), path))
    if not sheets:
        archive.close()
        raise ValueError("XLSX 中没有可读取工作表。")
    shared: dict[str, str] = {}
    if "xl/sharedStrings.xml" in archive.namelist():
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        for index, item in enumerate(root.findall(f"{main}si")):
            shared[str(index)] = "".join(node.text or "" for node in item.iter(f"{main}t"))
    return archive, shared, sheets


def xlsx_sheet_names(content: bytes) -> list[str]:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("文件为空或超过 20 MiB。")
    try:
        archive, _, sheets = _xlsx_parts(content)
    except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise ValueError("XLSX 文件结构无效或已损坏。") from exc
    archive.close()
    return [name for name, _ in sheets]


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        raise ValueError("XLSX 单元格坐标无效。")
    result = 0
    for char in letters.group(0):
        result = result * 26 + ord(char) - 64
    return result - 1


def _read_xlsx(content: bytes, sheet_name: str | None) -> tuple[list[str], list[dict[str, str]], int, list[str]]:
    try:
        archive, shared, sheets = _xlsx_parts(content)
        selected = next((item for item in sheets if item[0] == sheet_name), sheets[0] if sheet_name is None else None)
        if selected is None:
            raise ValueError("所选工作表不存在。")
        root = ET.fromstring(archive.read(selected[1]))
    except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise ValueError("XLSX 文件结构无效或已损坏。") from exc
    finally:
        if "archive" in locals():
            archive.close()
    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    matrix: list[list[str]] = []
    formula_count = 0
    for row_node in root.iter(f"{main}row"):
        values: list[str] = []
        for cell in row_node.findall(f"{main}c"):
            column = _column_index(cell.attrib.get("r", ""))
            if column >= MAX_COLUMNS:
                raise ValueError(f"列数超过 {MAX_COLUMNS}，请拆分文件。")
            while len(values) <= column:
                values.append("")
            if cell.find(f"{main}f") is not None:
                formula_count += 1
            kind = cell.attrib.get("t", "n")
            value_node = cell.find(f"{main}v")
            if kind == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{main}t"))
            elif value_node is None:
                value = ""
            elif kind == "s":
                value = shared.get(value_node.text or "", "")
            elif kind == "b":
                value = "true" if value_node.text == "1" else "false"
            else:
                value = value_node.text or ""
            values[column] = value
        matrix.append(values)
        if len(matrix) > MAX_ROWS + 1:
            raise ValueError(f"记录数超过 {MAX_ROWS}，请拆分批次。")
    headers, rows = _rows_from_matrix(matrix)
    return headers, rows, formula_count, [name for name, _ in sheets]


def inspect_external_file(file_name: str, content: bytes, *, sheet_name: str | None = None) -> dict[str, Any]:
    name = _safe_name(file_name)
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("文件为空或超过 20 MiB。")
    suffix = Path(name).suffix.lower()
    warnings: list[str] = []
    if suffix == ".xlsx":
        headers, rows, formula_count, sheets = _read_xlsx(content, sheet_name)
        if formula_count:
            warnings.append(FORMULA_WARNING)
    else:
        headers, rows = _read_delimited(name, content)
        formula_count, sheets = 0, []
    return {
        "schema_version": "1.0",
        "file_name": name,
        "file_type": suffix.lstrip("."),
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "sheet_name": sheet_name or (sheets[0] if sheets else None),
        "sheet_names": sheets,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "formula_cell_count": formula_count,
        "warnings": warnings,
    }


def suggest_mapping(headers: list[str], table_name: str, *, contract_path: Path = CONTRACT_PATH) -> dict[str, str]:
    spec = load_research_contract(contract_path).get("tables", {}).get(table_name)
    if not spec:
        raise KeyError(f"Unknown intake table: {table_name}")
    source_by_key = {_text_key(header): header for header in headers}
    aliases = {**COMMON_ALIASES}
    suggestions: dict[str, str] = {}
    for target in _allowed_columns(spec):
        exact = source_by_key.get(_text_key(target))
        if exact:
            suggestions[target] = exact
            continue
        match = next((header for header in headers if aliases.get(_text_key(header)) == target), "")
        suggestions[target] = match
    return suggestions


def canonical_unit_for_field(table_name: str, field: str) -> str | None:
    if table_name == "composition" and field not in {"sample_id", "source_status"}:
        return "wt.%"
    if field.endswith("_mpa"):
        return "MPa"
    if field.endswith("_pct"):
        return "%"
    if field.endswith("_temp_c") or field in {"start_temp_c", "end_temp_c", "test_temperature_c"}:
        return "degC"
    if field.endswith("_time_min"):
        return "min"
    if field.endswith("_s") and not field.endswith("_rate_s"):
        return "s"
    if field.endswith("_um"):
        return "um"
    if field.endswith("_deg"):
        return "deg"
    if field.endswith("_m2"):
        return "m^-2"
    if field == "impact_minus40_j" or field == "impact_std_j":
        return "J"
    if field == "impact_toughness_j_cm2":
        return "J/cm^2"
    if field == "hv":
        return "HV"
    return None


def infer_source_unit(header: str, target_unit: str | None) -> str | None:
    if target_unit is None:
        return None
    normalized = header.replace("μ", "u").casefold()
    candidates = ["j/cm^2", "m^-2", "wt.%", "mass_ppm", "gpa", "mpa", "kpa", "pa", "degc", "°c",
                  "kelvin", "um", "mm", "nm", "min", "hour", "ms", "sec", "%", "hv", "j"]
    aliases = {"gpa": "GPa", "mpa": "MPa", "kpa": "kPa", "pa": "Pa", "degc": "degC", "°c": "degC",
               "kelvin": "K", "um": "um", "mm": "mm", "nm": "nm", "min": "min", "hour": "h",
               "ms": "ms", "sec": "s", "%": "%", "hv": "HV", "j": "J", "j/cm^2": "J/cm^2",
               "m^-2": "m^-2", "wt.%": "wt.%", "mass_ppm": "mass_ppm"}
    for token in candidates:
        if token in normalized:
            return aliases[token]
    if _text_key(header) == _text_key(re.sub(r"_(mpa|pct|temp_c|time_min|um|deg|m2)$", "", header)):
        return None
    if _text_key(target_unit) in _text_key(header) or header.casefold().endswith("_" + target_unit.casefold()):
        return target_unit
    return target_unit if header.casefold().endswith(("_mpa", "_pct", "_um", "_deg", "_m2")) else None


def unit_choices(target_unit: str | None) -> list[str]:
    return {
        "MPa": ["MPa", "GPa", "kPa", "Pa"], "%": ["%", "fraction"], "degC": ["degC", "K"],
        "min": ["min", "s", "h"], "s": ["s", "ms", "min"], "um": ["um", "mm", "nm"],
        "deg": ["deg"], "m^-2": ["m^-2"], "J": ["J"], "J/cm^2": ["J/cm^2"],
        "HV": ["HV"], "wt.%": ["wt.%", "mass_ppm"],
    }.get(target_unit, [])


def _convert_number(raw: str, source_unit: str, target_unit: str) -> str:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("不是有限数值")
    if source_unit == target_unit:
        converted = value
    else:
        scale = {
            ("GPa", "MPa"): 1000.0, ("kPa", "MPa"): 0.001, ("Pa", "MPa"): 0.000001,
            ("fraction", "%"): 100.0, ("s", "min"): 1 / 60, ("h", "min"): 60.0,
            ("ms", "s"): 0.001, ("min", "s"): 60.0, ("mm", "um"): 1000.0,
            ("nm", "um"): 0.001, ("mass_ppm", "wt.%"): 0.0001,
        }.get((source_unit, target_unit))
        if source_unit == "K" and target_unit == "degC":
            converted = value - 273.15
        elif scale is None:
            raise ValueError(f"不支持 {source_unit} → {target_unit} 的换算")
        else:
            converted = value * scale
    return format(converted, ".15g")


def _constant_value(template: str, row_number: int, source_sha256: str) -> str:
    """Expand only deterministic record-ID placeholders, never physical IDs."""
    return (template.replace("{row}", f"{row_number - 1:06d}")
            .replace("{source8}", source_sha256[:8].upper()))


def build_standardization_preview(
    inspection: Mapping[str, Any],
    table_name: str,
    mapping: Mapping[str, str],
    *,
    constants: Mapping[str, str] | None = None,
    source_units: Mapping[str, str] | None = None,
    contract_path: Path = CONTRACT_PATH,
    project_root: Path | None = None,
) -> dict[str, Any]:
    contract = load_research_contract(contract_path)
    spec = contract.get("tables", {}).get(table_name)
    if not spec:
        raise KeyError(f"Unknown intake table: {table_name}")
    constants = {key: str(value).strip() for key, value in (constants or {}).items()}
    source_units = {key: str(value).strip() for key, value in (source_units or {}).items()}
    allowed = _allowed_columns(spec)
    unknown_targets = sorted(set(mapping) - set(allowed))
    if unknown_targets:
        raise ValueError("映射含未登记目标字段：" + ", ".join(unknown_targets))
    used_sources = [source for source in mapping.values() if source]
    if len(used_sources) != len(set(used_sources)):
        raise ValueError("同一来源列不能映射到多个目标字段。")
    headers = set(inspection.get("headers", []))
    missing_sources = sorted(set(used_sources) - headers)
    if missing_sources:
        raise ValueError("映射引用了不存在的来源列：" + ", ".join(missing_sources))

    errors: list[str] = []
    transformations: list[dict[str, str]] = []
    numeric_fields = set(spec.get("numeric_fields", []))
    for target, source in mapping.items():
        target_unit = canonical_unit_for_field(table_name, target)
        if source and target in numeric_fields and target_unit:
            source_unit = source_units.get(target, "")
            if not source_unit:
                errors.append(f"{target} 已映射到 {source}，但来源单位未确认")
            elif source_unit not in unit_choices(target_unit):
                errors.append(f"{target} 的来源单位 {source_unit} 不受支持")
            else:
                transformations.append({"source": source, "target": target, "source_unit": source_unit,
                                        "target_unit": target_unit})

    rows: list[dict[str, str]] = []
    for row_number, source_row in enumerate(inspection.get("rows", []), start=2):
        result: dict[str, str] = {}
        for target in allowed:
            source = mapping.get(target, "")
            raw = (str(source_row.get(source, "")).strip() if source else _constant_value(
                constants.get(target, ""), row_number, str(inspection.get("source_sha256", ""))
            ))
            target_unit = canonical_unit_for_field(table_name, target)
            if raw and source and target in numeric_fields and target_unit and source_units.get(target):
                try:
                    raw = _convert_number(raw, source_units[target], target_unit)
                except ValueError as exc:
                    errors.append(f"第{row_number}行 {target}: {exc}")
            result[target] = raw
        if any(result.values()):
            rows.append(result)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=allowed, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    report = validate_intake_csv(
        table_name,
        buffer.getvalue().encode("utf-8"),
        contract_path=contract_path,
        **({"project_root": project_root} if project_root is not None else {}),
    )
    report["errors"] = list(dict.fromkeys([*errors, *report.get("errors", [])]))
    report["warnings"] = list(dict.fromkeys([*inspection.get("warnings", []), *report.get("warnings", [])]))
    report["status"] = "blocked" if report["errors"] else "ready"
    report["standardization"] = {
        "standardizer_version": "1.0",
        "source_sha256": inspection.get("source_sha256"),
        "source_file_type": inspection.get("file_type"),
        "sheet_name": inspection.get("sheet_name"),
        "mapping": dict(mapping),
        "constants": dict(constants),
        "unit_transformations": transformations,
        "source_row_count": inspection.get("row_count"),
        "normalized_row_count": len(rows),
    }
    report["standardization_sha256"] = hashlib.sha256(json.dumps(
        report["standardization"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return report
