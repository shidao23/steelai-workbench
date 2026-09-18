"""Run, audit and transaction-boundary ports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, Sequence, runtime_checkable

from ..domain.models import AuditEvent, WorkflowRun

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .artifacts import ArtifactStore
    from .events import EventPublisher
    from .jobs import JobQueue


@dataclass(frozen=True)
class RunFilters:
    """Selection criteria for ``RunRepository.list_runs``."""

    project_id: str | None = None
    task_id: str | None = None
    states: tuple[str, ...] = ()
    result_level: str | None = None

    def matches(self, run: WorkflowRun) -> bool:
        if self.project_id is not None and run.project_id != self.project_id:
            return False
        if self.task_id is not None and run.task_id != self.task_id:
            return False
        if self.states and run.state not in self.states:
            return False
        if self.result_level is not None and run.result_level != self.result_level:
            return False
        return True


@runtime_checkable
class RunRepository(Protocol):
    """Workflow-run persistence.

    Contract:

    - ``create_run`` is idempotent per ``idempotency_key``: the identical request
      (same ``request_digest`` and same ``run_id``) reuses the existing run
      (``reused=True``) and one key is never bound to two runs; the same key with
      different content, or the same content under a different explicit
      ``run_id``, fails closed with ``ENT-IDEMPOTENCY-001`` **before any write**;
    - ``get_run_by_idempotency_key`` returns the run already bound to a key, or
      ``None``; it is the read-only replay probe and never mutates anything;
    - ``get_run`` returns ``None`` for an unknown run;
    - ``update_run_state`` requires ``expected_revision`` and refuses the write
      when the stored revision moved (optimistic concurrency); on success it
      returns the new run with ``revision`` incremented.
    """

    def create_run(self, run: WorkflowRun, *, idempotency_key: str) -> tuple[WorkflowRun, bool]:
        ...

    def get_run(self, run_id: str) -> WorkflowRun | None:
        ...

    def get_run_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        ...

    def list_runs(self, filters: RunFilters | None = None) -> Sequence[WorkflowRun]:
        ...

    def update_run_state(
        self,
        run_id: str,
        *,
        expected_revision: int,
        state: str,
        updated_at: str,
        result_level: str | None = None,
        next_action: str | None = None,
    ) -> WorkflowRun:
        ...


@runtime_checkable
class AuditRepository(Protocol):
    """Append-only audit trail.

    There is deliberately no update and no delete operation. Re-appending an
    existing ``audit_id`` fails closed instead of overwriting.
    """

    def append(self, event: AuditEvent) -> AuditEvent:
        ...

    def list_events(self, run_id: str | None = None) -> Sequence[AuditEvent]:
        ...

    def count(self) -> int:
        ...


class UnitOfWork(Protocol):
    """An explicit commit/rollback boundary over the storage ports.

    T80 ships an in-memory implementation used for demonstration only. It is
    *not* a database transaction: it makes no claim about durability, isolation
    across processes or concurrent workers.
    """

    @property
    def runs(self) -> RunRepository:
        ...

    @property
    def audits(self) -> AuditRepository:
        ...

    @property
    def artifacts(self) -> "ArtifactStore":
        ...

    @property
    def events(self) -> "EventPublisher":
        ...

    @property
    def jobs(self) -> "JobQueue":
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        ...


__all__ = ["AuditRepository", "RunFilters", "RunRepository", "UnitOfWork"]
