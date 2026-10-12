"""T33 tests use only isolated synthetic fixtures and temporary output roots."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steelai.steeldata_bridge import SYNTHETIC_PREVIEW_BLOCKER, inspect_run, mapping_rows
from steelai.steelstats_bridge import (
    INPUT_FILES,
    SteelStatsClient,
    SteelStatsConfigError,
    configured_steelstats_project,
    prepare_statistical_input,
    run_statistics_from_steeldata,
)
from tests.test_steeldata_bridge import result_fixture, seal


ROOT = Path(__file__).resolve().parents[1]
METHOD = "tensile-iso6892-1@1.0.0"
REVIEWED_AT = "2026-09-08T12:00:00+08:00"


def make_fake_steelstats_project(parent: Path) -> Path:
    """Descriptor + runtime layout without depending on any real sibling path."""
    project = parent / "SteelStatsFake"
    (project / "steelstats").mkdir(parents=True)
    (project / ".venv" / "Scripts").mkdir(parents=True)
    (project / "steelstats.module.json").write_text(json.dumps({
        "module_id": "steelstats",
        "contract_version": 1,
        "invocation": {
            "kind": "isolated_cli",
            "report_command": "report",
            "verify_command": "verify-report",
        },
    }), encoding="utf-8")
    (project / "steelstats" / "__main__.py").write_text("", encoding="utf-8")
    (project / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    return project


def write_settings_toml(path: Path, steelstats_project: str | None) -> None:
    lines = ["[project]\n", 'name = "settings-fixture"\n']
    lines.append("[tools]\n")
    if steelstats_project is not None:
        lines.append(f'steelstats_project = "{steelstats_project}"\n')
    path.write_text("".join(lines), encoding="utf-8")


def source_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def bindings_for(run: Path, sample_id: str = "SYN-SAMPLE-A") -> dict[str, str]:
    inspection = inspect_run(run)
    return {item["mapping_key"]: sample_id for item in mapping_rows(inspection)}


class StatisticalInputBridgeTests(unittest.TestCase):
    def make_run(self, parent: Path) -> Path:
        run = parent / "steeldata" / "run-test"
        result_fixture(run)
        return run

    def test_bridge_has_no_steelstats_python_import(self) -> None:
        source = (ROOT / "steelai" / "steelstats_bridge.py").read_text(encoding="utf-8")
        self.assertNotIn("import steelstats", source)
        self.assertNotIn("from steelstats", source)

    def test_prepared_bundle_has_frozen_contract_and_human_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = self.make_run(parent)
            before = source_snapshot(run)
            result = prepare_statistical_input(
                run,
                bindings_for(run),
                METHOD,
                "Researcher A",
                REVIEWED_AT,
                output_root=parent / "inputs",
            )
            bundle = Path(result["bundle_dir"])
            self.assertEqual({path.name for path in bundle.iterdir()}, set(INPUT_FILES))
            plan = json.loads((bundle / "analysis_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["contract_id"], "SteelStats-Statistical-Input-v1.0")
            self.assertEqual(plan["statistical_unit_type"], "specimen")
            self.assertEqual(set(plan["method_versions"].values()), {METHOD})
            with (bundle / "observations.csv").open(encoding="utf-8", newline="") as handle:
                observations = list(csv.DictReader(handle))
            with (bundle / "decisions.csv").open(encoding="utf-8", newline="") as handle:
                decisions = list(csv.DictReader(handle))
            self.assertEqual(len(observations), 3)
            self.assertEqual({row["quantity"] for row in observations}, {"ys_mpa", "uts_mpa", "elongation_pct"})
            self.assertTrue(all(row["reviewer"] == "Researcher A" for row in decisions))
            self.assertTrue(all(row["evidence_ref"].startswith("steeldata-manifest-sha256:") for row in decisions))
            self.assertEqual(source_snapshot(run), before)

    def test_same_review_reuses_exact_input_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = self.make_run(parent)
            kwargs = {
                "run_dir": run,
                "bindings": bindings_for(run),
                "method_version": METHOD,
                "reviewer": "Researcher A",
                "reviewed_at": REVIEWED_AT,
                "output_root": parent / "inputs",
            }
            first = prepare_statistical_input(**kwargs)
            second = prepare_statistical_input(**kwargs)
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(first["bundle_id"], second["bundle_id"])
            path = Path(first["bundle_dir"]) / "decisions.csv"
            path.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不会覆盖"):
                prepare_statistical_input(**kwargs)

    def test_missing_mapping_invalid_method_and_automatic_reviewer_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = self.make_run(parent)
            output = parent / "inputs"
            cases = [
                ({}, METHOD, "Researcher A"),
                (bindings_for(run), "unversioned-method", "Researcher A"),
                (bindings_for(run), METHOD, "agent"),
            ]
            for bindings, method, reviewer in cases:
                with self.subTest(method=method, reviewer=reviewer):
                    with self.assertRaises(ValueError):
                        prepare_statistical_input(
                            run, bindings, method, reviewer, REVIEWED_AT, output_root=output,
                        )
            self.assertFalse(output.exists())

    def test_duplicate_physical_specimen_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = self.make_run(parent)
            dataset_path = run / "datasets" / "001-tensile" / "data.json"
            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
            duplicate = dict(dataset["records"][0])
            duplicate["record_id"] = "test-record-02"
            dataset["records"].append(duplicate)
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["files"][0]["records"] = 2
            manifest["counts"]["records"] = 2
            seal(run, manifest)
            with self.assertRaisesRegex(ValueError, "重复出现物理试样"):
                prepare_statistical_input(
                    run, bindings_for(run), METHOD, "Researcher A", REVIEWED_AT,
                    output_root=parent / "inputs",
                )

    def test_output_inside_source_package_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = self.make_run(parent)
            with self.assertRaisesRegex(ValueError, "不能位于 SteelData"):
                prepare_statistical_input(
                    run, bindings_for(run), METHOD, "Researcher A", REVIEWED_AT,
                    output_root=run / "statistics",
                )

    def test_synthetic_source_requires_explicit_flag_and_keeps_synthetic_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = self.make_run(parent)
            manifest_path = run / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["synthetic"] = True
            seal(run, manifest)
            inspection = inspect_run(run)
            self.assertIn(SYNTHETIC_PREVIEW_BLOCKER, inspection.blockers)
            with self.assertRaisesRegex(ValueError, "合成演示数据"):
                prepare_statistical_input(
                    run, bindings_for(run), METHOD, "Researcher A", REVIEWED_AT,
                    output_root=parent / "blocked",
                )
            result = prepare_statistical_input(
                run, bindings_for(run), METHOD, "Researcher A", REVIEWED_AT,
                output_root=parent / "allowed", allow_synthetic=True,
            )
            with (Path(result["bundle_dir"]) / "units.csv").open(encoding="utf-8", newline="") as handle:
                units = list(csv.DictReader(handle))
            self.assertEqual({row["unit_status"] for row in units}, {"synthetic_fixture"})


class ConfigResolutionTests(unittest.TestCase):
    """Default SteelStats location resolution: explicit > configured > legacy sibling."""

    def test_explicit_argument_beats_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            settings = parent / "settings.toml"
            write_settings_toml(settings, (parent / "configured").as_posix())
            with patch("steelai.settings.SETTINGS_FILE", settings):
                client = SteelStatsClient(parent / "explicit")
            self.assertEqual(client.project, (parent / "explicit").resolve())
            self.assertEqual(client.project_source, "explicit")

    def test_configured_absolute_path_wins_over_legacy_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            configured = parent / "configured"
            configured.mkdir()
            settings = parent / "settings.toml"
            write_settings_toml(settings, configured.as_posix())
            with patch("steelai.settings.SETTINGS_FILE", settings):
                client = SteelStatsClient()
            self.assertEqual(client.project, configured.resolve())
            self.assertEqual(client.project_source, "configured")

    def test_configured_relative_path_resolves_against_workbench_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.toml"
            write_settings_toml(settings, "fake_steelstats")
            with patch("steelai.settings.SETTINGS_FILE", settings):
                client = SteelStatsClient()
            self.assertEqual(client.project, (ROOT / "fake_steelstats").resolve())

    def test_empty_or_missing_configuration_keeps_legacy_sibling(self) -> None:
        for value in ("", None):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as temp:
                    settings = Path(temp) / "settings.toml"
                    write_settings_toml(settings, value)
                    with patch("steelai.settings.SETTINGS_FILE", settings):
                        client = SteelStatsClient()
                    self.assertEqual(client.project, (ROOT.parent / "SteelStats").resolve())
                    self.assertEqual(client.project_source, "legacy_sibling")

    def test_configured_but_invalid_fails_closed_without_sibling_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            configured = parent / "configured-but-invalid"
            configured.mkdir()
            settings = parent / "settings.toml"
            write_settings_toml(settings, configured.as_posix())
            with patch("steelai.settings.SETTINGS_FILE", settings):
                client = SteelStatsClient()
                self.assertEqual(client.project, configured.resolve())
                report = client.availability()
            self.assertFalse(report["ready"])
            self.assertEqual(report["reason"], "invalid_module_descriptor")
            with self.assertRaisesRegex(ValueError, "未就绪"):
                client._call(["verify-report", "anything"])
            self.assertEqual(client.project, configured.resolve())

    def test_real_default_client_uses_configured_location_when_available(self) -> None:
        expected = configured_steelstats_project()
        client = SteelStatsClient()
        if expected is None:
            self.skipTest("tools.steelstats_project is not configured in this environment.")
        self.assertEqual(client.project, expected)
        self.assertEqual(client.project_source, "configured")
        if not client.availability()["ready"]:
            self.skipTest("Configured SteelStats runtime is unavailable in this environment.")


class ConfigErrorBoundaryTests(unittest.TestCase):
    """Configured-but-broken settings must fail closed; only true absence of
    configuration keeps the legacy sibling lookup (WO-16 A-stage boundary)."""

    def make_valid_sibling(self, temp: Path) -> Path:
        """A working fake legacy sibling next to a patched Workbench ROOT."""
        root = temp / "wb"
        (root / "steelai").mkdir(parents=True)
        sibling = temp / "SteelStats"
        (sibling / "steelstats").mkdir(parents=True)
        (sibling / ".venv" / "Scripts").mkdir(parents=True)
        (sibling / "steelstats.module.json").write_text(json.dumps({
            "module_id": "steelstats",
            "contract_version": 1,
            "invocation": {"kind": "isolated_cli", "report_command": "report",
                           "verify_command": "verify-report"},
        }), encoding="utf-8")
        (sibling / "steelstats" / "__main__.py").write_text("", encoding="utf-8")
        (sibling / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
        return root

    def assert_closed(self, client: SteelStatsClient, leak_token: str | None = None) -> None:
        self.assertIsNone(client.project)
        self.assertEqual(client.project_source, "config_error")
        report = client.availability()
        self.assertFalse(report["ready"])
        self.assertEqual(report["reason"], "config_error")
        self.assertTrue(report.get("detail"))
        with self.assertRaisesRegex(ValueError, "未就绪"):
            client._call(["verify-report", "anything"])
        if leak_token is not None:
            self.assertNotIn(leak_token, str(report))
            self.assertNotIn(leak_token, self.raises_actionable(client))

    def raises_actionable(self, client: SteelStatsClient) -> str:
        try:
            client._call(["verify-report", "anything"])
        except ValueError as exc:
            return str(exc)
        self.fail("config_error client._call must raise ValueError")

    def test_toml_parse_error_fails_closed_without_sibling_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            root = self.make_valid_sibling(temp)
            settings = temp / "settings.toml"
            settings.write_text("[tools\nsteelstats_project = \"broken\"\n", encoding="utf-8")
            with patch("steelai.settings.SETTINGS_FILE", settings), patch(
                "steelai.steelstats_bridge.ROOT", root,
            ):
                client = SteelStatsClient()
                self.assert_closed(client, leak_token="broken")
            # explicit valid path still works despite the broken config
            explicit = SteelStatsClient(temp / "explicit-ss")
            self.assertEqual(explicit.project_source, "explicit")
            self.assertEqual(explicit.project, (temp / "explicit-ss").resolve())

    def test_non_string_field_fails_closed_without_sibling_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            root = self.make_valid_sibling(temp)
            settings = temp / "settings.toml"
            settings.write_text("[tools]\nsteelstats_project = 23\n", encoding="utf-8")
            with patch("steelai.settings.SETTINGS_FILE", settings), patch(
                "steelai.steelstats_bridge.ROOT", root,
            ):
                client = SteelStatsClient()
                self.assert_closed(client)
            with patch("steelai.settings.SETTINGS_FILE", settings):
                with self.assertRaises(SteelStatsConfigError):
                    configured_steelstats_project()

    def test_tools_not_a_table_fails_closed_without_attribute_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            root = self.make_valid_sibling(temp)
            settings = temp / "settings.toml"
            settings.write_text("tools = \"not-a-table\"\n", encoding="utf-8")
            with patch("steelai.settings.SETTINGS_FILE", settings), patch(
                "steelai.steelstats_bridge.ROOT", root,
            ):
                client = SteelStatsClient()
                self.assert_closed(client)

    def test_settings_read_error_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.toml"
            settings.mkdir()  # a directory: open() raises IsADirectoryError (an OSError)
            with patch("steelai.settings.SETTINGS_FILE", settings):
                client = SteelStatsClient()
                self.assert_closed(client)

    def test_whitespace_only_value_counts_as_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.toml"
            settings.write_text("[tools]\nsteelstats_project = \"   \"\n", encoding="utf-8")
            with patch("steelai.settings.SETTINGS_FILE", settings):
                self.assertIsNone(configured_steelstats_project())
                client = SteelStatsClient()
            self.assertEqual(client.project_source, "legacy_sibling")
            self.assertEqual(client.project, (ROOT.parent / "SteelStats").resolve())

    def test_error_message_does_not_leak_configured_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings.toml"
            settings.write_text("[tools]\nsteelstats_project = 42\n", encoding="utf-8")
            with patch("steelai.settings.SETTINGS_FILE", settings):
                client = SteelStatsClient()
            text = self.raises_actionable(client)
            report = str(client.availability())
            for token in ("42", "steelstats_project ="):
                self.assertNotIn(token, text)
                self.assertNotIn(token, report)



    def test_availability_probes_runtime_instead_of_trusting_stale_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_fake_steelstats_project(Path(temp))
            client = SteelStatsClient(project)
            with patch("steelai.steelstats_bridge.subprocess.run", side_effect=OSError("stale launcher")):
                report = client.availability()
            self.assertFalse(report["ready"])
            self.assertEqual(report["reason"], "runtime_probe_failed")

    def test_cli_uses_argument_list_independent_runtime_and_scrubbed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            client = SteelStatsClient(make_fake_steelstats_project(Path(temp)))
            response = subprocess.CompletedProcess([], 0, '{"status":"passed","problems":[]}', "")
            with patch.object(client, "availability", return_value={"ready": True}), patch(
                "steelai.steelstats_bridge.subprocess.run", return_value=response,
            ) as run, patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret", "PYTHONPATH": "unsafe"}):
                payload = client._call(["verify-report", "path with spaces & text"])
        self.assertEqual(payload["status"], "passed")
        args, kwargs = run.call_args
        self.assertEqual(args[0][-2:], ["verify-report", "path with spaces & text"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 180)
        self.assertNotIn("DEEPSEEK_API_KEY", kwargs["env"])
        self.assertNotIn("PYTHONPATH", kwargs["env"])

    def test_missing_module_invalid_json_failure_and_timeout_are_actionable(self) -> None:
        client = SteelStatsClient(Path("missing-module"))
        with self.assertRaisesRegex(ValueError, "未就绪"):
            client._call(["verify-report", "missing"])
        with patch.object(client, "availability", return_value={"ready": True}), patch(
            "steelai.steelstats_bridge.subprocess.run",
            return_value=subprocess.CompletedProcess([], 2, "not json", "broken"),
        ):
            with self.assertRaisesRegex(ValueError, "有效 JSON"):
                client._call(["verify-report", "missing"])
        with patch.object(client, "availability", return_value={"ready": True}), patch(
            "steelai.steelstats_bridge.subprocess.run", side_effect=subprocess.TimeoutExpired([], 180),
        ):
            with self.assertRaisesRegex(ValueError, "180"):
                client._call(["verify-report", "missing"])


class EndToEndBoundaryTests(unittest.TestCase):
    def test_real_default_configured_cli_generates_verified_report_without_source_writeback(self) -> None:
        """Real default SteelStatsClient(): settings-resolved location, full bridge chain."""
        client = SteelStatsClient()
        expected = configured_steelstats_project()
        if expected is None or client.project_source != "configured" or not client.availability()["ready"]:
            self.skipTest("Configured SteelStats location or its runtime is unavailable.")
        self.assertEqual(client.project, expected)
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            run = parent / "steeldata" / "run-test"
            result_fixture(run)
            before = source_snapshot(run)
            result = run_statistics_from_steeldata(
                run,
                bindings_for(run),
                METHOD,
                "Test Synthetic Reviewer (fixture only)",
                REVIEWED_AT,
                input_root=parent / "inputs",
                report_root=parent / "reports",
                client=client,
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["statistics"]["verification"], "passed")
            self.assertEqual(result["source"]["modified"], False)
            self.assertTrue(Path(result["report"]).is_file())
            self.assertIn("SYN-SAMPLE-A", Path(result["report"]).read_text(encoding="utf-8"))
            self.assertEqual(source_snapshot(run), before)


class SteelStatsViewTests(unittest.TestCase):
    def test_view_loads_verified_source_but_keeps_generate_disabled_before_human_review(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "steeldata" / "run-test"
            result_fixture(run)
            with patch.object(
                SteelStatsClient,
                "availability",
                return_value={"ready": True, "project": "test", "python": "test"},
            ):
                app = AppTest.from_file(
                    str(ROOT / "steelai" / "views" / "steelstats_view.py"), default_timeout=20,
                ).run()
                app.text_input(key="ss_run_path").set_value(str(run)).run()
                app.button(key="ss_load").click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any(item.label == "研究样品 sample_id" for item in app.text_input))
        self.assertTrue(app.button(key="ss_generate").disabled)
        self.assertEqual(app.metric[0].label, "SteelData QC")


if __name__ == "__main__":
    unittest.main()
