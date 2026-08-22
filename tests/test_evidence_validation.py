import unittest

from steelai.evidence_validation import (
    build_claim_register,
    validation_report_markdown,
    validation_summary,
)


def ebsd_fixture(grain_delta, kam_delta, hagb_delta):
    return {
        "status": "completed",
        "metrics": [
            {"metric": "median_equivalent_diameter_um_interior", "R_minus_B": grain_delta},
            {"metric": "median_kam_deg", "R_minus_B": kam_delta},
            {"metric": "hagb_length_fraction_percent", "R_minus_B": hagb_delta},
        ],
    }


def autodimple_fixture():
    interval = {"r_minus_b": 1.0, "ci95_low": -1.0, "ci95_high": 2.0}
    return {
        "n_images": {"B": 5, "R": 5},
        "metrics": {
            "estimated_true_candidates": {"bootstrap_mean_difference": interval},
            "candidate_coverage_percent": {"bootstrap_mean_difference": interval},
            "median_equivalent_diameter_um": {"bootstrap_mean_difference": interval},
        },
    }


class EvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.low = ebsd_fixture(0.1, -0.08, 1.8)
        self.high = ebsd_fixture(0.12, 0.02, 0.5)
        self.auto = autodimple_fixture()

    def test_summary_has_explicit_scientific_readiness(self):
        summary = validation_summary(self.low, self.high, self.auto)
        self.assertEqual(summary["evidence_count"], 7)
        self.assertEqual(summary["claim_count"], 9)
        self.assertEqual(summary["overall_readiness"], "directional_evidence_only")
        self.assertFalse(summary["causal_inference_ready"])
        self.assertFalse(summary["machine_learning_ready"])
        self.assertTrue(summary["portfolio_case_ready"])

    def test_claim_matrix_preserves_consistency_and_conflict(self):
        claims = {item.claim_id: item for item in build_claim_register(self.low, self.high, self.auto)}
        self.assertEqual(claims["C-EBSD-001"].status, "directionally_consistent")
        self.assertEqual(claims["C-EBSD-001"].evidence_level, "L2")
        self.assertEqual(claims["C-EBSD-002"].status, "conflicting_evidence")
        self.assertEqual(claims["C-SEM-001"].status, "not_confirmed")

    def test_mechanical_claim_does_not_overstate_significance(self):
        claims = {item.claim_id: item for item in build_claim_register(self.low, self.high, self.auto)}
        impact = claims["C-MECH-002"]
        self.assertIn("-20.0%", impact.allowed_wording)
        self.assertIn("统计显著", impact.prohibited_wording)
        self.assertEqual(impact.status, "supported_with_caveat")

    def test_report_contains_gates_and_exclusion_decision(self):
        summary = validation_summary(self.low, self.high, self.auto)
        report = validation_report_markdown(summary)
        self.assertIn("Validation Gates", report)
        self.assertIn("Experiments 1-14: excluded", report)
        self.assertIn("C-EBSD-002", report)


if __name__ == "__main__":
    unittest.main()
