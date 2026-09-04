from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steelai.ebsd_comparison import build_comparison, compare_ctf_headers


def make_ctf(path: Path, coverage: float) -> None:
    path.write_text(
        "\n".join(
            [
                "Channel Text File",
                "XCells\t601",
                "YCells\t360",
                "XStep\t0.5",
                "YStep\t0.5",
                f"Euler angles refer to Sample Coordinate system (CS0)!\tMag\t1000\tCoverage\t{coverage}\tKV\t20\tTiltAngle\t70",
                "Phases\t2",
                "3.6;3.6;3.6\t90;90;90\tIron fcc\t11\t225",
                "2.86;2.86;2.86\t90;90;90\tIron bcc (old)\t11\t229",
                "Phase\tX\tY\tBands\tError\tEuler1\tEuler2\tEuler3\tMAD\tBC\tBS",
            ]
        ),
        encoding="utf-8",
    )


class EbsdComparisonTests(unittest.TestCase):
    def test_near_identical_high_resolution_headers_are_compatible(self) -> None:
        b_header = {
            "x_cells": 800,
            "y_cells": 599,
            "x_step_um": 0.15,
            "y_step_um": 0.15,
            "magnification": 2005.0,
            "voltage_kv": 20.0,
            "tilt_angle_deg": 70.0,
            "phases": ["Iron fcc", "Iron bcc (old)"],
        }
        r_header = {
            "x_cells": 801,
            "y_cells": 601,
            "x_step_um": 0.150225225225225,
            "y_step_um": 0.150225225225225,
            "magnification": 1998.0,
            "voltage_kv": 20.0,
            "tilt_angle_deg": 70.0,
            "phases": ["Iron fcc", "Iron bcc (old)"],
        }
        self.assertTrue(compare_ctf_headers(b_header, r_header)["compatible"])

    def test_matched_pair_and_relative_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            b_path = root / "b.ctf"
            r_path = root / "r.ctf"
            make_ctf(b_path, 80.0)
            make_ctf(r_path, 77.0)
            base = {
                "indexed_fraction_percent": 80.0,
                "retained_phase_fraction_of_indexed_percent": 0.2,
                "median_equivalent_diameter_um_interior": 2.0,
                "median_kam_deg": 0.5,
                "hagb_length_fraction_percent": 80.0,
            }
            b_summary = {**base, "input_file": str(b_path)}
            r_summary = {**base, "input_file": str(r_path), "median_kam_deg": 0.6}
            comparison = build_comparison(b_summary, r_summary)
        self.assertTrue(comparison["acquisition_compatibility"]["compatible"])
        kam = next(row for row in comparison["metrics"] if row["metric"] == "median_kam_deg")
        self.assertAlmostEqual(kam["R_vs_B_percent"], 20.0)


if __name__ == "__main__":
    unittest.main()
