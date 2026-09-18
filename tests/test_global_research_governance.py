"""T50 acceptance tests for the frozen global research-governance contract."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "global_research_governance_v1.0.json"
SPEC_PATH = ROOT / "docs" / "T50_GLOBAL_RESEARCH_GOVERNANCE.md"

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
EXPECTED_EVIDENCE_CLASSES = {
    "real_research_data",
    "synthetic_demo_data",
    "model_output",
    "human_conclusion",
}


class GlobalResearchGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_is_frozen_and_scope_is_exact(self) -> None:
        self.assertEqual(self.contract["contract_id"], "SteelAI-Global-Research-Governance-v1.0")
        self.assertEqual(self.contract["schema_version"], "1.0")
        self.assertEqual(self.contract["task_id"], "T50")
        self.assertEqual(self.contract["status"], "frozen")
        self.assertEqual(set(self.contract["scope"]["applies_to"]), EXPECTED_WORKSPACES)
        self.assertEqual(
            self.contract["scope"]["preconditions"],
            {"T40": "done", "T41": "done", "T42": "canceled", "T43": "canceled"},
        )

    def test_state_machine_has_one_approved_execution_gate(self) -> None:
        self.assertEqual(set(self.contract["states"]), EXPECTED_STATES)
        transitions = {
            (item["from"], item["to"]): item for item in self.contract["allowed_transitions"]
        }
        self.assertEqual(len(transitions), len(self.contract["allowed_transitions"]))
        for item in transitions.values():
            self.assertIn(item["from"], EXPECTED_STATES)
            self.assertIn(item["to"], EXPECTED_STATES)
            self.assertTrue(item["actor"])
            self.assertTrue(item["guard"])
        self.assertIn(("approved", "running"), transitions)
        self.assertNotIn(("draft", "running"), transitions)
        self.assertNotIn(("needs_human", "running"), transitions)
        self.assertNotIn(("blocked", "complete"), transitions)
        self.assertIn(("complete", "invalidated"), transitions)
        incoming_running = {source for source, target in transitions if target == "running"}
        self.assertEqual(incoming_running, {"approved"})

    def test_every_human_and_blocked_trigger_is_explicit(self) -> None:
        all_codes: list[str] = []
        for item in self.contract["needs_human_triggers"]:
            self.assertEqual(item["state"], "needs_human")
            self.assertTrue(item["trigger"])
            self.assertTrue(item["resolution"])
            all_codes.append(item["code"])
        for item in self.contract["blocked_triggers"]:
            self.assertEqual(item["state"], "blocked")
            self.assertTrue(item["trigger"])
            self.assertTrue(item["recovery"])
            all_codes.append(item["code"])
        self.assertGreaterEqual(len(self.contract["needs_human_triggers"]), 8)
        self.assertGreaterEqual(len(self.contract["blocked_triggers"]), 12)
        self.assertEqual(len(all_codes), len(set(all_codes)))

    def test_evidence_classes_cannot_be_conflated(self) -> None:
        classes = self.contract["evidence_classes"]
        self.assertEqual(set(classes), EXPECTED_EVIDENCE_CLASSES)
        self.assertTrue(classes["real_research_data"]["may_be_presented_as_experimental_truth"])
        self.assertFalse(classes["synthetic_demo_data"]["formal_evidence_eligible"])
        self.assertFalse(classes["synthetic_demo_data"]["may_be_presented_as_experimental_truth"])
        self.assertFalse(classes["model_output"]["formal_evidence_eligible"])
        self.assertFalse(classes["model_output"]["may_be_presented_as_experimental_truth"])
        self.assertFalse(classes["human_conclusion"]["may_be_presented_as_experimental_truth"])
        for details in classes.values():
            self.assertTrue(details["required_labels"])
            self.assertTrue(details["guard"])

    def test_object_identity_and_approval_are_hash_bound(self) -> None:
        identity = self.contract["research_object_identity"]
        identity_fields = set(identity["required_identity_fields"])
        self.assertTrue({"object_type", "object_id", "revision", "content_digest"}.issubset(identity_fields))
        object_types = [item["object_type"] for item in identity["objects"]]
        self.assertEqual(len(object_types), len(set(object_types)))
        self.assertTrue({"sample", "specimen", "source", "result", "evidence", "approval"}.issubset(object_types))

        approval_fields = set(self.contract["approval_record"]["required_fields"])
        self.assertTrue(
            {
                "approval_id",
                "object_type",
                "object_id",
                "object_revision",
                "object_digest",
                "decision",
                "reviewer_id",
                "decided_at",
                "scope",
                "rationale",
                "governance_contract_id",
            }.issubset(approval_fields)
        )
        approval_rules = " ".join(self.contract["approval_record"]["rules"])
        self.assertIn("cannot be reviewer_id", approval_rules)
        self.assertIn("invalidates the approval", approval_rules)
        self.assertIn("append-only", approval_rules)

    def test_formal_write_conditions_are_complete_and_fail_closed(self) -> None:
        conditions = {
            item["condition_id"]: item["requirement"]
            for item in self.contract["formal_write_conditions"]
        }
        self.assertEqual(
            set(conditions),
            {
                "FW-IDENTITY",
                "FW-SOURCE",
                "FW-SCHEMA",
                "FW-APPROVAL",
                "FW-QC",
                "FW-PROVENANCE",
                "FW-INTEGRITY",
                "FW-CLASS",
                "FW-APPEND",
                "FW-STATE",
            },
        )
        self.assertEqual(self.contract["principles"]["failure_policy"], "fail_closed")
        self.assertIn("append_only", self.contract["principles"]["formal_write_policy"])
        self.assertIn("synthetic data", conditions["FW-CLASS"])

    def test_nine_workspaces_have_chain_gate_and_common_mapping(self) -> None:
        workspaces = self.contract["workspaces"]
        ids = [item["workspace_id"] for item in workspaces]
        self.assertEqual(len(ids), 9)
        self.assertEqual(set(ids), EXPECTED_WORKSPACES)
        self.assertEqual(len(ids), len(set(ids)))
        result_levels = set(self.contract["result_levels"])
        for workspace in workspaces:
            self.assertTrue(workspace["current_entry_points"])
            self.assertTrue(workspace["current_outputs"])
            self.assertTrue(workspace["current_state_vocabulary"])
            self.assertTrue(workspace["target_chain"])
            self.assertGreaterEqual(len(workspace["target_chain"]), 3)
            self.assertTrue(workspace["primary_human_gate"])
            self.assertTrue(set(workspace["governed_states"]).issubset(EXPECTED_STATES))
            self.assertTrue(set(workspace["result_levels"]).issubset(result_levels))

    def test_component_responsibilities_are_separated(self) -> None:
        matrix = {item["component"]: item for item in self.contract["responsibility_matrix"]}
        self.assertEqual(
            set(matrix),
            {
                "SteelData",
                "SteelStats",
                "SteelAI Workbench",
                "Research Agent",
                "Registered external tool",
                "Project owner or delegated human reviewer",
            },
        )
        for responsibility in matrix.values():
            self.assertTrue(responsibility["owns"])
            self.assertTrue(responsibility["does_not_own"])
            self.assertFalse(set(responsibility["owns"]) & set(responsibility["does_not_own"]))
        self.assertIn("approval", matrix["Research Agent"]["does_not_own"])
        self.assertIn("approval", matrix["Project owner or delegated human reviewer"]["owns"])
        self.assertIn("source_data_mutation", matrix["SteelStats"]["does_not_own"])

    def test_contract_contains_no_local_absolute_path_or_real_values(self) -> None:
        serialized = json.dumps(self.contract, ensure_ascii=False)
        self.assertNotIn("D:\\\\", serialized)
        self.assertNotIn("C:\\\\Users", serialized)
        self.assertNotIn("manual_extraction_verified", serialized)
        self.assertNotIn("verified_from_source_note", serialized)

    def test_human_readable_spec_covers_all_frozen_terms(self) -> None:
        text = SPEC_PATH.read_text(encoding="utf-8")
        for workspace in self.contract["workspaces"]:
            self.assertIn(workspace["label"], text)
        for state in EXPECTED_STATES:
            self.assertIn(f"`{state}`", text)
        for heading in ("四类内容必须分开", "全局状态机", "九个工作区覆盖矩阵", "责任矩阵"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
