"""Artifact-reference port.

The store registers references only: a safe relative path, a SHA-256 digest, a
declared type and a version. It never carries artifact bytes and never writes to
the repository, the CSVs or the system temporary directory.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ..domain.models import ArtifactReference


@runtime_checkable
class ArtifactStore(Protocol):
    """Append-only artifact reference registry.

    Contract:

    - ``register`` refuses an absolute path, a traversal path, an empty digest, a
      malformed digest or a path already bound to a different digest;
    - registering the identical reference again is idempotent and returns
      ``reused=True``;
    - nothing here reads or writes artifact content.
    """

    def register(self, reference: ArtifactReference) -> tuple[ArtifactReference, bool]:
        ...

    def get(self, artifact_id: str) -> ArtifactReference | None:
        ...

    def list_for_run(self, run_id: str) -> Sequence[ArtifactReference]:
        ...

    def count(self) -> int:
        ...


__all__ = ["ArtifactStore"]
