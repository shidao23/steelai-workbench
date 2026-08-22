from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from steelai.paths import INDEX, PROCESSED


TABLES = {
    "samples": PROCESSED / "samples.csv",
    "composition": PROCESSED / "composition.csv",
    "process": PROCESSED / "process.csv",
    "microstructure": PROCESSED / "microstructure.csv",
    "properties": PROCESSED / "properties.csv",
    "evidence": INDEX / "evidence_index.csv",
}


def read_rows(name: str) -> list[dict[str, str]]:
    path = TABLES[name]
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path = TABLES[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fieldnames:
        raise ValueError("Empty rows require fieldnames")
    columns = fieldnames or list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_row(name: str, row: dict[str, Any]) -> None:
    existing = read_rows(name)
    columns = list(existing[0].keys()) if existing else list(row.keys())
    normalized = {column: row.get(column, "") for column in columns}
    existing.append(normalized)
    write_rows(name, existing, columns)


def sample_bundle(sample_id: str) -> dict[str, dict[str, str]]:
    bundle: dict[str, dict[str, str]] = {}
    for name in ("samples", "composition", "process", "microstructure", "properties"):
        row = next((item for item in read_rows(name) if item.get("sample_id") == sample_id), {})
        bundle[name] = row
    return bundle


def numeric(value: Any) -> float | None:
    if value in (None, "", "NA", "N/A", "nan"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evidence_path_status(path_text: str) -> str:
    if not path_text:
        return "missing_path"
    path = Path(path_text).expanduser()
    return "available" if path.exists() else "not_found"
