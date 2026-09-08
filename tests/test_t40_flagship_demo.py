"""T40 acceptance tests: public synthetic success and fail-closed unit case."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steelai.flagship_demo import (
    COMPLETE_NAME,
    FIXTURES,
    MANIFEST_NAME,
    run_flagship_demo,
    verify_flagship_demo,
)
from steelai.steeldata_bridge import SteelDataClient
from steelai.steelstats_bridge import SteelStatsClient


class FlagshipDemoTests(unittest.TestCase):
    def test_frozen_fixtures_are_explicitly_synthetic_and_unknown_unit_is_unresolved(self) -> None:
        success = json.loads((FIXTURES / "success_suggestion.json").read_text(encoding="utf-8"))
        blocked = json.loads((FIXTURES / "unknown_unit_suggestion.json").read_text(encoding="utf-8"))
        review = json.loads((FIXTURES / "review_fixture.json").read_text(encoding="utf-8"))
        self.assertTrue(review["synthetic_only"])
        self.assertTrue(all(value.startswith("SYN-") for value in review["sample_bindings"].values()))
        self.assertEqual(success["uncertainties"], [])
        self.assertEqual(blocked["proposed_profile"]["columns"][3]["unit"], None)
        self.assertEqual(blocked["uncertainties"][0]["code"], "unit_uncertain")

    def test_real_three_module_demo_passes_reuses_and_detects_tampering(self) -> None:
        data_client = SteelDataClient()
        stats_client = SteelStatsClient()
        if not data_client.availability()["ready"] or not stats_client.availability()["ready"]:
            self.skipTest("Sibling SteelData/SteelStats independent runtimes are unavailable.")
        with tempfile.TemporaryDirectory() as temp:
            first = run_flagship_demo(temp, steeldata=data_client, steelstats=stats_client)
            package = Path(first["demo_dir"])
            self.assertFalse(first["reused"])
            self.assertEqual(first["verification"]["status"], "passed")
            self.assertTrue((package / COMPLETE_NAME).is_file())
            manifest = json.loads((package / MANIFEST_NAME).read_text(encoding="utf-8"))
            stages = manifest["stages"]
            self.assertTrue(manifest["privacy"]["public_synthetic_only"])
            self.assertEqual(stages["steeldata"]["qc_status"], "passed")
            self.assertEqual(stages["steeldata"]["specimens"], 6)
            self.assertEqual(stages["steelstats"]["group_count"], 6)
            self.assertEqual(stages["unknown_unit_guardrail"]["status"], "needs_human")
            self.assertFalse(stages["unknown_unit_guardrail"]["execution_started"])
            self.assertFalse(stages["unknown_unit_guardrail"]["result_created"])
            self.assertFalse(any(Path(name).is_absolute() for name in manifest["artifacts"]))
            self.assertTrue(any(name.endswith("/COMPLETE") for name in manifest["artifacts"]))

            second = run_flagship_demo(temp, steeldata=data_client, steelstats=stats_client)
            self.assertTrue(second["reused"])
            (package / "summary.md").write_text("tampered", encoding="utf-8")
            self.assertEqual(verify_flagship_demo(package)["status"], "failed")
            with self.assertRaisesRegex(ValueError, "不会覆盖"):
                run_flagship_demo(temp, steeldata=data_client, steelstats=stats_client)


if __name__ == "__main__":
    unittest.main()
