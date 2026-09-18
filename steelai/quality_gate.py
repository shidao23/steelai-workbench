from __future__ import annotations

import json

from steelai.agent_evaluation import benchmark_contract
from steelai.agent_workflow_benchmark import validate_benchmark as validate_agent_workflow_benchmark
from steelai.graduation_data_contract import validate_graduation_contract
from steelai.frictionless_adapter import validate_frictionless_evaluation
from steelai.governance import validate_governance_contract
from steelai.multi_agent_orchestrator import validate_multi_agent_contract
from steelai.physics import validate_model_registry
from steelai.portfolio_release import validate_release_config as validate_portfolio_release
from steelai.public_release_audit import audit_public_candidate
from steelai.research_data_contract import validate_research_data_contract
from steelai.research_protocol import validate_protocol_contracts
from steelai.real_data_case import validate_real_data_case_contract
from steelai.release_candidate import validate_release_candidate
from steelai.research_session import validate_session_contract
from steelai.settings import load_settings
from steelai.third_party_registry import validate_third_party_registry
from steelai.thermal_simulation_analysis import load_double_hit_policy
from steelai.thermal_simulation_features import load_thermal_feature_policy
from steelai.thermal_softening_analysis import load_softening_method_registry


def run_quality_gate() -> dict:
    data_contract = validate_research_data_contract()
    graduation_contract = validate_graduation_contract()
    governance_contract = validate_governance_contract()
    frictionless_evaluation = validate_frictionless_evaluation()
    third_party_registry = validate_third_party_registry()
    physics_registry = validate_model_registry()
    research_sessions = validate_session_contract()
    agent_benchmark = benchmark_contract()
    agent_workflow_benchmark = validate_agent_workflow_benchmark()
    portfolio_release = validate_portfolio_release()
    public_candidate = audit_public_candidate()
    release_candidate = validate_release_candidate()
    multi_agent_contract = validate_multi_agent_contract()
    research_protocol = validate_protocol_contracts()
    real_data_case = validate_real_data_case_contract()
    double_hit_policy = load_double_hit_policy()
    thermal_feature_policy = load_thermal_feature_policy()
    softening_method_registry = load_softening_method_registry()
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
        "global_research_governance": governance_contract.get("status") == "passed",
        "frictionless_optional_adapter": frictionless_evaluation.get("status") == "passed",
        "third_party_registry": third_party_registry.get("status") == "passed",
        "physics_model_registry": physics_registry.get("status") == "passed",
        "research_session_contract": research_sessions.get("status") == "passed",
        "agent_benchmark_contract": agent_benchmark.get("status") == "passed",
        "t63_agent_workflow_benchmark": agent_workflow_benchmark.get("status") == "passed",
        "t64_portfolio_release_contract": portfolio_release.get("status") == "passed",
        "public_repository_candidate": public_candidate.get("status") == "passed",
        "release_candidate_v0_2": release_candidate.get("status") == "passed",
        "materials_multi_agent_contract": multi_agent_contract.get("status") == "passed",
        "research_mcp_a2a_protocol": research_protocol.get("status") == "passed",
        "t62_real_data_case_contract": real_data_case.get("status") == "passed",
        "t73_double_hit_processing_policy": bool(double_hit_policy.get("policy_id")),
        "t74_thermal_feature_policy": bool(thermal_feature_policy.get("feature_version")),
        "t75_softening_method_registry": bool(softening_method_registry.get("registry_id")),
        "privacy_contract": all(privacy_checks.values()),
    }
    return {
        "schema_version": "2.0",
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
        "global_research_governance": governance_contract,
        "frictionless_optional_adapter": frictionless_evaluation,
        "third_party_registry": third_party_registry,
        "physics_model_registry": physics_registry,
        "research_session_contract": research_sessions,
        "agent_benchmark": {
            "benchmark_id": agent_benchmark.get("benchmark_id"),
            "case_count": agent_benchmark.get("case_count"),
            "problems": agent_benchmark.get("problems", []),
        },
        "t63_agent_workflow_benchmark": agent_workflow_benchmark,
        "t64_portfolio_release_contract": portfolio_release,
        "public_repository_candidate": public_candidate,
        "release_candidate": release_candidate,
        "materials_multi_agent_contract": multi_agent_contract,
        "research_mcp_a2a_protocol": research_protocol,
        "t62_real_data_case_contract": real_data_case,
        "t73_double_hit_processing_policy": {
            "status": "passed",
            "policy_id": double_hit_policy.get("policy_id"),
            "source_status": double_hit_policy.get("source_status"),
            "formal_result_requires_human_review": double_hit_policy.get("analysis", {}).get(
                "formal_result_requires_human_review"
            ),
        },
        "t74_thermal_feature_policy": {
            "status": "passed",
            "feature_version": thermal_feature_policy.get("feature_version"),
            "target_local_true_strains": thermal_feature_policy.get("target_local_true_strains"),
            "formal_write_requires_human_review": thermal_feature_policy.get("formal_write", {}).get(
                "requires_named_human_segment_review"
            ),
        },
        "t75_softening_method_registry": {
            "status": "passed",
            "registry_id": softening_method_registry.get("registry_id"),
            "result_version": softening_method_registry.get("result_version"),
            "selection_status": softening_method_registry.get("selection_status"),
            "selected_method_id": softening_method_registry.get("selected_method_id"),
            "sensitivity_method_id": softening_method_registry.get("sensitivity_method_id"),
            "method_count": len(softening_method_registry.get("methods", [])),
        },
    }


def main() -> int:
    result = run_quality_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
