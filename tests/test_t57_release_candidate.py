from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from steelai.release_candidate import (
    EXPECTED_SCENARIOS,
    EXPECTED_WORKSPACES,
    RELEASE_CONTRACT,
    validate_release_candidate,
)


class ReleaseCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.contract = json.loads(RELEASE_CONTRACT.read_text(encoding="utf-8"))

    def validate_modified(self, payload: dict) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return validate_release_candidate(path, repository_root=self.root)

    def test_frozen_candidate_covers_nine_workspaces_and_eight_scenarios(self) -> None:
        result = validate_release_candidate()
        self.assertEqual(result["status"], "passed", result["problems"])
        self.assertEqual(result["workspace_count"], 9)
        self.assertEqual(result["scenario_count"], 8)
        self.assertEqual(result["deferred_workspaces"], ["automation_tasks"])
        self.assertEqual(
            tuple(item["workspace_id"] for item in self.contract["workspaces"]),
            EXPECTED_WORKSPACES,
        )
        self.assertEqual(
            tuple(item["scenario_id"] for item in self.contract["regression_scenarios"]),
            EXPECTED_SCENARIOS,
        )

    def test_workspace_target_chain_cannot_drift_from_global_governance(self) -> None:
        modified = copy.deepcopy(self.contract)
        modified["workspaces"][0]["target_chain"] = ["shortcut"]
        result = self.validate_modified(modified)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("target chain" in item for item in result["problems"]))

    def test_deferred_workspace_requires_named_reason_and_future_task(self) -> None:
        modified = copy.deepcopy(self.contract)
        automation = next(item for item in modified["workspaces"] if item["workspace_id"] == "automation_tasks")
        automation.pop("defer_reason")
        result = self.validate_modified(modified)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("deferred status" in item for item in result["problems"]))

    def test_absolute_or_missing_evidence_reference_fails_closed(self) -> None:
        modified = copy.deepcopy(self.contract)
        modified["workspaces"][0]["implementation_evidence"] = ["C:/private/raw.csv"]
        result = self.validate_modified(modified)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("evidence reference" in item for item in result["problems"]))

    def test_candidate_requires_offline_public_boundary_and_zero_failures(self) -> None:
        modified = copy.deepcopy(self.contract)
        modified["evidence_boundary"]["real_research_data_included"] = True
        modified["acceptance_thresholds"]["maximum_test_failures"] = 1
        result = self.validate_modified(modified)
        self.assertEqual(result["status"], "failed")
        self.assertIn("release candidate must not include real research data", result["problems"])
        self.assertTrue(any("zero test failures" in item for item in result["problems"]))


if __name__ == "__main__":
    unittest.main()
