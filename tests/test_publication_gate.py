from __future__ import annotations

import unittest

from steelai.publication_gate import run_publication_gate


class PublicationGateTests(unittest.TestCase):
    def test_public_release_is_sanitized_and_synthetic(self) -> None:
        report = run_publication_gate()
        self.assertEqual(report["status"], "passed", report["failures"])
        self.assertTrue(report["public_demo"])
        self.assertTrue(report["synthetic_data_only"])


if __name__ == "__main__":
    unittest.main()
