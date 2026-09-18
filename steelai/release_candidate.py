"""T57 release-candidate contract and fail-closed validation."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from steelai import __version__


ROOT = Path(__file__).resolve().parents[1]
RELEASE_CONTRACT = ROOT / "config" / "release_candidate_v0.2.json"
EXPECTED_RELEASE_ID = "SteelAI-Workbench-v0.2.0-rc1"
EXPECTED_VERSION = "0.2.0rc1"
EXPECTED_WORKSPACES = (
    "data_intake",
    "physics_engine",
    "traceable_statistics",
    "ebsd_sem",
    "research_agent",
    "model_laboratory",
    "automation_tasks",
    "research_session",
    "portfolio",
)
EXPECTED_SCENARIOS = (
    "success",
    "missing_field",
    "unknown_unit",
    "identity_conflict",
    "duplicate_write",
    "unapproved_execution",
    "tampering",
    "privacy_leak",
)
ALLOWED_WORKSPACE_STATUSES = {"complete", "deferred"}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("release contract must be a JSON object")
    return data


def _safe_relative_path(value: Any) -> str | None:
    text = str(value or "").replace("\\", "/")
    candidate = PurePosixPath(text)
    if not text or candidate.is_absolute() or ".." in candidate.parts or ":" in text:
        return None
    return candidate.as_posix()


def _referenced_path(value: Any) -> str | None:
    return _safe_relative_path(str(value or "").split("::", 1)[0])


def validate_release_candidate(
    contract_path: Path = RELEASE_CONTRACT,
    *,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    problems: list[str] = []

    def add(problem: str) -> None:
        if problem not in problems:
            problems.append(problem)

    try:
        contract = _read_json(contract_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "1.0",
            "status": "failed",
            "release_id": "",
            "product_version": "",
            "contract_sha256": "",
            "workspace_count": 0,
            "deferred_workspaces": [],
            "scenario_count": 0,
            "problems": [f"release_contract_unreadable:{type(exc).__name__}"],
        }

    if contract.get("schema_version") != "1.0":
        add("schema_version must be 1.0")
    if contract.get("release_id") != EXPECTED_RELEASE_ID:
        add("release_id is not the frozen v0.2 candidate")
    if contract.get("product_version") != EXPECTED_VERSION or __version__ != EXPECTED_VERSION:
        add("product version and runtime version must both equal 0.2.0rc1")
    if contract.get("stage") != "T57" or contract.get("status") != "frozen_candidate":
        add("stage/status must be T57/frozen_candidate")

    boundary = contract.get("evidence_boundary", {})
    if not isinstance(boundary, dict):
        add("evidence_boundary must be an object")
        boundary = {}
    if boundary.get("public_repository") != "synthetic_and_documentation_only":
        add("public repository evidence boundary is not frozen")
    if boundary.get("real_research_data_included") is not False:
        add("release candidate must not include real research data")
    if boundary.get("cloud_ai_required_for_validation") is not False:
        add("release validation must remain offline")

    governance_path = repository_root / "config" / "global_research_governance_v1.0.json"
    try:
        governance = _read_json(governance_path)
        target_chains = {
            item["workspace_id"]: item["target_chain"]
            for item in governance.get("workspaces", [])
            if isinstance(item, dict) and item.get("workspace_id")
        }
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        target_chains = {}
        add("global governance workspace matrix is unreadable")

    raw_workspaces = contract.get("workspaces", [])
    if not isinstance(raw_workspaces, list):
        raw_workspaces = []
        add("workspaces must be a list")
    workspace_ids = [str(item.get("workspace_id", "")) for item in raw_workspaces if isinstance(item, dict)]
    if tuple(workspace_ids) != EXPECTED_WORKSPACES:
        add("release candidate must contain the nine frozen workspaces in contract order")
    deferred: list[str] = []
    for item in raw_workspaces:
        if not isinstance(item, dict):
            add("every workspace entry must be an object")
            continue
        workspace_id = str(item.get("workspace_id", ""))
        status = str(item.get("status", ""))
        if status not in ALLOWED_WORKSPACE_STATUSES:
            add(f"{workspace_id}: unsupported workspace status")
        if item.get("target_chain") != target_chains.get(workspace_id):
            add(f"{workspace_id}: target chain differs from global governance")
        if not str(item.get("limitations", "")).strip():
            add(f"{workspace_id}: limitations are required")
        if status == "deferred":
            deferred.append(workspace_id)
            if not str(item.get("defer_reason", "")).strip() or not str(item.get("planned_task", "")).strip():
                add(f"{workspace_id}: deferred status requires reason and planned task")
        for field in ("implementation_evidence", "verification_evidence"):
            references = item.get(field, [])
            if not isinstance(references, list) or not references:
                add(f"{workspace_id}: {field} must be non-empty")
                continue
            for reference in references:
                relative = _referenced_path(reference)
                if relative is None or not (repository_root / relative).is_file():
                    add(f"{workspace_id}: invalid or missing evidence reference")

    raw_scenarios = contract.get("regression_scenarios", [])
    if not isinstance(raw_scenarios, list):
        raw_scenarios = []
        add("regression_scenarios must be a list")
    scenario_ids = [str(item.get("scenario_id", "")) for item in raw_scenarios if isinstance(item, dict)]
    if tuple(scenario_ids) != EXPECTED_SCENARIOS:
        add("regression matrix must cover the eight frozen scenarios in contract order")
    for item in raw_scenarios:
        if not isinstance(item, dict) or not isinstance(item.get("tests"), list) or not item["tests"]:
            add("every regression scenario requires test evidence")
            continue
        for reference in item["tests"]:
            relative = _referenced_path(reference)
            if relative is None or not (repository_root / relative).is_file():
                add("regression matrix contains an invalid or missing test reference")

    for entry in contract.get("offline_degradation", []):
        if not isinstance(entry, dict) or not entry.get("component") or not entry.get("expected"):
            add("offline degradation entries require component and expected behavior")
            continue
        for reference in entry.get("tests", []):
            relative = _referenced_path(reference)
            if relative is None or not (repository_root / relative).is_file():
                add("offline degradation contains an invalid or missing test reference")

    required_documents = contract.get("required_documents", [])
    if not isinstance(required_documents, list) or not required_documents:
        add("required_documents must be non-empty")
    else:
        for reference in required_documents:
            relative = _safe_relative_path(reference)
            if relative is None or not (repository_root / relative).is_file():
                add("release candidate contains an invalid or missing required document")

    thresholds = contract.get("acceptance_thresholds", {})
    if not isinstance(thresholds, dict):
        add("acceptance_thresholds must be an object")
        thresholds = {}
    if thresholds.get("minimum_test_count") != 147:
        add("minimum_test_count must preserve the T57 baseline of 147")
    if thresholds.get("maximum_test_failures") != 0 or thresholds.get("privacy_findings") != 0:
        add("release candidate must allow zero test failures and zero privacy findings")
    if thresholds.get("required_workspace_count") != 9:
        add("required_workspace_count must be 9")

    canonical = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "1.0",
        "status": "passed" if not problems else "failed",
        "release_id": contract.get("release_id", ""),
        "product_version": contract.get("product_version", ""),
        "contract_sha256": sha256(canonical).hexdigest(),
        "workspace_count": len(raw_workspaces),
        "deferred_workspaces": deferred,
        "scenario_count": len(raw_scenarios),
        "problems": problems,
    }


def main() -> int:
    result = validate_release_candidate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
