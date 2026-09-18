from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from steelai.governance import GovernanceError, verify_package
from steelai.real_data_case import (
    CASE_CONTRACT_PATH,
    LABEL_COLUMNS,
    frozen_split,
    load_verified_dataset,
    run_real_data_case,
    validate_real_data_case_contract,
)


OFFICIAL_ZIP = Path(os.environ.get("STEELAI_T62_TEST_ZIP", ".not-configured/t62/steel_plates_faults.zip"))


class T62ContractTests(unittest.TestCase):
    def test_contract_freezes_license_split_models_and_no_local_ai(self) -> None:
        result = validate_real_data_case_contract()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["license_id"], "CC-BY-4.0")


class T62RealDataCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not OFFICIAL_ZIP.is_file():
            raise unittest.SkipTest("official UCI ZIP is not present in the local test cache")

    def test_official_archive_schema_and_hashes_are_verified(self) -> None:
        frame, receipt = load_verified_dataset(OFFICIAL_ZIP)
        self.assertEqual(frame.shape[0], 1941)
        self.assertEqual(receipt["feature_count"], 27)
        self.assertEqual(receipt["class_count"], 7)
        self.assertEqual(receipt["missing_value_count"], 0)
        self.assertFalse(receipt["raw_data_copied_to_result"])
        self.assertEqual(set(frame["target_label"]), set(LABEL_COLUMNS))

    def test_frozen_split_is_disjoint_complete_and_reproducible(self) -> None:
        frame, _ = load_verified_dataset(OFFICIAL_ZIP)
        contract = json.loads(CASE_CONTRACT_PATH.read_text(encoding="utf-8"))
        first, first_manifest = frozen_split(frame, contract)
        second, second_manifest = frozen_split(frame, contract)
        self.assertEqual(first, second)
        self.assertEqual(first_manifest, second_manifest)
        self.assertFalse(set(first["train"]) & set(first["validation"]))
        self.assertFalse(set(first["train"]) & set(first["test"]))
        self.assertFalse(set(first["validation"]) & set(first["test"]))
        self.assertEqual(sum(map(len, first.values())), len(frame))
        self.assertFalse(first_manifest["test_used_for_tuning"])

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            damaged = Path(temporary) / "damaged.zip"
            damaged.write_bytes(OFFICIAL_ZIP.read_bytes() + b"tamper")
            with self.assertRaises(GovernanceError) as context:
                load_verified_dataset(damaged)
            self.assertEqual(context.exception.code, "GOV-INTEGRITY-001")

    def test_invalid_one_hot_target_fails_closed_after_frozen_hash_update(self) -> None:
        contract = json.loads(CASE_CONTRACT_PATH.read_text(encoding="utf-8"))
        with zipfile.ZipFile(OFFICIAL_ZIP) as archive:
            data = bytearray(archive.read(contract["dataset"]["data_member"]))
            variables = archive.read(contract["dataset"]["variables_member"])
        first_newline = data.index(ord("\n"))
        first = data[:first_newline].decode("utf-8").split()
        first[-7:] = ["0"] * 7
        modified_data = ("\t".join(first) + "\n").encode("utf-8") + bytes(data[first_newline + 1:])
        import hashlib

        contract["dataset"]["data_sha256"] = hashlib.sha256(modified_data).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            altered_zip = root / "altered.zip"
            with zipfile.ZipFile(altered_zip, "w") as archive:
                archive.writestr(contract["dataset"]["data_member"], modified_data)
                archive.writestr(contract["dataset"]["variables_member"], variables)
            contract["dataset"]["zip_sha256"] = hashlib.sha256(altered_zip.read_bytes()).hexdigest()
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaises(GovernanceError) as context:
                load_verified_dataset(altered_zip, contract_path=contract_path)
            self.assertEqual(context.exception.code, "GOV-SCHEMA-001")

    def test_end_to_end_case_is_reproducible_governed_and_nonformal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "cases"
            first = run_real_data_case(zip_path=OFFICIAL_ZIP, output_root=output)
            second = run_real_data_case(zip_path=OFFICIAL_ZIP, output_root=output)
            self.assertEqual(first["status"], "passed")
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(first["publication_id"], second["publication_id"])
            self.assertTrue(first["human_review_required"])
            self.assertFalse(first["portfolio_eligible"])
            package = output / first["publication_id"]
            self.assertEqual(verify_package(package).status, "passed")
            model_card = json.loads((package / "model_card.json").read_text(encoding="utf-8"))
            self.assertFalse(model_card["metrics"]["selection"]["test_examined_during_selection"])
            self.assertEqual(model_card["result_level"], "working_candidate")
            self.assertFalse(model_card["formal_scientific_conclusion"])
            self.assertFalse(any(path.name == "Faults.NNA" for path in package.rglob("*")))
            improved = first["test_metrics"]["improved"]
            baseline = first["test_metrics"]["baseline"]
            self.assertGreater(improved["macro_f1"], baseline["macro_f1"])


if __name__ == "__main__":
    unittest.main()
