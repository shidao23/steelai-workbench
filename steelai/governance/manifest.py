"""Governance Manifest construction, sealing and integrity verification."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from .contract import load_governance_contract
from .models import (
    ApprovalSnapshot,
    ArtifactRecord,
    EvidenceClass,
    GovernanceManifest,
    GovernanceState,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    VerificationResult,
    utc_now,
)
from .serialization import read_json_object, sha256_file, write_json_atomic


MANIFEST_NAME = "governance_manifest.json"
COMPLETE_NAME = "COMPLETE"

_RESULT_STATE_COMPATIBILITY = {
    ResultLevel.WORKING_CANDIDATE.value: {state.value for state in GovernanceState},
    ResultLevel.SYNTHETIC_DEMO_ONLY.value: {"passed", "complete"},
    ResultLevel.MODEL_RESULT.value: {"complete"},
    ResultLevel.VERIFIED_OUTPUT.value: {"passed", "warning", "complete"},
    ResultLevel.ACCEPTED_EVIDENCE.value: {"complete"},
    ResultLevel.HUMAN_CONCLUSION.value: {"complete"},
}
_CLASS_RESULT_COMPATIBILITY = {
    EvidenceClass.REAL_RESEARCH_DATA.value: {"working_candidate", "verified_output", "accepted_evidence"},
    EvidenceClass.SYNTHETIC_DEMO_DATA.value: {"working_candidate", "synthetic_demo_only"},
    EvidenceClass.MODEL_OUTPUT.value: {"working_candidate", "model_result"},
    EvidenceClass.HUMAN_CONCLUSION.value: {"working_candidate", "human_conclusion"},
}


def _validate_result_semantics(state: str, result_level: str, evidence_class: str) -> None:
    GovernanceState(state)
    ResultLevel(result_level)
    EvidenceClass(evidence_class)
    if state not in _RESULT_STATE_COMPATIBILITY[result_level]:
        raise ValueError(f"result level {result_level} is incompatible with state {state}")
    if result_level not in _CLASS_RESULT_COMPATIBILITY[evidence_class]:
        raise ValueError(f"result level {result_level} is incompatible with evidence class {evidence_class}")


def _artifacts(root: Path, excluded: set[str]) -> tuple[ArtifactRecord, ...]:
    records: list[ArtifactRecord] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symbolic links are not allowed in governed packages: {path.name}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        records.append(ArtifactRecord(relative, sha256_file(path), path.stat().st_size))
    return tuple(records)


def build_manifest(
    artifact_root: str | Path,
    *,
    publication_id: str,
    identity: ResearchObjectIdentity,
    state: str | GovernanceState,
    result_level: str | ResultLevel,
    evidence_class: str | EvidenceClass,
    sources: Iterable[SourceReference],
    approvals: Iterable[ApprovalSnapshot] = (),
    generated_by: str,
    generated_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> GovernanceManifest:
    root = Path(artifact_root).resolve()
    if not root.is_dir():
        raise ValueError("artifact_root must be an existing directory")
    state_value = GovernanceState(state).value
    result_value = ResultLevel(result_level).value
    class_value = EvidenceClass(evidence_class).value
    _validate_result_semantics(state_value, result_value, class_value)
    source_records = tuple(sources)
    if not source_records:
        raise ValueError("at least one source reference is required")
    manifest = GovernanceManifest(
        contract_id=load_governance_contract()["contract_id"],
        manifest_version="1.0",
        publication_id=publication_id,
        identity=identity,
        state=state_value,
        result_level=result_value,
        evidence_class=class_value,
        sources=source_records,
        approvals=tuple(approvals),
        artifacts=_artifacts(root, {MANIFEST_NAME, COMPLETE_NAME}),
        generated_at=generated_at or utc_now(),
        generated_by=generated_by,
        metadata=dict(metadata or {}),
    )
    return GovernanceManifest.from_dict(manifest.to_dict())


def seal_package(
    root: str | Path,
    manifest: GovernanceManifest,
    *,
    manifest_name: str = MANIFEST_NAME,
    complete_name: str = COMPLETE_NAME,
) -> str:
    package = Path(root).resolve()
    if not package.is_dir():
        raise ValueError("package root must be an existing directory")
    if manifest_name != MANIFEST_NAME or complete_name != COMPLETE_NAME:
        raise ValueError("governance v1 uses fixed manifest and completion marker names")
    current = _artifacts(package, {manifest_name, complete_name})
    if current != manifest.artifacts:
        raise ValueError("package artifacts changed after manifest construction")
    manifest_path = package / manifest_name
    write_json_atomic(manifest_path, manifest.to_dict())
    manifest_digest = sha256_file(manifest_path)
    marker = package / complete_name
    marker.write_text(f"governance_manifest_sha256={manifest_digest}\n", encoding="utf-8")
    return manifest_digest


def _unsafe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in value


def verify_package(
    root: str | Path,
    *,
    manifest_name: str = MANIFEST_NAME,
    complete_name: str = COMPLETE_NAME,
) -> VerificationResult:
    package = Path(root).resolve()
    problems: list[str] = []
    if not package.is_dir():
        return VerificationResult("invalidated", None, None, 0, ("package directory does not exist",))
    manifest_path = package / manifest_name
    marker_path = package / complete_name
    if not marker_path.is_file():
        problems.append("completion marker is missing")
    try:
        raw = read_json_object(manifest_path)
        manifest = GovernanceManifest.from_dict(raw)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return VerificationResult("invalidated", None, None, 0, tuple(problems + [f"manifest is invalid: {exc}"]))

    manifest_digest = sha256_file(manifest_path)
    if marker_path.is_file():
        expected = f"governance_manifest_sha256={manifest_digest}\n"
        try:
            if marker_path.read_text(encoding="utf-8") != expected:
                problems.append("completion marker does not bind the current manifest")
        except OSError:
            problems.append("completion marker cannot be read")
    if manifest.publication_fingerprint != manifest.expected_fingerprint():
        problems.append("publication fingerprint does not match manifest content")
    try:
        _validate_result_semantics(manifest.state, manifest.result_level, manifest.evidence_class)
    except ValueError as exc:
        problems.append(str(exc))

    declared = {item.path: item for item in manifest.artifacts}
    try:
        actual = {item.path: item for item in _artifacts(package, {manifest_name, complete_name})}
    except ValueError as exc:
        actual = {}
        problems.append(str(exc))
    if set(declared) != set(actual):
        problems.append("artifact file set does not match the manifest")
    for name, record in declared.items():
        if _unsafe_path(name):
            problems.append(f"unsafe artifact path: {name}")
            continue
        observed = actual.get(name)
        if observed is None:
            continue
        if observed.sha256 != record.sha256 or observed.size_bytes != record.size_bytes:
            problems.append(f"artifact digest or size mismatch: {name}")

    return VerificationResult(
        "passed" if not problems else "invalidated",
        manifest.publication_id,
        manifest_digest,
        len(manifest.artifacts),
        tuple(problems),
    )


def load_verified_manifest(root: str | Path) -> GovernanceManifest:
    verification = verify_package(root)
    if verification.status != "passed":
        raise ValueError("governed package is invalidated: " + "; ".join(verification.problems))
    return GovernanceManifest.from_dict(read_json_object(Path(root) / MANIFEST_NAME))
