"""Synthetic tests for the restricted double-hit case reference (PAOS-004B1 / 004B1R / 004B1R2).

Every case package here is built from synthesised evidence through the existing governance core. No
real research data, literature file, model or API is involved, and the tests never read ``lab_data/``.

The synthetic package root is injected through the internal Python API only. The public command line
must never be able to select a directory, so the CLI is exercised in-process with that internal
argument, and in a clean child process for the refusals that do not need a package.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from steelai.governance import (
    COMPLETE_NAME,
    MANIFEST_NAME,
    GovernanceManifest,
    GovernanceState,
    build_manifest,
    seal_package,
    sha256_file,
    verify_package,
)
from steelai.thermal_softening_case import publish_softening_case
from steelai.thermal_softening_case_ref import (
    REFUSAL_CODES,
    CaseReferenceError,
    InvalidCaseIdError,
    PackageMissingError,
    build_case_reference,
    resolve_case_root,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "export_thermal_softening_case_ref.py"
REFERENCE_KEYS = {
    "case_id",
    "package_verification",
    "manifest_digest",
    "review_state",
    "row_count",
    "artifact_count",
}
CASE_ID = "TSC-" + "A" * 20
OTHER_CASE_ID = "TSC-" + "B" * 20


def _load_cli_module():
    """Load the export script as a module so its main() can be called in-process."""
    spec = importlib.util.spec_from_file_location("paos_case_ref_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLI = _load_cli_module()


def _synthetic_case(case_id: str = CASE_ID) -> dict[str, object]:
    digest = "a" * 64
    return {
        "case_id": case_id,
        "status": "analysis_draft_needs_human_review",
        "row_count": 1,
        "passed_count": 0,
        "warning_ids": ["A1"],
        "large_method_difference_passed_ids": [],
        "source_digests": {
            "runs_sha256": digest,
            "points_sha256": digest,
            "features_sha256": digest,
            "formal_results_sha256": digest,
            "method_registry_sha256": digest,
            "literature_pdf_sha256": digest,
        },
        "observations": {
            "near_1000_c_9_to_11_s": {
                "b_dq_primary_percent_range": [50.0, 50.0],
                "r_dq_primary_percent_range": [70.0, 70.0],
            }
        },
        "rows": [{
            "acquisition_id": "A1", "sample_id": "B-DQ", "temperature_c": 1000.0,
            "deformation_gap_s": 10.0, "primary_percent": 120.0,
            "sensitivity_percent": 108.0, "qc_status": "warning_needs_human_review",
        }],
    }


@pytest.fixture()
def case_root(tmp_path: Path) -> Path:
    root = tmp_path / "cases"
    publish_softening_case(_synthetic_case(), output_root=root)
    return root


def _run_cli_in_process(*arguments: str, package_root: Path | None = None) -> tuple[int, str, str]:
    """Call the public main() with redirected streams. package_root is an internal test argument."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = CLI.main(list(arguments), package_root=package_root)
    return code, out.getvalue(), err.getvalue()


def _run_cli_clean_process(*arguments: str, environment: dict[str, str] | None = None):
    """Run the public script in a clean interpreter from the repository root."""
    child_environment = dict(os.environ)
    child_environment.pop("PYTHONPATH", None)  # the documented command needs no path setup
    if environment:
        child_environment.update(environment)
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *arguments],
        capture_output=True, text=True, check=False, cwd=str(REPO_ROOT), env=child_environment,
    )


def _set_manifest_state(package: Path, state: str) -> None:
    manifest_path = package / MANIFEST_NAME
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["state"] = state  # working_candidate accepts any state, so only the review guard reacts
    raw["publication_fingerprint"] = GovernanceManifest.from_dict(raw).expected_fingerprint()
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    (package / COMPLETE_NAME).write_text(
        f"governance_manifest_sha256={sha256_file(manifest_path)}\n", encoding="utf-8"
    )
    verification = verify_package(package)
    assert verification.status == "passed", verification.problems


# --------------------------------------------------------------------------------------
# success path
# --------------------------------------------------------------------------------------

def test_reference_carries_only_identity_digest_state_and_counts(case_root: Path) -> None:
    package = case_root / CASE_ID
    verification = verify_package(package)
    assert verification.status == "passed"

    reference = build_case_reference(CASE_ID, package_root=case_root)

    assert set(reference) == REFERENCE_KEYS
    assert reference["case_id"] == CASE_ID
    assert reference["package_verification"] == "passed"
    assert reference["review_state"] == "needs_human"
    assert reference["manifest_digest"] == verification.manifest_digest
    assert reference["manifest_digest"] == sha256_file(package / MANIFEST_NAME)
    assert reference["row_count"] == 1
    assert reference["artifact_count"] == verification.artifact_count

    serialised = json.dumps(reference, ensure_ascii=False)
    assert "lab_data" not in serialised
    assert "analysis_draft" not in serialised
    assert "120.0" not in serialised  # a raw softening value must not leak
    assert "B-DQ" not in serialised  # a raw sample identifier must not leak
    assert "data/processed" not in serialised
    assert "\\" not in serialised  # no local path separator
    assert str(case_root) not in serialised


# --------------------------------------------------------------------------------------
# refusals through the internal API
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "case_id",
    [
        "../escape",
        "TSC-" + "A" * 19,
        "TSC-" + "a" * 20,  # pattern is upper-case hex only
        "tsc-" + "A" * 20,
        "",
        "TSC-AAAAAAAAAAAAAAAAAAAA/../..",
    ],
)
def test_malformed_case_ids_are_refused(case_root: Path, case_id: str) -> None:
    with pytest.raises(InvalidCaseIdError):
        build_case_reference(case_id, package_root=case_root)


def test_unknown_case_id_is_refused(case_root: Path) -> None:
    with pytest.raises(PackageMissingError):
        build_case_reference(OTHER_CASE_ID, package_root=case_root)


def test_tampered_package_is_refused(case_root: Path) -> None:
    evidence_path = case_root / CASE_ID / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["row_count"] = 99
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    assert verify_package(case_root / CASE_ID).status == "invalidated"

    with pytest.raises(CaseReferenceError):
        build_case_reference(CASE_ID, package_root=case_root)


def test_manifest_identity_mismatch_is_refused(case_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second, independently valid package that is not the identity the caller asked for."""
    import steelai.thermal_softening_case_ref as module

    publish_softening_case(_synthetic_case(OTHER_CASE_ID), output_root=case_root)
    other_package = case_root / OTHER_CASE_ID
    assert verify_package(other_package).status == "passed"

    real_verify = module.verify_package
    monkeypatch.setattr(module, "verify_package", lambda directory: real_verify(other_package))

    with pytest.raises(CaseReferenceError) as raised:
        build_case_reference(CASE_ID, package_root=case_root)
    assert raised.value.code == "CASE_IDENTITY_MISMATCH"


def test_resealed_evidence_with_wrong_case_id_is_identity_mismatch(case_root: Path) -> None:
    """Manifest and COMPLETE stay valid and the manifest identity is correct - only the evidence
    content names a different case, and the package is re-sealed so integrity alone cannot object.

    The refusal code is fixed: this is an identity disagreement, not a broken package.
    """
    package = case_root / CASE_ID
    evidence_path = package / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["case_id"] = OTHER_CASE_ID
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    # Rebuild and re-seal the manifest through the public governance API so the package is complete
    # again and the manifest still names CASE_ID; only the evidence disagrees.
    manifest_path = package / MANIFEST_NAME
    previous = GovernanceManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    rebuilt = build_manifest(
        package,
        publication_id=CASE_ID,
        identity=previous.identity,
        state=GovernanceState.NEEDS_HUMAN,
        result_level=previous.result_level,
        evidence_class=previous.evidence_class,
        sources=previous.sources,
        generated_by=previous.generated_by,
        generated_at=previous.generated_at,
        metadata=previous.metadata,
    )
    seal_package(package, rebuilt)
    assert verify_package(package).status == "passed"

    with pytest.raises(CaseReferenceError) as raised:
        build_case_reference(CASE_ID, package_root=case_root)
    assert raised.value.code == "CASE_IDENTITY_MISMATCH"


def test_review_state_other_than_needs_human_is_refused(case_root: Path) -> None:
    _set_manifest_state(case_root / CASE_ID, "approved")

    with pytest.raises(CaseReferenceError) as raised:
        build_case_reference(CASE_ID, package_root=case_root)
    assert raised.value.code == "CASE_REVIEW_STATE_NOT_NEEDS_HUMAN"


def test_missing_evidence_file_is_refused_without_path_leak(case_root: Path) -> None:
    (case_root / CASE_ID / "evidence.json").unlink()

    with pytest.raises(CaseReferenceError) as raised:
        build_case_reference(CASE_ID, package_root=case_root)
    assert str(case_root) not in str(raised.value)
    assert str(case_root) not in raised.value.message
    assert "\\" not in raised.value.message


def test_missing_manifest_is_refused_without_path_leak(case_root: Path) -> None:
    (case_root / CASE_ID / MANIFEST_NAME).unlink()

    with pytest.raises(CaseReferenceError) as raised:
        build_case_reference(CASE_ID, package_root=case_root)
    assert str(case_root) not in raised.value.message
    assert "\\" not in raised.value.message


# --------------------------------------------------------------------------------------
# the production root cannot be redirected (PAOS-004B1R2)
# --------------------------------------------------------------------------------------

def test_resolve_case_root_ignores_the_legacy_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from steelai.thermal_softening_case import CASE_ROOT

    monkeypatch.setenv("STEELAI_THERMAL_CASE_ROOT", str(tmp_path / "hostile"))
    assert resolve_case_root() == CASE_ROOT


def test_cli_success_path_ignores_the_legacy_environment_variable(
    case_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import steelai.thermal_softening_case_ref as module

    # The public CLI resolves its root through resolve_case_root(); point that at the synthetic root
    # internally, then set the legacy environment variable and confirm it is not consulted.
    monkeypatch.setattr(module, "CASE_ROOT", case_root)
    monkeypatch.setenv("STEELAI_THERMAL_CASE_ROOT", "D:\\PRIVATE\\case-root")

    code, stdout, stderr = _run_cli_in_process(CASE_ID)

    assert code == 0, stderr
    assert json.loads(stdout)["case_id"] == CASE_ID


def test_legacy_environment_variable_does_not_let_the_cli_read_a_package(
    case_root: Path,
) -> None:
    """A clean process with the legacy variable set must not resolve the synthetic package."""
    completed = _run_cli_clean_process(
        CASE_ID, environment={"STEELAI_THERMAL_CASE_ROOT": str(case_root)}
    )

    assert completed.returncode == 2
    assert "refused: CASE_PACKAGE_MISSING" in completed.stderr
    assert str(case_root) not in completed.stderr


# --------------------------------------------------------------------------------------
# public command line
# --------------------------------------------------------------------------------------

def test_documented_command_imports_and_prints_help_from_repository_root() -> None:
    completed = _run_cli_clean_process("--help")
    assert completed.returncode == 0, completed.stderr
    assert "case_id" in completed.stdout


def test_cli_prints_path_free_json_and_exits_zero(case_root: Path) -> None:
    code, stdout, stderr = _run_cli_in_process(CASE_ID, package_root=case_root)

    assert code == 0, stderr
    reference = json.loads(stdout)
    assert set(reference) == REFERENCE_KEYS
    assert reference["case_id"] == CASE_ID
    assert reference["package_verification"] == "passed"
    assert reference["review_state"] == "needs_human"
    assert str(case_root) not in stdout
    assert str(case_root) not in stderr


@pytest.mark.parametrize(
    ("case_id", "expected_code"),
    [
        ("../escape", "CASE_ID_INVALID"),
        ("TSC-" + "a" * 20, "CASE_ID_INVALID"),
        ("TSC-" + "B" * 20, "CASE_PACKAGE_MISSING"),
    ],
)
def test_cli_refusals_are_nonzero_and_path_free(
    case_root: Path, case_id: str, expected_code: str
) -> None:
    code, stdout, stderr = _run_cli_in_process(case_id, package_root=case_root)

    assert code == 2
    assert stdout.strip() == ""
    assert f"refused: {expected_code}" in stderr
    assert str(case_root) not in stderr
    assert "escape" not in stderr
    assert "Traceback" not in stderr


def test_cli_missing_evidence_reports_stable_code_without_path(case_root: Path) -> None:
    (case_root / CASE_ID / "evidence.json").unlink()

    code, stdout, stderr = _run_cli_in_process(CASE_ID, package_root=case_root)

    assert code == 2
    assert stdout.strip() == ""
    assert "refused: CASE_" in stderr
    assert str(case_root) not in stderr
    assert "Traceback" not in stderr
    assert 'File "' not in stderr


def test_cli_missing_manifest_reports_stable_code_without_path(case_root: Path) -> None:
    (case_root / CASE_ID / MANIFEST_NAME).unlink()

    code, stdout, stderr = _run_cli_in_process(CASE_ID, package_root=case_root)

    assert code == 2
    assert stdout.strip() == ""
    assert "refused: CASE_PACKAGE_INVALIDATED" in stderr
    assert str(case_root) not in stderr
    assert "Traceback" not in stderr
    assert 'File "' not in stderr


def test_cli_tampered_package_reports_stable_code_without_path(case_root: Path) -> None:
    evidence_path = case_root / CASE_ID / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["row_count"] = 99
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    code, stdout, stderr = _run_cli_in_process(CASE_ID, package_root=case_root)

    assert code == 2
    assert "refused: CASE_PACKAGE_INVALIDATED" in stderr
    assert str(case_root) not in stderr
    assert "Traceback" not in stderr


# --------------------------------------------------------------------------------------
# argument parsing is path-free too (PAOS-004B1R2)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "arguments",
    [
        ("TSC-" + "B" * 20, "--case-root", "D:\\PRIVATE\\case-root"),
        ("TSC-" + "B" * 20, "--case-root=D:\\PRIVATE\\case-root"),
        ("--package-root", "D:\\PRIVATE\\case-root"),
        ("TSC-" + "B" * 20, "D:\\PRIVATE\\case-root"),
        ("TSC-" + "B" * 20, "--unknown-flag"),
    ],
)
def test_argument_refusals_never_echo_the_argument(arguments: tuple[str, ...]) -> None:
    code, stdout, stderr = _run_cli_in_process(*arguments)

    assert code == 2
    assert stdout.strip() == ""
    assert "refused: CASE_ARGUMENT_" in stderr
    assert "PRIVATE" not in stderr
    assert "case-root" not in stderr
    assert "usage:" not in stderr
    assert "unrecognized" not in stderr
    assert "Traceback" not in stderr


def test_argument_refusals_never_echo_the_argument_in_a_clean_process() -> None:
    completed = _run_cli_clean_process(
        "TSC-" + "B" * 20, "--case-root", "D:\\PRIVATE\\case-root"
    )

    assert completed.returncode == 2
    assert completed.stdout.strip() == ""
    assert "refused: CASE_ARGUMENT_" in completed.stderr
    assert "PRIVATE" not in completed.stderr
    assert "case-root" not in completed.stderr
    assert "usage:" not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_missing_case_id_argument_is_refused() -> None:
    code, stdout, stderr = _run_cli_in_process()

    assert code == 2
    assert stdout.strip() == ""
    assert "refused: CASE_ARGUMENT_INVALID" in stderr
    assert "Traceback" not in stderr


def test_synthetic_demo_package_cannot_be_cited_as_a_research_case(tmp_path: Path) -> None:
    """STEEL-V1-03C: the classification must come from the VERIFIED manifest, and only
    real_research_data packages are citable through this restricted research channel."""
    root = tmp_path / "demo-cases"
    publish_softening_case(_synthetic_case(), output_root=root, synthetic_demo=True)

    with pytest.raises(CaseReferenceError) as raised:
        build_case_reference(CASE_ID, package_root=root)

    assert raised.value.code == "CASE_NOT_REAL_RESEARCH"
    assert raised.value.code in REFUSAL_CODES
    # The stable code stays path-free.
    assert "tmp" not in str(raised.value).lower()
    assert CASE_ID not in str(raised.value)
