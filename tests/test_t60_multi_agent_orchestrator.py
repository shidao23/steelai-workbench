from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steelai.governance import GovernanceError, digest_value, verify_package
from steelai.multi_agent_orchestrator import (
    EvidenceReference,
    HumanCheckpointDecision,
    MaterialsMultiAgentOrchestrator,
    WORKFLOW_SEQUENCE,
    run_t60_demo,
    validate_multi_agent_contract,
)


STAMP = "2026-09-10T00:00:00+00:00"


def evidence() -> tuple[EvidenceReference, ...]:
    return (EvidenceReference("EVIDENCE-1", 1, digest_value({"fixture": 1}), "synthetic_demo_data"),)


def decisions(final: str = "approved") -> dict[str, HumanCheckpointDecision]:
    return {
        "plan_approval": HumanCheckpointDecision.create("plan_approval", "approved", "human-reviewer", "Plan reviewed.", decided_at=STAMP),
        "result_acceptance": HumanCheckpointDecision.create("result_acceptance", final, "human-reviewer", "Result reviewed.", decided_at=STAMP),
    }


class MultiAgentOrchestratorTests(unittest.TestCase):
    def test_contract_freezes_five_roles_permissions_and_checkpoints(self) -> None:
        result = validate_multi_agent_contract()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["role_count"], 5)
        self.assertEqual(result["checkpoint_count"], 2)

    def test_success_records_responsible_handoffs_and_verified_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = MaterialsMultiAgentOrchestrator(output_root=Path(temporary)).run(
                "Synthetic materials workflow", evidence(), decisions(), started_at=STAMP,
            )
            self.assertEqual(result.status, "complete")
            self.assertTrue(result.deterministic_outputs_ready)
            self.assertEqual([item.to_role for item in result.handoffs[1:5]], list(WORKFLOW_SEQUENCE[1:]))
            self.assertTrue(all(item.task_id and item.output_status and item.responsibility_role for item in result.handoffs))
            self.assertEqual(verify_package(result.audit_package).status, "passed")
            trace = json.loads((Path(result.audit_package) / "workflow_trace.json").read_text(encoding="utf-8"))
            self.assertNotIn("Synthetic materials workflow", json.dumps(trace))
            self.assertTrue(trace["human_decisions"])

    def test_missing_plan_decision_pauses_for_human_without_tools_after_planner(self) -> None:
        result = MaterialsMultiAgentOrchestrator(output_root=None).run(
            "Synthetic request", evidence(), {}, started_at=STAMP,
        )
        self.assertEqual(result.status, "needs_human")
        self.assertEqual(result.error_code, "GOV-APPROVAL-001")
        self.assertEqual([item.role_id for item in result.tool_calls], ["planner"])

    def test_human_can_reject_or_terminate_at_checkpoints(self) -> None:
        rejected = decisions()
        rejected["plan_approval"] = HumanCheckpointDecision.create("plan_approval", "rejected", "human-reviewer", "Out of scope.", decided_at=STAMP)
        result = MaterialsMultiAgentOrchestrator(output_root=None).run("Synthetic request", evidence(), rejected, started_at=STAMP)
        self.assertEqual(result.status, "rejected")
        terminated = decisions("terminated")
        result = MaterialsMultiAgentOrchestrator(output_root=None).run("Synthetic request", evidence(), terminated, started_at=STAMP)
        self.assertEqual(result.status, "blocked")
        self.assertIn("terminated", result.message)

    def test_ai_identity_cannot_approve_checkpoint(self) -> None:
        with self.assertRaises(GovernanceError) as context:
            HumanCheckpointDecision.create("plan_approval", "approved", "agent-planner", "Self approval.")
        self.assertEqual(context.exception.code, "GOV-AI-AUTH-001")

    def test_insufficient_evidence_is_a_frozen_failure_path(self) -> None:
        result = run_t60_demo("insufficient_evidence", output_root=None)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.error_code, "GOV-EVIDENCE-001")
        self.assertFalse(result.deterministic_outputs_ready)

    def test_tool_failure_retries_once_then_fails_closed(self) -> None:
        result = run_t60_demo("tool_failure", output_root=None)
        failures = [item for item in result.tool_calls if item.tool_name == "descriptive_statistics"]
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.error_code, "GOV-RUNTIME-001")
        self.assertEqual([item.attempt for item in failures], [1, 2])

    def test_reviewer_blocks_claim_without_registered_evidence(self) -> None:
        def executor(tool_name, payload):
            from steelai.multi_agent_orchestrator import _default_tool_executor
            if tool_name == "bounded_material_interpretation":
                return {"claims": [{"claim_id": "UNSUPPORTED", "text": "unsupported", "evidence_ids": []}], "limitations": []}
            return _default_tool_executor(tool_name, payload)

        result = MaterialsMultiAgentOrchestrator(output_root=None, tool_executor=executor).run(
            "Synthetic request", evidence(), decisions(), started_at=STAMP,
        )
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.error_code, "GOV-EVIDENCE-001")
        self.assertEqual(result.role_outputs["reviewer"]["unsupported_claims"], ["UNSUPPORTED"])
        self.assertFalse(result.role_outputs["reviewer"]["human_approval_authority"])

    def test_offline_cloud_keeps_deterministic_processing_and_trace(self) -> None:
        result = run_t60_demo("offline_success", output_root=None)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.cloud_status, "unavailable")
        self.assertEqual(result.interpretation_mode, "deterministic_fallback")
        self.assertTrue(result.deterministic_outputs_ready)
        self.assertIn("statistics", result.role_outputs["statistics_physics"])

    def test_audit_keeps_hashes_not_raw_tool_arguments_or_formal_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = MaterialsMultiAgentOrchestrator(output_root=Path(temporary)).run(
                "Private question text", evidence(), decisions(), started_at=STAMP,
            )
            persisted = "\n".join(path.read_text(encoding="utf-8") for path in Path(result.audit_package).glob("*.json"))
            self.assertNotIn("Private question text", persisted)
            self.assertNotIn('"arguments"', persisted)
            self.assertIn('"formal_write_performed": false', persisted)


if __name__ == "__main__":
    unittest.main()
