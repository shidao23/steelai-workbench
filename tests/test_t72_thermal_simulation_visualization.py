import math
import unittest

from steelai.thermal_simulation_analysis import (
    derive_compression_curve,
    paired_runs,
    process_double_hit_curve,
)


def run_row(sample: str = "B-DQ", acquisition: str = "75", *, test_type: str = "DH") -> dict[str, str]:
    return {
        "sample_id": sample,
        "specimen_id": f"{sample}-HT-A{acquisition}",
        "experiment_run_id": f"EXP-ZHT-A{acquisition}",
        "acquisition_id": acquisition,
        "test_type": test_type,
        "planned_temperature_c": "1100",
        "planned_interpass_time_s": "1",
        "specimen_diameter_mm": "10",
        "specimen_height_mm": "15",
    }


def point(run: dict[str, str], force: str = "1000", stroke: str = "0.5") -> dict[str, str]:
    return {
        "sample_id": run["sample_id"],
        "specimen_id": run["specimen_id"],
        "experiment_run_id": run["experiment_run_id"],
        "interval_index": "1",
        "point_index": "0",
        "time_s": "0.1",
        "force_value_raw": force,
        "force_unit_raw": "Kg",
        "stroke_value_raw": stroke,
        "stroke_unit_raw": "cm",
        "stroke_mm": str(float(stroke) * 10),
        "control_temperature_c": "1100",
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
                force = 30.0 + (index - 20) * 20.0
                stroke = starting_stroke + (index - 19) * 0.01
            else:
                force = 400.0 - (index - 50) * 30.0
                stroke = starting_stroke + 0.3 - (index - 49) * 0.005
            row = point(run, force=str(force), stroke=str(stroke))
            row["interval_index"] = str(interval)
            row["point_index"] = str(index)
            row["time_s"] = str((interval - 1) * 2 + index * 0.001)
            rows.append(row)
    return rows


class ThermalSimulationVisualizationTests(unittest.TestCase):
    def test_phi10x15_formula_matches_project_owner_equations(self):
        run = run_row()
        source = point(run)
        result = derive_compression_curve(run, [source])
        derived = result["rows"][0]
        self.assertAlmostEqual(derived["stress_mpa"], 83.0)
        self.assertAlmostEqual(derived["true_strain"], math.log(1.5))
        self.assertEqual(derived["force_value_raw"], 1000.0)
        self.assertEqual(derived["stroke_cm"], 0.5)
        self.assertEqual(derived["formula_id"], "SteelAI-Thermal-Compression-Phi10x15-v1.0")

    def test_formula_fails_closed_for_wrong_geometry_or_test_type(self):
        wrong_geometry = run_row()
        wrong_geometry["specimen_height_mm"] = "12"
        with self.assertRaisesRegex(ValueError, "15 mm"):
            derive_compression_curve(wrong_geometry, [point(wrong_geometry)])
        pag = run_row(test_type="PAG")
        with self.assertRaisesRegex(ValueError, "DH"):
            derive_compression_curve(pag, [point(pag)])

    def test_formula_rejects_nonpositive_current_height(self):
        run = run_row()
        with self.assertRaisesRegex(ValueError, "不大于 0"):
            derive_compression_curve(run, [point(run, stroke="1.5")])

    def test_br_pairing_uses_reviewed_condition_fields(self):
        b = run_row("B-DQ", "75")
        r = run_row("R-DQ", "76")
        pairs = paired_runs([b, r])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["B-DQ"]["acquisition_id"], "75")
        self.assertEqual(pairs[0]["R-DQ"]["acquisition_id"], "76")

    def test_double_hit_processing_keeps_raw_and_builds_two_local_segments(self):
        run = run_row()
        result = process_double_hit_curve(run, double_hit_points(run))
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["review_status"], "suggested_needs_human")
        for segment in result["segments"]:
            self.assertLess(segment["contact_point_index"], segment["end_point_index"])
            self.assertGreater(segment["max_local_true_strain"], 0.1)
        effective = result["effective_rows"]
        for interval in (1, 2):
            first = next(row for row in effective if row["interval_index"] == interval)
            self.assertAlmostEqual(first["true_strain_local"], 0.0)
            self.assertEqual(first["force_value_raw"], 30.0)
            self.assertEqual(first["force_baseline_corrected"], 40.0)
            self.assertIn("stress_mpa_formula_raw", first)

    def test_double_hit_processing_fails_closed_without_two_intervals(self):
        run = run_row()
        one_interval = [row for row in double_hit_points(run) if row["interval_index"] == "1"]
        with self.assertRaisesRegex(ValueError, "2 个 interval"):
            process_double_hit_curve(run, one_interval)


if __name__ == "__main__":
    unittest.main()
