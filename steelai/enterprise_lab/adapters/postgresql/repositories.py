"""PostgreSQL persistence adapter for the Enterprise Lab (T82).

Implements the frozen T80 ports on top of the T81 schema using SQLAlchemy Core and
synchronous Psycopg 3 - no ORM, no ``Session``, no global engine. One unit of work
owns one connection and one transaction, so a run, its artifact references, its
audit records, its outbox events and its job rows commit atomically.

Scope (see ``docs/enterprise/T82_POSTGRESQL_REPOSITORIES.md``): the write side of
the repositories and the transactional outbox. There is no dispatcher, no Kafka, no
worker loop, no API and no default-application wiring.
"""
from __future__ import annotations

import weakref
from typing import Any, Mapping, Sequence

from sqlalchemy import Connection, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from steelai.enterprise_lab.domain.models import (
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
)
from steelai.enterprise_lab.ports.repositories import RunFilters

from ._context import PostgreSQLContext
from ._locks import audit_sequence_lock_key, event_sequence_lock_key
from .errors import ERROR_DATABASE, map_database_error
from .hydration import (
    hydrate_artifact_reference,
    hydrate_audit_event,
    hydrate_background_job,
    hydrate_domain_event,
    hydrate_workflow_run,
)
from .mapping import (
    artifact_reference_row,
    audit_event_row,
    background_job_row,
    outbox_event_row,
    workflow_run_row,
)
from .schema import artifact_references, audit_events, background_jobs, outbox_events, workflow_runs


def _artifact_fields(reference: ArtifactReference) -> tuple[str, ...]:
    """Every persisted field of an artifact reference, for an exact reuse decision.

    ``created_at`` is included: two references that differ only in creation time are
    still different persisted rows and must not be treated as the same registration.
    """
    return (
        reference.artifact_id,
        reference.relative_path,
        reference.sha256,
        reference.artifact_type,
        reference.artifact_version,
        reference.run_id,
        reference.created_at,
    )


def _acquire(owner: Any, action: str) -> PostgreSQLContext:
    """Resolve the transaction context of a repository, failing closed when closed."""
    context = owner._context
    context.require_active(action)
    return context


class _PostgreSQLRepository:
    """Base class for the five repositories: every call re-checks the transaction."""

    def __init__(self, unit_of_work: "PostgreSQLUnitOfWork") -> None:
        self._uow_ref = weakref.ref(unit_of_work)

    @property
    def _context(self) -> PostgreSQLContext:
        unit = self._uow_ref()
        if unit is None:
            raise DomainError(
                ERROR_STORE_NOT_ACTIVE,
                "this repository is no longer bound to an open unit of work",
            )
        return unit._context

    def _connection(self, action: str) -> Connection:
        return self._context.connection_for_call(action)


class PostgreSQLRunRepository(_PostgreSQLRepository):
    """``RunRepository`` on ``workflow_runs``."""

    def create_run(self, run: WorkflowRun, *, idempotency_key: str) -> tuple[WorkflowRun, bool]:
        # The unit-of-work lifecycle is checked first: a handle kept from a closed
        # boundary reports ENT-UOW-001 even when the arguments are also wrong.
        connection = self._connection("create a workflow run")
        # Identity is then checked before any SQL: the caller-supplied key must be the
        # key the run itself carries, otherwise the binding is ambiguous.
        if idempotency_key != run.idempotency_key:
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "idempotency_key argument does not match the run's own idempotency key",
                details={"idempotency_key": idempotency_key, "run_id": run.run_id},
            )
        try:
            # The binding is never decided by "select then insert": the insert itself
            # is conflict-free and the decision is made from what the database stored.
            bound = self._select_by_key(connection, idempotency_key)
            if bound is not None:
                if bound.request_digest == run.request_digest and bound.run_id == run.run_id:
                    return bound, True
                raise DomainError(
                    ERROR_IDEMPOTENCY_CONFLICT,
                    "idempotency key is already bound to a different run request",
                    details={"idempotency_key": idempotency_key, "bound_run_id": bound.run_id},
                )
            # ``INSERT ... ON CONFLICT DO NOTHING RETURNING`` is authoritative here:
            # psycopg reports ``rowcount == -1`` for this statement shape, so the
            # presence of a returned row is what decides whether we inserted.
            inserted_row = (
                connection.execute(
                    insert(workflow_runs)
                    .on_conflict_do_nothing(index_elements=["run_id"])
                    .values(**workflow_run_row(run))
                    .returning(*workflow_runs.c)
                )
                .mappings()
                .first()
            )
            if inserted_row is not None:
                return hydrate_workflow_run(inserted_row), False
            stored = self._select_by_run_id(connection, run.run_id)
            if stored is None:  # pragma: no cover - the conflicting row must exist
                raise DomainError(ERROR_UNKNOWN_RUN, "unknown run", details={"run_id": run.run_id})
            # A concurrent transaction inserted this run_id or this idempotency key.
            if (
                stored.request_digest == run.request_digest
                and stored.run_id == run.run_id
                and stored.idempotency_key == idempotency_key
            ):
                return stored, True
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "idempotency key is already bound to a different run request",
                details={"idempotency_key": idempotency_key, "bound_run_id": stored.run_id},
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001 - classify by SQLSTATE
            raise map_database_error(exc) from None

    def get_run(self, run_id: str) -> WorkflowRun | None:
        connection = self._connection("read a workflow run")
        try:
            return self._select_by_run_id(connection, run_id)
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def get_run_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        connection = self._connection("read a workflow run by idempotency key")
        try:
            return self._select_by_key(connection, idempotency_key)
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def list_runs(self, filters: RunFilters | None = None) -> Sequence[WorkflowRun]:
        connection = self._connection("list workflow runs")
        statement = select(workflow_runs)
        if filters is not None:
            if filters.project_id is not None:
                statement = statement.where(workflow_runs.c.project_id == filters.project_id)
            if filters.task_id is not None:
                statement = statement.where(workflow_runs.c.task_id == filters.task_id)
            if filters.states:
                statement = statement.where(workflow_runs.c.state.in_(list(filters.states)))
            if filters.result_level is not None:
                statement = statement.where(workflow_runs.c.result_level == filters.result_level)
        statement = statement.order_by(workflow_runs.c.created_at, workflow_runs.c.run_id)
        try:
            rows = connection.execute(statement).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return [hydrate_workflow_run(row) for row in rows]

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
        connection = self._connection("update a workflow run state")
        current = self._select_by_run_id(connection, run_id)
        if current is None:
            raise DomainError(ERROR_UNKNOWN_RUN, "unknown run", details={"run_id": run_id})
        # A stored revision that already moved is a concurrency conflict, not a
        # missing run: report it before issuing the guarded UPDATE.
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
        row = workflow_run_row(updated)
        row.pop("run_id")
        try:
            # Guarded UPDATE ... WHERE run_id AND revision: no lost update is possible.
            result = connection.execute(
                update(workflow_runs)
                .where(
                    workflow_runs.c.run_id == run_id,
                    workflow_runs.c.revision == expected_revision,
                )
                .values(**row)
                .returning(*workflow_runs.c)
            )
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        stored = result.mappings().first()
        if stored is None:
            # The revision moved between the read and the guarded write.
            raise DomainError(
                ERROR_REVISION_CONFLICT,
                "expected_revision does not match the stored revision",
                details={"run_id": run_id, "expected_revision": expected_revision},
            )
        return hydrate_workflow_run(stored)

    # -- internals -------------------------------------------------------------
    def _select_by_run_id(self, connection: Connection, run_id: str) -> WorkflowRun | None:
        row = (
            connection.execute(select(workflow_runs).where(workflow_runs.c.run_id == run_id))
            .mappings()
            .first()
        )
        return hydrate_workflow_run(row) if row is not None else None

    def _select_by_key(self, connection: Connection, idempotency_key: str) -> WorkflowRun | None:
        row = (
            connection.execute(
                select(workflow_runs).where(workflow_runs.c.idempotency_key == idempotency_key)
            )
            .mappings()
            .first()
        )
        return hydrate_workflow_run(row) if row is not None else None


class PostgreSQLArtifactStore(_PostgreSQLRepository):
    """``ArtifactStore`` on ``artifact_references``: references and digests only."""

    def register(self, reference: ArtifactReference) -> tuple[ArtifactReference, bool]:
        connection = self._connection("register an artifact reference")
        try:
            existing = self._select_by_id(connection, reference.artifact_id)
            if existing is not None:
                # Reuse only when every persisted field matches; a derived id that
                # happens to repeat with different content is a conflict.
                if _artifact_fields(existing) == _artifact_fields(reference):
                    return existing, True
                raise DomainError(
                    ERROR_ARTIFACT_CONFLICT,
                    "artifact_id is already registered with different content",
                    details={"artifact_id": reference.artifact_id},
                )
            by_path = self._select_by_path(connection, reference.relative_path)
            if by_path is not None:
                raise DomainError(
                    ERROR_ARTIFACT_CONFLICT,
                    "artifact path is already registered with different content",
                    details={"relative_path": reference.relative_path},
                )
            inserted_row = (
                connection.execute(
                    insert(artifact_references)
                    .on_conflict_do_nothing(index_elements=["artifact_id"])
                    .values(**artifact_reference_row(reference))
                    .returning(*artifact_references.c)
                )
                .mappings()
                .first()
            )
            if inserted_row is not None:
                return hydrate_artifact_reference(inserted_row), False
            stored = self._select_by_id(connection, reference.artifact_id)
            if stored is not None:
                if _artifact_fields(stored) == _artifact_fields(reference):
                    return stored, True
                raise DomainError(
                    ERROR_ARTIFACT_CONFLICT,
                    "artifact_id is already registered with different content",
                    details={"artifact_id": reference.artifact_id},
                )
            raise DomainError(
                ERROR_ARTIFACT_CONFLICT,
                "artifact path is already registered with different content",
                details={"relative_path": reference.relative_path},
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def get(self, artifact_id: str) -> ArtifactReference | None:
        connection = self._connection("read an artifact reference")
        try:
            return self._select_by_id(connection, artifact_id)
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def list_for_run(self, run_id: str) -> Sequence[ArtifactReference]:
        connection = self._connection("list artifact references for a run")
        try:
            rows = (
                connection.execute(
                    select(artifact_references)
                    .where(artifact_references.c.run_id == run_id)
                    .order_by(artifact_references.c.relative_path)
                )
                .mappings()
                .all()
            )
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return [hydrate_artifact_reference(row) for row in rows]

    def count(self) -> int:
        connection = self._connection("count artifact references")
        try:
            return int(connection.execute(select(text("count(*)")).select_from(artifact_references)).scalar_one())
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def _select_by_id(self, connection: Connection, artifact_id: str) -> ArtifactReference | None:
        row = (
            connection.execute(
                select(artifact_references).where(artifact_references.c.artifact_id == artifact_id)
            )
            .mappings()
            .first()
        )
        return hydrate_artifact_reference(row) if row is not None else None

    def _select_by_path(self, connection: Connection, relative_path: str) -> ArtifactReference | None:
        row = (
            connection.execute(
                select(artifact_references).where(
                    artifact_references.c.relative_path == relative_path
                )
            )
            .mappings()
            .first()
        )
        return hydrate_artifact_reference(row) if row is not None else None


class PostgreSQLAuditRepository(_PostgreSQLRepository):
    """Append-only ``AuditRepository`` on ``audit_events``.

    There is no update and no delete. The append order is global, so **both**
    ``count()`` and ``append()`` take the same transaction-level advisory lock
    *before* reading the current maximum. Two concurrent transactions that each do
    ``count() + 1`` therefore serialize on the lock and both succeed with sequences
    1 and 2 - neither has to retry. The database trigger stays the final protection.
    """

    def append(self, event: AuditEvent) -> AuditEvent:
        connection = self._connection("append an audit event")
        self._context.acquire_advisory_lock(audit_sequence_lock_key())
        expected = self._next_sequence(connection)
        if event.sequence != expected:
            raise DomainError(
                ERROR_AUDIT_APPEND_ONLY,
                "audit sequence must follow the append order",
                details={"expected_sequence": expected, "supplied_sequence": event.sequence},
            )
        try:
            connection.execute(insert(audit_events).values(**audit_event_row(event)))
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return event

    def list_events(self, run_id: str | None = None) -> Sequence[AuditEvent]:
        connection = self._connection("list audit events")
        statement = select(audit_events)
        if run_id is not None:
            statement = statement.where(audit_events.c.run_id == run_id)
        statement = statement.order_by(audit_events.c.sequence)
        try:
            rows = connection.execute(statement).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return [hydrate_audit_event(row) for row in rows]

    def count(self) -> int:
        connection = self._connection("count audit events")
        # The same lock as ``append``: a caller that computes ``count() + 1`` and then
        # appends holds the lock across both calls, so its sequence is still valid.
        self._context.acquire_advisory_lock(audit_sequence_lock_key())
        try:
            return int(connection.execute(select(text("count(*)")).select_from(audit_events)).scalar_one())
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def _next_sequence(self, connection: Connection) -> int:
        # MAX(sequence) + 1 is only safe together with the advisory lock taken by the
        # caller, which serializes this allocation across concurrent transactions.
        current = connection.execute(select(text("coalesce(max(sequence), 0)")).select_from(audit_events)).scalar_one()
        return int(current) + 1


class PostgreSQLEventPublisher(_PostgreSQLRepository):
    """``EventPublisher`` implemented as a transactional outbox.

    ``publish`` only inserts a ``pending`` row in the caller's transaction. Nothing is
    sent anywhere: there is no dispatcher, no Kafka client and no exactly-once claim.

    ``next_sequence`` takes the per-run advisory lock *before* reading the current
    maximum, so two concurrent transactions that each do ``next_sequence`` then
    ``publish`` serialize and both succeed with sequences 1 and 2.
    """

    def next_sequence(self, run_id: str) -> int:
        connection = self._connection("read the next outbox sequence")
        self._context.acquire_advisory_lock(event_sequence_lock_key(run_id))
        return self._next_sequence(connection, run_id)

    def publish(self, event: DomainEvent) -> DomainEvent:
        connection = self._connection("publish a domain event")
        # The same per-run lock as ``next_sequence``: a caller that reads the next
        # sequence and then publishes holds the lock across both calls.
        self._context.acquire_advisory_lock(event_sequence_lock_key(event.run_id))
        expected = self._next_sequence(connection, event.run_id)
        if event.sequence != expected:
            raise DomainError(
                ERROR_EVENT_ORDER,
                "domain events must be published in a contiguous creation order",
                details={
                    "run_id": event.run_id,
                    "expected_sequence": expected,
                    "supplied": event.sequence,
                },
            )
        try:
            connection.execute(insert(outbox_events).values(**outbox_event_row(event)))
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return event

    def replay(self, run_id: str) -> Sequence[DomainEvent]:
        connection = self._connection("replay outbox events")
        try:
            rows = (
                connection.execute(
                    select(outbox_events)
                    .where(outbox_events.c.run_id == run_id)
                    .order_by(outbox_events.c.sequence)
                )
                .mappings()
                .all()
            )
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return [hydrate_domain_event(row) for row in rows]

    def count(self) -> int:
        connection = self._connection("count outbox events")
        try:
            return int(connection.execute(select(text("count(*)")).select_from(outbox_events)).scalar_one())
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def _next_sequence(self, connection: Connection, run_id: str) -> int:
        current = connection.execute(
            select(text("coalesce(max(sequence), 0)"))
            .select_from(outbox_events)
            .where(outbox_events.c.run_id == run_id)
        ).scalar_one()
        return int(current) + 1


class PostgreSQLJobQueue(_PostgreSQLRepository):
    """``JobQueue`` on ``background_jobs``: lease records and state transitions only.

    No worker loop, no heartbeat, no lease timeout reaper and no scheduler: ``lease``
    just hands out a queued row with ``FOR UPDATE SKIP LOCKED``.
    """

    def enqueue(self, job: BackgroundJob) -> tuple[BackgroundJob, bool]:
        connection = self._connection("enqueue a background job")
        try:
            stored_by_id = self._select_by_id(connection, job.job_id)
            if stored_by_id is not None:
                if stored_by_id.idempotency_key != job.idempotency_key:
                    raise DomainError(
                        ERROR_IDEMPOTENCY_CONFLICT,
                        "job_id already exists with a different idempotency key",
                        details={"job_id": job.job_id},
                    )
                if stored_by_id.request_digest() == job.request_digest():
                    return stored_by_id, True
                raise DomainError(
                    ERROR_IDEMPOTENCY_CONFLICT,
                    "job_id is already bound to a different request for this idempotency key",
                    details={"job_id": job.job_id, "idempotency_key": job.idempotency_key},
                )
            stored_by_key = self._select_by_key(connection, job.idempotency_key)
            if stored_by_key is not None:
                if (
                    stored_by_key.job_id == job.job_id
                    and stored_by_key.request_digest() == job.request_digest()
                ):
                    return stored_by_key, True
                raise DomainError(
                    ERROR_IDEMPOTENCY_CONFLICT,
                    "idempotency key is already bound to a different background job request",
                    details={
                        "idempotency_key": job.idempotency_key,
                        "bound_job_id": stored_by_key.job_id,
                    },
                )
            inserted_row = (
                connection.execute(
                    insert(background_jobs)
                    .on_conflict_do_nothing(index_elements=["job_id"])
                    .values(**background_job_row(job))
                    .returning(*background_jobs.c)
                )
                .mappings()
                .first()
            )
            if inserted_row is not None:
                return hydrate_background_job(inserted_row), False
            stored = self._select_by_id(connection, job.job_id)
            if stored is not None and stored.request_digest() == job.request_digest():
                return stored, True
            raise DomainError(
                ERROR_IDEMPOTENCY_CONFLICT,
                "idempotency key is already bound to a different background job request",
                details={"job_id": job.job_id, "idempotency_key": job.idempotency_key},
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def lease(self, *, job_type: str | None = None) -> BackgroundJob | None:
        """Hand out one queued or retrying job to the caller's transaction.

        Only ``FOR UPDATE SKIP LOCKED`` is used. No advisory lock is taken, so two
        overlapping transactions lease two *different* rows instead of serializing on
        a global lock; when only one row is available the second transaction skips it
        and immediately receives ``None``.
        """
        connection = self._connection("lease a background job")
        statement = (
            select(background_jobs)
            .where(background_jobs.c.state.in_([JobState.QUEUED.value, JobState.RETRYING.value]))
            .order_by(background_jobs.c.created_at, background_jobs.c.job_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job_type is not None:
            statement = statement.where(background_jobs.c.job_type == job_type)
        try:
            row = connection.execute(statement).mappings().first()
            if row is None:
                return None
            selected = hydrate_background_job(row)
            leased = selected.transition(
                JobState.LEASED,
                updated_at=utc_now(),
                lease_id=f"lease_{selected.job_id[-12:]}",
            )
            updated_row = background_job_row(leased)
            updated_row.pop("job_id")
            stored = (
                connection.execute(
                    update(background_jobs)
                    .where(background_jobs.c.job_id == selected.job_id)
                    .values(**updated_row)
                    .returning(*background_jobs.c)
                )
                .mappings()
                .first()
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return hydrate_background_job(stored) if stored is not None else None

    def complete(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        return self._transition(job_id, JobState.SUCCEEDED, updated_at=updated_at)

    def fail(self, job_id: str, *, error_code: str, updated_at: str | None = None) -> BackgroundJob:
        return self._transition(job_id, JobState.FAILED, updated_at=updated_at, error_code=error_code)

    def retry(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        # The attempts limit is evaluated inside ``_transition`` on the row-locked
        # object, so there is no separate pre-check outside the lock.
        return self._transition(job_id, JobState.RETRYING, updated_at=updated_at, count_attempt=True)

    def cancel(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        return self._transition(job_id, JobState.CANCELLED, updated_at=updated_at)

    def get(self, job_id: str) -> BackgroundJob | None:
        try:
            return self._select_by_id(self._connection("read a background job"), job_id)
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None

    def list_jobs(self) -> Sequence[BackgroundJob]:
        connection = self._connection("list background jobs")
        try:
            rows = (
                connection.execute(
                    select(background_jobs).order_by(
                        background_jobs.c.created_at, background_jobs.c.job_id
                    )
                )
                .mappings()
                .all()
            )
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        return [hydrate_background_job(row) for row in rows]

    # -- internals -------------------------------------------------------------
    def _lock_row(self, connection: Connection, job_id: str) -> BackgroundJob | None:
        """Read the target row under ``FOR UPDATE`` so the transition sees current state."""
        row = (
            connection.execute(
                select(background_jobs)
                .where(background_jobs.c.job_id == job_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        return hydrate_background_job(row) if row is not None else None

    def _transition(
        self,
        job_id: str,
        target: JobState,
        *,
        updated_at: str | None = None,
        error_code: str | None = None,
        count_attempt: bool = False,
    ) -> BackgroundJob:
        """Lock the row, then apply the frozen state machine to the locked object.

        Locking first is what makes concurrent ``complete`` / ``fail`` / ``retry`` /
        ``cancel`` on the same job safe: the second transaction waits for the lock,
        reads the *latest* state and then fails closed with ``ENT-JOB-001`` instead of
        overwriting the winner's outcome.
        """
        connection = self._connection("update a background job")
        try:
            current = self._lock_row(connection, job_id)
            if current is None:
                raise DomainError(ERROR_UNKNOWN_RUN, "unknown background job", details={"job_id": job_id})
            if count_attempt and current.attempts >= current.max_attempts:
                raise DomainError(
                    ERROR_JOB_TRANSITION,
                    "background job exhausted its attempts and cannot be retried",
                    details={
                        "job_id": job_id,
                        "attempts": current.attempts,
                        "max_attempts": current.max_attempts,
                    },
                )
            # The frozen T80 state machine decides legality; no second state machine here.
            transitioned = current.transition(
                target,
                updated_at=updated_at or utc_now(),
                error_code=error_code,
                count_attempt=count_attempt,
            )
            row = background_job_row(transitioned)
            row.pop("job_id")
            stored = (
                connection.execute(
                    update(background_jobs)
                    .where(background_jobs.c.job_id == job_id)
                    .values(**row)
                    .returning(*background_jobs.c)
                )
                .mappings()
                .first()
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_database_error(exc) from None
        if stored is None:  # pragma: no cover - the row was locked a moment ago
            raise DomainError(ERROR_UNKNOWN_RUN, "unknown background job", details={"job_id": job_id})
        return hydrate_background_job(stored)

    def _select_by_id(self, connection: Connection, job_id: str) -> BackgroundJob | None:
        row = (
            connection.execute(select(background_jobs).where(background_jobs.c.job_id == job_id))
            .mappings()
            .first()
        )
        return hydrate_background_job(row) if row is not None else None

    def _select_by_key(self, connection: Connection, idempotency_key: str) -> BackgroundJob | None:
        row = (
            connection.execute(
                select(background_jobs).where(background_jobs.c.idempotency_key == idempotency_key)
            )
            .mappings()
            .first()
        )
        return hydrate_background_job(row) if row is not None else None


class PostgreSQLUnitOfWork:
    """One connection, one transaction, five repositories bound to that transaction."""

    def __init__(self, engine: Engine) -> None:
        self._context = PostgreSQLContext(engine)
        self._runs = PostgreSQLRunRepository(self)
        self._audits = PostgreSQLAuditRepository(self)
        self._artifacts = PostgreSQLArtifactStore(self)
        self._events = PostgreSQLEventPublisher(self)
        self._jobs = PostgreSQLJobQueue(self)

    # -- repository access -----------------------------------------------------
    @property
    def runs(self) -> PostgreSQLRunRepository:
        _acquire(self, "use the run repository")
        return self._runs

    @property
    def audits(self) -> PostgreSQLAuditRepository:
        _acquire(self, "use the audit repository")
        return self._audits

    @property
    def artifacts(self) -> PostgreSQLArtifactStore:
        _acquire(self, "use the artifact store")
        return self._artifacts

    @property
    def events(self) -> PostgreSQLEventPublisher:
        _acquire(self, "publish domain events")
        return self._events

    @property
    def jobs(self) -> PostgreSQLJobQueue:
        _acquire(self, "use the job queue")
        return self._jobs

    # -- boundary --------------------------------------------------------------
    @property
    def committed(self) -> bool:
        """True only when *this* unit of work completed its own commit."""
        return self._context.committed

    @property
    def rolled_back(self) -> bool:
        return self._context.rolled_back

    def commit(self) -> None:
        self._context.commit()

    def rollback(self) -> None:
        self._context.rollback()

    def __enter__(self) -> "PostgreSQLUnitOfWork":
        self._context.require_open("enter")
        self._context.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        # Leaving without an explicit commit or rollback always rolls back, so a
        # raised exception can never leave a partial write behind.
        rolled_back = self._context.close_without_result()
        if not rolled_back and exc_type is None:
            # A clean exit whose automatic rollback failed must not look successful:
            # report the sanitised database error instead of returning quietly.
            raise DomainError(
                ERROR_DATABASE,
                "the database refused to roll back this transaction",
            )
        # An exception that is already propagating is never masked by a rollback
        # failure; the boundary is closed either way.
        return False


class PostgreSQLUnitOfWorkFactory:
    """Creates PostgreSQL units of work over one explicit engine.

    The engine is always injected: this adapter never reads ``.env``, never falls
    back to a default connection string and never creates a global engine.

    There is exactly one transaction-creation semantic - :meth:`unit_of_work`. A
    read is a unit of work that is simply rolled back, so no second session type
    exists.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    def unit_of_work(self) -> PostgreSQLUnitOfWork:
        return PostgreSQLUnitOfWork(self._engine)

    def describe(self) -> Mapping[str, Any]:
        """Sanitised diagnostic summary: driver and database only, never host or user."""
        url = self._engine.url
        return {"driver": url.drivername, "database": url.database or ""}


__all__ = [
    "PostgreSQLArtifactStore",
    "PostgreSQLAuditRepository",
    "PostgreSQLEventPublisher",
    "PostgreSQLJobQueue",
    "PostgreSQLRunRepository",
    "PostgreSQLUnitOfWork",
    "PostgreSQLUnitOfWorkFactory",
]
