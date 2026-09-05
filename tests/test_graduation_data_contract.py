import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from steelai.graduation_data_contract import (
    CONTRACT_PATH,
    load_graduation_contract,
    validate_graduation_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class GraduationDataContractTests(unittest.TestCase):
    def _copy_fixture(self, temporary: str) -> tuple[Path, Path]:
        root = Path(temporary)
        contract = load_graduation_contract()
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        source = ROOT / "data" / "examples" / "graduation_contract_v1"
        destination = root / "data" / "examples" / "graduation_contract_v1"
        shutil.copytree(source, destination)
        return root, contract_path

    def _append_observation(self, root: Path, row: dict[str, str]) -> None:
        path = root / "data" / "examples" / "graduation_contract_v1" / "observations.csv"
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writerow(row)

    def test_frozen_contract_and_public_example_graph_pass(self):
        report = validate_graduation_contract()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["contract_id"], "SteelAI-Graduation-Core-v1.0")
        self.assertEqual(report["table_counts"], {
            "heats": 1,
            "materials": 1,
            "observations": 11,
            "reports": 2,
            "samples": 1,
            "specimens": 3,
        })

    def test_identity_and_deferred_object_boundaries_are_explicit(self):
        contract = load_graduation_contract(CONTRACT_PATH)
        self.assertEqual(contract["status"], "frozen")
        self.assertEqual(
            set(contract["identity_roles"]),
            {"material_id", "heat_id", "sample_id", "specimen_id", "report_id", "observation_id"},
        )
        self.assertTrue(
            {"curve_point", "image_field", "ebsd_pixel"}.issubset(contract["deferred_object_roles"])
        )
        self.assertIn("never", contract["deferred_object_roles"]["ebsd_pixel"])

    def test_summary_curve_image_and_pixel_cannot_masquerade_as_specimens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, contract_path = self._copy_fixture(temporary)
            base = {
                "report_id": "SYN-REPORT-IND",
                "quantity": "ys_mpa",
                "value": "700",
                "unit": "MPa",
                "replicate_count": "1",
                "source_status": "synthetic_fixture",
                "source_record_id": "SYN-INVALID",
                "source_field": "ys_mpa",
                "notes": "deliberately invalid regression row",
            }
            invalid = [
                {**base, "observation_id": "SYN-BAD-SUM", "subject_type": "specimen", "subject_id": "SYN-T12-01", "statistic_type": "reported_mean"},
                {**base, "observation_id": "SYN-BAD-CURVE", "subject_type": "curve_point", "subject_id": "SYN-POINT-01", "statistic_type": "individual"},
                {**base, "observation_id": "SYN-BAD-FIELD", "subject_type": "image_field", "subject_id": "SYN-FIELD-01", "statistic_type": "individual"},
                {**base, "observation_id": "SYN-BAD-PIXEL", "subject_type": "ebsd_pixel", "subject_id": "SYN-PIXEL-01", "statistic_type": "individual"},
            ]
            for row in invalid:
                self._append_observation(root, row)
            report = validate_graduation_contract(contract_path, root)

        self.assertEqual(report["status"], "failed")
        text = " ".join(report["problems"])
        self.assertIn("statistic_type does not match specimen", text)
        self.assertIn("subject_type curve_point is not a v1 measurement subject", text)
        self.assertIn("subject_type image_field is not a v1 measurement subject", text)
        self.assertIn("subject_type ebsd_pixel is not a v1 measurement subject", text)

    def test_wrong_unit_or_unregistered_report_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, contract_path = self._copy_fixture(temporary)
            self._append_observation(root, {
                "observation_id": "SYN-BAD-UNIT",
                "report_id": "SYN-REPORT-MISSING",
                "subject_type": "specimen",
                "subject_id": "SYN-T12-01",
                "quantity": "uts_mpa",
                "value": "0.9",
                "unit": "GPa",
                "statistic_type": "individual",
                "replicate_count": "1",
                "source_status": "synthetic_fixture",
                "source_record_id": "SYN-INVALID",
                "source_field": "uts_mpa",
                "notes": "deliberately invalid regression row",
            })
            report = validate_graduation_contract(contract_path, root)

        self.assertEqual(report["status"], "failed")
        text = " ".join(report["problems"])
        self.assertIn("unregistered report_id", text)
        self.assertIn("uts_mpa requires unit MPa", text)

    def test_migration_requires_registration_and_never_invents_specimens(self):
        rules = load_graduation_contract()["migration_rules"]
        text = " ".join(item["rule"] for item in rules)
        self.assertIn("specimen and report registration", text)
        self.assertIn("never manufacture specimen rows", text)
        self.assertIn("batch_id is not inferred as heat_id", text)
        self.assertIn("never become specimen replicates", text)


if __name__ == "__main__":
    unittest.main()
