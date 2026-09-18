"""All fixtures are synthetic and all writes target TemporaryDirectory, never real data."""
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steelai.data_intake import commit_intake, validate_intake_csv
from steelai.steeldata_bridge import (
    SteelDataClient, _digest, commit_run, inspect_run, mapping_rows, prepare_intake,
)

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def seal(root, manifest):
    manifest["artifacts"] = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file() and p.name not in {"manifest.json", "COMPLETE"}
    }
    write_json(root / "manifest.json", manifest)
    (root / "COMPLETE").write_text(hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(), encoding="ascii")


def result_fixture(root, *, synthetic=False):
    """False only exercises the real-data gate in an isolated test project; not real data."""
    root.mkdir(parents=True)
    source = b"SYNTHETIC TEST FIXTURE,not laboratory data\n"
    source_hash = hashlib.sha256(source).hexdigest()
    (root / "sources").mkdir()
    (root / "sources/0001.csv").write_bytes(source)
    (root / "report.html").write_text("<p>Synthetic test</p>", encoding="utf-8")
    profile = {"profile_id": "test-tensile", "domain": "tensile"}
    approval = {"kind": "human", "profile": profile, "profile_sha256": _digest(profile),
                "reviewer": "automated-test-only", "note": "synthetic sandbox", "approved_at": "test"}
    write_json(root / "approvals/test-tensile.json", approval)
    data = {"schema_version": 1, "domain": "tensile", "kind": "table", "source_file": "fixture.csv",
            "source_sha256": source_hash, "sheet": "CSV", "metadata": {"units": {
                "ys_mpa": {"target": "MPa"}, "uts_mpa": {"target": "MPa"}, "el_pct": {"target": "%"}}},
            "records": [{"record_id": "test-record-01", "specimen_id": "SYN-T01", "source_row": 2,
                         "ys_mpa": 950.0, "uts_mpa": 1250.0, "el_pct": 12.0, "raw_values": {"uts_mpa": "1.25"},
                         "source_cells": {field: {"row": 2, "column": i, "header": field}
                                          for i, field in enumerate(["ys_mpa", "uts_mpa", "el_pct"], 1)}}]}
    write_json(root / "datasets/001-tensile/data.json", data)
    write_json(root / "qc.json", {"schema_version": 1, "status": "passed", "values_modified_by_qc": False, "issues": []})
    manifest = {"schema_version": 1, "module": "steeldata", "version": "0.2.0", "complete": True,
                "run_id": "run-test", "processing_status": "complete", "qc_status": "passed",
                "synthetic": synthetic, "input_fingerprint": "fixture-fingerprint",
                "counts": {"files": 1, "datasets": 1, "records": 1}, "files": [{
                    "source_file": "fixture.csv", "source_sha256": source_hash, "snapshot": "sources/0001.csv",
                    "status": "processed", "records": 1, "dataset_dir": "datasets/001-tensile", "domain": "tensile",
                    "kind": "table", "profile_id": "test-tensile", "qc_status": "passed"}],
                "approvals": [{"profile_id": "test-tensile", "kind": "human", "profile_sha256": _digest(profile),
                               "approval_record_sha256": _digest(approval)}]}
    seal(root, manifest)
    return manifest


def attach_execution_audit(root, manifest):
    """Add a synthetic T23 chain that has the same digest bindings as SteelData."""
    approval_path = root / "approvals/test-tensile.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    suggestion = {
        "suggestion_id": "execute-one",
        "source_file": "fixture.csv",
        "source_sha256": manifest["files"][0]["source_sha256"],
        "proposed_profile": approval["profile"],
    }
    suggestion_sha256 = _digest(suggestion)
    suggestion_record = {
        "schema_version": 1,
        "suggestion": suggestion,
        "suggestion_sha256": suggestion_sha256,
        "status": "executing",
        "revision": 3,
    }
    approval.update({
        "suggestion_id": "execute-one",
        "suggestion_sha256": suggestion_sha256,
        "suggestion_revision": 2,
    })
    write_json(approval_path, approval)
    approval_sha256 = _digest(approval)
    review_record = {
        "schema_version": 1,
        "suggestion_id": "execute-one",
        "suggestion_sha256": suggestion_sha256,
        "decision": "approved",
        "reviewer": "automated-test-only",
        "note": "synthetic audit-chain fixture",
        "profile_sha256": approval["profile_sha256"],
        "approval_record": "approved_v2/execute-one.json",
        "approval_record_sha256": approval_sha256,
    }
    review_sha256 = _digest(review_record)
    idempotency_key = _digest({
        "suggestion_sha256": suggestion_sha256,
        "approval_record_sha256": approval_sha256,
        "review_record_sha256": review_sha256,
        "source_sha256": suggestion["source_sha256"],
    })
    request = {
        "schema_version": 1,
        "trigger": "human_approval",
        "actor": "system",
        "suggestion_id": "execute-one",
        "suggestion_sha256": suggestion_sha256,
        "source_file": suggestion["source_file"],
        "source_sha256": suggestion["source_sha256"],
        "idempotency_key": idempotency_key,
        "attempt": 1,
        "requested_at": "test",
    }
    write_json(root / "audit/suggestion.json", suggestion_record)
    write_json(root / "audit/review.json", review_record)
    write_json(root / "audit/execution_request.json", request)
    manifest["approvals"][0].update({
        "suggestion_id": "execute-one",
        "suggestion_sha256": suggestion_sha256,
        "suggestion_revision": 2,
        "approval_record_sha256": approval_sha256,
    })
    manifest["execution"] = {
        "schema_version": 1,
        "suggestion_id": "execute-one",
        "suggestion_sha256": suggestion_sha256,
        "approval_record_sha256": approval_sha256,
        "review_record_sha256": review_sha256,
        "idempotency_key": idempotency_key,
        "attempt": 1,
        "audit_files": {
            "suggestion": {"path": "audit/suggestion.json", "sha256": _digest(suggestion_record)},
            "review": {"path": "audit/review.json", "sha256": _digest(review_record)},
            "execution_request": {"path": "audit/execution_request.json", "sha256": _digest(request)},
        },
    }
    seal(root, manifest)
    return suggestion_record, review_record, request


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "module-output/run-test"
        self.manifest = result_fixture(self.run)
        self.project = self.root / "workbench"
        (self.project / "data/processed").mkdir(parents=True)
        (self.project / "data/processed/samples.csv").write_text("sample_id\nB-DQ\nR-DQ\n", encoding="utf-8")
        self.kwargs = {"project_root": self.project}

    def tearDown(self):
        self.temp.cleanup()

    def candidate(self, sample="B-DQ"):
        inspection = inspect_run(self.run)
        bindings = {r["mapping_key"]: sample for r in mapping_rows(inspection)}
        return prepare_intake(inspection, bindings, "instrument_export", **self.kwargs), bindings

    def commit(self, candidate, bindings, **kwargs):
        return commit_run(self.run, bindings, "instrument_export", candidate["preview_sha256"],
                          reviewer="test", note="synthetic sandbox only", confirmed=True, **self.kwargs, **kwargs)

    def test_tensile_wide_to_long_preserves_value_identity_and_provenance(self):
        candidate, _ = self.candidate()
        self.assertEqual(candidate["report"]["status"], "ready")
        rows = candidate["report"]["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["property"] for r in rows], ["ys_mpa", "uts_mpa", "elongation_pct"])
        self.assertEqual(float(rows[1]["value"]), 1250)
        self.assertTrue(all(r["specimen_id"] == "SYN-T01" for r in rows))
        self.assertEqual(candidate["evidence"]["provenance"][1]["source_cell"]["column"], 2)
        self.assertFalse((self.project / "data/processed/property_observations.csv").exists())

    def test_commit_appends_and_leaves_audit_without_copying_raw_sources(self):
        candidate, bindings = self.candidate()
        result = self.commit(candidate, bindings)
        self.assertEqual(result["rows_added"], 3)
        package = self.project / "outputs/data_intake" / result["intake_id"]
        self.assertTrue((package / "steeldata_provenance.json").exists())
        self.assertTrue((package / "commit_result.json").exists())
        self.assertFalse((self.project / "data/processed/properties.csv").exists())
        self.assertFalse(list(self.project.rglob("0001.csv")))

    def test_second_import_is_blocked_even_if_sample_is_changed(self):
        candidate, bindings = self.candidate()
        self.commit(candidate, bindings)
        second, _ = self.candidate("R-DQ")
        self.assertEqual(second["report"]["status"], "blocked")
        self.assertIn("来源单元格", " ".join(second["report"]["errors"]))

    def test_synthetic_partial_failed_needs_review_are_all_blocked(self):
        for key, value in [("synthetic", True), ("synthetic", None), ("processing_status", "partial"),
                           ("qc_status", "failed"), ("qc_status", "needs_review")]:
            with self.subTest(key=key, value=value):
                m = {**self.manifest, key: value}
                seal(self.run, m)
                view = inspect_run(self.run)
                self.assertFalse(view.transferable)
                with self.assertRaises(ValueError):
                    prepare_intake(view, {}, "instrument_export", **self.kwargs)

    def test_warning_is_visible_and_still_requires_explicit_confirmation(self):
        self.manifest["qc_status"] = "warning"
        self.manifest["files"][0]["qc_status"] = "warning"
        write_json(self.run / "qc.json", {"status": "warning", "values_modified_by_qc": False,
            "issues": [{"severity": "warning", "code": "test_warning", "message": "review me"}]})
        seal(self.run, self.manifest)
        self.assertEqual(inspect_run(self.run).warnings, ["test_warning: review me"])
        candidate, bindings = self.candidate()
        with self.assertRaises(ValueError):
            commit_run(self.run, bindings, "instrument_export", candidate["preview_sha256"],
                       reviewer="test", note="test", confirmed=False, **self.kwargs)

    def test_inconsistent_qc_error_cannot_hide_behind_passed_status(self):
        write_json(self.run / "qc.json", {"status": "passed", "values_modified_by_qc": False,
            "issues": [{"severity": "error", "code": "hidden", "message": "bad"}]})
        seal(self.run, self.manifest)
        self.assertFalse(inspect_run(self.run).transferable)

    def test_corrupted_file_and_manifest_marker_are_rejected(self):
        (self.run / "report.html").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            inspect_run(self.run)
        seal(self.run, self.manifest)
        (self.run / "COMPLETE").write_text("invalid", encoding="ascii")
        with self.assertRaises(ValueError):
            inspect_run(self.run)

    def test_path_traversal_is_rejected_before_read(self):
        self.manifest["artifacts"]["../outside.txt"] = "0" * 64
        write_json(self.run / "manifest.json", self.manifest)
        (self.run / "COMPLETE").write_text(hashlib.sha256((self.run / "manifest.json").read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            inspect_run(self.run)

    def test_empty_file_list_is_rejected_cleanly(self):
        self.manifest["files"] = []
        seal(self.run, self.manifest)
        with self.assertRaises(ValueError):
            inspect_run(self.run)

    def test_modified_approval_digest_is_rejected(self):
        path = self.run / "approvals/test-tensile.json"
        approval = json.loads(path.read_text())
        approval["profile"]["domain"] = "composition"
        write_json(path, approval)
        seal(self.run, self.manifest)
        with self.assertRaises(ValueError):
            inspect_run(self.run)

    def test_t23_execution_audit_chain_is_verified(self):
        attach_execution_audit(self.run, self.manifest)
        inspection = inspect_run(self.run)
        self.assertTrue(inspection.transferable)
        self.assertEqual(inspection.manifest["execution"]["suggestion_id"], "execute-one")

    def test_t23_resealed_but_changed_review_is_rejected(self):
        attach_execution_audit(self.run, self.manifest)
        review_path = self.run / "audit/review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["decision"] = "rejected"
        write_json(review_path, review)
        seal(self.run, self.manifest)
        with self.assertRaisesRegex(ValueError, "审计链"):
            inspect_run(self.run)

    def test_unknown_domain_is_inspect_only(self):
        path = self.run / "datasets/001-tensile/data.json"
        data = json.loads(path.read_text())
        data["domain"] = "composition"
        self.manifest["files"][0]["domain"] = "composition"
        write_json(path, data)
        seal(self.run, self.manifest)
        self.assertFalse(inspect_run(self.run).transferable)

    def test_invalid_physics_and_missing_units_block_even_when_qc_says_passed(self):
        path = self.run / "datasets/001-tensile/data.json"
        original = json.loads(path.read_text())
        for change in ["value", "unit", "missing", "empty"]:
            with self.subTest(change=change):
                data = copy.deepcopy(original)
                if change == "value":
                    data["records"][0]["uts_mpa"] = 100
                elif change == "unit":
                    data["metadata"]["units"]["uts_mpa"]["target"] = "GPa"
                elif change == "missing":
                    data["records"][0]["ys_mpa"] = None
                else:
                    data["records"][0]["source_cells"] = {}
                write_json(path, data)
                seal(self.run, self.manifest)
                self.assertFalse(inspect_run(self.run).transferable)

    def test_mapping_never_guesses_from_specimen_name(self):
        inspection = inspect_run(self.run)
        self.assertEqual(mapping_rows(inspection)[0]["sample_id"], "")
        with self.assertRaises(ValueError):
            prepare_intake(inspection, {}, "instrument_export", **self.kwargs)

    def test_t200_and_unregistered_samples_stay_blocked(self):
        for sample in ["B-T200", "EXP-01"]:
            candidate, _ = self.candidate(sample)
            self.assertEqual(candidate["report"]["status"], "blocked")
        (self.project / "data/processed/samples.csv").write_text("sample_id\nB-DQ\n", encoding="utf-8")
        candidate, _ = self.candidate("R-DQ")
        self.assertEqual(candidate["report"]["status"], "blocked")

    def test_commit_rebuild_detects_changed_mapping_and_changed_result(self):
        candidate, bindings = self.candidate()
        with self.assertRaises(ValueError):
            self.commit(candidate, {k: "R-DQ" for k in bindings})
        self.manifest["run_id"] = "changed-after-preview"
        seal(self.run, self.manifest)
        with self.assertRaises(ValueError):
            self.commit(candidate, bindings)

    def test_model_generated_source_status_not_accepted(self):
        inspection = inspect_run(self.run)
        bindings = {r["mapping_key"]: "B-DQ" for r in mapping_rows(inspection)}
        with self.assertRaises(ValueError):
            prepare_intake(inspection, bindings, "model_generated", **self.kwargs)

    def test_shared_gate_rechecks_stale_report_and_lock(self):
        candidate, _ = self.candidate()
        report = candidate["report"]
        lock = self.project / "data/processed/.intake.lock"
        lock.write_text("other writer", encoding="utf-8")
        with self.assertRaises(ValueError):
            commit_intake(report, **self.kwargs)
        lock.unlink()
        commit_intake(report, **self.kwargs)
        with self.assertRaises(ValueError):
            commit_intake(report, **self.kwargs)
        self.assertFalse(lock.exists())

    def test_manual_upload_with_extra_cells_is_blocked_not_silently_truncated(self):
        content = b"sample_id,specimen_id,property,value,unit,source_status\nB-DQ,T01,ys_mpa,950,MPa,instrument_export,EXTRA\n"
        report = validate_intake_csv("property_observations", content, **self.kwargs)
        self.assertEqual(report["status"], "blocked")


class ClientTests(unittest.TestCase):
    def test_availability_probes_runtime_instead_of_trusting_stale_executable(self):
        client = SteelDataClient(ROOT.parent / "SteelData")
        with patch("steelai.steeldata_bridge.subprocess.run", side_effect=OSError("stale launcher")):
            report = client.availability()
        self.assertFalse(report["ready"])
        self.assertEqual(report["reason"], "runtime_probe_failed")

    def test_cli_uses_isolated_python_argument_list_no_shell_and_handles_partial(self):
        client = SteelDataClient(ROOT.parent / "SteelData")
        response = subprocess.CompletedProcess([], 2, '{"run_dir":"example","processing_status":"partial"}', "")
        with patch.object(client, "availability", return_value={"ready": True}), patch(
            "steelai.steeldata_bridge.subprocess.run", return_value=response) as run:
            payload = client._call(["run", "--input", "path with spaces & text"], accepted=(0, 2, 3))
        self.assertEqual(payload["processing_status"], "partial")
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1], "path with spaces & text")
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 180)
        self.assertNotIn("DEEPSEEK_API_KEY", kwargs["env"])

    def test_missing_module_invalid_json_and_timeout_are_actionable(self):
        client = SteelDataClient(Path("missing-module"))
        with self.assertRaises(ValueError):
            client.doctor()
        with patch.object(client, "availability", return_value={"ready": True}), patch(
            "steelai.steeldata_bridge.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "oops", "broken")):
            with self.assertRaisesRegex(ValueError, "JSON"):
                client.doctor()
        with patch.object(client, "availability", return_value={"ready": True}), patch(
            "steelai.steeldata_bridge.subprocess.run", side_effect=subprocess.TimeoutExpired([], 180)):
            with self.assertRaisesRegex(ValueError, "180"):
                client.doctor()

    def test_suggestion_review_uses_fixed_single_item_cli_contract(self):
        client = SteelDataClient(ROOT.parent / "SteelData")
        suggestion = {"suggestion_id": "review-one", "revision": 2, "suggestion_sha256": "a" * 64}
        with patch.object(client, "_call", side_effect=[
            {"suggestions": [suggestion]},
            {**suggestion, "status": "needs_human"},
            {"suggestion_id": "review-one", "status": "approved"},
        ]) as call:
            self.assertEqual(client.list_suggestions(), [suggestion])
            client.show_suggestion("review-one")
            client.review_suggestion(suggestion, "approve", " Researcher ", " Checked units. ")
        review_args = call.call_args_list[2].args[0]
        self.assertEqual(review_args.count("--suggestion-id"), 1)
        self.assertIn("review-one", review_args)
        self.assertIn("2", review_args)
        self.assertIn("a" * 64, review_args)
        self.assertEqual(review_args[-2:], ["--note", "Checked units."])

    def test_t23_execution_uses_fixed_hash_bound_cli_contract(self):
        client = SteelDataClient(ROOT.parent / "SteelData")
        with patch.object(client, "_call", side_effect=[
            {"suggestion_id": "review-one", "execution_status": "not_started"},
            {"suggestion_id": "review-one", "execution_status": "completed"},
        ]) as call:
            client.suggestion_execution_status("review-one")
            client.execute_suggestion("review-one", "a" * 64)
        status_args = call.call_args_list[0].args[0]
        execute_args = call.call_args_list[1].args[0]
        self.assertEqual(status_args.count("--suggestion-id"), 1)
        self.assertEqual(execute_args.count("--suggestion-id"), 1)
        self.assertEqual(execute_args.count("--expected-sha256"), 1)
        self.assertEqual(execute_args[-1], "a" * 64)

    def test_t24_intake_evaluation_requires_explicit_fixed_cli_actions(self):
        client = SteelDataClient(ROOT.parent / "SteelData")
        with patch.object(client, "_call", side_effect=[
            {"case_count": 40, "label_status": "pending_user_review"},
            {"evaluation_id": "IAE-test", "summary": {"passed_count": 40}},
        ]) as call:
            contract = client.intake_evaluation_contract()
            result = client.run_intake_reference_evaluation()
        self.assertEqual(contract["case_count"], 40)
        self.assertEqual(result["evaluation_id"], "IAE-test")
        self.assertEqual(call.call_args_list[0].args[0], ["intake-eval-contract"])
        run_args = call.call_args_list[1].args[0]
        self.assertEqual(run_args[0], "intake-eval-reference")
        self.assertEqual(run_args.count("--output"), 1)
        self.assertTrue(str(run_args[-1]).endswith("output\\intake_agent_evaluations"))


class PanelTests(unittest.TestCase):
    def test_valid_package_renders_mapping_without_default_sample(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result_fixture(run)
            app = AppTest.from_file(str(ROOT / "steelai/views/data_quality_panel.py"), default_timeout=20).run()
            app.text_input(key="sd_run_path").set_value(str(run)).run()
            app.button(key="sd_load").click().run()
            self.assertFalse(app.exception, str(app.exception))
            inspection = app.session_state["sd_inspection"]
            self.assertEqual(mapping_rows(inspection)[0]["sample_id"], "")
            self.assertTrue(any("真实来源状态" in item.label for item in app.selectbox))
            self.assertFalse(any(item.key == "sd_commit" for item in app.button))

    def test_common_and_advanced_import_tabs_render_without_module_execution(self):
        from streamlit.testing.v1 import AppTest
        with patch.object(SteelDataClient, "_call", side_effect=AssertionError("No automatic execution")):
            app = AppTest.from_file(str(ROOT / "steelai/views/data_quality_panel.py"), default_timeout=20).run()
        self.assertFalse(app.exception, str(app.exception))
        expected_tabs = [
            "导入实验表格", "导入热模拟", "查看数据状态", "高级工具",
            "标准表导入", "SteelData 接入", "字段与模板",
        ]
        self.assertEqual([t.label for t in app.tabs if t.label in expected_tabs], expected_tabs)
        self.assertTrue(any(item.label == "上传填写后的CSV" for item in app.get("file_uploader")))

    def test_synthetic_load_shows_disabled_commit(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result_fixture(run, synthetic=True)
            app = AppTest.from_file(str(ROOT / "steelai/views/data_quality_panel.py"), default_timeout=20).run()
            app.text_input(key="sd_run_path").set_value(str(run)).run()
            app.button(key="sd_load").click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertTrue(app.button(key="sd_blocked_commit").disabled)

    def test_t22_review_requires_human_fields_and_approves_only_one_loaded_digest(self):
        from streamlit.testing.v1 import AppTest
        row = {
            "suggestion_id": "review-one", "source_file": "source.csv", "domain": "tensile",
            "status": "needs_human", "revision": 2, "suggestion_sha256": "a" * 64,
            "uncertainty_count": 1,
        }
        view = {
            **row, "source_sha256": "b" * 64, "source_current_sha256": "b" * 64,
            "source_matches": True, "rationale": "header evidence", "profile_sha256": "c" * 64,
            "field_mappings": [{
                "source": "YS", "target": "ys_mpa", "dtype": "number",
                "source_unit": "MPa", "target_unit": "MPa",
                "evidence": ["header_unit"], "confidence": 1, "alternatives": [],
            }],
            "uncertainties": [{"field": "ys_mpa", "code": "unit_uncertain", "detail": "check", "alternatives": []}],
            "profile_diff": [{"path": "columns", "change": "added", "approved_value": None, "suggested_value": ["YS"]}],
            "diff_baseline": "new_profile", "risks": [{"code": "unit_uncertain", "severity": "warning", "message": "check"}],
            "can_review": True, "can_approve": True, "can_reject": True,
        }
        result = {
            "suggestion_id": "review-one", "status": "approved", "revision": 3,
            "suggestion_sha256": "a" * 64, "profile_sha256": "c" * 64,
            "approval_record_sha256": "d" * 64, "review_record_sha256": "e" * 64,
        }
        execution_status = {
            "suggestion_id": "review-one", "suggestion_status": "needs_human",
            "execution_status": "not_started", "attempts": 0,
        }
        execution_result = {
            "suggestion_id": "review-one", "suggestion_sha256": "a" * 64,
            "execution_status": "completed", "run_id": "run-test",
        }
        with patch.object(SteelDataClient, "availability", return_value={"ready": True, "project": "test"}), patch.object(
            SteelDataClient, "list_suggestions", return_value=[row]), patch.object(
            SteelDataClient, "show_suggestion", return_value=view), patch.object(
            SteelDataClient, "suggestion_execution_status", return_value=execution_status), patch.object(
            SteelDataClient, "review_suggestion", return_value=result) as review, patch(
            "steelai.views.steeldata_panel._execute_and_load", return_value=execution_result) as execute, patch(
            "steelai.views.steeldata_panel.record_event"):
            app = AppTest.from_file(str(ROOT / "steelai/views/data_quality_panel.py"), default_timeout=20).run()
            app.button(key="sd_suggestion_refresh").click().run()
            app.button(key="sd_suggestion_load").click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(app.text_input(key="sd_suggestion_reviewer_review-one").value, "")
            self.assertTrue(app.button(key="sd_suggestion_approve_review-one").disabled)
            app.text_input(key="sd_suggestion_reviewer_review-one").set_value("Researcher A")
            app.text_area(key="sd_suggestion_note_review-one").set_value("Checked source, fields, units and digest.")
            app.checkbox(key="sd_suggestion_approve_confirm_review-one").check().run()
            app.button(key="sd_suggestion_approve_review-one").click().run()
        self.assertFalse(app.exception, str(app.exception))
        review.assert_called_once()
        self.assertEqual(review.call_args.args[1], "approve")
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1:], ("review-one", "a" * 64))


if __name__ == "__main__":
    unittest.main()
