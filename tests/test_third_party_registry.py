import json
import tempfile
import unittest
from pathlib import Path

from steelai.third_party_registry import (
    load_third_party_registry,
    validate_third_party_registry,
)


class ThirdPartyRegistryTests(unittest.TestCase):
    def _validate_modified(self, change) -> dict:
        registry = load_third_party_registry()
        change(registry)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            return validate_third_party_registry(path)

    def test_registry_passes_with_one_bounded_t14_candidate(self):
        report = validate_third_party_registry()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["candidate_count"], 5)
        self.assertEqual(report["selected_for_t14"], ["frictionless-data-package"])
        self.assertFalse(report["code_imported"])

    def test_unknown_license_and_unpinned_version_fail_closed(self):
        def change(registry):
            candidate = registry["candidates"][0]
            candidate["license_spdx"] = "UNKNOWN"
            candidate["version_ref"] = "latest"

        report = self._validate_modified(change)
        self.assertEqual(report["status"], "failed")
        text = " ".join(report["problems"])
        self.assertIn("exact numeric release", text)
        self.assertIn("license is not verified", text)

    def test_t13_rejects_any_claim_that_code_was_imported(self):
        def change(registry):
            registry["candidates"][0]["code_imported"] = True

        report = self._validate_modified(change)
        self.assertEqual(report["status"], "failed")
        self.assertIn("T13 must not import third-party code", " ".join(report["problems"]))

    def test_rejected_overlap_and_large_system_boundaries_are_recorded(self):
        registry = load_third_party_registry()
        candidates = {item["candidate_id"]: item for item in registry["candidates"]}
        gx = candidates["great-expectations-validation"]
        self.assertEqual(gx["decision"], "rejected_now")
        self.assertIn("CPython 3.12.14", gx["runtime_fit"])
        self.assertIn("overlap", gx["dependency_impact"])
        self.assertEqual(candidates["nomad-schema-eln-reference"]["decision"], "reference_only")
        self.assertEqual(candidates["mlflow-run-tracking"]["decision"], "deferred")
        self.assertTrue(all(item["official_repo"].startswith("https://") for item in candidates.values()))


if __name__ == "__main__":
    unittest.main()
