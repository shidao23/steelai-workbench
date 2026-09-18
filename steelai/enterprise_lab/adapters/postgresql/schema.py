"""PostgreSQL-specific SQLAlchemy Core metadata for the Enterprise Lab.

This module owns the **live** database schema definition used by T82 and by the
tests. It never creates PostgreSQL enums (states stay string columns with named
CHECK constraints so a later state change is a normal migration), never adds ORM
base classes to the domain objects and never stores experimental values, file
bytes, credentials or absolute paths.

The SQL text and names live in ``constraints.py`` so the frozen migration can
reuse them without importing this module or its ``Table``/``MetaData`` objects.

Only ``adapters/postgresql`` imports SQLAlchemy. The domain, application and
ports layers must not.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .config import POSTGRESQL_SCHEMA
from .constraints import (
    CHECK_ATTEMPTS_NON_NEGATIVE,
    CHECK_CONTENT_DIGEST_FORMAT,
    CHECK_DELIVERY_STATUS_DECLARED,
    CHECK_EVIDENCE_CLASS_DECLARED,
    CHECK_JOB_ATTEMPTS_POSITIVE,
    CHECK_JOB_ATTEMPTS_WITHIN_LIMIT,
    CHECK_JOB_MAX_ATTEMPTS_POSITIVE,
    CHECK_OBJECT_DIGEST_FORMAT,
    CHECK_PAYLOAD_DIGEST_LOWERCASE,
    CHECK_PAYLOAD_IS_JSON_OBJECT,
    CHECK_RELATIVE_PATH_POSIX,
    CHECK_REQUEST_DIGEST_LOWERCASE,
    CHECK_RESULT_LEVEL_DECLARED,
    CHECK_REVISION_POSITIVE,
    CHECK_SEQUENCE_POSITIVE,
    CHECK_SHA256_LOWERCASE,
    CHECK_STATE_DECLARED,
    CONTENT_DIGEST_REGEX,
    DELIVERY_STATUS_VALUES,
    EVIDENCE_CLASS_VALUES,
    GOVERNANCE_STATE_VALUES,
    JOB_STATE_VALUES,
    NAMING_CONVENTION,
    RESULT_LEVEL_VALUES,
    SHA256_LOWERCASE_REGEX,
    audit_append_only_function_sql,
    audit_append_only_trigger_sql,
    content_digest_check_sql,
    relative_path_check_sql,
    sha256_check_sql,
    sql_in_list,
)


SCHEMA_VERSION = "1.0"

#: Append-only enforcement objects, created by the initial migration.
AUDIT_APPEND_ONLY_FUNCTION = "fn_audit_events_reject_mutation"
AUDIT_APPEND_ONLY_TRIGGER = "trg_audit_events_append_only"

AUDIT_TRIGGER_SQL = audit_append_only_function_sql(POSTGRESQL_SCHEMA)
AUDIT_TRIGGER_BIND_SQL = audit_append_only_trigger_sql(POSTGRESQL_SCHEMA)

metadata = MetaData(schema=POSTGRESQL_SCHEMA, naming_convention=NAMING_CONVENTION)


workflow_runs = Table(
    "workflow_runs",
    metadata,
    Column("run_id", String(160), primary_key=True),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("state", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("content_digest", String(72), nullable=False),
    Column("result_level", String(32), nullable=False),
    Column("evidence_class", String(32), nullable=False),
    Column("idempotency_key", String(160), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("created_by", String(160), nullable=False),
    Column("next_action", String(200), nullable=False),
    UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
    CheckConstraint(sha256_check_sql("request_digest"), name=CHECK_REQUEST_DIGEST_LOWERCASE),
    CheckConstraint(content_digest_check_sql("content_digest"), name=CHECK_CONTENT_DIGEST_FORMAT),
    CheckConstraint(sql_in_list("state", GOVERNANCE_STATE_VALUES), name=CHECK_STATE_DECLARED),
    CheckConstraint(
        sql_in_list("result_level", RESULT_LEVEL_VALUES), name=CHECK_RESULT_LEVEL_DECLARED
    ),
    CheckConstraint(
        sql_in_list("evidence_class", EVIDENCE_CLASS_VALUES), name=CHECK_EVIDENCE_CLASS_DECLARED
    ),
    CheckConstraint("revision >= 1", name=CHECK_REVISION_POSITIVE),
    schema=POSTGRESQL_SCHEMA,
)


artifact_references = Table(
    "artifact_references",
    metadata,
    Column("artifact_id", String(160), primary_key=True),
    Column(
        "run_id",
        String(160),
        ForeignKey(f"{POSTGRESQL_SCHEMA}.workflow_runs.run_id", name="fk_artifact_references_run_id_workflow_runs"),
        nullable=False,
    ),
    Column("relative_path", String(240), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("artifact_type", String(160), nullable=False),
    Column("artifact_version", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("relative_path", name="uq_artifact_references_relative_path"),
    CheckConstraint(sha256_check_sql("sha256"), name=CHECK_SHA256_LOWERCASE),
    CheckConstraint(relative_path_check_sql(), name=CHECK_RELATIVE_PATH_POSIX),
    schema=POSTGRESQL_SCHEMA,
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("audit_id", String(160), primary_key=True),
    Column("sequence", Integer, nullable=False),
    Column(
        "run_id",
        String(160),
        ForeignKey(f"{POSTGRESQL_SCHEMA}.workflow_runs.run_id", name="fk_audit_events_run_id_workflow_runs"),
        nullable=False,
    ),
    Column("action", String(160), nullable=False),
    Column("actor_role", String(32), nullable=False),
    Column("actor_id", String(160), nullable=False),
    Column("summary", String(240), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("object_type", String(160), nullable=False),
    Column("object_id", String(160), nullable=False),
    Column("object_revision", Integer, nullable=False),
    Column("object_digest", String(72), nullable=False),
    UniqueConstraint("sequence", name="uq_audit_events_sequence"),
    CheckConstraint("sequence > 0", name=CHECK_SEQUENCE_POSITIVE),
    CheckConstraint("object_revision >= 1", name=CHECK_REVISION_POSITIVE),
    CheckConstraint(content_digest_check_sql("object_digest"), name=CHECK_OBJECT_DIGEST_FORMAT),
    schema=POSTGRESQL_SCHEMA,
)


outbox_events = Table(
    "outbox_events",
    metadata,
    Column("event_id", String(160), primary_key=True),
    Column("event_type", String(160), nullable=False),
    Column(
        "run_id",
        String(160),
        ForeignKey(f"{POSTGRESQL_SCHEMA}.workflow_runs.run_id", name="fk_outbox_events_run_id_workflow_runs"),
        nullable=False,
    ),
    Column("sequence", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("delivery_status", String(32), nullable=False, server_default=text("'pending'")),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("last_error_code", String(64), nullable=True),
    UniqueConstraint("run_id", "sequence", name="uq_outbox_events_run_id_sequence"),
    CheckConstraint("sequence > 0", name=CHECK_SEQUENCE_POSITIVE),
    CheckConstraint(
        sql_in_list("delivery_status", DELIVERY_STATUS_VALUES), name=CHECK_DELIVERY_STATUS_DECLARED
    ),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name=CHECK_PAYLOAD_IS_JSON_OBJECT),
    CheckConstraint("attempts >= 0", name=CHECK_ATTEMPTS_NON_NEGATIVE),
    schema=POSTGRESQL_SCHEMA,
)


background_jobs = Table(
    "background_jobs",
    metadata,
    Column("job_id", String(160), primary_key=True),
    Column("job_type", String(160), nullable=False),
    Column(
        "run_id",
        String(160),
        ForeignKey(f"{POSTGRESQL_SCHEMA}.workflow_runs.run_id", name="fk_background_jobs_run_id_workflow_runs"),
        nullable=False,
    ),
    Column("state", String(32), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("idempotency_key", String(160), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("payload_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("lease_id", String(160), nullable=True),
    Column("error_code", String(64), nullable=True),
    UniqueConstraint("idempotency_key", name="uq_background_jobs_idempotency_key"),
    CheckConstraint(sha256_check_sql("request_digest"), name=CHECK_REQUEST_DIGEST_LOWERCASE),
    CheckConstraint(sha256_check_sql("payload_digest"), name=CHECK_PAYLOAD_DIGEST_LOWERCASE),
    CheckConstraint(sql_in_list("state", JOB_STATE_VALUES), name=CHECK_STATE_DECLARED),
    CheckConstraint("attempts >= 1", name=CHECK_JOB_ATTEMPTS_POSITIVE),
    CheckConstraint("max_attempts >= 1", name=CHECK_JOB_MAX_ATTEMPTS_POSITIVE),
    CheckConstraint("attempts <= max_attempts", name=CHECK_JOB_ATTEMPTS_WITHIN_LIMIT),
    schema=POSTGRESQL_SCHEMA,
)


#: The only indexes T81 creates. They support the documented read paths
#: (run listing, dispatcher polling and job leasing) without over-indexing.
Index("ix_workflow_runs_project_id", workflow_runs.c.project_id)
Index("ix_workflow_runs_task_id", workflow_runs.c.task_id)
Index("ix_workflow_runs_state", workflow_runs.c.state)
Index("ix_workflow_runs_created_at", workflow_runs.c.created_at)
Index("ix_artifact_references_run_id", artifact_references.c.run_id)
Index("ix_audit_events_run_id", audit_events.c.run_id)
Index(
    "ix_outbox_events_delivery_status_available_at",
    outbox_events.c.delivery_status,
    outbox_events.c.available_at,
)
Index("ix_background_jobs_state_created_at", background_jobs.c.state, background_jobs.c.created_at)


TABLES_IN_DROP_ORDER = (
    "artifact_references",
    "audit_events",
    "outbox_events",
    "background_jobs",
    "workflow_runs",
)


def schema_table_names() -> tuple[str, ...]:
    """The five business tables owned by this baseline."""
    return tuple(sorted(table.name for table in metadata.tables.values()))


def table(name: str) -> Table:
    return metadata.tables[f"{POSTGRESQL_SCHEMA}.{name}"]


__all__ = [
    "AUDIT_APPEND_ONLY_FUNCTION",
    "AUDIT_APPEND_ONLY_TRIGGER",
    "AUDIT_TRIGGER_BIND_SQL",
    "AUDIT_TRIGGER_SQL",
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
    "POSTGRESQL_SCHEMA",
    "RESULT_LEVEL_VALUES",
    "SCHEMA_VERSION",
    "SHA256_LOWERCASE_REGEX",
    "TABLES_IN_DROP_ORDER",
    "artifact_references",
    "audit_events",
    "background_jobs",
    "metadata",
    "outbox_events",
    "schema_table_names",
    "table",
    "workflow_runs",
]
