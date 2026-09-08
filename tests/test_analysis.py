import unittest

from steelai.analysis import build_rule_report
class AnalysisTests(unittest.TestCase):
    def test_verified_report_keeps_evidence_boundaries(self):
        def fixture(sample_id, is_demo, ys, uts, elongation, impact):
            return {
                "samples": {"sample_id": sample_id, "is_demo": is_demo},
                "properties": {
                    "ys_mpa": ys,
                    "uts_mpa": uts,
                    "elongation_pct": elongation,
                    "impact_minus40_j": impact,
                },
                "microstructure": {},
            }

        report = build_rule_report(
            fixture("B-DQ", "false", 1000, 1300, 10, 20),
            fixture("R-DQ", "false", 980, 1290, 9.5, 16),
        )
        self.assertTrue(report.confirmed_facts)
        self.assertTrue(report.hypotheses)
        self.assertTrue(any("经验公式" in item for item in report.limitations))
        self.assertFalse(any("DEMO" in item for item in report.limitations))
        self.assertEqual(report.provider, "offline_rules")


if __name__ == "__main__":
    unittest.main()
