from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steelai.governance import verify_package
from steelai.portfolio_release import prepare_release_package, validate_release_config


class T64PortfolioReleaseTests(unittest.TestCase):
    def test_release_contract_has_assets_claims_and_passes(self) -> None:
        result = validate_release_config()
        self.assertEqual(result["status"], "passed")
        self.assertGreaterEqual(result["required_asset_count"], 15)
        self.assertGreaterEqual(result["claim_count"], 4)

    def test_release_package_is_governed_and_requires_human_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = prepare_release_package(output_root=Path(temporary))
            self.assertEqual(result["status"], "needs_human")
            package = Path(result["package"])
            self.assertEqual(verify_package(package).status, "passed")
            self.assertIn("needs_human", (package / "release_checklist.md").read_text(encoding="utf-8"))

    def test_missing_required_asset_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "portfolio.json"
            source = Path("config/portfolio_release_v1.0.json").read_text(encoding="utf-8")
            path.write_text(source.replace('"README.en.md"', '"missing/README.en.md"'), encoding="utf-8")
            result = validate_release_config(path)
            self.assertEqual(result["status"], "failed")
            self.assertIn("missing/README.en.md", result["missing_assets"])


if __name__ == "__main__":
    unittest.main()
