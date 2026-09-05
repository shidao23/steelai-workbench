from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from steelai.paths import ROOT


REGISTRY_PATH = ROOT / "config" / "third_party_candidates_v1.0.json"
ALLOWED_LICENSES = {"MIT", "Apache-2.0"}
ALLOWED_DECISIONS = {"selected_for_t14_evaluation", "reference_only", "deferred", "rejected_now"}
REQUIRED_FIELDS = {
    "candidate_id", "project", "feature_considered", "version_ref", "source_ref",
    "official_repo", "release_url", "license_spdx", "license_url", "license_status",
    "runtime_fit", "dependency_impact", "decision", "decision_reason", "t14_eligible",
    "code_imported",
}


def load_third_party_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Third-party registry must be a JSON object.")
    return value


def validate_third_party_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = load_third_party_registry(path)
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    if registry.get("registry_id") != "SteelAI-ThirdParty-Candidates-v1.0":
        add("Unexpected third-party registry_id.")
    if registry.get("schema_version") != "1.0" or registry.get("stage") != "T13_governance_only":
        add("T13 registry must use schema v1.0 and governance-only stage.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(registry.get("reviewed_at", ""))):
        add("Registry review date is missing or invalid.")

    policy = registry.get("policy", {})
    if policy.get("unknown_license") != "reject":
        add("Unknown licenses must be rejected.")
    if policy.get("non_open_or_source_available_only") != "do_not_copy":
        add("Non-open or source-available-only code must not be copied.")
    if "pin_exact" not in str(policy.get("version_rule", "")):
        add("Exact release and source pinning is required.")
    if "optional_adapter" not in str(policy.get("architecture_rule", "")):
        add("Third-party functionality must remain an optional adapter.")

    candidates = registry.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) < 5:
        add("At least five bounded candidates must be recorded.")
        candidates = candidates if isinstance(candidates, list) else []
    candidate_ids = [item.get("candidate_id") for item in candidates if isinstance(item, dict)]
    if len(candidate_ids) != len(candidates) or len(set(candidate_ids)) != len(candidate_ids):
        add("Candidate IDs must be present and unique.")

    selected = []
    for item in candidates:
        if not isinstance(item, dict):
            add("Candidate entries must be objects.")
            continue
        candidate_id = str(item.get("candidate_id", "<missing>"))
        missing = sorted(field for field in REQUIRED_FIELDS if field not in item)
        if missing:
            add(f"{candidate_id}: missing fields {missing}.")
            continue
        version = str(item["version_ref"])
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            add(f"{candidate_id}: version_ref must be an exact numeric release.")
        if not re.fullmatch(r"[0-9a-f]{7,40}", str(item["source_ref"])):
            add(f"{candidate_id}: source_ref must be a pinned Git commit prefix or SHA.")
        for field in ("official_repo", "release_url", "license_url"):
            if not str(item[field]).startswith("https://"):
                add(f"{candidate_id}: {field} must be an HTTPS official source.")
        if version not in str(item["release_url"]):
            add(f"{candidate_id}: release URL does not contain the pinned version.")
        if item["license_spdx"] not in ALLOWED_LICENSES or item["license_status"] != "verified_osi":
            add(f"{candidate_id}: license is not verified against the allowed OSI list.")
        if item["decision"] not in ALLOWED_DECISIONS:
            add(f"{candidate_id}: unsupported decision {item['decision']}.")
        if item["code_imported"] is not False:
            add(f"{candidate_id}: T13 must not import third-party code.")
        if item["decision"] == "selected_for_t14_evaluation":
            selected.append(candidate_id)
            if item["t14_eligible"] is not True:
                add(f"{candidate_id}: selected candidate must be T14 eligible.")
        elif item["t14_eligible"] is not False:
            add(f"{candidate_id}: only the selected candidate may be T14 eligible.")

    if selected != ["frictionless-data-package"]:
        add("T13 must select exactly the bounded Frictionless Data Package evaluation for T14.")
    gx = next((item for item in candidates if item.get("candidate_id") == "great-expectations-validation"), {})
    if gx.get("decision") != "rejected_now" or "<3.14" not in str(gx.get("runtime_fit", "")):
        add("Great Expectations must record the current Python 3.14 incompatibility and rejection.")

    return {
        "schema_version": "1.0",
        "registry_id": registry.get("registry_id"),
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "candidate_count": len(candidates),
        "selected_for_t14": selected,
        "reviewed_at": registry.get("reviewed_at"),
        "code_imported": any(item.get("code_imported") is True for item in candidates if isinstance(item, dict)),
    }
