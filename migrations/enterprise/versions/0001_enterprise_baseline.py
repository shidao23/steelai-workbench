"""enterprise metadata baseline

Revision ID: 0001_enterprise_baseline
Revises:
Create Date: 2026-09-17

Hand-written, hand-reviewed, FROZEN baseline migration for the optional SteelAI
Enterprise Lab PostgreSQL schema (T81).

Frozen means: this revision declares every column, primary key, foreign key,
unique constraint and CHECK constraint explicitly, and depends on **no SteelAI
runtime module at all**. It does not import the live schema module, the shared
contract module or the domain layer; the naming convention, constraint names,
digest patterns, state vocabularies, delivery statuses, the relative-path CHECK
SQL and the audit trigger SQL are all frozen as literals inside this file. A later
task may change any of those modules; this revision must keep producing exactly
the same DDL, and a T81 baseline change requires a new revision.

What it creates:

- schema ``steelai_enterprise`` (idempotent, never dropped by ``downgrade``);
- five business-metadata tables: ``workflow_runs``, ``artifact_references``,
  ``audit_events``, ``outbox_events``, ``background_jobs``;
- named primary keys, foreign keys, unique constraints, CHECK constraints and
  the minimal index set described in the T81 baseline document;
- an append-only trigger that rejects UPDATE and DELETE on ``audit_events``.

What it deliberately does not do: it creates no PostgreSQL enum type, inserts no
seed or demo row, reads no scientific file, touches no processed-data path and
claims no repository, dispatcher, worker or Kafka integration.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# This revision imports NOTHING from ``steelai.*``: only the standard library,
# Alembic and SQLAlchemy. Every contract value it needs is frozen below.


#: The Alembic version table stores ``version_num`` as ``VARCHAR(32)``, so a
#: revision id must never exceed 32 characters.
revision = "0001_enterprise_baseline"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA = "steelai_enterprise"

#: Creation order follows the foreign-key dependency graph.
TABLE_CREATION_ORDER = (
    "workflow_runs",
    "artifact_references",
    "audit_events",
    "outbox_events",
    "background_jobs",
)

#: Deletion order is the exact reverse, without CASCADE.
TABLE_DROP_ORDER = tuple(reversed(TABLE_CREATION_ORDER))

#: Indexes created by this revision, in creation order.
INDEX_DEFINITIONS = (
    ("ix_workflow_runs_project_id", "workflow_runs", ("project_id",)),
    ("ix_workflow_runs_task_id", "workflow_runs", ("task_id",)),
    ("ix_workflow_runs_state", "workflow_runs", ("state",)),
    ("ix_workflow_runs_created_at", "workflow_runs", ("created_at",)),
    ("ix_artifact_references_run_id", "artifact_references", ("run_id",)),
    ("ix_audit_events_run_id", "audit_events", ("run_id",)),
    (
        "ix_outbox_events_delivery_status_available_at",
        "outbox_events",
        ("delivery_status", "available_at"),
    ),
    ("ix_background_jobs_state_created_at", "background_jobs", ("state", "created_at")),
)


def _text(sql: str):
    """Wrap raw SQL text so it survives offline (``--sql``) rendering."""
    return sa.text(sql)


# ---------------------------------------------------------------------------
# FROZEN T81 BASELINE LITERALS
#
# Everything below is a literal copy of the T81 contract as it stood when this
# revision was written. This revision imports NOTHING from ``steelai.*``: not the
# live ``schema`` module, not ``constraints`` and not the domain layer. Editing any
# of those modules therefore cannot change the DDL this historical revision emits -
# a changed contract needs a NEW revision.
# ---------------------------------------------------------------------------

#: Constraint naming convention used when this revision creates its tables.
#: ``op.create_table`` builds its DDL through a fresh ``MetaData``, so it needs the
#: same convention the T81 live schema used. Primary keys and unique constraints
#: carry their final name explicitly; CHECK constraints pass the bare check name,
#: which this convention expands to ``ck_<table>_<check>``.
FROZEN_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SHA256_PATTERN = "^[0-9a-f]{64}$"
CONTENT_DIGEST_PATTERN = "^[a-z]{2,8}_[0-9a-f]{32,64}$"

GOVERNANCE_STATES = (
    "draft",
    "needs_human",
    "approved",
    "running",
    "passed",
    "warning",
    "rejected",
    "blocked",
    "complete",
    "invalidated",
)
RESULT_LEVELS = (
    "working_candidate",
    "synthetic_demo_only",
    "model_result",
    "verified_output",
    "accepted_evidence",
    "human_conclusion",
)
EVIDENCE_CLASSES = (
    "real_research_data",
    "synthetic_demo_data",
    "model_output",
    "human_conclusion",
)
JOB_STATES = ("queued", "leased", "retrying", "succeeded", "failed", "cancelled")
DELIVERY_STATUSES = ("pending", "publishing", "published", "failed")

CHECK_REQUEST_DIGEST_LOWERCASE = "request_digest_lowercase_hex"
CHECK_PAYLOAD_DIGEST_LOWERCASE = "payload_digest_lowercase_hex"
CHECK_SHA256_LOWERCASE = "sha256_lowercase_hex"
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

AUDIT_APPEND_ONLY_FUNCTION = "fn_audit_events_reject_mutation"
AUDIT_APPEND_ONLY_TRIGGER = "trg_audit_events_append_only"

#: The append-only trigger function, frozen verbatim.
AUDIT_TRIGGER_FUNCTION_SQL = f"""
CREATE FUNCTION {SCHEMA}.{AUDIT_APPEND_ONLY_FUNCTION}()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""

#: The append-only trigger binding, frozen verbatim.
AUDIT_TRIGGER_SQL = f"""
CREATE TRIGGER {AUDIT_APPEND_ONLY_TRIGGER}
BEFORE UPDATE OR DELETE ON {SCHEMA}.audit_events
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{AUDIT_APPEND_ONLY_FUNCTION}()
""".rstrip()


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    """Frozen ``column IN (...)`` renderer for the declared T81 vocabularies."""
    rendered = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({rendered})"


def _sha256_check(column: str) -> str:
    return f"{column} ~ '{SHA256_PATTERN}'"


def _content_digest_check(column: str) -> str:
    return f"{column} ~ '{CONTENT_DIGEST_PATTERN}'"


def _relative_path_check(column: str = "relative_path") -> str:
    """The frozen T81 relative-path predicate.

    Rejects an empty value, an absolute path, a backslash, a drive letter, the bare
    ``.`` and ``..`` values, and every ``.``/``..``/empty path component.
    """
    return (
        f"{column} <> ''"
        f" AND {column} NOT LIKE '/%'"
        f" AND {column} NOT LIKE '%\\\\%'"
        f" AND strpos({column}, ':') = 0"
        f" AND {column} NOT IN ('.', '..')"
        f" AND {column} NOT LIKE '../%'"
        f" AND {column} NOT LIKE './%'"
        f" AND {column} NOT LIKE '%/../%'"
        f" AND {column} NOT LIKE '%/./%'"
        f" AND {column} NOT LIKE '%/..'"
        f" AND {column} NOT LIKE '%/.'"
        f" AND {column} NOT LIKE '%//%'"
    )


def _table_columns_and_constraints(name: str) -> tuple[list, list]:
    """Explicit, frozen definition of one table.

    Every column and constraint is declared here by hand. Nothing is read from a
    runtime ``Table`` object, so a later metadata change cannot silently alter
    what this historical revision creates.
    """
    if name == "workflow_runs":
        columns = [
            sa.Column("run_id", sa.String(160), nullable=False),
            sa.Column("project_id", sa.String(160), nullable=False),
            sa.Column("task_id", sa.String(160), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("content_digest", sa.String(72), nullable=False),
            sa.Column("result_level", sa.String(32), nullable=False),
            sa.Column("evidence_class", sa.String(32), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("request_digest", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(160), nullable=False),
            sa.Column("next_action", sa.String(200), nullable=False),
        ]
        constraints = [
            sa.PrimaryKeyConstraint("run_id", name="pk_workflow_runs"),
            sa.UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
            sa.CheckConstraint(
                _sha256_check("request_digest"),
                name=f"{CHECK_REQUEST_DIGEST_LOWERCASE}",
            ),
            sa.CheckConstraint(
                _content_digest_check("content_digest"),
                name=f"{CHECK_CONTENT_DIGEST_FORMAT}",
            ),
            sa.CheckConstraint(
                _sql_in("state", GOVERNANCE_STATES),
                name=f"{CHECK_STATE_DECLARED}",
            ),
            sa.CheckConstraint(
                _sql_in("result_level", RESULT_LEVELS),
                name=f"{CHECK_RESULT_LEVEL_DECLARED}",
            ),
            sa.CheckConstraint(
                _sql_in("evidence_class", EVIDENCE_CLASSES),
                name=f"{CHECK_EVIDENCE_CLASS_DECLARED}",
            ),
            sa.CheckConstraint("revision >= 1", name=f"{CHECK_REVISION_POSITIVE}"),
        ]
        return columns, constraints

    if name == "artifact_references":
        columns = [
            sa.Column("artifact_id", sa.String(160), nullable=False),
            sa.Column("run_id", sa.String(160), nullable=False),
            sa.Column("relative_path", sa.String(240), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("artifact_type", sa.String(160), nullable=False),
            sa.Column("artifact_version", sa.String(160), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]
        constraints = [
            sa.PrimaryKeyConstraint("artifact_id", name="pk_artifact_references"),
            sa.ForeignKeyConstraint(
                ["run_id"],
                [f"{SCHEMA}.workflow_runs.run_id"],
                name="fk_artifact_references_run_id_workflow_runs",
            ),
            sa.UniqueConstraint("relative_path", name="uq_artifact_references_relative_path"),
            sa.CheckConstraint(
                _sha256_check("sha256"), name=f"{CHECK_SHA256_LOWERCASE}"
            ),
            sa.CheckConstraint(
                _relative_path_check(),
                name=f"{CHECK_RELATIVE_PATH_POSIX}",
            ),
        ]
        return columns, constraints

    if name == "audit_events":
        columns = [
            sa.Column("audit_id", sa.String(160), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.String(160), nullable=False),
            sa.Column("action", sa.String(160), nullable=False),
            sa.Column("actor_role", sa.String(32), nullable=False),
            sa.Column("actor_id", sa.String(160), nullable=False),
            sa.Column("summary", sa.String(240), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("object_type", sa.String(160), nullable=False),
            sa.Column("object_id", sa.String(160), nullable=False),
            sa.Column("object_revision", sa.Integer(), nullable=False),
            sa.Column("object_digest", sa.String(72), nullable=False),
        ]
        constraints = [
            sa.PrimaryKeyConstraint("audit_id", name="pk_audit_events"),
            sa.ForeignKeyConstraint(
                ["run_id"], [f"{SCHEMA}.workflow_runs.run_id"], name="fk_audit_events_run_id_workflow_runs"
            ),
            sa.UniqueConstraint("sequence", name="uq_audit_events_sequence"),
            sa.CheckConstraint("sequence > 0", name=f"{CHECK_SEQUENCE_POSITIVE}"),
            sa.CheckConstraint("object_revision >= 1", name=f"{CHECK_REVISION_POSITIVE}"),
            sa.CheckConstraint(
                _content_digest_check("object_digest"),
                name=f"{CHECK_OBJECT_DIGEST_FORMAT}",
            ),
        ]
        return columns, constraints

    if name == "outbox_events":
        columns = [
            sa.Column("event_id", sa.String(160), nullable=False),
            sa.Column("event_type", sa.String(160), nullable=False),
            sa.Column("run_id", sa.String(160), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("delivery_status", sa.String(32), nullable=False, server_default=_text("'pending'")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=_text("0")),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(64), nullable=True),
        ]
        constraints = [
            sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
            sa.ForeignKeyConstraint(
                ["run_id"], [f"{SCHEMA}.workflow_runs.run_id"], name="fk_outbox_events_run_id_workflow_runs"
            ),
            sa.UniqueConstraint("run_id", "sequence", name="uq_outbox_events_run_id_sequence"),
            sa.CheckConstraint("sequence > 0", name=f"{CHECK_SEQUENCE_POSITIVE}"),
            sa.CheckConstraint(
                _sql_in("delivery_status", DELIVERY_STATUSES),
                name=f"{CHECK_DELIVERY_STATUS_DECLARED}",
            ),
            sa.CheckConstraint(
                "jsonb_typeof(payload) = 'object'",
                name=f"{CHECK_PAYLOAD_IS_JSON_OBJECT}",
            ),
            sa.CheckConstraint("attempts >= 0", name=f"{CHECK_ATTEMPTS_NON_NEGATIVE}"),
        ]
        return columns, constraints

    if name == "background_jobs":
        columns = [
            sa.Column("job_id", sa.String(160), nullable=False),
            sa.Column("job_type", sa.String(160), nullable=False),
            sa.Column("run_id", sa.String(160), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("request_digest", sa.String(64), nullable=False),
            sa.Column("payload_digest", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lease_id", sa.String(160), nullable=True),
            sa.Column("error_code", sa.String(64), nullable=True),
        ]
        constraints = [
            sa.PrimaryKeyConstraint("job_id", name="pk_background_jobs"),
            sa.ForeignKeyConstraint(
                ["run_id"],
                [f"{SCHEMA}.workflow_runs.run_id"],
                name="fk_background_jobs_run_id_workflow_runs",
            ),
            sa.UniqueConstraint("idempotency_key", name="uq_background_jobs_idempotency_key"),
            sa.CheckConstraint(
                _sha256_check("request_digest"),
                name=f"{CHECK_REQUEST_DIGEST_LOWERCASE}",
            ),
            sa.CheckConstraint(
                _sha256_check("payload_digest"),
                name=f"{CHECK_PAYLOAD_DIGEST_LOWERCASE}",
            ),
            sa.CheckConstraint(
                _sql_in("state", JOB_STATES), name=f"{CHECK_STATE_DECLARED}"
            ),
            sa.CheckConstraint("attempts >= 1", name=f"{CHECK_JOB_ATTEMPTS_POSITIVE}"),
            sa.CheckConstraint(
                "max_attempts >= 1", name=f"{CHECK_JOB_MAX_ATTEMPTS_POSITIVE}"
            ),
            sa.CheckConstraint(
                "attempts <= max_attempts", name=f"{CHECK_JOB_ATTEMPTS_WITHIN_LIMIT}"
            ),
        ]
        return columns, constraints

    raise ValueError(f"unknown table in the frozen baseline revision: {name}")


def upgrade() -> None:
    # The schema must exist before Alembic writes its version row, and
    # ``env.py`` also creates it before the first revision runs.
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    for name in TABLE_CREATION_ORDER:
        columns, constraints = _table_columns_and_constraints(name)
        op.create_table(
            name, *columns, *constraints, schema=SCHEMA, naming_convention=FROZEN_NAMING_CONVENTION
        )

    for index_name, table_name, columns in INDEX_DEFINITIONS:
        op.create_index(index_name, table_name, list(columns), schema=SCHEMA)

    # Append-only enforcement for the audit trail: UPDATE and DELETE fail with a
    # stable SQLSTATE ('restrict_violation') and a deterministic object name.
    op.execute(AUDIT_TRIGGER_FUNCTION_SQL)
    op.execute(AUDIT_TRIGGER_SQL)


def downgrade() -> None:
    # Reverse dependency order, no CASCADE, no DROP DATABASE and no deletion of
    # anything this migration does not own. The ``steelai_enterprise`` schema is
    # intentionally left in place and empty: another owner may have created it,
    # and dropping it would be an unrecoverable, out-of-scope side effect.
    op.execute(f'DROP TRIGGER IF EXISTS {AUDIT_APPEND_ONLY_TRIGGER} ON "{SCHEMA}".audit_events')
    op.execute(f'DROP FUNCTION IF EXISTS "{SCHEMA}".{AUDIT_APPEND_ONLY_FUNCTION}()')

    for name in TABLE_DROP_ORDER:
        # Nothing references workflow_runs by the time it is dropped, so no
        # CASCADE is needed and none is used.
        op.drop_table(name, schema=SCHEMA)
