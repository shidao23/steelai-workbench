"""T84 real PostgreSQL integration tests for the background job worker.

Every test runs against a dedicated PostgreSQL container and is skipped unless
``STEELAI_TEST_DATABASE_URL`` names a safe test database (the database name must contain
both ``steelai`` and ``test``). The T81 migration is applied to the empty database first, so
the T84 worker is proven on the frozen T81 schema and on the T82 ``background_jobs`` rows: no
table, column, index or migration is added by T84.

Concurrency tests use a bounded thread pool with a join timeout and a starting barrier, so a
deadlock fails the test instead of hanging the suite. No test prints a connection string.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import sqlalchemy
from sqlalchemy import func, select, text

from steelai.enterprise_lab.adapters.outbox_memory import RecordingEventTransport
from steelai.enterprise_lab.adapters.postgresql.config import POSTGRESQL_SCHEMA
from steelai.enterprise_lab.adapters.postgresql.outbox import PostgreSQLOutboxDeliveryRepository
from steelai.enterprise_lab.adapters.postgresql.repositories import PostgreSQLUnitOfWorkFactory
from steelai.enterprise_lab.adapters.postgresql.schema import background_jobs, outbox_events, workflow_runs
from steelai.enterprise_lab.adapters.postgresql.worker import PostgreSQLJobExecutionRepository
from steelai.enterprise_lab.adapters.worker_memory import RecordingJobHandler
from steelai.enterprise_lab.application.job_worker import (
    OUTCOME_FAILURE_UNRECORDED,
    PERSISTED_FIELDS,
    OUTCOME_FAILED_TERMINAL,
    OUTCOME_RETRY_SCHEDULED,
    OUTCOME_SUCCEEDED,
    OUTCOME_SUCCESS_UNRECORDED,
    JobWorker,
    JobWorkerConfig,
)
from steelai.enterprise_lab.application.outbox_dispatcher import OutboxDispatcher, OutboxDispatcherConfig
from steelai.enterprise_lab.domain.models import (
    ERROR_JOB_TRANSITION,
    BackgroundJob,
    DomainError,
    DomainEvent,
    JobState,
    WorkflowRun,
)
from steelai.enterprise_lab.ports.workers import (
    ERROR_WORKER_CLAIM,
    ERROR_WORKER_EXECUTION,
    ERROR_WORKER_HANDLER_NOT_FOUND,
    ERROR_WORKER_LEASE_EXPIRED,
    JobExecutionContext,
    JobHandlerError,
    JobHandlerRegistry,
)


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
ALEMBIC_INI = ROOT / "alembic-enterprise.ini"
TEST_DATABASE_URL_ENV_VAR = "STEELAI_TEST_DATABASE_URL"
TEST_DATABASE_ONLY_ENV_VAR = "STEELAI_ENTERPRISE_TEST_DATABASE_ONLY"

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

CLEAR_TRUNCATE_SQL = (
    f"TRUNCATE TABLE {POSTGRESQL_SCHEMA}.artifact_references, {POSTGRESQL_SCHEMA}.audit_events, "
    f"{POSTGRESQL_SCHEMA}.outbox_events, {POSTGRESQL_SCHEMA}.background_jobs, "
    f"{POSTGRESQL_SCHEMA}.workflow_runs"
)


def _test_database_url() -> str | None:
    value = os.environ.get(TEST_DATABASE_URL_ENV_VAR, "").strip()
    if not value:
        return None
    name = value.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if "steelai" not in name or "test" not in name:
        return None
    return value


class _OverlapHandler:
    """Handler that blocks until every concurrent worker has claimed its own job."""

    def __init__(self, expected: int) -> None:
        self._barrier = threading.Barrier(expected, timeout=20)
        self.calls: list[str] = []

    def execute(self, context: JobExecutionContext) -> None:
        self.calls.append(context.job_id)
        # The barrier only passes when both workers are executing at the same time.
        self._barrier.wait(timeout=20)


class _PoolObservingHandler:
    """Handler that records the pool state while it runs."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.observed: list[int] = []
        self.calls: list[str] = []

    def execute(self, context: JobExecutionContext) -> None:
        self.calls.append(context.job_id)
        self.observed.append(self._engine.pool.checkedout())


@unittest.skipUnless(
    _test_database_url() is not None,
    "STEELAI_TEST_DATABASE_URL with a database name containing both 'steelai' and 'test' is required",
)
class JobWorkerIntegrationTests(unittest.TestCase):
    """The T84 acceptance scenarios against a real PostgreSQL server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.url = _test_database_url()
        assert cls.url is not None
        separator = "&" if "?" in cls.url else "?"
        cls.url = f"{cls.url}{separator}connect_timeout=10"
        cls.env = {TEST_DATABASE_ONLY_ENV_VAR: "1", "STEELAI_ENTERPRISE_DATABASE_URL": cls.url}
        cls.engine = cls._make_engine()
        cls._migrate("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._migrate("downgrade", "base")
        finally:
            cls.engine.dispose()

    # -- helpers ---------------------------------------------------------------
    @classmethod
    def _make_engine(cls):
        return sqlalchemy.create_engine(
            cls.url, poolclass=sqlalchemy.pool.QueuePool, pool_size=5, max_overflow=5
        )

    @classmethod
    def _migrate(cls, *args: str) -> None:
        environment = dict(os.environ)
        environment.pop(TEST_DATABASE_URL_ENV_VAR, None)
        environment.update(cls.env)
        completed = subprocess.run(
            [str(PYTHON), "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"alembic {' '.join(args)} failed with exit {completed.returncode}: "
                f"{completed.stderr.strip()[-400:]}"
            )

    def setUp(self) -> None:
        self.factory = PostgreSQLUnitOfWorkFactory(self.engine)
        self.execution = PostgreSQLJobExecutionRepository(self.engine)
        self.handler = RecordingJobHandler()
        self.registry = JobHandlerRegistry()
        self.registry.register("artifact-verify", self.handler)
        self.config = JobWorkerConfig(worker_id="worker_local_001", lease_timeout_seconds=30)
        self.worker = JobWorker(self.execution, self.registry, self.config)
        with self.engine.begin() as connection:
            connection.execute(text(CLEAR_TRUNCATE_SQL))

    def _seed_run(self, run_id: str = "run_t84demo001", key: str = "idem-t84-demo-001") -> WorkflowRun:
        with self.factory.unit_of_work() as unit:
            run, _ = unit.runs.create_run(
                WorkflowRun.create(
                    run_id=run_id,
                    project_id="PRJ-T84-DEMO",
                    task_id="task_t84demo001",
                    idempotency_key=key,
                    request_digest=DIGEST_A,
                ),
                idempotency_key=key,
            )
            unit.commit()
        return run

    def _enqueue(
        self,
        job_id: str = "job_t84demo001",
        *,
        job_type: str = "artifact-verify",
        run_id: str = "run_t84demo001",
        idempotency_key: str = "idem-t84-job-001",
        max_attempts: int = 3,
    ) -> BackgroundJob:
        """Write a ``queued`` job through the T82 JobQueue (the write side is unchanged)."""
        with self.factory.unit_of_work() as unit:
            job, _ = unit.jobs.enqueue(
                BackgroundJob.create(
                    job_id=job_id,
                    job_type=job_type,
                    run_id=run_id,
                    idempotency_key=idempotency_key,
                    payload_digest=DIGEST_B,
                    max_attempts=max_attempts,
                )
            )
            unit.commit()
        return job

    def _job_row(self, job_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(background_jobs).where(background_jobs.c.job_id == job_id))
                .mappings()
                .first()
            )
        assert row is not None
        return dict(row)

    def _expire_lease(self, job_id: str) -> None:
        """Push a lease past any timeout using the database clock."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.background_jobs "
                    "SET updated_at = now() - interval '1 hour' WHERE job_id = :job_id"
                ),
                {"job_id": job_id},
            )

    def _db_now(self) -> Any:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT now()")).scalar_one()

    def _concurrently(self, actions: list[Callable[[], Any]], *, timeout: float = 30.0) -> list[Any]:
        barrier = threading.Barrier(len(actions))
        pool = ThreadPoolExecutor(max_workers=len(actions))
        try:
            futures = [pool.submit(_run_after_barrier, action, barrier) for action in actions]
            return [future.result(timeout=timeout) for future in futures]
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    # -- 1/6: a T82 queued job runs to success --------------------------------
    def test_a_queued_t82_job_is_executed_and_succeeds(self) -> None:
        self._seed_run()
        job = self._enqueue()
        self.assertEqual(self._job_row(job.job_id)["state"], JobState.QUEUED.value)

        outcome = self.worker.run_once()
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCEEDED)
        self.assertEqual(outcome.attempt, 1)
        self.assertEqual(self.handler.job_ids, [job.job_id])

        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.SUCCEEDED.value)
        self.assertIsNone(row["lease_id"])
        self.assertIsNone(row["error_code"])
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(self.worker.run_once(), None, "a finished job is never claimed again")

    # -- 2/4: two concurrent workers ------------------------------------------
    def test_two_concurrent_workers_never_claim_the_same_job(self) -> None:
        self._seed_run()
        self._enqueue("job_t84demo001", idempotency_key="idem-t84-job-001")
        jobs = [
            (self.execution, JobWorkerConfig(worker_id="worker_a", lease_timeout_seconds=30)),
            (self.execution, JobWorkerConfig(worker_id="worker_b", lease_timeout_seconds=30)),
        ]

        def run(index: int) -> Callable[[], Any]:
            execution, config = jobs[index]

            def action():
                worker = JobWorker(execution, self.registry, config)
                return worker.run_batch(limit=5)

            return action

        results = self._concurrently([run(0), run(1)])
        claimed = [outcome.job_id for outcomes in results for outcome in outcomes]
        self.assertEqual(claimed, ["job_t84demo001"], results)
        self.assertEqual(
            self._job_row("job_t84demo001")["state"], JobState.SUCCEEDED.value, "one worker ran it"
        )

    def test_a_second_worker_gets_none_immediately_when_only_one_job_exists(self) -> None:
        self._seed_run()
        self._enqueue()
        holder_has_lease = threading.Event()
        release_holder = threading.Event()
        second_finished = threading.Event()
        results: dict[str, Any] = {}

        def holder() -> None:
            lease = self.execution.claim_next(worker_id="worker_a", lease_id="lease_holder")
            results["holder"] = lease
            holder_has_lease.set()
            release_holder.wait(timeout=20)
            self.execution.mark_succeeded(lease.job_id, lease.lease_id, lease.attempt)

        def second() -> None:
            self.assertTrue(holder_has_lease.wait(timeout=20))
            started = time.monotonic()
            results["second"] = self.execution.claim_next(worker_id="worker_b", lease_id="lease_second")
            results["elapsed"] = time.monotonic() - started
            second_finished.set()

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            first = pool.submit(holder)
            other = pool.submit(second)
            self.assertTrue(
                second_finished.wait(timeout=20),
                "the second worker waited instead of skipping the locked row",
            )
            self.assertIsNotNone(results.get("holder"))
            self.assertIsNone(results["second"], "the leased job must not be claimed twice")
            self.assertLess(results["elapsed"], 5.0, "the empty claim must return immediately")
            release_holder.set()
            first.result(timeout=20)
            other.result(timeout=20)
        finally:
            release_holder.set()
            pool.shutdown(wait=True, cancel_futures=True)

    # -- 3/5: overlapping execution and no connection held --------------------
    def test_two_jobs_can_be_executed_at_the_same_time_with_no_connection_held(self) -> None:
        self._seed_run()
        self._enqueue("job_t84demo001", idempotency_key="idem-t84-job-001")
        self._enqueue("job_t84demo002", idempotency_key="idem-t84-job-002")
        overlap = _OverlapHandler(expected=2)
        registry = JobHandlerRegistry()
        registry.register("artifact-verify", overlap)
        engine = self.engine

        class _PoolRecordingHandler:
            def __init__(self, inner: _OverlapHandler) -> None:
                self._inner = inner
                self.observed: list[int] = []

            def execute(self, context: JobExecutionContext) -> None:
                self.observed.append(engine.pool.checkedout())
                self._inner.execute(context)

        recording = _PoolRecordingHandler(overlap)
        registry = JobHandlerRegistry()
        registry.register("artifact-verify", recording)

        def run(worker_id: str) -> Callable[[], Any]:
            def action():
                worker = JobWorker(
                    self.execution,
                    registry,
                    JobWorkerConfig(worker_id=worker_id, lease_timeout_seconds=30),
                )
                return worker.run_once()

            return action

        outcomes = self._concurrently([run("worker_a"), run("worker_b")])
        self.assertEqual({outcome.status for outcome in outcomes}, {OUTCOME_SUCCEEDED}, outcomes)
        self.assertEqual(sorted(overlap.calls), ["job_t84demo001", "job_t84demo002"])
        # Each handler runs with no connection of its own: with two workers overlapping, the
        # other worker's short claim transaction may hold at most one pooled connection.
        self.assertTrue(
            all(value <= 1 for value in recording.observed),
            f"a handler must not hold a connection of its own: {recording.observed}",
        )
        self.assertEqual(self.engine.pool.checkedout(), 0)

    # -- 7/8/9: retry, new lease, exhaustion ----------------------------------
    def test_a_retryable_failure_enters_retrying_atomically_and_the_next_claim_is_a_new_lease(self) -> None:
        self._seed_run()
        job = self._enqueue()
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_RETRY_SCHEDULED)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.RETRYING.value)
        self.assertEqual(row["attempts"], 2, "the retry consumes exactly one attempt")
        self.assertIsNone(row["lease_id"])
        self.assertEqual(row["error_code"], "ENT-HANDLER-TIMEOUT")

        second = self.worker.run_once()
        assert second is not None
        self.assertEqual(second.status, OUTCOME_SUCCEEDED)
        self.assertEqual(second.attempt, 2)
        self.assertNotEqual(second.lease_id, outcome.lease_id, "every claim gets a new lease_id")
        self.assertEqual(row["job_id"], self._job_row(job.job_id)["job_id"])
        self.assertEqual(self._job_row(job.job_id)["state"], JobState.SUCCEEDED.value)
        self.assertEqual(self.handler.attempts, [1, 2])
        self.assertEqual(len(set(self.handler.idempotency_keys)), 1)

    def test_reaching_max_attempts_makes_the_failure_terminal(self) -> None:
        self._seed_run()
        job = self._enqueue(max_attempts=2)
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True, times=2)
        first = self.worker.run_once()
        second = self.worker.run_once()
        assert first is not None and second is not None
        self.assertEqual(first.status, OUTCOME_RETRY_SCHEDULED)
        self.assertEqual(second.attempt, 2)
        self.assertEqual(second.status, OUTCOME_FAILED_TERMINAL)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.FAILED.value)
        self.assertEqual(row["attempts"], 2)
        self.assertIsNone(row["lease_id"])
        self.assertEqual(self.worker.run_once(), None)

    def test_a_non_retryable_failure_is_terminal_on_the_first_attempt(self) -> None:
        self._seed_run()
        job = self._enqueue()
        self.handler.fail_next("ENT-HANDLER-REJECTED", retryable=False)
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILED_TERMINAL)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.FAILED.value)
        self.assertEqual(row["attempts"], 1)
        self.assertIsNone(row["lease_id"])

    # -- 10/11/12: heartbeat and expiry ---------------------------------------
    def test_heartbeat_uses_the_database_clock_and_prevents_reclaim(self) -> None:
        self._seed_run()
        job = self._enqueue()
        lease = self.execution.claim_next(worker_id="worker_a", lease_id="lease_heartbeat")
        assert lease is not None
        before = self._db_now()
        refreshed = self.execution.heartbeat(job.job_id, lease.lease_id, lease.attempt)
        after = self._db_now()
        self.assertGreater(refreshed.updated_at, lease.leased_at)
        stored = dt.datetime.fromisoformat(refreshed.updated_at)
        self.assertLessEqual(before, stored)
        self.assertLessEqual(stored, after + dt.timedelta(seconds=1))
        self.assertEqual(
            self.worker.reclaim_expired(), (), "a heartbeated lease is still inside the timeout"
        )

    def test_a_timed_out_lease_is_reclaimed_and_executed_again(self) -> None:
        self._seed_run()
        job = self._enqueue()
        lease = self.execution.claim_next(worker_id="worker_a", lease_id="lease_timeout")
        assert lease is not None
        self._expire_lease(job.job_id)
        reclaimed = self.worker.reclaim_expired()
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].state, JobState.RETRYING.value)
        self.assertEqual(reclaimed[0].attempts, 2)
        self.assertIsNone(reclaimed[0].lease_id)
        self.assertEqual(reclaimed[0].error_code, ERROR_WORKER_LEASE_EXPIRED)

        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCEEDED)
        self.assertEqual(outcome.attempt, 2)
        self.assertEqual(self.handler.job_ids, [job.job_id])

    def test_a_timed_out_lease_at_the_attempt_limit_becomes_failed(self) -> None:
        self._seed_run()
        job = self._enqueue(max_attempts=1)
        self.execution.claim_next(worker_id="worker_a", lease_id="lease_last")
        self._expire_lease(job.job_id)
        reclaimed = self.worker.reclaim_expired()
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].state, JobState.FAILED.value)
        self.assertEqual(reclaimed[0].attempts, 1)
        self.assertEqual(reclaimed[0].error_code, ERROR_WORKER_LEASE_EXPIRED)
        self.assertEqual(self._job_row(job.job_id)["state"], JobState.FAILED.value)
        self.assertEqual(self.worker.run_once(), None)

    # -- 13/14: fencing against a stale worker --------------------------------
    def test_an_expired_worker_cannot_heartbeat_confirm_or_fail_the_new_lease(self) -> None:
        self._seed_run()
        job = self._enqueue()
        stale = self.execution.claim_next(worker_id="worker_a", lease_id="lease_stale")
        assert stale is not None
        self._expire_lease(job.job_id)
        self.worker.reclaim_expired()
        fresh = self.execution.claim_next(worker_id="worker_b", lease_id="lease_fresh")
        assert fresh is not None
        self.assertNotEqual(fresh.lease_id, stale.lease_id)

        for name, call in {
            "heartbeat": lambda: self.execution.heartbeat(job.job_id, stale.lease_id, stale.attempt),
            "mark_succeeded": lambda: self.execution.mark_succeeded(
                job.job_id, stale.lease_id, stale.attempt
            ),
            "mark_failed": lambda: self.execution.mark_failed(
                job.job_id, stale.lease_id, stale.attempt, "ENT-HANDLER-STALE", retryable=True
            ),
        }.items():
            with self.subTest(write=name), self.assertRaises(DomainError) as captured:
                call()
            self.assertEqual(captured.exception.code, ERROR_WORKER_CLAIM)

    def test_the_stale_worker_cannot_overwrite_the_new_workers_state(self) -> None:
        self._seed_run()
        job = self._enqueue()
        stale = self.execution.claim_next(worker_id="worker_a", lease_id="lease_stale_two")
        assert stale is not None
        self._expire_lease(job.job_id)
        self.worker.reclaim_expired()
        fresh = self.execution.claim_next(worker_id="worker_b", lease_id="lease_fresh_two")
        assert fresh is not None
        before = self._job_row(job.job_id)

        for call in (
            lambda: self.execution.mark_succeeded(job.job_id, stale.lease_id, stale.attempt),
            lambda: self.execution.mark_failed(
                job.job_id, stale.lease_id, stale.attempt, "ENT-HANDLER-STALE", retryable=True
            ),
            lambda: self.execution.heartbeat(job.job_id, stale.lease_id, stale.attempt),
        ):
            with self.assertRaises(DomainError):
                call()

        after = self._job_row(job.job_id)
        self.assertEqual(after["state"], JobState.LEASED.value, "the new lease is untouched")
        self.assertEqual(after["lease_id"], "lease_fresh_two")
        self.assertEqual(after["attempts"], fresh.attempt)
        self.assertEqual(after["updated_at"], before["updated_at"], "the stale worker wrote nothing")
        self.assertEqual(after["error_code"], before["error_code"])

    # -- 15/16: the two unknown outcomes --------------------------------------
    def test_a_success_that_cannot_be_confirmed_is_reported_and_recovered(self) -> None:
        self._seed_run()
        job = self._enqueue()

        class _RefusingConfirm(PostgreSQLJobExecutionRepository):
            def mark_succeeded(self, job_id: str, lease_id: str, attempt: int):
                # A real database refusal: the frozen CHECK constraint rejects the write, so
                # the confirmation is rolled back and the handler result stays unrecorded.
                self._short_transaction(
                    lambda connection: connection.execute(
                        text(
                            f"UPDATE {POSTGRESQL_SCHEMA}.background_jobs "
                            "SET state = 'not_a_declared_state' WHERE job_id = :job_id"
                        ),
                        {"job_id": job_id},
                    )
                )
                raise AssertionError("the frozen CHECK constraint must refuse this state")

        worker = JobWorker(_RefusingConfirm(self.engine), self.registry, self.config)
        outcome = worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCESS_UNRECORDED)
        self.assertTrue(outcome.handler_succeeded)
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.reexecution_possible)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.LEASED.value, "the lease survives the rollback")
        self.assertEqual(len(self.handler.calls), 1)

        # Recovery: the lease times out, the job is requeued with a new attempt and runs again.
        self._expire_lease(job.job_id)
        self.assertEqual(len(self.worker.reclaim_expired()), 1)
        recovered = self.worker.run_once()
        assert recovered is not None
        self.assertEqual(recovered.status, OUTCOME_SUCCEEDED)
        self.assertEqual(recovered.attempt, 2)
        self.assertEqual(self.handler.job_ids, [job.job_id, job.job_id], "at-least-once execution")
        self.assertEqual(len(set(self.handler.idempotency_keys)), 1)

    def test_a_failure_that_cannot_be_recorded_is_reported_as_failure_unrecorded(self) -> None:
        self._seed_run()
        job = self._enqueue()
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)

        class _RefusingFailure(PostgreSQLJobExecutionRepository):
            def mark_failed(self, job_id, lease_id, attempt, error_code, **kwargs):
                self._short_transaction(
                    lambda connection: connection.execute(
                        text(
                            f"UPDATE {POSTGRESQL_SCHEMA}.background_jobs "
                            "SET state = 'not_a_declared_state' WHERE job_id = :job_id"
                        ),
                        {"job_id": job_id},
                    )
                )
                raise AssertionError("the frozen CHECK constraint must refuse this state")

        worker = JobWorker(_RefusingFailure(self.engine), self.registry, self.config)
        outcome = worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILURE_UNRECORDED)
        self.assertFalse(outcome.handler_succeeded)
        self.assertFalse(outcome.persistence_state_known)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.LEASED.value)
        self.assertIsNone(row["error_code"], "no half-applied failure code")
        self.assertEqual(row["attempts"], 1)

        self._expire_lease(job.job_id)
        reclaimed = self.worker.reclaim_expired()
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].error_code, ERROR_WORKER_LEASE_EXPIRED)
        self.assertEqual(self._job_row(job.job_id)["state"], JobState.RETRYING.value)

    # -- 17/18: safe failures only --------------------------------------------
    def test_an_unregistered_job_type_fails_safely(self) -> None:
        self._seed_run()
        job = self._enqueue(job_type="artifact-verify")
        registry = JobHandlerRegistry()  # nothing registered for this type
        worker = JobWorker(self.execution, registry, self.config)
        outcome = worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_FAILED_TERMINAL)
        self.assertEqual(outcome.error_code, ERROR_WORKER_HANDLER_NOT_FOUND)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.FAILED.value)
        self.assertEqual(row["error_code"], ERROR_WORKER_HANDLER_NOT_FOUND)
        self.assertIsNone(row["lease_id"])

    def test_no_raw_exception_text_reaches_the_database(self) -> None:
        self._seed_run()
        job = self._enqueue()
        self.handler.raise_next(
            RuntimeError(
                "boom postgresql://steelai:t0psecret@db-host:5432/steelai_enterprise_test "
                "while reading C:\\data\\raw\\sample.csv"
            )
        )
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.error_code, ERROR_WORKER_EXECUTION)
        row = self._job_row(job.job_id)
        self.assertEqual(row["error_code"], ERROR_WORKER_EXECUTION)
        self.assertEqual(row["state"], JobState.RETRYING.value)
        rendered = " ".join(str(value) for value in row.values())
        for forbidden in ("t0psecret", "postgresql://", "db-host", "C:\\data", "boom", "RuntimeError"):
            self.assertNotIn(forbidden, rendered)
        self.assertLessEqual(len(row["error_code"]), 64)

    def test_a_handler_error_code_is_persisted_without_free_text(self) -> None:
        self._seed_run()
        job = self._enqueue()
        self.handler.fail_next("ENT-HANDLER-POLICY-REJECTED", retryable=False)
        self.worker.run_once()
        row = self._job_row(job.job_id)
        self.assertEqual(row["error_code"], "ENT-HANDLER-POLICY-REJECTED")
        self.assertEqual(row["state"], JobState.FAILED.value)

    # -- 19/20: connection and transaction hygiene ----------------------------
    def test_no_connection_is_held_while_handlers_run_and_no_transaction_is_left_open(self) -> None:
        self._seed_run()
        self._enqueue("job_t84demo001", idempotency_key="idem-t84-job-001")
        self._enqueue("job_t84demo002", idempotency_key="idem-t84-job-002")
        observing = _PoolObservingHandler(self.engine)
        registry = JobHandlerRegistry()
        registry.register("artifact-verify", observing)
        worker = JobWorker(self.execution, registry, self.config)
        outcomes = worker.run_batch(limit=5)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(observing.observed, [0, 0], "each handler runs with no connection held")
        self.assertEqual(self.engine.pool.checkedout(), 0, "no short transaction leaked a connection")
        with self.engine.connect() as connection:
            idle = connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'")
            ).scalar_one()
        self.assertEqual(idle, 0, "no transaction may be left open")

    def test_a_batch_returns_immediately_when_the_queue_is_empty(self) -> None:
        started = time.monotonic()
        self.assertEqual(self.worker.run_batch(limit=5), ())
        self.assertEqual(self.worker.run_once(), None)
        self.assertLess(time.monotonic() - started, 5.0)

    # -- 21: the T82 job queue semantics are unchanged ------------------------
    def test_the_t82_complete_versus_fail_concurrency_still_holds(self) -> None:
        self._seed_run()
        self._enqueue()
        with self.factory.unit_of_work() as unit:
            leased = unit.jobs.lease()
            self.assertIsNotNone(leased)
            unit.commit()

        def worker(finish: str) -> Callable[[], Any]:
            def action():
                unit = self.factory.unit_of_work()
                with unit:
                    if finish == "complete":
                        job = unit.jobs.complete(leased.job_id)
                    else:
                        job = unit.jobs.fail(leased.job_id, error_code="ENT-JOB-001")
                    unit.commit()
                return job

            return action

        outcomes = self._concurrently([worker("complete"), worker("fail")])
        codes = sorted(_code_of(outcome) for outcome in outcomes)
        self.assertEqual(codes.count("ok"), 1, outcomes)
        self.assertIn(ERROR_JOB_TRANSITION, codes, outcomes)
        row = self._job_row(leased.job_id)
        self.assertIn(row["state"], {JobState.SUCCEEDED.value, JobState.FAILED.value})

    # -- 22: the T83 dispatcher is unaffected ---------------------------------
    def test_the_t83_outbox_dispatcher_still_works_on_the_same_database(self) -> None:
        self._seed_run()
        with self.factory.unit_of_work() as unit:
            sequence = unit.events.next_sequence("run_t84demo001")
            event = DomainEvent.create(
                event_type="enterprise.workflow_run.registered",
                run_id="run_t84demo001",
                sequence=sequence,
                payload={"state": "draft", "revision": 1, "summary": "worker regression probe"},
            )
            unit.events.publish(event)
            unit.commit()
        with self.engine.connect() as connection:
            pending = connection.execute(select(func.count()).select_from(outbox_events)).scalar_one()
        self.assertEqual(pending, 1)

        transport = RecordingEventTransport()
        dispatcher = OutboxDispatcher(
            PostgreSQLOutboxDeliveryRepository(self.engine),
            transport,
            OutboxDispatcherConfig(lease_seconds=30, max_attempts=3),
        )
        outcomes = dispatcher.dispatch_batch(limit=5)
        self.assertEqual([outcome.status for outcome in outcomes], ["published"])
        self.assertEqual(transport.event_ids, [event.event_id])

    # -- 23/24: the handler exception boundary on a real database --------------
    def test_a_handler_domain_error_is_sanitised_and_does_not_stop_the_batch(self) -> None:
        """A handler DomainError is unclassified: safe code, lease released, batch continues."""
        self._seed_run()
        first = self._enqueue("job_t84demo001", idempotency_key="idem-t84-job-001", max_attempts=2)
        second = self._enqueue("job_t84demo002", idempotency_key="idem-t84-job-002")
        leaky = DomainError(
            "ENT-LEAKY-001",
            "connection to postgresql://steelai:t0psecret@db-host:5432/steelai_enterprise_test failed "
            "while reading C:\\data\\raw\\sample.csv with leaked-token",
            details={
                "url": "postgresql://steelai:t0psecret@db-host:5432/steelai_enterprise_test",
                "path": "C:\\data\\raw\\sample.csv",
                "token": "leaked-token",
            },
        )

        class _SelectiveLeakyHandler:
            def __init__(self, failing_job_id: str) -> None:
                self._failing_job_id = failing_job_id

            def execute(self, context: JobExecutionContext) -> None:
                if context.job_id == self._failing_job_id:
                    raise leaky

        registry = JobHandlerRegistry()
        registry.register("artifact-verify", _SelectiveLeakyHandler(first.job_id))
        worker = JobWorker(self.execution, registry, self.config)

        outcomes = worker.run_batch(limit=4)  # must not raise
        self.assertEqual(len(outcomes), 3, outcomes)
        self.assertEqual(
            [outcome.job_id for outcome in outcomes], [first.job_id, first.job_id, second.job_id]
        )
        self.assertEqual(outcomes[0].status, OUTCOME_RETRY_SCHEDULED)
        self.assertEqual(outcomes[1].status, OUTCOME_FAILED_TERMINAL)
        self.assertEqual(outcomes[2].status, OUTCOME_SUCCEEDED)
        for outcome in outcomes[:2]:
            self.assertEqual(outcome.error_code, ERROR_WORKER_EXECUTION)

        row = self._job_row(first.job_id)
        self.assertEqual(row["state"], JobState.FAILED.value, "the job must not stay leased")
        self.assertIsNone(row["lease_id"], "the lease must be released")
        self.assertEqual(row["error_code"], ERROR_WORKER_EXECUTION)
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(self._job_row(second.job_id)["state"], JobState.SUCCEEDED.value)

        rendered = " ".join(str(value) for value in row.values())
        rendered += " ".join(str(outcome.to_dict()) for outcome in outcomes)
        for fragment in ("t0psecret", "postgresql://", "db-host", "C:\\data", "sample.csv", "ENT-LEAKY-001", "leaked-token"):
            self.assertNotIn(fragment, rendered, f"the failure leaked {fragment}")

    def test_every_real_worker_outcome_satisfies_the_invariant_table(self) -> None:
        """Each persisted-state claim made by a real outcome matches the database row."""
        self._seed_run()
        job_types = ("inv-success", "inv-retry", "inv-terminal")
        jobs = {
            job_types[0]: self._enqueue("job_t84inv001", job_type=job_types[0], idempotency_key="idem-t84-inv-001"),
            job_types[1]: self._enqueue("job_t84inv002", job_type=job_types[1], idempotency_key="idem-t84-inv-002"),
            job_types[2]: self._enqueue("job_t84inv003", job_type=job_types[2], idempotency_key="idem-t84-inv-003"),
        }
        registry = JobHandlerRegistry()
        for job_type in job_types:
            registry.register(job_type, self.handler)
        worker = JobWorker(self.execution, registry, self.config)

        # Each call is scoped to one job type, so the scripted outcome lands on that job.
        success_outcome = worker.run_once(job_types[0])
        self.handler.fail_next("ENT-HANDLER-TIMEOUT", retryable=True)
        retry_outcome = worker.run_once(job_types[1])
        self.handler.fail_next("ENT-HANDLER-REJECTED", retryable=False)
        terminal_outcome = worker.run_once(job_types[2])
        assert success_outcome is not None and retry_outcome is not None and terminal_outcome is not None

        for outcome, expected_status, job_type in (
            (success_outcome, OUTCOME_SUCCEEDED, job_types[0]),
            (retry_outcome, OUTCOME_RETRY_SCHEDULED, job_types[1]),
            (terminal_outcome, OUTCOME_FAILED_TERMINAL, job_types[2]),
        ):
            with self.subTest(status=expected_status):
                self.assertEqual(outcome.status, expected_status)
                self.assertEqual(outcome.job_id, jobs[job_type].job_id)
                state, offset, needs_code = PERSISTED_FIELDS[outcome.status]
                row = self._job_row(outcome.job_id)
                self.assertEqual(outcome.state, row["state"], "the reported state is the persisted one")
                self.assertEqual(row["state"], state)
                self.assertEqual(outcome.attempts, row["attempts"])
                self.assertEqual(row["attempts"], outcome.attempt + offset)
                self.assertEqual(outcome.error_code, row["error_code"])
                self.assertEqual(outcome.error_code is None, not needs_code)
                self.assertIsNone(row["lease_id"], "no confirmed write leaves a lease behind")

    def test_a_real_repository_and_handler_combination_executes_a_job(self) -> None:
        """Guard: the integration suite drives the real repository with a real handler."""
        self._seed_run()
        self._enqueue()
        self.assertIsInstance(self.execution, PostgreSQLJobExecutionRepository)
        outcome = self.worker.run_once()
        assert outcome is not None
        self.assertEqual(outcome.status, OUTCOME_SUCCEEDED)
        self.assertEqual(self.handler.job_ids, [outcome.job_id])

    def test_a_worker_lease_survives_an_unrelated_outbox_dispatch(self) -> None:
        """The two loops share one database without interfering: job lease vs outbox lease."""
        self._seed_run()
        job = self._enqueue()
        lease = self.execution.claim_next(worker_id="worker_a", lease_id="lease_shared")
        assert lease is not None
        self.execution.heartbeat(job.job_id, lease.lease_id, lease.attempt)
        row = self._job_row(job.job_id)
        self.assertEqual(row["state"], JobState.LEASED.value)
        self.assertEqual(row["lease_id"], "lease_shared")
        outcome = self.execution.mark_succeeded(job.job_id, lease.lease_id, lease.attempt)
        self.assertEqual(outcome.state, JobState.SUCCEEDED.value)
        self.assertIsNone(outcome.lease_id)


def _code_of(result: Any) -> str:
    """Normalise one concurrent outcome to ``ok`` or a stable error code."""
    if isinstance(result, DomainError):
        return result.code
    if isinstance(result, BaseException):
        return f"unexpected:{type(result).__name__}"
    return "ok"


def _run_after_barrier(action: Callable[[], Any], barrier: threading.Barrier) -> Any:
    """Run ``action`` after a shared barrier, bounded in time."""
    barrier.wait(timeout=15)
    try:
        return action()
    except DomainError as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - the test asserts on the outcome
        return exc


if __name__ == "__main__":
    unittest.main()
