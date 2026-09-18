"""T84 offline tests: background job worker contract without a database.

Nothing here opens a connection or performs any I/O: the execution boundary is the
in-memory adapter and the handler is the recording handler. The suite proves the claim
predicate, ``lease_id`` + ``attempt`` fencing, heartbeat, expiry recovery, the two-step
retry transition, the five worker outcomes and the at-least-once boundary.

The real PostgreSQL scenarios live in ``tests/test_t84_job_worker_integration.py`` and only
run when ``STEELAI_TEST_DATABASE_URL`` names a safe test database.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from steelai.enterprise_lab.adapters.worker_memory import (
    MemoryJobExecutionRepository,
    RecordedJobCall,
    RecordingJobHandler,
)
from steelai.enterprise_lab.application.job_worker import (
    OUTCOME_FAILURE_UNRECORDED,
    OUTCOME_FAILED_TERMINAL,
    OUTCOME_PROPERTIES,
    OUTCOME_RETRY_SCHEDULED,
    OUTCOME_SUCCEEDED,
    OUTCOME_SUCCESS_UNRECORDED,
    PERSISTED_FIELDS,
    JobOutcome,
    JobWorker,
    JobWorkerConfig,
)
from steelai.enterprise_lab.domain.models import (
    ALLOWED_JOB_TRANSITIONS,
    BackgroundJob,
    DomainError,
    ERROR_JOB_TRANSITION,
    JobState,
)
from steelai.enterprise_lab.ports.workers import (
    ERROR_WORKER_CLAIM,
    ERROR_WORKER_CONFIG,
    ERROR_WORKER_EXECUTION,
    ERROR_WORKER_HANDLER_NOT_FOUND,
    ERROR_WORKER_LEASE_EXPIRED,
    JobExecutionContext,
    JobExecutionRepository,
    JobExecutionState,
    JobHandler,
    JobHandlerError,
    JobHandlerRegistry,
    JobLease,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "steelai" / "enterprise_lab"
PYTHON = Path(sys.executable)
FORBIDDEN_RUNTIME_MODULES = ("sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg", "kafka")
DISALLOWED_WORKER_MODULES = (
    "threading",
    "asyncio",
    "schedule",
    "time",
    "socket",
    "requests",
    "urllib",
    "http",
    "subprocess",
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

#: Sensitive fragments a handler must never be able to leak through an outcome or a row.
LEAKY_FRAGMENTS = (
    "t0psecret",
    "postgresql://",
    "db-host",
    "C:\\data",
    "sample.csv",
    "ENT-LEAKY-001",
    "DomainError",
    "leaked-token",
)


def _leaky_domain_error() -> DomainError:
    """A handler failure that carries every kind of sensitive text a leak could expose."""
    return DomainError(
        "ENT-LEAKY-001",
        "connection to postgresql://steelai:t0psecret@db-host:5432/steelai_enterprise_test failed "
        "while reading C:\\data\\raw\\sample.csv with leaked-token",
        details={
            "url": "postgresql://steelai:t0psecret@db-host:5432/steelai_enterprise_test",
            "path": "C:\\data\\raw\\sample.csv",
            "token": "leaked-token",
        },
    )


def _valid_outcome(status: str, *, attempt: int = 1, lease_id: str = "lease_x") -> JobOutcome:
    """Build a :class:`JobOutcome` that satisfies the status invariants exactly."""
    state, offset, needs_code = PERSISTED_FIELDS[status]
    return JobOutcome(
        job_id="job_t84demo001",
        job_type="artifact-verify",
        run_id="run_t84demo001",
        attempt=attempt,
        status=status,
        lease_id=lease_id,
        error_code="ENT-HANDLER-TIMEOUT" if needs_code else None,
        state=state,
        attempts=(attempt + offset) if offset is not None else None,
    )


def _job(
    job_id: str = "job_t84demo001",
    *,
    job_type: str = "artifact-verify",
    run_id: str = "run_t84demo001",
    idempotency_key: str = "idem-t84-demo-001",
    payload_digest: str = DIGEST_A,
    max_attempts: int = 3,
    created_at: str | None = None,
) -> BackgroundJob:
    return BackgroundJob.create(
        job_id=job_id,
        job_type=job_type,
        run_id=run_id,
        idempotency_key=idempotency_key,
        payload_digest=payload_digest,
        max_attempts=max_attempts,
        created_at=created_at,
    )


class _FailingConfirmRepository:
    """Execution proxy whose success confirmation always fails."""

    def __init__(self, inner: MemoryJobExecutionRepository, error_code: str) -> None:
        self._inner = inner
        self._error_code = error_code
        self.confirm_attempts = 0

    def claim_next(self, **kwargs: object):
        return self._inner.claim_next(**kwargs)  # type: ignore[arg-type]

    def heartbeat(self, job_id: str, lease_id: str, attempt: int):
        return self._inner.heartbeat(job_id, lease_id, attempt)

    def mark_succeeded(self, job_id: str, lease_id: str, attempt: int):
        self.confirm_attempts += 1
        raise DomainError(self._error_code, "the database refused to confirm this execution")

    def mark_failed(self, job_id: str, lease_id: str, attempt: int, error_code: str, **kwargs: object):
        return self._inner.mark_failed(job_id, lease_id, attempt, error_code, **kwargs)  # type: ignore[arg-type]

    def reclaim_expired(self, **kwargs: object):
        return self._inner.reclaim_expired(**kwargs)  # type: ignore[arg-type]


class _FailingFailureRepository:
    """Execution proxy whose failure record always fails."""

    def __init__(self, inner: MemoryJobExecutionRepository, error_code: str) -> None:
        self._inner = inner
        self._error_code = error_code
        self.failure_record_attempts = 0

    def claim_next(self, **kwargs: object):
        return self._inner.claim_next(**kwargs)  # type: ignore[arg-type]

    def heartbeat(self, job_id: str, lease_id: str, attempt: int):
        return self._inner.heartbeat(job_id, lease_id, attempt)

    def mark_succeeded(self, job_id: str, lease_id: str, attempt: int):
        return self._inner.mark_succeeded(job_id, lease_id, attempt)

    def mark_failed(self, job_id: str, lease_id: str, attempt: int, error_code: str, **kwargs: object):
        self.failure_record_attempts += 1
        raise DomainError(self._error_code, "the database refused to record this failure")

    def reclaim_expired(self, **kwargs: object):
        return self._inner.reclaim_expired(**kwargs)  # type: ignore[arg-type]


class WorkerHarness(unittest.TestCase):
    """Shared fixture: one in-memory execution boundary and one recording handler."""

    def setUp(self) -> None:
        self.jobs = MemoryJobExecutionRepository()
        self.handler = RecordingJobHandler()
        self.registry = JobHandlerRegistry()
        self.registry.register("artifact-verify", self.handler)
        self.config = JobWorkerConfig(worker_id="worker_local_001", lease_timeout_seconds=30)
        self.worker = JobWorker(self.jobs, self.registry, self.config)

    def add_job(self, job_id: str = "job_t84demo001", **overrides: object) -> BackgroundJob:
        job = _job(job_id, **overrides)  # type: ignore[arg-type]
        self.jobs.add(job)
        return job


class ClaimAndExecuteTests(WorkerHarness):
    """The happy path, the claim contract and the transaction discipline."""

    def test_queued_is_leased_then_succeeded(self) -> None:
        job = self.add_job()
        self.assertEqual(self.jobs.get(job.job_id).state, JobState.QUEUED.value)
        outcome = self.worker.run_once()
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCEEDED)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.SUCCEEDED.value)
        self.assertIsNone(stored.lease_id, "a finished job must not keep a lease")
        self.assertIsNone(stored.error_code)
        self.assertEqual(stored.attempts, 1, "the attempt counter is preserved on success")

    def test_the_first_claim_is_attempt_one_without_incrementing_attempts(self) -> None:
        job = self.add_job()
        lease = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_first")
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(lease.attempt, 1)
        self.assertEqual(lease.job.attempts, 1)
        self.assertEqual(self.jobs.get(job.job_id).attempts, 1, "the first claim does not increment")

    def test_the_handler_runs_after_the_claim_boundary_closed(self) -> None:
        self.add_job()
        observed: list[bool] = []
        inner = self.jobs

        class _BoundaryObservingHandler:
            def execute(self, context: JobExecutionContext) -> None:
                observed.append(inner.in_short_transaction)

        registry = JobHandlerRegistry()
        registry.register("artifact-verify", _BoundaryObservingHandler())
        JobWorker(self.jobs, registry, self.config).run_once()
        self.assertEqual(observed, [False], "the handler must run with no open boundary")
        self.assertFalse(self.jobs.in_short_transaction)

    def test_the_handler_receives_only_safe_metadata(self) -> None:
        job = self.add_job()
        self.worker.run_once()
        call = self.handler.calls[0]
        self.assertIsInstance(call, RecordedJobCall)
        self.assertEqual(call.job_id, job.job_id)
        self.assertEqual(call.attempt, 1)
        self.assertEqual(call.idempotency_key, job.idempotency_key)
        self.assertEqual(call.payload_digest, DIGEST_A)
        context = JobExecutionContext(
            job_id=job.job_id,
            job_type=job.job_type,
            run_id=job.run_id,
            attempt=1,
            max_attempts=job.max_attempts,
            payload_digest=DIGEST_A,
            idempotency_key=job.idempotency_key,
            heartbeat=lambda: None,  # type: ignore[arg-type,return-value]
        )
        projection = context.to_dict()
        self.assertEqual(
            set(projection),
            {
                "job_id",
                "job_type",
                "run_id",
                "attempt",
                "max_attempts",
                "payload_digest",
                "idempotency_key",
            },
            "the context exposes only safe metadata",
        )
        rendered = str(projection)
        for forbidden in ("C:\\", "/data/", "password", "postgresql://", "SELECT ", "connection"):
            self.assertNotIn(forbidden, rendered, f"the context must not expose {forbidden}")

    def test_a_batch_stops_when_nothing_is_claimable(self) -> None:
        self.add_job("job_t84demo001")
        self.add_job("job_t84demo002", idempotency_key="idem-t84-demo-002")
        outcomes = self.worker.run_batch(limit=5)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual({outcome.status for outcome in outcomes}, {OUTCOME_SUCCEEDED})
        self.assertEqual(self.worker.run_once(), None)
        self.assertEqual(self.worker.run_batch(limit=3), ())


class HeartbeatTests(WorkerHarness):
    """The heartbeat is fenced, finite and extends the lease."""

    def test_heartbeat_uses_the_current_lease_and_extends_it(self) -> None:
        job = self.add_job()
        lease = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_hb")
        assert lease is not None
        self.jobs.advance(10)
        refreshed = self.jobs.heartbeat(lease.job_id, lease.lease_id, lease.attempt)
        self.assertEqual(refreshed.state, JobState.LEASED.value)
        self.assertEqual(refreshed.lease_id, "lease_hb")
        self.assertGreater(refreshed.updated_at, lease.leased_at)
        self.assertEqual(self.jobs.get(job.job_id).updated_at, refreshed.updated_at)

    def test_the_handler_can_heartbeat_during_execution(self) -> None:
        self.add_job()
        self.handler.heartbeat_next(2)
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCEEDED)
        self.assertEqual(len(self.handler.heartbeat_results), 2)
        for state in self.handler.heartbeat_results:
            self.assertEqual(state.state, JobState.LEASED.value)

    def test_heartbeat_rejects_a_stale_lease(self) -> None:
        self.add_job()
        stale = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_old")
        assert stale is not None
        self.jobs.advance(31)
        self.assertEqual(len(self.worker.reclaim_expired()), 1)
        with self.assertRaises(DomainError) as captured:
            self.jobs.heartbeat(stale.job_id, stale.lease_id, stale.attempt)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CLAIM)

    def test_heartbeat_rejects_a_wrong_attempt_and_an_unleased_job(self) -> None:
        job = self.add_job()
        lease = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_hb2")
        assert lease is not None
        with self.assertRaises(DomainError) as wrong_attempt:
            self.jobs.heartbeat(job.job_id, "lease_hb2", 2)
        self.assertEqual(wrong_attempt.exception.code, ERROR_WORKER_CLAIM)
        with self.assertRaises(DomainError) as wrong_lease:
            self.jobs.heartbeat(job.job_id, "lease_other", 1)
        self.assertEqual(wrong_lease.exception.code, ERROR_WORKER_CLAIM)
        self.jobs.mark_succeeded(job.job_id, "lease_hb2", 1)
        with self.assertRaises(DomainError) as not_leased:
            self.jobs.heartbeat(job.job_id, "lease_hb2", 1)
        self.assertEqual(not_leased.exception.code, ERROR_WORKER_CLAIM)


class LeaseRecoveryTests(WorkerHarness):
    """Expired leases are recovered with the frozen state machine."""

    def test_a_live_lease_is_not_reclaimed(self) -> None:
        self.add_job()
        self.worker.run_once()
        self.add_job("job_t84demo002", idempotency_key="idem-t84-demo-002")
        self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_live")
        self.jobs.advance(29)
        self.assertEqual(self.worker.reclaim_expired(), (), "a live lease must not be reclaimed")

    def test_an_expired_lease_returns_to_retrying_with_a_new_attempt(self) -> None:
        job = self.add_job()
        lease = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_expired")
        assert lease is not None
        self.jobs.advance(31)
        reclaimed = self.worker.reclaim_expired()
        self.assertEqual(len(reclaimed), 1)
        entry = reclaimed[0]
        self.assertEqual(entry.state, JobState.RETRYING.value)
        self.assertEqual(entry.attempts, 2, "recovery consumes an attempt")
        self.assertIsNone(entry.lease_id)
        self.assertEqual(entry.error_code, ERROR_WORKER_LEASE_EXPIRED)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.RETRYING.value)
        self.assertEqual(stored.attempts, 2)

    def test_an_expired_lease_at_the_attempt_limit_becomes_failed(self) -> None:
        job = self.add_job(max_attempts=1)
        self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_last")
        self.jobs.advance(31)
        reclaimed = self.worker.reclaim_expired()
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].state, JobState.FAILED.value)
        self.assertEqual(reclaimed[0].attempts, 1, "the attempt budget is exhausted")
        self.assertEqual(reclaimed[0].error_code, ERROR_WORKER_LEASE_EXPIRED)
        self.assertEqual(self.jobs.get(job.job_id).state, JobState.FAILED.value)

    def test_a_recovered_job_is_claimed_again_with_a_brand_new_lease(self) -> None:
        job = self.add_job()
        first = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_one")
        assert first is not None
        self.jobs.advance(31)
        self.worker.reclaim_expired()
        second = self.jobs.claim_next(worker_id="worker_local_002", lease_id="lease_two")
        assert second is not None
        self.assertNotEqual(first.lease_id, second.lease_id)
        self.assertEqual(second.attempt, 2)
        self.assertEqual(self.jobs.get(job.job_id).lease_id, "lease_two")

    def test_every_claim_uses_a_different_lease_id(self) -> None:
        self.add_job("job_t84demo001")
        self.add_job("job_t84demo002", idempotency_key="idem-t84-demo-002")
        outcomes = self.worker.run_batch(limit=5)
        lease_ids = [outcome.lease_id for outcome in outcomes]
        self.assertEqual(len(lease_ids), 2)
        self.assertEqual(len(set(lease_ids)), 2)


class FencingTests(WorkerHarness):
    """Every worker write is fenced by ``job_id + lease_id + attempt``."""

    def _stale_lease(self) -> JobLease:
        self.add_job()
        stale = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_stale")
        assert stale is not None
        self.jobs.advance(31)
        self.worker.reclaim_expired()
        fresh = self.jobs.claim_next(worker_id="worker_local_002", lease_id="lease_fresh")
        assert fresh is not None
        return stale

    def test_an_expired_worker_cannot_confirm_success(self) -> None:
        stale = self._stale_lease()
        with self.assertRaises(DomainError) as captured:
            self.jobs.mark_succeeded(stale.job_id, stale.lease_id, stale.attempt)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CLAIM)
        stored = self.jobs.get(stale.job_id)
        self.assertEqual(stored.state, JobState.LEASED.value)
        self.assertEqual(stored.lease_id, "lease_fresh", "the new lease is untouched")

    def test_an_expired_worker_cannot_record_a_failure(self) -> None:
        stale = self._stale_lease()
        stored_before = self.jobs.get(stale.job_id)
        with self.assertRaises(DomainError) as captured:
            self.jobs.mark_failed(
                stale.job_id,
                stale.lease_id,
                stale.attempt,
                "ENT-HANDLER-STALE",
                retryable=True,
            )
        self.assertEqual(captured.exception.code, ERROR_WORKER_CLAIM)
        stored = self.jobs.get(stale.job_id)
        self.assertEqual(stored.updated_at, stored_before.updated_at, "no write may land")
        self.assertEqual(stored.error_code, stored_before.error_code)
        self.assertEqual(stored.state, JobState.LEASED.value)

    def test_a_lost_lease_reports_a_classified_failure_through_the_worker(self) -> None:
        self.add_job()
        stale = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_lost")
        assert stale is not None
        self.jobs.advance(31)
        self.worker.reclaim_expired()
        # The old worker still runs its handler, and the handler fails: neither the heartbeat
        # nor the failure record can be written, so the outcome must not claim anything.
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        outcome = self.worker._execute(stale)  # noqa: SLF001 - the stale worker's own path
        self.assertEqual(outcome.status, OUTCOME_FAILURE_UNRECORDED)
        self.assertFalse(outcome.handler_succeeded)
        self.assertFalse(outcome.persistence_state_known)
        self.assertEqual(outcome.error_code, ERROR_WORKER_CLAIM)

    def test_a_stale_worker_that_succeeded_reports_success_unrecorded(self) -> None:
        self.add_job()
        stale = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_lost_two")
        assert stale is not None
        self.jobs.advance(31)
        self.worker.reclaim_expired()
        outcome = self.worker._execute(stale)  # noqa: SLF001 - the stale worker's own path
        self.assertEqual(outcome.status, OUTCOME_SUCCESS_UNRECORDED)
        self.assertTrue(outcome.handler_succeeded)
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.reexecution_possible, "the job may run again")

    def test_a_repeated_confirmation_of_the_same_lease_is_refused(self) -> None:
        job = self.add_job()
        lease = self.jobs.claim_next(worker_id="worker_local_001", lease_id="lease_once")
        assert lease is not None
        self.jobs.mark_succeeded(job.job_id, lease.lease_id, lease.attempt)
        with self.assertRaises(DomainError) as captured:
            self.jobs.mark_succeeded(job.job_id, lease.lease_id, lease.attempt)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CLAIM)


class FailureAndOutcomeTests(WorkerHarness):
    """Failure classification, the retry transition and the five outcomes."""

    def test_a_retryable_handler_failure_enters_retrying_with_attempt_plus_one(self) -> None:
        job = self.add_job()
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_RETRY_SCHEDULED)
        self.assertFalse(outcome.handler_succeeded)
        self.assertTrue(outcome.persistence_state_known)
        self.assertTrue(outcome.reexecution_possible)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.RETRYING.value)
        self.assertEqual(stored.attempts, 2, "the retry consumes an attempt")
        self.assertIsNone(stored.lease_id)
        self.assertEqual(stored.error_code, "ENT-HANDLER-TIMEOUT")

    def test_a_non_retryable_handler_failure_is_terminal(self) -> None:
        job = self.add_job()
        self.handler.fail_next("ENT-HANDLER-REJECTED", retryable=False)
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILED_TERMINAL)
        self.assertFalse(outcome.reexecution_possible)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.FAILED.value)
        self.assertEqual(stored.attempts, 1)
        self.assertIsNone(stored.lease_id)
        self.assertEqual(stored.error_code, "ENT-HANDLER-REJECTED")

    def test_a_retryable_failure_at_the_attempt_limit_is_terminal(self) -> None:
        job = self.add_job(max_attempts=2)
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True, times=2)
        first = self.worker.run_once()
        assert first is not None
        self.assertEqual(first.status, OUTCOME_RETRY_SCHEDULED)
        second = self.worker.run_once()
        assert second is not None
        self.assertEqual(second.attempt, 2)
        self.assertEqual(second.status, OUTCOME_FAILED_TERMINAL, "the budget is exhausted")
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.FAILED.value)
        self.assertEqual(stored.attempts, 2)
        self.assertEqual(self.worker.run_once(), None, "a failed job is never claimed again")

    def test_a_retried_job_executes_again_with_the_same_job_id_and_a_larger_attempt(self) -> None:
        job = self.add_job()
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        self.worker.run_once()
        self.worker.run_once()
        self.assertEqual(self.handler.job_ids, [job.job_id, job.job_id])
        self.assertEqual(self.handler.attempts, [1, 2])
        self.assertEqual(
            len(set(self.handler.idempotency_keys)), 1, "the idempotency key is stable"
        )

    def test_an_unregistered_job_type_fails_terminally_with_the_fixed_code(self) -> None:
        job = self.add_job(job_type="unknown-job-type")
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILED_TERMINAL)
        self.assertEqual(outcome.error_code, ERROR_WORKER_HANDLER_NOT_FOUND)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.FAILED.value)
        self.assertEqual(stored.error_code, ERROR_WORKER_HANDLER_NOT_FOUND)
        self.assertIsNone(stored.lease_id)

    def test_an_unknown_handler_exception_is_mapped_to_the_fixed_safe_code(self) -> None:
        job = self.add_job()
        self.handler.raise_next(
            RuntimeError("exploded on postgresql://steelai:t0psecret@host:5432/steelai while reading C:\\data\\raw.csv")
        )
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.error_code, ERROR_WORKER_EXECUTION)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.error_code, ERROR_WORKER_EXECUTION)
        self.assertEqual(stored.state, JobState.RETRYING.value, "an unknown failure is retried")
        rendered = f"{outcome.to_dict()} {stored.to_dict()}"
        for forbidden in ("t0psecret", "postgresql://", "host:5432", "C:\\data", "RuntimeError", "exploded"):
            self.assertNotIn(forbidden, rendered)

    def test_a_handler_error_carries_only_a_safe_code(self) -> None:
        error = JobHandlerError("ENT-HANDLER-TIMEOUT", retryable=True)
        self.assertEqual(str(error), "ENT-HANDLER-TIMEOUT")
        self.assertTrue(error.retryable)
        with self.assertRaises(DomainError) as captured:
            JobHandlerError("failed at https://host/queue?token=abc", retryable=False)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
        with self.assertRaises(DomainError) as path_error:
            JobHandlerError("C:\\data\\raw.csv", retryable=False)
        self.assertEqual(path_error.exception.code, ERROR_WORKER_CONFIG)

    def test_success_unrecorded_means_the_handler_ran_but_the_state_is_unknown(self) -> None:
        job = self.add_job()
        execution = _FailingConfirmRepository(self.jobs, ERROR_WORKER_CLAIM)
        worker = JobWorker(execution, self.registry, self.config)  # type: ignore[arg-type]
        outcome = worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCESS_UNRECORDED)
        self.assertTrue(outcome.handler_succeeded, "the handler really did run")
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.reexecution_possible, "the job may run again after expiry")
        self.assertEqual(execution.confirm_attempts, 1)
        self.assertEqual(len(self.handler.calls), 1)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.LEASED.value, "the lost lease is still held")
        self.assertNotEqual(outcome.status, OUTCOME_SUCCEEDED, "it must not be reported as final")

    def test_failure_unrecorded_means_nothing_was_confirmed(self) -> None:
        job = self.add_job()
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        execution = _FailingFailureRepository(self.jobs, ERROR_WORKER_CLAIM)
        worker = JobWorker(execution, self.registry, self.config)  # type: ignore[arg-type]
        outcome = worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILURE_UNRECORDED)
        self.assertFalse(outcome.handler_succeeded)
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.reexecution_possible)
        self.assertEqual(execution.failure_record_attempts, 1)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.LEASED.value)
        self.assertIsNone(stored.error_code, "no half-applied failure code")

    def test_an_unknown_outcome_status_is_rejected(self) -> None:
        for status in ("unacknowledged", "completed", "", "SUCCEEDED", None):
            with self.subTest(status=status), self.assertRaises(DomainError) as captured:
                JobOutcome(
                    job_id="job_t84demo001",
                    job_type="artifact-verify",
                    run_id="run_t84demo001",
                    attempt=1,
                    status=status,  # type: ignore[arg-type]
                    lease_id="lease_x",
                )
            self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)

    def test_the_outcome_property_table_is_exactly_the_agreed_contract(self) -> None:
        expected = {
            OUTCOME_SUCCEEDED: (True, True, False),
            OUTCOME_RETRY_SCHEDULED: (False, True, True),
            OUTCOME_FAILED_TERMINAL: (False, True, False),
            OUTCOME_SUCCESS_UNRECORDED: (True, False, True),
            OUTCOME_FAILURE_UNRECORDED: (False, False, True),
        }
        self.assertEqual(set(OUTCOME_PROPERTIES), set(expected))
        self.assertEqual(set(PERSISTED_FIELDS), set(expected))
        for status, properties in expected.items():
            with self.subTest(status=status):
                outcome = _valid_outcome(status)
                self.assertEqual(
                    (
                        outcome.handler_succeeded,
                        outcome.persistence_state_known,
                        outcome.reexecution_possible,
                    ),
                    properties,
                )
                self.assertEqual(OUTCOME_PROPERTIES[status], properties)

    def test_one_failing_job_does_not_stop_the_batch(self) -> None:
        first = self.add_job("job_t84demo001")
        second = self.add_job("job_t84demo002", idempotency_key="idem-t84-demo-002")
        third = self.add_job("job_t84demo003", idempotency_key="idem-t84-demo-003")
        self.handler.fail_next("ENT-HANDLER-REJECTED", retryable=False)
        outcomes = self.worker.run_batch(limit=5)
        by_id = {outcome.job_id: outcome.status for outcome in outcomes}
        self.assertEqual(by_id[first.job_id], OUTCOME_FAILED_TERMINAL)
        self.assertEqual(by_id[second.job_id], OUTCOME_SUCCEEDED)
        self.assertEqual(by_id[third.job_id], OUTCOME_SUCCEEDED)
        self.assertEqual(len(outcomes), 3)


class _RefusingClaimRepository:
    """Execution proxy whose claim fails, to prove repository errors are not swallowed."""

    def __init__(self, error_code: str) -> None:
        self._error_code = error_code

    def claim_next(self, **kwargs: object):
        raise DomainError(self._error_code, "the database refused to claim a job")

    def heartbeat(self, job_id: str, lease_id: str, attempt: int):
        raise DomainError(self._error_code, "unreachable in this test")

    def mark_succeeded(self, job_id: str, lease_id: str, attempt: int):
        raise DomainError(self._error_code, "unreachable in this test")

    def mark_failed(self, job_id: str, lease_id: str, attempt: int, error_code: str, **kwargs: object):
        raise DomainError(self._error_code, "unreachable in this test")

    def reclaim_expired(self, **kwargs: object):
        raise DomainError(self._error_code, "unreachable in this test")


class HandlerExceptionBoundaryTests(WorkerHarness):
    """Every handler ``Exception`` is unclassified; it must never escape or leak."""

    def test_a_handler_domain_error_does_not_break_the_batch_or_leak(self) -> None:
        class _SelectiveLeakyHandler:
            """Raises a leaky DomainError for one job id and succeeds for the others."""

            def __init__(self, failing_job_id: str) -> None:
                self._failing_job_id = failing_job_id
                self.calls: list[str] = []

            def execute(self, context: JobExecutionContext) -> None:
                self.calls.append(context.job_id)
                if context.job_id == self._failing_job_id:
                    raise _leaky_domain_error()

        first = self.add_job("job_t84demo001", max_attempts=2)
        second = self.add_job("job_t84demo002", idempotency_key="idem-t84-demo-002")
        third = self.add_job("job_t84demo003", idempotency_key="idem-t84-demo-003")
        handler = _SelectiveLeakyHandler(first.job_id)
        registry = JobHandlerRegistry()
        registry.register("artifact-verify", handler)
        worker = JobWorker(self.jobs, registry, self.config)

        # run_batch must not raise: a handler domain error is an ordinary unclassified failure.
        outcomes = worker.run_batch(limit=4)
        self.assertEqual(len(outcomes), 4, outcomes)
        self.assertEqual([outcome.job_id for outcome in outcomes], [first.job_id, first.job_id, second.job_id, third.job_id])

        # The first attempt was retryable, the second one (at the limit) is terminal.
        self.assertEqual(outcomes[0].status, OUTCOME_RETRY_SCHEDULED)
        self.assertEqual(outcomes[1].status, OUTCOME_FAILED_TERMINAL)
        for outcome in outcomes[:2]:
            self.assertEqual(outcome.error_code, ERROR_WORKER_EXECUTION)
        self.assertEqual(outcomes[2].status, OUTCOME_SUCCEEDED)
        self.assertEqual(outcomes[3].status, OUTCOME_SUCCEEDED)

        stored = self.jobs.get(first.job_id)
        self.assertEqual(stored.state, JobState.FAILED.value, "the job must not stay leased")
        self.assertIsNone(stored.lease_id, "the lease must be released")
        self.assertEqual(stored.error_code, ERROR_WORKER_EXECUTION)
        self.assertEqual(self.jobs.get(second.job_id).state, JobState.SUCCEEDED.value)
        self.assertEqual(self.jobs.get(third.job_id).state, JobState.SUCCEEDED.value)
        self.assertEqual(handler.calls, [first.job_id, first.job_id, second.job_id, third.job_id])

        rendered = " ".join(
            (
                str([outcome.to_dict() for outcome in outcomes]),
                str(stored.to_dict()),
                str(self.jobs.get(second.job_id).to_dict()),
                repr(outcomes),
            )
        )
        for fragment in LEAKY_FRAGMENTS:
            self.assertNotIn(fragment, rendered, f"the outcome leaked {fragment}")

    def test_a_handler_domain_error_at_the_attempt_limit_is_terminal(self) -> None:
        job = self.add_job(max_attempts=1)
        self.handler.raise_next(_leaky_domain_error())
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILED_TERMINAL)
        self.assertEqual(outcome.error_code, ERROR_WORKER_EXECUTION)
        self.assertEqual(outcome.state, JobState.FAILED.value)
        self.assertEqual(outcome.attempts, outcome.attempt)
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.state, JobState.FAILED.value)
        self.assertIsNone(stored.lease_id)
        self.assertEqual(stored.error_code, ERROR_WORKER_EXECUTION)
        self.assertEqual(self.worker.run_once(), None)

    def test_run_once_never_raises_a_handler_domain_error(self) -> None:
        self.add_job()
        self.handler.raise_next(_leaky_domain_error())
        outcome = self.worker.run_once()  # must return, not raise
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_RETRY_SCHEDULED)
        self.assertEqual(outcome.error_code, ERROR_WORKER_EXECUTION)
        for fragment in LEAKY_FRAGMENTS:
            self.assertNotIn(fragment, str(outcome.to_dict()))

    def test_a_handler_domain_error_is_recorded_like_any_unknown_failure(self) -> None:
        job = self.add_job()
        self.handler.raise_next(_leaky_domain_error())
        self.worker.run_once()
        stored = self.jobs.get(job.job_id)
        self.assertEqual(stored.error_code, ERROR_WORKER_EXECUTION)
        self.assertLessEqual(len(stored.error_code or ""), 64)
        self.assertNotIn("ENT-LEAKY-001", stored.to_dict().values())

    def test_base_exceptions_are_not_swallowed(self) -> None:
        for exception in (KeyboardInterrupt(), SystemExit(2)):
            with self.subTest(exception=type(exception).__name__):
                # A fresh boundary per signal, so the claim order is unambiguous.
                jobs = MemoryJobExecutionRepository()
                handler = RecordingJobHandler()
                registry = JobHandlerRegistry()
                registry.register("artifact-verify", handler)
                worker = JobWorker(jobs, registry, self.config)
                job = _job(f"job_t84signal{type(exception).__name__[:4]}".lower())
                jobs.add(job)
                handler.raise_next(exception)
                with self.assertRaises(type(exception)):
                    worker.run_once()
                # An operator signal aborts the run; the lease stays and is recovered later.
                self.assertEqual(jobs.get(job.job_id).state, JobState.LEASED.value)
                jobs.advance(31)
                reclaimed = worker.reclaim_expired()
                self.assertEqual([entry.job_id for entry in reclaimed], [job.job_id])

    def test_a_repository_claim_failure_is_not_swallowed(self) -> None:
        self.add_job()
        worker = JobWorker(
            _RefusingClaimRepository(ERROR_WORKER_CLAIM),  # type: ignore[arg-type]
            self.registry,
            self.config,
        )
        with self.assertRaises(DomainError) as captured:
            worker.run_batch(limit=3)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CLAIM)
        with self.assertRaises(DomainError) as single:
            worker.run_once()
        self.assertEqual(single.exception.code, ERROR_WORKER_CLAIM)

    def test_a_configuration_error_is_not_swallowed(self) -> None:
        self.add_job()
        with self.assertRaises(DomainError) as captured:
            self.worker.run_batch(limit=0)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
        self.assertEqual(self.handler.calls, [])

    def test_the_call_order_is_claim_handler_then_confirm(self) -> None:
        self.add_job()
        calls: list[str] = []
        inner = self.jobs

        class _OrderRecordingRepository:
            def claim_next(self, **kwargs: object):
                calls.append("claim")
                return inner.claim_next(**kwargs)  # type: ignore[arg-type]

            def heartbeat(self, job_id: str, lease_id: str, attempt: int):
                calls.append("heartbeat")
                return inner.heartbeat(job_id, lease_id, attempt)

            def mark_succeeded(self, job_id: str, lease_id: str, attempt: int):
                calls.append("mark_succeeded")
                return inner.mark_succeeded(job_id, lease_id, attempt)

            def mark_failed(self, job_id: str, lease_id: str, attempt: int, error_code: str, **kwargs: object):
                calls.append("mark_failed")
                return inner.mark_failed(job_id, lease_id, attempt, error_code, **kwargs)  # type: ignore[arg-type]

            def reclaim_expired(self, **kwargs: object):
                return inner.reclaim_expired(**kwargs)  # type: ignore[arg-type]

        class _OrderRecordingHandler:
            def execute(self, context: JobExecutionContext) -> None:
                calls.append("handler")

        registry = JobHandlerRegistry()
        registry.register("artifact-verify", _OrderRecordingHandler())
        JobWorker(_OrderRecordingRepository(), registry, self.config).run_once()  # type: ignore[arg-type]
        self.assertEqual(calls, ["claim", "handler", "mark_succeeded"])


class JobOutcomeInvariantTests(unittest.TestCase):
    """``JobOutcome`` can only express a self-consistent result."""

    def _make_outcome(self, **overrides: object) -> JobOutcome:
        base: dict[str, object] = {
            "job_id": "job_t84demo001",
            "job_type": "artifact-verify",
            "run_id": "run_t84demo001",
            "attempt": 1,
            "status": OUTCOME_SUCCEEDED,
            "lease_id": "lease_x",
            "state": JobState.SUCCEEDED.value,
            "attempts": 1,
            "error_code": None,
        }
        base.update(overrides)
        return JobOutcome(**base)  # type: ignore[arg-type]

    def test_every_status_has_a_valid_shape(self) -> None:
        for status in PERSISTED_FIELDS:
            with self.subTest(status=status):
                outcome = _valid_outcome(status)
                self.assertEqual(outcome.status, status)
                self.assertEqual(outcome.attempts, None if PERSISTED_FIELDS[status][1] is None else outcome.attempt + PERSISTED_FIELDS[status][1])  # type: ignore[operator]

    def test_contradictory_outcomes_are_refused(self) -> None:
        cases: dict[str, dict[str, object]] = {
            "succeeded with state=failed": {"status": OUTCOME_SUCCEEDED, "state": JobState.FAILED.value},
            "succeeded with an error code": {"status": OUTCOME_SUCCEEDED, "error_code": "ENT-HANDLER-TIMEOUT"},
            "succeeded with attempts=0": {"status": OUTCOME_SUCCEEDED, "attempts": 0},
            "succeeded without attempts": {"status": OUTCOME_SUCCEEDED, "attempts": None},
            "succeeded with the wrong attempts": {"status": OUTCOME_SUCCEEDED, "attempts": 2},
            "retry_scheduled with attempts==attempt": {
                "status": OUTCOME_RETRY_SCHEDULED,
                "state": JobState.RETRYING.value,
                "attempts": 1,
                "error_code": "ENT-HANDLER-TIMEOUT",
            },
            "retry_scheduled with state=failed": {
                "status": OUTCOME_RETRY_SCHEDULED,
                "state": JobState.FAILED.value,
                "attempts": 2,
                "error_code": "ENT-HANDLER-TIMEOUT",
            },
            "retry_scheduled without an error code": {
                "status": OUTCOME_RETRY_SCHEDULED,
                "state": JobState.RETRYING.value,
                "attempts": 2,
                "error_code": None,
            },
            "failed_terminal with state=retrying": {
                "status": OUTCOME_FAILED_TERMINAL,
                "state": JobState.RETRYING.value,
                "attempts": 1,
                "error_code": "ENT-HANDLER-REJECTED",
            },
            "failed_terminal without an error code": {
                "status": OUTCOME_FAILED_TERMINAL,
                "state": JobState.FAILED.value,
                "attempts": 1,
                "error_code": None,
            },
            "failed_terminal with the wrong attempts": {
                "status": OUTCOME_FAILED_TERMINAL,
                "state": JobState.FAILED.value,
                "attempts": 2,
                "error_code": "ENT-HANDLER-REJECTED",
            },
            "failed_terminal without attempts": {
                "status": OUTCOME_FAILED_TERMINAL,
                "state": JobState.FAILED.value,
                "attempts": None,
                "error_code": "ENT-HANDLER-REJECTED",
            },
            "success_unrecorded with a persisted state": {
                "status": OUTCOME_SUCCESS_UNRECORDED,
                "state": JobState.SUCCEEDED.value,
                "attempts": None,
                "error_code": ERROR_WORKER_CLAIM,
            },
            "success_unrecorded with an attempt counter": {
                "status": OUTCOME_SUCCESS_UNRECORDED,
                "state": None,
                "attempts": 1,
                "error_code": ERROR_WORKER_CLAIM,
            },
            "success_unrecorded without an error code": {
                "status": OUTCOME_SUCCESS_UNRECORDED,
                "state": None,
                "attempts": None,
                "error_code": None,
            },
            "failure_unrecorded with a persisted state": {
                "status": OUTCOME_FAILURE_UNRECORDED,
                "state": JobState.FAILED.value,
                "attempts": None,
                "error_code": ERROR_WORKER_CLAIM,
            },
            "failure_unrecorded without an error code": {
                "status": OUTCOME_FAILURE_UNRECORDED,
                "state": None,
                "attempts": None,
                "error_code": None,
            },
            "attempts as a bool": {"status": OUTCOME_SUCCEEDED, "state": JobState.SUCCEEDED.value, "attempts": True},
            "attempts as a negative number": {
                "status": OUTCOME_SUCCEEDED,
                "state": JobState.SUCCEEDED.value,
                "attempts": -1,
            },
            "attempts as a string": {"status": OUTCOME_SUCCEEDED, "state": JobState.SUCCEEDED.value, "attempts": "1"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name), self.assertRaises(DomainError) as captured:
                self._make_outcome(**overrides)
            self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)

    def test_a_boolean_attempt_counter_is_refused_for_retry_outcomes_too(self) -> None:
        with self.assertRaises(DomainError) as captured:
            self._make_outcome(
                status=OUTCOME_RETRY_SCHEDULED,
                state=JobState.RETRYING.value,
                attempts=True,
                error_code="ENT-HANDLER-TIMEOUT",
            )
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)

    def test_an_unsafe_error_code_is_refused(self) -> None:
        with self.assertRaises(DomainError) as captured:
            self._make_outcome(
                status=OUTCOME_FAILED_TERMINAL,
                state=JobState.FAILED.value,
                attempts=1,
                error_code="failed at https://host/queue?token=abc",
            )
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)

    def test_the_five_real_worker_paths_satisfy_the_invariants(self) -> None:
        """Every outcome the worker really produces must be constructible and consistent."""
        jobs = MemoryJobExecutionRepository()
        handler = RecordingJobHandler()
        registry = JobHandlerRegistry()
        job_types = (
            "path-success",
            "path-retry",
            "path-terminal",
            "path-success-unrecorded",
            "path-failure-unrecorded",
        )
        for job_type in job_types:
            registry.register(job_type, handler)
        config = JobWorkerConfig(worker_id="worker_local_001", lease_timeout_seconds=30)
        seen: list[JobOutcome] = []

        for index, job_type in enumerate(job_types, start=1):
            jobs.add(
                _job(
                    f"job_t84path{index:03d}",
                    job_type=job_type,
                    idempotency_key=f"idem-t84-path-{index:03d}",
                )
            )

        worker = JobWorker(jobs, registry, config)
        # Each path is scripted immediately before its own call: the recording handler
        # consumes scripted outcomes in call order, not per job type.
        seen.append(worker.run_once(job_types[0]))  # type: ignore[arg-type]
        handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        seen.append(worker.run_once(job_types[1]))  # type: ignore[arg-type]
        handler.fail_next("ENT-HANDLER-REJECTED", retryable=False)
        seen.append(worker.run_once(job_types[2]))  # type: ignore[arg-type]

        refusing_confirm = JobWorker(_FailingConfirmRepository(jobs, ERROR_WORKER_CLAIM), registry, config)  # type: ignore[arg-type]
        seen.append(refusing_confirm.run_once(job_types[3]))  # type: ignore[arg-type]
        handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        refusing_failure = JobWorker(_FailingFailureRepository(jobs, ERROR_WORKER_CLAIM), registry, config)  # type: ignore[arg-type]
        seen.append(refusing_failure.run_once(job_types[4]))  # type: ignore[arg-type]

        statuses = [outcome.status for outcome in seen if outcome is not None]
        self.assertEqual(
            statuses,
            [
                OUTCOME_SUCCEEDED,
                OUTCOME_RETRY_SCHEDULED,
                OUTCOME_FAILED_TERMINAL,
                OUTCOME_SUCCESS_UNRECORDED,
                OUTCOME_FAILURE_UNRECORDED,
            ],
        )
        for outcome in seen:
            assert outcome is not None
            state, offset, needs_code = PERSISTED_FIELDS[outcome.status]
            self.assertEqual(outcome.state, state)
            self.assertEqual(outcome.attempts, None if offset is None else outcome.attempt + offset)
            self.assertEqual(outcome.error_code is None, not needs_code)
            if state is None:
                self.assertFalse(outcome.persistence_state_known)
                self.assertTrue(outcome.reexecution_possible)
                self.assertNotEqual(outcome.status, OUTCOME_SUCCEEDED)


class RegistryTests(unittest.TestCase):
    """The registry is explicit and fails closed."""

    def test_registering_the_same_job_type_twice_fails_closed(self) -> None:
        registry = JobHandlerRegistry()
        registry.register("artifact-verify", RecordingJobHandler())
        with self.assertRaises(DomainError) as captured:
            registry.register("artifact-verify", RecordingJobHandler())
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
        self.assertEqual(registry.registered_types(), ("artifact-verify",))

    def test_resolving_an_unregistered_job_type_fails_with_the_fixed_code(self) -> None:
        registry = JobHandlerRegistry()
        with self.assertRaises(DomainError) as captured:
            registry.resolve("missing-job-type")
        self.assertEqual(captured.exception.code, ERROR_WORKER_HANDLER_NOT_FOUND)
        self.assertNotIn("missing-job-type", str(captured.exception).replace("missing-job-type", ""))

    def test_the_registry_rejects_unsafe_job_types_and_handlers(self) -> None:
        registry = JobHandlerRegistry()
        for bad_type in ("C:\\jobs\\run", "user@host", "job type", "", "a" * 80):
            with self.subTest(job_type=bad_type), self.assertRaises(DomainError) as captured:
                registry.register(bad_type, RecordingJobHandler())
            self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
        with self.assertRaises(DomainError) as captured_handler:
            registry.register("artifact-verify", object())  # type: ignore[arg-type]
        self.assertEqual(captured_handler.exception.code, ERROR_WORKER_CONFIG)

    def test_the_registry_never_loads_a_module_dynamically(self) -> None:
        source = (PACKAGE / "ports" / "workers.py").read_text(encoding="utf-8")
        for forbidden in ("importlib", "entry_points", "__import__", "pkgutil", "exec("):
            self.assertNotIn(forbidden, source, f"the registry must not use {forbidden}")


class ConfigurationTests(WorkerHarness):
    """Illegal configuration and illegal call arguments fail closed."""

    def test_illegal_worker_configuration_fails_closed(self) -> None:
        cases = {
            "empty worker_id": {"worker_id": ""},
            "worker_id with a colon": {"worker_id": "host:5432"},
            "worker_id with a path": {"worker_id": "C:\\worker"},
            "worker_id with a user": {"worker_id": "user@host"},
            "zero timeout": {"lease_timeout_seconds": 0},
            "negative timeout": {"lease_timeout_seconds": -5},
            "boolean timeout": {"lease_timeout_seconds": True},
            "string timeout": {"lease_timeout_seconds": "60"},
            "zero batch limit": {"batch_limit": 0},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name), self.assertRaises(DomainError) as captured:
                JobWorkerConfig(**overrides)  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)

    def test_illegal_call_limits_fail_closed(self) -> None:
        self.add_job()
        for bad_limit in (0, -3, True, "2", 1.5):
            with self.subTest(limit=bad_limit), self.assertRaises(DomainError) as captured:
                self.worker.run_batch(limit=bad_limit)  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
            with self.assertRaises(DomainError) as reclaim_error:
                self.worker.reclaim_expired(limit=bad_limit)  # type: ignore[arg-type]
            self.assertEqual(reclaim_error.exception.code, ERROR_WORKER_CONFIG)
        self.assertEqual(self.handler.calls, [], "a refused call must not execute anything")

    def test_illegal_claim_arguments_fail_closed(self) -> None:
        self.add_job()
        with self.assertRaises(DomainError) as captured:
            self.jobs.claim_next(worker_id="bad host", lease_id="lease_ok")
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
        with self.assertRaises(DomainError) as bad_lease:
            self.jobs.claim_next(worker_id="worker_ok", lease_id="lease/with/path")
        self.assertEqual(bad_lease.exception.code, ERROR_WORKER_CONFIG)
        with self.assertRaises(DomainError) as bad_reclaim:
            self.jobs.reclaim_expired(limit=1, lease_timeout_seconds=0)
        self.assertEqual(bad_reclaim.exception.code, ERROR_WORKER_CONFIG)

    def test_an_unsafe_worker_id_or_lease_id_cannot_be_built(self) -> None:
        with self.assertRaises(DomainError) as captured:
            JobLease(
                job=_job(), lease_id="lease_ok", attempt=1,
                leased_at="2026-09-18T10:00:00+00:00", worker_id="host:5432",
            )
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)


class DtoContractTests(unittest.TestCase):
    """The worker DTOs are immutable and validate themselves when built directly."""

    def _lease(self, **overrides: object) -> JobLease:
        job = overrides.pop("job", None)
        if job is None:
            job = _job().transition(
                JobState.LEASED,
                updated_at="2026-09-18T10:00:00+00:00",
                lease_id="lease_direct",
            )
        payload: dict[str, object] = {
            "job": job,
            "lease_id": "lease_direct",
            "attempt": 1,
            "leased_at": "2026-09-18T10:00:00+00:00",
            "worker_id": "worker_direct",
        }
        payload.update(overrides)
        return JobLease(**payload)  # type: ignore[arg-type]

    def test_a_valid_directly_constructed_lease_is_accepted(self) -> None:
        lease = self._lease()
        self.assertEqual(lease.attempt, 1)
        self.assertEqual(lease.job_id, "job_t84demo001")
        self.assertEqual(lease.last_activity_at, lease.leased_at)

    def test_a_lease_must_describe_a_leased_job(self) -> None:
        job = _job()
        queued = BackgroundJob(
            job_id=job.job_id, job_type=job.job_type, run_id=job.run_id, state=JobState.QUEUED.value,
            attempts=1, max_attempts=3, idempotency_key=job.idempotency_key,
            payload_digest=job.payload_digest, created_at=job.created_at, updated_at=job.updated_at,
        )
        with self.assertRaises(DomainError) as captured:
            self._lease(job=queued)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)
        for state in (JobState.SUCCEEDED, JobState.FAILED, JobState.RETRYING, JobState.CANCELLED):
            with self.subTest(state=state.value):
                other = BackgroundJob(
                    job_id=job.job_id, job_type=job.job_type, run_id=job.run_id, state=state.value,
                    attempts=1, max_attempts=3, idempotency_key=job.idempotency_key,
                    payload_digest=job.payload_digest, created_at=job.created_at,
                    updated_at=job.updated_at, lease_id="lease_direct",
                )
                with self.assertRaises(DomainError) as rejected:
                    self._lease(job=other)
                self.assertEqual(rejected.exception.code, ERROR_WORKER_CONFIG)

    def test_a_lease_attempt_must_match_the_job_attempts(self) -> None:
        with self.assertRaises(DomainError) as captured:
            self._lease(attempt=2)
        self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)

    def test_a_lease_rejects_a_naive_timestamp_and_a_mismatched_lease_id(self) -> None:
        with self.assertRaises(DomainError) as naive:
            self._lease(leased_at="2026-09-18T10:00:00")
        self.assertEqual(naive.exception.code, ERROR_WORKER_CONFIG)
        job = _job().transition(
            JobState.LEASED,
            updated_at="2026-09-18T10:00:00+00:00",
            lease_id="lease_other",
        )
        with self.assertRaises(DomainError) as mismatched:
            self._lease(job=job)
        self.assertEqual(mismatched.exception.code, ERROR_WORKER_CONFIG)

    def test_the_lease_is_immutable(self) -> None:
        lease = self._lease()
        with self.assertRaises(FrozenInstanceError):
            lease.attempt = 5  # type: ignore[misc]

    def test_the_execution_state_rejects_invalid_values(self) -> None:
        base = {
            "job_id": "job_t84demo001",
            "job_type": "artifact-verify",
            "state": JobState.SUCCEEDED.value,
            "attempts": 1,
            "max_attempts": 3,
            "updated_at": "2026-09-18T10:00:00+00:00",
        }
        self.assertIsInstance(JobExecutionState(**base), JobExecutionState)  # type: ignore[arg-type]
        cases = {
            "unknown state": {"state": "done"},
            "zero attempts": {"attempts": 0},
            "attempts above max": {"attempts": 4},
            "naive timestamp": {"updated_at": "2026-09-18T10:00:00"},
            "unsafe error code": {"error_code": "see https://host/path"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name), self.assertRaises(DomainError) as captured:
                JobExecutionState(**{**base, **overrides})  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_WORKER_CONFIG)


class LeaseClearTests(unittest.TestCase):
    """``BackgroundJob.transition`` can clear a lease without changing any other behaviour."""

    def test_clearing_the_lease_is_explicit(self) -> None:
        job = _job()
        leased = job.transition(
            JobState.LEASED, updated_at="2026-09-18T10:00:00+00:00", lease_id="lease_clear"
        )
        self.assertEqual(leased.lease_id, "lease_clear")
        succeeded = leased.transition(
            JobState.SUCCEEDED, updated_at="2026-09-18T10:01:00+00:00", error_code=None, clear_lease=True
        )
        self.assertIsNone(succeeded.lease_id)
        self.assertIsNone(succeeded.error_code)
        self.assertEqual(succeeded.state, JobState.SUCCEEDED.value)

    def test_setting_and_clearing_the_lease_at_once_is_refused(self) -> None:
        leased = _job().transition(
            JobState.LEASED, updated_at="2026-09-18T10:00:00+00:00", lease_id="lease_both"
        )
        with self.assertRaises(DomainError) as captured:
            leased.transition(
                JobState.SUCCEEDED,
                updated_at="2026-09-18T10:01:00+00:00",
                lease_id="lease_new",
                clear_lease=True,
            )
        self.assertEqual(captured.exception.code, ERROR_JOB_TRANSITION)

    def test_the_default_behaviour_still_keeps_the_lease(self) -> None:
        leased = _job().transition(
            JobState.LEASED, updated_at="2026-09-18T10:00:00+00:00", lease_id="lease_keep"
        )
        failed = leased.transition(
            JobState.FAILED, updated_at="2026-09-18T10:02:00+00:00", error_code="ENT-X"
        )
        self.assertEqual(failed.lease_id, "lease_keep", "the default keeps the current lease")

    def test_no_new_state_or_transition_was_added(self) -> None:
        self.assertEqual(
            {state.value for state in JobState},
            {"queued", "leased", "retrying", "succeeded", "failed", "cancelled"},
        )
        self.assertEqual(
            {state.value for state in ALLOWED_JOB_TRANSITIONS[JobState.LEASED]},
            {"succeeded", "failed"},
        )
        self.assertEqual(
            {state.value for state in ALLOWED_JOB_TRANSITIONS[JobState.FAILED]},
            {"retrying"},
        )


class RecordingHandlerTests(unittest.TestCase):
    """The recording handler is inert: no filesystem, network, subprocess or database."""

    def _context(self, handler: RecordingJobHandler) -> JobExecutionContext:
        return JobExecutionContext(
            job_id="job_t84demo001",
            job_type="artifact-verify",
            run_id="run_t84demo001",
            attempt=1,
            max_attempts=3,
            payload_digest=DIGEST_A,
            idempotency_key="idem-t84-demo-001",
            heartbeat=lambda: None,  # type: ignore[arg-type,return-value]
        )

    def test_the_recording_handler_performs_no_io(self) -> None:
        handler = RecordingJobHandler()
        context = self._context(handler)
        with mock.patch("socket.socket", side_effect=AssertionError("network access")), mock.patch(
            "builtins.open", side_effect=AssertionError("filesystem access")
        ), mock.patch("subprocess.run", side_effect=AssertionError("subprocess access")):
            handler.execute(context)
        self.assertEqual(handler.job_ids, ["job_t84demo001"])

    def test_the_execution_adapter_imports_no_io_library(self) -> None:
        imported = _imported_modules(PACKAGE / "adapters" / "worker_memory.py")
        for module in DISALLOWED_WORKER_MODULES:
            self.assertNotIn(module, imported, f"the offline adapter must not import {module}")

    def test_the_recording_handler_scripts_every_outcome(self) -> None:
        handler = RecordingJobHandler()
        handler.succeed()
        handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        handler.raise_next(RuntimeError("boom"))
        context = self._context(handler)
        handler.execute(context)
        with self.assertRaises(JobHandlerError):
            handler.execute(context)
        with self.assertRaises(RuntimeError):
            handler.execute(context)
        self.assertEqual(len(handler.calls), 3)


class ArchitectureBoundaryTests(unittest.TestCase):
    """T84 stays inside the hexagon and away from the default application."""

    def test_the_worker_has_no_daemon_loop_or_timer(self) -> None:
        source = (PACKAGE / "application" / "job_worker.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                self.fail("the worker must not contain a loop construct at all")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                "run_forever",
                "start",
                "loop",
            }:
                self.fail(f"the worker must not define {node.name}()")
        imported = _imported_modules(PACKAGE / "application" / "job_worker.py")
        for module in ("threading", "asyncio", "sched", "time", "signal"):
            self.assertNotIn(module, imported, f"the worker must not import {module}")
        self.assertNotIn("sleep(", source)

    def test_the_memory_adapter_and_worker_expose_no_long_running_call(self) -> None:
        worker_source = (PACKAGE / "application" / "job_worker.py").read_text(encoding="utf-8")
        for forbidden in ("def run_forever", "while True", "Timer(", "Thread("):
            self.assertNotIn(forbidden, worker_source)

    def test_the_inner_layers_import_no_database_or_background_framework(self) -> None:
        offenders: list[str] = []
        for relative in (
            "ports/workers.py",
            "application/job_worker.py",
            "adapters/worker_memory.py",
        ):
            for module in _imported_modules(PACKAGE / relative):
                head = module.split(".")[0]
                if head in FORBIDDEN_RUNTIME_MODULES or head in DISALLOWED_WORKER_MODULES:
                    offenders.append(f"{relative}: {module}")
        self.assertEqual(offenders, [])

    def test_the_ports_are_runtime_checkable_protocols(self) -> None:
        self.assertIsInstance(MemoryJobExecutionRepository(), JobExecutionRepository)
        self.assertIsInstance(RecordingJobHandler(), JobHandler)
        self.assertFalse(isinstance(object(), JobExecutionRepository))

    def test_the_default_application_does_not_import_the_worker_or_the_database(self) -> None:
        code = (
            "import sys\n"
            "import app  # noqa: F401\n"
            f"print(','.join(m for m in {FORBIDDEN_RUNTIME_MODULES!r} if m in sys.modules))\n"
            "print('steelai.enterprise_lab' in sys.modules)\n"
            "print('steelai.enterprise_lab.adapters.postgresql' in sys.modules)\n"
            "print('steelai.enterprise_lab.application.job_worker' in sys.modules)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "False", "the default application must not load the lab")
        self.assertEqual(lines[2].strip(), "False")
        self.assertEqual(lines[3].strip(), "False", "the default application must not load the worker")

    def test_the_public_import_paths_are_available_without_the_optional_dependency(self) -> None:
        code = (
            "import sys\n"
            "from steelai.enterprise_lab.ports import JobLease, JobExecutionRepository, JobHandler\n"
            "from steelai.enterprise_lab.application import JobWorker, JobWorkerConfig, JobOutcome\n"
            "from steelai.enterprise_lab.adapters import MemoryJobExecutionRepository, RecordingJobHandler\n"
            "import steelai.enterprise_lab as lab\n"
            f"print(','.join(m for m in {FORBIDDEN_RUNTIME_MODULES!r} if m in sys.modules))\n"
            "print('steelai.enterprise_lab.adapters.postgresql' in sys.modules)\n"
            "print(lab.JobWorker is JobWorker, lab.MemoryJobExecutionRepository is MemoryJobExecutionRepository)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "False")
        self.assertEqual(lines[2].strip(), "True True")

    def test_the_postgresql_package_exports_the_execution_adapter(self) -> None:
        code = (
            "from steelai.enterprise_lab.adapters.postgresql import PostgreSQLJobExecutionRepository\n"
            "import steelai.enterprise_lab.adapters.postgresql as package\n"
            "print('PostgreSQLJobExecutionRepository' in package.__all__)\n"
            "print(callable(PostgreSQLJobExecutionRepository))\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["True", "True"])


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


if __name__ == "__main__":
    unittest.main()
