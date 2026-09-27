"""SteelAI read-only research tool catalog and execution entry point.

This module is the single implementation home for the audited read-only research
tools published to the Research Agent, the DSH read-only bridge, and the T61
governed protocol layer.

Dependency direction: this tool boundary -> deterministic SteelAI capability modules.
It must never import ``steelai.research_agent`` (or any agent/transport adapter),
so that the tool boundary stays independent of any specific model client.
"""
from __future__ import annotations

import json
from typing import Any

from steelai.analysis import build_rule_report
from steelai.automation import AUTODIMPLE_RESULT_ROOT
from steelai.data import numeric, read_rows, sample_bundle
from steelai.ebsd import read_highres_comparison, read_matched_comparison
from steelai.evidence_validation import agent_validation_payload
from steelai.physics import calculate_all
from steelai.thermal_softening_case import load_softening_case


__all__ = ["TOOL_DEFINITIONS", "TOOL_FUNCTIONS", "execute_readonly_tool"]


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_samples",
        "description": "List processed sample IDs and table completeness. Returns structured metadata only; never raw files.",
        "parameters": _empty_schema(),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_sample_bundle",
        "description": "Read the processed composition, process, microstructure and properties rows for one sample. Returns evidence table names and structured fields.",
        "parameters": {
            "type": "object",
            "properties": {"sample_id": {"type": "string", "description": "Exact sample ID returned by list_samples."}},
            "required": ["sample_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "compare_samples",
        "description": "Build the deterministic evidence-bounded comparison of two processed samples. Returns facts, judgments, hypotheses, actions and limitations separately.",
        "parameters": {
            "type": "object",
            "properties": {
                "control_id": {"type": "string", "description": "Control sample ID."},
                "comparison_id": {"type": "string", "description": "Comparison sample ID."},
            },
            "required": ["control_id", "comparison_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "calculate_physics_card",
        "description": "Calculate empirical Ms, Ac1, Ac3, Tnr, Ceq and Pcm estimates from one processed composition. Results include formula source, review status and warnings; all values are model estimates.",
        "parameters": {
            "type": "object",
            "properties": {"sample_id": {"type": "string", "description": "Exact sample ID."}},
            "required": ["sample_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_ebsd_summary",
        "description": "Read an existing acquisition-matched B/R EBSD comparison. Low- and high-resolution groups remain separate and must never be pooled.",
        "parameters": {
            "type": "object",
            "properties": {
                "scale": {
                    "type": "string",
                    "enum": ["low_resolution", "high_resolution"],
                    "description": "Use low_resolution for about 1000x/0.5 um or high_resolution for about 2000x/0.15 um.",
                }
            },
            "required": ["scale"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_autodimple_summary",
        "description": "Read the existing B/R AutoDimple comparison and its image-level interpretation boundary. Does not run segmentation.",
        "parameters": _empty_schema(),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_evidence_validation_summary",
        "description": "Read the deterministic B/R evidence registry, claim validation matrix and scientific gates. Contains no raw paths or original files.",
        "parameters": _empty_schema(),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_thermal_softening_case",
        "description": "Read a hash-verified, approved-data double-hit softening case with literature references and QC warnings. It is an analysis draft, not a final scientific conclusion.",
        "parameters": {
            "type": "object",
            "properties": {"case_id": {"type": "string", "description": "Exact TSC case ID."}},
            "required": ["case_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _require_sample(sample_id: str) -> dict[str, dict[str, str]]:
    bundle = sample_bundle(sample_id)
    if not bundle.get("samples"):
        raise ValueError(f"Unknown sample_id: {sample_id}")
    return bundle


def _sanitize_for_model(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_for_model(item)
            for key, item in value.items()
            if "path" not in key.lower() and "file" not in key.lower()
        }
    if isinstance(value, list):
        return [_sanitize_for_model(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_model(item) for item in value]
    return value


def _list_samples() -> dict[str, Any]:
    tables = ("samples", "composition", "process", "microstructure", "properties")
    result = []
    for row in read_rows("samples"):
        sample_id = row.get("sample_id", "")
        bundle = sample_bundle(sample_id)
        result.append({
            "sample_id": sample_id,
            "steel": row.get("steel", ""),
            "condition": row.get("condition", ""),
            "data_status": row.get("data_status", ""),
            "tables_present": [name for name in tables if bool(bundle.get(name))],
            "tables_missing": [name for name in tables if not bundle.get(name)],
        })
    return {"samples": result, "count": len(result), "source": "data/processed/*.csv"}


def _get_sample_bundle(sample_id: str) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "data": _sanitize_for_model(_require_sample(sample_id)),
        "evidence": [
            "data/processed/samples.csv",
            "data/processed/composition.csv",
            "data/processed/process.csv",
            "data/processed/microstructure.csv",
            "data/processed/properties.csv",
        ],
    }


def _compare_samples(control_id: str, comparison_id: str) -> dict[str, Any]:
    report = build_rule_report(_require_sample(control_id), _require_sample(comparison_id))
    payload = report.to_dict()
    payload.pop("narrative", None)
    payload["evidence"] = {"control": control_id, "comparison": comparison_id, "method": "offline_rules"}
    return payload


def _calculate_physics_card(sample_id: str) -> dict[str, Any]:
    bundle = _require_sample(sample_id)
    composition_row = bundle["composition"]
    composition = {
        key: number
        for key, raw in composition_row.items()
        if key not in {"sample_id", "source_status"} and (number := numeric(raw)) is not None
    }
    results = [item.to_dict() for item in calculate_all(composition, set(composition))]
    return {
        "sample_id": sample_id,
        "engine": "SteelAI Physics Model Registry v1.0",
        "model_count": len(results),
        "result_type": "empirical_model_estimates_not_experimental_truth",
        "results": results,
        "evidence": "data/processed/composition.csv",
    }


def _get_ebsd_summary(scale: str) -> dict[str, Any]:
    if scale == "low_resolution":
        data = read_matched_comparison()
        acquisition = "about 1000x / 0.5 um"
    elif scale == "high_resolution":
        data = read_highres_comparison()
        acquisition = "about 2000x / 0.15 um"
    else:
        raise ValueError(f"Unsupported EBSD scale: {scale}")
    if not data:
        return {"scale": scale, "available": False, "message": "No completed comparison is available."}
    return {
        "scale": scale,
        "acquisition_group": acquisition,
        "available": True,
        "comparison": _sanitize_for_model(data),
        "boundary": "One EBSD field per condition is directional evidence, not an independent specimen-level inference.",
    }


def _get_autodimple_summary() -> dict[str, Any]:
    manifest_path = AUTODIMPLE_RESULT_ROOT / "batch_manifest_v0.1.json"
    comparison_path = AUTODIMPLE_RESULT_ROOT / "br_comparison_v0.1.json"
    if not manifest_path.exists() or not comparison_path.exists():
        return {"available": False, "message": "No completed AutoDimple comparison is available."}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "standard_id": manifest.get("standard_id"),
        "image_count": manifest.get("image_count"),
        "status": manifest.get("status"),
        "comparison": _sanitize_for_model(comparison),
        "boundary": "Image-level bootstrap is descriptive; fields and segmented objects are not independent specimen replicates.",
    }


TOOL_FUNCTIONS = {
    "list_samples": _list_samples,
    "get_sample_bundle": _get_sample_bundle,
    "compare_samples": _compare_samples,
    "calculate_physics_card": _calculate_physics_card,
    "get_ebsd_summary": _get_ebsd_summary,
    "get_autodimple_summary": _get_autodimple_summary,
    "get_evidence_validation_summary": agent_validation_payload,
    "get_thermal_softening_case": load_softening_case,
}


def execute_readonly_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ValueError(f"Unknown or non-whitelisted tool: {name}")
    return _sanitize_for_model(function(**arguments))
