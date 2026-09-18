"""G09 end-to-end matrix; all inputs and outputs are synthetic and temporary."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steelai.steeldata_bridge import (
    SteelDataClient,
    commit_run,
    inspect_run,
    mapping_rows,
    prepare_intake,
)
from steelai.views.steeldata_panel import steeldata_state_presentation


ROOT = Path(__file__).resolve().parents[1]
STEELDATA = ROOT.parent / "SteelData"
STEELDATA_PYTHON = STEELDATA / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
FIXTURES = ROOT / "tests/fixtures/g09_import_matrix"


@unittest.skipUnless(STEELDATA_PYTHON.is_file(), "sibling SteelData environment is unavailable")
class G09ImportMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expectations = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))
        cls.cases = {item["id"]: item for item in cls.expectations["cases"]}

    def setUp(self) -> None:
        self.client = SteelDataClient(project=STEELDATA)
        self.assertTrue(self.client.availability()["ready"])

    def _approved_profile(self, root: Path) -> tuple[Path, dict]:
        profile = json.loads(
            (STEELDATA / "steeldata/demo_data/profiles/tensile-results-v1.json").read_text(encoding="utf-8")
        )
        profile["profile_id"] = "synthetic-g09-matrix-only"
        profile["description"] = "SYNTHETIC G09 fixture; not laboratory data or a real approval"
        profile_path = root / "profile.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        checked = self.client._call(["profile", str(profile_path)])
        approval = root / "approval.json"
        self.client._call([
            "approve", "--profile", str(profile_path),
            "--expected-sha256", checked["profile_sha256"],
            "--reviewer", "automated-g09-test-not-human",
            "--note", "temporary synthetic matrix test only",
            "--output", str(approval),
        ])
        return approval, profile

    def _run_case(self, root: Path, case_id: str) -> tuple[dict, dict, Path]:
        case = self.cases[case_id]
        inputs = root / "inputs"
        inputs.mkdir()
        source = inputs / case["input"]
        source.write_bytes((FIXTURES / case["input"]).read_bytes())
        approval, profile = self._approved_profile(root)
        result = self.client._call([
            "run", "--input", str(inputs), "--approval", str(approval),
            "--output", str(root / "results"),
        ], accepted=(0, 2, 3))
        return result, profile, source

    def test_matrix_contract_declares_all_five_synthetic_cases(self) -> None:
        self.assertEqual(self.expectations["fixture_classification"], "synthetic_test_only")
        self.assertEqual(set(self.cases), {"valid", "unknown_unit", "offline", "stale_approval", "tamper"})
        self.assertTrue(all(item["input"].startswith(("valid_", "unknown_unit_")) for item in self.cases.values()))

    def test_valid_approved_profile_reaches_temporary_append_only_commit(self) -> None:
        case = self.cases["valid"]
        with tempfile.TemporaryDirectory(prefix="g09-valid-") as temp:
            root = Path(temp)
            result, _, source = self._run_case(root, "valid")
            verified = self.client._call(["verify", result["run_dir"]])
            inspection = inspect_run(result["run_dir"])
            workbench = root / "workbench"
            (workbench / "data/processed").mkdir(parents=True)
            (workbench / "data/processed/samples.csv").write_text("sample_id\nB-DQ\n", encoding="utf-8")
            bindings = {row["mapping_key"]: "B-DQ" for row in mapping_rows(inspection)}
            candidate = prepare_intake(inspection, bindings, "instrument_export", project_root=workbench)
            committed = commit_run(
                result["run_dir"], bindings, "instrument_export", candidate["preview_sha256"],
                reviewer="automated-g09-test", note="temporary synthetic matrix only",
                confirmed=True, project_root=workbench,
            )

            self.assertEqual(result["processing_status"], case["expected_processing_status"])
            self.assertEqual(verified["integrity"], "verified")
            self.assertTrue(inspection.transferable, inspection.blockers)
            self.assertEqual(committed["rows_added"], 3)
            self.assertEqual(steeldata_state_presentation("completed")["state"], case["expected_ui_state"])
            self.assertTrue(source.is_file())

    def test_unknown_unit_is_preserved_and_stops_before_workbench_write(self) -> None:
        case = self.cases["unknown_unit"]
        with tempfile.TemporaryDirectory(prefix="g09-unit-") as temp:
            root = Path(temp)
            result, _, source = self._run_case(root, "unknown_unit")
            verified = self.client._call(["verify", result["run_dir"]])
            inspection = inspect_run(result["run_dir"])

            self.assertEqual(result["processing_status"], case["expected_processing_status"])
            self.assertEqual(verified["integrity"], "verified")
            self.assertFalse(inspection.transferable)
            self.assertTrue(any("未处理完成" in item or "没有可接入" in item for item in inspection.blockers))
            self.assertEqual(steeldata_state_presentation("blocked")["state"], case["expected_ui_state"])
            self.assertIn("YS (ksi)", source.read_text(encoding="utf-8"))
            self.assertFalse((root / "workbench").exists())

    def test_agent_and_model_offline_environment_keeps_deterministic_result_reviewable(self) -> None:
        case = self.cases["offline"]
        poison = {
            "DSH_HOME": r"Z:\missing-dsh",
            "DSH_EXECUTABLE": r"Z:\missing-dsh\dsh.exe",
            "OPENCLAW_HOME": r"Z:\missing-openclaw",
            "WORKBUDDY_HOME": r"Z:\missing-workbuddy",
            "DEEPSEEK_API_KEY": "unusable-test-value",
            "OPENAI_API_KEY": "unusable-test-value",
            "HTTPS_PROXY": "http://127.0.0.1:1",
        }
        with tempfile.TemporaryDirectory(prefix="g09-offline-") as temp, patch.dict(
            os.environ, poison, clear=False
        ):
            root = Path(temp)
            result, _, _ = self._run_case(root, "offline")
            verified = self.client._call(["verify", result["run_dir"]])
            inspection = inspect_run(result["run_dir"])

        self.assertEqual(result["processing_status"], case["expected_processing_status"])
        self.assertEqual(verified["integrity"], "verified")
        self.assertTrue(inspection.transferable, inspection.blockers)
        self.assertEqual(steeldata_state_presentation("needs_human")["state"], case["expected_ui_state"])

    def test_replayed_stale_approval_revision_fails_closed_without_execution(self) -> None:
        case = self.cases["stale_approval"]
        with tempfile.TemporaryDirectory(prefix="g09-stale-") as temp:
            root = Path(temp)
            inbox = root / "inbox_v2"
            inbox.mkdir()
            source = (FIXTURES / case["input"]).read_bytes()
            (inbox / "source.csv").write_bytes(source)
            _, profile = self._approved_profile(root)
            mappings = [{
                "source": column["source"],
                "target": column["target"],
                "dtype": column.get("dtype", "number"),
                "source_unit": column.get("unit"),
                "target_unit": column.get("target_unit"),
                "evidence": ["exact_header"] + (["header_unit"] if column.get("unit") else []),
                "confidence": 1,
            } for column in profile["columns"]]
            payload = {
                "suggestion_id": "g09-stale-approval",
                "source_file": "source.csv",
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "domain": "tensile",
                "proposed_profile": profile,
                "field_mappings": mappings,
                "uncertainties": [],
                "rationale": "Synthetic exact-header G09 contract fixture.",
            }
            payload_path = root / "suggestion.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            created = self.client._call([
                "suggestion-create", "--workspace", str(root), "--payload", str(payload_path),
            ])
            review_args = [
                "suggestion-review", "--workspace", str(root),
                "--suggestion-id", created["suggestion_id"], "--decision", "approve",
                "--expected-revision", str(created["revision"]),
                "--expected-sha256", created["suggestion_sha256"],
                "--reviewer", "automated-g09-test-not-human",
                "--note", "temporary stale revision test only",
            ]
            first = self.client._call(review_args)
            with self.assertRaisesRegex(ValueError, case["expected_error"]):
                self.client._call(review_args)

            self.assertEqual(first["status"], "approved")
            self.assertEqual(len(list((root / "approved_v2").glob("*.json"))), 1)
            self.assertFalse((root / "executions_v2").exists())
            self.assertEqual(steeldata_state_presentation("blocked")["state"], case["expected_ui_state"])

    def test_tampered_sealed_result_is_invalidated_before_workbench_write(self) -> None:
        case = self.cases["tamper"]
        with tempfile.TemporaryDirectory(prefix="g09-tamper-") as temp:
            root = Path(temp)
            result, _, _ = self._run_case(root, "tamper")
            report = Path(result["run_dir"]) / "report.html"
            report.write_text("tampered after publication", encoding="utf-8")

            with self.assertRaises(ValueError):
                self.client._call(["verify", result["run_dir"]])
            with self.assertRaises(ValueError):
                inspect_run(result["run_dir"])
            self.assertEqual(steeldata_state_presentation("invalidated")["state"], case["expected_ui_state"])
            self.assertFalse((root / "workbench").exists())


if __name__ == "__main__":
    unittest.main()
