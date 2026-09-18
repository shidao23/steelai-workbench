from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from steelai.agent_workflow_benchmark import (
    TEMPLATE_COLUMNS,
    WORKFLOWS,
    evaluate_records,
    load_benchmark,
    load_measurement_csv,
    publish_benchmark_package,
    validate_benchmark,
    validate_record,
)
from steelai.governance import GovernanceError, verify_package


def measured_records(
    *,
    human_seconds: float = 100,
    single_seconds: float = 80,
    multi_seconds: float = 70,
    human_revisions: int = 2,
    agent_revisions: int = 1,
):
    contract = load_benchmark()
    durations = {"human_only": human_seconds, "single_agent": single_seconds, "multi_agent": multi_seconds}
    rows = []
    for task in contract["tasks"]:
        for workflow in WORKFLOWS:
            for repetition in (1, 2):
                rows.append(validate_record({
                    "run_group_id": "T63-TEST-MEASURED",
                    "task_id": task["task_id"],
                    "workflow": workflow,
                    "repetition": repetition,
                    "measurement_kind": "measured",
                    "started_at": "2026-09-10T00:00:00+00:00",
                    "finished_at": "2026-09-10T00:02:00+00:00",
                    "elapsed_seconds": durations[workflow],
                    "status": "completed",
                    "passed_checks": task["required_checks"],
                    "critical_errors": [],
                    "human_revision_count": human_revisions if workflow == "human_only" else agent_revisions,
                    "input_tokens": 0 if workflow == "human_only" else 100,
                    "output_tokens": 0 if workflow == "human_only" else 50,
                    "cloud_cost_usd": 0 if workflow == "human_only" else 0.001,
                    "present_trace_fields": contract["trace_fields_by_workflow"][workflow],
                    "runner_identity": "human-tester" if workflow == "human_only" else "test-runner",
                    "notes": "public test fixture",
                }, contract))
    return rows


class T63AgentWorkflowBenchmarkTests(unittest.TestCase):
    def test_contract_freezes_four_tasks_three_workflows_and_metrics(self) -> None:
        result = validate_benchmark()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["task_count"], 4)
        self.assertEqual(result["workflow_count"], 3)
        self.assertEqual(result["required_measurement_count"], 24)

    def test_preparation_package_contains_template_raw_calibration_and_no_advantage_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = publish_benchmark_package(output_root=Path(temporary))
            self.assertEqual(result["status"], "needs_human")
            self.assertEqual(result["evaluation"]["measured_record_count"], 0)
            self.assertEqual(result["evaluation"]["conclusion"], "insufficient_evidence")
            package = Path(result["package"])
            self.assertEqual(verify_package(package).status, "passed")
            raw = (package / "raw_run_records.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(raw), 12)
            with (package / "measurement_template.csv").open(encoding="utf-8-sig", newline="") as handle:
                template = list(csv.DictReader(handle))
            self.assertEqual(len(template), 24)
            self.assertEqual(tuple(template[0]), TEMPLATE_COLUMNS)
            report = (package / "evaluation_report.md").read_text(encoding="utf-8")
            self.assertIn("不能声称", report)

    def test_unknown_check_or_critical_error_fails_closed(self) -> None:
        contract = load_benchmark()
        task = contract["tasks"][0]
        base = {
            "run_group_id": "T63-BAD", "task_id": task["task_id"], "workflow": "human_only",
            "repetition": 1, "measurement_kind": "measured", "started_at": "x", "finished_at": "y",
            "elapsed_seconds": 1, "status": "completed", "passed_checks": ["unknown"],
            "critical_errors": [], "human_revision_count": 0, "input_tokens": 0, "output_tokens": 0,
            "cloud_cost_usd": 0, "present_trace_fields": [], "runner_identity": "human-tester", "notes": "",
        }
        with self.assertRaises(GovernanceError) as context:
            validate_record(base, contract)
        self.assertEqual(context.exception.code, "GOV-SCHEMA-001")

    def test_measured_record_requires_a_real_timezone_aware_timestamp(self) -> None:
        contract = load_benchmark()
        task = contract["tasks"][0]
        with self.assertRaises(GovernanceError) as context:
            validate_record({
                "run_group_id": "T63-BAD-TIME", "task_id": task["task_id"], "workflow": "human_only",
                "repetition": 1, "measurement_kind": "measured", "started_at": "not-measured",
                "finished_at": "not-measured", "elapsed_seconds": 1, "status": "completed",
                "passed_checks": task["required_checks"], "critical_errors": [],
                "human_revision_count": 0, "input_tokens": 0, "output_tokens": 0,
                "cloud_cost_usd": 0,
                "present_trace_fields": contract["trace_fields_by_workflow"]["human_only"],
                "runner_identity": "human-tester", "notes": "",
            }, contract)
        self.assertEqual(context.exception.code, "GOV-SCHEMA-001")

    def test_complete_measurement_uses_frozen_advantage_rule(self) -> None:
        contract = load_benchmark()
        result = evaluate_records(measured_records(), contract)
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["measured_record_count"], 24)
        self.assertEqual(result["conclusion"], "both_agent_workflows_meet_frozen_advantage_rule")
        self.assertTrue(result["advantage_rule_results"]["single_agent"])
        self.assertTrue(result["advantage_rule_results"]["multi_agent"])

    def test_no_advantage_is_retained_when_measured_results_do_not_support_it(self) -> None:
        contract = load_benchmark()
        result = evaluate_records(
            measured_records(single_seconds=110, multi_seconds=120, agent_revisions=2), contract,
        )
        self.assertEqual(result["conclusion"], "no_agent_workflow_advantage_detected")
        self.assertFalse(any(result["advantage_rule_results"].values()))

    def test_incomplete_records_remain_insufficient_evidence(self) -> None:
        contract = load_benchmark()
        result = evaluate_records(measured_records()[:-1], contract)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["conclusion"], "insufficient_evidence")
        self.assertEqual(len(result["missing_measurements"]), 1)

    def test_measurement_csv_rejects_changed_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wrong.csv"
            path.write_text("task_id,workflow\nT63-DATA-01,human_only\n", encoding="utf-8")
            with self.assertRaises(GovernanceError) as context:
                load_measurement_csv(path)
            self.assertEqual(context.exception.code, "GOV-SCHEMA-001")

    def test_measured_package_is_governed_even_when_no_advantage_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = publish_benchmark_package(
                measured_records(single_seconds=110, multi_seconds=120, agent_revisions=2),
                output_root=Path(temporary),
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["evaluation"]["conclusion"], "no_agent_workflow_advantage_detected")
            self.assertEqual(verify_package(result["package"]).status, "passed")
            raw = (Path(result["package"]) / "raw_run_records.jsonl").read_text(encoding="utf-8")
            self.assertIn('"status": "completed"', raw)


if __name__ == "__main__":
    unittest.main()
