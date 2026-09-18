from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from steelai.agent_evidence_gateway import (
    ALLOWED_AGENT_TOOLS,
    RESTRICTED_OUTPUT_SECTIONS,
    AgentEvidenceGateway,
    AgentGatewayError,
    normalize_restricted_output,
    sanitize_structured_evidence,
)
from steelai.agent_evaluation import _call_matches
from steelai.governance import digest_value, verify_package
from steelai.research_agent import AgentStatus, run_research_agent


COMPLETE_ANSWER = """## 已确认事实
- list_samples 返回 2 个样品。
## 当前判断
- 当前只能进行描述性比较。
## 待验证假设
- 组织差异可能影响性能。
## 证据与局限
- 样本量不足以进行因果推断。
## 下一步行动
- 由研究者复核证据并决定是否继续。
"""


def _gateway(root: Path | None = None) -> AgentEvidenceGateway:
    return AgentEvidenceGateway(
        "比较 B-DQ 与 R-DQ 的已确认差异。",
        "openai",
        "test-model",
        tuple(sorted(ALLOWED_AGENT_TOOLS)),
        output_root=root,
    )


class AgentEvidenceGatewayTests(unittest.TestCase):
    def test_send_summary_and_audit_persist_hashes_not_sensitive_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gateway = _gateway(root)
            with patch(
                "steelai.agent_evidence_gateway.validate_research_data_contract",
                return_value={
                    "contract_id": "fixture-contract",
                    "contract_status": "passed",
                    "sample_count": 2,
                    "tables": ["samples"],
                },
            ):
                result = gateway.execute_evidence_tool(
                    "get_sample_bundle",
                    {"sample_id": "B-DQ"},
                    lambda _name, _args: {
                        "sample_id": "B-DQ",
                        "source_path": "must-be-removed",
                        "yield_strength_mpa": 950,
                    },
                    round_number=1,
                )
            self.assertNotIn("source_path", result)
            gateway.before_model_call()
            final = gateway.finalize(
                status="completed",
                answer=COMPLETE_ANSWER,
                response_id="provider-response-fixture",
                usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
                error="",
            )

            package = Path(final["audit_package"])
            self.assertEqual(verify_package(package).status, "passed")
            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in package.glob("*.json")
            )
            self.assertNotIn(gateway.question, persisted)
            self.assertNotIn(COMPLETE_ANSWER, persisted)
            self.assertNotIn("provider-response-fixture", persisted)
            self.assertNotIn("must-be-removed", persisted)
            self.assertNotIn('"sample_id": "B-DQ"', persisted)
            audit = json.loads((package / "agent_run_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["provider"], "openai")
            self.assertEqual(audit["usage"]["total_tokens"], 20)
            self.assertEqual(audit["tool_calls"][0]["status"], "completed")
            self.assertTrue(audit["human_review_required"])

    def test_sensitive_fields_are_removed_and_sensitive_values_fail_closed(self) -> None:
        clean = sanitize_structured_evidence({
            "sample_id": "B-DQ",
            "source_path": "private locator",
            "source": "private source label",
            "nested": {"filename": "private name", "value": 1},
        })
        self.assertEqual(clean, {"sample_id": "B-DQ", "nested": {"value": 1}})
        with self.assertRaises(AgentGatewayError) as context:
            sanitize_structured_evidence({"note": "See D:\\private\\sample.csv"})
        self.assertEqual(context.exception.code, "GOV-PRIVACY-001")

    def test_processed_evidence_requires_passed_shared_contract(self) -> None:
        executor = Mock(return_value={"count": 2})
        gateway = _gateway()
        with patch(
            "steelai.agent_evidence_gateway.validate_research_data_contract",
            return_value={"contract_status": "blocked"},
        ), self.assertRaises(AgentGatewayError) as context:
            gateway.execute_evidence_tool("list_samples", {}, executor, round_number=1)
        self.assertEqual(context.exception.code, "GOV-EVIDENCE-001")
        executor.assert_not_called()

    def test_ebsd_and_sem_require_verified_human_review(self) -> None:
        executor = Mock(return_value={"status": "ok"})
        gateway = _gateway()
        with patch(
            "steelai.agent_evidence_gateway.list_image_model_result_index",
            return_value=[],
        ), self.assertRaises(AgentGatewayError) as context:
            gateway.execute_evidence_tool(
                "get_ebsd_summary", {"scale": "low"}, executor, round_number=1
            )
        self.assertEqual(context.exception.state, "needs_human")
        executor.assert_not_called()

    def test_reviewed_image_evidence_gets_a_gateway_identity(self) -> None:
        gateway = _gateway()
        reviewed = [{
            "modality": "SEM",
            "evidence_eligible": True,
            "governance_state": "complete",
            "review_id": "REVIEW-1",
            "run_id": "RUN-1",
            "task_id": "TASK-1",
            "result_level": "model_result",
            "accepted_output_ids": ["MASK-1"],
        }]
        with patch(
            "steelai.agent_evidence_gateway.list_image_model_result_index",
            return_value=reviewed,
        ):
            result = gateway.execute_evidence_tool(
                "get_autodimple_summary",
                {},
                lambda _name, _args: {"objects": 3, "status": "reviewed"},
                round_number=1,
            )
        self.assertTrue(result["_gateway"]["evidence_id"].startswith("AGEVID-"))
        self.assertEqual(result["_gateway"]["verification_status"], "passed")

    def test_agent_has_no_approval_write_or_shell_tool_authority(self) -> None:
        for tool_name in ("approve_suggestion", "write_formal_data", "run_shell"):
            executor = Mock()
            with self.subTest(tool=tool_name), self.assertRaises(AgentGatewayError) as context:
                _gateway().execute_evidence_tool(tool_name, {}, executor, round_number=1)
            self.assertEqual(context.exception.code, "GOV-AI-AUTH-001")
            executor.assert_not_called()

    def test_model_output_contract_has_exact_five_sections_and_no_authority(self) -> None:
        structured = normalize_restricted_output(COMPLETE_ANSWER)
        self.assertEqual(tuple(structured["sections"]), RESTRICTED_OUTPUT_SECTIONS)
        self.assertEqual(structured["contract_status"], "passed")
        self.assertFalse(structured["boundaries"]["human_approval"])
        self.assertFalse(structured["boundaries"]["formal_write"])
        self.assertFalse(structured["boundaries"]["shell_execution"])
        self.assertTrue(structured["boundaries"]["requires_human_review"])

    def test_question_and_model_response_privacy_blocks_before_release(self) -> None:
        with self.assertRaises(AgentGatewayError):
            AgentEvidenceGateway(
                "读取 D:\\private\\sample.csv",
                "openai",
                "test-model",
                tuple(ALLOWED_AGENT_TOOLS),
            )
        gateway = _gateway()
        final = gateway.finalize(
            status="completed",
            answer="## 已确认事实\n- raw_sample_01.ctf 显示异常。",
            response_id="fixture",
            usage={},
            error="",
        )
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(final["answer"], "")

    def test_offline_mode_needs_no_api_key_and_creates_no_audit_package(self) -> None:
        status = AgentStatus(
            "offline_missing_key", True, False, True, "test-model", "low", 6, 4,
            "未配置密钥", "test-version",
        )
        result = run_research_agent("比较两个样品。", status=status)
        self.assertEqual(result.status, "offline")
        self.assertEqual(result.audit_package, "")

    def test_evaluator_scores_hashed_arguments_without_retaining_raw_values(self) -> None:
        expected = {"tool": "get_sample_bundle", "arguments": {"sample_id": "B-DQ"}}
        actual = {
            "tool": "get_sample_bundle",
            "arguments_sha256": digest_value({"sample_id": "B-DQ"}),
            "status": "completed",
        }
        self.assertTrue(_call_matches(expected, actual))
        self.assertNotIn("arguments", actual)

    def test_failed_call_audit_never_retains_an_untrusted_tool_name(self) -> None:
        gateway = _gateway()
        record = gateway.record_failed_tool(
            "D:\\private\\secret.ctf",
            {"token": "not-persisted"},
            round_number=1,
            error=AgentGatewayError("GOV-AI-AUTH-001", "blocked", "denied"),
            duration_ms=0.1,
        )
        self.assertEqual(record["tool"], "blocked_non_allowlisted_tool")
        serialized = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("private", serialized)
        self.assertNotIn("secret.ctf", serialized)
        self.assertNotIn("not-persisted", serialized)


if __name__ == "__main__":
    unittest.main()
