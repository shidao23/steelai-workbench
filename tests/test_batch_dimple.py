from __future__ import annotations

import unittest

from steelai.batch_dimple import summarize_groups


class BatchDimpleTests(unittest.TestCase):
    def test_summarizes_by_image_not_object(self) -> None:
        rows = []
        for steel, values in (("B", [10, 12]), ("R", [8, 9])):
            for value in values:
                rows.append(
                    {
                        "steel": steel,
                        "status": "in_standard",
                        "estimated_true_candidates": value,
                        "candidate_coverage_percent": value,
                        "median_equivalent_diameter_um": value,
                        "adjusted_density_per_1000_um2": value,
                        "D10_um": value,
                        "D90_um": value,
                    }
                )
        result = summarize_groups(rows)
        self.assertEqual(result["n_images"], {"B": 2, "R": 2})
        self.assertEqual(result["metrics"]["estimated_true_candidates"]["B_mean"], 11.0)
        self.assertEqual(result["metrics"]["estimated_true_candidates"]["R_mean"], 8.5)


if __name__ == "__main__":
    unittest.main()
