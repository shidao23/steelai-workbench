import csv
import tempfile
import unittest
from pathlib import Path

from steelai.thermal_simulation_intake import (
    build_thermal_standardization_preview,
    commit_thermal_preview_governed,
    inspect_thermal_simulation_batch,
    parse_thermal_simulation_file,
    read_thermal_simulation_folder,
    save_thermal_preview_package,
)
from steelai.research_data_contract import validate_research_data_contract


def thermal_file(acquisition: int = 75, *, second_start: float = 1.0010) -> bytes:
    return f"""-1  Program: ZHT       Acquisition: {acquisition}
0                                Channel Information
0   Channel  Name                     Units                    Time Offset
-2     1    Force                    Kg                       0.0000
-2     2    Stroke                   cm                       0.0002
-2     3    Control Temperature      Celsius                  0.0003
0
0   Period
-3     0.0005
0
0   Intervals         Points Per Channel
-4     2                4
0
0   Interval #1
0
0            Time  Channel 1  Channel 2  Channel 3
0          0.0000    -4.0000     0.1000  1100.0000
1          0.0010   100.0000     0.2000  1101.0000
0
0   Interval #2
0
0            Time  Channel 1  Channel 2  Channel 3
0          {second_start:.4f}   200.0000     0.3000  1099.0000
1          {second_start + 0.001:.4f}   300.0000     0.4000  1098.0000
""".encode("ascii")


class ThermalSimulationIntakeTests(unittest.TestCase):
    def test_parser_preserves_raw_force_and_interval_boundaries(self):
        item = parse_thermal_simulation_file("ZHT.A75", thermal_file())
        self.assertEqual(item["status"], "parsed", item["errors"])
        self.assertEqual(item["point_count"], 4)
        self.assertEqual([value["point_count"] for value in item["intervals"]], [2, 2])
        self.assertAlmostEqual(item["measured_interval_gap_raw"], 1.0)
        self.assertEqual(item["points"][0]["force_value_raw"], -4.0)

    def test_header_filename_mismatch_is_blocked(self):
        item = parse_thermal_simulation_file("ZHT.A76", thermal_file(75))
        self.assertEqual(item["status"], "blocked")
        self.assertIn("文件名 acquisition", " ".join(item["errors"]))

    def test_preview_stops_on_unknown_units_and_identity(self):
        batch = inspect_thermal_simulation_batch({"ZHT.A75": thermal_file()})
        preview = build_thermal_standardization_preview(batch)
        self.assertEqual(preview["status"], "needs_human")
        self.assertEqual(preview["point_rows"][0]["time_value_raw"], "0")
        self.assertEqual(preview["point_rows"][0]["time_s"], "")
        self.assertEqual(preview["point_rows"][0]["force_n"], "")
        self.assertTrue(any("sample_id/specimen_id" in value for value in preview["decisions_needed"]))

    def test_confirmed_units_convert_stroke_and_kgf_deterministically(self):
        batch = inspect_thermal_simulation_batch({"ZHT.A75": thermal_file()})
        plan = [{
            "acquisition_id": "75", "sample_id": "B-DQ", "specimen_id": "B-DQ-HT-A75",
            "test_type": "DH", "planned_temperature_c": "1100",
            "planned_interpass_time_s": "1", "strain_1": "0.25", "strain_2": "0.25",
            "strain_rate_s": "2", "specimen_diameter_mm": "10", "specimen_height_mm": "15",
            "plan_source_status": "manual_extraction_verified",
        }]
        preview = build_thermal_standardization_preview(
            batch, plan, time_unit_confirmed=True, force_unit_interpretation="kgf",
            specimen_mapping_confirmed=True,
        )
        self.assertEqual(preview["status"], "ready", preview["decisions_needed"])
        point = preview["point_rows"][1]
        self.assertEqual(point["stroke_mm"], "2")
        self.assertEqual(point["force_n"], "980.665")

    def test_plan_curve_disagreement_requires_human_review(self):
        batch = inspect_thermal_simulation_batch({"ZHT.A75": thermal_file(second_start=10.001)})
        plan = [{
            "acquisition_id": "75", "sample_id": "B-DQ", "specimen_id": "B-DQ-HT-A75",
            "test_type": "DH", "planned_temperature_c": "1050",
            "planned_interpass_time_s": "30", "strain_1": "0.25", "strain_2": "0.25",
            "strain_rate_s": "2", "plan_source_status": "manual_extraction_verified",
        }]
        preview = build_thermal_standardization_preview(
            batch, plan, time_unit_confirmed=True, force_unit_interpretation="kgf",
            specimen_mapping_confirmed=True,
        )
        self.assertEqual(preview["status"], "needs_human")
        self.assertEqual(preview["comparisons"][0]["status"], "needs_human")

    def test_reviewed_instrument_values_can_override_wrong_plan_without_kg_to_n_guess(self):
        batch = inspect_thermal_simulation_batch({"ZHT.A75": thermal_file(second_start=10.001)})
        plan = [{
            "acquisition_id": "75", "sample_id": "B-DQ", "specimen_id": "B-DQ-HT-A75",
            "test_type": "DH", "planned_temperature_c": "1050",
            "planned_interpass_time_s": "30", "strain_1": "0.25", "strain_2": "0.25",
            "strain_rate_s": "2", "plan_source_status": "manual_extraction_verified",
        }]
        preview = build_thermal_standardization_preview(
            batch, plan, time_unit_confirmed=True, force_unit_interpretation="instrument_kg_force",
            specimen_mapping_confirmed=True, accept_instrument_over_plan=True,
        )
        self.assertEqual(preview["status"], "ready", preview["decisions_needed"])
        run = preview["run_rows"][0]
        self.assertEqual(run["review_status"], "deviation_accepted_actual_instrument")
        self.assertEqual(run["planned_interpass_time_s"], "30")
        self.assertEqual(run["effective_interpass_time_s"], "10")
        self.assertEqual(preview["point_rows"][1]["force_n"], "")

    def test_folder_scan_is_non_recursive_and_preview_package_has_no_raw_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ZHT.A75").write_bytes(thermal_file())
            (root / "photo.jpg").write_bytes(b"not included")
            (root / "nested").mkdir()
            (root / "nested" / "ZHT.A76").write_bytes(thermal_file(76))
            files = read_thermal_simulation_folder(root)
            self.assertEqual(list(files), ["ZHT.A75"])
            preview = build_thermal_standardization_preview(inspect_thermal_simulation_batch(files))
            paths = save_thermal_preview_package(preview, root / "output")
            self.assertTrue(paths["manifest"].exists())
            self.assertFalse(any(path.name == "ZHT.A75" for path in paths["package"].iterdir()))

    def test_governed_commit_appends_both_tables_and_replay_is_blocked(self):
        batch = inspect_thermal_simulation_batch({"ZHT.A75": thermal_file(second_start=10.001)})
        plan = [{
            "acquisition_id": "75", "sample_id": "B-DQ", "specimen_id": "B-DQ-HT-A75",
            "test_type": "DH", "planned_temperature_c": "1050",
            "planned_interpass_time_s": "30", "strain_1": "0.25", "strain_2": "0.25",
            "strain_rate_s": "2", "specimen_diameter_mm": "10", "specimen_height_mm": "15",
            "plan_source_status": "manual_extraction_verified",
        }]
        preview = build_thermal_standardization_preview(
            batch, plan, time_unit_confirmed=True,
            force_unit_interpretation="instrument_kg_force",
            specimen_mapping_confirmed=True, accept_instrument_over_plan=True,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            (processed / "samples.csv").write_text(
                "sample_id,steel,condition,batch,data_status,is_demo,notes\n"
                "B-DQ,B,DQ,DQ_6PASS_B,verified_from_source_note,false,test\n",
                encoding="utf-8",
            )
            result = commit_thermal_preview_governed(
                preview, reviewer_id="tester", rationale="verified test fixture",
                confirmed=True, project_root=root,
            )
            self.assertEqual(result["status"], "committed")
            self.assertEqual(result["governance_state"], "complete")
            self.assertEqual([item["rows_added"] for item in result["tables"]], [1, 4])
            with (processed / "thermal_simulation_runs.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                runs = list(csv.DictReader(handle))
            with (processed / "thermal_simulation_points.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                points = list(csv.DictReader(handle))
            self.assertEqual((runs[0]["specimen_diameter_mm"], runs[0]["specimen_height_mm"]), ("10", "15"))
            self.assertEqual(runs[0]["effective_interpass_time_s"], "10")
            self.assertEqual(points[1]["stroke_mm"], "2")
            self.assertEqual(points[1]["force_n"], "")
            contract = validate_research_data_contract(project_root=root)
            thermal_layers = {
                row["layer"]: row for row in contract["tables"]
                if row["layer"].startswith("thermal_simulation")
            }
            self.assertEqual(thermal_layers["thermal_simulation_runs"]["status"], "structured")
            self.assertEqual(thermal_layers["thermal_simulation_points"]["status"], "structured")
            with self.assertRaisesRegex(ValueError, "现有记录冲突"):
                commit_thermal_preview_governed(
                    preview, reviewer_id="tester", rationale="replay must fail",
                    confirmed=True, project_root=root,
                )


if __name__ == "__main__":
    unittest.main()
