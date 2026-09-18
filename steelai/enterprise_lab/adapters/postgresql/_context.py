"""Shared PostgreSQL transaction context for the Enterprise Lab adapter (T82).

One unit of work owns exactly one :class:`sqlalchemy.Connection` and one
``Transaction``; every repository in that unit of work shares them, so a run, its
artifacts, its audit records, its outbox rows and its job rows are written in the
same database transaction.

No global engine, connection or session exists, nothing connects at import time
and nothing here reads ``.env`` or a default connection string.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from steelai.enterprise_lab.domain.models import ERROR_STORE_NOT_ACTIVE, DomainError

from .errors import ERROR_DATABASE, map_database_error


class PostgreSQLContext:
    """The single connection/transaction pair of one PostgreSQL unit of work.

    Lifecycle:

    1. ``__init__`` only stores the engine; no connection is opened.
    2. ``start()`` checks out a connection and begins a transaction (lazy).
    3. repository calls use :attr:`connection` through :meth:`connection_for_call`,
       which also re-checks that this unit of work is still the live one.
    4. ``commit()`` or ``rollback()`` closes the transaction and returns the
       connection to the pool; after either, every call raises
       ``ENT-UOW-001`` until the unit of work is closed.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Connection | None = None
        self._transaction: Any = None
        self._started = False
        self._closed = False
        self._committed = False
        self._rolled_back = False

    # -- state -----------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._started and not self._closed

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def rolled_back(self) -> bool:
        return self._rolled_back

    @property
    def connection(self) -> Connection:
        """The transaction's connection; fails closed once the boundary closed."""
        self.require_open("use the connection")
        assert self._connection is not None
        return self._connection

    def require_open(self, action: str) -> None:
        if self._closed:
            raise DomainError(
                ERROR_STORE_NOT_ACTIVE,
                f"this unit of work is already closed; cannot {action}",
            )

    def require_started(self, action: str) -> None:
        """Commit and rollback require a boundary that actually started.

        Calling either before entering the ``with`` block - or after the boundary
        already closed - fails closed with ``ENT-UOW-001``.
        """
        if not self._started or self._closed:
            raise DomainError(
                ERROR_STORE_NOT_ACTIVE,
                f"this unit of work has no open transaction; cannot {action}",
            )

    def require_active(self, action: str) -> None:
        """Fails closed unless this context is the live, started transaction.

        A repository handle is unusable before the boundary starts, after a commit
        and after a rollback - in every case with the same stable code.
        """
        if self._closed or not self._started:
            raise DomainError(
                ERROR_STORE_NOT_ACTIVE,
                f"this repository is no longer bound to an open unit of work; cannot {action}",
            )

    def connection_for_call(self, action: str) -> Connection:
        self.require_active(action)
        assert self._connection is not None
        return self._connection

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Check out a connection and begin the transaction.

        If ``connect()`` succeeds but ``begin()`` fails, the connection is closed
        immediately so a failed start never leaks a pooled connection.
        """
        if self._started:
            return
        try:
            self._connection = self._engine.connect()
        except Exception as exc:  # noqa: BLE001 - the driver decides the type
            self._started = True
            self._closed = True
            raise DomainError(
                ERROR_DATABASE,
                "could not open a database connection",
                details={"error_type": type(exc).__name__},
            ) from None
        try:
            self._transaction = self._connection.begin()
        except Exception as exc:  # noqa: BLE001
            self._started = True
            self._closed = True
            self._release()
            raise DomainError(
                ERROR_DATABASE,
                "could not open a database transaction",
                details={"error_type": type(exc).__name__},
            ) from None
        self._started = True

    def commit(self) -> None:
        """Commit the transaction; a failure rolls back and closes the boundary.

        A commit that the database refused must never leave the boundary looking
        usable: the transaction is rolled back, the connection is closed, the context
        is marked closed and only the sanitised ``ENT-DB-001`` reaches the caller.
        """
        self.require_started("commit")
        try:
            self._commit_transaction()
        except DomainError:
            # Roll back first: if that also fails it must not mask the commit error,
            # but the connection is closed either way.
            self._rolled_back = self._rollback_transaction()
            self._closed = True
            self._committed = False
            self._release()
            raise
        self._committed = True
        self._closed = True
        self._release()

    def rollback(self) -> None:
        """Roll back the transaction; a failure closes the boundary and is reported.

        An explicit rollback that the driver refuses is **not** a silent success:
        ``rolled_back`` stays ``False``, the connection is closed, the boundary is
        closed and the caller receives only a sanitised ``ENT-DB-001``.
        """
        self.require_started("rollback")
        rolled_back = self._rollback_transaction()
        self._rolled_back = rolled_back
        self._closed = True
        self._release()
        if not rolled_back:
            raise DomainError(
                ERROR_DATABASE,
                "the database refused to roll back this transaction",
            )

    def close_without_result(self) -> bool:
        """Release the transaction by rolling it back; report a failed rollback.

        Leaving the boundary without an explicit ``commit`` or ``rollback`` always
        rolls back, so a raised exception can never leave a partial write behind.
        ``rolled_back`` then reports the real outcome: the transaction was rolled
        back, whether that was stated or merely implied by abandoning the block.

        Returns ``False`` when the automatic rollback failed, so the boundary can
        decide: inside ``__exit__`` that failure must not mask an exception that is
        already propagating, but on a clean exit it must be reported instead of
        silently succeeding.
        """
        if not self._started or self._closed:
            return True
        self._rolled_back = self._rollback_transaction()
        self._closed = True
        self._release()
        return self._rolled_back

    def _commit_transaction(self) -> None:
        transaction = self._transaction
        if transaction is None:
            return
        try:
            transaction.commit()
        except Exception as exc:  # noqa: BLE001
            # The transaction reference is kept so the failure path can still try to
            # roll the transaction back before the connection is released.
            raise DomainError(
                ERROR_DATABASE,
                "the database refused to commit this transaction",
                details={"error_type": type(exc).__name__},
            ) from None
        self._transaction = None

    def _rollback_transaction(self) -> bool:
        """Roll the transaction back; report whether the rollback actually happened.

        A failing rollback is swallowed so it can never mask the error that caused it
        (a failed commit, or the exception that aborted the ``with`` block); the
        connection is closed by the caller in every case.
        """
        transaction = self._transaction
        self._transaction = None
        if transaction is None:
            return True
        try:
            transaction.rollback()
        except Exception:  # noqa: BLE001 - rollback must never mask the real error
            return False
        return True

    def _release(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - a closing failure must not mask results
            pass
    # -- locks -----------------------------------------------------------------
    def acquire_advisory_lock(self, key: int) -> None:
        """Take a transaction-level PostgreSQL advisory lock.

        The lock is released automatically when the transaction ends. Callers pass
        a key produced by this module's key helpers, which are stable SHA-256 derived
        integers rather than Python ``hash()`` values.

        A driver failure is classified with the same SQLSTATE/constraint mapping as
        every other database error, so the caller only ever sees a sanitised
        ``ENT-DB-*`` code - never the statement, its parameters or the driver text.
        """
        connection = self.connection_for_call("acquire an advisory lock")
        try:
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001 - classify by SQLSTATE, never by text
            raise map_database_error(exc) from None


__all__ = ["PostgreSQLContext"]
