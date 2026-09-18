"""Append-only, same-filesystem atomic publication with idempotent reuse."""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from .errors import GovernanceError
from .manifest import load_verified_manifest, verify_package
from .models import GovernanceState, PublicationResult


def _safe_publication_id(publication_id: str) -> str:
    if (
        not publication_id
        or len(publication_id) > 160
        or publication_id in {".", ".."}
        or any(char in publication_id for char in ("/", "\\", "\r", "\n", "\t", "<", ">", ":", '"', "|", "?", "*"))
    ):
        raise ValueError("publication_id must be a safe directory identifier")
    return publication_id


def create_staging_directory(output_root: str | Path, publication_id: str) -> Path:
    requested_root = Path(output_root)
    if requested_root.is_symlink():
        raise GovernanceError("GOV-WRITE-001", "blocked", "output root must not be a symbolic link")
    root = requested_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_publication_id(publication_id)
    staging = root / f".tmp-{safe_id}-{uuid.uuid4().hex}"
    staging.mkdir()
    return staging


def _validate_layout(staging: Path, destination: Path) -> None:
    if not staging.is_dir():
        raise GovernanceError("GOV-WRITE-001", "blocked", "staging directory does not exist")
    if staging.parent.resolve() != destination.parent.resolve():
        raise GovernanceError("GOV-WRITE-001", "blocked", "staging and destination must share one parent")
    expected_prefix = f".tmp-{destination.name}-"
    if not staging.name.startswith(expected_prefix) or destination.name in {"", ".", ".."}:
        raise GovernanceError("GOV-WRITE-001", "blocked", "staging directory is outside the governed pattern")
    if staging.is_symlink() or destination.is_symlink():
        raise GovernanceError("GOV-WRITE-001", "blocked", "symbolic-link publication targets are prohibited")


def _remove_verified_staging(staging: Path, destination: Path) -> None:
    _validate_layout(staging, destination)
    shutil.rmtree(staging)


def publish_append_only(staging: str | Path, destination: str | Path) -> PublicationResult:
    stage = Path(staging).absolute()
    target = Path(destination).absolute()
    _validate_layout(stage, target)
    stage_verification = verify_package(stage)
    if stage_verification.status != "passed":
        raise GovernanceError(
            "GOV-INTEGRITY-001",
            GovernanceState.BLOCKED.value,
            "staging package failed integrity verification",
            details={"problems": list(stage_verification.problems)},
        )
    staged_manifest = load_verified_manifest(stage)
    if staged_manifest.publication_id != target.name:
        raise GovernanceError("GOV-WRITE-001", "blocked", "destination name must match publication_id")

    if target.exists():
        existing_verification = verify_package(target)
        if existing_verification.status != "passed":
            raise GovernanceError(
                "GOV-INTEGRITY-001",
                GovernanceState.BLOCKED.value,
                "existing destination is invalidated and will not be overwritten",
                details={"problems": list(existing_verification.problems)},
            )
        existing = load_verified_manifest(target)
        if existing.publication_fingerprint != staged_manifest.publication_fingerprint:
            raise GovernanceError(
                "GOV-DUPLICATE-001",
                GovernanceState.BLOCKED.value,
                "publication identity already exists with different governed content",
            )
        _remove_verified_staging(stage, target)
        return PublicationResult(
            GovernanceState.COMPLETE.value,
            existing.publication_id,
            str(target),
            True,
            existing_verification.manifest_digest or "",
        )

    for attempt in range(5):
        try:
            stage.rename(target)
            break
        except PermissionError:
            if attempt == 4 or target.exists():
                raise
            time.sleep(0.1 * (attempt + 1))
        except FileExistsError:
            return publish_append_only(stage, target)
    final = verify_package(target)
    if final.status != "passed":
        raise GovernanceError(
            "GOV-INTEGRITY-001",
            GovernanceState.INVALIDATED.value,
            "published package failed post-switch integrity verification",
            details={"problems": list(final.problems)},
        )
    return PublicationResult(
        GovernanceState.COMPLETE.value,
        staged_manifest.publication_id,
        str(target),
        False,
        final.manifest_digest or "",
    )
