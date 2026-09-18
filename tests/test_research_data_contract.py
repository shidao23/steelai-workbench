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


CONTRACT_SOURCE = Path(__file__).resolve().parents[1] / "config" / "research_data_contract_v1.0.json"


def _layer_row(report: dict, layer: str) -> dict:
    return next(row for row in report["tables"] if row["layer"] == layer)


def _write_csv(root: Path, spec: dict, rows: list[dict]) -> None:
    path = root / spec["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(spec["essential_fields"] + spec.get("recommended_fields", [])))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "")) for field in fields})


def _softening_row(sample_id: str, experiment_run_id: str, softening_version: str) -> dict:
    return {
        "sample_id": sample_id,
        "experiment_run_id": experiment_run_id,
        "softening_version": softening_version,
    }


def _validate_softening_rows(rows: list[dict]) -> dict:
    """Isolated fixture: real contract shape, synthetic rows, no scientific data touched."""
    contract = json.loads(CONTRACT_SOURCE.read_text(encoding="utf-8"))
    tables = contract["tables"]
    tables["thermal_simulation_softening"] = {
        "path": tables["thermal_simulation_softening"]["path"],
        "required": False,
        "essential_fields": ["sample_id", "experiment_run_id", "softening_version"],
        "recommended_fields": [],
        "primary_key": ["experiment_run_id", "softening_version"],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        contract_path = root / "synthetic_contract.json"
        contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        for table_name, spec in tables.items():
            if not spec.get("required"):
                continue
            fields = list(dict.fromkeys(spec["essential_fields"] + spec.get("recommended_fields", [])))
            rows_for_table = []
            for sample_id in ("B-DQ", "R-DQ"):
                row = {field: "1" for field in fields}
                row["sample_id"] = sample_id
                if table_name == "samples":
                    row.update({"steel": "B" if sample_id == "B-DQ" else "R", "condition": "DQ", "batch": "fixture", "data_status": "synthetic"})
                rows_for_table.append(row)
            _write_csv(root, spec, rows_for_table)
        _write_csv(root, tables["thermal_simulation_softening"], rows)
        return validate_research_data_contract(contract_path, root)


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
        source_contract = json.loads(CONTRACT_SOURCE.read_text(encoding="utf-8"))
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

    def test_repeated_sample_id_across_distinct_experiment_runs_is_allowed(self):
        report = _validate_softening_rows([
            _softening_row("B-DQ", "EXPERIMENT-RUN-1", "softening_v1"),
            _softening_row("B-DQ", "EXPERIMENT-RUN-2", "softening_v1"),
            _softening_row("B-DQ", "EXPERIMENT-RUN-3", "softening_v1"),
        ])
        softening_problems = [
            item for item in report["problems"] if item.startswith("thermal_simulation_softening")
        ]
        self.assertEqual(softening_problems, [])
        self.assertEqual(report["contract_status"], "passed")
        self.assertEqual(_layer_row(report, "thermal_simulation_softening")["status"], "structured")
        self.assertEqual(_layer_row(report, "thermal_simulation_softening")["row_count"], 3)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("sample_id重复", serialized)
        self.assertNotIn("主键重复", serialized)

    def test_distinct_softening_versions_under_one_run_are_allowed(self):
        report = _validate_softening_rows([
            _softening_row("B-DQ", "EXPERIMENT-RUN-1", "softening_v1"),
            _softening_row("B-DQ", "EXPERIMENT-RUN-1", "softening_v2"),
            _softening_row("B-DQ", "EXPERIMENT-RUN-2", "softening_v1"),
        ])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["contract_status"], "passed")
        self.assertEqual(_layer_row(report, "thermal_simulation_softening")["row_count"], 3)

    def test_duplicate_composite_primary_key_still_fails(self):
        report = _validate_softening_rows([
            _softening_row("B-DQ", "EXPERIMENT-RUN-1", "softening_v1"),
            _softening_row("B-DQ", "EXPERIMENT-RUN-1", "softening_v1"),
        ])
        self.assertEqual(report["contract_status"], "failed")
        self.assertEqual(
            _layer_row(report, "thermal_simulation_softening")["status"],
            "blocked",
        )
        self.assertIn(
            "thermal_simulation_softening: 主键重复：EXPERIMENT-RUN-1 | softening_v1",
            report["problems"],
        )

    def test_unregistered_sample_id_still_fails_as_orphan(self):
        report = _validate_softening_rows([
            _softening_row("ORPHAN", "EXPERIMENT-RUN-1", "softening_v1"),
        ])
        self.assertEqual(report["contract_status"], "failed")
        self.assertEqual(
            _layer_row(report, "thermal_simulation_softening")["status"],
            "blocked",
        )
        self.assertIn(
            "thermal_simulation_softening存在未登记样品：ORPHAN",
            report["problems"],
        )

    def test_local_quality_gate_passes_without_api_call(self):
        result = run_quality_gate()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["checks"]["privacy_contract"])
        self.assertTrue(result["checks"]["graduation_data_contract"])
        self.assertTrue(result["checks"]["frictionless_optional_adapter"])
        self.assertTrue(result["checks"]["third_party_registry"])


if __name__ == "__main__":
    unittest.main()
