import csv
import tempfile
import unittest
from pathlib import Path

from steelai.thermal_simulation_features import (
    approve_and_commit_thermal_features,
    build_thermal_feature_batch_preview,
    build_thermal_feature_preview,
)


def run_row(acquisition: str = "75") -> dict[str, str]:
    return {
        "sample_id": "B-DQ",
        "specimen_id": f"B-DQ-HT-A{acquisition}",
        "experiment_run_id": f"EXP-ZHT-A{acquisition}",
        "acquisition_id": acquisition,
        "test_type": "DH",
        "specimen_diameter_mm": "10",
        "specimen_height_mm": "15",
        "effective_temperature_c": "1100.5",
        "effective_interpass_time_s": "1.01",
        "review_status": "matched",
        "source_file_sha256": "a" * 64,
    }


def double_hit_points(run: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for interval in (1, 2):
        starting_stroke = 0.0 if interval == 1 else 0.3
        for index in range(60):
            if index < 20:
                force = -10.0
                stroke = starting_stroke
            elif index < 50:
                force = 30.0 + (index - 20) * (20.0 if interval == 1 else 18.0)
                stroke = starting_stroke + (index - 19) * 0.01
            else:
                force = 400.0 - (index - 50) * 30.0
                stroke = starting_stroke + 0.3 - (index - 49) * 0.005
            rows.append({
                "sample_id": run["sample_id"],
                "specimen_id": run["specimen_id"],
                "experiment_run_id": run["experiment_run_id"],
                "interval_index": str(interval),
                "point_index": str(index),
                "time_s": str((interval - 1) * 2 + index * 0.001),
                "force_value_raw": str(force),
                "force_unit_raw": "Kg",
                "stroke_value_raw": str(stroke),
                "stroke_unit_raw": "cm",
                "stroke_mm": str(stroke * 10),
                "control_temperature_c": str(1100 + interval + index * 0.01),
            })
    return rows


class ThermalSimulationFeatureTests(unittest.TestCase):
    def test_feature_preview_contains_two_hit_features_and_provenance(self):
        run = run_row()
        preview = build_thermal_feature_preview(run, double_hit_points(run))
        row = preview["rows"][0]
        self.assertEqual(preview["status"], "needs_human")
        self.assertEqual(row["segment_review_status"], "suggested_needs_human")
        self.assertGreater(row["hit1_peak_stress_mpa"], 0)
        self.assertGreater(row["hit2_peak_stress_mpa"], 0)
        self.assertIn("hit1_flow_stress_at_strain_0p1_mpa", row)
        self.assertIn("hit2_flow_stress_at_strain_0p2_mpa", row)
        self.assertAlmostEqual(
            row["effective_deformation_gap_s"],
            row["hit2_start_time_s"] - row["hit1_end_time_s"],
        )
        for field in (
            "source_file_sha256", "source_points_sha256", "formula_config_sha256",
            "segment_policy_sha256", "feature_policy_sha256", "segment_candidate_sha256",
            "feature_row_sha256",
        ):
            self.assertEqual(len(row[field]), 64)

    def test_batch_preview_is_one_row_per_run(self):
        first = run_row("75")
        second = run_row("76")
        batch = build_thermal_feature_batch_preview(
            [first, second], [*double_hit_points(first), *double_hit_points(second)],
        )
        self.assertEqual(batch["run_count"], 2)
        self.assertEqual(batch["segment_count"], 4)

    def test_formal_write_requires_explicit_named_review(self):
        run = run_row()
        preview = build_thermal_feature_preview(run, double_hit_points(run))
        with self.assertRaisesRegex(ValueError, "具名复核人"):
            approve_and_commit_thermal_features(
                preview, reviewer_id="", rationale="", confirmed=False,
            )

    def test_approved_features_use_shared_append_only_gate(self):
        run = run_row()
        preview = build_thermal_feature_preview(run, double_hit_points(run))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            (processed / "samples.csv").write_text(
                "sample_id,steel,condition,batch,data_status,is_demo,notes\n"
                "B-DQ,B,DQ,DQ_6PASS_B,verified_from_source_note,false,test\n",
                encoding="utf-8",
            )
            result = approve_and_commit_thermal_features(
                preview,
                reviewer_id="project_owner",
                rationale="目视核对两道次接触点与卸载前终点。",
                confirmed=True,
                project_root=root,
                decided_at="2026-09-11T20:00:00+08:00",
            )
            self.assertEqual(result["status"], "committed")
            destination = processed / "thermal_simulation_features.csv"
            with destination.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["segment_review_status"], "approved")
            self.assertEqual(rows[0]["segment_reviewer_id"], "project_owner")
            self.assertTrue(Path(result["governance_package"]).exists())


if __name__ == "__main__":
    unittest.main()
