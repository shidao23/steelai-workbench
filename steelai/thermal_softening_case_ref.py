"""Restricted read-only reference to a governed double-hit softening case.

PAOS-004B1 / PAOS-004B1R / PAOS-004B1R2: this module exposes only case identity, package verification
status, the verified governance-manifest digest, the review state and non-sensitive counts.

It exists so a later platform mapping step (PAOS-004B2) can cite a case by identity without touching
raw research rows, literature text, local paths or the analysis draft.

Boundaries this module deliberately keeps:

* It is read-only. It never rebuilds T71/T74/T75, never creates or modifies a package, never writes a
  task record, never calls a model and never satisfies a human gate.
* A returned reference means "the package's governance integrity was verified just now". It does NOT
  mean the research conclusion is approved. The review gate stays open for the caller.
* There is exactly one production package root: the project's own ``CASE_ROOT``. No environment
  variable and no public command-line option can redirect it, and every refusal is a stable,
  path-free code so a failure can never echo a local filesystem location.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from steelai.governance import GovernanceState, load_verified_manifest, verify_package
from steelai.thermal_softening_case import CASE_ROOT, _CASE_ID, load_softening_case

#: Stable, path-free refusal codes. These are the only failure detail a caller may rely on.
REFUSAL_CODES = {
    "CASE_ID_INVALID": "case ID must match TSC- followed by 20 upper-case hex characters",
    "CASE_PACKAGE_MISSING": "no governed case package exists for the requested case ID",
    "CASE_EVIDENCE_UNAVAILABLE": "the case package's curated evidence cannot be read",
    "CASE_PACKAGE_INVALIDATED": "the case package did not pass governance integrity verification",
    "CASE_IDENTITY_MISMATCH": "the package identity, or the evidence identity inside it, is not the requested case ID",
    "CASE_REVIEW_STATE_NOT_NEEDS_HUMAN": "the case package is not the open needs_human review candidate",
    "CASE_NOT_REAL_RESEARCH": "the verified package is not classified as real research data, so it cannot be cited as a research case",
    "CASE_REFERENCE_INTERNAL_ERROR": "the case reference could not be produced",
}
#: Argument-parsing refusals. The offending input is never echoed.
PARSER_REFUSAL_CODES = {
    "CASE_ARGUMENT_UNKNOWN": "unknown command-line argument",
    "CASE_ARGUMENT_INVALID": "the command line is not a single case ID",
}


class CaseReferenceError(Exception):
    """Base refusal. Carries a stable code and a code-derived message only - never a path."""

    code = "CASE_REFERENCE_INTERNAL_ERROR"

    def __init__(self) -> None:
        self.message = REFUSAL_CODES[self.code]
        super().__init__(self.message)


class InvalidCaseIdError(CaseReferenceError):
    code = "CASE_ID_INVALID"


class PackageMissingError(CaseReferenceError):
    code = "CASE_PACKAGE_MISSING"


class EvidenceUnavailableError(CaseReferenceError):
    code = "CASE_EVIDENCE_UNAVAILABLE"


class PackageVerificationError(CaseReferenceError):
    code = "CASE_PACKAGE_INVALIDATED"


class IdentityMismatchError(CaseReferenceError):
    code = "CASE_IDENTITY_MISMATCH"


class ReviewStateError(CaseReferenceError):
    code = "CASE_REVIEW_STATE_NOT_NEEDS_HUMAN"


class NotRealResearchError(CaseReferenceError):
    code = "CASE_NOT_REAL_RESEARCH"


def resolve_case_root() -> Path:
    """The one production package root.

    Deliberately takes no input: the CLI must not be able to read an arbitrary directory, so no
    environment variable and no command-line option is consulted here.
    """
    return CASE_ROOT


def _case_directory(case_id: str, case_root: Path) -> Path:
    if not _CASE_ID.fullmatch(case_id):
        raise InvalidCaseIdError()
    directory = Path(case_root) / case_id
    # A pattern-validated ID cannot traverse, but never hand a caller-controlled path to the core.
    if directory.parent.resolve() != Path(case_root).resolve():
        raise InvalidCaseIdError()
    return directory


def build_case_reference(case_id: str, *, package_root: Path | None = None) -> dict[str, Any]:
    """Return the restricted read-only reference for one governed case.

    ``package_root`` exists solely so tests can point at a synthetic package root. It is never
    surfaced as a command-line option, and the result never echoes it.
    """
    if not isinstance(case_id, str):
        raise InvalidCaseIdError()
    root = Path(package_root) if package_root is not None else resolve_case_root()
    directory = _case_directory(case_id, root)

    if not directory.is_dir():
        raise PackageMissingError()

    verification = verify_package(directory)
    if verification.status != "passed":
        # The governance problems may quote filesystem error text, so they are never forwarded.
        raise PackageVerificationError()
    if verification.publication_id != case_id:
        raise IdentityMismatchError()

    # The evidence classification is read from the VERIFIED manifest itself - never from anything
    # the evidence body or a caller declares. This channel cites REAL research cases only; a
    # synthetic-demo package (whatever its internal consistency) is refused with a stable code.
    try:
        manifest = load_verified_manifest(directory)
    except (OSError, ValueError):
        raise PackageVerificationError() from None
    if manifest.evidence_class != "real_research_data":
        raise NotRealResearchError()

    # Reuse the project's own evidence reader: it re-verifies the package, requires the manifest to be
    # the needs_human candidate, and cross-checks the evidence identity against the manifest.
    try:
        evidence = load_softening_case(case_id, output_root=root)
    except ValueError as exc:
        detail = str(exc)
        if "case evidence identity differs from manifest" in detail:
            raise IdentityMismatchError() from None
        if "case manifest is not the expected review candidate" in detail:
            raise ReviewStateError() from None
        if "invalid case ID" in detail:
            raise InvalidCaseIdError() from None
        raise PackageVerificationError() from None
    except OSError:
        raise EvidenceUnavailableError() from None

    if not isinstance(evidence, dict):
        raise EvidenceUnavailableError()
    if evidence.get("case_id") != case_id:
        raise IdentityMismatchError()

    rows = evidence.get("rows")
    row_count = len(rows) if isinstance(rows, list) else 0

    return {
        "case_id": case_id,
        "package_verification": verification.status,
        "manifest_digest": verification.manifest_digest,
        "review_state": GovernanceState.NEEDS_HUMAN.value,
        # Non-sensitive counts only: how many curated rows the case carries and how many artifacts the
        # verified manifest declares. No values, no paths, no row content.
        "row_count": row_count,
        "artifact_count": verification.artifact_count,
    }
