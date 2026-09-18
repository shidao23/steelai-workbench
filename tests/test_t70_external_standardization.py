import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from steelai.data_intake import validate_intake_csv
from steelai.data_intake_governance import prepare_intake_governance
from steelai.external_data_standardizer import (
    build_standardization_preview,
    inspect_external_file,
    suggest_mapping,
    xlsx_sheet_names,
)


ROOT = Path(__file__).resolve().parents[1]


class ExternalStandardizationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        contract = json.loads((ROOT / "config/research_data_contract_v1.0.json").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "config/research_id_policy_v1.0.json").read_text(encoding="utf-8"))
        contract_path = root / "contract.json"
        policy_path = root / "policy.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        processed = root / "data/processed"
        processed.mkdir(parents=True)
        (processed / "samples.csv").write_text(
            "sample_id,steel,condition,batch,data_status\nB-DQ,B,DQ,DQ-6PASS-B,verified_from_source\n",
            encoding="utf-8",
        )
        return contract_path, policy_path

    def test_csv_is_inspected_and_common_headers_are_suggested(self):
        info = inspect_external_file(
            "tensile.csv",
            "样品编号,屈服强度,抗拉强度\nB-DQ,1.088,1455\n".encode("utf-8"),
        )
        self.assertEqual(info["row_count"], 1)
        mapping = suggest_mapping(info["headers"], "properties")
        self.assertEqual(mapping["sample_id"], "样品编号")
        self.assertEqual(mapping["ys_mpa"], "屈服强度")
        self.assertEqual(mapping["uts_mpa"], "抗拉强度")

    def test_semicolon_csv_is_detected_without_changing_source_text(self):
        info = inspect_external_file("lab.csv", b"sample_id;value\nB-DQ;1088\n")
        self.assertEqual(info["headers"], ["sample_id", "value"])
        self.assertEqual(info["rows"][0]["value"], "1088")

    def test_explicit_gpa_conversion_builds_ready_standard_rows(self):
        info = inspect_external_file(
            "tensile.csv",
            b"sample,YS (GPa),UTS (MPa),Impact (J),Replicates\nB-DQ,1.088,1455,16.37,3\n",
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract_path, _ = self._fixture(root)
            report = build_standardization_preview(
                info,
                "properties",
                {
                    "sample_id": "sample", "ys_mpa": "YS (GPa)", "uts_mpa": "UTS (MPa)",
                    "impact_minus40_j": "Impact (J)", "replicates": "Replicates",
                },
                constants={"source_status": "instrument_export"},
                source_units={"ys_mpa": "GPa", "uts_mpa": "MPa", "impact_minus40_j": "J"},
                contract_path=contract_path,
                project_root=root,
            )
        self.assertEqual(report["status"], "ready", report["errors"])
        self.assertEqual(report["rows"][0]["ys_mpa"], "1088")
        self.assertEqual(report["standardization"]["unit_transformations"][0]["target_unit"], "MPa")

    def test_unknown_source_unit_blocks_instead_of_guessing(self):
        info = inspect_external_file("test.csv", b"sample,YS\nB-DQ,1088\n")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract_path, _ = self._fixture(root)
            report = build_standardization_preview(
                info, "properties", {"sample_id": "sample", "ys_mpa": "YS"},
                constants={"uts_mpa": "1455", "impact_minus40_j": "16", "replicates": "3",
                           "source_status": "instrument_export"},
                contract_path=contract_path, project_root=root,
            )
        self.assertEqual(report["status"], "blocked")
        self.assertIn("来源单位未确认", " ".join(report["errors"]))

    def test_new_sample_must_be_registered_through_samples_table_first(self):
        content = (
            "sample_id,steel,condition,batch,data_status\n"
            "B-T200,B,T200,T200-B,manual_extraction_verified\n"
        ).encode()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract_path, policy_path = self._fixture(root)
            registration = validate_intake_csv(
                "samples", content, contract_path=contract_path, project_root=root, id_policy_path=policy_path,
            )
            self.assertEqual(registration["status"], "ready", registration["errors"])
            unregistered = validate_intake_csv(
                "property_observations",
                b"sample_id,specimen_id,property,value,unit,source_status\n"
                b"R-T200,R-T200-T01,YS,1000,MPa,instrument_export\n",
                contract_path=contract_path, project_root=root, id_policy_path=policy_path,
            )
            self.assertEqual(unregistered["status"], "blocked")
            self.assertIn("尚未登记", " ".join(unregistered["errors"]))

    def test_minimal_xlsx_is_read_without_a_new_runtime_dependency(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/workbook.xml", """<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Data\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>""")
            archive.writestr("xl/_rels/workbook.xml.rels", """<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Target=\"worksheets/sheet1.xml\"/></Relationships>""")
            archive.writestr("xl/worksheets/sheet1.xml", """<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData><row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>sample_id</t></is></c><c r=\"B1\" t=\"inlineStr\"><is><t>value</t></is></c></row><row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>B-DQ</t></is></c><c r=\"B2\"><v>1088</v></c></row></sheetData></worksheet>""")
        payload = buffer.getvalue()
        self.assertEqual(xlsx_sheet_names(payload), ["Data"])
        info = inspect_external_file("lab.xlsx", payload, sheet_name="Data")
        self.assertEqual(info["rows"], [{"sample_id": "B-DQ", "value": "1088"}])

    def test_external_file_route_uses_the_existing_governance_state_machine(self):
        report = {
            "table_name": "samples", "destination": "data/processed/samples.csv",
            "content_sha256": "a" * 64, "columns": ["sample_id"], "row_count": 1,
            "rows": [{"sample_id": "B-T200", "data_status": "instrument_export"}],
            "status": "ready", "errors": [], "warnings": [],
        }
        record = prepare_intake_governance(
            report, route="external_file", reviewer_id="reviewer", rationale="checked", confirmed=True,
        )
        self.assertEqual(record.state, "approved")
        self.assertEqual(record.route, "external_file")

    def test_uploaded_flat_file_renders_mapping_and_keeps_commit_disabled(self):
        from streamlit.testing.v1 import AppTest

        class Upload:
            name = "tensile.csv"
            size = 79

            @staticmethod
            def getvalue():
                return (b"sample_id,specimen_id,property,value,unit\n"
                        b"B-DQ,B-DQ-T01,YS,1088,MPa\n")

        path = ROOT / "steelai/views/data_quality_panel.py"
        def uploader(label, **kwargs):
            return Upload() if label.startswith("1. ") else None
        with patch("streamlit.file_uploader", side_effect=uploader), patch(
            "steelai.intake_request.record_event"
        ) as intake_event:
            app = AppTest.from_file(str(path), default_timeout=20).run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any(
            call.args and call.args[0] == "intake_request"
            for call in intake_event.call_args_list
        ))
        buttons = [(item.key, item.label, item.disabled) for item in app.button]
        self.assertTrue(any(item.key == "external_commit_property_observations" and item.disabled
                            for item in app.button), buttons)


if __name__ == "__main__":
    unittest.main()
