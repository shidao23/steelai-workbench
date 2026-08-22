import json
import tempfile
import unittest
from pathlib import Path

from steelai.agent_evaluation import (
    benchmark_contract,
    evaluate_agent_result,
    load_benchmark,
    run_agent_evaluation,
)
from steelai.agent_observability import (
    build_trace_records,
    compare_evaluation_runs,
    read_evaluation_history,
)
from steelai.research_agent import AgentRunResult, AgentStatus, run_research_agent


class AgentEvaluationTests(unittest.TestCase):
    def test_benchmark_contract_has_six_categories_and_no_unknown_tools(self):
        contract = benchmark_contract()
        self.assertEqual(contract["status"], "passed")
        self.assertEqual(contract["case_count"], 25)
        self.assertEqual(contract["category_count"], 6)
        self.assertEqual(contract["privacy_case_count"], 4)
        self.assertEqual(contract["unknown_tools"], [])

    def test_transparent_scorer_rewards_expected_tool_and_evidence(self):
        _benchmark, cases = load_benchmark()
        case = next(item for item in cases if item.case_id == "DATA-001")
        result = AgentRunResult(
            "completed",
            "list_samples显示当前有两个核心样品：B-DQ和R-DQ。",
            "test-model",
            tool_trace=[{"tool": "list_samples", "arguments": {}, "status": "completed"}],
        )
        row = evaluate_agent_result(case, result, latency_ms=12.3)
        self.assertTrue(row["passed"])
        self.assertEqual(row["overall_score"], 1.0)
        self.assertEqual(row["tool_score"], 1.0)
        self.assertEqual(row["privacy_score"], 1.0)

    def test_forbidden_scientific_claim_fails_guardrail(self):
        _benchmark, cases = load_benchmark()
        case = next(item for item in cases if item.case_id == "EVID-001")
        result = AgentRunResult(
            "completed",
            "现有数据已经证明残余元素导致R-DQ韧性下降。",
            "test-model",
            tool_trace=[{
                "tool": "get_evidence_validation_summary",
                "arguments": {},
                "status": "completed",
            }],
        )
        row = evaluate_agent_result(case, result)
        self.assertFalse(row["passed"])
        self.assertEqual(row["guardrail_score"], 0.0)
        self.assertTrue(row["forbidden_hits"])

    def test_raw_locator_is_blocked_before_client_call(self):
        status = AgentStatus(
            "online_ready", True, True, True, "test-model", "low", 6, 4, "ok"
        )
        result = run_research_agent(
            r"请读取D:\private\sample.ctf",
            client=object(),
            status=status,
        )
        self.assertEqual(result.status, "invalid_input")
        self.assertIn("API调用前阻断", result.error)
        self.assertEqual(result.tool_trace, [])

    def test_evaluation_run_writes_results_report_and_manifest(self):
        def fake_runner(case):
            if case.case_id == "PRIV-001":
                return AgentRunResult(
                    "invalid_input", "", "test-model", error="已在API调用前阻断。"
                )
            return AgentRunResult(
                "completed",
                "list_samples显示当前有两个核心样品：B-DQ和R-DQ。",
                "test-model",
                tool_trace=[{"tool": "list_samples", "arguments": {}, "status": "completed"}],
                usage={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_agent_evaluation(
                ["DATA-001", "PRIV-001"],
                runner=fake_runner,
                output_root=Path(temp_dir),
            )
            self.assertTrue(result.result_path.exists())
            self.assertTrue(result.report_path.exists())
            self.assertTrue(result.manifest_path.exists())
            self.assertTrue((result.manifest_path.parent / "trace_spans.jsonl").exists())
            self.assertTrue((result.manifest_path.parent / "observability_summary.json").exists())
            self.assertEqual(result.summary["case_count"], 2)
            self.assertEqual(result.summary["passed_count"], 2)
            self.assertEqual(result.summary["total_tokens"], 18)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["privacy"]["raw_files_transmitted"])
            serialized = result.result_path.read_text(encoding="utf-8").lower()
            self.assertNotIn("d:\\private", serialized)
            self.assertNotIn("sample.ctf", serialized)

    def test_trace_export_excludes_prompts_answers_arguments_and_paths(self):
        manifest = {"evaluation_id": "AE-test", "created_at": "2026-08-19T00:00:00+08:00"}
        rows = [{
            "case_id": "DATA-001",
            "category": "data_grounding",
            "model": "test-model",
            "passed": True,
            "overall_score": 1.0,
            "latency_ms": 12.0,
            "usage": {"total_tokens": 18},
            "question": r"读取D:\private\sample.ctf",
            "answer": "sensitive answer",
            "tool_trace": [{
                "tool": "list_samples",
                "arguments": {"path": r"D:\private"},
                "status": "completed",
                "duration_ms": 2.5,
                "round": 1,
            }],
        }]
        records = build_trace_records(manifest, rows)
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertEqual(len(records), 2)
        self.assertNotIn("sensitive answer", serialized)
        self.assertNotIn("D:\\private", serialized)
        self.assertNotIn("sample.ctf", serialized)
        self.assertEqual(records[1]["duration_ms"], 2.5)

    def test_history_and_run_comparison_detect_regression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for evaluation_id, score, passed, latency in (
                ("AE-001", 1.0, True, 10.0),
                ("AE-002", 0.7, False, 20.0),
            ):
                run_root = root / evaluation_id
                run_root.mkdir()
                manifest = {
                    "evaluation_id": evaluation_id,
                    "created_at": f"2026-08-19T00:00:0{evaluation_id[-1]}+08:00",
                    "selected_case_ids": ["DATA-001"],
                    "summary": {
                        "model": "test-model",
                        "case_count": 1,
                        "passed_count": int(passed),
                        "pass_rate": float(passed),
                        "mean_overall_score": score,
                        "mean_guardrail_score": 1.0,
                        "mean_privacy_score": 1.0,
                        "mean_latency_ms": latency,
                        "total_tokens": 10,
                    },
                }
                rows = [{
                    "case_id": "DATA-001", "title": "sample", "passed": passed,
                    "overall_score": score, "latency_ms": latency,
                }]
                (run_root / "evaluation_manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                (run_root / "evaluation_results.json").write_text(
                    json.dumps(rows), encoding="utf-8"
                )
            history = read_evaluation_history(root)
            self.assertEqual([row["evaluation_id"] for row in history], ["AE-002", "AE-001"])
            comparison = compare_evaluation_runs("AE-001", "AE-002", root)
            self.assertEqual(comparison["regression_count"], 1)
            self.assertEqual(comparison["score_delta"], -0.3)
            self.assertEqual(comparison["latency_delta_ms"], 10.0)


if __name__ == "__main__":
    unittest.main()
