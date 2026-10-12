"""STEEL-V1 (S3) - restricted read-only STRUCTURED snapshot of a governed real case.

S3-03: the platform needs more than the PAOS-004B1 reference (which deliberately exposes only
counts): it needs the case's curated structured rows - identity, method, counts, source and
artifact digests, and the small per-acquisition measurement rows - so the governed import into
the platform's SQLite store can be validated field by field.

Boundaries kept (same discipline as ``thermal_softening_case_ref``):

* Read-only: never rebuilds the case, never writes a package, never satisfies a human gate.
* Every export RE-VERIFIES the package; the ``COMPLETE`` marker alone is never accepted.
* Only ``real_research_data`` + ``needs_human`` packages are eligible; a synthetic demo package
  (whatever its internal consistency) is refused with the stable ``CASE_NOT_REAL_RESEARCH`` code.
* Output is path-free: logical relative locators and digests only, no absolute paths, no draft
  or literature text, no raw CSV.
* The one production package root stays ``CASE_ROOT``; ``package_root`` exists solely so tests
  can point at a synthetic governed package and is never a CLI option.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from steelai.governance import load_verified_manifest, verify_package
from steelai.thermal_softening_case import CASE_ROOT, load_softening_case
from steelai.thermal_softening_case_ref import (
    CaseReferenceError,
    IdentityMismatchError,
    InvalidCaseIdError,
    NotRealResearchError,
    PackageMissingError,
    PackageVerificationError,
    ReviewStateError,
    _case_directory,
)

#: Fixed schema identifier of this snapshot contract (frozen in PAOS-S3-01 §8).
SNAPSHOT_SCHEMA = "SteelAI-Thermal-Softening-Snapshot-v1"

#: Package artifact path -> logical artifact role (the platform stores the role).
_ARTIFACT_ROLES = {
    "analysis_draft.md": "analysis_draft",
    "evidence.json": "evidence",
}


def build_case_snapshot(case_id: str, *, package_root: Path | None = None) -> dict[str, Any]:
    """Return the restricted structured snapshot for one governed real case."""
    if not isinstance(case_id, str):
        raise InvalidCaseIdError()
    root = Path(package_root) if package_root is not None else CASE_ROOT
    try:
        directory = _case_directory(case_id, root)
    except CaseReferenceError:
        raise
    if not directory.is_dir():
        raise PackageMissingError()

    verification = verify_package(directory)
    if verification.status != "passed":
        raise PackageVerificationError()
    manifest = load_verified_manifest(directory)
    if manifest.publication_id != case_id:
        raise IdentityMismatchError()
    if manifest.evidence_class != "real_research_data":
        raise NotRealResearchError()
    if manifest.state != "needs_human":
        raise ReviewStateError()

    evidence = load_softening_case(case_id, output_root=root)
    if not isinstance(evidence, dict) or evidence.get("case_id") != case_id:
        raise IdentityMismatchError()

    method = evidence.get("method")
    required_method = {"primary_id", "sensitivity_id", "primary_sigma_m",
                       "sensitivity_sigma_m", "same_sigma_m_for_both_methods"}
    if not isinstance(method, dict) or not required_method.issubset(method):
        raise PackageVerificationError()
    rows = evidence.get("rows")
    if not isinstance(rows, list):
        raise PackageVerificationError()

    sources = [
        {
            "source_id": source.source_id,
            "source_revision": source.source_revision,
            "source_digest": source.source_digest,
            "evidence_class": source.evidence_class,
            "source_status": source.source_status,
            "relative_locator": source.relative_locator,
        }
        for source in manifest.sources
    ]
    artifacts = []
    for artifact in manifest.artifacts:
        role = _ARTIFACT_ROLES.get(artifact.path)
        if role is None:
            # A governed artifact the platform contract does not name: refuse rather than guess.
            raise PackageVerificationError()
        artifacts.append({
            "artifact_role": role,
            "package_path": artifact.path,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        })

    return {
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "case": {
            "case_id": case_id,
            "case_version": evidence["case_version"],
            "manifest_digest": verification.manifest_digest,
            "identity_content_digest": manifest.identity.content_digest,
            "identity_revision": manifest.identity.revision,
            "publication_fingerprint": manifest.publication_fingerprint,
            "evidence_class": manifest.evidence_class,
            "governance_state": manifest.state,
            "result_level": manifest.result_level,
            "status": evidence["status"],
        },
        "method": {
            "primary_id": method["primary_id"],
            "sensitivity_id": method["sensitivity_id"],
            "primary_sigma_m": method["primary_sigma_m"],
            "sensitivity_sigma_m": method["sensitivity_sigma_m"],
            "same_sigma_m_for_both_methods": bool(method["same_sigma_m_for_both_methods"]),
        },
        "counts": {
            "row_count": int(evidence["row_count"]),
            "passed_count": int(evidence["passed_count"]),
        },
        "sources": sources,
        "artifacts": artifacts,
        "rows": [dict(row) for row in rows],
    }
