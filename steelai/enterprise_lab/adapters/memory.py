"""Pure in-memory adapters for the Enterprise Lab ports (T80).

These adapters exist to prove the interfaces work without PostgreSQL, Kafka,
FastAPI, Redis, Docker or any other service. They are process-local and
non-durable by design.

Guarantees implemented here:

- ``MemoryStore.state`` is **always the committed state only**; a unit of work
  mutates a private working copy that no other reader can observe;
- repositories are bound to one unit of work and stop working with
  ``ENT-UOW-001`` the moment it closes, even for an already-held reference;
- only one unit of work may be open per store; a second one is refused instead
  of being allowed to observe uncommitted data;
- ``commit`` atomically replaces the committed state; ``rollback`` discards the
  working copy and leaves the committed state untouched;
- no repository file and no system temporary directory is read or written;
- idempotent creation (identical content reused, conflicting content refused);
- optimistic concurrency through ``expected_revision``;
- append-only audit records;
- ordered per-run event replay;
- illegal background-job transitions refused, with the job idempotency key bound
  to both a ``job_id`` and a request digest;
- path-safe artifact references only.
"""
from __future__ import annotations

import weakref
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..domain.models import (
    ALLOWED_JOB_TRANSITIONS,
    ERROR_ARTIFACT_CONFLICT,
    ERROR_AUDIT_APPEND_ONLY,
    ERROR_EVENT_ORDER,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_JOB_TRANSITION,
    ERROR_REVISION_CONFLICT,
    ERROR_STORE_NOT_ACTIVE,
    ERROR_UNKNOWN_RUN,
    ArtifactReference,
    AuditEvent,
    BackgroundJob,
    DomainError,
    DomainEvent,
    JobState,
    WorkflowRun,
    utc_now,
    validate_identifier,
)
from ..ports.repositories import RunFilters


def empty_state() -> dict[str, dict[str, Any]]:
    """A fresh, fully empty committed state."""
    return {
        "runs": {},
        "idempotency": {},
        "audits": {},
        "artifacts": {},
        "events": {},
        "jobs": {},
        "job_idempotency": {},
    }


@dataclass
class MemoryStore:
    """Holds the committed state and the single active unit of work.

    ``state`` is never a working copy: it is replaced, atomically and as a whole,
    only by ``MemoryUnitOfWork.commit``.

    ``_active_uow`` is a weak reference, so the store never keeps a finished or
    abandoned unit of work alive and never stays locked because of one.
    """

    state: dict[str, dict[str, Any]] = field(default_factory=empty_state)
    _active_uow: "weakref.ReferenceType[MemoryUnitOfWork] | None" = None

    def __post_init__(self) -> None:
        if not self.state:
            self.state = empty_state()

    @property
    def active_unit(self) -> "MemoryUnitOfWork | None":
        """The unit of work currently holding the single-writer guard, if any."""
        return self._active_uow() if self._active_uow is not None else None


class _ScopedRepository:
    """Shared plumbing: a repository belongs to exactly one unit of work.

    Every call re-checks that this unit of work is still the store's active one,
    so a reference captured before ``commit`` or ``rollback`` fails closed with
    ``ENT-UOW-001`` instead of reading a stale or discarded working copy.
    """

    def __init__(self, unit_of_work: "MemoryUnitOfWork") -> None:
        self._uow_ref = weakref.ref(unit_of_work)

    def _require_scope(self) -> "MemoryUnitOfWork":
        unit = self._uow_ref()
        if unit is None or not unit.is_open or unit._store.active_unit is not unit:
            raise DomainError(
                ERROR_STORE_NOT_ACTIVE,
                "this repository is no longer bound to an open unit of work",
            )
        return unit

    @property
    def _state(self) -> dict[str, dict[str, Any]]:
        return self._require_scope()._working


class MemoryRunRepository(_ScopedRepository):
    """In-memory :class:`~steelai.enterprise_lab.ports.repositories.RunRepository`."""

    def create_run(self, run: WorkflowRun, *, idempotency_key: str) -> tuple[WorkflowRun, bool]:
        # The unit-of-work lifecycle is checked first (``self._state`` fails closed
        # with ENT-UOW-001): a handle kept from a closed boundary reports that code
        # even when the arguments are also wrong.
        state = self._state
        validate_identifier(idempotency_key, "idempotency_key")
        # Identity is checked before any write: the argument and the run's own key must
        # agree, so a binding can never be recorded under two different keys.
        if idempotency_key != run.idempotency_key:
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "idempotency_key argument does not match the run's own idempotency key",
                details={"idempotency_key": idempotency_key, "run_id": run.run_id},
            )
        runs = state["runs"]
        bound = state["idempotency"].get(idempotency_key)
        if bound is not None:
            reused = (
                bound["digest"] == run.request_digest
                and bound["run_id"] == run.run_id
                and runs[bound["run_id"]].request_digest == run.request_digest
            )
            if reused:
                return runs[bound["run_id"]], True
            # Refused before any artifact, audit record or event is written.
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "idempotency key is already bound to a different run request",
                details={"idempotency_key": idempotency_key, "bound_run_id": bound["run_id"]},
            )
        if run.run_id in runs:
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "run_id already exists with a different idempotency key",
                details={"run_id": run.run_id},
            )
        runs[run.run_id] = run
        state["idempotency"][idempotency_key] = {"run_id": run.run_id, "digest": run.request_digest}
        return run, False

    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self._state["runs"].get(run_id)

    def get_run_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        bound = self._state["idempotency"].get(idempotency_key)
        if bound is None:
            return None
        return self._state["runs"].get(bound["run_id"])

    def list_runs(self, filters: RunFilters | None = None) -> Sequence[WorkflowRun]:
        runs = list(self._state["runs"].values())
        if filters is not None:
            runs = [run for run in runs if filters.matches(run)]
        return sorted(runs, key=lambda item: (item.created_at, item.run_id))

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
        runs = self._state["runs"]
        current = runs.get(run_id)
        if current is None:
            raise DomainError(ERROR_UNKNOWN_RUN, "unknown run", details={"run_id": run_id})
        if current.revision != expected_revision:
            raise DomainError(
                ERROR_REVISION_CONFLICT,
                "expected_revision does not match the stored revision",
                details={
                    "run_id": run_id,
                    "expected_revision": expected_revision,
                    "stored_revision": current.revision,
                },
            )
        updated = current.evolves_to(
            state=state,
            revision=current.revision + 1,
            updated_at=updated_at,
            result_level=result_level,
            next_action=next_action,
        )
        runs[run_id] = updated
        return updated


class MemoryAuditRepository(_ScopedRepository):
    """Append-only in-memory :class:`~steelai.enterprise_lab.ports.repositories.AuditRepository`."""

    def append(self, event: AuditEvent) -> AuditEvent:
        audits = self._state["audits"]
        if event.audit_id in audits:
            raise DomainError(
                ERROR_AUDIT_APPEND_ONLY,
                "audit records are append-only; this audit_id already exists",
                details={"audit_id": event.audit_id},
            )
        next_sequence = len(audits) + 1
        sequence = event.sequence if event.sequence else next_sequence
        if sequence != next_sequence:
            raise DomainError(
                ERROR_AUDIT_APPEND_ONLY,
                "audit sequence must follow the append order",
                details={"expected_sequence": next_sequence, "supplied_sequence": sequence},
            )
        audits[event.audit_id] = event
        return event

    def list_events(self, run_id: str | None = None) -> Sequence[AuditEvent]:
        events = sorted(self._state["audits"].values(), key=lambda item: item.sequence)
        if run_id is not None:
            events = [event for event in events if event.run_id == run_id]
        return events

    def count(self) -> int:
        return len(self._state["audits"])


def _artifact_fields(reference: ArtifactReference) -> tuple[str, ...]:
    """Every persisted field of an artifact reference, for an exact reuse decision."""
    return (
        reference.artifact_id,
        reference.relative_path,
        reference.sha256,
        reference.artifact_type,
        reference.artifact_version,
        reference.run_id,
        reference.created_at,
    )


class MemoryArtifactStore(_ScopedRepository):
    """Reference-only in-memory :class:`~steelai.enterprise_lab.ports.artifacts.ArtifactStore`."""
    def register(self, reference: ArtifactReference) -> tuple[ArtifactReference, bool]:
        artifacts = self._state["artifacts"]
        existing = artifacts.get(reference.artifact_id)
        if existing is not None:
            # Reuse only when every persisted field matches; a repeated artifact_id
            # with different content is a conflict, not a re-registration.
            if _artifact_fields(existing) == _artifact_fields(reference):
                return existing, True
            raise DomainError(
                ERROR_ARTIFACT_CONFLICT,
                "artifact_id is already registered with different content",
                details={"artifact_id": reference.artifact_id},
            )
        for stored in artifacts.values():
            if stored.relative_path == reference.relative_path:
                raise DomainError(
                    ERROR_ARTIFACT_CONFLICT,
                    "artifact path is already registered with different content",
                    details={"relative_path": reference.relative_path},
                )
        artifacts[reference.artifact_id] = reference
        return reference, False

    def get(self, artifact_id: str) -> ArtifactReference | None:
        return self._state["artifacts"].get(artifact_id)

    def list_for_run(self, run_id: str) -> Sequence[ArtifactReference]:
        return sorted(
            (item for item in self._state["artifacts"].values() if item.run_id == run_id),
            key=lambda item: item.relative_path,
        )

    def count(self) -> int:
        return len(self._state["artifacts"])


class MemoryEventPublisher(_ScopedRepository):
    """Ordered in-memory :class:`~steelai.enterprise_lab.ports.events.EventPublisher`."""

    def next_sequence(self, run_id: str) -> int:
        return len(self._state["events"].get(run_id, [])) + 1

    def publish(self, event: DomainEvent) -> DomainEvent:
        events = self._state["events"]
        recorded = events.setdefault(event.run_id, [])
        expected = len(recorded) + 1
        if event.sequence != expected:
            raise DomainError(
                ERROR_EVENT_ORDER,
                "domain events must be published in a contiguous creation order",
                details={"run_id": event.run_id, "expected_sequence": expected, "supplied": event.sequence},
            )
        if any(item.event_id == event.event_id for item in recorded):
            raise DomainError(
                ERROR_EVENT_ORDER,
                "domain events are append-only; this event_id already exists",
                details={"event_id": event.event_id},
            )
        recorded.append(event)
        return event

    def replay(self, run_id: str) -> Sequence[DomainEvent]:
        return tuple(self._state["events"].get(run_id, []))

    def count(self) -> int:
        return sum(len(items) for items in self._state["events"].values())


class MemoryJobQueue(_ScopedRepository):
    """State-machine-checked in-memory :class:`~steelai.enterprise_lab.ports.jobs.JobQueue`.

    Job identity is resolved through an idempotency index that binds one
    ``idempotency_key`` to exactly one ``job_id`` and one request digest. T80
    deliberately implements no worker loop and no concurrency control.
    """

    def enqueue(self, job: BackgroundJob) -> tuple[BackgroundJob, bool]:
        state = self._state
        jobs = state["jobs"]
        index = state["job_idempotency"]

        existing = jobs.get(job.job_id)
        if existing is not None:
            if existing.idempotency_key != job.idempotency_key:
                raise DomainError(
                    ERROR_IDEMPOTENCY_CONFLICT,
                    "job_id already exists with a different idempotency key",
                    details={"job_id": job.job_id},
                )
            bound = index.get(job.idempotency_key)
            if bound is not None and bound["request_digest"] == job.request_digest():
                return existing, True
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "job_id is already bound to a different request for this idempotency key",
                details={"job_id": job.job_id, "idempotency_key": job.idempotency_key},
            )

        bound = index.get(job.idempotency_key)
        if bound is not None:
            if bound["job_id"] == job.job_id and bound["request_digest"] == job.request_digest():
                return jobs[job.job_id], True
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "idempotency key is already bound to a different background job request",
                details={
                    "idempotency_key": job.idempotency_key,
                    "bound_job_id": bound["job_id"],
                },
            )

        jobs[job.job_id] = job
        index[job.idempotency_key] = {"job_id": job.job_id, "request_digest": job.request_digest()}
        return job, False

    def lease(self, *, job_type: str | None = None) -> BackgroundJob | None:
        jobs = self._state["jobs"]
        candidates = [
            job
            for job in jobs.values()
            if job.state in {JobState.QUEUED.value, JobState.RETRYING.value}
            and (job_type is None or job.job_type == job_type)
        ]
        if not candidates:
            return None
        selected = sorted(candidates, key=lambda item: (item.created_at, item.job_id))[0]
        leased = selected.transition(
            JobState.LEASED,
            updated_at=utc_now(),
            lease_id=f"lease_{selected.job_id[-12:]}",
        )
        jobs[selected.job_id] = leased
        return leased

    def _require(self, job_id: str) -> BackgroundJob:
        job = self._state["jobs"].get(job_id)
        if job is None:
            raise DomainError(ERROR_UNKNOWN_RUN, "unknown background job", details={"job_id": job_id})
        return job

    def _save(self, job: BackgroundJob) -> BackgroundJob:
        self._state["jobs"][job.job_id] = job
        return job

    def complete(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        job = self._require(job_id)
        return self._save(job.transition(JobState.SUCCEEDED, updated_at=updated_at or utc_now()))

    def fail(self, job_id: str, *, error_code: str, updated_at: str | None = None) -> BackgroundJob:
        job = self._require(job_id)
        return self._save(
            job.transition(JobState.FAILED, updated_at=updated_at or utc_now(), error_code=error_code)
        )

    def retry(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        job = self._require(job_id)
        if job.attempts >= job.max_attempts:
            raise DomainError(
                ERROR_JOB_TRANSITION,
                "background job exhausted its attempts and cannot be retried",
                details={"job_id": job_id, "attempts": job.attempts, "max_attempts": job.max_attempts},
            )
        return self._save(
            job.transition(JobState.RETRYING, updated_at=updated_at or utc_now(), count_attempt=True)
        )

    def cancel(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        job = self._require(job_id)
        return self._save(job.transition(JobState.CANCELLED, updated_at=updated_at or utc_now()))

    def get(self, job_id: str) -> BackgroundJob | None:
        return self._state["jobs"].get(job_id)

    def list_jobs(self) -> Sequence[BackgroundJob]:
        return sorted(self._state["jobs"].values(), key=lambda item: (item.created_at, item.job_id))


class MemoryUnitOfWork:
    """Single-writer unit of work used for demonstration only.

    The demonstrated guarantee is exact and narrow:

    - ``MemoryStore.state`` always holds the committed state, so a working copy
      staged here is invisible to every other reader until ``commit``;
    - ``commit`` replaces the committed state atomically (one assignment);
    - ``rollback`` discards the working copy and leaves the committed state
      byte-for-byte as it was;
    - only one unit of work may be open per store at a time; a second one is
      refused with ``ENT-UOW-001`` rather than being allowed to read uncommitted
      data. T80 therefore supports no overlapping or concurrent transactions;
    - after ``commit`` or ``rollback`` every repository of this unit of work
      refuses further use with ``ENT-UOW-001``.

    T80 does not claim database transaction semantics: there is no durability,
    no cross-process isolation, no rollback of external side effects and no
    concurrent-worker support.
    """

    def __init__(self, store: MemoryStore) -> None:
        guarded = store._active_uow
        active = guarded() if guarded is not None else None
        if active is not None and active.is_open:
            raise DomainError(
                ERROR_STORE_NOT_ACTIVE,
                "another unit of work is already open on this store; T80 does not support "
                "overlapping units of work",
            )
        if active is not None:
            # A closed or otherwise finished unit of work never keeps the store
            # locked for the next one.
            store._active_uow = None
        self._store = store
        self._working: dict[str, dict[str, Any]] = deepcopy(store.state)
        self._closed = False
        self._committed = False
        store._active_uow = weakref.ref(self)
        self._runs = MemoryRunRepository(self)
        self._audits = MemoryAuditRepository(self)
        self._artifacts = MemoryArtifactStore(self)
        self._events = MemoryEventPublisher(self)
        self._jobs = MemoryJobQueue(self)

    @property
    def is_open(self) -> bool:
        return not self._closed

    @property
    def committed(self) -> bool:
        """True once this unit of work committed, independently of later ones."""
        return self._committed

    @property
    def working_state(self) -> dict[str, dict[str, Any]]:
        """The private, uncommitted working state (introspection and tests only)."""
        self._require_open("inspect the working state")
        return self._working

    def _require_open(self, action: str) -> None:
        if self._closed:
            raise DomainError(ERROR_STORE_NOT_ACTIVE, f"unit of work is already closed; cannot {action}")

    def _release(self) -> None:
        guarded = self._store._active_uow
        if guarded is not None and guarded() is self:
            self._store._active_uow = None

    @property
    def runs(self) -> MemoryRunRepository:
        self._require_open("use run repository")
        return self._runs

    @property
    def audits(self) -> MemoryAuditRepository:
        self._require_open("use audit repository")
        return self._audits

    @property
    def artifacts(self) -> MemoryArtifactStore:
        self._require_open("use artifact store")
        return self._artifacts

    @property
    def events(self) -> MemoryEventPublisher:
        self._require_open("publish domain events")
        return self._events

    @property
    def jobs(self) -> MemoryJobQueue:
        self._require_open("use job queue")
        return self._jobs

    def commit(self) -> None:
        self._require_open("commit")
        self._closed = True
        self._committed = True
        # One atomic swap: the committed state becomes the working copy that was
        # built in private, and no reader ever observes a half-applied change.
        self._store.state = self._working
        self._release()

    def rollback(self) -> None:
        self._require_open("rollback")
        self._closed = True
        self._committed = False
        # The working copy is simply dropped; the committed state was never
        # touched, so no partial write can survive.
        self._release()

    def __enter__(self) -> "MemoryUnitOfWork":
        self._require_open("enter")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if not self._closed:
            self.rollback()
        return False

    def __del__(self) -> None:
        # Last-resort guard release: an abandoned unit of work must never leave
        # the store permanently locked. The weak reference in the store makes this
        # hook a safety net rather than a requirement.
        try:
            self._release()
        except Exception:  # pragma: no cover - never raise from a finalizer
            pass


class MemoryUnitOfWorkFactory:
    """Creates :class:`MemoryUnitOfWork` transactions over one shared store.

    There is no separate read-only session type: a read is a unit of work that is
    simply rolled back, which keeps a single explicit transaction boundary.
    """

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def unit_of_work(self) -> MemoryUnitOfWork:
        return MemoryUnitOfWork(self.store)


__all__ = [
    "MemoryArtifactStore",
    "MemoryAuditRepository",
    "MemoryEventPublisher",
    "MemoryJobQueue",
    "MemoryRunRepository",
    "MemoryStore",
    "MemoryUnitOfWork",
    "MemoryUnitOfWorkFactory",
    "empty_state",
]
