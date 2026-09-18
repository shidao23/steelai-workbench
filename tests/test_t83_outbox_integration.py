"""T83 real PostgreSQL integration tests for the outbox dispatcher.

Every test runs against a dedicated PostgreSQL container and is skipped unless
``STEELAI_TEST_DATABASE_URL`` names a safe test database (the database name must contain
both ``steelai`` and ``test``). The T81 migration is applied to the empty database first,
so the T83 dispatcher is proven on the frozen T81 schema: no column, index or migration
is added by T83.

Concurrency tests use a bounded thread pool with a join timeout, so a deadlock fails the
test instead of hanging the suite. No test prints a connection string.
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
from steelai.enterprise_lab.adapters.postgresql.schema import outbox_events, workflow_runs
from steelai.enterprise_lab.application.outbox_dispatcher import (
    STATUS_FAILED,
    STATUS_FAILURE_UNRECORDED,
    STATUS_PUBLISHED,
    STATUS_RETRY_SCHEDULED,
    STATUS_SENT_UNACKNOWLEDGED,
    OutboxDispatcher,
    OutboxDispatcherConfig,
)
from steelai.enterprise_lab.domain.models import DomainError, DomainEvent, WorkflowRun
from steelai.enterprise_lab.ports.outbox import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_PUBLISHED,
    DELIVERY_PUBLISHING,
    ERROR_OUTBOX_CLAIM,
    ERROR_OUTBOX_LEASE_EXPIRED,
    ERROR_OUTBOX_TRANSPORT,
)


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
ALEMBIC_INI = ROOT / "alembic-enterprise.ini"
TEST_DATABASE_URL_ENV_VAR = "STEELAI_TEST_DATABASE_URL"
TEST_DATABASE_ONLY_ENV_VAR = "STEELAI_ENTERPRISE_TEST_DATABASE_ONLY"

DIGEST_A = "a" * 64

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


def _event(run_id: str, sequence: int) -> DomainEvent:
    return DomainEvent.create(
        event_type="enterprise.workflow_run.registered",
        run_id=run_id,
        sequence=sequence,
        payload={"state": "draft", "revision": sequence, "summary": "outbox integration probe"},
    )


@unittest.skipUnless(
    _test_database_url() is not None,
    "STEELAI_TEST_DATABASE_URL with a database name containing both 'steelai' and 'test' is required",
)
class OutboxDispatcherIntegrationTests(unittest.TestCase):
    """The T83 acceptance scenarios against a real PostgreSQL server."""

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
        self.delivery = PostgreSQLOutboxDeliveryRepository(self.engine)
        self.transport = RecordingEventTransport()
        self.config = OutboxDispatcherConfig(
            lease_seconds=30,
            max_attempts=3,
            retry_backoff_seconds=5,
            retry_backoff_cap_seconds=20,
            batch_limit=10,
        )
        self.dispatcher = OutboxDispatcher(self.delivery, self.transport, self.config)
        with self.engine.begin() as connection:
            connection.execute(text(CLEAR_TRUNCATE_SQL))

    def _seed_run(self, run_id: str = "run_t83demo001", key: str = "idem-t83-demo-001") -> WorkflowRun:
        """Create the run row the outbox rows reference, through the T82 adapter."""
        with self.factory.unit_of_work() as unit:
            run, _ = unit.runs.create_run(
                WorkflowRun.create(
                    run_id=run_id,
                    project_id="PRJ-T83-DEMO",
                    task_id="task_t83demo001",
                    idempotency_key=key,
                    request_digest=DIGEST_A,
                ),
                idempotency_key=key,
            )
            unit.commit()
        return run

    def _publish_event(self, run_id: str, sequence: int) -> DomainEvent:
        """Write a ``pending`` outbox row through the T82 EventPublisher (write side)."""
        with self.factory.unit_of_work() as unit:
            expected = unit.events.next_sequence(run_id)
            event = _event(run_id, sequence)
            if expected != sequence:
                raise AssertionError(f"expected sequence {expected}, got {sequence}")
            unit.events.publish(event)
            unit.commit()
        self._await_claimable(event.event_id)
        return event

    def _await_claimable(self, event_id: str, *, timeout: float = 10.0) -> None:
        """Wait until the write-side timestamp is claimable on the *database* clock.

        The T82 write side stamps ``available_at`` from the event timestamp (a client-side
        value). A claim compares it with the database clock, so a container whose clock is
        briefly behind the host delays the first claim by that offset. The wait keeps the
        suite deterministic without weakening the claim contract.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self.engine.connect() as connection:
                claimable = connection.execute(
                    text(
                        f"SELECT available_at <= now() FROM {POSTGRESQL_SCHEMA}.outbox_events "
                        "WHERE event_id = :event_id"
                    ),
                    {"event_id": event_id},
                ).scalar_one()
            if claimable:
                return
            if time.monotonic() > deadline:
                raise AssertionError(
                    "the write-side available_at never became claimable on the database clock"
                )
            time.sleep(0.05)

    def _row(self, event_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(outbox_events).where(outbox_events.c.event_id == event_id)
                )
                .mappings()
                .first()
            )
        assert row is not None
        return dict(row)

    def _statuses(self, run_id: str) -> list[tuple[int, str, int]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(outbox_events.c.sequence, outbox_events.c.delivery_status, outbox_events.c.attempts)
                .where(outbox_events.c.run_id == run_id)
                .order_by(outbox_events.c.sequence)
            ).all()
        return [tuple(row) for row in rows]

    def _db_now(self) -> Any:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT now()")).scalar_one()

    def _make_available(self, event_id: str) -> None:
        """Move one row's ``available_at`` into the past, to skip a backoff in a test.

        The lease and the backoff are both ``available_at``; a test that wants the next
        claim immediately moves the database clock's stamp instead of sleeping.
        """
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events "
                    "SET available_at = now() - interval '1 second' WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            )

    def _make_all_pending_available(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events "
                    "SET available_at = now() - interval '1 second' WHERE delivery_status = 'pending'"
                )
            )

    def _concurrently(self, actions: list[Callable[[], Any]], *, timeout: float = 30.0) -> list[Any]:
        barrier = threading.Barrier(len(actions))
        pool = ThreadPoolExecutor(max_workers=len(actions))
        try:
            futures = [pool.submit(_run_after_barrier, action, barrier) for action in actions]
            return [future.result(timeout=timeout) for future in futures]
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    # -- 1/4: two dispatchers, no duplicate claim, immediate empty batch --------
    def test_two_concurrent_dispatchers_never_claim_the_same_event(self) -> None:
        self._seed_run("run_t83demo001", "idem-t83-demo-001")
        self._seed_run("run_t83demo002", "idem-t83-demo-002")
        self._publish_event("run_t83demo001", 1)
        self._publish_event("run_t83demo002", 1)

        outcome_sets = self._concurrently(
            [
                lambda: OutboxDispatcher(self.delivery, RecordingEventTransport(), self.config).dispatch_batch(limit=10),
                lambda: OutboxDispatcher(self.delivery, RecordingEventTransport(), self.config).dispatch_batch(limit=10),
            ]
        )
        claimed = [outcome.event_id for outcomes in outcome_sets for outcome in outcomes]
        self.assertEqual(len(claimed), 2, outcome_sets)
        self.assertEqual(len(set(claimed)), 2, f"an event was claimed twice: {claimed}")
        self.assertEqual(self._statuses("run_t83demo001")[0][1], DELIVERY_PUBLISHED)
        self.assertEqual(self._statuses("run_t83demo002")[0][1], DELIVERY_PUBLISHED)

    def test_an_empty_queue_returns_immediately(self) -> None:
        started = time.monotonic()
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), ())
        self.assertLess(time.monotonic() - started, 5.0, "an empty claim must not wait for other workers")

    # -- 2: different runs are independent -------------------------------------
    def test_different_runs_can_be_publishing_at_the_same_time(self) -> None:
        self._seed_run("run_t83demo001", "idem-t83-demo-001")
        self._seed_run("run_t83demo002", "idem-t83-demo-002")
        self._publish_event("run_t83demo001", 1)
        self._publish_event("run_t83demo002", 1)
        claims = self.delivery.claim_batch(limit=10, lease_seconds=60, max_attempts=3)
        self.assertEqual(len(claims), 2)
        self.assertEqual({claim.event.run_id for claim in claims}, {"run_t83demo001", "run_t83demo002"})
        with self.engine.connect() as connection:
            publishing = connection.execute(
                select(func.count()).select_from(outbox_events).where(
                    outbox_events.c.delivery_status == DELIVERY_PUBLISHING
                )
            ).scalar_one()
        self.assertEqual(publishing, 2)

    # -- 3/14: per-run strict ordering ----------------------------------------
    def test_a_run_only_offers_its_smallest_unpublished_sequence(self) -> None:
        self._seed_run()
        first = self._publish_event("run_t83demo001", 1)
        second = self._publish_event("run_t83demo001", 2)
        third = self._publish_event("run_t83demo001", 3)

        outcomes = self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual([outcome.event_id for outcome in outcomes], [first.event_id])
        self.assertEqual(
            self._statuses("run_t83demo001"),
            [(1, DELIVERY_PUBLISHED, 1), (2, DELIVERY_PENDING, 0), (3, DELIVERY_PENDING, 0)],
        )
        self.assertEqual([outcome.event_id for outcome in self.dispatcher.dispatch_batch(limit=10)], [second.event_id])
        self.assertEqual([outcome.event_id for outcome in self.dispatcher.dispatch_batch(limit=10)], [third.event_id])

    def test_a_failed_event_keeps_blocking_the_rest_of_its_run(self) -> None:
        self._seed_run()
        first = self._publish_event("run_t83demo001", 1)
        self._publish_event("run_t83demo001", 2)
        self.transport.fail_next("ENT-TRANSPORT-REJECTED", retryable=False)
        self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(self._row(first.event_id)["delivery_status"], DELIVERY_FAILED)

        for _ in range(3):
            self.assertEqual(self.dispatcher.dispatch_batch(limit=10), (), "a failed event blocks its run")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events SET available_at = now() + interval '1 hour' "
                    "WHERE delivery_status = 'publishing'"
                )
            )
        self.assertEqual(self.dispatcher.reclaim_expired(limit=10), ())
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), (), "T83 has no skip and no manual unlock")
        self.assertEqual(self._statuses("run_t83demo001")[1][1], DELIVERY_PENDING)

    # -- 5: attempts is an atomic fencing token -------------------------------
    def test_attempts_increments_atomically_and_is_a_fencing_token(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        first = self.delivery.claim_batch(limit=1, lease_seconds=60, max_attempts=5)[0]
        self.assertEqual(first.claim_attempt, 1)
        self.assertEqual(self._row(event.event_id)["attempts"], 1)

        # The row is leased: a second claim sees nothing until the lease expires.
        self.assertEqual(self.delivery.claim_batch(limit=1, lease_seconds=60, max_attempts=5), ())
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events SET available_at = now() - interval '1 second' "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event.event_id},
            )
        reclaimed = self.dispatcher.reclaim_expired(limit=10)
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].last_error_code, ERROR_OUTBOX_LEASE_EXPIRED)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events SET available_at = now() - interval '1 second' "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event.event_id},
            )
        second = self.delivery.claim_batch(limit=1, lease_seconds=60, max_attempts=5)[0]
        self.assertEqual(second.claim_attempt, 2, "the fencing token advanced with the new claim")
        self.assertEqual(self._row(event.event_id)["attempts"], 2)

    # -- 6: an old worker cannot confirm a new lease --------------------------
    def test_an_old_worker_cannot_confirm_the_new_lease(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        stale = self.delivery.claim_batch(limit=1, lease_seconds=1, max_attempts=5)[0]
        time.sleep(1.2)
        reclaimed = self.dispatcher.reclaim_expired(limit=10)
        self.assertEqual(len(reclaimed), 1)
        # A recovered row waits for the first backoff step before it can be claimed.
        self._make_available(event.event_id)
        fresh = self.delivery.claim_batch(limit=1, lease_seconds=60, max_attempts=5)[0]
        self.assertEqual(fresh.claim_attempt, stale.claim_attempt + 1)

        with self.assertRaises(DomainError) as captured:
            self.delivery.mark_published(event.event_id, stale.claim_attempt)
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CLAIM)
        with self.assertRaises(DomainError) as captured_nack:
            self.delivery.mark_failed(
                event.event_id,
                stale.claim_attempt,
                "ENT-TRANSPORT-TIMEOUT",
                retry_delay_seconds=5,
                retryable=True,
            )
        self.assertEqual(captured_nack.exception.code, ERROR_OUTBOX_CLAIM)

        row = self._row(event.event_id)
        self.assertEqual(row["delivery_status"], DELIVERY_PUBLISHING)
        self.assertEqual(row["attempts"], fresh.claim_attempt)
        self.assertIsNone(row["published_at"], "the stale worker must not publish the new lease")

    # -- 7/8: lease recovery --------------------------------------------------
    def test_an_expired_lease_is_reclaimed_and_can_be_claimed_again(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        self.delivery.claim_batch(limit=1, lease_seconds=1, max_attempts=5)
        time.sleep(1.2)
        reclaimed = self.dispatcher.reclaim_expired(limit=10)
        self.assertEqual([entry.event_id for entry in reclaimed], [event.event_id])
        self.assertTrue(reclaimed[0].requeued)
        self.assertEqual(reclaimed[0].attempts, 1)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events SET available_at = now() - interval '1 second' "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event.event_id},
            )
        outcomes = self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual([outcome.status for outcome in outcomes], [STATUS_PUBLISHED])
        self.assertEqual(self._row(event.event_id)["attempts"], 2)

    def test_an_expired_lease_at_the_attempt_limit_becomes_failed(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        config = OutboxDispatcherConfig(lease_seconds=1, max_attempts=1, retry_backoff_seconds=1)
        dispatcher = OutboxDispatcher(self.delivery, self.transport, config)
        self.delivery.claim_batch(limit=1, lease_seconds=1, max_attempts=1)
        time.sleep(1.2)
        reclaimed = dispatcher.reclaim_expired(limit=10)
        self.assertEqual(len(reclaimed), 1)
        self.assertFalse(reclaimed[0].requeued)
        row = self._row(event.event_id)
        self.assertEqual(row["delivery_status"], DELIVERY_FAILED)
        self.assertEqual(row["last_error_code"], ERROR_OUTBOX_LEASE_EXPIRED)
        self.assertEqual(dispatcher.dispatch_batch(limit=10), (), "a failed row is never claimed again")

    # -- 9/10: published_at and retry available_at use the database clock ------
    def test_a_successful_acknowledge_writes_published_at_from_the_database_clock(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        before = self._db_now()
        self.assertEqual([outcome.status for outcome in self.dispatcher.dispatch_batch(limit=10)], [STATUS_PUBLISHED])
        after = self._db_now()
        row = self._row(event.event_id)
        self.assertEqual(row["delivery_status"], DELIVERY_PUBLISHED)
        self.assertIsNotNone(row["published_at"])
        self.assertLessEqual(before, row["published_at"])
        self.assertLessEqual(row["published_at"], after)
        self.assertIsNone(row["last_error_code"])
        self.assertEqual(row["attempts"], 1)

    def test_a_retry_delay_is_computed_from_the_database_clock(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        before = self._db_now()
        outcome = self.dispatcher.dispatch_batch(limit=10)[0]
        self.assertEqual(outcome.status, STATUS_RETRY_SCHEDULED)
        after = self._db_now()
        row = self._row(event.event_id)
        self.assertEqual(row["delivery_status"], DELIVERY_PENDING)
        self.assertEqual(row["last_error_code"], "ENT-TRANSPORT-TIMEOUT")
        self.assertLessEqual(before, row["available_at"])
        # 5 second base backoff, measured on the database clock (allow one second slack).
        self.assertLess(row["available_at"], after + _seconds(6))
        self.assertGreaterEqual(row["available_at"], after + _seconds(3))

    # -- 11/12: no long-lived connection, no open transaction ------------------
    def test_no_connection_is_checked_out_while_the_transport_runs(self) -> None:
        self._seed_run()
        self._publish_event("run_t83demo001", 1)
        engine = self.engine
        observed: list[int] = []

        class _PoolObservingTransport:
            """Transport that inspects the pool while the send is happening."""

            def send(self, event: DomainEvent, *, idempotency_key: str) -> None:
                observed.append(engine.pool.checkedout())

        dispatcher = OutboxDispatcher(self.delivery, _PoolObservingTransport(), self.config)
        outcomes = dispatcher.dispatch_batch(limit=10)
        self.assertEqual([outcome.status for outcome in outcomes], [STATUS_PUBLISHED])
        self.assertEqual(observed, [0], "the claim transaction must be closed before the send")

        with self.engine.connect() as connection:
            idle = connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'")
            ).scalar_one()
        self.assertEqual(idle, 0, "no transaction may be left open")
        self.assertEqual(self.engine.pool.checkedout(), 0, "no connection may stay checked out")

    # -- 13: T82 pending rows are consumable by T83 ---------------------------
    def test_pending_rows_written_by_t82_are_consumed_by_t83(self) -> None:
        self._seed_run()
        first = self._publish_event("run_t83demo001", 1)
        second = self._publish_event("run_t83demo001", 2)
        with self.engine.connect() as connection:
            pending = connection.execute(
                select(func.count()).select_from(outbox_events).where(
                    outbox_events.c.delivery_status == DELIVERY_PENDING
                )
            ).scalar_one()
        self.assertEqual(pending, 2, "the T82 write side leaves pending rows for the dispatcher")

        dispatched: list[str] = []
        for _ in range(2):
            dispatched.extend(outcome.event_id for outcome in self.dispatcher.dispatch_batch(limit=10))
        self.assertEqual(dispatched, [first.event_id, second.event_id])
        self.assertEqual(
            [row[1] for row in self._statuses("run_t83demo001")], [DELIVERY_PUBLISHED, DELIVERY_PUBLISHED]
        )
        # The delivery columns are dispatcher state only: the domain event replay is intact.
        with self.factory.unit_of_work() as unit:
            replayed = unit.events.replay("run_t83demo001")
            self.assertEqual([event.event_id for event in replayed], [first.event_id, second.event_id])
            self.assertEqual(replayed[0].payload["state"], "draft")
            unit.rollback()

    # -- 15: rollback leaves no half-finished state ---------------------------
    def test_a_failed_acknowledge_is_sent_unacknowledged_and_stays_leased(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)

        class _RefusingDelivery(PostgreSQLOutboxDeliveryRepository):
            def mark_published(self, event_id: str, claim_attempt: int):
                # A real database refusal at acknowledge time: the frozen CHECK constraint
                # rejects an undeclared delivery status, the statement is rolled back and the
                # row must stay leased so the at-least-once recovery path can redeliver it.
                self._short_transaction(
                    lambda connection: connection.execute(
                        text(
                            f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events "
                            "SET delivery_status = 'not_a_declared_state' WHERE event_id = :event_id"
                        ),
                        {"event_id": event_id},
                    )
                )
                raise AssertionError("the frozen CHECK constraint must refuse this status")

        dispatcher = OutboxDispatcher(
            _RefusingDelivery(self.engine), self.transport, self.config
        )
        outcomes = dispatcher.dispatch_batch(limit=10)
        self.assertEqual([outcome.status for outcome in outcomes], [STATUS_SENT_UNACKNOWLEDGED])
        outcome = outcomes[0]
        self.assertTrue(outcome.delivered, "the transport really sent the event")
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.redelivery_possible)
        row = self._row(event.event_id)
        self.assertEqual(row["delivery_status"], DELIVERY_PUBLISHING, "no half-applied acknowledge")
        self.assertIsNone(row["published_at"])
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(len(self.transport.sent), 1, "the transport already delivered it once")

        # Recovery: after the lease expires the event is sent again with the same key.
        self._make_available(event.event_id)
        self.assertEqual(len(self.dispatcher.reclaim_expired(limit=10)), 1)
        self._make_available(event.event_id)
        second = self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual([outcome.status for outcome in second], [STATUS_PUBLISHED])
        self.assertEqual(
            self.transport.idempotency_keys,
            [event.event_id, event.event_id],
            "at-least-once redelivery uses the same idempotency key",
        )
        self.assertEqual(self._row(event.event_id)["attempts"], 2)

    def test_a_transport_failure_is_persisted_with_a_safe_code_only(self) -> None:
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        self.transport.raise_next(
            RuntimeError("broker postgresql://steelai:t0psecret@broker-host:9092 refused the payload")
        )
        outcome = self.dispatcher.dispatch_batch(limit=10)[0]
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_TRANSPORT)
        row = self._row(event.event_id)
        self.assertEqual(row["last_error_code"], ERROR_OUTBOX_TRANSPORT)
        self.assertEqual(row["delivery_status"], DELIVERY_PENDING)
        rendered = " ".join(str(value) for value in row.values())
        for forbidden in ("t0psecret", "broker-host", "postgresql://", "payload"):
            self.assertNotIn(forbidden, rendered)

    def test_a_failure_that_cannot_be_recorded_is_reported_as_failure_unrecorded(self) -> None:
        """The transport failed and the database refused to persist that failure."""
        self._seed_run()
        event = self._publish_event("run_t83demo001", 1)
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)

        class _RefusingFailureDelivery(PostgreSQLOutboxDeliveryRepository):
            def mark_failed(self, event_id, claim_attempt, error_code, **kwargs):
                # A real refusal: the frozen CHECK constraint rejects the write, the
                # statement is rolled back, so the failure is genuinely unrecorded.
                self._short_transaction(
                    lambda connection: connection.execute(
                        text(
                            f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events "
                            "SET delivery_status = 'not_a_declared_state' WHERE event_id = :event_id"
                        ),
                        {"event_id": event_id},
                    )
                )
                raise AssertionError("the frozen CHECK constraint must refuse this status")

        dispatcher = OutboxDispatcher(_RefusingFailureDelivery(self.engine), self.transport, self.config)
        outcomes = dispatcher.dispatch_batch(limit=10)
        self.assertEqual([outcome.status for outcome in outcomes], [STATUS_FAILURE_UNRECORDED])
        outcome = outcomes[0]
        self.assertFalse(outcome.delivered, "nothing was sent and the state is unknown")
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.redelivery_possible)
        self.assertEqual(self.transport.sent, [], "the transport failed, nothing was delivered")

        row = self._row(event.event_id)
        self.assertEqual(row["delivery_status"], DELIVERY_PUBLISHING, "the rollback kept the lease")
        self.assertEqual(row["attempts"], 1)
        self.assertIsNone(row["last_error_code"])

        # The lease is the recovery path: after expiry the event is delivered for real.
        self._make_available(event.event_id)
        self.assertEqual(len(self.dispatcher.reclaim_expired(limit=10)), 1)
        self._make_available(event.event_id)
        self.assertEqual(
            [item.status for item in self.dispatcher.dispatch_batch(limit=10)], [STATUS_PUBLISHED]
        )
        self.assertEqual(self.transport.idempotency_keys, [event.event_id])

    def test_attempt_limit_reached_in_the_database_makes_the_event_terminal(self) -> None:
        self._seed_run()
        self._publish_event("run_t83demo001", 1)
        config = OutboxDispatcherConfig(lease_seconds=60, max_attempts=2, retry_backoff_seconds=1)
        dispatcher = OutboxDispatcher(self.delivery, self.transport, config)
        for expected_attempt in (1, 2):
            self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
            # Skip the retry backoff so the next attempt happens immediately.
            self._make_all_pending_available()
            outcome = dispatcher.dispatch_batch(limit=10)[0]
            self.assertEqual(outcome.claim_attempt, expected_attempt)
        # The second failure reached max_attempts, so the row is terminal, not pending.
        self.assertEqual(outcome.status, STATUS_FAILED)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {POSTGRESQL_SCHEMA}.outbox_events SET available_at = now() - interval '1 hour' "
                    "WHERE delivery_status = 'pending'"
                )
            )
        self.assertEqual(dispatcher.dispatch_batch(limit=10), ())
        self.assertEqual(self._row(outcome.event_id)["delivery_status"], DELIVERY_FAILED)


def _seconds(count: int) -> dt.timedelta:
    """A small timedelta, used to bound database-clock comparisons in assertions."""
    return dt.timedelta(seconds=count)


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
