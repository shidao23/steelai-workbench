"""PostgreSQL background-job execution adapter (T84).

Implements :class:`~steelai.enterprise_lab.ports.workers.JobExecutionRepository` on the
**existing** ``background_jobs`` table: T84 adds no table, no column, no index and no
migration, and it does not touch the frozen T81 schema or constraints.

Every method is one short unit of work on its own connection from the injected Engine:

- :meth:`claim_next` locks the oldest ``queued``/``retrying`` row with
  ``SELECT ... FOR UPDATE SKIP LOCKED`` and flips it to ``leased`` with a brand new
  ``lease_id``; ``attempts`` is **not** incremented, because a job is created with
  ``attempts = 1`` and that first execution is attempt 1;
- :meth:`heartbeat`, :meth:`mark_succeeded` and :meth:`mark_failed` only touch a row that is
  still ``leased`` with exactly the same ``job_id + lease_id + attempts`` triple, which is
  the fencing condition: a worker whose lease expired can never overwrite the newer claim;
- :meth:`reclaim_expired` recovers leases whose ``updated_at`` is older than the timeout on
  the **database** clock.

All state changes reuse the frozen ``BackgroundJob.transition`` machine (including the
``leased -> failed -> retrying`` two-step for a retryable failure), so there is no second
state machine and no new state. Execution is at-least-once: a handler with external side
effects must use the stable ``job_id`` as its idempotency key.

``updated_at`` on a ``leased`` row means the database time of the last successful claim or
heartbeat; the lease timeout is process configuration and is not persisted per job.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from ...domain.models import BackgroundJob, DomainError, JobState
from ...ports.workers import (
    ERROR_WORKER_CLAIM,
    ERROR_WORKER_LEASE_EXPIRED,
    JobExecutionState,
    JobLease,
    require_positive_int,
    require_worker_error_code,
    require_worker_token,
)
from ._context import PostgreSQLContext
from .config import POSTGRESQL_SCHEMA
from .errors import map_database_error
from .hydration import hydrate_background_job, to_iso8601

T = TypeVar("T")

_SELECT_CLAIMABLE_SQL = text(
    f"""
    SELECT job_id
    FROM {POSTGRESQL_SCHEMA}.background_jobs
    WHERE state IN (:queued, :retrying)
    ORDER BY created_at, job_id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
    """
)

_SELECT_CLAIMABLE_BY_TYPE_SQL = text(
    f"""
    SELECT job_id
    FROM {POSTGRESQL_SCHEMA}.background_jobs
    WHERE state IN (:queued, :retrying)
      AND job_type = :job_type
    ORDER BY created_at, job_id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
    """
)

_CLAIM_ONE_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.background_jobs
    SET state = :leased,
        lease_id = :lease_id,
        updated_at = now()
    WHERE job_id = :job_id
      AND state IN (:queued, :retrying)
    RETURNING *
    """
)

_HEARTBEAT_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.background_jobs
    SET updated_at = now()
    WHERE job_id = :job_id
      AND state = :leased
      AND lease_id = :lease_id
      AND attempts = :attempt
    RETURNING *
    """
)

_FENCED_WRITE_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.background_jobs
    SET state = :state,
        attempts = :attempts,
        lease_id = :new_lease_id,
        error_code = :error_code,
        updated_at = now()
    WHERE job_id = :job_id
      AND state = :leased
      AND lease_id = :lease_id
      AND attempts = :attempt
    RETURNING *
    """
)

_SELECT_EXPIRED_SQL = text(
    f"""
    SELECT *
    FROM {POSTGRESQL_SCHEMA}.background_jobs
    WHERE state = :leased
      AND updated_at <= now() - make_interval(secs => :lease_timeout_seconds)
    ORDER BY updated_at, job_id
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
    """
)


def _state_from_row(row: Mapping[str, Any]) -> JobExecutionState:
    return JobExecutionState(
        job_id=row["job_id"],
        job_type=row["job_type"],
        state=row["state"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        updated_at=to_iso8601(row["updated_at"]),
        lease_id=row["lease_id"],
        error_code=row["error_code"],
    )


class PostgreSQLJobExecutionRepository:
    """Execution-state repository over the frozen ``background_jobs`` table.

    The Engine is always injected; this adapter never reads ``.env`` and never creates a
    global engine. Each call opens one short transaction and releases it before returning,
    so a handler runs with no connection held.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    # -- execution contract ----------------------------------------------------
    def claim_next(
        self,
        *,
        worker_id: str,
        lease_id: str,
        job_type: str | None = None,
    ) -> JobLease | None:
        require_worker_token(worker_id, "worker_id")
        require_worker_token(lease_id, "lease_id")
        if job_type is not None:
            require_worker_token(job_type, "job_type")

        def action(connection: Connection) -> JobLease | None:
            statement = _SELECT_CLAIMABLE_BY_TYPE_SQL if job_type is not None else _SELECT_CLAIMABLE_SQL
            parameters: dict[str, Any] = {
                "queued": JobState.QUEUED.value,
                "retrying": JobState.RETRYING.value,
            }
            if job_type is not None:
                parameters["job_type"] = job_type
            candidate = connection.execute(statement, parameters).mappings().first()
            if candidate is None:
                return None
            stored = (
                connection.execute(
                    _CLAIM_ONE_SQL,
                    {
                        "leased": JobState.LEASED.value,
                        "queued": JobState.QUEUED.value,
                        "retrying": JobState.RETRYING.value,
                        "lease_id": lease_id,
                        "job_id": candidate["job_id"],
                    },
                )
                .mappings()
                .first()
            )
            if stored is None:  # pragma: no cover - the row is locked by this transaction
                raise DomainError(
                    ERROR_WORKER_CLAIM,
                    "the claimed job changed while it was locked",
                    details={"job_id": candidate["job_id"]},
                )
            job = hydrate_background_job(stored)
            return JobLease(
                job=job,
                lease_id=lease_id,
                attempt=job.attempts,
                leased_at=to_iso8601(stored["updated_at"]),
                worker_id=worker_id,
                heartbeat_at=to_iso8601(stored["updated_at"]),
            )

        return self._short_transaction(action)

    def heartbeat(self, job_id: str, lease_id: str, attempt: int) -> JobExecutionState:
        require_worker_token(job_id, "job_id")
        require_worker_token(lease_id, "lease_id")
        require_positive_int(attempt, "attempt")

        def action(connection: Connection) -> JobExecutionState:
            stored = (
                connection.execute(
                    _HEARTBEAT_SQL,
                    {
                        "leased": JobState.LEASED.value,
                        "job_id": job_id,
                        "lease_id": lease_id,
                        "attempt": attempt,
                    },
                )
                .mappings()
                .first()
            )
            if stored is None:
                raise DomainError(
                    ERROR_WORKER_CLAIM,
                    "this lease is no longer the current lease of the job",
                    details={"job_id": job_id, "attempt": attempt},
                )
            return _state_from_row(stored)

        return self._short_transaction(action)

    def mark_succeeded(self, job_id: str, lease_id: str, attempt: int) -> JobExecutionState:
        require_worker_token(job_id, "job_id")
        require_worker_token(lease_id, "lease_id")
        require_positive_int(attempt, "attempt")

        def action(connection: Connection) -> JobExecutionState:
            current = self._lock_fenced(connection, job_id, lease_id, attempt)
            target = current.transition(
                JobState.SUCCEEDED,
                updated_at=to_iso8601(connection.execute(text("SELECT now()")).scalar_one()),
                error_code=None,
                clear_lease=True,
            )
            return self._persist_fenced(connection, target, job_id, lease_id, attempt)

        return self._short_transaction(action)

    def mark_failed(
        self,
        job_id: str,
        lease_id: str,
        attempt: int,
        error_code: str,
        *,
        retryable: bool,
    ) -> JobExecutionState:
        require_worker_token(job_id, "job_id")
        require_worker_token(lease_id, "lease_id")
        require_positive_int(attempt, "attempt")
        safe_code = require_worker_error_code(error_code)

        def action(connection: Connection) -> JobExecutionState:
            current = self._lock_fenced(connection, job_id, lease_id, attempt)
            timestamp = to_iso8601(connection.execute(text("SELECT now()")).scalar_one())
            failed = current.transition(
                JobState.FAILED,
                updated_at=timestamp,
                error_code=safe_code,
                clear_lease=True,
            )
            # The retry decision uses the persisted attempt budget of the locked row.
            if retryable and current.attempts < current.max_attempts:
                # Two legal transitions in one transaction; only ``retrying`` is persisted.
                target = failed.transition(
                    JobState.RETRYING,
                    updated_at=timestamp,
                    error_code=safe_code,
                    count_attempt=True,
                    clear_lease=True,
                )
            else:
                target = failed
            return self._persist_fenced(connection, target, job_id, lease_id, attempt)

        return self._short_transaction(action)

    def reclaim_expired(
        self,
        *,
        limit: int,
        lease_timeout_seconds: int,
    ) -> Sequence[JobExecutionState]:
        require_positive_int(limit, "limit")
        require_positive_int(lease_timeout_seconds, "lease_timeout_seconds")

        def action(connection: Connection) -> tuple[JobExecutionState, ...]:
            expired = (
                connection.execute(
                    _SELECT_EXPIRED_SQL,
                    {
                        "leased": JobState.LEASED.value,
                        "lease_timeout_seconds": lease_timeout_seconds,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
            reclaimed: list[JobExecutionState] = []
            for row in expired:
                current = hydrate_background_job(row)
                timestamp = to_iso8601(connection.execute(text("SELECT now()")).scalar_one())
                failed = current.transition(
                    JobState.FAILED,
                    updated_at=timestamp,
                    error_code=ERROR_WORKER_LEASE_EXPIRED,
                    clear_lease=True,
                )
                if current.attempts < current.max_attempts:
                    target = failed.transition(
                        JobState.RETRYING,
                        updated_at=timestamp,
                        error_code=ERROR_WORKER_LEASE_EXPIRED,
                        count_attempt=True,
                        clear_lease=True,
                    )
                else:
                    target = failed
                reclaimed.append(
                    self._persist_fenced(
                        connection,
                        target,
                        current.job_id,
                        current.lease_id or "",
                        current.attempts,
                    )
                )
            return tuple(reclaimed)

        return self._short_transaction(action)

    # -- internals -------------------------------------------------------------
    def _lock_fenced(
        self,
        connection: Connection,
        job_id: str,
        lease_id: str,
        attempt: int,
    ) -> BackgroundJob:
        """Read the locked row and verify the fencing triple before any write."""
        row = (
            connection.execute(
                text(
                    f"SELECT * FROM {POSTGRESQL_SCHEMA}.background_jobs "
                    "WHERE job_id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise DomainError(
                ERROR_WORKER_CLAIM,
                "unknown background job",
                details={"job_id": job_id},
            )
        current = hydrate_background_job(row)
        if (
            current.state != JobState.LEASED.value
            or current.lease_id != lease_id
            or current.attempts != attempt
        ):
            raise DomainError(
                ERROR_WORKER_CLAIM,
                "this lease is no longer the current lease of the job",
                details={"job_id": job_id, "attempt": attempt, "stored_state": current.state},
            )
        return current

    def _persist_fenced(
        self,
        connection: Connection,
        target: BackgroundJob,
        job_id: str,
        lease_id: str,
        attempt: int,
    ) -> JobExecutionState:
        """Persist the transitioned job, fenced by the full claim identity."""
        stored = (
            connection.execute(
                _FENCED_WRITE_SQL,
                {
                    "state": target.state,
                    "attempts": target.attempts,
                    "new_lease_id": target.lease_id,
                    "error_code": target.error_code,
                    "job_id": job_id,
                    "lease_id": lease_id,
                    "attempt": attempt,
                    "leased": JobState.LEASED.value,
                },
            )
            .mappings()
            .first()
        )
        if stored is None:  # pragma: no cover - the row is locked by this transaction
            raise DomainError(
                ERROR_WORKER_CLAIM,
                "this lease is no longer the current lease of the job",
                details={"job_id": job_id, "attempt": attempt},
            )
        return _state_from_row(stored)

    def _short_transaction(self, action: Callable[[Connection], T]) -> T:
        """Run ``action`` in one committed unit of work and release the connection.

        The boundary is deliberately not the five-repository unit of work: a worker needs a
        *short* claim, heartbeat or confirm transaction, and no handle may outlive it.
        Failures are rolled back without masking the original error, and database errors keep
        the T82 SQLSTATE mapping.
        """
        context = PostgreSQLContext(self._engine)
        context.start()
        try:
            result = action(context.connection)
        except DomainError:
            context.close_without_result()
            raise
        except Exception as exc:  # noqa: BLE001 - classify by SQLSTATE, never by text
            context.close_without_result()
            raise map_database_error(exc) from None
        context.commit()
        return result


__all__ = ["PostgreSQLJobExecutionRepository"]
