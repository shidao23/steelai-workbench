from __future__ import annotations

import json

from steelai.agent_evaluation import benchmark_contract
from steelai.research_data_contract import validate_research_data_contract
from steelai.settings import load_settings


def run_quality_gate() -> dict:
    data_contract = validate_research_data_contract()
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
        "agent_benchmark_contract": agent_benchmark.get("status") == "passed",
        "privacy_contract": all(privacy_checks.values()),
    }
    return {
        "schema_version": "1.0",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "privacy_checks": privacy_checks,
        "research_data_contract": {
            "contract_id": data_contract.get("contract_id"),
            "problems": data_contract.get("problems", []),
            "scientific_readiness": data_contract.get("scientific_readiness", {}),
        },
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
