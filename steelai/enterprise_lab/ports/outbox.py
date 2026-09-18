"""Transactional-outbox delivery port (T83).

This port is deliberately **separate** from :class:`~steelai.enterprise_lab.ports.events.EventPublisher`:
delivery state (``delivery_status``, ``attempts``, ``available_at``, ``published_at``,
``last_error_code``) is dispatcher infrastructure. It never enters ``DomainEvent`` and it
never changes the T80 publish contract.

Delivery semantics are **at-least-once**, never exactly-once:

- a claim sets ``pending`` -> ``publishing``, increments ``attempts`` and stamps a lease
  deadline in ``available_at`` using the *database* clock;
- ``attempts`` is the fencing token: an acknowledge or negative-acknowledge is only
  accepted while the row is still ``publishing`` with the same ``attempts`` value, so a
  worker whose lease expired can never overwrite the new worker's outcome;
- if a transport send succeeds but the acknowledge fails, the row stays ``publishing``
  and is re-sent after the lease expires, so a consumer must deduplicate on ``event_id``.

Per-run ordering is part of the claim contract: only the smallest sequence that is not
yet ``published`` for a run may be claimed. A ``failed`` earlier event blocks the rest of
its run; T83 provides no skip and no manual unlock.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from ..domain.models import DomainError, DomainEvent, validate_timestamp

#: Delivery states of one outbox row. Frozen vocabulary, identical to the T81 CHECK
#: constraint on ``outbox_events.delivery_status``.
DELIVERY_PENDING = "pending"
DELIVERY_PUBLISHING = "publishing"
DELIVERY_PUBLISHED = "published"
DELIVERY_FAILED = "failed"

DELIVERY_STATUSES = (DELIVERY_PENDING, DELIVERY_PUBLISHING, DELIVERY_PUBLISHED, DELIVERY_FAILED)

#: Stable, redaction-safe error codes of the delivery boundary. They are part of the
#: persisted ``last_error_code`` vocabulary, so they must never carry free text.
ERROR_OUTBOX_CLAIM = "ENT-OUTBOX-CLAIM-001"
ERROR_OUTBOX_TRANSPORT = "ENT-OUTBOX-TRANSPORT-001"
ERROR_OUTBOX_CONFIG = "ENT-OUTBOX-CONFIG-001"
ERROR_OUTBOX_LEASE_EXPIRED = "ENT-OUTBOX-LEASE-EXPIRED"

#: A persisted error code is a short identifier, never a message, URL, host or payload.
SAFE_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def is_safe_error_code(value: object) -> bool:
    """True when ``value`` may be persisted as ``last_error_code``."""
    return isinstance(value, str) and bool(SAFE_ERROR_CODE_PATTERN.fullmatch(value))


def require_safe_error_code(value: object, field_name: str = "error_code") -> str:
    """Fail closed with ``ENT-OUTBOX-CONFIG-001`` on any unsafe error code."""
    if not is_safe_error_code(value):
        raise DomainError(
            ERROR_OUTBOX_CONFIG,
            f"{field_name} must be a safe error code without text, URL, host or credentials",
        )
    return str(value)


def require_positive_int(value: object, field_name: str) -> int:
    """Fail closed with ``ENT-OUTBOX-CONFIG-001`` on a non-positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DomainError(
            ERROR_OUTBOX_CONFIG,
            f"{field_name} must be a positive integer",
            details={"field": field_name},
        )
    return value


def require_non_negative_int(value: object, field_name: str) -> int:
    """Fail closed with ``ENT-OUTBOX-CONFIG-001`` on a negative or non-integer counter.

    ``attempts`` is ``0`` on a freshly written ``pending`` row and becomes positive on the
    first claim, so a stored delivery state legitimately carries ``0``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DomainError(
            ERROR_OUTBOX_CONFIG,
            f"{field_name} must be a non-negative integer",
            details={"field": field_name},
        )
    return value


def require_aware_timestamp(value: object, field_name: str) -> str:
    """Fail closed with ``ENT-OUTBOX-CONFIG-001`` on a timestamp without a timezone.

    Lease deadlines and delivery timestamps are database-clock values, so a naive or
    unparsable timestamp is a contract violation rather than a harmless detail.
    """
    try:
        validate_timestamp(str(value), field_name)
    except DomainError:
        raise DomainError(
            ERROR_OUTBOX_CONFIG,
            f"{field_name} must be an ISO-8601 timestamp with a timezone",
            details={"field": field_name},
        ) from None
    return str(value)


def require_declared_status(value: object, field_name: str = "delivery_status") -> str:
    """Fail closed with ``ENT-OUTBOX-CONFIG-001`` on an undeclared delivery state."""
    if not isinstance(value, str) or value not in DELIVERY_STATUSES:
        raise DomainError(
            ERROR_OUTBOX_CONFIG,
            f"{field_name} must be one of the declared delivery states",
            details={"field": field_name, "declared": list(DELIVERY_STATUSES)},
        )
    return value


@dataclass(frozen=True)
class OutboxClaim:
    """One outbox row leased by a dispatcher, with its fencing token.

    ``claim_attempt`` is the value of ``attempts`` after the claim increment. Every
    acknowledge or negative-acknowledge must present it again.

    A claim only exists for a row that is currently ``publishing``: a ``pending``,
    ``published`` or ``failed`` row can never be handed to a dispatcher, and a naive or
    missing ``lease_deadline`` is refused, because the lease is a database-clock value.
    """

    event: DomainEvent
    claim_attempt: int
    lease_deadline: str
    delivery_status: str = DELIVERY_PUBLISHING

    def __post_init__(self) -> None:
        if not isinstance(self.event, DomainEvent):
            raise DomainError(ERROR_OUTBOX_CONFIG, "claim.event must be a DomainEvent")
        require_positive_int(self.claim_attempt, "claim_attempt")
        require_aware_timestamp(self.lease_deadline, "lease_deadline")
        if self.delivery_status != DELIVERY_PUBLISHING:
            raise DomainError(
                ERROR_OUTBOX_CONFIG,
                "a claim must describe a publishing row",
                details={"delivery_status": self.delivery_status},
            )

    @property
    def event_id(self) -> str:
        return self.event.event_id

    @property
    def run_id(self) -> str:
        return self.event.run_id

    @property
    def sequence(self) -> int:
        return self.event.sequence

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "claim_attempt": self.claim_attempt,
            "lease_deadline": self.lease_deadline,
            "delivery_status": self.delivery_status,
        }


@dataclass(frozen=True)
class OutboxDeliveryState:
    """The persisted delivery state of one outbox row after an acknowledged change."""

    event_id: str
    run_id: str
    sequence: int
    delivery_status: str
    attempts: int
    available_at: str
    published_at: str | None = None
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        require_declared_status(self.delivery_status)
        require_non_negative_int(self.attempts, "attempts")
        require_aware_timestamp(self.available_at, "available_at")
        if self.published_at is not None:
            require_aware_timestamp(self.published_at, "published_at")
        if self.last_error_code is not None:
            require_safe_error_code(self.last_error_code, "last_error_code")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "delivery_status": self.delivery_status,
            "attempts": self.attempts,
            "available_at": self.available_at,
            "published_at": self.published_at,
            "last_error_code": self.last_error_code,
        }


@dataclass(frozen=True)
class OutboxReclaim:
    """One expired ``publishing`` lease that was returned to the queue or failed.

    ``attempts`` keeps the attempt count of the expired lease (it is never reset by
    recovery) and ``last_error_code`` is the fixed lease-recovery code.
    """

    event_id: str
    run_id: str
    sequence: int
    attempts: int
    delivery_status: str
    available_at: str
    last_error_code: str

    def __post_init__(self) -> None:
        if self.delivery_status not in (DELIVERY_PENDING, DELIVERY_FAILED):
            raise DomainError(
                ERROR_OUTBOX_CONFIG,
                "a reclaimed row must become pending or failed",
                details={"delivery_status": self.delivery_status},
            )
        require_positive_int(self.attempts, "attempts")
        require_safe_error_code(self.last_error_code, "last_error_code")
        require_aware_timestamp(self.available_at, "available_at")

    @property
    def requeued(self) -> bool:
        return self.delivery_status == DELIVERY_PENDING

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "attempts": self.attempts,
            "delivery_status": self.delivery_status,
            "available_at": self.available_at,
            "last_error_code": self.last_error_code,
        }


@runtime_checkable
class OutboxDeliveryRepository(Protocol):
    """Persistence boundary of the delivery loop: claim, acknowledge, recover.

    Every method is one short unit of work that commits before it returns. A
    dispatcher must never call a transport while one of these calls is in flight.
    """

    def claim_batch(
        self,
        *,
        limit: int,
        lease_seconds: int,
        max_attempts: int,
    ) -> Sequence[OutboxClaim]:
        """Lease up to ``limit`` deliverable rows, or return an empty sequence at once."""
        ...

    def mark_published(self, event_id: str, claim_attempt: int) -> OutboxDeliveryState:
        """``publishing`` -> ``published`` for the current ``claim_attempt`` only."""
        ...

    def mark_failed(
        self,
        event_id: str,
        claim_attempt: int,
        error_code: str,
        *,
        retry_delay_seconds: int,
        retryable: bool,
    ) -> OutboxDeliveryState:
        """``publishing`` -> ``pending`` (retryable) or ``failed`` (terminal)."""
        ...

    def reclaim_expired(
        self,
        *,
        limit: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> Sequence[OutboxReclaim]:
        """Recover expired leases: ``pending`` while attempts remain, else ``failed``."""
        ...


@runtime_checkable
class EventTransport(Protocol):
    """Where a claimed event is actually sent. No implementation is wired by default."""

    def send(self, event: DomainEvent, *, idempotency_key: str) -> None:
        """Send one event; raise :class:`TransportError` on a classified failure."""
        ...


class TransportError(Exception):
    """A transport failure carrying only safe structured fields.

    The exception message is the safe error code itself: no driver text, URL, host,
    credential or payload can travel through this type into the outbox table.
    """

    def __init__(self, error_code: str, *, retryable: bool) -> None:
        safe_code = require_safe_error_code(error_code)
        super().__init__(safe_code)
        self.error_code = safe_code
        self.retryable = bool(retryable)


__all__ = [
    "DELIVERY_FAILED",
    "DELIVERY_PENDING",
    "DELIVERY_PUBLISHED",
    "DELIVERY_PUBLISHING",
    "DELIVERY_STATUSES",
    "ERROR_OUTBOX_CLAIM",
    "ERROR_OUTBOX_CONFIG",
    "ERROR_OUTBOX_LEASE_EXPIRED",
    "ERROR_OUTBOX_TRANSPORT",
    "EventTransport",
    "OutboxClaim",
    "OutboxDeliveryRepository",
    "OutboxDeliveryState",
    "OutboxReclaim",
    "SAFE_ERROR_CODE_PATTERN",
    "TransportError",
    "is_safe_error_code",
    "require_aware_timestamp",
    "require_declared_status",
    "require_non_negative_int",
    "require_positive_int",
    "require_safe_error_code",
]
