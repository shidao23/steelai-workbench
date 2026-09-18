"""PostgreSQL transactional-outbox delivery adapter (T83).

Implements :class:`~steelai.enterprise_lab.ports.outbox.OutboxDeliveryRepository` on the
**existing** ``outbox_events`` table: the five dispatcher columns (``delivery_status``,
``attempts``, ``available_at``, ``published_at``, ``last_error_code``) were created by the
frozen T81 baseline, so T83 adds no column, no index and no migration.

Every method is one short unit of work on its own connection from the injected Engine:

- the claim takes a row lock with ``SELECT ... FOR UPDATE SKIP LOCKED``, flips the row to
  ``publishing``, increments ``attempts`` and stamps ``available_at`` from the **database**
  clock, then commits and returns the connection to the pool;
- an acknowledgement only touches a row that is still ``publishing`` with exactly the
  ``attempts`` value of the claim, which makes ``attempts`` a fencing token: a worker whose
  lease expired can never overwrite the outcome of the worker that took over;
- expired leases are recovered with the same lock-then-update shape.

Delivery is at-least-once. A row whose transport send succeeded but whose acknowledgement
failed stays ``publishing`` and is delivered again after the lease expires; consumers must
deduplicate on ``event_id``. There is no dispatcher daemon, no scheduler and no exactly-once
claim here.

The schema and the migration baseline are frozen T81 artifacts: this module reads and
writes them, and never alters them.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from ...domain.models import DomainError
from ...ports.outbox import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_PUBLISHED,
    DELIVERY_PUBLISHING,
    ERROR_OUTBOX_CLAIM,
    ERROR_OUTBOX_LEASE_EXPIRED,
    OutboxClaim,
    OutboxDeliveryState,
    OutboxReclaim,
    require_positive_int,
    require_safe_error_code,
)
from ._context import PostgreSQLContext
from .config import POSTGRESQL_SCHEMA
from .errors import map_database_error
from .hydration import hydrate_domain_event, to_iso8601

T = TypeVar("T")

#: Claim predicate. ``sequence = min(non-published sequence of the run)`` is what makes a
#: run strictly ordered: a later event can never be claimed while an earlier event of the
#: same run is pending, publishing, backing off or terminally failed.
_SELECT_CLAIMABLE_SQL = text(
    f"""
    SELECT o.event_id, o.attempts
    FROM {POSTGRESQL_SCHEMA}.outbox_events AS o
    WHERE o.delivery_status = :pending
      AND o.available_at <= now()
      AND o.attempts < :max_attempts
      AND o.sequence = (
          SELECT min(e.sequence)
          FROM {POSTGRESQL_SCHEMA}.outbox_events AS e
          WHERE e.run_id = o.run_id
            AND e.delivery_status <> :published
      )
    ORDER BY o.run_id, o.sequence
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
    """
)

_CLAIM_ONE_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.outbox_events
    SET delivery_status = :publishing,
        attempts = attempts + 1,
        available_at = now() + make_interval(secs => :lease_seconds),
        published_at = NULL
    WHERE event_id = :event_id
      AND delivery_status = :pending
      AND attempts = :seen_attempts
    RETURNING *
    """
)

_MARK_PUBLISHED_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.outbox_events
    SET delivery_status = :published,
        published_at = now(),
        last_error_code = NULL
    WHERE event_id = :event_id
      AND delivery_status = :publishing
      AND attempts = :claim_attempt
    RETURNING *
    """
)

_MARK_RETRY_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.outbox_events
    SET delivery_status = :target_status,
        available_at = now() + make_interval(secs => :retry_delay_seconds),
        last_error_code = :error_code
    WHERE event_id = :event_id
      AND delivery_status = :publishing
      AND attempts = :claim_attempt
    RETURNING *
    """
)

_MARK_TERMINAL_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.outbox_events
    SET delivery_status = :target_status,
        last_error_code = :error_code
    WHERE event_id = :event_id
      AND delivery_status = :publishing
      AND attempts = :claim_attempt
    RETURNING *
    """
)

_SELECT_EXPIRED_SQL = text(
    f"""
    SELECT event_id, attempts
    FROM {POSTGRESQL_SCHEMA}.outbox_events
    WHERE delivery_status = :publishing
      AND available_at <= now()
    ORDER BY available_at, run_id, sequence
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
    """
)

_RECLAIM_REQUEUE_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.outbox_events
    SET delivery_status = :target_status,
        available_at = now() + make_interval(secs => :retry_delay_seconds),
        last_error_code = :error_code
    WHERE event_id = :event_id
      AND delivery_status = :publishing
      AND attempts = :seen_attempts
    RETURNING *
    """
)

_RECLAIM_TERMINAL_SQL = text(
    f"""
    UPDATE {POSTGRESQL_SCHEMA}.outbox_events
    SET delivery_status = :target_status,
        last_error_code = :error_code
    WHERE event_id = :event_id
      AND delivery_status = :publishing
      AND attempts = :seen_attempts
    RETURNING *
    """
)


def _state_from_row(row: Mapping[str, Any]) -> OutboxDeliveryState:
    return OutboxDeliveryState(
        event_id=row["event_id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        delivery_status=row["delivery_status"],
        attempts=row["attempts"],
        available_at=to_iso8601(row["available_at"]),
        published_at=to_iso8601(row["published_at"]) if row["published_at"] is not None else None,
        last_error_code=row["last_error_code"],
    )


def _claim_from_row(row: Mapping[str, Any]) -> OutboxClaim:
    return OutboxClaim(
        event=hydrate_domain_event(row),
        claim_attempt=row["attempts"],
        lease_deadline=to_iso8601(row["available_at"]),
    )


def _reclaim_from_row(row: Mapping[str, Any]) -> OutboxReclaim:
    return OutboxReclaim(
        event_id=row["event_id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        attempts=row["attempts"],
        delivery_status=row["delivery_status"],
        available_at=to_iso8601(row["available_at"]),
        last_error_code=row["last_error_code"],
    )


class PostgreSQLOutboxDeliveryRepository:
    """Delivery-state repository over the frozen ``outbox_events`` table.

    The Engine is always injected; this adapter never reads ``.env`` and never creates a
    global engine. Each call opens one short transaction and releases it before returning,
    so a dispatcher can call a transport between two calls without holding a connection.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    # -- delivery contract -----------------------------------------------------
    def claim_batch(self, *, limit: int, lease_seconds: int, max_attempts: int) -> Sequence[OutboxClaim]:
        require_positive_int(limit, "limit")
        require_positive_int(lease_seconds, "lease_seconds")
        require_positive_int(max_attempts, "max_attempts")

        def action(connection: Connection) -> tuple[OutboxClaim, ...]:
            candidates = (
                connection.execute(
                    _SELECT_CLAIMABLE_SQL,
                    {
                        "pending": DELIVERY_PENDING,
                        "published": DELIVERY_PUBLISHED,
                        "max_attempts": max_attempts,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
            claims: list[OutboxClaim] = []
            for candidate in candidates:
                # Guarded by the fencing column: only the attempt we just read may be
                # claimed, even though this transaction already holds the row lock.
                stored = (
                    connection.execute(
                        _CLAIM_ONE_SQL,
                        {
                            "pending": DELIVERY_PENDING,
                            "publishing": DELIVERY_PUBLISHING,
                            "lease_seconds": lease_seconds,
                            "event_id": candidate["event_id"],
                            "seen_attempts": candidate["attempts"],
                        },
                    )
                    .mappings()
                    .first()
                )
                if stored is None:  # pragma: no cover - the row is locked by this transaction
                    raise DomainError(
                        ERROR_OUTBOX_CLAIM,
                        "the claimed row changed while it was locked",
                        details={"event_id": candidate["event_id"]},
                    )
                claims.append(_claim_from_row(stored))
            return tuple(claims)

        return self._short_transaction(action)

    def mark_published(self, event_id: str, claim_attempt: int) -> OutboxDeliveryState:
        require_positive_int(claim_attempt, "claim_attempt")

        def action(connection: Connection) -> OutboxDeliveryState:
            stored = (
                connection.execute(
                    _MARK_PUBLISHED_SQL,
                    {
                        "published": DELIVERY_PUBLISHED,
                        "publishing": DELIVERY_PUBLISHING,
                        "event_id": event_id,
                        "claim_attempt": claim_attempt,
                    },
                )
                .mappings()
                .first()
            )
            if stored is None:
                raise DomainError(
                    ERROR_OUTBOX_CLAIM,
                    "this claim is no longer the current lease of the event",
                    details={"event_id": event_id, "claim_attempt": claim_attempt},
                )
            return _state_from_row(stored)

        return self._short_transaction(action)

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

        def action(connection: Connection) -> OutboxDeliveryState:
            parameters = {
                "publishing": DELIVERY_PUBLISHING,
                "target_status": DELIVERY_PENDING if retryable else DELIVERY_FAILED,
                "retry_delay_seconds": retry_delay_seconds,
                "error_code": safe_code,
                "event_id": event_id,
                "claim_attempt": claim_attempt,
            }
            statement = _MARK_RETRY_SQL if retryable else _MARK_TERMINAL_SQL
            stored = connection.execute(statement, parameters).mappings().first()
            if stored is None:
                raise DomainError(
                    ERROR_OUTBOX_CLAIM,
                    "this claim is no longer the current lease of the event",
                    details={"event_id": event_id, "claim_attempt": claim_attempt},
                )
            return _state_from_row(stored)

        return self._short_transaction(action)

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

        def action(connection: Connection) -> tuple[OutboxReclaim, ...]:
            expired = (
                connection.execute(
                    _SELECT_EXPIRED_SQL,
                    {"publishing": DELIVERY_PUBLISHING, "limit": limit},
                )
                .mappings()
                .all()
            )
            reclaimed: list[OutboxReclaim] = []
            for row in expired:
                requeue = row["attempts"] < max_attempts
                parameters = {
                    "publishing": DELIVERY_PUBLISHING,
                    "target_status": DELIVERY_PENDING if requeue else DELIVERY_FAILED,
                    "retry_delay_seconds": retry_delay_seconds,
                    "error_code": ERROR_OUTBOX_LEASE_EXPIRED,
                    "event_id": row["event_id"],
                    "seen_attempts": row["attempts"],
                }
                statement = _RECLAIM_REQUEUE_SQL if requeue else _RECLAIM_TERMINAL_SQL
                stored = connection.execute(statement, parameters).mappings().first()
                if stored is None:  # pragma: no cover - the row is locked by this transaction
                    raise DomainError(
                        ERROR_OUTBOX_CLAIM,
                        "the expired row changed while it was locked",
                        details={"event_id": row["event_id"]},
                    )
                reclaimed.append(_reclaim_from_row(stored))
            return tuple(reclaimed)

        return self._short_transaction(action)

    # -- short transaction -----------------------------------------------------
    def _short_transaction(self, action: Callable[[Connection], T]) -> T:
        """Run ``action`` in one committed unit of work and release the connection.

        The boundary is deliberately not the five-repository unit of work: a dispatcher
        needs a *short* claim or acknowledge transaction, and no repository handle may
        outlive it. Failures are rolled back without ever masking the original error and
        database errors keep the T82 SQLSTATE mapping.
        """
        context = PostgreSQLContext(self._engine)
        context.start()
        try:
            result = action(context.connection)
        except DomainError:
            context.close_without_result()
            raise
        except Exception as exc:  # noqa: BLE001 - classify by SQLSTATE, never by text
            context.close_without_result()
            raise map_database_error(exc) from None
        context.commit()
        return result


__all__ = ["PostgreSQLOutboxDeliveryRepository"]
