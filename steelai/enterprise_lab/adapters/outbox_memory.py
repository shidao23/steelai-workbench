"""In-memory outbox delivery adapter and recording transport (T83).

Two test-only building blocks live here:

- :class:`MemoryOutboxDeliveryRepository` mirrors the PostgreSQL delivery contract
  exactly (claim predicate, ``attempts`` fencing, lease recovery, per-run ordering), so
  the offline suite proves the dispatcher against the same semantics without a server;
- :class:`RecordingEventTransport` records what a transport would have sent and never
  touches the network, the filesystem or any external system. It exists to prove the
  interface and the flow: it is **not** a Kafka adapter and proves nothing about Kafka.

Neither class is wired into the default application.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from ..domain.models import DomainError, DomainEvent
from ..ports.outbox import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_PUBLISHED,
    DELIVERY_PUBLISHING,
    ERROR_OUTBOX_CLAIM,
    ERROR_OUTBOX_LEASE_EXPIRED,
    OutboxClaim,
    OutboxDeliveryState,
    OutboxReclaim,
    TransportError,
    require_positive_int,
    require_safe_error_code,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise DomainError(ERROR_OUTBOX_CLAIM, "stored timestamps must carry a timezone")
    return moment.astimezone(timezone.utc).isoformat()


@dataclass
class _Row:
    """One outbox row: the domain event plus the five delivery columns."""

    event: DomainEvent
    delivery_status: str = DELIVERY_PENDING
    attempts: int = 0
    available_at: datetime = field(default_factory=_utc_now)
    published_at: datetime | None = None
    last_error_code: str | None = None


class MemoryOutboxDeliveryRepository:
    """In-memory :class:`~steelai.enterprise_lab.ports.outbox.OutboxDeliveryRepository`.

    The clock is injectable so a test can advance time deterministically; the default
    clock is the system UTC clock, mirroring the database clock of the PostgreSQL
    adapter. ``in_short_transaction`` is ``True`` only while one claim or acknowledge
    call is executing, which lets a test prove the transport is never called while a
    delivery boundary is open.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utc_now
        self._offset = timedelta(0)
        self._rows: dict[str, _Row] = {}
        self._in_short_transaction = False

    # -- clock -----------------------------------------------------------------
    def _now(self) -> datetime:
        return self._clock() + self._offset

    # -- test helpers ----------------------------------------------------------
    @property
    def in_short_transaction(self) -> bool:
        """True only inside a claim/acknowledge call, never during a transport send."""
        return self._in_short_transaction

    def add(self, event: DomainEvent) -> None:
        """Append a ``pending`` row with ``attempts = 0``, as the T82 write side does."""
        if event.event_id in self._rows:
            raise DomainError(ERROR_OUTBOX_CLAIM, "event_id already exists", details={"event_id": event.event_id})
        self._rows[event.event_id] = _Row(event=event, available_at=self._now())

    def state(self, event_id: str) -> OutboxDeliveryState:
        return self._state_of(self._row(event_id))

    def count(self, delivery_status: str | None = None) -> int:
        if delivery_status is None:
            return len(self._rows)
        return sum(1 for row in self._rows.values() if row.delivery_status == delivery_status)

    def advance(self, seconds: int) -> None:
        """Move the clock forward, e.g. to expire a lease in a test."""
        require_positive_int(seconds, "seconds")
        self._offset += timedelta(seconds=seconds)

    # -- delivery contract -----------------------------------------------------
    def claim_batch(self, *, limit: int, lease_seconds: int, max_attempts: int) -> Sequence[OutboxClaim]:
        require_positive_int(limit, "limit")
        require_positive_int(lease_seconds, "lease_seconds")
        require_positive_int(max_attempts, "max_attempts")
        self._in_short_transaction = True
        try:
            now = self._now()
            claims: list[OutboxClaim] = []
            for row in self._claimable(now=now, limit=limit, max_attempts=max_attempts):
                row.attempts += 1
                row.delivery_status = DELIVERY_PUBLISHING
                row.available_at = now + timedelta(seconds=lease_seconds)
                row.published_at = None
                claims.append(
                    OutboxClaim(
                        event=row.event,
                        claim_attempt=row.attempts,
                        lease_deadline=_to_iso(row.available_at),
                    )
                )
            return tuple(claims)
        finally:
            self._in_short_transaction = False

    def mark_published(self, event_id: str, claim_attempt: int) -> OutboxDeliveryState:
        require_positive_int(claim_attempt, "claim_attempt")
        self._in_short_transaction = True
        try:
            row = self._require_claim(event_id, claim_attempt)
            row.delivery_status = DELIVERY_PUBLISHED
            row.published_at = self._now()
            row.last_error_code = None
            return self._state_of(row)
        finally:
            self._in_short_transaction = False

    def mark_failed(
        self,
        event_id: str,
        claim_attempt: int,
        error_code: str,
        *,
        retry_delay_seconds: int,
        retryable: bool,
    ) -> OutboxDeliveryState:
        require_positive_int(claim_attempt, "claim_attempt")
        safe_code = require_safe_error_code(error_code)
        if retryable:
            require_positive_int(retry_delay_seconds, "retry_delay_seconds")
        self._in_short_transaction = True
        try:
            row = self._require_claim(event_id, claim_attempt)
            if retryable:
                row.delivery_status = DELIVERY_PENDING
                row.available_at = self._now() + timedelta(seconds=retry_delay_seconds)
            else:
                row.delivery_status = DELIVERY_FAILED
            row.last_error_code = safe_code
            return self._state_of(row)
        finally:
            self._in_short_transaction = False

    def reclaim_expired(
        self,
        *,
        limit: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> Sequence[OutboxReclaim]:
        require_positive_int(limit, "limit")
        require_positive_int(max_attempts, "max_attempts")
        require_positive_int(retry_delay_seconds, "retry_delay_seconds")
        self._in_short_transaction = True
        try:
            now = self._now()
            expired = [
                row
                for row in self._rows.values()
                if row.delivery_status == DELIVERY_PUBLISHING and row.available_at <= now
            ]
            expired.sort(key=lambda row: (row.available_at, row.event.run_id, row.event.sequence))
            reclaimed: list[OutboxReclaim] = []
            for row in expired[:limit]:
                if row.attempts >= max_attempts:
                    row.delivery_status = DELIVERY_FAILED
                else:
                    row.delivery_status = DELIVERY_PENDING
                    row.available_at = now + timedelta(seconds=retry_delay_seconds)
                row.last_error_code = ERROR_OUTBOX_LEASE_EXPIRED
                reclaimed.append(
                    OutboxReclaim(
                        event_id=row.event.event_id,
                        run_id=row.event.run_id,
                        sequence=row.event.sequence,
                        attempts=row.attempts,
                        delivery_status=row.delivery_status,
                        available_at=_to_iso(row.available_at),
                        last_error_code=ERROR_OUTBOX_LEASE_EXPIRED,
                    )
                )
            return tuple(reclaimed)
        finally:
            self._in_short_transaction = False

    # -- internals -------------------------------------------------------------
    def _claimable(self, *, now: datetime, limit: int, max_attempts: int) -> list[_Row]:
        """Rows that may be claimed now: available, under the attempt cap, first of run.

        The ``sequence`` filter is what enforces the per-run contract: an event is only
        claimable when it is the smallest sequence of its run that is not yet
        ``published``. A later event is therefore blocked by an earlier event that is
        pending, publishing, backing off or terminally failed.
        """
        claimable: list[_Row] = []
        for row in self._rows.values():
            if row.delivery_status != DELIVERY_PENDING:
                continue
            if row.available_at > now or row.attempts >= max_attempts:
                continue
            first_open = min(
                candidate.event.sequence
                for candidate in self._rows.values()
                if candidate.event.run_id == row.event.run_id
                and candidate.delivery_status != DELIVERY_PUBLISHED
            )
            if row.event.sequence != first_open:
                continue
            claimable.append(row)
        claimable.sort(key=lambda row: (row.event.run_id, row.event.sequence))
        return claimable[:limit]

    def _row(self, event_id: str) -> _Row:
        row = self._rows.get(event_id)
        if row is None:
            raise DomainError(ERROR_OUTBOX_CLAIM, "unknown outbox event", details={"event_id": event_id})
        return row

    def _require_claim(self, event_id: str, claim_attempt: int) -> _Row:
        """Accept an acknowledge only for a live claim with the same fencing token."""
        row = self._row(event_id)
        if row.delivery_status != DELIVERY_PUBLISHING or row.attempts != claim_attempt:
            raise DomainError(
                ERROR_OUTBOX_CLAIM,
                "this claim is no longer the current lease of the event",
                details={
                    "event_id": event_id,
                    "claim_attempt": claim_attempt,
                    "stored_attempts": row.attempts,
                    "delivery_status": row.delivery_status,
                },
            )
        return row

    def _state_of(self, row: _Row) -> OutboxDeliveryState:
        return OutboxDeliveryState(
            event_id=row.event.event_id,
            run_id=row.event.run_id,
            sequence=row.event.sequence,
            delivery_status=row.delivery_status,
            attempts=row.attempts,
            available_at=_to_iso(row.available_at),
            published_at=_to_iso(row.published_at) if row.published_at is not None else None,
            last_error_code=row.last_error_code,
        )


@dataclass(frozen=True)
class RecordedSend:
    """One recorded transport call: what an external system would have received."""

    idempotency_key: str
    event_id: str
    run_id: str
    sequence: int
    sent_at: str


class RecordingEventTransport:
    """Records sends in memory; performs no network, filesystem or process I/O.

    A test can script the next outcomes to exercise the failure paths. The recorded
    list is the evidence that ``event_id`` is used as the idempotency key, and it is
    **not** evidence that any broker received anything.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utc_now
        self.sent: list[RecordedSend] = []
        self._scripted: list[BaseException] = []

    def fail_next(self, error_code: str, *, retryable: bool = True, times: int = 1) -> None:
        """Queue ``times`` classified :class:`TransportError` failures."""
        require_positive_int(times, "times")
        self._scripted.extend(TransportError(error_code, retryable=retryable) for _ in range(times))

    def raise_next(self, exception: BaseException, *, times: int = 1) -> None:
        """Queue ``times`` raw exceptions, to prove unknown failures are sanitised."""
        require_positive_int(times, "times")
        self._scripted.extend(exception for _ in range(times))

    def send(self, event: DomainEvent, *, idempotency_key: str) -> None:
        if self._scripted:
            raise self._scripted.pop(0)
        self.sent.append(
            RecordedSend(
                idempotency_key=idempotency_key,
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=event.sequence,
                sent_at=_to_iso(self._clock()),
            )
        )

    @property
    def idempotency_keys(self) -> list[str]:
        return [record.idempotency_key for record in self.sent]

    @property
    def event_ids(self) -> list[str]:
        return [record.event_id for record in self.sent]


__all__ = [
    "MemoryOutboxDeliveryRepository",
    "RecordedSend",
    "RecordingEventTransport",
]
