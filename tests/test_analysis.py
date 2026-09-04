import unittest

from steelai.analysis import build_rule_report
from steelai.data import sample_bundle


class AnalysisTests(unittest.TestCase):
    def test_verified_report_keeps_evidence_boundaries(self):
        report = build_rule_report(sample_bundle("B-DQ"), sample_bundle("R-DQ"))
        self.assertTrue(report.confirmed_facts)
        self.assertTrue(report.hypotheses)
        self.assertTrue(any("经验公式" in item for item in report.limitations))
        self.assertFalse(any("DEMO" in item for item in report.limitations))
        self.assertEqual(report.provider, "offline_rules")


if __name__ == "__main__":
    unittest.main()
