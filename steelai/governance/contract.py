"""Loader and structural validator for the frozen T50 governance contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .serialization import digest_value


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config" / "global_research_governance_v1.0.json"

EXPECTED_STATES = {
    "draft",
    "needs_human",
    "approved",
    "running",
    "passed",
    "warning",
    "rejected",
    "blocked",
    "complete",
    "invalidated",
}
EXPECTED_WORKSPACES = {
    "data_intake",
    "physics_engine",
    "traceable_statistics",
    "ebsd_sem",
    "research_agent",
    "model_laboratory",
    "automation_tasks",
    "research_session",
    "portfolio",
}


def _read_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("governance contract top level must be an object")
    return value


def validate_governance_contract(path: str | Path = CONTRACT_PATH) -> dict[str, Any]:
    contract_path = Path(path)
    problems: list[str] = []
    try:
        contract = _read_contract(contract_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "contract_id": None,
            "contract_sha256": None,
            "problems": [f"contract cannot be read: {exc}"],
        }

    if contract.get("contract_id") != "SteelAI-Global-Research-Governance-v1.0":
        problems.append("unexpected contract_id")
    if contract.get("schema_version") != "1.0" or contract.get("status") != "frozen":
        problems.append("contract must be frozen schema version 1.0")
    if set(contract.get("states", {})) != EXPECTED_STATES:
        problems.append("global state vocabulary is incomplete or changed")
    scope = contract.get("scope", {}).get("applies_to", [])
    if set(scope) != EXPECTED_WORKSPACES or len(scope) != len(EXPECTED_WORKSPACES):
        problems.append("workspace scope must contain exactly the nine frozen workspaces")

    transitions = contract.get("allowed_transitions", [])
    pairs: set[tuple[str, str]] = set()
    for item in transitions:
        if not isinstance(item, dict):
            problems.append("state transition must be an object")
            continue
        pair = (str(item.get("from")), str(item.get("to")))
        if pair in pairs:
            problems.append(f"duplicate state transition: {pair[0]}->{pair[1]}")
        pairs.add(pair)
        if pair[0] not in EXPECTED_STATES or pair[1] not in EXPECTED_STATES:
            problems.append(f"unknown state in transition: {pair[0]}->{pair[1]}")
        if not item.get("actor") or not item.get("guard"):
            problems.append(f"transition lacks actor or guard: {pair[0]}->{pair[1]}")
    if {source for source, target in pairs if target == "running"} != {"approved"}:
        problems.append("running must only be reachable from approved")

    trigger_codes: list[str] = []
    for key, expected_state, recovery_key in (
        ("needs_human_triggers", "needs_human", "resolution"),
        ("blocked_triggers", "blocked", "recovery"),
    ):
        for item in contract.get(key, []):
            if not isinstance(item, dict):
                problems.append(f"{key} entries must be objects")
                continue
            trigger_codes.append(str(item.get("code", "")))
            if item.get("state") != expected_state or not item.get("trigger") or not item.get(recovery_key):
                problems.append(f"incomplete {expected_state} trigger: {item.get('code')}")
    if not trigger_codes or len(trigger_codes) != len(set(trigger_codes)):
        problems.append("governance trigger codes must be present and unique")

    levels = contract.get("result_levels", {})
    classes = contract.get("evidence_classes", {})
    if not levels or not classes:
        problems.append("result levels and evidence classes are required")
    for workspace in contract.get("workspaces", []):
        if not set(workspace.get("governed_states", [])).issubset(EXPECTED_STATES):
            problems.append(f"workspace has unknown state: {workspace.get('workspace_id')}")
        if not set(workspace.get("result_levels", [])).issubset(levels):
            problems.append(f"workspace has unknown result level: {workspace.get('workspace_id')}")

    return {
        "status": "passed" if not problems else "failed",
        "contract_id": contract.get("contract_id"),
        "contract_sha256": digest_value(contract),
        "workspace_count": len(contract.get("workspaces", [])),
        "state_count": len(contract.get("states", {})),
        "problems": problems,
    }


def load_governance_contract(path: str | Path = CONTRACT_PATH) -> dict[str, Any]:
    report = validate_governance_contract(path)
    if report["status"] != "passed":
        raise ValueError("invalid governance contract: " + "; ".join(report["problems"]))
    return _read_contract(Path(path))
