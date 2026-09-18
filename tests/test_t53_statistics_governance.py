"""T53 tests use synthetic contracts and temporary directories only."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from steelai.evidence_validation import validation_report_markdown, validation_summary
from steelai.governance import GovernanceError, load_verified_manifest, verify_package
from steelai.statistics_governance import (
    build_statistics_statement_policy,
    inspect_governed_statistics,
    register_statistics_result,
    run_governed_statistics_from_steeldata,
)
from steelai.steeldata_bridge import inspect_run, mapping_rows
from steelai.steelstats_bridge import SteelStatsClient
from tests.test_steeldata_bridge import result_fixture


STAMP = "2026-09-09T10:00:00+00:00"
REVIEWER = "Researcher A"
ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _fixture(root: Path, *, quality_status: str = "passed") -> dict:
    input_root = root / "input"
    report_root = root / "report"
    input_root.mkdir()
    report_root.mkdir()
    method = "tensile-iso6892-1@1.0.0"
    plan = {
        "plan_id": "SYN-T53-PLAN-001",
        "plan_version": "1.0.0",
        "statistical_unit_type": "specimen",
        "group_keys": ["sample_id", "quantity", "unit", "method_version"],
        "method_versions": {quantity: method for quantity in ("ys_mpa", "uts_mpa", "elongation_pct")},
        "summary_policy": "descriptive_only_not_raw_replicate",
    }
    (input_root / "analysis_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    units = []
    observations = []
    decisions = []
    values = {
        "B-DQ": {"ys_mpa": [940, 950, 960], "uts_mpa": [1100, 1110, 1120], "elongation_pct": [12, 13, 14]},
        "R-DQ": {"ys_mpa": [920, 930, 940], "uts_mpa": [1080, 1090, 1100], "elongation_pct": [11, 12, 13]},
    }
    units_by_group: dict[tuple[str, str], list[dict]] = {}
    for sample_id, quantities in values.items():
        for index in range(3):
            specimen_id = f"{sample_id}-S{index + 1:02d}"
            units.append({
                "unit_id": specimen_id,
                "unit_type": "specimen",
                "parent_unit_id": sample_id,
                "parent_unit_type": "sample",
                "sample_id": sample_id,
                "specimen_id": specimen_id,
                "unit_status": "verified",
                "notes": "synthetic T53 contract fixture",
            })
            for quantity, group_values in quantities.items():
                observation_id = f"OBS-{sample_id}-{quantity}-{index + 1}"
                unit = "%" if quantity == "elongation_pct" else "MPa"
                observations.append({
                    "observation_id": observation_id,
                    "subject_type": "specimen",
                    "subject_id": specimen_id,
                    "sample_id": sample_id,
                    "specimen_id": specimen_id,
                    "quantity": quantity,
                    "value": group_values[index],
                    "unit": unit,
                    "quality_status": "passed",
                    "measurement_role": "individual",
                    "missing_reason": "",
                    "method_version": method,
                    "report_id": "SYN-T53-SOURCE-RUN",
                    "source_record_id": observation_id,
                    "notes": "synthetic contract fixture",
                })
                decisions.append({
                    "observation_id": observation_id,
                    "decision": "include",
                    "reason_code": "eligible_predeclared",
                    "reviewer": REVIEWER,
                    "reviewed_at": STAMP,
                    "evidence_ref": "steeldata-manifest-sha256:" + "a" * 64,
                })
                units_by_group.setdefault((sample_id, quantity), []).append({
                    "observation_id": observation_id,
                    "statistical_unit_id": specimen_id,
                    "value": group_values[index],
                })
    _write_csv(input_root / "units.csv", list(units[0]), units)
    _write_csv(input_root / "observations.csv", list(observations[0]), observations)
    _write_csv(input_root / "decisions.csv", list(decisions[0]), decisions)

    groups = []
    for (sample_id, quantity), included in sorted(units_by_group.items()):
        numbers = [row["value"] for row in included]
        groups.append({
            "group": {
                "sample_id": sample_id,
                "quantity": quantity,
                "unit": "%" if quantity == "elongation_pct" else "MPa",
                "method_version": method,
            },
            "included_unit_observations": included,
            "interpretation": "descriptive_only_no_inference",
            "qc": {
                "status": quality_status,
                "n_distinct_statistical_units": 3,
                "issue_codes": [] if quality_status == "passed" else ["synthetic_warning"],
            },
            "statistics": {
                "n": 3,
                "mean": sum(numbers) / 3,
                "median": sorted(numbers)[1],
                "sample_standard_deviation": 10.0,
                "minimum": min(numbers),
                "maximum": max(numbers),
                "range": max(numbers) - min(numbers),
            },
        })
    result = {
        "analysis_id": "STS-SYN-T53-001",
        "status": quality_status,
        "statistics_method_version": "steelstats-descriptive@1.0.0",
        "group_count": len(groups),
        "groups": groups,
        "guardrails": {
            "inferential_statistics": False,
            "source_files_modified": False,
            "imputation": False,
        },
    }
    (report_root / "statistics_result.json").write_text(json.dumps(result), encoding="utf-8")
    (report_root / "statistics_report.md").write_text(
        "# Synthetic SteelStats report\n\nDescriptive only.\n",
        encoding="utf-8",
    )
    (report_root / "report_manifest.json").write_text(
        json.dumps({"analysis_id": result["analysis_id"], "status": "complete"}),
        encoding="utf-8",
    )
    (report_root / "COMPLETE").write_text("synthetic-test-marker\n", encoding="utf-8")
    return {
        "status": "complete",
        "quality_status": quality_status,
        "analysis_id": result["analysis_id"],
        "report": str(report_root / "statistics_report.md"),
        "result": str(report_root / "statistics_result.json"),
        "report_dir": str(report_root),
        "input_bundle": str(input_root),
        "source": {
            "run_id": "SYN-T53-SOURCE-RUN",
            "manifest_sha256": "a" * 64,
            "qc_status": quality_status,
            "warnings": [] if quality_status == "passed" else ["synthetic warning"],
            "modified": False,
        },
        "statistics": {
            "status": quality_status,
            "method_version": result["statistics_method_version"],
            "verification": "passed",
        },
    }


class StatisticsGovernanceTests(unittest.TestCase):
    def _register(self, root: Path, *, quality_status: str = "passed", accept_warnings: bool = False) -> dict:
        return register_statistics_result(
            _fixture(root, quality_status=quality_status),
            reviewer_id=REVIEWER,
            rationale="Reviewed statistical units, inclusion decisions, methods and source binding.",
            reviewed_at=STAMP,
            accept_warnings=accept_warnings,
            output_root=root / "governed",
        )

    def test_complete_report_backtraces_to_units_observations_decisions_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._register(root)
            package = Path(result["governance_package"])
            self.assertEqual(verify_package(package).status, "passed")
            manifest = load_verified_manifest(package)
            self.assertEqual(manifest.state, "complete")
            self.assertEqual(manifest.result_level, "accepted_evidence")
            registry = json.loads((package / "statistics_registry.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["counts"], {
                "statistical_units": 6,
                "observations": 18,
                "inclusion_decisions": 18,
                "groups": 6,
            })
            self.assertEqual(registry["source"]["steeldata_manifest_sha256"], "a" * 64)
            trace = json.loads((package / "traceability_index.json").read_text(encoding="utf-8"))
            for key in ("statistical_units", "observations", "inclusion_decisions", "statistics_result"):
                self.assertTrue((package / trace[key]).is_file())
            report = (package / "traceable_statistics_report.md").read_text(encoding="utf-8")
            self.assertIn(result["governance_id"], report)
            self.assertIn("SteelData Manifest SHA-256", report)

    def test_statement_policy_keeps_descriptive_difference_out_of_inference_and_causality(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._register(Path(temporary))
            policy = result["statement_policy"]
            self.assertEqual(policy["evidence_level"], "L3")
            self.assertFalse(policy["inferential_statistics_performed"])
            self.assertFalse(policy["causal_inference_allowed"])
            prohibited = " ".join(policy["prohibited_statements"])
            self.assertIn("统计显著差异", prohibited)
            self.assertIn("因果作用", prohibited)
            self.assertNotIn("显著", " ".join(policy["allowed_statements"]))

    def test_warning_requires_explicit_acceptance_and_is_bound_to_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_result = _fixture(root, quality_status="warning")
            with self.assertRaises(GovernanceError) as caught:
                register_statistics_result(
                    run_result,
                    reviewer_id=REVIEWER,
                    rationale="Warning not yet accepted.",
                    reviewed_at=STAMP,
                    accept_warnings=False,
                    output_root=root / "blocked",
                )
            self.assertEqual(caught.exception.code, "GOV-SCOPE-001")
            self.assertFalse((root / "blocked").exists())
            accepted = register_statistics_result(
                run_result,
                reviewer_id=REVIEWER,
                rationale="Reviewed and retained the declared warning.",
                reviewed_at=STAMP,
                accept_warnings=True,
                output_root=root / "accepted",
            )
            record = json.loads(
                (Path(accepted["governance_package"]) / "governance_record.json").read_text(encoding="utf-8")
            )
            self.assertIn("warning_accepted", {item["decision"] for item in record["approvals"]})
            self.assertEqual(record["quality_status"], "warning")

    def test_identical_registration_reuses_and_tampering_invalidates_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_result = _fixture(root)
            kwargs = {
                "run_result": run_result,
                "reviewer_id": REVIEWER,
                "rationale": "Reviewed statistical units, inclusion decisions, methods and source binding.",
                "reviewed_at": STAMP,
                "accept_warnings": False,
                "output_root": root / "governed",
            }
            first = register_statistics_result(**kwargs)
            second = register_statistics_result(**kwargs)
            self.assertFalse(first["governance_reused"])
            self.assertTrue(second["governance_reused"])
            package = Path(first["governance_package"])
            report_path = package / "traceable_statistics_report.md"
            report_path.write_text("tampered\n", encoding="utf-8")
            self.assertEqual(inspect_governed_statistics(package)["status"], "invalidated")
            with self.assertRaises(GovernanceError) as caught:
                register_statistics_result(**kwargs)
            self.assertEqual(caught.exception.code, "GOV-INTEGRITY-001")
            self.assertEqual(report_path.read_text(encoding="utf-8"), "tampered\n")

    def test_evidence_validation_consumes_only_verified_governed_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._register(Path(temporary))
            summary = validation_summary(
                {},
                {},
                {},
                statistics_package=result["governance_package"],
            )
            governed = summary["governed_statistics"]
            self.assertEqual(governed["governance_id"], result["governance_id"])
            self.assertEqual(governed["evidence_level"], "L3")
            mechanical = next(item for item in summary["evidence"] if item["evidence_id"] == "E-MECH-001")
            self.assertEqual(mechanical["status"], "governed_statistics_complete")
            report = validation_report_markdown(summary)
            self.assertIn("Governed Statistical Evidence", report)
            self.assertIn(result["governance_id"], report)

    def test_unverified_or_failed_statistics_never_enters_governed_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = _fixture(root)
            result["statistics"]["verification"] = "failed"
            with self.assertRaises(GovernanceError) as caught:
                register_statistics_result(
                    result,
                    reviewer_id=REVIEWER,
                    rationale="Unverified result must be rejected.",
                    reviewed_at=STAMP,
                    accept_warnings=False,
                    output_root=root / "governed",
                )
            self.assertEqual(caught.exception.code, "GOV-INTEGRITY-001")
            self.assertFalse((root / "governed").exists())


class GovernedStatisticsEndToEndTests(unittest.TestCase):
    def test_real_cli_governance_wrapper_keeps_steeldata_source_unchanged(self) -> None:
        client = SteelStatsClient(ROOT.parent / "SteelStats")
        if not client.availability()["ready"]:
            self.skipTest("Sibling SteelStats independent runtime is unavailable.")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "steeldata" / "run-test"
            result_fixture(run)
            inspection = inspect_run(run)
            bindings = {item["mapping_key"]: "SYN-SAMPLE-A" for item in mapping_rows(inspection)}
            before = {
                path.relative_to(run).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in run.rglob("*")
                if path.is_file()
            }
            result = run_governed_statistics_from_steeldata(
                run,
                bindings,
                "tensile-iso6892-1@1.0.0",
                REVIEWER,
                STAMP,
                rationale="Reviewed isolated end-to-end T53 contract fixture.",
                accept_warnings=True,
                input_root=root / "inputs",
                report_root=root / "reports",
                governance_root=root / "governed",
                client=client,
            )
            after = {
                path.relative_to(run).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in run.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertEqual(result["source"]["modified"], False)
            self.assertEqual(verify_package(result["governance_package"]).status, "passed")


if __name__ == "__main__":
    unittest.main()
