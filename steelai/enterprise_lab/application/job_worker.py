"""Finite background-job worker (T84).

One call does a bounded amount of work and returns: there is no unbounded run-forever entry
point, no unbounded loop, no timer and no background thread. The caller decides when to call
:meth:`JobWorker.run_once`, :meth:`JobWorker.run_batch` and
:meth:`JobWorker.reclaim_expired`.

Transaction discipline, identical in spirit to the T83 dispatcher:

1. claim in one **short** unit of work and commit it (the lease is durable and the
   connection is back in the pool);
2. run the handler **outside** any database transaction - a long handler must never hold a
   connection, and it may extend its lease explicitly through ``context.heartbeat()``;
3. confirm the result - success or failure - in its **own** short unit of work, fenced by
   ``job_id + lease_id + attempt``.

Execution is **at-least-once**. When the handler succeeded but the confirmation did not
commit (``success_unrecorded``), the lease expires and the job may run again: a handler with
external side effects must use the stable ``job_id`` as its idempotency key. T84 never
claims exactly-once execution.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable

from ..domain.models import DomainError, JobState
from ..ports.workers import (
    ERROR_WORKER_CLAIM,
    ERROR_WORKER_CONFIG,
    ERROR_WORKER_EXECUTION,
    ERROR_WORKER_HANDLER_NOT_FOUND,
    JobExecutionContext,
    JobExecutionRepository,
    JobExecutionState,
    JobHandlerError,
    JobHandlerRegistry,
    JobLease,
    require_positive_int,
    require_worker_token,
)

#: Outcomes reported by one bounded worker call.
OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_RETRY_SCHEDULED = "retry_scheduled"
OUTCOME_FAILED_TERMINAL = "failed_terminal"
#: The handler returned successfully, but the success state did not commit.
OUTCOME_SUCCESS_UNRECORDED = "success_unrecorded"
#: The handler failed, and the failure state did not commit either.
OUTCOME_FAILURE_UNRECORDED = "failure_unrecorded"

#: ``status -> (handler_succeeded, persistence_state_known, reexecution_possible)``.
#:
#: The three properties are derived from the status only, so a caller can never assemble a
#: contradictory combination (for example "handler succeeded" together with "not executed").
OUTCOME_PROPERTIES: dict[str, tuple[bool, bool, bool]] = {
    OUTCOME_SUCCEEDED: (True, True, False),
    OUTCOME_RETRY_SCHEDULED: (False, True, True),
    OUTCOME_FAILED_TERMINAL: (False, True, False),
    OUTCOME_SUCCESS_UNRECORDED: (True, False, True),
    OUTCOME_FAILURE_UNRECORDED: (False, False, True),
}

OUTCOME_STATUSES = tuple(OUTCOME_PROPERTIES)

#: ``status -> (persisted state, attempts offset relative to the attempt, error code required)``.
#:
#: The three "known" statuses must report the state the repository actually persisted, the
#: exact attempt counter that goes with it, and (for a failure) a safe error code. The two
#: "unknown" statuses must report **no** persisted state at all, because nothing about the
#: persisted row is known - only that a safe error code explains what happened.
PERSISTED_FIELDS: dict[str, tuple[str | None, int | None, bool]] = {
    OUTCOME_SUCCEEDED: (JobState.SUCCEEDED.value, 0, False),
    OUTCOME_RETRY_SCHEDULED: (JobState.RETRYING.value, 1, True),
    OUTCOME_FAILED_TERMINAL: (JobState.FAILED.value, 0, True),
    OUTCOME_SUCCESS_UNRECORDED: (None, None, True),
    OUTCOME_FAILURE_UNRECORDED: (None, None, True),
}


def default_lease_id() -> str:
    """A fresh, safe lease token: never derived from a host name, path or credential."""
    return f"lease_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class JobWorkerConfig:
    """Bounded, validated worker configuration.

    ``lease_timeout_seconds`` is process configuration: T84 stores no per-job timeout, so
    every worker and reaper in a deployment must use the same value. The attempt budget is
    **not** here - it lives on the job row (``background_jobs.max_attempts``), which is the
    authoritative persisted value.
    """

    worker_id: str = "worker_local_001"
    lease_timeout_seconds: int = 60
    batch_limit: int = 5

    def __post_init__(self) -> None:
        require_worker_token(self.worker_id, "worker_id")
        require_positive_int(self.lease_timeout_seconds, "lease_timeout_seconds")
        require_positive_int(self.batch_limit, "batch_limit")


@dataclass(frozen=True)
class JobOutcome:
    """What happened to one job in this call.

    Only ``status`` is passed in; the three properties are derived from it, and the
    persisted fields must agree with the status:

    =========================  ==================  =============  ==================
    status                     ``state``           ``attempts``   ``error_code``
    =========================  ==================  =============  ==================
    ``succeeded``              ``succeeded``       ``attempt``    ``None``
    ``retry_scheduled``        ``retrying``        ``attempt + 1`` required
    ``failed_terminal``        ``failed``          ``attempt``    required
    ``success_unrecorded``     ``None``            ``None``       required
    ``failure_unrecorded``     ``None``            ``None``       required
    =========================  ==================  =============  ==================

    Any other combination is refused with ``ENT-WORKER-CONFIG-001``, so an outcome can
    never claim a persisted state it does not describe, forget the failure code of a known
    failure, or carry a persisted state for an unknown one.
    """

    job_id: str
    job_type: str
    run_id: str
    attempt: int
    status: str
    lease_id: str
    error_code: str | None = None
    state: str | None = None
    attempts: int | None = None

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_PROPERTIES:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "unknown worker outcome status",
                details={"status": self.status, "declared": list(OUTCOME_STATUSES)},
            )
        require_worker_token(self.job_id, "job_id")
        require_worker_token(self.job_type, "job_type")
        require_worker_token(self.run_id, "run_id")
        require_worker_token(self.lease_id, "lease_id")
        require_positive_int(self.attempt, "attempt")
        if self.error_code is not None:
            from ..ports.workers import require_worker_error_code

            require_worker_error_code(self.error_code)
        self._require_persisted_fields()

    def _require_persisted_fields(self) -> None:
        """Enforce the status -> (state, attempts, error_code) table exactly."""
        expected = PERSISTED_FIELDS[self.status]
        expected_state, attempt_offset, error_code_required = expected
        if self.state != expected_state:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                f"{self.status} must report the persisted state {expected_state!r}",
                details={"status": self.status, "state": self.state},
            )
        if error_code_required and self.error_code is None:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                f"{self.status} must carry a safe error code",
                details={"status": self.status},
            )
        if not error_code_required and self.error_code is not None:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                f"{self.status} must not carry an error code",
                details={"status": self.status},
            )
        if attempt_offset is None:
            if self.attempts is not None:
                raise DomainError(
                    ERROR_WORKER_CONFIG,
                    f"{self.status} must not report a persisted attempt counter",
                    details={"status": self.status, "attempts": self.attempts},
                )
            return
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "attempts must be a positive integer when the persisted state is known",
                details={"status": self.status},
            )
        require_positive_int(self.attempts, "attempts")
        if self.attempts != self.attempt + attempt_offset:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                f"{self.status} must report attempts == attempt + {attempt_offset}",
                details={"status": self.status, "attempt": self.attempt, "attempts": self.attempts},
            )

    @property
    def handler_succeeded(self) -> bool:
        """True only when the handler itself returned successfully."""
        return OUTCOME_PROPERTIES[self.status][0]

    @property
    def persistence_state_known(self) -> bool:
        """True only when the persisted job state is known to have been written."""
        return OUTCOME_PROPERTIES[self.status][1]

    @property
    def reexecution_possible(self) -> bool:
        """True when the job may be executed again later (retry or lease recovery)."""
        return OUTCOME_PROPERTIES[self.status][2]

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "status": self.status,
            "lease_id": self.lease_id,
            "error_code": self.error_code,
            "state": self.state,
            "attempts": self.attempts,
            "handler_succeeded": self.handler_succeeded,
            "persistence_state_known": self.persistence_state_known,
            "reexecution_possible": self.reexecution_possible,
        }


class JobWorker:
    """Claim one job, run its handler outside any transaction, then confirm the result."""

    def __init__(
        self,
        execution: JobExecutionRepository,
        registry: JobHandlerRegistry,
        config: JobWorkerConfig | None = None,
        *,
        lease_id_factory: Callable[[], str] = default_lease_id,
    ) -> None:
        self._execution = execution
        self._registry = registry
        self._config = config or JobWorkerConfig()
        self._lease_id_factory = lease_id_factory

    @property
    def config(self) -> JobWorkerConfig:
        return self._config

    # -- public finite calls ---------------------------------------------------
    def run_once(self, job_type: str | None = None) -> JobOutcome | None:
        """Lease at most one job, execute it outside any transaction, confirm the result.

        Returns ``None`` when nothing was claimable. A handler failure never raises out of
        this method: it is recorded as a retry or a terminal failure, and an unrecordable
        result is reported as one of the two explicit "unknown" statuses.
        """
        if job_type is not None:
            require_worker_token(job_type, "job_type")
        lease = self._execution.claim_next(
            worker_id=self._config.worker_id,
            lease_id=self._lease_id_factory(),
            job_type=job_type,
        )
        if lease is None:
            return None
        return self._execute(lease)

    def run_batch(self, limit: int | None = None, job_type: str | None = None) -> tuple[JobOutcome, ...]:
        """Repeat :meth:`run_once` up to ``limit`` times, stopping when nothing is claimable.

        One job's outcome - including an unknown or failed one - never interrupts the rest
        of the batch.
        """
        batch_limit = self._config.batch_limit if limit is None else require_positive_int(limit, "limit")
        outcomes: list[JobOutcome] = []
        for _ in range(batch_limit):
            outcome = self.run_once(job_type)
            if outcome is None:
                break
            outcomes.append(outcome)
        return tuple(outcomes)

    def reclaim_expired(self, limit: int | None = None) -> tuple[JobExecutionState, ...]:
        """Recover leases older than the configured timeout on the database clock."""
        batch_limit = self._config.batch_limit if limit is None else require_positive_int(limit, "limit")
        return tuple(
            self._execution.reclaim_expired(
                limit=batch_limit,
                lease_timeout_seconds=self._config.lease_timeout_seconds,
            )
        )

    # -- internals -------------------------------------------------------------
    def _execute(self, lease: JobLease) -> JobOutcome:
        """Run the handler outside any transaction, then confirm in its own transaction."""
        context = JobExecutionContext(
            job_id=lease.job_id,
            job_type=lease.job_type,
            run_id=lease.run_id,
            attempt=lease.attempt,
            max_attempts=lease.job.max_attempts,
            payload_digest=lease.job.payload_digest,
            idempotency_key=lease.job.idempotency_key,
            heartbeat=lambda: self._heartbeat(lease),
        )
        failure = self._run_handler(context, lease)
        if failure is not None:
            return self._record_failure(lease, failure)
        # The handler succeeded; the confirmation is its own short unit of work.
        try:
            state = self._execution.mark_succeeded(lease.job_id, lease.lease_id, lease.attempt)
        except DomainError as exc:
            # The state did not commit (another worker took the lease over, or the write
            # failed): the handler really did succeed, but the job may run again.
            return self._outcome(
                lease,
                OUTCOME_SUCCESS_UNRECORDED,
                error_code=exc.code or ERROR_WORKER_CLAIM,
            )
        return self._outcome(lease, OUTCOME_SUCCEEDED, state=state.state, attempts=state.attempts)

    def _run_handler(self, context: JobExecutionContext, lease: JobLease) -> JobHandlerError | None:
        """Return a classified failure, or ``None`` when the handler succeeded.

        The handler execution boundary is deliberately total for ``Exception``: a handler
        that raises a :class:`~steelai.enterprise_lab.domain.models.DomainError` is just as
        unclassified as one that raises anything else, so the original code, message,
        ``details``, URL, host, credential, path or exception type must never leave this
        method. Everything except :class:`JobHandlerError` becomes
        ``ENT-WORKER-EXECUTION-001`` (retryable), which keeps the batch running and lets the
        failure be recorded instead of leaving the job stuck in ``leased``.

        ``BaseException`` such as ``KeyboardInterrupt`` or ``SystemExit`` is **not** caught:
        an operator signal must reach the caller.
        """
        try:
            handler = self._registry.resolve(lease.job_type)
        except DomainError:
            # An unregistered job type is a terminal, non-retryable failure.
            return JobHandlerError(ERROR_WORKER_HANDLER_NOT_FOUND, retryable=False)
        try:
            handler.execute(context)
        except JobHandlerError as exc:
            # The handler classified its own failure: keep its safe code and retry hint.
            return exc
        except Exception:  # noqa: BLE001 - every handler exception is unclassified here
            # Only a fixed safe code is ever persisted or returned, and the original
            # exception never reaches the database, the outcome or the caller.
            return JobHandlerError(ERROR_WORKER_EXECUTION, retryable=True)
        return None

    def _heartbeat(self, lease: JobLease) -> JobExecutionState:
        """Extend this lease; a lost lease becomes a classified, retryable failure."""
        try:
            return self._execution.heartbeat(lease.job_id, lease.lease_id, lease.attempt)
        except DomainError:
            raise JobHandlerError(ERROR_WORKER_CLAIM, retryable=True) from None

    def _record_failure(self, lease: JobLease, failure: JobHandlerError) -> JobOutcome:
        """Persist a safe failure; the repository decides retry versus terminal."""
        try:
            state = self._execution.mark_failed(
                lease.job_id,
                lease.lease_id,
                lease.attempt,
                failure.error_code,
                retryable=failure.retryable,
            )
        except DomainError as exc:
            # The failure could not be recorded (lost lease or failed write): the job was
            # not executed successfully and its persisted state is unknown.
            return self._outcome(
                lease,
                OUTCOME_FAILURE_UNRECORDED,
                error_code=exc.code or ERROR_WORKER_CLAIM,
            )
        status = (
            OUTCOME_RETRY_SCHEDULED
            if state.state == JobState.RETRYING.value
            else OUTCOME_FAILED_TERMINAL
        )
        return self._outcome(
            lease,
            status,
            error_code=failure.error_code,
            state=state.state,
            attempts=state.attempts,
        )

    def _outcome(
        self,
        lease: JobLease,
        status: str,
        *,
        error_code: str | None = None,
        state: str | None = None,
        attempts: int | None = None,
    ) -> JobOutcome:
        return JobOutcome(
            job_id=lease.job_id,
            job_type=lease.job_type,
            run_id=lease.run_id,
            attempt=lease.attempt,
            status=status,
            lease_id=lease.lease_id,
            error_code=error_code,
            state=state,
            attempts=attempts,
        )


__all__ = [
    "JobOutcome",
    "JobWorker",
    "JobWorkerConfig",
    "OUTCOME_FAILURE_UNRECORDED",
    "OUTCOME_FAILED_TERMINAL",
    "OUTCOME_PROPERTIES",
    "OUTCOME_RETRY_SCHEDULED",
    "OUTCOME_STATUSES",
    "OUTCOME_SUCCEEDED",
    "OUTCOME_SUCCESS_UNRECORDED",
    "PERSISTED_FIELDS",
    "default_lease_id",
]
