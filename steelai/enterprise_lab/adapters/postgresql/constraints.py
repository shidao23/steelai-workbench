"""Frozen SQL contract constants for the Enterprise Lab PostgreSQL schema.

This module is the single source of truth shared by the live SQLAlchemy metadata
(``schema.py``, used by T82 and by tests) and the frozen Alembic migration. It
imports no SQLAlchemy and holds no ``Table``/``MetaData`` object, so a historical
migration can depend on these plain strings and constants without ever depending
on a metadata object that a later task may change.

Only the state, result-level, evidence-class and job-state value tuples come from
the domain layer, because those vocabularies are owned by the T50/T51 governance
contract and must stay in sync with it.
"""
from __future__ import annotations

from steelai.enterprise_lab.domain.models import (
    EvidenceClass,
    GovernanceState,
    JobState,
    ResultLevel,
)

#: Deterministic constraint naming convention. Every primary key, foreign key,
#: unique constraint, check constraint and index therefore has a stable name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: Stable CHECK constraint names, without the table prefix. The naming convention
#: expands them to ``ck_<table>_<name>``.
CHECK_SHA256_LOWERCASE = "sha256_lowercase_hex"
CHECK_REQUEST_DIGEST_LOWERCASE = "request_digest_lowercase_hex"
CHECK_PAYLOAD_DIGEST_LOWERCASE = "payload_digest_lowercase_hex"
CHECK_CONTENT_DIGEST_FORMAT = "content_digest_format"
CHECK_OBJECT_DIGEST_FORMAT = "object_digest_format"
CHECK_STATE_DECLARED = "state_declared"
CHECK_RESULT_LEVEL_DECLARED = "result_level_declared"
CHECK_EVIDENCE_CLASS_DECLARED = "evidence_class_declared"
CHECK_REVISION_POSITIVE = "revision_positive"
CHECK_SEQUENCE_POSITIVE = "sequence_positive"
CHECK_RELATIVE_PATH_POSIX = "relative_path_posix"
CHECK_DELIVERY_STATUS_DECLARED = "delivery_status_declared"
CHECK_PAYLOAD_IS_JSON_OBJECT = "payload_is_json_object"
CHECK_ATTEMPTS_NON_NEGATIVE = "attempts_non_negative"
CHECK_JOB_ATTEMPTS_POSITIVE = "attempts_positive"
CHECK_JOB_MAX_ATTEMPTS_POSITIVE = "max_attempts_positive"
CHECK_JOB_ATTEMPTS_WITHIN_LIMIT = "attempts_within_limit"

#: Regular expressions used by CHECK constraints.
SHA256_LOWERCASE_REGEX = "^[0-9a-f]{64}$"
#: Stable content identity of a domain object, for example ``run_<hex>``.
CONTENT_DIGEST_REGEX = "^[a-z]{2,8}_[0-9a-f]{32,64}$"

GOVERNANCE_STATE_VALUES = tuple(state.value for state in GovernanceState)
RESULT_LEVEL_VALUES = tuple(level.value for level in ResultLevel)
EVIDENCE_CLASS_VALUES = tuple(item.value for item in EvidenceClass)
JOB_STATE_VALUES = tuple(state.value for state in JobState)
DELIVERY_STATUS_VALUES = ("pending", "publishing", "published", "failed")

#: Relative-path segments that are never a valid artifact reference.
RELATIVE_PATH_BLOCKED_SEGMENTS = (".", "..")


def sql_string_list(values: tuple[str, ...]) -> str:
    """Render a value tuple as a SQL ``IN`` list."""
    return ", ".join(f"'{value}'" for value in values)


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    """Render ``column IN (...)`` for a declared vocabulary."""
    return f"{column} IN ({sql_string_list(values)})"


def relative_path_check_sql(column: str = "relative_path") -> str:
    """Reject absolute paths, backslashes, drive letters and traversal segments.

    Covers the bare ``.`` and ``..`` values as well as any ``.``/``..`` component
    inside a path, so a reference can never escape its root.
    """
    return (
        f"{column} <> ''"
        f" AND {column} NOT LIKE '/%'"
        f" AND {column} NOT LIKE '%\\\\%'"
        f" AND strpos({column}, ':') = 0"
        f" AND {column} NOT IN ('{RELATIVE_PATH_BLOCKED_SEGMENTS[0]}', "
        f"'{RELATIVE_PATH_BLOCKED_SEGMENTS[1]}')"
        f" AND {column} NOT LIKE '../%'"
        f" AND {column} NOT LIKE './%'"
        f" AND {column} NOT LIKE '%/../%'"
        f" AND {column} NOT LIKE '%/./%'"
        f" AND {column} NOT LIKE '%/..'"
        f" AND {column} NOT LIKE '%/.'"
        f" AND {column} NOT LIKE '%//%'"
    )


def sha256_check_sql(column: str) -> str:
    return f"{column} ~ '{SHA256_LOWERCASE_REGEX}'"


def content_digest_check_sql(column: str) -> str:
    return f"{column} ~ '{CONTENT_DIGEST_REGEX}'"


#: Append-only enforcement objects, created by the initial migration.
AUDIT_APPEND_ONLY_FUNCTION = "fn_audit_events_reject_mutation"
AUDIT_APPEND_ONLY_TRIGGER = "trg_audit_events_append_only"


def audit_append_only_function_sql(schema: str) -> str:
    return f"""
CREATE FUNCTION {schema}.{AUDIT_APPEND_ONLY_FUNCTION}()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""


def audit_append_only_trigger_sql(schema: str) -> str:
    return f"""
CREATE TRIGGER {AUDIT_APPEND_ONLY_TRIGGER}
BEFORE UPDATE OR DELETE ON {schema}.audit_events
FOR EACH ROW EXECUTE FUNCTION {schema}.{AUDIT_APPEND_ONLY_FUNCTION}()
""".rstrip()


def drop_audit_append_only_trigger_sql(schema: str) -> str:
    return f'DROP TRIGGER IF EXISTS {AUDIT_APPEND_ONLY_TRIGGER} ON "{schema}".audit_events'


def drop_audit_append_only_function_sql(schema: str) -> str:
    return f'DROP FUNCTION IF EXISTS "{schema}".{AUDIT_APPEND_ONLY_FUNCTION}()'


__all__ = [
    "AUDIT_APPEND_ONLY_FUNCTION",
    "AUDIT_APPEND_ONLY_TRIGGER",
    "CHECK_ATTEMPTS_NON_NEGATIVE",
    "CHECK_CONTENT_DIGEST_FORMAT",
    "CHECK_DELIVERY_STATUS_DECLARED",
    "CHECK_EVIDENCE_CLASS_DECLARED",
    "CHECK_JOB_ATTEMPTS_POSITIVE",
    "CHECK_JOB_ATTEMPTS_WITHIN_LIMIT",
    "CHECK_JOB_MAX_ATTEMPTS_POSITIVE",
    "CHECK_OBJECT_DIGEST_FORMAT",
    "CHECK_PAYLOAD_DIGEST_LOWERCASE",
    "CHECK_PAYLOAD_IS_JSON_OBJECT",
    "CHECK_RELATIVE_PATH_POSIX",
    "CHECK_REQUEST_DIGEST_LOWERCASE",
    "CHECK_RESULT_LEVEL_DECLARED",
    "CHECK_REVISION_POSITIVE",
    "CHECK_SEQUENCE_POSITIVE",
    "CHECK_SHA256_LOWERCASE",
    "CHECK_STATE_DECLARED",
    "CONTENT_DIGEST_REGEX",
    "DELIVERY_STATUS_VALUES",
    "EVIDENCE_CLASS_VALUES",
    "GOVERNANCE_STATE_VALUES",
    "JOB_STATE_VALUES",
    "NAMING_CONVENTION",
    "RELATIVE_PATH_BLOCKED_SEGMENTS",
    "RESULT_LEVEL_VALUES",
    "SHA256_LOWERCASE_REGEX",
    "audit_append_only_function_sql",
    "audit_append_only_trigger_sql",
    "content_digest_check_sql",
    "drop_audit_append_only_function_sql",
    "drop_audit_append_only_trigger_sql",
    "relative_path_check_sql",
    "sha256_check_sql",
    "sql_in_list",
    "sql_string_list",
]
