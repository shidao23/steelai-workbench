import json
import tempfile
import unittest
from pathlib import Path

from steelai.research_session import (
    add_finding,
    add_next_action,
    attach_run,
    continue_session,
    create_session,
    list_sessions,
    load_session,
    research_session_dashboard,
    session_summary,
    update_action_status,
    update_stage,
    validate_session_contract,
    workflow_templates,
)


class ResearchSessionTests(unittest.TestCase):
    def test_template_contract_has_five_bounded_daily_workflows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = validate_session_contract(root=Path(temp_dir))
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["template_count"], 5)
        self.assertEqual(
            {item["template_id"] for item in workflow_templates()},
            {"br_integrated_case", "new_sample_data_check", "physics_calibration", "ebsd_dual_scale", "sem_fracture"},
        )

    def test_create_load_list_and_summary_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            created = create_session(
                "B/R综合研究",
                "为什么R-DQ冲击韧性较低？",
                "br_integrated_case",
                ["B-DQ", "R-DQ"],
                root=root,
            )
            loaded = load_session(created["session_id"], root=root)
            sessions = list_sessions(root=root)
            summary = session_summary(loaded)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(loaded["status"], "planned")
        self.assertEqual(summary["progress"], "0/5")
        self.assertFalse(loaded["data_boundary"]["experiments_1_14_included"])
        self.assertFalse(loaded["data_boundary"]["absolute_paths_stored"])

    def test_out_of_scope_sample_and_raw_locator_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ValueError):
                create_session("旧实验", "检查1号数据", "new_sample_data_check", ["1"], root=root)
            with self.assertRaises(ValueError):
                create_session("原始文件", r"读取D:\data\sample.ctf", "br_integrated_case", ["B-DQ"], root=root)

    def test_continue_and_stage_updates_preserve_revision_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            created = create_session("Physics校正", "评价Ms残差", "physics_calibration", ["B-DQ"], root=root)
            active = continue_session(created["session_id"], root=root)
            first = active["stages"][0]
            updated = update_stage(active["session_id"], first["stage_id"], "completed", "已选择Ms", root=root)
        self.assertEqual(active["status"], "active")
        self.assertEqual(first["status"], "in_progress")
        self.assertEqual(updated["stages"][0]["status"], "completed")
        self.assertGreater(updated["revision"], created["revision"])

    def test_findings_and_actions_remain_structured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = create_session("EBSD比较", "两个尺度方向是否一致？", "ebsd_dual_scale", ["B-DQ", "R-DQ"], root=root)
            session = add_finding(session["session_id"], "hypothesis", "R-DQ局部取向差异需要更多视场验证。", ["RUN-TEST-01"], root=root)
            session = add_next_action(session["session_id"], "补充独立试样EBSD视场。", "high", root=root)
            action_id = session["next_actions"][0]["action_id"]
            session = update_action_status(session["session_id"], action_id, "in_progress", root=root)
        self.assertEqual(session["findings"][0]["category"], "hypothesis")
        self.assertEqual(session["findings"][0]["evidence_references"], ["RUN-TEST-01"])
        self.assertEqual(session["next_actions"][0]["status"], "in_progress")

    def test_run_attachment_uses_relative_artifact_and_updates_dashboard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = create_session("B/R任务", "比较B/R", "br_integrated_case", ["B-DQ", "R-DQ"], root=root)
            attached = attach_run(
                session["session_id"], "BR-TEST-001", "0.7.0", "completed",
                "outputs/research_cases/BR-TEST-001/research_report.md", root=root,
            )
            dashboard = research_session_dashboard(root=root)
            report = validate_session_contract(root=root)
            serialized = json.dumps(attached, ensure_ascii=False).lower()
            with self.assertRaises(ValueError):
                attach_run(session["session_id"], "BR-TEST-002", "0.7.0", "completed", r"D:\output\report.md", root=root)
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(dashboard["session_count"], 1)
        self.assertEqual(attached["run_references"][0]["run_id"], "BR-TEST-001")
        self.assertNotIn("d:\\", serialized)
        run_stage = next(item for item in attached["stages"] if item["stage_id"] == "run_br_case")
        self.assertEqual(run_stage["status"], "completed")


if __name__ == "__main__":
    unittest.main()
