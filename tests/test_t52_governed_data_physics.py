"""T52 acceptance tests for governed data intake and Physics Engine runs."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steelai.data_intake import save_intake_package, validate_intake_csv
from steelai.data_intake_governance import (
    commit_standard_intake_governed,
    prepare_intake_governance,
    preview_intake_governance,
)
from steelai.governance import GovernanceError, load_verified_manifest, verify_package
from steelai.physics_governance import preview_physics_governance, run_governed_physics


ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-09-09T09:00:00+00:00"


class GovernedDataPhysicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.composition = {
            "C": 0.20,
            "Si": 0.25,
            "Mn": 1.35,
            "Ni": 0.20,
            "Cr": 0.65,
            "Mo": 0.22,
            "V": 0.03,
            "Nb": 0.025,
            "Ti": 0.018,
            "Al": 0.035,
            "Cu": 0.08,
            "As": 0.01,
            "B": 0.0015,
            "W": 0.0,
        }

    def _fixture(self, temp_root: Path) -> tuple[Path, Path]:
        contract = json.loads(
            (ROOT / "config" / "research_data_contract_v1.0.json").read_text(encoding="utf-8")
        )
        policy = json.loads(
            (ROOT / "config" / "research_id_policy_v1.0.json").read_text(encoding="utf-8")
        )
        contract_path = temp_root / "contract.json"
        policy_path = temp_root / "policy.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        sample_path = temp_root / "data" / "processed" / "samples.csv"
        sample_path.parent.mkdir(parents=True)
        sample_path.write_text(
            "sample_id,steel,condition,batch,data_status\n"
            "B-DQ,B,DQ,DQ_6PASS_B,verified\n"
            "R-DQ,R,DQ,DQ_6PASS_R,verified\n",
            encoding="utf-8",
        )
        return contract_path, policy_path

    def _process_report(self, root: Path, contract_path: Path, policy_path: Path) -> dict:
        content = (
            "sample_id,step_id,step_type,sequence,source_status,start_temp_c,end_temp_c\n"
            "B-DQ,B-DQ-P01,rolling,1,verified_from_source,1060,1010\n"
            "B-DQ,B-DQ-P02,rolling,2,verified_from_source,1000,950\n"
        ).encode("utf-8")
        return validate_intake_csv(
            "process_steps",
            content,
            contract_path=contract_path,
            project_root=root,
            id_policy_path=policy_path,
        )

    def test_unknown_unit_is_blocked_before_staging_or_commit(self) -> None:
        content = (
            "sample_id,observation_id,element,value,unit,source_status\n"
            "B-DQ,OBS-BDQ-0001,C,0.20,unregistered_unit,verified_from_source\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract_path, policy_path = self._fixture(root)
            report = validate_intake_csv(
                "composition_observations",
                content,
                contract_path=contract_path,
                project_root=root,
                id_policy_path=policy_path,
            )
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(preview_intake_governance(report)["state"], "needs_human")
            self.assertIn("GOV-UNIT-001", preview_intake_governance(report)["issue_codes"])
            legacy_package = save_intake_package(report, output_root=root / "legacy_preview")
            self.assertIsNone(legacy_package["normalized_staging"])
            with self.assertRaises(GovernanceError) as caught:
                commit_standard_intake_governed(
                    report,
                    reviewer_id="researcher-t52",
                    rationale="Unit has not been registered.",
                    confirmed=True,
                    project_root=root,
                    contract_path=contract_path,
                    id_policy_path=policy_path,
                    output_root=root / "governed",
                    decided_at=STAMP,
                )
            self.assertEqual(caught.exception.code, "GOV-UNIT-001")
            self.assertFalse((root / "data" / "processed" / "composition_observations.csv").exists())

    def test_manual_route_requires_approval_and_publishes_append_only_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract_path, policy_path = self._fixture(root)
            report = self._process_report(root, contract_path, policy_path)
            self.assertEqual(report["status"], "ready")
            unapproved = prepare_intake_governance(report, route="standard_csv", decided_at=STAMP)
            self.assertEqual(unapproved.state, "draft")

            result = commit_standard_intake_governed(
                report,
                reviewer_id="researcher-t52",
                rationale="Reviewed normalized rows, sample identity and append destination.",
                confirmed=True,
                project_root=root,
                contract_path=contract_path,
                id_policy_path=policy_path,
                output_root=root / "governed",
                decided_at=STAMP,
            )
            destination = root / "data" / "processed" / "process_steps.csv"
            original = destination.read_bytes()
            package = Path(result["governance_package"])
            self.assertEqual(result["rows_added"], 2)
            self.assertEqual(result["governance_state"], "complete")
            self.assertEqual(verify_package(package).status, "passed")
            manifest = load_verified_manifest(package)
            self.assertEqual(manifest.state, "complete")
            self.assertEqual(manifest.result_level, "accepted_evidence")
            record = json.loads((package / "governance_record.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [item["to_state"] for item in record["transitions"]],
                ["approved", "running", "passed", "complete"],
            )

            duplicate = self._process_report(root, contract_path, policy_path)
            self.assertEqual(duplicate["status"], "blocked")
            with self.assertRaises(GovernanceError) as caught:
                commit_standard_intake_governed(
                    duplicate,
                    reviewer_id="researcher-t52",
                    rationale="Duplicate replay check.",
                    confirmed=True,
                    project_root=root,
                    contract_path=contract_path,
                    id_policy_path=policy_path,
                    output_root=root / "governed",
                    decided_at=STAMP,
                )
            self.assertEqual(caught.exception.code, "GOV-DUPLICATE-001")
            self.assertEqual(destination.read_bytes(), original)

    def test_manual_and_steeldata_routes_share_one_governance_record_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract_path, policy_path = self._fixture(root)
            report = self._process_report(root, contract_path, policy_path)
            standard = prepare_intake_governance(
                report,
                route="standard_csv",
                reviewer_id="researcher-t52",
                rationale="Standard-route contract check.",
                confirmed=True,
                decided_at=STAMP,
            )
            steeldata = prepare_intake_governance(
                report,
                route="steeldata",
                reviewer_id="researcher-t52",
                rationale="SteelData-route contract check.",
                confirmed=True,
                source_id="STEELDATA-SYN-T52-RUN-001",
                source_digest="1" * 64,
                decided_at=STAMP,
            )
            self.assertEqual(set(standard.to_dict()), set(steeldata.to_dict()))
            self.assertEqual(standard.state, steeldata.state, "approved")
            self.assertEqual(standard.approvals[0].governance_contract_id,
                             steeldata.approvals[0].governance_contract_id)

    def test_missing_physics_input_is_never_substituted_with_zero(self) -> None:
        preview = preview_physics_governance(
            "B-DQ",
            {"C": 0.20},
            provided_fields={"C"},
        )
        self.assertEqual(preview.state, "blocked")
        self.assertFalse(preview.input_snapshot["missing_values_are_zero"])
        self.assertTrue(any(result.value is None for result in preview.results))
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "physics"
            with self.assertRaises(GovernanceError) as caught:
                run_governed_physics(
                    "B-DQ",
                    {"C": 0.20},
                    reviewer_id="researcher-t52",
                    rationale="Missing-input block check.",
                    accept_warnings=True,
                    provided_fields={"C"},
                    output_root=output_root,
                    decided_at=STAMP,
                )
            self.assertEqual(caught.exception.code, "GOV-SCHEMA-001")
            self.assertFalse(output_root.exists())

    def test_out_of_range_physics_run_requires_warning_acceptance(self) -> None:
        composition = dict(self.composition)
        composition["C"] = 0.80
        preview = preview_physics_governance(
            "B-DQ",
            composition,
            provided_fields=set(composition),
        )
        self.assertEqual(preview.state, "needs_human")
        self.assertIn("GOV-SCOPE-001", preview.error_codes)
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "physics"
            with self.assertRaises(GovernanceError) as caught:
                run_governed_physics(
                    "B-DQ",
                    composition,
                    reviewer_id="researcher-t52",
                    rationale="Range warning is not accepted.",
                    accept_warnings=False,
                    provided_fields=set(composition),
                    output_root=output_root,
                    decided_at=STAMP,
                )
            self.assertEqual(caught.exception.code, "GOV-SCOPE-001")
            self.assertFalse(output_root.exists())

    def test_physics_run_publishes_traceable_estimate_and_reuses_identical_run(self) -> None:
        observations = [{
            "sample_id": "B-DQ",
            "observation_id": "OBS-BDQ-MS-01",
            "quantity": "Ms",
            "value": "400",
            "unit": "°C",
            "measurement_type": "experimental",
            "source_status": "synthetic_contract_fixture",
        }]
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "physics"
            result = run_governed_physics(
                "B-DQ",
                self.composition,
                reviewer_id="researcher-t52",
                rationale="Reviewed formula versions, input snapshot and applicability warnings.",
                accept_warnings=True,
                provided_fields=set(self.composition),
                observations=observations,
                output_root=output_root,
                decided_at=STAMP,
            )
            package = Path(result["package"])
            self.assertFalse(result["reused"])
            self.assertEqual(verify_package(package).status, "passed")
            manifest = load_verified_manifest(package)
            self.assertEqual(manifest.evidence_class, "model_output")
            self.assertEqual(manifest.result_level, "model_result")
            self.assertEqual(manifest.metadata["result_type"],
                             "empirical_model_estimate_not_experimental_truth")
            snapshot = json.loads((package / "input_snapshot.json").read_text(encoding="utf-8"))
            self.assertFalse(snapshot["missing_values_are_zero"])
            self.assertEqual(len(snapshot["models"]), 6)
            self.assertTrue(all(model["model_id"] and model["model_version"] for model in snapshot["models"]))
            results = json.loads((package / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(results["result_type"], "empirical_model_estimate_not_experimental_truth")
            comparison = json.loads(
                (package / "experimental_comparison.json").read_text(encoding="utf-8")
            )
            self.assertEqual(comparison["residual_definition"], "model_value - experimental_value")
            self.assertEqual(len(list((package / "model_cards").glob("*.md"))), 6)

            replay = run_governed_physics(
                "B-DQ",
                self.composition,
                reviewer_id="researcher-t52",
                rationale="Reviewed formula versions, input snapshot and applicability warnings.",
                accept_warnings=True,
                provided_fields=set(self.composition),
                observations=observations,
                output_root=output_root,
                decided_at=STAMP,
            )
            self.assertTrue(replay["reused"])
            self.assertEqual(replay["run_id"], result["run_id"])

    def test_tampered_physics_package_is_invalidated_and_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "physics"
            first = run_governed_physics(
                "B-DQ",
                self.composition,
                reviewer_id="researcher-t52",
                rationale="Create isolated package for tamper test.",
                accept_warnings=True,
                provided_fields=set(self.composition),
                output_root=output_root,
                decided_at=STAMP,
            )
            package = Path(first["package"])
            (package / "results.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(verify_package(package).status, "invalidated")
            with self.assertRaises(GovernanceError) as caught:
                run_governed_physics(
                    "B-DQ",
                    self.composition,
                    reviewer_id="researcher-t52",
                    rationale="Invalidated package must not be replaced.",
                    accept_warnings=True,
                    provided_fields=set(self.composition),
                    output_root=output_root,
                    decided_at=STAMP,
                )
            self.assertEqual(caught.exception.code, "GOV-INTEGRITY-001")
            self.assertEqual((package / "results.json").read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
