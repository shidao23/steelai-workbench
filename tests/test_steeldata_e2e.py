"""Opt-in cross-environment tests. ALL data, approvals, and commits are temporary.

Enable with STEELDATA_E2E=1; requires the sibling SteelData .venv. The real-data
CLI route is exercised using explicitly labelled synthetic TEST fixtures; no
test approval or result package is retained in either production project.
"""
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from steelai.steeldata_bridge import SteelDataClient, commit_run, inspect_run, mapping_rows, prepare_intake


@unittest.skipUnless(os.environ.get("STEELDATA_E2E") == "1", "Opt-in: STEELDATA_E2E=1 and sibling SteelData required")
class SteelDataEndToEndTests(unittest.TestCase):
    def test_real_cli_protocol_to_isolated_workbench_intake(self):
        client = SteelDataClient()
        self.assertTrue(client.availability()["ready"])
        with tempfile.TemporaryDirectory(prefix="steelai-synthetic-e2e-") as temp:
            root = Path(temp)
            inbox = root / "inputs"
            inbox.mkdir()
            source = inbox / "SYNTHETIC-NOT-LAB-DATA.csv"
            source.write_text(
                "Specimen,Batch,Process,YS (MPa),UTS (GPa),EL (%)\n"
                "SYN-TEST-T01,SYN-TEST-BATCH,DQ,950,1.25,12\n"
                "SYN-TEST-T02,SYN-TEST-BATCH,DQ,970,1.28,11.5\n"
                "SYN-TEST-T03,SYN-TEST-BATCH,DQ,960,1.26,12.2\n", encoding="utf-8")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            profile = json.loads((client.project / "steeldata/demo_data/profiles/tensile-results-v1.json").read_text(encoding="utf-8"))
            profile["profile_id"] = "synthetic-test-protocol-only"
            profile["description"] = "SYNTHETIC automated fixture, not real laboratory data or real human approval"
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            checked = client._call(["profile", str(profile_path)])
            approved = root / "approval.json"
            client._call(["approve", "--profile", str(profile_path), "--expected-sha256", checked["profile_sha256"],
                          "--reviewer", "automated-test-not-human", "--note", "temporary test of approval protocol only",
                          "--output", str(approved)])
            result = client._call(["run", "--input", str(inbox), "--approval", str(approved),
                                   "--output", str(root / "results")])
            official = client._call(["verify", result["run_dir"]])
            self.assertEqual(official["integrity"], "verified")
            view = inspect_run(result["run_dir"])
            self.assertTrue(view.transferable, view.blockers)
            self.assertEqual(view.manifest["counts"]["records"], 3)
            workbench = root / "workbench"
            (workbench / "data/processed").mkdir(parents=True)
            (workbench / "data/processed/samples.csv").write_text("sample_id\nB-DQ\nR-DQ\n", encoding="utf-8")
            bindings = {r["mapping_key"]: "B-DQ" for r in mapping_rows(view)}
            candidate = prepare_intake(view, bindings, "instrument_export", project_root=workbench)
            self.assertEqual(candidate["report"]["status"], "ready")
            self.assertEqual(candidate["report"]["row_count"], 9)
            self.assertEqual(float(candidate["report"]["rows"][1]["value"]), 1250)
            committed = commit_run(result["run_dir"], bindings, "instrument_export", candidate["preview_sha256"],
                                   reviewer="automated-test", note="synthetic sandbox only", confirmed=True,
                                   project_root=workbench)
            self.assertEqual(committed["rows_added"], 9)
            with self.assertRaises(ValueError):
                commit_run(result["run_dir"], bindings, "instrument_export", candidate["preview_sha256"],
                           reviewer="automated-test", note="duplicate attempt", confirmed=True, project_root=workbench)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            # Actual browser-selection backend: stage uploaded bytes, then invoke
            # the same real CLI. Redirect only the result location to this sandbox.
            real_call = client._call
            def isolated_call(args, **kwargs):
                args = list(args)
                args[args.index("--output") + 1] = str(root / "selected-results")
                return real_call(args, **kwargs)
            with patch.object(client, "_call", side_effect=isolated_call):
                selected = client.run_selected([(source.name, source.read_bytes())],
                                                [(approved.name, approved.read_bytes())])
            selected_view = inspect_run(selected["run_dir"])
            self.assertTrue(selected_view.transferable, selected_view.blockers)
            self.assertEqual(selected_view.manifest["counts"]["records"], 3)
            self.assertEqual(selected_view.datasets[0]["records"], view.datasets[0]["records"])


if __name__ == "__main__":
    unittest.main()
