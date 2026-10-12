"""S3-03 - acceptance for the restricted structured case snapshot (SteelAI side).

The fixed REAL case is exercised read-only through the production root; every synthetic
scenario (demo refusal, tamper refusal, formal-path round trip) uses temporary governed
packages built through the public publish entry - the real package and all formal sources are
never touched. Proves: every export re-verifies; only real_research_data + needs_human passes;
rows keep their raw unclipped values; output is path-free; the CLI accepts only a case ID.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from steelai import thermal_softening_case
from steelai.thermal_softening_case_ref import (
    IdentityMismatchError,
    InvalidCaseIdError,
    NotRealResearchError,
    PackageMissingError,
    PackageVerificationError,
)
from steelai.thermal_softening_case_snapshot import SNAPSHOT_SCHEMA, build_case_snapshot

REAL_CASE_ID = "TSC-9DF11B41FB31FF5C6C08"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOT_SCRIPT = _REPO_ROOT / "scripts" / "export_thermal_softening_case_snapshot.py"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load_demo_module():
    spec = importlib.util.spec_from_file_location(
        "demo_thermal_softening_case",
        _REPO_ROOT / "scripts" / "demo_thermal_softening_case.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _formal_shape_case() -> dict[str, object]:
    digest = "a" * 64
    return {
        "case_id": "TSC-" + "F" * 20,
        "case_version": "Synthetic-Formal-v1",
        "status": "analysis_draft_needs_human_review",
        "method": {
            "primary_id": "offset_2p0_srx_focused",
            "sensitivity_id": "fixed_true_strain_0p05",
            "primary_sigma_m": "first_hit_observed_peak",
            "sensitivity_sigma_m": "first_hit_hollomon_projection",
            "same_sigma_m_for_both_methods": False,
        },
        "row_count": 1,
        "passed_count": 0,
        "warning_ids": ["A1"],
        "large_method_difference_passed_ids": [],
        "source_digests": {
            "runs_sha256": digest, "points_sha256": digest, "features_sha256": digest,
            "formal_results_sha256": digest, "method_registry_sha256": digest,
            "literature_pdf_sha256": digest,
        },
        "observations": {},
        "rows": [{
            "acquisition_id": "A1", "sample_id": "B-DQ", "temperature_c": 1000.0,
            "deformation_gap_s": 10.0, "primary_percent": 120.0,
            "sensitivity_percent": 108.0, "sensitivity_minus_primary_pp": -12.0,
            "sigma_2_minus_sigma_1_mpa": -2.0, "qc_status": "warning_needs_human_review",
            "qc_flags": ["primary_softening_outside_0_to_1"],
            "approved_row_digest": "b" * 64,
        }],
    }


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(_SNAPSHOT_SCRIPT), *args],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=180,
    )


def test_real_fixed_case_snapshot_matches_the_frozen_contract() -> None:
    snapshot = build_case_snapshot(REAL_CASE_ID)
    assert snapshot["snapshot_schema"] == SNAPSHOT_SCHEMA
    case = snapshot["case"]
    assert case["case_id"] == REAL_CASE_ID
    assert case["case_version"] == "SteelAI-Thermal-Softening-Case-v1.1"
    assert case["manifest_digest"] == (
        "db7ef1049727cf1cee975491e32dcd8fc3b64ed89bf006cb7ab589431c8e48df")
    assert case["identity_revision"] == 1
    assert case["evidence_class"] == "real_research_data"
    assert case["governance_state"] == "needs_human"
    assert case["result_level"] == "working_candidate"
    assert snapshot["counts"] == {"row_count": 16, "passed_count": 12}
    assert len(snapshot["sources"]) == 6
    assert {s["source_id"] for s in snapshot["sources"]} == {
        "approved-t71-runs", "approved-t71-points", "approved-t74-features",
        "approved-t75-results", "zhang-ling-2007-thesis", "approved-t75-method"}
    assert {s["relative_locator"] for s in snapshot["sources"] if s["relative_locator"]} == {
        "data/processed/thermal_simulation_runs.csv",
        "data/processed/thermal_simulation_points.csv",
        "data/processed/thermal_simulation_features.csv",
        "data/processed/thermal_simulation_softening.csv",
        "config/thermal_softening_method_registry_v1.0.json"}
    assert len(snapshot["artifacts"]) == 2
    assert {a["artifact_role"] for a in snapshot["artifacts"]} == {"analysis_draft", "evidence"}
    assert len(snapshot["rows"]) == 16
    raw_over_100 = [row for row in snapshot["rows"] if row["primary_percent"] > 100.0]
    assert len(raw_over_100) == 4  # raw warnings are kept, never clipped
    for row in snapshot["rows"]:
        assert _HEX64.fullmatch(row["approved_row_digest"])
    # path-free output: no drive letters, no user names, no draft or literature text
    text = json.dumps(snapshot, ensure_ascii=False)
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    assert "张玲" not in text and "双道次软化实验分析草稿" not in text


def test_snapshot_is_stable_across_exports() -> None:
    assert build_case_snapshot(REAL_CASE_ID) == build_case_snapshot(REAL_CASE_ID)


def test_invalid_and_missing_case_ids_are_refused() -> None:
    with pytest.raises(InvalidCaseIdError):
        build_case_snapshot("TSC-short")
    with pytest.raises(PackageMissingError):
        build_case_snapshot("TSC-" + "0" * 20)


def test_synthetic_demo_package_is_refused_as_not_real_research(tmp_path: Path) -> None:
    demo = _load_demo_module()
    case = demo.build_synthetic_demo_case()
    thermal_softening_case.publish_softening_case(
        case, output_root=tmp_path, synthetic_demo=True)
    with pytest.raises(NotRealResearchError):
        build_case_snapshot(case["case_id"], package_root=tmp_path)


def test_tampered_synthetic_package_is_refused_without_real_package_contact(tmp_path: Path) -> None:
    destination = thermal_softening_case.publish_softening_case(
        _formal_shape_case(), output_root=tmp_path)
    evidence_path = destination / "evidence.json"
    original = evidence_path.read_bytes()
    evidence_path.write_bytes(original.replace(b'"row_count": 1', b'"row_count": 2'))
    with pytest.raises(PackageVerificationError):
        build_case_snapshot(_formal_shape_case()["case_id"], package_root=tmp_path)
    # the tampered synthetic package stays as-is (this is a disposable copy anyway)


def test_synthetic_real_package_snapshot_round_trip(tmp_path: Path) -> None:
    destination = thermal_softening_case.publish_softening_case(
        _formal_shape_case(), output_root=tmp_path)
    assert destination.is_dir()
    case_id = _formal_shape_case()["case_id"]
    snapshot = build_case_snapshot(case_id, package_root=tmp_path)
    assert snapshot["snapshot_schema"] == SNAPSHOT_SCHEMA
    assert snapshot["case"]["evidence_class"] == "real_research_data"
    assert snapshot["case"]["governance_state"] == "needs_human"
    assert snapshot["counts"] == {"row_count": 1, "passed_count": 0}
    assert len(snapshot["sources"]) == 6 and len(snapshot["artifacts"]) == 2
    assert snapshot["rows"][0]["primary_percent"] == 120.0  # raw, unclipped
    assert snapshot == build_case_snapshot(case_id, package_root=tmp_path)


def test_identity_mismatch_inside_a_package_is_refused(tmp_path: Path) -> None:
    case = _formal_shape_case()
    other = json.loads(json.dumps(case))
    other["case_id"] = "TSC-" + "E" * 20
    thermal_softening_case.publish_softening_case(case, output_root=tmp_path)
    with pytest.raises(PackageMissingError):
        build_case_snapshot("TSC-" + "E" * 20, package_root=tmp_path)


def test_cli_emits_snapshot_and_refuses_stably() -> None:
    result = _run_cli(REAL_CASE_ID)
    assert result.returncode == 0, result.stderr
    snapshot = json.loads(result.stdout)
    assert snapshot["case"]["case_id"] == REAL_CASE_ID

    bad_shape = _run_cli("TSC-short")
    assert bad_shape.returncode == 2
    assert bad_shape.stderr.startswith("CASE_ID_INVALID")
    assert str(_REPO_ROOT) not in bad_shape.stderr

    missing = _run_cli("TSC-" + "0" * 20)
    assert missing.returncode == 2
    assert missing.stderr.startswith("CASE_PACKAGE_MISSING")

    for bad_argv in ([], ["a", "b"]):
        usage = _run_cli(*bad_argv)
        assert usage.returncode == 3
        assert "CASE_ARGUMENT_INVALID" in usage.stderr
