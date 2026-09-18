"""Finite outbox dispatcher (T83).

One call does a bounded amount of work and returns: there is no daemon, no timer, no
long-running process and no scheduler. The caller decides when to call
:meth:`OutboxDispatcher.dispatch_batch` and :meth:`OutboxDispatcher.reclaim_expired`.

The transaction discipline is the core of the design:

1. claim in one **short** unit of work and commit it (the lease is now durable and the
   connection is back in the pool);
2. send every claimed event **outside** any database transaction;
3. acknowledge or negative-acknowledge each event in its **own** short unit of work.

Delivery is **at-least-once**. When the send succeeded but the acknowledgement failed,
the row stays ``publishing`` and is delivered again after the lease expires, so a
consumer must treat ``event_id`` as its idempotency key. T83 never claims exactly-once
delivery.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import DomainError
from ..ports.outbox import (
    DELIVERY_PENDING,
    ERROR_OUTBOX_CLAIM,
    ERROR_OUTBOX_CONFIG,
    ERROR_OUTBOX_TRANSPORT,
    EventTransport,
    OutboxClaim,
    OutboxDeliveryRepository,
    OutboxReclaim,
    TransportError,
    is_safe_error_code,
    require_aware_timestamp,
    require_positive_int,
    require_safe_error_code,
)

#: Outcomes reported by one bounded dispatch call.
STATUS_PUBLISHED = "published"
STATUS_RETRY_SCHEDULED = "retry_scheduled"
STATUS_FAILED = "failed_terminal"
#: The transport returned successfully, but the acknowledge did not commit: the event was
#: really sent at least once and the persisted state is unknown.
STATUS_SENT_UNACKNOWLEDGED = "sent_unacknowledged"
#: The transport failed **and** the failure could not be persisted: the event was not
#: delivered and the persisted state is unknown.
STATUS_FAILURE_UNRECORDED = "failure_unrecorded"

#: ``status -> (delivered, persistence_state_known, redelivery_possible)``.
#:
#: The three properties are derived from the status only, so a caller can never assemble a
#: contradictory combination (for example "delivered" together with an unsent event).
OUTCOME_PROPERTIES: dict[str, tuple[bool, bool, bool]] = {
    STATUS_PUBLISHED: (True, True, False),
    STATUS_RETRY_SCHEDULED: (False, True, True),
    STATUS_FAILED: (False, True, False),
    STATUS_SENT_UNACKNOWLEDGED: (True, False, True),
    STATUS_FAILURE_UNRECORDED: (False, False, True),
}

OUTCOME_STATUSES = tuple(OUTCOME_PROPERTIES)


@dataclass(frozen=True)
class OutboxDispatcherConfig:
    """Bounded, validated dispatcher configuration.

    ``retry_backoff_seconds`` is the delay of the first retry and doubles with every
    attempt, capped by ``retry_backoff_cap_seconds``.
    """

    lease_seconds: int = 30
    max_attempts: int = 3
    retry_backoff_seconds: int = 5
    retry_backoff_cap_seconds: int = 300
    batch_limit: int = 10

    def __post_init__(self) -> None:
        require_positive_int(self.lease_seconds, "lease_seconds")
        require_positive_int(self.max_attempts, "max_attempts")
        require_positive_int(self.retry_backoff_seconds, "retry_backoff_seconds")
        require_positive_int(self.retry_backoff_cap_seconds, "retry_backoff_cap_seconds")
        require_positive_int(self.batch_limit, "batch_limit")
        if self.retry_backoff_cap_seconds < self.retry_backoff_seconds:
            raise DomainError(
                ERROR_OUTBOX_CONFIG,
                "retry_backoff_cap_seconds must not be smaller than retry_backoff_seconds",
            )

    def backoff_seconds(self, attempt: int) -> int:
        """Exponential backoff for a claim attempt, capped by the configured maximum."""
        require_positive_int(attempt, "attempt")
        delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
        return min(delay, self.retry_backoff_cap_seconds)


@dataclass(frozen=True)
class OutboxDispatchOutcome:
    """What happened to one claimed event in this call.

    Only ``status`` is passed in; the three properties are derived from it, so the caller
    cannot report a contradiction. The two "unknown" statuses are deliberately distinct:

    - ``sent_unacknowledged``: the transport returned successfully, so the event was really
      sent at least once, but the acknowledge did not commit and the persisted state is
      unknown. ``delivered`` is ``True``.
    - ``failure_unrecorded``: the transport failed **and** the failure could not be
      persisted, so the event was **not** sent and the persisted state is unknown.
      ``delivered`` is ``False``, and reporting it as delivered would be a false claim.

    Both unknown states may be taken over later by another worker (``redelivery_possible``),
    which is exactly why neither is reported as a completed delivery.
    """

    event_id: str
    run_id: str
    sequence: int
    claim_attempt: int
    status: str
    error_code: str | None = None
    available_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_PROPERTIES:
            raise DomainError(
                ERROR_OUTBOX_CONFIG,
                "unknown dispatch outcome status",
                details={"status": self.status, "declared": list(OUTCOME_STATUSES)},
            )
        if self.error_code is not None:
            require_safe_error_code(self.error_code, "error_code")
        if self.available_at is not None:
            require_aware_timestamp(self.available_at, "available_at")

    @property
    def delivered(self) -> bool:
        """True only when the transport itself returned successfully."""
        return OUTCOME_PROPERTIES[self.status][0]

    @property
    def persistence_state_known(self) -> bool:
        """True only when the persisted delivery state is known to have been written."""
        return OUTCOME_PROPERTIES[self.status][1]

    @property
    def redelivery_possible(self) -> bool:
        """True when the event may be sent again later (new attempt or lease recovery)."""
        return OUTCOME_PROPERTIES[self.status][2]

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "claim_attempt": self.claim_attempt,
            "status": self.status,
            "error_code": self.error_code,
            "available_at": self.available_at,
            "delivered": self.delivered,
            "persistence_state_known": self.persistence_state_known,
            "redelivery_possible": self.redelivery_possible,
        }


class OutboxDispatcher:
    """Claim, send, acknowledge and recover expired leases, in bounded batches."""

    def __init__(
        self,
        delivery: OutboxDeliveryRepository,
        transport: EventTransport,
        config: OutboxDispatcherConfig | None = None,
    ) -> None:
        self._delivery = delivery
        self._transport = transport
        self._config = config or OutboxDispatcherConfig()

    @property
    def config(self) -> OutboxDispatcherConfig:
        return self._config

    # -- public finite calls ---------------------------------------------------
    def dispatch_batch(self, limit: int | None = None) -> tuple[OutboxDispatchOutcome, ...]:
        """Lease a bounded batch, send it outside any transaction, then acknowledge.

        A transport failure never aborts the batch: every other claim is still
        acknowledged. A failed acknowledgement is reported as ``unacknowledged`` instead
        of raising, so the caller keeps the at-least-once recovery path.
        """
        batch_limit = self._require_limit(limit)
        # Step 1: the claim is its own committed unit of work. When it returns, the
        # lease is durable and this dispatcher holds no database connection.
        claims = tuple(
            self._delivery.claim_batch(
                limit=batch_limit,
                lease_seconds=self._config.lease_seconds,
                max_attempts=self._config.max_attempts,
            )
        )
        return tuple(self._deliver(claim) for claim in claims)

    def reclaim_expired(self, limit: int | None = None) -> tuple[OutboxReclaim, ...]:
        """Recover expired leases: requeue while attempts remain, else fail terminally.

        A recovered row is requeued after the first backoff step (not a per-row computed
        delay), which is enough to keep a dead worker's ghost from racing the new claim.
        """
        batch_limit = self._require_limit(limit)
        return tuple(
            self._delivery.reclaim_expired(
                limit=batch_limit,
                max_attempts=self._config.max_attempts,
                retry_delay_seconds=self._config.retry_backoff_seconds,
            )
        )

    # -- internals -------------------------------------------------------------
    def _require_limit(self, limit: int | None) -> int:
        if limit is None:
            return self._config.batch_limit
        return require_positive_int(limit, "limit")

    def _deliver(self, claim: OutboxClaim) -> OutboxDispatchOutcome:
        """Send one claim outside any transaction, then acknowledge it separately."""
        try:
            # ``event_id`` is the idempotency key: an at-least-once redelivery of the
            # same event must be recognisable by the downstream consumer.
            self._transport.send(claim.event, idempotency_key=claim.event.event_id)
        except TransportError as exc:
            return self._record_failure(claim, exc.error_code, retryable=exc.retryable)
        except DomainError:
            # A transport must not fail with a domain error: that is a programming or
            # configuration bug, and hiding it as a retry would make it unfixable.
            raise
        except Exception as exc:  # noqa: BLE001 - the transport decides its own types
            declared = getattr(exc, "error_code", None)
            retryable = bool(getattr(exc, "retryable", True))
            # Unknown transport exception: only a fixed safe code is ever persisted, and
            # the original text never reaches the database or the caller.
            code = declared if is_safe_error_code(declared) else ERROR_OUTBOX_TRANSPORT
            return self._record_failure(claim, str(code), retryable=retryable)
        # The send succeeded; the acknowledgement is its own short unit of work.
        try:
            self._delivery.mark_published(claim.event_id, claim.claim_attempt)
        except DomainError as exc:
            # The event really was sent, but the acknowledge did not commit (another
            # worker may have taken the claim over). Report "sent, state unknown" instead
            # of pretending it was published or that nothing was sent.
            return self._unknown_state(claim, STATUS_SENT_UNACKNOWLEDGED, exc.code or ERROR_OUTBOX_CLAIM)
        return OutboxDispatchOutcome(
            event_id=claim.event_id,
            run_id=claim.run_id,
            sequence=claim.sequence,
            claim_attempt=claim.claim_attempt,
            status=STATUS_PUBLISHED,
        )

    def _record_failure(
        self,
        claim: OutboxClaim,
        error_code: str,
        *,
        retryable: bool,
    ) -> OutboxDispatchOutcome:
        """Persist a safe failure: retry while attempts remain, else fail terminally.

        When the failure itself cannot be persisted the outcome is ``failure_unrecorded``:
        the event was **not** delivered and the persisted state is unknown, so it must
        never be reported as delivered.
        """
        may_retry = bool(retryable) and claim.claim_attempt < self._config.max_attempts
        delay = self._config.backoff_seconds(claim.claim_attempt) if may_retry else 0
        try:
            stored = self._delivery.mark_failed(
                claim.event_id,
                claim.claim_attempt,
                error_code,
                retry_delay_seconds=delay,
                retryable=may_retry,
            )
        except DomainError as exc:
            # The claim is gone (the lease was recovered by another worker) or the write
            # failed: fail closed and report the unknown persisted state.
            return self._unknown_state(claim, STATUS_FAILURE_UNRECORDED, exc.code or ERROR_OUTBOX_CLAIM)
        status = STATUS_RETRY_SCHEDULED if stored.delivery_status == DELIVERY_PENDING else STATUS_FAILED
        return OutboxDispatchOutcome(
            event_id=claim.event_id,
            run_id=claim.run_id,
            sequence=claim.sequence,
            claim_attempt=claim.claim_attempt,
            status=status,
            error_code=error_code,
            available_at=stored.available_at,
        )

    def _unknown_state(self, claim: OutboxClaim, status: str, error_code: str) -> OutboxDispatchOutcome:
        """Report an outcome whose persisted delivery state is not known."""
        return OutboxDispatchOutcome(
            event_id=claim.event_id,
            run_id=claim.run_id,
            sequence=claim.sequence,
            claim_attempt=claim.claim_attempt,
            status=status,
            error_code=error_code,
        )


__all__ = [
    "OUTCOME_PROPERTIES",
    "OUTCOME_STATUSES",
    "OutboxDispatchOutcome",
    "OutboxDispatcher",
    "OutboxDispatcherConfig",
    "STATUS_FAILED",
    "STATUS_FAILURE_UNRECORDED",
    "STATUS_PUBLISHED",
    "STATUS_RETRY_SCHEDULED",
    "STATUS_SENT_UNACKNOWLEDGED",
]
