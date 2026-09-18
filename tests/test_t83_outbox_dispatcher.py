"""T83 offline tests: transactional-outbox dispatcher contract without a database.

Nothing here opens a connection or performs any I/O: the delivery boundary is the
in-memory adapter and the transport is the recording adapter. The suite proves the claim
predicate, the ``attempts`` fencing token, the retry/terminal decision, lease recovery,
per-run ordering and the at-least-once recovery path.

The real PostgreSQL scenarios live in ``tests/test_t83_outbox_integration.py`` and only
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

from steelai.enterprise_lab.adapters.outbox_memory import (
    MemoryOutboxDeliveryRepository,
    RecordedSend,
    RecordingEventTransport,
)
from steelai.enterprise_lab.application.outbox_dispatcher import (
    OUTCOME_PROPERTIES,
    STATUS_FAILED,
    STATUS_FAILURE_UNRECORDED,
    STATUS_PUBLISHED,
    STATUS_RETRY_SCHEDULED,
    STATUS_SENT_UNACKNOWLEDGED,
    OutboxDispatchOutcome,
    OutboxDispatcher,
    OutboxDispatcherConfig,
)
from steelai.enterprise_lab.domain.models import DomainError, DomainEvent
from steelai.enterprise_lab.ports.outbox import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_PUBLISHED,
    DELIVERY_PUBLISHING,
    DELIVERY_STATUSES,
    ERROR_OUTBOX_CLAIM,
    ERROR_OUTBOX_CONFIG,
    ERROR_OUTBOX_LEASE_EXPIRED,
    ERROR_OUTBOX_TRANSPORT,
    EventTransport,
    OutboxClaim,
    OutboxDeliveryRepository,
    OutboxDeliveryState,
    OutboxReclaim,
    TransportError,
    is_safe_error_code,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "steelai" / "enterprise_lab"
PYTHON = Path(sys.executable)
FORBIDDEN_RUNTIME_MODULES = ("sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg", "kafka")
DISALLOWED_DISPATCHER_MODULES = ("threading", "asyncio", "schedule", "time", "socket", "requests", "urllib", "http")


def _event(run_id: str = "run_t83demo001", sequence: int = 1) -> DomainEvent:
    return DomainEvent.create(
        event_type="enterprise.workflow_run.registered",
        run_id=run_id,
        sequence=sequence,
        payload={"state": "draft", "revision": sequence, "summary": "outbox dispatcher probe"},
    )


class _RecordingDelivery:
    """Delivery proxy that records the call order around the transport."""

    def __init__(self, inner: MemoryOutboxDeliveryRepository, calls: list[str]) -> None:
        self._inner = inner
        self._calls = calls

    def claim_batch(self, **kwargs: object):
        self._calls.append("claim")
        return self._inner.claim_batch(**kwargs)  # type: ignore[arg-type]

    def mark_published(self, event_id: str, claim_attempt: int):
        self._calls.append("mark_published")
        return self._inner.mark_published(event_id, claim_attempt)

    def mark_failed(self, event_id: str, claim_attempt: int, error_code: str, **kwargs: object):
        self._calls.append(f"mark_failed:{error_code}")
        return self._inner.mark_failed(event_id, claim_attempt, error_code, **kwargs)  # type: ignore[arg-type]

    def reclaim_expired(self, **kwargs: object):
        self._calls.append("reclaim")
        return self._inner.reclaim_expired(**kwargs)  # type: ignore[arg-type]


class _BoundaryObservingTransport:
    """Transport that records whether a delivery boundary was open during the send."""

    def __init__(self, delivery: MemoryOutboxDeliveryRepository, calls: list[str]) -> None:
        self._delivery = delivery
        self._calls = calls
        self.observed_boundary: list[bool] = []
        self.sent: list[str] = []

    def send(self, event: DomainEvent, *, idempotency_key: str) -> None:
        self._calls.append("send")
        self.observed_boundary.append(self._delivery.in_short_transaction)
        self.sent.append(idempotency_key)


class _FailingAcknowledgeDelivery:
    """Delivery proxy whose acknowledge always fails, to expose the at-least-once path."""

    def __init__(self, inner: MemoryOutboxDeliveryRepository, error_code: str) -> None:
        self._inner = inner
        self._error_code = error_code
        self.acknowledge_attempts = 0

    def claim_batch(self, **kwargs: object):
        return self._inner.claim_batch(**kwargs)  # type: ignore[arg-type]

    def mark_published(self, event_id: str, claim_attempt: int):
        self.acknowledge_attempts += 1
        raise DomainError(self._error_code, "the database refused to acknowledge this event")

    def mark_failed(self, event_id: str, claim_attempt: int, error_code: str, **kwargs: object):
        return self._inner.mark_failed(event_id, claim_attempt, error_code, **kwargs)  # type: ignore[arg-type]

    def reclaim_expired(self, **kwargs: object):
        return self._inner.reclaim_expired(**kwargs)  # type: ignore[arg-type]


class _FailingRecordDelivery:
    """Delivery proxy whose negative-acknowledge always fails.

    The transport failure itself reaches the dispatcher first, so this double exposes the
    "the failure could not be persisted" path.
    """

    def __init__(self, inner: MemoryOutboxDeliveryRepository, error_code: str) -> None:
        self._inner = inner
        self._error_code = error_code
        self.failure_record_attempts = 0

    def claim_batch(self, **kwargs: object):
        return self._inner.claim_batch(**kwargs)  # type: ignore[arg-type]

    def mark_published(self, event_id: str, claim_attempt: int):
        return self._inner.mark_published(event_id, claim_attempt)

    def mark_failed(self, event_id: str, claim_attempt: int, error_code: str, **kwargs: object):
        self.failure_record_attempts += 1
        raise DomainError(self._error_code, "the database refused to record this failure")

    def reclaim_expired(self, **kwargs: object):
        return self._inner.reclaim_expired(**kwargs)  # type: ignore[arg-type]


class DispatcherHarness(unittest.TestCase):
    """Shared fixture: one in-memory delivery boundary and one recording transport."""

    def setUp(self) -> None:
        self.delivery = MemoryOutboxDeliveryRepository()
        self.transport = RecordingEventTransport()
        self.config = OutboxDispatcherConfig(
            lease_seconds=30,
            max_attempts=3,
            retry_backoff_seconds=5,
            retry_backoff_cap_seconds=20,
            batch_limit=10,
        )
        self.dispatcher = OutboxDispatcher(self.delivery, self.transport, self.config)

    def add(self, run_id: str = "run_t83demo001", sequence: int = 1) -> DomainEvent:
        event = _event(run_id, sequence)
        self.delivery.add(event)
        return event


class ClaimAndPublishTests(DispatcherHarness):
    """The happy path, the transaction discipline and the idempotency key."""

    def test_pending_becomes_publishing_on_claim_with_the_lease_deadline(self) -> None:
        event = self.add()
        claim = self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)[0]
        self.assertEqual(claim.event.event_id, event.event_id)
        self.assertEqual(claim.claim_attempt, 1, "the first claim is attempt 1")
        self.assertEqual(claim.delivery_status, DELIVERY_PUBLISHING)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PUBLISHING)
        self.assertEqual(stored.attempts, 1, "attempts is incremented by the claim")
        self.assertEqual(stored.available_at, claim.lease_deadline, "available_at is the lease deadline")
        self.assertIsNone(stored.published_at)
        self.assertEqual(self.delivery.count(DELIVERY_PUBLISHING), 1)
        self.assertEqual(self.delivery.count(DELIVERY_PENDING), 0)

    def test_full_transition_pending_publishing_published(self) -> None:
        event = self.add()
        outcomes = self.dispatcher.dispatch_batch(limit=1)
        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.status, STATUS_PUBLISHED)
        self.assertEqual(outcome.claim_attempt, 1)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PUBLISHED)
        self.assertEqual(stored.attempts, 1, "the attempt counter is preserved")
        self.assertIsNotNone(stored.published_at, "published_at is mandatory when published")
        self.assertIsNone(stored.last_error_code)
        self.assertEqual(self.delivery.count(DELIVERY_PUBLISHING), 0)

    def test_transport_is_called_after_the_claim_boundary_closed(self) -> None:
        self.add()
        calls: list[str] = []
        transport = _BoundaryObservingTransport(self.delivery, calls)
        dispatcher = OutboxDispatcher(_RecordingDelivery(self.delivery, calls), transport, self.config)
        dispatcher.dispatch_batch(limit=1)
        self.assertEqual(calls, ["claim", "send", "mark_published"])
        self.assertEqual(transport.observed_boundary, [False], "no delivery boundary may be open during send")
        self.assertFalse(self.delivery.in_short_transaction)

    def test_event_id_is_used_as_the_transport_idempotency_key(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo002", 1)
        self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(sorted(self.transport.idempotency_keys), sorted([first.event_id, second.event_id]))
        for record in self.transport.sent:
            self.assertIsInstance(record, RecordedSend)
            self.assertEqual(record.idempotency_key, record.event_id)

    def test_empty_queue_returns_an_empty_batch_immediately(self) -> None:
        self.assertEqual(self.dispatcher.dispatch_batch(limit=5), ())
        self.assertEqual(self.transport.sent, [])

    def test_acknowledge_requires_a_live_publishing_claim(self) -> None:
        event = self.add()
        with self.assertRaises(DomainError) as captured:
            self.delivery.mark_published(event.event_id, 1)
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CLAIM)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_PENDING)

    def test_claim_object_is_immutable(self) -> None:
        self.add()
        claim = self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)[0]
        with self.assertRaises(FrozenInstanceError):
            claim.claim_attempt = 7  # type: ignore[misc]
        self.assertIsInstance(claim, OutboxClaim)


class FailureAndRetryTests(DispatcherHarness):
    """Retryable, terminal and sanitised transport failures."""

    def test_retryable_failure_returns_to_pending_with_backoff(self) -> None:
        event = self.add()
        available_before = self.delivery.state(event.event_id).available_at
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        outcome = self.dispatcher.dispatch_batch(limit=1)[0]
        self.assertEqual(outcome.status, STATUS_RETRY_SCHEDULED)
        self.assertEqual(outcome.error_code, "ENT-TRANSPORT-TIMEOUT")
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PENDING)
        self.assertEqual(stored.attempts, 1)
        self.assertEqual(stored.last_error_code, "ENT-TRANSPORT-TIMEOUT")
        # The reported backoff is exactly the persisted one and lies in the future.
        self.assertEqual(outcome.available_at, stored.available_at)
        self.assertGreater(stored.available_at, available_before)
        # A row in backoff is not claimable yet, but is claimable after the delay.
        self.assertEqual(self.dispatcher.dispatch_batch(limit=1), ())
        self.delivery.advance(5)
        retried = self.dispatcher.dispatch_batch(limit=1)
        self.assertEqual(len(retried), 1)
        self.assertEqual(retried[0].claim_attempt, 2, "the retry is a new, fenced attempt")

    def test_backoff_doubles_and_is_capped(self) -> None:
        config = self.config
        self.assertEqual(config.backoff_seconds(1), 5)
        self.assertEqual(config.backoff_seconds(2), 10)
        self.assertEqual(config.backoff_seconds(3), 20, "capped at retry_backoff_cap_seconds")
        self.assertEqual(config.backoff_seconds(9), 20)

    def test_non_retryable_failure_is_terminal(self) -> None:
        event = self.add()
        self.transport.fail_next("ENT-TRANSPORT-REJECTED", retryable=False)
        outcome = self.dispatcher.dispatch_batch(limit=1)[0]
        self.assertEqual(outcome.status, STATUS_FAILED)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_FAILED)
        self.assertEqual(stored.last_error_code, "ENT-TRANSPORT-REJECTED")
        self.assertIsNone(stored.published_at)

    def test_attempt_limit_makes_a_retryable_failure_terminal(self) -> None:
        config = OutboxDispatcherConfig(lease_seconds=30, max_attempts=1, retry_backoff_seconds=1)
        self.dispatcher = OutboxDispatcher(self.delivery, self.transport, config)
        event = self.add()
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        outcome = self.dispatcher.dispatch_batch(limit=1)[0]
        self.assertEqual(outcome.status, STATUS_FAILED, "attempts reached max_attempts")
        self.assertEqual(outcome.claim_attempt, 1)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_FAILED)

    def test_unknown_transport_exception_is_mapped_to_the_fixed_safe_code(self) -> None:
        event = self.add()
        leaky = RuntimeError(
            "connection to postgresql://steelai:t0psecret@broker-host:9092 failed for payload secret-value"
        )
        self.transport.raise_next(leaky)
        outcome = self.dispatcher.dispatch_batch(limit=1)[0]
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_TRANSPORT)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.last_error_code, ERROR_OUTBOX_TRANSPORT)
        self.assertEqual(stored.delivery_status, DELIVERY_PENDING, "an unknown failure is retried")
        rendered = f"{outcome.to_dict()} {stored.to_dict()}"
        for forbidden in ("t0psecret", "broker-host", "postgresql://", "secret-value", "RuntimeError"):
            self.assertNotIn(forbidden, rendered)

    def test_transport_error_carries_only_a_safe_code(self) -> None:
        error = TransportError("ENT-TRANSPORT-TIMEOUT", retryable=True)
        self.assertEqual(str(error), "ENT-TRANSPORT-TIMEOUT")
        self.assertTrue(error.retryable)
        with self.assertRaises(DomainError) as captured:
            TransportError("postgresql://user:pw@host/db", retryable=True)
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_custom_exception_with_unsafe_code_falls_back_to_the_fixed_code(self) -> None:
        class Leaky(Exception):
            error_code = "postgresql://user:pw@host/db"
            retryable = True

        event = self.add()
        self.transport.raise_next(Leaky("boom"))
        outcome = self.dispatcher.dispatch_batch(limit=1)[0]
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_TRANSPORT)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.last_error_code, ERROR_OUTBOX_TRANSPORT)
        self.assertNotIn("user", str(stored.to_dict()))

    def test_a_failure_does_not_stop_the_rest_of_the_batch(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo002", 1)
        third = self.add("run_t83demo003", 1)
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        outcomes = self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(len(outcomes), 3)
        by_status = {outcome.event_id: outcome.status for outcome in outcomes}
        self.assertEqual(by_status[first.event_id], STATUS_RETRY_SCHEDULED)
        self.assertEqual(by_status[second.event_id], STATUS_PUBLISHED)
        self.assertEqual(by_status[third.event_id], STATUS_PUBLISHED)

    def test_error_code_must_be_safe_at_the_persistence_boundary(self) -> None:
        event = self.add()
        self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)
        with self.assertRaises(DomainError) as captured:
            self.delivery.mark_failed(
                event.event_id,
                1,
                "failure at https://host/queue?token=abc",
                retry_delay_seconds=1,
                retryable=True,
            )
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_PUBLISHING)
        self.assertTrue(is_safe_error_code("ENT-OUTBOX-LEASE-EXPIRED"))
        self.assertFalse(is_safe_error_code("contains a space"))


class FencingAndLeaseTests(DispatcherHarness):
    """``attempts`` is a fencing token; expired leases are recovered, never lost."""

    def test_expired_lease_is_reclaimed_and_requeued(self) -> None:
        event = self.add()
        self.dispatcher.dispatch_batch(limit=1)
        # A successful dispatch publishes; simulate a worker that died after claiming.
        self.delivery.add(_event("run_t83demo002", 1))
        stale = self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)
        self.assertEqual(len(stale), 1)
        self.assertEqual(self.dispatcher.reclaim_expired(limit=10), (), "the lease is still valid")
        self.delivery.advance(31)
        reclaimed = self.dispatcher.reclaim_expired(limit=10)
        self.assertEqual(len(reclaimed), 1)
        entry = reclaimed[0]
        self.assertEqual(entry.delivery_status, DELIVERY_PENDING)
        self.assertTrue(entry.requeued)
        self.assertEqual(entry.attempts, 1, "the attempt counter is not reset by recovery")
        self.assertEqual(entry.last_error_code, ERROR_OUTBOX_LEASE_EXPIRED)
        stored = self.delivery.state(stale[0].event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PENDING)
        self.assertEqual(stored.last_error_code, ERROR_OUTBOX_LEASE_EXPIRED)
        self.assertNotEqual(stored.available_at, stale[0].lease_deadline)

    def test_expired_lease_at_the_attempt_limit_becomes_failed(self) -> None:
        config = OutboxDispatcherConfig(lease_seconds=1, max_attempts=1, retry_backoff_seconds=1)
        self.dispatcher = OutboxDispatcher(self.delivery, self.transport, config)
        event = self.add()
        claims = self.delivery.claim_batch(limit=1, lease_seconds=1, max_attempts=1)
        self.assertEqual(claims[0].claim_attempt, 1)
        self.delivery.advance(2)
        reclaimed = self.dispatcher.reclaim_expired(limit=10)
        self.assertEqual(len(reclaimed), 1)
        self.assertFalse(reclaimed[0].requeued)
        self.assertEqual(reclaimed[0].delivery_status, DELIVERY_FAILED)
        self.assertEqual(self.delivery.state(event.event_id).last_error_code, ERROR_OUTBOX_LEASE_EXPIRED)
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), (), "a failed row is never claimed")

    def test_old_claim_attempt_cannot_acknowledge_a_new_lease(self) -> None:
        event = self.add()
        self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)
        self.delivery.advance(31)
        self.dispatcher.reclaim_expired(limit=10)
        # A recovered row waits for the first backoff step before it can be claimed.
        self.delivery.advance(self.config.retry_backoff_seconds)
        new_claim = self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)[0]
        self.assertEqual(new_claim.claim_attempt, 2)
        with self.assertRaises(DomainError) as captured:
            self.delivery.mark_published(event.event_id, 1)
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CLAIM)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PUBLISHING)
        self.assertEqual(stored.attempts, 2, "the new lease is untouched")
        self.assertIsNone(stored.published_at)

    def test_old_claim_attempt_cannot_negative_acknowledge_a_new_lease(self) -> None:
        event = self.add()
        self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)
        self.delivery.advance(31)
        self.dispatcher.reclaim_expired(limit=10)
        self.delivery.advance(self.config.retry_backoff_seconds)
        self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)
        code_before = self.delivery.state(event.event_id).last_error_code
        with self.assertRaises(DomainError) as captured:
            self.delivery.mark_failed(
                event.event_id, 1, "ENT-TRANSPORT-TIMEOUT", retry_delay_seconds=5, retryable=True
            )
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CLAIM)
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PUBLISHING)
        self.assertEqual(stored.attempts, 2)
        self.assertEqual(
            stored.last_error_code,
            code_before,
            "a stale worker must not overwrite the lease-recovery code of the new lease",
        )
        self.assertNotEqual(stored.last_error_code, "ENT-TRANSPORT-TIMEOUT")

    def test_stale_worker_failure_is_reported_as_unacknowledged(self) -> None:
        self.add()
        stale_claim = self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=3)[0]
        self.delivery.advance(31)
        self.dispatcher.reclaim_expired(limit=10)
        self.delivery.advance(self.config.retry_backoff_seconds)
        dispatcher = OutboxDispatcher(self.delivery, self.transport, self.config)
        # The dispatcher re-claims (attempt 2) and succeeds on the fresh lease.
        self.assertEqual(dispatcher.dispatch_batch(limit=1)[0].claim_attempt, 2)
        with self.assertRaises(DomainError) as captured:
            self.delivery.mark_published(stale_claim.event_id, stale_claim.claim_attempt)
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CLAIM)


class OrderingAndParallelismTests(DispatcherHarness):
    """One run is strictly ordered; different runs are independent."""

    def test_later_event_of_a_run_is_blocked_by_the_earlier_one(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo001", 2)
        third = self.add("run_t83demo001", 3)
        claims = self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual([claim.event_id for claim in claims], [first.event_id])
        self.assertEqual(self.delivery.state(second.event_id).delivery_status, DELIVERY_PENDING)
        self.assertEqual(self.delivery.state(third.event_id).delivery_status, DELIVERY_PENDING)
        self.assertEqual(self.delivery.state(first.event_id).delivery_status, DELIVERY_PUBLISHED)
        # Only after the earlier event is published does the next one become claimable.
        self.assertEqual([outcome.event_id for outcome in self.dispatcher.dispatch_batch(limit=10)], [second.event_id])
        self.assertEqual([outcome.event_id for outcome in self.dispatcher.dispatch_batch(limit=10)], [third.event_id])

    def test_later_event_stays_blocked_while_the_earlier_one_backs_off(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo001", 2)
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(self.delivery.state(first.event_id).delivery_status, DELIVERY_PENDING)
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), (), "the run is in backoff, not skipped")
        self.delivery.advance(5)
        self.assertEqual([outcome.event_id for outcome in self.dispatcher.dispatch_batch(limit=10)], [first.event_id])
        self.assertEqual(self.delivery.state(second.event_id).delivery_status, DELIVERY_PENDING)

    def test_later_event_stays_blocked_when_the_earlier_one_failed(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo001", 2)
        self.transport.fail_next("ENT-TRANSPORT-REJECTED", retryable=False)
        self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(self.delivery.state(first.event_id).delivery_status, DELIVERY_FAILED)
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), (), "a failed event blocks its run")
        self.delivery.advance(10_000)
        self.assertEqual(self.dispatcher.reclaim_expired(limit=10), ())
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), (), "there is no skip and no manual unlock")

    def test_different_runs_are_claimed_together(self) -> None:
        events = [self.add(f"run_t83demo00{index}", 1) for index in range(1, 4)]
        outcomes = self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(sorted(outcome.event_id for outcome in outcomes), sorted(event.event_id for event in events))
        self.assertEqual({outcome.status for outcome in outcomes}, {STATUS_PUBLISHED})

    def test_batch_limit_bounds_the_claim(self) -> None:
        events = [self.add(f"run_t83demo00{index}", 1) for index in range(1, 5)]
        outcomes = self.dispatcher.dispatch_batch(limit=2)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(self.delivery.count(DELIVERY_PUBLISHED), 2)
        self.assertEqual(self.delivery.count(DELIVERY_PENDING), len(events) - 2)

    def test_published_rows_are_never_claimed_again(self) -> None:
        event = self.add()
        self.dispatcher.dispatch_batch(limit=10)
        self.assertEqual(self.dispatcher.dispatch_batch(limit=10), ())
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_PUBLISHED)

    def test_failed_rows_are_never_claimed_again(self) -> None:
        event = self.add()
        self.transport.fail_next("ENT-TRANSPORT-REJECTED", retryable=False)
        self.dispatcher.dispatch_batch(limit=10)
        for _ in range(3):
            self.delivery.advance(1000)
            self.assertEqual(self.dispatcher.dispatch_batch(limit=10), ())
        self.assertEqual(len(self.transport.sent), 0)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_FAILED)


class AtLeastOnceTests(DispatcherHarness):
    """The documented at-least-once recovery path, never an exactly-once claim."""

    def test_sent_but_unacknowledged_is_delivered_with_unknown_state(self) -> None:
        """The transport returned successfully but the acknowledge did not commit."""
        event = self.add()
        delivery = _FailingAcknowledgeDelivery(self.delivery, ERROR_OUTBOX_CLAIM)
        dispatcher = OutboxDispatcher(delivery, self.transport, self.config)  # type: ignore[arg-type]
        outcomes = dispatcher.dispatch_batch(limit=1)
        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.status, STATUS_SENT_UNACKNOWLEDGED)
        self.assertTrue(outcome.delivered, "the transport really did send the event")
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.redelivery_possible)
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_CLAIM)
        # The transport ran, but the row is still leased: it will be sent again.
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_PUBLISHING)

        self.delivery.advance(31)
        reclaimed = dispatcher.reclaim_expired(limit=1)
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0].last_error_code, ERROR_OUTBOX_LEASE_EXPIRED)
        self.delivery.advance(self.config.retry_backoff_seconds)
        self.assertEqual([outcome.event_id for outcome in dispatcher.dispatch_batch(limit=1)], [event.event_id])
        # Sent twice with the same idempotency key: the downstream must deduplicate.
        self.assertEqual(self.transport.idempotency_keys, [event.event_id, event.event_id])
        self.assertEqual(self.delivery.state(event.event_id).attempts, 2)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_PUBLISHING)

    def test_sent_but_unacknowledged_never_leaks_transport_or_database_text(self) -> None:
        self.add()
        delivery = _FailingAcknowledgeDelivery(self.delivery, ERROR_OUTBOX_CLAIM)
        outcome = OutboxDispatcher(delivery, self.transport, self.config).dispatch_batch(limit=1)[0]  # type: ignore[arg-type]
        rendered = str(outcome.to_dict())
        for forbidden in ("postgresql://", "host", "password", "Traceback", "DomainError"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_CLAIM)

    def test_a_failure_that_cannot_be_recorded_is_not_reported_as_delivered(self) -> None:
        """The transport failed and the failure could not be persisted either."""
        event = self.add()
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        delivery = _FailingRecordDelivery(self.delivery, ERROR_OUTBOX_CLAIM)
        dispatcher = OutboxDispatcher(delivery, self.transport, self.config)  # type: ignore[arg-type]
        outcomes = dispatcher.dispatch_batch(limit=1)
        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.status, STATUS_FAILURE_UNRECORDED)
        self.assertFalse(outcome.delivered, "the event was never sent, so it is not delivered")
        self.assertFalse(outcome.persistence_state_known)
        self.assertTrue(outcome.redelivery_possible)
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_CLAIM)
        self.assertEqual(delivery.failure_record_attempts, 1)
        self.assertEqual(self.transport.sent, [], "the transport failed, nothing was sent")
        # The row is still leased with its original attempt: recovery can redeliver it.
        stored = self.delivery.state(event.event_id)
        self.assertEqual(stored.delivery_status, DELIVERY_PUBLISHING)
        self.assertEqual(stored.attempts, 1)
        rendered = str(outcome.to_dict())
        for forbidden in ("postgresql://", "host", "password", "Traceback", "DomainError"):
            self.assertNotIn(forbidden, rendered)

    def test_failure_unrecorded_does_not_stop_the_rest_of_the_batch(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo002", 1)
        third = self.add("run_t83demo003", 1)
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        delivery = _FailingRecordDelivery(self.delivery, ERROR_OUTBOX_CLAIM)
        dispatcher = OutboxDispatcher(delivery, self.transport, self.config)  # type: ignore[arg-type]
        outcomes = dispatcher.dispatch_batch(limit=10)
        by_id = {outcome.event_id: outcome.status for outcome in outcomes}
        self.assertEqual(by_id[first.event_id], STATUS_FAILURE_UNRECORDED)
        self.assertEqual(by_id[second.event_id], STATUS_PUBLISHED)
        self.assertEqual(by_id[third.event_id], STATUS_PUBLISHED)
        self.assertEqual(len(outcomes), 3, "one unknown state must not abort the batch")

    def test_sent_unacknowledged_does_not_stop_the_rest_of_the_batch(self) -> None:
        first = self.add("run_t83demo001", 1)
        second = self.add("run_t83demo002", 1)
        delivery = _FailingAcknowledgeDelivery(self.delivery, ERROR_OUTBOX_CLAIM)
        dispatcher = OutboxDispatcher(delivery, self.transport, self.config)  # type: ignore[arg-type]
        outcomes = dispatcher.dispatch_batch(limit=10)
        by_id = {outcome.event_id: outcome.status for outcome in outcomes}
        self.assertEqual(by_id[first.event_id], STATUS_SENT_UNACKNOWLEDGED)
        self.assertEqual(by_id[second.event_id], STATUS_SENT_UNACKNOWLEDGED)
        self.assertEqual(len(outcomes), 2, "one unknown state must not abort the batch")
        self.assertEqual(sorted(self.transport.event_ids), sorted([first.event_id, second.event_id]))

    def test_recovery_path_is_reported_not_silently_successful(self) -> None:
        self.add()
        delivery = _FailingAcknowledgeDelivery(self.delivery, ERROR_OUTBOX_CLAIM)
        outcome = OutboxDispatcher(delivery, self.transport, self.config).dispatch_batch(limit=1)[0]  # type: ignore[arg-type]
        self.assertNotEqual(outcome.status, STATUS_PUBLISHED)
        self.assertTrue(outcome.delivered, "the transport did deliver it at least once")
        self.assertFalse(self.delivery.state(outcome.event_id).delivery_status == DELIVERY_PUBLISHED)
        self.assertIsInstance(outcome, OutboxDispatchOutcome)

    def test_stale_claim_failure_is_reported_as_failure_unrecorded(self) -> None:
        event = self.add()
        stale = self.delivery.claim_batch(limit=1, lease_seconds=30, max_attempts=5)[0]
        self.delivery.advance(31)
        self.dispatcher.reclaim_expired(limit=1)
        self.delivery.advance(self.config.retry_backoff_seconds)
        # A second dispatcher takes the event over and publishes it.
        second = OutboxDispatcher(self.delivery, RecordingEventTransport(), self.config)
        second.dispatch_batch(limit=1)
        # The first worker now tries to record a failure with its stale token.
        self.transport.fail_next("ENT-TRANSPORT-TIMEOUT", retryable=True)
        outcome = self.dispatcher._deliver(stale)  # noqa: SLF001 - the stale worker's own path
        self.assertEqual(outcome.status, STATUS_FAILURE_UNRECORDED)
        self.assertFalse(outcome.delivered)
        self.assertFalse(outcome.persistence_state_known)
        self.assertEqual(outcome.error_code, ERROR_OUTBOX_CLAIM)
        self.assertEqual(self.delivery.state(event.event_id).delivery_status, DELIVERY_PUBLISHED)


class ConfigurationTests(DispatcherHarness):
    """Illegal configuration and illegal call arguments fail closed."""

    def test_illegal_dispatcher_configuration_fails_closed(self) -> None:
        cases = {
            "lease_seconds=0": {"lease_seconds": 0},
            "lease_seconds=True": {"lease_seconds": True},
            "max_attempts=-1": {"max_attempts": -1},
            "retry_backoff_seconds=0": {"retry_backoff_seconds": 0},
            "batch_limit=0": {"batch_limit": 0},
            "cap below base": {"retry_backoff_seconds": 10, "retry_backoff_cap_seconds": 5},
            "non integer": {"lease_seconds": "30"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name), self.assertRaises(DomainError) as captured:
                OutboxDispatcherConfig(**overrides)  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_illegal_call_limits_fail_closed(self) -> None:
        self.add()
        for bad_limit in (0, -3, True, "2", 1.5):
            with self.subTest(limit=bad_limit), self.assertRaises(DomainError) as captured:
                self.dispatcher.dispatch_batch(limit=bad_limit)  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)
            with self.assertRaises(DomainError) as captured_reclaim:
                self.dispatcher.reclaim_expired(limit=bad_limit)  # type: ignore[arg-type]
            self.assertEqual(captured_reclaim.exception.code, ERROR_OUTBOX_CONFIG)
        self.assertEqual(self.transport.sent, [], "a refused call must not send anything")

    def test_illegal_claim_arguments_fail_closed(self) -> None:
        self.add()
        for name, kwargs in {
            "limit": {"limit": 0, "lease_seconds": 30, "max_attempts": 3},
            "lease": {"limit": 1, "lease_seconds": 0, "max_attempts": 3},
            "attempts": {"limit": 1, "lease_seconds": 30, "max_attempts": 0},
        }.items():
            with self.subTest(argument=name), self.assertRaises(DomainError) as captured:
                self.delivery.claim_batch(**kwargs)  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_invalid_reclaim_arguments_fail_closed(self) -> None:
        with self.assertRaises(DomainError) as captured:
            self.delivery.reclaim_expired(limit=1, max_attempts=3, retry_delay_seconds=0)
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_default_configuration_is_bounded_and_valid(self) -> None:
        config = OutboxDispatcherConfig()
        self.assertEqual(config.backoff_seconds(1), config.retry_backoff_seconds)
        self.assertLessEqual(config.backoff_seconds(50), config.retry_backoff_cap_seconds)
        dispatcher = OutboxDispatcher(self.delivery, self.transport, config)
        self.assertIs(dispatcher.config, config)


class OutboxContractValidationTests(unittest.TestCase):
    """The delivery DTOs reject objects a dispatcher must never see.

    These tests construct the objects **directly**, so the contract of ``OutboxClaim`` and
    ``OutboxReclaim`` is proven independently of what the two adapters happen to produce.
    """

    def _event(self) -> DomainEvent:
        return _event()

    def test_a_valid_directly_constructed_claim_is_accepted(self) -> None:
        claim = OutboxClaim(
            event=self._event(),
            claim_attempt=1,
            lease_deadline="2026-09-18T10:00:00+00:00",
        )
        self.assertEqual(claim.delivery_status, DELIVERY_PUBLISHING)
        self.assertEqual(claim.claim_attempt, 1)

    def test_claim_rejects_a_row_that_is_not_publishing(self) -> None:
        for status in (DELIVERY_PENDING, DELIVERY_PUBLISHED, DELIVERY_FAILED, "made_up"):
            with self.subTest(delivery_status=status), self.assertRaises(DomainError) as captured:
                OutboxClaim(
                    event=self._event(),
                    claim_attempt=1,
                    lease_deadline="2026-09-18T10:00:00+00:00",
                    delivery_status=status,
                )
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_claim_rejects_an_invalid_attempt_counter(self) -> None:
        for attempt in (0, -1, True, "1", 1.5, None):
            with self.subTest(claim_attempt=attempt), self.assertRaises(DomainError) as captured:
                OutboxClaim(
                    event=self._event(),
                    claim_attempt=attempt,  # type: ignore[arg-type]
                    lease_deadline="2026-09-18T10:00:00+00:00",
                )
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_claim_rejects_a_lease_deadline_without_a_timezone(self) -> None:
        for deadline in ("2026-09-18T10:00:00", "not a timestamp", "", None, 1234):
            with self.subTest(lease_deadline=deadline), self.assertRaises(DomainError) as captured:
                OutboxClaim(
                    event=self._event(),
                    claim_attempt=1,
                    lease_deadline=deadline,  # type: ignore[arg-type]
                )
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_claim_rejects_a_non_domain_event(self) -> None:
        with self.assertRaises(DomainError) as captured:
            OutboxClaim(
                event={"event_id": "evt_x"},  # type: ignore[arg-type]
                claim_attempt=1,
                lease_deadline="2026-09-18T10:00:00+00:00",
            )
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_reclaim_accepts_only_pending_or_failed(self) -> None:
        valid = {
            "event_id": "evt_" + "a" * 64,
            "run_id": "run_t83demo001",
            "sequence": 1,
            "attempts": 2,
            "delivery_status": DELIVERY_PENDING,
            "available_at": "2026-09-18T10:00:00+00:00",
            "last_error_code": ERROR_OUTBOX_LEASE_EXPIRED,
        }
        reclaim = OutboxReclaim(**valid)  # type: ignore[arg-type]
        self.assertTrue(reclaim.requeued)
        for status in (DELIVERY_PUBLISHING, DELIVERY_PUBLISHED, "made_up"):
            with self.subTest(delivery_status=status), self.assertRaises(DomainError) as captured:
                OutboxReclaim(**{**valid, "delivery_status": status})  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_reclaim_rejects_an_unsafe_error_code_and_an_invalid_attempt(self) -> None:
        base = {
            "event_id": "evt_" + "a" * 64,
            "run_id": "run_t83demo001",
            "sequence": 1,
            "attempts": 1,
            "delivery_status": DELIVERY_PENDING,
            "available_at": "2026-09-18T10:00:00+00:00",
            "last_error_code": ERROR_OUTBOX_LEASE_EXPIRED,
        }
        cases = {
            "unsafe code": {"last_error_code": "failed at https://host/path?token=abc"},
            "empty code": {"last_error_code": ""},
            "zero attempts": {"attempts": 0},
            "negative attempts": {"attempts": -2},
            "non integer attempts": {"attempts": "3"},
            "naive timestamp": {"available_at": "2026-09-18T10:00:00"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name), self.assertRaises(DomainError) as captured:
                OutboxReclaim(**{**base, **overrides})  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)


class OutcomeSemanticsTests(unittest.TestCase):
    """``status`` alone decides the three outcome properties."""

    EXPECTED = {
        STATUS_PUBLISHED: (True, True, False),
        STATUS_RETRY_SCHEDULED: (False, True, True),
        STATUS_FAILED: (False, True, False),
        STATUS_SENT_UNACKNOWLEDGED: (True, False, True),
        STATUS_FAILURE_UNRECORDED: (False, False, True),
    }

    def _make_outcome(self, status: str) -> OutboxDispatchOutcome:
        return OutboxDispatchOutcome(
            event_id="evt_" + "a" * 64,
            run_id="run_t83demo001",
            sequence=1,
            claim_attempt=1,
            status=status,
        )

    def test_property_table_is_exactly_the_agreed_contract(self) -> None:
        self.assertEqual(set(OUTCOME_PROPERTIES), set(self.EXPECTED))
        for status, expected in self.EXPECTED.items():
            with self.subTest(status=status):
                outcome = self._make_outcome(status)
                self.assertEqual(
                    (outcome.delivered, outcome.persistence_state_known, outcome.redelivery_possible),
                    expected,
                )
                self.assertEqual(OUTCOME_PROPERTIES[status], expected)

    def test_the_two_unknown_states_are_distinct(self) -> None:
        sent = self._make_outcome(STATUS_SENT_UNACKNOWLEDGED)
        unrecorded = self._make_outcome(STATUS_FAILURE_UNRECORDED)
        self.assertNotEqual(sent.status, unrecorded.status)
        self.assertTrue(sent.delivered)
        self.assertFalse(unrecorded.delivered, "an unsent event must never be reported as delivered")
        self.assertFalse(sent.persistence_state_known)
        self.assertFalse(unrecorded.persistence_state_known)
        self.assertTrue(sent.redelivery_possible)
        self.assertTrue(unrecorded.redelivery_possible)

    def test_an_unknown_status_is_rejected(self) -> None:
        for status in ("unacknowledged", "unknown", "", "PUBLISHED", None):
            with self.subTest(status=status), self.assertRaises(DomainError) as captured:
                self._make_outcome(status)  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_outcome_rejects_an_unsafe_error_code(self) -> None:
        with self.assertRaises(DomainError) as captured:
            OutboxDispatchOutcome(
                event_id="evt_" + "a" * 64,
                run_id="run_t83demo001",
                sequence=1,
                claim_attempt=1,
                status=STATUS_RETRY_SCHEDULED,
                error_code="failed at https://host/queue?token=abc",
            )
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)

    def test_there_is_no_needs_redelivery_property_any_more(self) -> None:
        outcome = self._make_outcome(STATUS_SENT_UNACKNOWLEDGED)
        self.assertFalse(hasattr(outcome, "needs_redelivery"))
        self.assertTrue(outcome.redelivery_possible)
        self.assertNotIn("needs_redelivery", outcome.to_dict())
        self.assertTrue(outcome.to_dict()["delivered"])


class PublicImportPathTests(unittest.TestCase):
    """The recommended import paths work and keep the optional dependency optional."""

    def test_ports_package_exports_the_delivery_contract(self) -> None:
        from steelai.enterprise_lab import ports

        for name in (
            "OutboxClaim",
            "OutboxReclaim",
            "OutboxDeliveryState",
            "OutboxDeliveryRepository",
            "EventTransport",
            "TransportError",
            "DELIVERY_PENDING",
            "DELIVERY_PUBLISHING",
            "DELIVERY_PUBLISHED",
            "DELIVERY_FAILED",
            "ERROR_OUTBOX_CLAIM",
            "ERROR_OUTBOX_TRANSPORT",
            "ERROR_OUTBOX_CONFIG",
            "ERROR_OUTBOX_LEASE_EXPIRED",
        ):
            with self.subTest(name=name):
                self.assertIn(name, ports.__all__)
                self.assertTrue(hasattr(ports, name))

    def test_application_package_exports_the_dispatcher_and_outcomes(self) -> None:
        from steelai.enterprise_lab import application

        for name in (
            "OutboxDispatcher",
            "OutboxDispatcherConfig",
            "OutboxDispatchOutcome",
            "STATUS_PUBLISHED",
            "STATUS_RETRY_SCHEDULED",
            "STATUS_FAILED",
            "STATUS_SENT_UNACKNOWLEDGED",
            "STATUS_FAILURE_UNRECORDED",
        ):
            with self.subTest(name=name):
                self.assertIn(name, application.__all__)
                self.assertTrue(hasattr(application, name))

    def test_adapters_package_exports_the_offline_delivery_adapter(self) -> None:
        from steelai.enterprise_lab import adapters

        for name in ("MemoryOutboxDeliveryRepository", "RecordingEventTransport", "RecordedSend"):
            with self.subTest(name=name):
                self.assertIn(name, adapters.__all__)
                self.assertTrue(hasattr(adapters, name))
        self.assertFalse(
            any("postgresql" in module for module in _imported_modules(PACKAGE / "adapters" / "__init__.py")),
            "the adapters package must not import the optional PostgreSQL adapter",
        )

    def test_top_level_package_exports_the_dependency_free_t83_types(self) -> None:
        from steelai.enterprise_lab import (
            MemoryOutboxDeliveryRepository,
            OutboxClaim,
            OutboxDispatchOutcome,
            OutboxDispatcher,
            OutboxDispatcherConfig,
            RecordingEventTransport,
            STATUS_FAILURE_UNRECORDED,
            STATUS_SENT_UNACKNOWLEDGED,
        )

        self.assertTrue(callable(OutboxDispatcher))
        self.assertTrue(callable(OutboxDispatcherConfig))
        self.assertEqual(STATUS_SENT_UNACKNOWLEDGED, "sent_unacknowledged")
        self.assertEqual(STATUS_FAILURE_UNRECORDED, "failure_unrecorded")
        self.assertIsNotNone(OutboxClaim)
        self.assertIsNotNone(OutboxDispatchOutcome)
        self.assertIsNotNone(MemoryOutboxDeliveryRepository)
        self.assertIsNotNone(RecordingEventTransport)

    def test_top_level_import_never_loads_the_postgresql_adapter_or_database_packages(self) -> None:
        code = (
            "import sys\n"
            "import steelai.enterprise_lab  # noqa: F401\n"
            "import steelai.enterprise_lab.ports  # noqa: F401\n"
            "import steelai.enterprise_lab.application  # noqa: F401\n"
            "import steelai.enterprise_lab.adapters  # noqa: F401\n"
            f"print(','.join(m for m in {FORBIDDEN_RUNTIME_MODULES!r} if m in sys.modules))\n"
            "print('steelai.enterprise_lab.adapters.postgresql' in sys.modules)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(lines[0].strip(), "", "the lab packages must not load a database driver")
        self.assertEqual(lines[1].strip(), "False")

    def test_postgresql_package_exports_the_delivery_adapter(self) -> None:
        code = (
            "from steelai.enterprise_lab.adapters.postgresql import PostgreSQLOutboxDeliveryRepository\n"
            "import steelai.enterprise_lab.adapters.postgresql as package\n"
            "print('PostgreSQLOutboxDeliveryRepository' in package.__all__)\n"
            "print(callable(PostgreSQLOutboxDeliveryRepository))\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["True", "True"])


class RecordingTransportTests(unittest.TestCase):
    """The recording transport is inert: no network, no filesystem, no broker."""

    def test_recording_transport_performs_no_network_or_file_access(self) -> None:
        transport = RecordingEventTransport()
        event = _event()
        with mock.patch("socket.socket", side_effect=AssertionError("network access")), mock.patch(
            "builtins.open", side_effect=AssertionError("filesystem access")
        ):
            transport.send(event, idempotency_key=event.event_id)
        self.assertEqual(transport.event_ids, [event.event_id])

    def test_recording_transport_module_imports_no_io_library(self) -> None:
        source = (PACKAGE / "adapters" / "outbox_memory.py").read_text(encoding="utf-8")
        imported = _imported_modules_from_source(source)
        for module in DISALLOWED_DISPATCHER_MODULES:
            self.assertNotIn(module, imported, f"the offline adapter must not import {module}")

    def test_recording_transport_needs_no_running_broker(self) -> None:
        transport = RecordingEventTransport()
        event = _event()
        transport.send(event, idempotency_key=event.event_id)
        self.assertIsInstance(transport.sent[0], RecordedSend)
        self.assertEqual(transport.sent[0].run_id, event.run_id)
        self.assertEqual(transport.sent[0].sequence, event.sequence)


class ArchitectureBoundaryTests(unittest.TestCase):
    """T83 stays inside the hexagon and away from the default application."""

    def test_dispatcher_imports_no_database_or_background_framework(self) -> None:
        offenders: list[str] = []
        for relative in ("application/outbox_dispatcher.py", "ports/outbox.py"):
            modules = _imported_modules(PACKAGE / relative)
            for module in modules:
                head = module.split(".")[0]
                if head in FORBIDDEN_RUNTIME_MODULES or head in DISALLOWED_DISPATCHER_MODULES:
                    offenders.append(f"{relative}: {module}")
        self.assertEqual(offenders, [])

    def test_dispatcher_has_no_daemon_loop_or_timer(self) -> None:
        source = (PACKAGE / "application" / "outbox_dispatcher.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True:
                self.fail("the dispatcher must not contain an unbounded loop")
        self.assertNotIn("threading", source)
        self.assertNotIn("asyncio", source)
        self.assertNotIn("sleep(", source)

    def test_ports_and_dispatcher_keep_the_frozen_delivery_vocabulary(self) -> None:
        from steelai.enterprise_lab.adapters.postgresql.constraints import DELIVERY_STATUS_VALUES

        self.assertEqual(DELIVERY_STATUSES, DELIVERY_STATUS_VALUES)
        self.assertEqual(
            (DELIVERY_PENDING, DELIVERY_PUBLISHING, DELIVERY_PUBLISHED, DELIVERY_FAILED),
            DELIVERY_STATUS_VALUES,
        )

    def test_ports_are_runtime_checkable_protocols(self) -> None:
        self.assertIsInstance(MemoryOutboxDeliveryRepository(), OutboxDeliveryRepository)
        self.assertIsInstance(RecordingEventTransport(), EventTransport)
        self.assertFalse(isinstance(object(), OutboxDeliveryRepository))

    def test_default_application_does_not_import_the_dispatcher_or_database(self) -> None:
        code = (
            "import sys\n"
            "import app  # noqa: F401\n"
            f"print(','.join(m for m in {FORBIDDEN_RUNTIME_MODULES!r} if m in sys.modules))\n"
            "print('steelai.enterprise_lab.adapters.postgresql' in sys.modules)\n"
            "print('steelai.enterprise_lab.application.outbox_dispatcher' in sys.modules)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "False")
        self.assertEqual(lines[2].strip(), "False", "the default application must not wire the dispatcher")

    def test_outbox_delivery_state_rejects_unsafe_persisted_codes(self) -> None:
        from steelai.enterprise_lab.ports.outbox import OutboxDeliveryState

        with self.assertRaises(DomainError) as captured:
            OutboxDeliveryState(
                event_id="evt_x",
                run_id="run_x",
                sequence=1,
                delivery_status=DELIVERY_FAILED,
                attempts=1,
                available_at="2026-09-18T00:00:00+00:00",
                last_error_code="see https://host/path",
            )
        self.assertEqual(captured.exception.code, ERROR_OUTBOX_CONFIG)


def _imported_modules(path: Path) -> set[str]:
    return _imported_modules_from_source(path.read_text(encoding="utf-8"))


def _imported_modules_from_source(source: str) -> set[str]:
    tree = ast.parse(source)
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
