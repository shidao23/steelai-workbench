"""Background-job execution port (T84).

This port is deliberately **separate** from
:class:`~steelai.enterprise_lab.ports.jobs.JobQueue`. The T80/T82 queue keeps doing what it
already does - ``enqueue``, basic state queries and the frozen state-machine drills. The
execution side needs *distributed worker* semantics that do not belong in that interface:

- a lease has its own identity (``lease_id``) that changes on every claim;
- every write is fenced by ``job_id + lease_id + attempt``;
- a heartbeat extends the lease, and an expired lease is recovered by another worker.

There is no new job state: every write reuses the frozen
``BackgroundJob.transition`` machine, and ``ALLOWED_JOB_TRANSITIONS`` is unchanged.

Job execution is **at-least-once**. A worker that loses its lease may already have produced
external side effects, so a handler with side effects must use the stable ``job_id`` as its
idempotency key. T84 never claims exactly-once execution.

``updated_at`` on a ``leased`` row means "the database time of the last successful claim or
heartbeat". There is no ``lease_expires_at`` column: the lease timeout is configuration, and
T84 does not persist a per-job timeout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence, runtime_checkable

from ..domain.models import (
    BackgroundJob,
    DomainError,
    JobState,
    validate_timestamp,
)

#: Stable, redaction-safe error codes of the worker boundary.
ERROR_WORKER_CLAIM = "ENT-WORKER-CLAIM-001"
ERROR_WORKER_CONFIG = "ENT-WORKER-CONFIG-001"
ERROR_WORKER_EXECUTION = "ENT-WORKER-EXECUTION-001"
ERROR_WORKER_HANDLER_NOT_FOUND = "ENT-WORKER-HANDLER-NOT-FOUND"
ERROR_WORKER_LEASE_EXPIRED = "ENT-WORKER-LEASE-EXPIRED"

#: A worker identity or lease identity is a short safe token: no host, port, user, path,
#: credential or free text can be expressed with this alphabet.
WORKER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: A payload digest is a lowercase SHA-256 of the redacted job request.
PAYLOAD_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def require_worker_error_code(value: object, field_name: str = "error_code") -> str:
    """Fail closed with ``ENT-WORKER-CONFIG-001`` on an unsafe error code."""
    if not isinstance(value, str) or not WORKER_TOKEN_PATTERN.fullmatch(value):
        raise DomainError(
            ERROR_WORKER_CONFIG,
            f"{field_name} must be a safe error code without text, URL, host, path or credentials",
            details={"field": field_name},
        )
    return value


def require_worker_token(value: object, field_name: str) -> str:
    """Fail closed with ``ENT-WORKER-CONFIG-001`` on an unsafe worker/lease identity."""
    if not isinstance(value, str) or not WORKER_TOKEN_PATTERN.fullmatch(value):
        raise DomainError(
            ERROR_WORKER_CONFIG,
            f"{field_name} must be a short safe token without host, path or credential information",
            details={"field": field_name},
        )
    return value


def require_positive_int(value: object, field_name: str) -> int:
    """Fail closed with ``ENT-WORKER-CONFIG-001`` on a non-positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DomainError(
            ERROR_WORKER_CONFIG,
            f"{field_name} must be a positive integer",
            details={"field": field_name},
        )
    return value


def require_aware_timestamp(value: object, field_name: str) -> str:
    """Fail closed with ``ENT-WORKER-CONFIG-001`` on a timestamp without a timezone."""
    try:
        validate_timestamp(str(value), field_name)
    except DomainError:
        raise DomainError(
            ERROR_WORKER_CONFIG,
            f"{field_name} must be an ISO-8601 timestamp with a timezone",
            details={"field": field_name},
        ) from None
    return str(value)


@dataclass(frozen=True)
class JobLease:
    """One leased job: the frozen job plus the identity of *this* lease.

    ``attempt`` always equals ``job.attempts`` and is the execution attempt number the
    worker is running. ``job_id + lease_id + attempt`` is the fencing condition every write
    must satisfy, so a worker whose lease expired can never record a result over the newer
    claim.
    """

    job: BackgroundJob
    lease_id: str
    attempt: int
    leased_at: str
    worker_id: str
    heartbeat_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.job, BackgroundJob):
            raise DomainError(ERROR_WORKER_CONFIG, "lease.job must be a BackgroundJob")
        if self.job.state != JobState.LEASED.value:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "a lease must describe a leased job",
                details={"state": self.job.state},
            )
        require_worker_token(self.lease_id, "lease_id")
        require_worker_token(self.worker_id, "worker_id")
        require_positive_int(self.attempt, "attempt")
        if self.attempt != self.job.attempts:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "lease.attempt must equal the job's own attempts counter",
                details={"attempt": self.attempt, "job_attempts": self.job.attempts},
            )
        require_aware_timestamp(self.leased_at, "leased_at")
        if self.heartbeat_at:
            require_aware_timestamp(self.heartbeat_at, "heartbeat_at")
        if self.job.lease_id != self.lease_id:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "the leased job must carry the same lease_id as the lease",
                details={"lease_id": self.lease_id},
            )

    @property
    def job_id(self) -> str:
        return self.job.job_id

    @property
    def job_type(self) -> str:
        return self.job.job_type

    @property
    def run_id(self) -> str:
        return self.job.run_id

    @property
    def last_activity_at(self) -> str:
        """The database time of the last successful claim or heartbeat."""
        return self.heartbeat_at or self.leased_at

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "attempt": self.attempt,
            "attempts": self.job.attempts,
            "max_attempts": self.job.max_attempts,
            "state": self.job.state,
            "worker_id": self.worker_id,
            "leased_at": self.leased_at,
            "heartbeat_at": self.heartbeat_at,
        }


@dataclass(frozen=True)
class JobExecutionState:
    """The persisted state of one job after a fenced worker write."""

    job_id: str
    job_type: str
    state: str
    attempts: int
    max_attempts: int
    updated_at: str
    lease_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {item.value for item in JobState}:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "state must be a declared job state",
                details={"state": self.state},
            )
        require_positive_int(self.attempts, "attempts")
        require_positive_int(self.max_attempts, "max_attempts")
        if self.attempts > self.max_attempts:
            raise DomainError(ERROR_WORKER_CONFIG, "attempts must not exceed max_attempts")
        require_aware_timestamp(self.updated_at, "updated_at")
        if self.lease_id is not None:
            require_worker_token(self.lease_id, "lease_id")
        if self.error_code is not None:
            require_worker_error_code(self.error_code, "error_code")

    @property
    def requeued(self) -> bool:
        return self.state == JobState.RETRYING.value

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "state": self.state,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "updated_at": self.updated_at,
            "lease_id": self.lease_id,
            "error_code": self.error_code,
        }


@runtime_checkable
class JobExecutionRepository(Protocol):
    """Execution boundary of the worker: claim, heartbeat, confirm, recover.

    Every method is one short unit of work that commits or rolls back before it returns, so
    a handler never runs while a database connection is held.
    """

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_id: str,
        job_type: str | None = None,
    ) -> JobLease | None:
        """Lease the oldest queued or retrying job, or return ``None`` immediately."""
        ...

    def heartbeat(self, job_id: str, lease_id: str, attempt: int) -> JobExecutionState:
        """Extend the lease and refresh ``updated_at``; fenced by the full triple."""
        ...

    def mark_succeeded(self, job_id: str, lease_id: str, attempt: int) -> JobExecutionState:
        """``leased`` -> ``succeeded``, clearing the lease and the error code."""
        ...

    def mark_failed(
        self,
        job_id: str,
        lease_id: str,
        attempt: int,
        error_code: str,
        *,
        retryable: bool,
    ) -> JobExecutionState:
        """``leased`` -> ``failed``, or ``leased`` -> ``failed`` -> ``retrying`` when the
        failure is retryable **and** the persisted attempt budget still allows another try."""
        ...

    def reclaim_expired(
        self,
        *,
        limit: int,
        lease_timeout_seconds: int,
    ) -> Sequence[JobExecutionState]:
        """Recover leases whose ``updated_at`` is older than the timeout on the database clock."""
        ...


@dataclass(frozen=True)
class JobExecutionContext:
    """The safe metadata a handler receives.

    It carries identifiers, counters and the (already redacted) payload digest - never the
    job payload itself, a file path, a database connection or a credential. ``heartbeat()``
    is a finite call that extends the lease and returns the refreshed
    :class:`JobExecutionState`; a handler that runs long may call it as often as it likes.
    """

    job_id: str
    job_type: str
    run_id: str
    attempt: int
    max_attempts: int
    payload_digest: str
    idempotency_key: str
    heartbeat: Callable[[], JobExecutionState] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        require_worker_token(self.job_id, "job_id")
        require_worker_token(self.job_type, "job_type")
        require_worker_token(self.run_id, "run_id")
        require_worker_token(self.idempotency_key, "idempotency_key")
        require_positive_int(self.attempt, "attempt")
        require_positive_int(self.max_attempts, "max_attempts")
        if self.attempt > self.max_attempts:
            raise DomainError(ERROR_WORKER_CONFIG, "attempt must not exceed max_attempts")
        if not isinstance(self.payload_digest, str) or not PAYLOAD_DIGEST_PATTERN.fullmatch(
            self.payload_digest
        ):
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "payload_digest must be a lowercase SHA-256 digest",
            )
        if not callable(self.heartbeat):
            raise DomainError(ERROR_WORKER_CONFIG, "heartbeat must be callable")

    def to_dict(self) -> dict[str, object]:
        """The safe projection a handler may log: no payload, no path, no credential."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "payload_digest": self.payload_digest,
            "idempotency_key": self.idempotency_key,
        }


class JobHandlerError(Exception):
    """A handler failure carrying only a safe error code and a retry hint."""

    def __init__(self, error_code: str, *, retryable: bool) -> None:
        safe_code = require_worker_error_code(error_code)
        super().__init__(safe_code)
        self.error_code = safe_code
        self.retryable = bool(retryable)


@runtime_checkable
class JobHandler(Protocol):
    """One job type's execution. Implementations receive only safe metadata."""

    def execute(self, context: JobExecutionContext) -> None:
        """Run the job; raise :class:`JobHandlerError` for a classified failure."""
        ...


class JobHandlerRegistry:
    """An explicit job_type -> handler map.

    There is no dynamic import, no entry-point scan and no module loading from a string:
    a job type is executable only after an explicit :meth:`register` call in the process
    that runs the worker. Registering the same job type twice fails closed.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        require_worker_token(job_type, "job_type")
        if not callable(getattr(handler, "execute", None)):
            raise DomainError(ERROR_WORKER_CONFIG, "a handler must provide execute(context)")
        if job_type in self._handlers:
            raise DomainError(
                ERROR_WORKER_CONFIG,
                "this job type already has a registered handler",
                details={"job_type": job_type},
            )
        self._handlers[job_type] = handler

    def resolve(self, job_type: str) -> JobHandler:
        handler = self._handlers.get(job_type)
        if handler is None:
            raise DomainError(
                ERROR_WORKER_HANDLER_NOT_FOUND,
                "no handler is registered for this job type",
                details={"job_type": job_type},
            )
        return handler

    def registered_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def __contains__(self, job_type: object) -> bool:
        return job_type in self._handlers


__all__ = [
    "ERROR_WORKER_CLAIM",
    "ERROR_WORKER_CONFIG",
    "ERROR_WORKER_EXECUTION",
    "ERROR_WORKER_HANDLER_NOT_FOUND",
    "ERROR_WORKER_LEASE_EXPIRED",
    "JobExecutionContext",
    "JobExecutionRepository",
    "JobExecutionState",
    "JobHandler",
    "JobHandlerError",
    "JobHandlerRegistry",
    "JobLease",
    "PAYLOAD_DIGEST_PATTERN",
    "WORKER_TOKEN_PATTERN",
    "require_aware_timestamp",
    "require_positive_int",
    "require_worker_error_code",
    "require_worker_token",
]
