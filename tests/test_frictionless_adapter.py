import csv
import json
import shutil
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

from steelai.frictionless_adapter import (
    DESCRIPTOR_PATH,
    EXPECTED_FRICTIONLESS_VERSION,
    benchmark_public_data_package,
    build_data_package_descriptor,
    frictionless_availability,
    validate_public_data_package,
    validate_frictionless_evaluation,
    write_data_package_descriptor,
)
from steelai.graduation_data_contract import CONTRACT_PATH


ROOT = Path(__file__).resolve().parents[1]


class FrictionlessAdapterTests(unittest.TestCase):
    def test_committed_evaluation_and_lock_pass_without_optional_runtime(self):
        report = validate_frictionless_evaluation()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["locked_package_count"], 40)
        self.assertFalse(report["required_by_core"])

    def test_evaluation_rejects_claim_that_component_is_required_by_core(self):
        source = ROOT / "config" / "frictionless_adapter_evaluation_v1.0.json"
        record = json.loads(source.read_text(encoding="utf-8"))
        record["integration"]["required_by_core"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evaluation.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            report = validate_frictionless_evaluation(path)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("stay optional" in problem for problem in report["problems"]))

    def test_descriptor_is_relative_deterministic_and_matches_committed_example(self):
        expected = build_data_package_descriptor()
        actual = json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)
        self.assertEqual([item["name"] for item in actual["resources"]], [
            "materials", "heats", "samples", "specimens", "reports", "observations",
        ])
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in actual["resources"]))
        observations = next(item for item in actual["resources"] if item["name"] == "observations")
        value = next(field for field in observations["schema"]["fields"] if field["name"] == "value")
        self.assertEqual(value["type"], "number")

    def test_missing_component_is_cleanly_optional_and_native_contract_still_passes(self):
        missing = metadata.PackageNotFoundError("frictionless")
        with patch("steelai.frictionless_adapter.metadata.version", side_effect=missing):
            report = validate_public_data_package()
        self.assertEqual(report["status"], "unavailable")
        self.assertIsNone(report["valid"])
        self.assertFalse(report["required_by_core"])
        self.assertEqual(report["native_contract_status"], "passed")

    def test_wrong_component_version_is_rejected_without_becoming_a_core_failure(self):
        with patch("steelai.frictionless_adapter.metadata.version", return_value="5.20.0"):
            report = validate_public_data_package()
        self.assertEqual(report["status"], "version_mismatch")
        self.assertFalse(report["required_by_core"])

    def test_modified_or_remote_descriptor_is_blocked_before_optional_library(self):
        descriptor = json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))
        descriptor["resources"][0]["path"] = "https://example.invalid/private.csv"
        descriptor["resources"][0]["scheme"] = "https"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "datapackage.json"
            path.write_text(json.dumps(descriptor), encoding="utf-8")
            report = validate_public_data_package(path)
        self.assertEqual(report["status"], "blocked_descriptor_boundary")
        self.assertFalse(report["valid"])

    def test_benchmark_is_bounded_and_optional(self):
        with self.assertRaises(ValueError):
            benchmark_public_data_package(2)
        missing = metadata.PackageNotFoundError("frictionless")
        with patch("steelai.frictionless_adapter.metadata.version", side_effect=missing):
            report = benchmark_public_data_package(3)
        self.assertEqual(report["status"], "unavailable")

    def test_non_synthetic_identity_is_blocked_before_optional_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            source = ROOT / "data" / "examples" / "graduation_contract_v1"
            destination = root / "data" / "examples" / "graduation_contract_v1"
            shutil.copytree(source, destination)
            path = destination / "materials.csv"
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            rows[0]["material_id"] = "REAL-MAT-01"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            descriptor = write_data_package_descriptor(
                destination / "datapackage.json", contract_path, root,
            )
            report = validate_public_data_package(descriptor, contract_path, root)
        self.assertEqual(report["status"], "blocked_native_contract")
        self.assertTrue(any("not a SYN- identity" in problem for problem in report["public_boundary_problems"]))

    @unittest.skipUnless(frictionless_availability()["ready"], "optional frictionless adapter is not installed")
    def test_pinned_component_validates_the_public_package(self):
        report = validate_public_data_package()
        self.assertEqual(report["frictionless"]["version"], EXPECTED_FRICTIONLESS_VERSION)
        self.assertEqual(report["status"], "passed", report)
        self.assertTrue(report["valid"])


if __name__ == "__main__":
    unittest.main()
