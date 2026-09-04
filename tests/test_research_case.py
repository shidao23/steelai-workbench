import json
import tempfile
import unittest
from pathlib import Path

from steelai.research_agent import AgentRunResult
from steelai.research_case import ResearchCaseRequest, run_research_case


class ResearchCaseTests(unittest.TestCase):
    def test_offline_pipeline_writes_reproducible_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_research_case(
                ResearchCaseRequest(use_agent=False),
                output_root=Path(temp_dir),
            )

            self.assertEqual(result.status, "completed")
            self.assertTrue(result.report_path.exists())
            self.assertTrue(result.manifest_path.exists())
            self.assertTrue(result.snapshot_path.exists())
            self.assertEqual(result.manifest["pipeline"]["version"], "0.7.0")
            self.assertFalse(result.manifest["request"]["experiments_1_14_included"])
            self.assertEqual(result.manifest["agent"]["status"], "not_requested")
            self.assertEqual(len(result.manifest["stages"]), 8)
            self.assertTrue(result.manifest["data_snapshot"])
            self.assertTrue(result.manifest["code_snapshot"])

    def test_manifest_and_snapshot_do_not_expose_raw_files_or_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_research_case(
                ResearchCaseRequest(use_agent=False),
                output_root=Path(temp_dir),
            )
            serialized = json.dumps(result.manifest, ensure_ascii=False).lower()
            snapshot = result.snapshot_path.read_text(encoding="utf-8").lower()
            for content in (serialized, snapshot):
                self.assertNotIn("d:\\", content)
                self.assertNotIn(".ctf", content)
                self.assertNotIn(".tif", content)
            self.assertFalse(result.manifest["privacy"]["raw_files_transmitted"])

    def test_agent_trace_is_captured_without_becoming_a_calculation(self):
        fake = AgentRunResult(
            status="completed",
            answer="## 已确认事实\n- 证据验证工具显示当前仅支持方向性分析。",
            model="deepseek-test",
            tool_trace=[{"round": 1, "tool": "get_evidence_validation_summary", "status": "completed"}],
            response_id="test-response",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_research_case(
                ResearchCaseRequest(use_agent=True),
                output_root=Path(temp_dir),
                agent_runner=lambda _question: fake,
            )
            self.assertEqual(result.manifest["agent"]["status"], "completed")
            self.assertEqual(
                result.manifest["agent"]["tool_trace"][0]["tool"],
                "get_evidence_validation_summary",
            )
            self.assertIn("Research Agent综合", result.report)

    def test_external_agent_rejects_raw_locator_in_question(self):
        request = ResearchCaseRequest(
            question=r"请读取D:\research\sample.ctf",
            use_agent=True,
        )
        with self.assertRaises(ValueError):
            request.validate()

    def test_only_current_br_case_is_accepted(self):
        request = ResearchCaseRequest(control_id="B-DQ", comparison_id="1")
        with self.assertRaises(ValueError):
            request.validate()


if __name__ == "__main__":
    unittest.main()
