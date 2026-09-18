"""Database error mapping for the PostgreSQL adapter (T82).

Every failure is classified from the SQLSTATE and the constraint name only. The
localised driver message, the SQL statement and its parameters are never parsed and
never surfaced, so no credential, connection string or experimental value can leak
through an exception.
"""
from __future__ import annotations

from typing import Any, Mapping

from steelai.enterprise_lab.domain.models import (
    ERROR_ARTIFACT_CONFLICT,
    ERROR_AUDIT_APPEND_ONLY,
    ERROR_EVENT_ORDER,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_JOB_TRANSITION,
    ERROR_REVISION_CONFLICT,
    ERROR_UNKNOWN_RUN,
    DomainError,
)

#: Adapter-owned codes. ``ENT-DB-*`` is reserved for database failures; the
#: ``ENT-DB-CONFIG-*`` family in :mod:`config` stays configuration-only.
ERROR_DATABASE = "ENT-DB-001"
ERROR_CHECK_CONSTRAINT = "ENT-DB-002"
ERROR_TRIGGER_REJECTED = "ENT-DB-003"
ERROR_SERIALIZATION = "ENT-DB-004"
ERROR_SCHEMA_MISSING = "ENT-DB-005"

# SQLSTATE classes/specific codes we classify.
SQLSTATE_UNIQUE_VIOLATION = "23505"
SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
SQLSTATE_CHECK_VIOLATION = "23514"
SQLSTATE_NOT_NULL_VIOLATION = "23502"
SQLSTATE_RESTRICT_VIOLATION = "23001"
SQLSTATE_SERIALIZATION_FAILURE = "40001"
SQLSTATE_DEADLOCK_DETECTED = "40P01"
#: Missing schema object: a real infrastructure problem, reported as such instead of
#: being collapsed into a generic write rejection.
SQLSTATE_UNDEFINED_TABLE = "42P01"
SQLSTATE_UNDEFINED_COLUMN = "42703"
SQLSTATE_INSUFFICIENT_PRIVILEGE = "42501"

#: Constraint name to stable governance error code.
CONSTRAINT_ERROR_CODES: Mapping[str, str] = {
    "uq_workflow_runs_idempotency_key": ERROR_IDEMPOTENCY_CONFLICT,
    "uq_background_jobs_idempotency_key": ERROR_IDEMPOTENCY_CONFLICT,
    "uq_artifact_references_relative_path": ERROR_ARTIFACT_CONFLICT,
    "uq_audit_events_sequence": ERROR_AUDIT_APPEND_ONLY,
    "uq_outbox_events_run_id_sequence": ERROR_EVENT_ORDER,
    "fk_artifact_references_run_id_workflow_runs": ERROR_UNKNOWN_RUN,
    "fk_audit_events_run_id_workflow_runs": ERROR_UNKNOWN_RUN,
    "fk_outbox_events_run_id_workflow_runs": ERROR_UNKNOWN_RUN,
    "fk_background_jobs_run_id_workflow_runs": ERROR_UNKNOWN_RUN,
    "ck_artifact_references_relative_path_posix": ERROR_ARTIFACT_CONFLICT,
    "ck_artifact_references_sha256_lowercase_hex": ERROR_ARTIFACT_CONFLICT,
    "ck_workflow_runs_revision_positive": ERROR_REVISION_CONFLICT,
    "ck_background_jobs_attempts_positive": ERROR_JOB_TRANSITION,
    "ck_background_jobs_max_attempts_positive": ERROR_JOB_TRANSITION,
    "ck_background_jobs_attempts_within_limit": ERROR_JOB_TRANSITION,
    "ck_background_jobs_state_declared": ERROR_JOB_TRANSITION,
    "ck_outbox_events_sequence_positive": ERROR_EVENT_ORDER,
    "ck_audit_events_sequence_positive": ERROR_AUDIT_APPEND_ONLY,
    "ck_audit_events_revision_positive": ERROR_AUDIT_APPEND_ONLY,
}

#: Messages are fixed English strings: no driver text, no SQL, no parameters.
CONSTRAINT_MESSAGES: Mapping[str, str] = {
    ERROR_IDEMPOTENCY_CONFLICT: "the database already binds this idempotency key to a different request",
    ERROR_ARTIFACT_CONFLICT: "the database already binds this artifact reference to different content",
    ERROR_AUDIT_APPEND_ONLY: "the database rejected this audit append",
    ERROR_EVENT_ORDER: "the database rejected this outbox event sequence",
    ERROR_UNKNOWN_RUN: "the referenced run does not exist",
    ERROR_REVISION_CONFLICT: "the stored revision does not accept this update",
    ERROR_JOB_TRANSITION: "the database rejected this background job state",
}


def sqlstate_of(exc: BaseException) -> str | None:
    """Extract the SQLSTATE without touching the message text."""
    for candidate in (getattr(exc, "orig", None), exc):
        if candidate is None:
            continue
        sqlstate = getattr(candidate, "sqlstate", None)
        if isinstance(sqlstate, str) and sqlstate:
            return sqlstate
        code = getattr(candidate, "pgcode", None)
        if isinstance(code, str) and code:
            return code
    return None


def constraint_name_of(exc: BaseException) -> str | None:
    """Extract the violated constraint name from structured diagnostics only."""
    diag = None
    for candidate in (getattr(exc, "orig", None), exc):
        if candidate is None:
            continue
        diag = getattr(candidate, "diag", None)
        if diag is not None:
            break
    if diag is None:
        return None
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) and name else None


def map_database_error(
    exc: BaseException,
    *,
    mutate_audit_error_code: str = ERROR_AUDIT_APPEND_ONLY,
) -> DomainError:
    """Translate a driver exception into a stable, sanitised governance error.

    ``mutate_audit_error_code`` lets the caller choose which audit code is used for
    a trigger rejection: a normal append keeps ``ENT-AUDIT-001`` semantics, while a
    direct UPDATE/DELETE attempt is reported as an adapter trigger rejection.
    """
    sqlstate = sqlstate_of(exc)
    constraint = constraint_name_of(exc)

    if sqlstate == SQLSTATE_RESTRICT_VIOLATION:
        return _error(
            mutate_audit_error_code,
            "the append-only database trigger rejected this mutation",
            sqlstate=sqlstate,
            constraint=constraint,
        )
    if sqlstate in (SQLSTATE_UNIQUE_VIOLATION, SQLSTATE_FOREIGN_KEY_VIOLATION, SQLSTATE_CHECK_VIOLATION):
        code = CONSTRAINT_ERROR_CODES.get(constraint or "")
        if code is None:
            default = {
                SQLSTATE_UNIQUE_VIOLATION: ERROR_DATABASE,
                SQLSTATE_FOREIGN_KEY_VIOLATION: ERROR_UNKNOWN_RUN,
                SQLSTATE_CHECK_VIOLATION: ERROR_CHECK_CONSTRAINT,
            }[sqlstate]
            message = {
                SQLSTATE_UNIQUE_VIOLATION: "the database rejected this write because it duplicates an existing row",
                SQLSTATE_FOREIGN_KEY_VIOLATION: "the referenced run does not exist",
                SQLSTATE_CHECK_VIOLATION: "the database rejected this row because a declared constraint failed",
            }[sqlstate]
            return _error(default, message, sqlstate=sqlstate, constraint=constraint)
        return _error(
            code,
            CONSTRAINT_MESSAGES.get(code, "the database rejected this write"),
            sqlstate=sqlstate,
            constraint=constraint,
        )
    if sqlstate == SQLSTATE_NOT_NULL_VIOLATION:
        return _error(
            ERROR_CHECK_CONSTRAINT,
            "the database rejected this row because a required column was missing",
            sqlstate=sqlstate,
            constraint=constraint,
        )
    if sqlstate in (SQLSTATE_SERIALIZATION_FAILURE, SQLSTATE_DEADLOCK_DETECTED):
        return _error(
            ERROR_SERIALIZATION,
            "the transaction was aborted by the database because of a concurrency conflict",
            sqlstate=sqlstate,
            constraint=constraint,
        )
    if sqlstate in (SQLSTATE_UNDEFINED_TABLE, SQLSTATE_UNDEFINED_COLUMN):
        return _error(
            ERROR_SCHEMA_MISSING,
            "the database schema this adapter expects is not present; apply the enterprise migration first",
            sqlstate=sqlstate,
            constraint=constraint,
        )
    if sqlstate == SQLSTATE_INSUFFICIENT_PRIVILEGE:
        return _error(
            ERROR_DATABASE,
            "the database role is not permitted to perform this operation",
            sqlstate=sqlstate,
            constraint=constraint,
        )
    return _error(
        ERROR_DATABASE,
        "the database rejected this operation",
        sqlstate=sqlstate,
        constraint=constraint,
        error_type=type(exc).__name__,
    )


def _error(
    code: str,
    message: str,
    *,
    sqlstate: str | None,
    constraint: str | None,
    error_type: str | None = None,
) -> DomainError:
    details: dict[str, Any] = {}
    if sqlstate:
        details["sqlstate"] = sqlstate
    if constraint:
        details["constraint"] = constraint
    if error_type:
        details["error_type"] = error_type
    return DomainError(code, message, details=details)


def is_redaction_safe(error: DomainError) -> bool:
    """True when an adapter error carries only code, SQLSTATE and constraint name."""
    allowed = {"sqlstate", "constraint", "error_type"}
    return set(error.details).issubset(allowed)


__all__ = [
    "CONSTRAINT_ERROR_CODES",
    "ERROR_CHECK_CONSTRAINT",
    "ERROR_DATABASE",
    "ERROR_SCHEMA_MISSING",
    "ERROR_SERIALIZATION",
    "ERROR_TRIGGER_REJECTED",
    "SQLSTATE_CHECK_VIOLATION",
    "SQLSTATE_FOREIGN_KEY_VIOLATION",
    "SQLSTATE_NOT_NULL_VIOLATION",
    "SQLSTATE_RESTRICT_VIOLATION",
    "SQLSTATE_INSUFFICIENT_PRIVILEGE",
    "SQLSTATE_SERIALIZATION_FAILURE",
    "SQLSTATE_UNDEFINED_COLUMN",
    "SQLSTATE_UNDEFINED_TABLE",
    "SQLSTATE_UNIQUE_VIOLATION",
    "constraint_name_of",
    "is_redaction_safe",
    "map_database_error",
    "sqlstate_of",
]
