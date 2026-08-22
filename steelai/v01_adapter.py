from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from steelai.settings import load_settings


def configured_root() -> Path | None:
    value = load_settings().get("sources", {}).get("wearsteel_v01_root", "")
    return Path(value) if value else None


def is_available(root: Path | None = None) -> bool:
    base = root or configured_root()
    return bool(base and (base / "physics_models.py").is_file() and (base / "data" / "composition.csv").is_file())


def _load_module(root: Path) -> ModuleType:
    module_path = root / "physics_models.py"
    spec = importlib.util.spec_from_file_location("wearsteel_v01_physics_models", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 v0.1 Physics Engine：{module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_composition(steel_id: str, root: Path | None = None) -> tuple[dict[str, float | None], dict[str, str]]:
    base = root or configured_root()
    if not base:
        raise FileNotFoundError("wearsteel_v01_root 未配置")
    with (base / "data" / "composition.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        row = next((item for item in csv.DictReader(handle) if item.get("steel_id") == steel_id), None)
    if row is None:
        raise KeyError(f"v0.1 中没有钢种 {steel_id}")
    ignored = {"steel_id", "steel_name", "composition_basis", "source_file", "source_location", "verification_status", "notes"}
    composition: dict[str, float | None] = {}
    for key, value in row.items():
        if key in ignored:
            continue
        composition[key] = None if value in (None, "") else float(value)
    metadata = {key: row.get(key, "") for key in ignored}
    return composition, metadata


def evaluate(steel_id: str, root: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, float | None], dict[str, str]]:
    base = root or configured_root()
    if not base or not is_available(base):
        raise FileNotFoundError("未找到完整 WearSteel-AI v0.1")
    composition, source_metadata = load_composition(steel_id, base)
    module = _load_module(base)
    rows = []
    for result in module.evaluate_all(composition):
        model = result.metadata
        rows.append({
            "model_id": model.model_id,
            "family": model.family,
            "name": model.name,
            "output_name": model.output_name,
            "value": result.value,
            "unit": model.output_unit,
            "status": result.status,
            "warnings": list(result.warnings),
            "formula": model.formula,
            "source": model.source,
            "source_url": model.source_url,
            "required_inputs": list(model.required_inputs),
            "applicability": model.applicability,
            "range_basis": model.range_basis,
            "limitations": list(model.limitations),
        })
    return rows, composition, source_metadata
