from __future__ import annotations

import unittest

from steelai.dimple_standard import assess_run, build_preliminary_standard, estimate_true_candidates


class DimpleStandardTests(unittest.TestCase):
    def test_builds_reported_ratio_and_estimate(self) -> None:
        standard = build_preliminary_standard()
        self.assertAlmostEqual(standard["calibration"]["candidate_acceptance_rate"], 22 / 30, places=5)
        estimate = estimate_true_candidates(465, standard)
        self.assertEqual(estimate["estimated_true_candidates"], 341)

    def test_marks_mismatched_image_out_of_standard(self) -> None:
        standard = build_preliminary_standard()
        result = assess_run(500, 0.5, 28.01766, 7.586165, standard)
        self.assertEqual(result["status"], "out_of_standard")
        self.assertIn("magnification_mismatch", result["triggered_rules"])


if __name__ == "__main__":
    unittest.main()
