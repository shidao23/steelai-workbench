from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from steelai.governance import GovernanceError, digest_value, verify_package
from steelai.research_protocol import (
    A2ATaskEnvelope,
    GovernedResearchToolLayer,
    ProtocolEvidenceReference,
    TaskApprovalPermit,
    make_tool_request,
    run_t61_handoff_demo,
    validate_protocol_contracts,
)


ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-09-10T00:00:00+00:00"


def reference() -> ProtocolEvidenceReference:
    return ProtocolEvidenceReference("SYNTH-EVIDENCE", 1, digest_value({"fixture": 1}), "synthetic_demo_data")


def task(receiver: str = "data_steward") -> A2ATaskEnvelope:
    sender = "planner" if receiver != "planner" else "reviewer"
    return A2ATaskEnvelope.create(sender, receiver, (reference(),), status="accepted", created_at=STAMP)


class ResearchProtocolTests(unittest.TestCase):
    def test_contracts_freeze_five_nonformal_tools_and_minimal_a2a(self) -> None:
        result = validate_protocol_contracts()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["tool_count"], 5)
        self.assertEqual(result["role_count"], 5)

    def test_a2a_contract_without_request_identity_fails_validation(self) -> None:
        contract = json.loads(
            (ROOT / "config" / "a2a_task_envelope_v1.0.json").read_text(encoding="utf-8")
        )
        contract["required_fields"].remove("request_id")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "a2a.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = validate_protocol_contracts(a2a_path=path)
        self.assertEqual(result["status"], "failed")
        self.assertIn("A2A required fields mismatch", result["problems"])

    def test_a2a_digest_detects_tampering_and_roles_are_registered(self) -> None:
        current = task()
        payload = current.to_dict()
        payload["result_summary"] = "tampered"
        with self.assertRaises(GovernanceError) as context:
            A2ATaskEnvelope.from_dict(payload)
        self.assertEqual(context.exception.code, "GOV-INTEGRITY-001")
        with self.assertRaises(GovernanceError):
            A2ATaskEnvelope.create("planner", "unknown-role", (reference(),))

    def test_unauthorized_role_and_missing_approval_fail_before_backend(self) -> None:
        calls = []
        layer = GovernedResearchToolLayer(output_root=None, backend=lambda name, args: calls.append((name, args)) or {})
        wrong_role = task("reviewer")
        with self.assertRaises(GovernanceError) as context:
            layer.execute("query_samples", make_tool_request(wrong_role.request_id, "IDEM-1", wrong_role, "v1", {}))
        self.assertEqual(context.exception.code, "GOV-AI-AUTH-001")
        analysis = task("statistics_physics")
        with self.assertRaises(GovernanceError) as context:
            layer.execute("run_descriptive_statistics", make_tool_request(analysis.request_id, "IDEM-2", analysis, "v1", {"sample_ids": ["SYNTH-A"]}))
        self.assertEqual(context.exception.code, "GOV-APPROVAL-001")
        self.assertEqual(calls, [])

    def test_success_receipt_traces_task_input_version_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layer = GovernedResearchToolLayer(output_root=Path(temporary), backend=lambda _name, _args: {"samples": [], "count": 0})
            current = task("data_steward")
            result = layer.execute("query_samples", make_tool_request(current.request_id, "IDEM-TRACE", current, "registry-v7", {}))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["input_version"], "registry-v7")
            self.assertFalse(result["formal_result"])
            package = Path(temporary) / result["tool_call_id"]
            self.assertEqual(verify_package(package).status, "passed")
            receipt = json.loads((package / "tool_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["request_id"], current.request_id)
            self.assertEqual(receipt["task_id"], current.task_id)
            self.assertEqual(receipt["run_id"], result["run_id"])
            self.assertEqual(receipt["result_sha256"], result["result_sha256"])
            self.assertFalse(receipt["formal_write_performed"])

    def test_timeout_has_stable_error_receipt(self) -> None:
        manifest = json.loads((ROOT / "config" / "research_mcp_tools_v1.0.json").read_text(encoding="utf-8"))
        next(item for item in manifest["tools"] if item["tool_id"] == "query_samples")["timeout_ms"] = 100
        with tempfile.TemporaryDirectory() as temporary:
            contract = Path(temporary) / "tools.json"
            contract.write_text(json.dumps(manifest), encoding="utf-8")
            layer = GovernedResearchToolLayer(
                output_root=Path(temporary) / "out",
                backend=lambda _name, _args: (time.sleep(0.2) or {"samples": [], "count": 0}),
                tool_manifest_path=contract,
            )
            current = task()
            result = layer.execute("query_samples", make_tool_request(current.request_id, "IDEM-TIMEOUT", current, "v1", {}))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["error_code"], "GOV-RUNTIME-001")

    def test_same_idempotency_reuses_and_different_input_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layer = GovernedResearchToolLayer(output_root=Path(temporary), backend=lambda _name, _args: {"samples": [], "count": 0})
            current = task()
            request = make_tool_request(current.request_id, "IDEM-STABLE", current, "v1", {})
            first = layer.execute("query_samples", request)
            second = layer.execute("query_samples", request)
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            changed = make_tool_request(current.request_id, "IDEM-STABLE", current, "v2", {})
            with self.assertRaises(GovernanceError) as context:
                layer.execute("query_samples", changed)
            self.assertEqual(context.exception.code, "GOV-DUPLICATE-001")

    def test_request_identity_must_match_task_envelope(self) -> None:
        current = task()
        with self.assertRaises(GovernanceError) as context:
            make_tool_request("request_mismatch001", "IDEM-MISMATCH", current, "v1", {})
        self.assertEqual(context.exception.code, "GOV-INTEGRITY-001")

    def test_human_approval_is_bound_to_current_task_revision(self) -> None:
        current = task("statistics_physics")
        stale = TaskApprovalPermit.create(current, "human-reviewer")
        successor = current.handoff("materials_interpreter", status="accepted", result_summary="next", updated_at=STAMP)
        self.assertFalse(stale.matches(successor))
        with self.assertRaises(GovernanceError):
            TaskApprovalPermit.create(current, "agent-statistics")

    def test_end_to_end_handoff_uses_multiple_roles_and_remains_nonformal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_t61_handoff_demo(output_root=Path(temporary))
            self.assertEqual(result["status"], "passed")
            self.assertGreaterEqual(len(set(result["roles"])), 3)
            self.assertEqual([item["task_revision"] for item in result["task_revisions"]], [1, 2, 3])
            self.assertTrue(all(item["status"] == "completed" for item in result["tool_calls"]))
            self.assertTrue(all(item["formal_result"] is False for item in result["tool_calls"]))
            self.assertTrue(result["human_review_required"])


class ResearchMCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_lists_the_five_governed_tools(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "steelai.research_mcp_server"],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                self.assertEqual(names, {
                    "get_protocol_status", "query_samples", "get_verified_evidence",
                    "run_descriptive_statistics", "run_physics_calculation", "generate_report_candidate",
                })


if __name__ == "__main__":
    unittest.main()
