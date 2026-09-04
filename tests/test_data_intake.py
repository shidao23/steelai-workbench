import csv
import json
import tempfile
import unittest
from pathlib import Path

from steelai.data_intake import (
    commit_intake,
    save_intake_package,
    template_csv_bytes,
    validate_intake_csv,
)


ROOT = Path(__file__).resolve().parents[1]


class DataIntakeTests(unittest.TestCase):
    def _fixture(self, temp_root: Path) -> tuple[Path, Path]:
        contract = json.loads((ROOT / "config" / "research_data_contract_v1.0.json").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "config" / "research_id_policy_v1.0.json").read_text(encoding="utf-8"))
        contract_path = temp_root / "contract.json"
        policy_path = temp_root / "policy.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        sample_path = temp_root / "data" / "processed" / "samples.csv"
        sample_path.parent.mkdir(parents=True)
        sample_path.write_text(
            "sample_id,steel,condition,batch,data_status\nB-DQ,B,DQ,DQ_6PASS_B,verified\nR-DQ,R,DQ,DQ_6PASS_R,verified\n",
            encoding="utf-8",
        )
        return contract_path, policy_path

    def test_template_is_header_only_and_keeps_required_fields(self):
        text = template_csv_bytes("property_observations").decode("utf-8-sig")
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("specimen_id", text)
        self.assertIn("source_status", text)

    def test_valid_process_steps_can_be_staged_and_appended(self):
        content = (
            "sample_id,step_id,step_type,sequence,source_status,start_temp_c,end_temp_c\n"
            "B-DQ,B-DQ-P01,rolling,1,verified_from_source,1060,1010\n"
            "B-DQ,B-DQ-P02,rolling,2,verified_from_source,1000,950\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path, policy_path = self._fixture(root)
            report = validate_intake_csv(
                "process_steps", content, contract_path=contract_path,
                project_root=root, id_policy_path=policy_path,
            )
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["row_count"], 2)
            package = save_intake_package(report, output_root=root / "outputs")
            result = commit_intake(report, project_root=root)
            self.assertEqual(result["rows_added"], 2)
            self.assertTrue(package["manifest"].exists())
            self.assertTrue(package["normalized_staging"].exists())
            destination = root / "data" / "processed" / "process_steps.csv"
            with destination.open("r", encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)

    def test_duplicate_existing_key_is_blocked_without_overwrite(self):
        content = (
            "sample_id,step_id,step_type,sequence,source_status\n"
            "B-DQ,B-DQ-P01,rolling,1,verified_from_source\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path, policy_path = self._fixture(root)
            first = validate_intake_csv(
                "process_steps", content, contract_path=contract_path,
                project_root=root, id_policy_path=policy_path,
            )
            commit_intake(first, project_root=root)
            second = validate_intake_csv(
                "process_steps", content, contract_path=contract_path,
                project_root=root, id_policy_path=policy_path,
            )
            self.assertEqual(second["status"], "blocked")
            self.assertIn("不会覆盖", " ".join(second["errors"]))

    def test_out_of_scope_missing_value_and_unknown_column_are_blocked(self):
        content = (
            "sample_id,observation_id,element,value,unit,source_status,unexpected\n"
            "EXP-01,OBS-01,C,,wt.%,verified_from_source,x\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path, policy_path = self._fixture(root)
            report = validate_intake_csv(
                "composition_observations", content, contract_path=contract_path,
                project_root=root, id_policy_path=policy_path,
            )
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertEqual(report["status"], "blocked")
            self.assertIn("超出当前B/R契约范围", serialized)
            self.assertIn("必要值为空", serialized)
            self.assertIn("未登记列", serialized)

    def test_explicit_chinese_aliases_are_normalized(self):
        content = (
            "样品编号,观察编号,元素,数值,单位,来源状态\n"
            "B-DQ,OBS-BDQ-0001,C,0.19,wt.%,verified_from_source\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path, policy_path = self._fixture(root)
            report = validate_intake_csv(
                "composition_observations", content, contract_path=contract_path,
                project_root=root, id_policy_path=policy_path,
            )
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["rows"][0]["sample_id"], "B-DQ")


if __name__ == "__main__":
    unittest.main()
