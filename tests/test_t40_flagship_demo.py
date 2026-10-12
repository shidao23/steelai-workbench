"""T40 acceptance tests: public synthetic success and fail-closed unit case."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from steelai.flagship_demo import (
    COMPLETE_NAME,
    FIXTURES,
    MANIFEST_NAME,
    demo_identity,
    run_flagship_demo,
    verify_flagship_demo,
)
from steelai.steeldata_bridge import SteelDataClient
from steelai.steelstats_bridge import SteelStatsClient


def _file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _default_clients() -> tuple[SteelDataClient, SteelStatsClient]:
    """Default clients whose project roots feed the fingerprint."""
    return SteelDataClient(), SteelStatsClient()


def _copy_identity_material(source_root: Path, package: str, destination: Path) -> Path:
    """Isolated copy of one module's fingerprint material (descriptor + package).

    Only the identity-relevant material is copied; the live repositories are
    never modified and no symbolic links are involved.
    """
    target = destination / source_root.name
    target.mkdir(parents=True)
    shutil.copy2(source_root / f"{package}.module.json", target / f"{package}.module.json")
    shutil.copytree(source_root / package, target / package)
    return target


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
        data_client, stats_client = _default_clients()
        if stats_client.project is None:
            self.skipTest("SteelStats project cannot be located from the current configuration.")
        if not data_client.availability()["ready"] or not stats_client.availability()["ready"]:
            self.skipTest("Sibling SteelData/SteelStats independent runtimes are unavailable.")
        # WO-17: the default consumption must follow the configured SteelStats
        # root (post-migration), not the retired legacy sibling.
        self.assertEqual(
            stats_client.project_source, "configured",
            "tools.steelstats_project 必须指向迁移后的 SteelStats 根。",
        )
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
            # WO-17: identity is computed from the actually consumed roots and
            # never carries drive letters or absolute positions.
            code_fingerprint = manifest["identity_contract"]["code_sha256"]
            self.assertIn("SteelStats/steelstats.module.json", code_fingerprint)
            self.assertIn("SteelData/steeldata.module.json", code_fingerprint)
            for key in code_fingerprint:
                self.assertFalse(Path(key).is_absolute(), key)
                self.assertNotIn(":", key)
                self.assertNotIn("..", key)
            stats_descriptor_hash = code_fingerprint["SteelStats/steelstats.module.json"]
            self.assertEqual(
                stats_descriptor_hash,
                _file_sha256(stats_client.project / "steelstats.module.json"),
            )

            second = run_flagship_demo(temp, steeldata=data_client, steelstats=stats_client)
            self.assertTrue(second["reused"])
            (package / "summary.md").write_text("tampered", encoding="utf-8")
            self.assertEqual(verify_flagship_demo(package)["status"], "failed")
            with self.assertRaisesRegex(ValueError, "不会覆盖"):
                run_flagship_demo(temp, steeldata=data_client, steelstats=stats_client)


class FingerprintConsumptionTests(unittest.TestCase):
    """WO-17: identity follows the actually consumed client project roots."""

    def _prepare_copies(self, temp: Path) -> tuple[SteelDataClient, SteelStatsClient, Path, Path]:
        data_default, stats_default = _default_clients()
        if stats_default.project is None:
            self.skipTest("SteelStats project cannot be located from the current configuration.")
        data_copy = _copy_identity_material(data_default.project, "steeldata", temp / "material_a")
        stats_copy = _copy_identity_material(stats_default.project, "steelstats", temp / "material_a")
        return (
            SteelDataClient(project=data_copy),
            SteelStatsClient(project=stats_copy),
            data_copy,
            stats_copy,
        )

    def test_explicit_client_roots_drive_the_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            data_client, stats_client, data_copy, stats_copy = self._prepare_copies(temp_path)
            demo_id, contract = demo_identity(data_client, stats_client)
            fingerprint = contract["code_sha256"]
            self.assertEqual(
                fingerprint["SteelStats/steelstats.module.json"],
                _file_sha256(stats_copy / "steelstats.module.json"),
            )
            self.assertEqual(
                fingerprint["SteelData/steeldata.module.json"],
                _file_sha256(data_copy / "steeldata.module.json"),
            )
            some_py = sorted((stats_copy / "steelstats").rglob("*.py"))[0]
            key = f"SteelStats/{some_py.relative_to(stats_copy).as_posix()}"
            self.assertEqual(fingerprint[key], _file_sha256(some_py))
            demo_id_again, contract_again = demo_identity(data_client, stats_client)
            self.assertEqual(demo_id, demo_id_again)
            self.assertEqual(contract, contract_again)

    def test_relocated_identical_content_keeps_identity_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            data_client_a, stats_client_a, _, _ = self._prepare_copies(temp_path / "one")
            # Second, byte-identical material set at a different location.
            data_default, stats_default = _default_clients()
            data_copy_b = _copy_identity_material(
                data_default.project, "steeldata", temp_path / "two" / "deeper")
            stats_copy_b = _copy_identity_material(
                stats_default.project, "steelstats", temp_path / "two" / "deeper")
            demo_id_a, contract_a = demo_identity(data_client_a, stats_client_a)
            demo_id_b, contract_b = demo_identity(
                SteelDataClient(project=data_copy_b), SteelStatsClient(project=stats_copy_b))
            self.assertEqual(demo_id_a, demo_id_b)
            self.assertEqual(contract_a, contract_b)
            for key in contract_a["code_sha256"]:
                self.assertFalse(Path(key).is_absolute(), key)
                self.assertNotIn(":", key)
                self.assertNotIn("..", key)

    def test_module_source_change_changes_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            data_client_a, stats_client_a, _, stats_copy_a = self._prepare_copies(temp_path / "a")
            data_default, stats_default = _default_clients()
            stats_copy_b = _copy_identity_material(
                stats_default.project, "steelstats", temp_path / "b")
            data_copy_b = _copy_identity_material(
                data_default.project, "steeldata", temp_path / "b")
            target = sorted((stats_copy_b / "steelstats").rglob("*.py"))[0]
            target.write_text(
                target.read_text(encoding="utf-8") + "\n# isolated fingerprint probe\n",
                encoding="utf-8",
            )
            demo_id_a, _ = demo_identity(data_client_a, stats_client_a)
            demo_id_b, contract_b = demo_identity(
                SteelDataClient(project=data_copy_b), SteelStatsClient(project=stats_copy_b))
            self.assertNotEqual(demo_id_a, demo_id_b)
            changed_key = f"SteelStats/{target.relative_to(stats_copy_b).as_posix()}"
            self.assertEqual(contract_b["code_sha256"][changed_key], _file_sha256(target))

    def test_missing_module_descriptor_fails_operably_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            data_client, stats_client, _, stats_copy = self._prepare_copies(temp_path)
            (stats_copy / "steelstats.module.json").unlink()
            with self.assertRaisesRegex(ValueError, "SteelStats/steelstats.module.json"):
                demo_identity(data_client, stats_client)

    def test_config_error_client_is_rejected_not_fallback(self) -> None:
        with mock.patch(
            "steelai.steelstats_bridge.load_settings",
            side_effect=OSError("settings unavailable"),
        ):
            broken = SteelStatsClient()
        self.assertIsNone(broken.project)
        self.assertEqual(broken.project_source, "config_error")
        with self.assertRaisesRegex(ValueError, "无法定位 SteelStats 项目"):
            demo_identity(steelstats=broken)


if __name__ == "__main__":
    unittest.main()
