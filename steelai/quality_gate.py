from __future__ import annotations

import json

from steelai.agent_evaluation import benchmark_contract
from steelai.graduation_data_contract import validate_graduation_contract
from steelai.frictionless_adapter import validate_frictionless_evaluation
from steelai.physics import validate_model_registry
from steelai.research_data_contract import validate_research_data_contract
from steelai.research_session import validate_session_contract
from steelai.settings import load_settings
from steelai.third_party_registry import validate_third_party_registry


def run_quality_gate() -> dict:
    data_contract = validate_research_data_contract()
    graduation_contract = validate_graduation_contract()
    frictionless_evaluation = validate_frictionless_evaluation()
    third_party_registry = validate_third_party_registry()
    physics_registry = validate_model_registry()
    research_sessions = validate_session_contract()
    agent_benchmark = benchmark_contract()
    settings = load_settings()
    ai = settings.get("ai", {})
    privacy_checks = {
        "structured_data_only": bool(ai.get("structured_data_only", False)),
        "api_key_uses_environment_variable": str(ai.get("api_key_env", "")).endswith("_API_KEY"),
        "experiments_1_14_excluded": "experiments_1_14"
        in data_contract.get("scope", {}).get("excluded_datasets", []),
        "raw_source_of_truth_is_external_read_only": data_contract.get("scope", {}).get("source_of_truth")
        == "external_raw_experiment_folders_read_only",
    }
    checks = {
        "research_data_contract": data_contract.get("contract_status") == "passed",
        "graduation_data_contract": graduation_contract.get("status") == "passed",
        "frictionless_optional_adapter": frictionless_evaluation.get("status") == "passed",
        "third_party_registry": third_party_registry.get("status") == "passed",
        "physics_model_registry": physics_registry.get("status") == "passed",
        "research_session_contract": research_sessions.get("status") == "passed",
        "agent_benchmark_contract": agent_benchmark.get("status") == "passed",
        "privacy_contract": all(privacy_checks.values()),
    }
    return {
        "schema_version": "1.5",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "privacy_checks": privacy_checks,
        "research_data_contract": {
            "contract_id": data_contract.get("contract_id"),
            "problems": data_contract.get("problems", []),
            "scientific_readiness": data_contract.get("scientific_readiness", {}),
        },
        "graduation_data_contract": {
            "contract_id": graduation_contract.get("contract_id"),
            "contract_sha256": graduation_contract.get("contract_sha256"),
            "problems": graduation_contract.get("problems", []),
        },
        "frictionless_optional_adapter": frictionless_evaluation,
        "third_party_registry": third_party_registry,
        "physics_model_registry": physics_registry,
        "research_session_contract": research_sessions,
        "agent_benchmark": {
            "benchmark_id": agent_benchmark.get("benchmark_id"),
            "case_count": agent_benchmark.get("case_count"),
            "problems": agent_benchmark.get("problems", []),
        },
    }


def main() -> int:
    result = run_quality_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
