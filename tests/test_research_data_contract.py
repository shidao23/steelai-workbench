import csv
import json
import tempfile
import unittest
from pathlib import Path

from steelai.quality_gate import run_quality_gate
from steelai.research_data_contract import (
    contract_report_markdown,
    validate_research_data_contract,
)


class ResearchDataContractTests(unittest.TestCase):
    def test_current_br_tables_pass_structure_without_claiming_ml_readiness(self):
        report = validate_research_data_contract()
        self.assertEqual(report["contract_status"], "passed")
        self.assertEqual(report["sample_count"], 2)
        self.assertFalse(report["scientific_readiness"]["causal_inference_ready"])
        self.assertFalse(report["scientific_readiness"]["machine_learning_ready"])
        statuses = {row["layer"]: row["status"] for row in report["tables"]}
        self.assertEqual(statuses["composition"], "structured")
        self.assertEqual(statuses["process"], "partial")
        self.assertEqual(statuses["microstructure"], "partial")
        self.assertEqual(statuses["physics_observations"], "not_started_optional")

    def test_report_keeps_missing_zero_and_model_boundaries(self):
        text = contract_report_markdown()
        self.assertIn("Blank values are missing, not zero", text)
        self.assertIn("Model estimates are not experimental truth", text)
        self.assertIn("Experiments 1-14 remain excluded", text)

    def test_contract_rejects_orphan_sample_and_invalid_numeric_value(self):
        source_contract = json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "research_data_contract_v1.0.json")
            .read_text(encoding="utf-8")
        )
        source_contract["scope"]["included_samples"] = ["B-DQ"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(source_contract), encoding="utf-8")
            for table_name, spec in source_contract["tables"].items():
                if not spec.get("required"):
                    continue
                path = root / spec["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                fields = list(dict.fromkeys(spec["essential_fields"] + spec.get("recommended_fields", [])))
                row = {field: "1" for field in fields}
                row["sample_id"] = "B-DQ" if table_name == "samples" else "ORPHAN"
                if table_name == "samples":
                    row.update({"steel": "B", "condition": "DQ", "batch": "test", "data_status": "synthetic"})
                if table_name == "composition":
                    row["C"] = "not-a-number"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow(row)
            report = validate_research_data_contract(contract_path, root)
            self.assertEqual(report["contract_status"], "failed")
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertIn("不是数值", serialized)
            self.assertIn("未登记样品", serialized)

    def test_local_quality_gate_passes_without_api_call(self):
        result = run_quality_gate()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["checks"]["privacy_contract"])
        self.assertTrue(result["checks"]["graduation_data_contract"])
        self.assertTrue(result["checks"]["third_party_registry"])


if __name__ == "__main__":
    unittest.main()
