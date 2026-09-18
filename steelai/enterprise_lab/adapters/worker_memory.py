"""In-memory job execution adapter and recording handler (T84).

Two test-only building blocks live here:

- :class:`MemoryJobExecutionRepository` mirrors the PostgreSQL execution contract (claim
  predicate, ``lease_id`` + ``attempt`` fencing, heartbeat, expiry recovery, the two-step
  retry transition), so the offline suite proves the worker against the same semantics
  without a server. It is **not** a concurrency guarantee and is not a production adapter;
- :class:`RecordingJobHandler` records calls in memory and never touches the filesystem,
  the network, a subprocess or a database. It proves the interface and the flow - it is
  **not** a real scientific job.

Neither class is wired into the default application.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from ..domain.models import BackgroundJob, DomainError, JobState
from ..ports.workers import (
    ERROR_WORKER_CLAIM,
    ERROR_WORKER_LEASE_EXPIRED,
    JobExecutionContext,
    JobExecutionState,
    JobHandlerError,
    JobLease,
    require_positive_int,
    require_worker_error_code,
    require_worker_token,
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _to_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        raise DomainError(ERROR_WORKER_CLAIM, "stored timestamps must carry a timezone")
    return moment.astimezone(dt.timezone.utc).isoformat()


@dataclass
class _Row:
    """One job row: the frozen job plus its current lease."""

    job: BackgroundJob


class MemoryJobExecutionRepository:
    """In-memory :class:`~steelai.enterprise_lab.ports.workers.JobExecutionRepository`.

    The clock is injectable so a test can advance it deterministically; the default clock is
    the system UTC clock, mirroring the database clock of the PostgreSQL adapter.
    ``in_short_transaction`` is ``True`` only while one claim/heartbeat/confirm call is
    executing, which lets a test prove the handler never runs with an open boundary.
    """

    def __init__(self, clock: Callable[[], dt.datetime] | None = None) -> None:
        self._clock = clock or _utc_now
        self._offset = dt.timedelta(0)
        self._rows: dict[str, _Row] = {}
        self._in_short_transaction = False

    # -- clock -----------------------------------------------------------------
    def _now(self) -> dt.datetime:
        return self._clock() + self._offset

    def advance(self, seconds: int) -> None:
        """Move the clock forward, e.g. to expire a lease in a test."""
        require_positive_int(seconds, "seconds")
        self._offset += dt.timedelta(seconds=seconds)

    # -- test helpers ----------------------------------------------------------
    @property
    def in_short_transaction(self) -> bool:
        """True only inside a repository call, never during handler execution."""
        return self._in_short_transaction

    def add(self, job: BackgroundJob) -> None:
        """Seed one job exactly as the T82 queue wrote it (``queued``, ``attempts = 1``)."""
        if job.job_id in self._rows:
            raise DomainError(ERROR_WORKER_CLAIM, "job_id already exists", details={"job_id": job.job_id})
        self._rows[job.job_id] = _Row(job=job)

    def get(self, job_id: str) -> BackgroundJob:
        return self._row(job_id).job

    def count(self, state: str | None = None) -> int:
        if state is None:
            return len(self._rows)
        return sum(1 for row in self._rows.values() if row.job.state == state)

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
        self._in_short_transaction = True
        try:
            candidates = [
                row
                for row in self._rows.values()
                if row.job.state in (JobState.QUEUED.value, JobState.RETRYING.value)
                and (job_type is None or row.job.job_type == job_type)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda row: (row.job.created_at, row.job.job_id))
            row = candidates[0]
            now = self._now()
            # queued/retrying -> leased: no attempt increment, a brand new lease identity.
            leased = row.job.transition(
                JobState.LEASED,
                updated_at=_to_iso(now),
                lease_id=lease_id,
            )
            row.job = leased
            return JobLease(
                job=leased,
                lease_id=lease_id,
                attempt=leased.attempts,
                leased_at=_to_iso(now),
                worker_id=worker_id,
                heartbeat_at=_to_iso(now),
            )
        finally:
            self._in_short_transaction = False

    def heartbeat(self, job_id: str, lease_id: str, attempt: int) -> JobExecutionState:
        require_worker_token(job_id, "job_id")
        require_worker_token(lease_id, "lease_id")
        require_positive_int(attempt, "attempt")
        self._in_short_transaction = True
        try:
            row = self._require_lease(job_id, lease_id, attempt)
            now = self._now()
            row.job = BackgroundJob(
                job_id=row.job.job_id,
                job_type=row.job.job_type,
                run_id=row.job.run_id,
                state=row.job.state,
                attempts=row.job.attempts,
                max_attempts=row.job.max_attempts,
                idempotency_key=row.job.idempotency_key,
                payload_digest=row.job.payload_digest,
                created_at=row.job.created_at,
                updated_at=_to_iso(now),
                lease_id=row.job.lease_id,
                error_code=row.job.error_code,
            )
            return self._state_of(row.job)
        finally:
            self._in_short_transaction = False

    def mark_succeeded(self, job_id: str, lease_id: str, attempt: int) -> JobExecutionState:
        require_positive_int(attempt, "attempt")
        self._in_short_transaction = True
        try:
            row = self._require_lease(job_id, lease_id, attempt)
            row.job = row.job.transition(
                JobState.SUCCEEDED,
                updated_at=_to_iso(self._now()),
                error_code=None,
                clear_lease=True,
            )
            return self._state_of(row.job)
        finally:
            self._in_short_transaction = False

    def mark_failed(
        self,
        job_id: str,
        lease_id: str,
        attempt: int,
        error_code: str,
        *,
        retryable: bool,
    ) -> JobExecutionState:
        require_positive_int(attempt, "attempt")
        safe_code = require_worker_error_code(error_code)
        self._in_short_transaction = True
        try:
            row = self._require_lease(job_id, lease_id, attempt)
            now = _to_iso(self._now())
            # The retry decision uses the persisted attempt budget of the locked row.
            if retryable and row.job.attempts < row.job.max_attempts:
                failed = row.job.transition(
                    JobState.FAILED, updated_at=now, error_code=safe_code, clear_lease=True
                )
                row.job = failed.transition(
                    JobState.RETRYING,
                    updated_at=now,
                    error_code=safe_code,
                    count_attempt=True,
                    clear_lease=True,
                )
            else:
                row.job = row.job.transition(
                    JobState.FAILED, updated_at=now, error_code=safe_code, clear_lease=True
                )
            return self._state_of(row.job)
        finally:
            self._in_short_transaction = False

    def reclaim_expired(
        self,
        *,
        limit: int,
        lease_timeout_seconds: int,
    ) -> tuple[JobExecutionState, ...]:
        require_positive_int(limit, "limit")
        require_positive_int(lease_timeout_seconds, "lease_timeout_seconds")
        self._in_short_transaction = True
        try:
            now = self._now()
            deadline = now - dt.timedelta(seconds=lease_timeout_seconds)
            expired = [
                row
                for row in self._rows.values()
                if row.job.state == JobState.LEASED.value
                and dt.datetime.fromisoformat(row.job.updated_at) <= deadline
            ]
            expired.sort(key=lambda row: (row.job.updated_at, row.job.job_id))
            reclaimed: list[JobExecutionState] = []
            for row in expired[:limit]:
                timestamp = _to_iso(now)
                if row.job.attempts < row.job.max_attempts:
                    failed = row.job.transition(
                        JobState.FAILED,
                        updated_at=timestamp,
                        error_code=ERROR_WORKER_LEASE_EXPIRED,
                        clear_lease=True,
                    )
                    row.job = failed.transition(
                        JobState.RETRYING,
                        updated_at=timestamp,
                        error_code=ERROR_WORKER_LEASE_EXPIRED,
                        count_attempt=True,
                        clear_lease=True,
                    )
                else:
                    row.job = row.job.transition(
                        JobState.FAILED,
                        updated_at=timestamp,
                        error_code=ERROR_WORKER_LEASE_EXPIRED,
                        clear_lease=True,
                    )
                reclaimed.append(self._state_of(row.job))
            return tuple(reclaimed)
        finally:
            self._in_short_transaction = False

    # -- internals -------------------------------------------------------------
    def _row(self, job_id: str) -> _Row:
        row = self._rows.get(job_id)
        if row is None:
            raise DomainError(ERROR_WORKER_CLAIM, "unknown job", details={"job_id": job_id})
        return row

    def _require_lease(self, job_id: str, lease_id: str, attempt: int) -> _Row:
        """Accept a write only for the live lease with the matching fencing triple."""
        row = self._row(job_id)
        if (
            row.job.state != JobState.LEASED.value
            or row.job.lease_id != lease_id
            or row.job.attempts != attempt
        ):
            raise DomainError(
                ERROR_WORKER_CLAIM,
                "this lease is no longer the current lease of the job",
                details={
                    "job_id": job_id,
                    "lease_id": lease_id,
                    "attempt": attempt,
                    "stored_state": row.job.state,
                    "stored_attempts": row.job.attempts,
                },
            )
        return row

    def _state_of(self, job: BackgroundJob) -> JobExecutionState:
        return JobExecutionState(
            job_id=job.job_id,
            job_type=job.job_type,
            state=job.state,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            updated_at=job.updated_at,
            lease_id=job.lease_id,
            error_code=job.error_code,
        )


@dataclass(frozen=True)
class RecordedJobCall:
    """One recorded handler call: what a real handler would have received."""

    job_id: str
    job_type: str
    run_id: str
    attempt: int
    idempotency_key: str
    payload_digest: str


class RecordingJobHandler:
    """Records handler calls in memory; performs no I/O of any kind.

    A test can script the next outcomes to exercise every failure path. The recorded calls
    are the evidence that a re-execution uses the same ``job_id`` and a larger ``attempt``,
    and they are **not** evidence that any real scientific job ran.
    """

    def __init__(self, *, heartbeats: int = 0) -> None:
        self.calls: list[RecordedJobCall] = []
        self._scripted: list[BaseException | None] = []
        self._heartbeats = heartbeats
        self.heartbeat_results: list[JobExecutionState] = []

    # -- scripting -------------------------------------------------------------
    def succeed(self, *, times: int = 1) -> None:
        require_positive_int(times, "times")
        self._scripted.extend([None] * times)

    def fail_next(self, error_code: str, *, retryable: bool = True, times: int = 1) -> None:
        require_positive_int(times, "times")
        self._scripted.extend(
            JobHandlerError(error_code, retryable=retryable) for _ in range(times)
        )

    def raise_next(self, exception: BaseException, *, times: int = 1) -> None:
        require_positive_int(times, "times")
        self._scripted.extend(exception for _ in range(times))

    def heartbeat_next(self, times: int) -> None:
        """Call ``context.heartbeat()`` ``times`` times during the next executions."""
        require_positive_int(times, "times")
        self._heartbeats = times

    # -- handler ---------------------------------------------------------------
    def execute(self, context: JobExecutionContext) -> None:
        self.calls.append(
            RecordedJobCall(
                job_id=context.job_id,
                job_type=context.job_type,
                run_id=context.run_id,
                attempt=context.attempt,
                idempotency_key=context.idempotency_key,
                payload_digest=context.payload_digest,
            )
        )
        for _ in range(self._heartbeats):
            self.heartbeat_results.append(context.heartbeat())
        if self._scripted:
            outcome = self._scripted.pop(0)
            if outcome is not None:
                raise outcome

    # -- evidence --------------------------------------------------------------
    @property
    def job_ids(self) -> list[str]:
        return [call.job_id for call in self.calls]

    @property
    def attempts(self) -> list[int]:
        return [call.attempt for call in self.calls]

    @property
    def idempotency_keys(self) -> list[str]:
        return [call.idempotency_key for call in self.calls]


__all__ = [
    "MemoryJobExecutionRepository",
    "RecordedJobCall",
    "RecordingJobHandler",
]
