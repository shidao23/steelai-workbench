"""G08 offline degradation tests; all execution uses temporary synthetic fixtures."""
from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steelai.steeldata_bridge import (
    SteelDataClient, _steeldata_subprocess_env, inspect_run,
    resolve_steeldata_project, resolve_steeldata_python,
)


ROOT = Path(__file__).resolve().parents[1]

# The migrated layout keeps SteelData inside the Engineering container under a
# numbered name, so resolution goes through the same config-first helper the
# production client uses. When nothing is available the path simply does not
# exist and the tests that need a real checkout skip instead of failing.
STEELDATA = resolve_steeldata_project() or (ROOT.parent / "02_SteelData")
STEELDATA_PYTHON = resolve_steeldata_python(STEELDATA)


class OfflineBoundaryTests(unittest.TestCase):
    def test_deterministic_child_drops_agent_runtime_model_and_proxy_context(self) -> None:
        source = {
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "PROJECT_MODE": "local",
            "DSH_HOME": r"Z:\missing-dsh",
            "DSH_PROFILE": "missing-profile",
            "DEEPSEEK_HARNESS_CONFIG": r"Z:\missing-harness.json",
            "HARNESS_WORKSPACE": r"Z:\missing-workspace",
            "OPENCLAW_HOME": r"Z:\missing-openclaw",
            "WORKBUDDY_HOME": r"Z:\missing-workbuddy",
            "DEEPSEEK_API_KEY": "must-not-cross-boundary",
            "OPENAI_API_KEY": "must-not-cross-boundary",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "SERVICE_AUTH_TOKEN": "must-not-cross-boundary",
        }

        env = _steeldata_subprocess_env(source)

        self.assertEqual(env["PROJECT_MODE"], "local")
        self.assertEqual(env["PYTHONUTF8"], "1")
        for key in source:
            upper = key.upper()
            if upper.startswith(("DSH_", "DEEPSEEK_HARNESS_", "HARNESS_", "OPENCLAW_", "WORKBUDDY_")):
                self.assertNotIn(key, env)
            if upper.endswith(("_API_KEY", "_AUTH_TOKEN")) or upper == "HTTPS_PROXY":
                self.assertNotIn(key, env)

    def test_default_import_modules_have_no_agent_or_model_sdk_imports(self) -> None:
        forbidden = {
            "anthropic", "deepseek", "dsh", "openai", "openclaw", "workbuddy",
            "langchain", "crewai", "autogen", "requests", "httpx", "aiohttp",
        }
        paths = [
            ROOT / "steelai/steeldata_bridge.py",
            ROOT / "steelai/views/steeldata_panel.py",
        ]
        # The SteelData-side modules only exist in a checkout that also carries
        # the sibling project; the public CI checkout carries neither.
        if STEELDATA.is_dir():
            paths += [
                STEELDATA / "steeldata/pipeline.py",
                STEELDATA / "steeldata/preview.py",
                STEELDATA / "steeldata/normalize.py",
                STEELDATA / "steeldata/qc.py",
            ]
        imported = set()
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
        self.assertFalse(imported.intersection(forbidden), imported.intersection(forbidden))

    @unittest.skipUnless(STEELDATA_PYTHON.is_file(), "sibling SteelData environment is unavailable")
    def test_real_deterministic_cli_survives_poisoned_offline_agent_environment(self) -> None:
        poison = {
            "DSH_HOME": r"Z:\missing-dsh",
            "DSH_EXECUTABLE": r"Z:\missing-dsh\dsh.exe",
            "DEEPSEEK_HARNESS_CONFIG": r"Z:\missing-harness.json",
            "OPENCLAW_HOME": r"Z:\missing-openclaw",
            "WORKBUDDY_HOME": r"Z:\missing-workbuddy",
            "DEEPSEEK_API_KEY": "offline-test-secret",
            "OPENAI_API_KEY": "offline-test-secret",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
        }
        client = SteelDataClient(project=STEELDATA)
        with tempfile.TemporaryDirectory(prefix="g08-offline-") as temp, patch.dict(
            os.environ, poison, clear=False
        ):
            root = Path(temp)
            inputs = root / "inputs"
            inputs.mkdir()
            source = inputs / "SYNTHETIC-G08.csv"
            source.write_text(
                "Specimen,Batch,Process,YS (MPa),UTS (GPa),EL (%)\n"
                "SYN-G08-T01,SYN-G08-BATCH,DQ,950,1.25,12\n",
                encoding="utf-8",
            )
            profile = json.loads(
                (STEELDATA / "steeldata/demo_data/profiles/tensile-results-v1.json").read_text(encoding="utf-8")
            )
            profile["profile_id"] = "synthetic-g08-offline-only"
            profile["description"] = "SYNTHETIC G08 fixture; not laboratory data or a real approval"
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            self.assertTrue(client.availability()["ready"])
            checked = client._call(["profile", str(profile_path)])
            approval = root / "approval.json"
            client._call([
                "approve", "--profile", str(profile_path),
                "--expected-sha256", checked["profile_sha256"],
                "--reviewer", "automated-g08-test-not-human",
                "--note", "temporary offline boundary test only",
                "--output", str(approval),
            ])
            result = client._call([
                "run", "--input", str(inputs), "--approval", str(approval),
                "--output", str(root / "results"),
            ])
            verified = client._call(["verify", result["run_dir"]])
            inspection = inspect_run(result["run_dir"])

        self.assertEqual(result["processing_status"], "complete")
        self.assertEqual(verified["integrity"], "verified")
        self.assertTrue(inspection.transferable, inspection.blockers)
        self.assertEqual(inspection.manifest["counts"]["records"], 1)


if __name__ == "__main__":
    unittest.main()
