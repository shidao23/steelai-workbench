from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from math import sqrt
from pathlib import Path
from typing import Any, Callable

from steelai.paths import PROCESSED, ROOT


NumberMap = dict[str, float | None]
REGISTRY_PATH = ROOT / "config" / "physics_model_registry_v1.0.json"
PHYSICS_OBSERVATIONS_PATH = PROCESSED / "physics_observations.csv"
MODEL_FAMILIES = ("Ms", "Ac1", "Ac3", "Tnr", "Ceq", "Pcm")
REQUIRED_REGISTRY_FIELDS = {
    "model_id", "model_version", "model_family", "formula_or_backend", "source",
    "required_inputs", "output_unit", "applicability", "applicable_composition_range",
    "limitations", "license", "review_status", "experimental_reference", "residual",
    "calibration_status",
}


@dataclass(frozen=True)
class PhysicsResult:
    key: str
    label: str
    value: float | None
    unit: str
    formula: str
    source: str
    review_status: str
    warnings: tuple[str, ...]
    note: str
    model_id: str = ""
    model_version: str = ""
    model_family: str = ""
    status: str = ""
    calibration_status: str = ""
    experimental_reference: dict[str, Any] | None = None
    residual_definition: str = "model_value - experimental_value"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["warnings"] = list(self.warnings)
        result["result_type"] = "empirical_model_estimate_not_experimental_truth"
        return result


def load_model_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_model_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    problems: list[str] = []
    try:
        registry = load_model_registry(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "failed", "registry_id": "", "model_count": 0, "problems": [str(exc)]}

    models = registry.get("models", [])
    if not isinstance(models, list) or not models:
        problems.append("注册表未包含模型。")
        models = []
    identifiers: list[str] = []
    defaults: dict[str, int] = {family: 0 for family in MODEL_FAMILIES}
    for index, model in enumerate(models, start=1):
        if not isinstance(model, dict):
            problems.append(f"第{index}个模型不是对象。")
            continue
        missing = sorted(REQUIRED_REGISTRY_FIELDS - set(model))
        if missing:
            problems.append(f"{model.get('model_id', index)} 缺少字段：{', '.join(missing)}")
        model_id = str(model.get("model_id", "")).strip()
        if not model_id:
            problems.append(f"第{index}个模型缺少model_id。")
        identifiers.append(model_id)
        family = str(model.get("model_family", ""))
        if family not in MODEL_FAMILIES:
            problems.append(f"{model_id or index} 的model_family不受支持：{family}")
        if model.get("default_for_family"):
            defaults[family] = defaults.get(family, 0) + 1
        ranges = model.get("applicable_composition_range", {})
        if not isinstance(ranges, dict):
            problems.append(f"{model_id or index} 的适用成分范围必须是对象。")
        else:
            for element, limits in ranges.items():
                if not isinstance(limits, list) or len(limits) != 2 or limits[0] > limits[1]:
                    problems.append(f"{model_id or index} 的{element}范围无效。")
    duplicates = sorted({item for item in identifiers if item and identifiers.count(item) > 1})
    if duplicates:
        problems.append("model_id重复：" + ", ".join(duplicates))
    for family in MODEL_FAMILIES:
        family_count = sum(model.get("model_family") == family for model in models if isinstance(model, dict))
        if family_count == 0:
            problems.append(f"缺少{family}模型。")
        if defaults.get(family, 0) != 1:
            problems.append(f"{family}必须且只能有一个默认模型。")
    return {
        "status": "passed" if not problems else "failed",
        "registry_id": registry.get("registry_id", ""),
        "schema_version": registry.get("schema_version", ""),
        "model_count": len(models),
        "families": list(MODEL_FAMILIES),
        "problems": problems,
    }


def registry_models(path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    registry = load_model_registry(path)
    return [dict(model) for model in registry.get("models", [])]


def model_by_id(model_id: str) -> dict[str, Any]:
    model = next((item for item in registry_models() if item.get("model_id") == model_id), None)
    if model is None:
        raise KeyError(f"未知物理模型：{model_id}")
    return model


def models_for_family(model_family: str) -> list[dict[str, Any]]:
    if model_family not in MODEL_FAMILIES:
        raise ValueError(f"不支持的物理量：{model_family}")
    return [item for item in registry_models() if item.get("model_family") == model_family]


def default_model_ids() -> dict[str, str]:
    return {
        family: next(
            item["model_id"] for item in models_for_family(family)
            if item.get("default_for_family")
        )
        for family in MODEL_FAMILIES
    }


def _v(composition: NumberMap, key: str) -> float:
    value = composition.get(key)
    if value is None:
        raise ValueError(f"missing input: {key}")
    return float(value)


CALCULATORS: dict[str, Callable[[NumberMap], float]] = {
    "ms_andrews_linear_1965": lambda c: 539 - 423 * _v(c, "C") - 30.4 * _v(c, "Mn") - 17.7 * _v(c, "Ni") - 12.1 * _v(c, "Cr") - 7.5 * _v(c, "Mo"),
    "ms_andrews_nonlinear_1965": lambda c: 512 - 453 * _v(c, "C") - 16.9 * _v(c, "Ni") + 15 * _v(c, "Cr") - 9.5 * _v(c, "Mo") + 217 * _v(c, "C") ** 2 - 71.5 * _v(c, "C") * _v(c, "Mn") - 67.6 * _v(c, "C") * _v(c, "Cr"),
    "ac1_andrews_1965": lambda c: 723 - 10.7 * _v(c, "Mn") - 16.9 * _v(c, "Ni") + 29.1 * _v(c, "Si") + 16.9 * _v(c, "Cr") + 290 * _v(c, "As") + 6.38 * _v(c, "W"),
    "ac1_trzaska_2016": lambda c: 742 - 29 * _v(c, "C") - 14 * _v(c, "Mn") + 13 * _v(c, "Si") + 16 * _v(c, "Cr") - 17 * _v(c, "Ni") - 16 * _v(c, "Mo") + 45 * _v(c, "V") + 36 * _v(c, "Cu"),
    "ac3_andrews_1965": lambda c: 910 - 203 * sqrt(_v(c, "C")) - 15.2 * _v(c, "Ni") + 44.7 * _v(c, "Si") + 104.4 * _v(c, "V") + 31.5 * _v(c, "Mo") + 13.1 * _v(c, "W"),
    "ac3_trzaska_2016": lambda c: 925 - 219 * _v(c, "C") - 7 * _v(c, "Mn") + 39 * _v(c, "Si") - 16 * _v(c, "Ni") + 13 * _v(c, "Mo") + 97 * _v(c, "V"),
    "tnr_boratto_1988": lambda c: 887 + 464 * _v(c, "C") + 6445 * _v(c, "Nb") - 644 * sqrt(_v(c, "Nb")) + 732 * _v(c, "V") - 230 * sqrt(_v(c, "V")) + 890 * _v(c, "Ti") + 363 * _v(c, "Al") - 357 * _v(c, "Si"),
    "tnr_militzer_2000": lambda c: 893 + 910 * _v(c, "Nb"),
    "ceq_iiw": lambda c: _v(c, "C") + _v(c, "Mn") / 6 + (_v(c, "Cr") + _v(c, "Mo") + _v(c, "V")) / 5 + (_v(c, "Ni") + _v(c, "Cu")) / 15,
    "pcm_ito_bessyo": lambda c: _v(c, "C") + _v(c, "Si") / 30 + (_v(c, "Mn") + _v(c, "Cu") + _v(c, "Cr")) / 20 + _v(c, "Ni") / 60 + _v(c, "Mo") / 15 + _v(c, "V") / 10 + 5 * _v(c, "B"),
}


def _extra_warnings(model_id: str, composition: NumberMap, provided: set[str]) -> list[str]:
    warnings: list[str] = []
    if model_id == "ac1_andrews_1965":
        warnings.append("Ac1专属验证范围尚未建立；当前范围仅为已标明的筛查代理。")
    if model_id in {"ac1_trzaska_2016", "ac3_trzaska_2016"} and {"Mn", "Cr", "Ni"} <= provided:
        mn, cr, ni = _v(composition, "Mn"), _v(composition, "Cr"), _v(composition, "Ni")
        for label, value, maximum in (
            ("Mn+Cr", mn + cr, 3.6), ("Mn+Cr+Ni", mn + cr + ni, 5.6),
            ("Cr+Ni", cr + ni, 5.3), ("Mn+Ni", mn + ni, 4.5),
        ):
            if value > maximum:
                warnings.append(f"{label}={value:g} wt.% 超出模型组合上限 {maximum:g} wt.%")
    if model_id == "ceq_iiw" and "C" in provided and _v(composition, "C") < 0.12:
        warnings.append("C < 0.12 wt.%；低碳微合金钢通常还应比较Pcm。")
    return warnings


def evaluate_model(
    model_id: str,
    composition: NumberMap,
    provided_fields: set[str] | None = None,
) -> PhysicsResult:
    model = model_by_id(model_id)
    provided = set(provided_fields) if provided_fields is not None else {
        key for key, value in composition.items() if value is not None
    }
    required = list(model["required_inputs"])
    missing = [key for key in required if key not in provided or composition.get(key) is None]
    warnings: list[str] = []
    if missing:
        warnings.append("缺少成分字段，模型已跳过且未按0代填: " + ", ".join(missing))
    for element, limits in model.get("applicable_composition_range", {}).items():
        if element not in provided or composition.get(element) is None:
            continue
        value = _v(composition, element)
        low, high = float(limits[0]), float(limits[1])
        if value < low or value > high:
            warnings.append(f"{element}={value:g} wt.% 超出工作台审查范围/适用证据范围 [{low:g}, {high:g}] wt.%")
    warnings.extend(_extra_warnings(model_id, composition, provided))
    value: float | None = None
    status = "skipped_missing_inputs" if missing else "ok"
    if not missing:
        try:
            value = round(float(CALCULATORS[model_id](composition)), 3)
            if warnings:
                status = "warning"
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            status = "skipped_formula_domain"
            warnings.append(f"公式定义域错误，模型已跳过: {exc}")
    residual = model.get("residual", {})
    return PhysicsResult(
        key=model["model_family"], label=model["display_name"], value=value,
        unit=model["output_unit"], formula=model["formula_or_backend"], source=model["source"],
        review_status=model["review_status"], warnings=tuple(warnings),
        note="；".join(model.get("limitations", [])), model_id=model_id,
        model_version=model["model_version"], model_family=model["model_family"], status=status,
        calibration_status=model["calibration_status"],
        experimental_reference=model.get("experimental_reference"),
        residual_definition=str(residual.get("definition", "model_value - experimental_value")),
    )


def calculate_all(
    composition: NumberMap,
    provided_fields: set[str] | None = None,
    selected_models: dict[str, str] | None = None,
) -> list[PhysicsResult]:
    selected = default_model_ids()
    if selected_models:
        for family, model_id in selected_models.items():
            if family not in MODEL_FAMILIES:
                raise ValueError(f"不支持的物理量：{family}")
            if model_by_id(model_id).get("model_family") != family:
                raise ValueError(f"模型{model_id}不属于{family}")
            selected[family] = model_id
    return [evaluate_model(selected[family], composition, provided_fields) for family in MODEL_FAMILIES]


def compare_versions(
    model_family: str,
    composition: NumberMap,
    provided_fields: set[str] | None = None,
) -> list[PhysicsResult]:
    return [evaluate_model(model["model_id"], composition, provided_fields) for model in models_for_family(model_family)]


def specs_as_rows() -> list[dict[str, Any]]:
    rows = []
    for model in registry_models():
        rows.append({
            "model_id": model["model_id"], "model_version": model["model_version"],
            "model_family": model["model_family"], "formula_or_backend": model["formula_or_backend"],
            "required_inputs": ", ".join(model["required_inputs"]), "output_unit": model["output_unit"],
            "review_status": model["review_status"], "calibration_status": model["calibration_status"],
        })
    return rows


def model_card_markdown(model_id: str) -> str:
    model = model_by_id(model_id)
    ranges = model.get("applicable_composition_range", {})
    range_text = "; ".join(f"{key}={value[0]:g}–{value[1]:g} wt.%" for key, value in ranges.items()) or "未声明通用逐元素范围；遵守适用性与范围依据说明。"
    limitations = "\n".join(f"- {item}" for item in model["limitations"])
    return (
        f"# Physics Model Card · {model['display_name']}\n\n"
        f"- Model ID: `{model['model_id']}`\n- Version: `{model['model_version']}`\n"
        f"- Family: `{model['model_family']}`\n- Review status: `{model['review_status']}`\n"
        f"- Calibration status: `{model['calibration_status']}`\n- Output: `{model['output_unit']}`\n"
        f"- Required inputs: `{', '.join(model['required_inputs'])}`\n"
        f"- Result type: `empirical_model_estimate_not_experimental_truth`\n\n"
        f"## Formula / Backend\n\n`{model['formula_or_backend']}`\n\n"
        f"## Source\n\n{model['source']}\n\n"
        f"## Applicability\n\n{model['applicability']}\n\n"
        f"- Composition range: {range_text}\n- Range basis: {model['range_basis']}\n\n"
        f"## Limitations\n\n{limitations}\n\n"
        f"## Experimental and Residual Interface\n\n"
        f"- Experimental reference: `{model['experimental_reference']['status']}`\n"
        f"- Residual: `{model['residual']['definition']}`\n"
        f"- Original formula is never overwritten by a fit.\n\n"
        f"## License Note\n\n{model['license']}\n"
    )


def version_comparison_markdown(sample_id: str, model_family: str, results: list[PhysicsResult]) -> str:
    lines = [
        f"# {model_family} Model Version Comparison", "", f"- Sample: `{sample_id}`",
        "- Result type: `empirical_model_estimate_not_experimental_truth`",
        "- Models are compared without fitting or overwriting the published formula.", "",
        "| Model ID | Version | Value | Status | Warnings |", "|---|---|---:|---|---|",
    ]
    for result in results:
        value = "NA" if result.value is None else f"{result.value:g} {result.unit}"
        warnings = "<br>".join(result.warnings) if result.warnings else "None"
        lines.append(f"| `{result.model_id}` | `{result.model_version}` | {value} | `{result.status}` | {warnings} |")
    lines.extend([
        "", "## Boundary", "", "- Formula outputs are empirical estimates, not experimental truth.",
        "- A smaller difference between formula versions does not establish accuracy.",
        "- Calibration requires matched experimental observations with provenance.",
    ])
    return "\n".join(lines).strip() + "\n"


def load_physics_observations(path: Path = PHYSICS_OBSERVATIONS_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def compare_with_experimental_observations(
    sample_id: str,
    results: list[PhysicsResult],
    observations: list[dict[str, str]],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for observation in observations:
        if observation.get("sample_id") != sample_id or observation.get("measurement_type") != "experimental":
            continue
        quantity = str(observation.get("quantity", "")).strip()
        experimental_raw = observation.get("value")
        try:
            experimental_value = float(experimental_raw) if experimental_raw not in (None, "") else None
        except (TypeError, ValueError):
            experimental_value = None
        for result in results:
            if result.key.casefold() != quantity.casefold():
                continue
            unit_matches = str(observation.get("unit", "")).strip() == result.unit
            residual = None
            warnings = list(result.warnings)
            if not unit_matches:
                warnings.append("实验值与模型值单位不一致，未计算残差。")
            elif experimental_value is None or result.value is None:
                warnings.append("实验值或模型值缺失，未计算残差。")
            else:
                residual = round(result.value - experimental_value, 3)
            comparisons.append({
                "sample_id": sample_id, "observation_id": observation.get("observation_id", ""),
                "specimen_id": observation.get("specimen_id", ""), "quantity": result.key,
                "experimental_value": experimental_value, "model_value": result.value,
                "residual_model_minus_experimental": residual, "unit": result.unit,
                "model_id": result.model_id, "model_version": result.model_version,
                "calibration_status": result.calibration_status,
                "source_status": observation.get("source_status", ""), "warnings": warnings,
            })
    return comparisons
