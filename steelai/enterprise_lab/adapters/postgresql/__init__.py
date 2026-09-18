"""Optional PostgreSQL boundary of the Enterprise Lab (T81 schema, T82 adapter, T83 delivery).

Importing anything in this package requires the optional dependencies listed in
``requirements-enterprise.txt`` (SQLAlchemy 2.x, Alembic, Psycopg 3). It is
therefore deliberately **not** imported by ``steelai.enterprise_lab``, by
``steelai.enterprise_lab.adapters`` or by the default application, so an
installation without those packages keeps working.

T81 scope: PostgreSQL schema, initial Alembic migration, explicit connection
configuration and the mapping contract.

T82 scope: the optional PostgreSQL ``RunRepository``, ``AuditRepository``,
``ArtifactStore``, ``EventPublisher`` (transactional outbox write side),
``JobQueue`` and the ``UnitOfWork`` that binds them to one connection and one
transaction.

T83 scope: the outbox **delivery** side on the same frozen ``outbox_events`` table -
``PostgreSQLOutboxDeliveryRepository`` claims with ``FOR UPDATE SKIP LOCKED``, acknowledges
with an ``attempts`` fencing token and recovers expired leases, each step in its own short
transaction. It adds no column, index or migration, and it still provides no Kafka client,
no worker daemon and no API.

T84 scope: the background job **execution** side on the frozen ``background_jobs`` table -
``PostgreSQLJobExecutionRepository`` claims with ``FOR UPDATE SKIP LOCKED``, writes a fresh
``lease_id``, fences every write with ``job_id + lease_id + attempts``, refreshes
``updated_at`` on a heartbeat and recovers timed-out leases on the database clock, each step
in its own short transaction. It adds no table, column, index or migration, keeps every state
change inside the frozen ``BackgroundJob.transition`` machine, and still provides no daemon,
no scheduler and no API.
"""
from .config import (
    ALEMBIC_VERSION_TABLE,
    DATABASE_URL_ENV_VAR,
    POSTGRESQL_SCHEMA,
    EnterpriseDatabaseConfig,
    EnterpriseDatabaseConfigError,
    create_engine_from_config,
    create_enterprise_engine,
    load_database_config,
    redact_database_url,
    resolve_database_url,
)
from .errors import ERROR_DATABASE, map_database_error, sqlstate_of
from .hydration import (
    hydrate_artifact_reference,
    hydrate_audit_event,
    hydrate_background_job,
    hydrate_domain_event,
    hydrate_workflow_run,
)
from .mapping import TABLE_MAPPINGS, mapping_report
from .outbox import PostgreSQLOutboxDeliveryRepository
from .worker import PostgreSQLJobExecutionRepository
from .repositories import (
    PostgreSQLArtifactStore,
    PostgreSQLAuditRepository,
    PostgreSQLEventPublisher,
    PostgreSQLJobQueue,
    PostgreSQLRunRepository,
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)

__all__ = [
    "ALEMBIC_VERSION_TABLE",
    "DATABASE_URL_ENV_VAR",
    "ERROR_DATABASE",
    "EnterpriseDatabaseConfig",
    "EnterpriseDatabaseConfigError",
    "POSTGRESQL_SCHEMA",
    "PostgreSQLArtifactStore",
    "PostgreSQLAuditRepository",
    "PostgreSQLEventPublisher",
    "PostgreSQLJobExecutionRepository",
    "PostgreSQLJobQueue",
    "PostgreSQLOutboxDeliveryRepository",
    "PostgreSQLRunRepository",
    "PostgreSQLUnitOfWork",
    "PostgreSQLUnitOfWorkFactory",
    "TABLE_MAPPINGS",
    "create_engine_from_config",
    "create_enterprise_engine",
    "hydrate_artifact_reference",
    "hydrate_audit_event",
    "hydrate_background_job",
    "hydrate_domain_event",
    "hydrate_workflow_run",
    "load_database_config",
    "map_database_error",
    "mapping_report",
    "redact_database_url",
    "resolve_database_url",
    "sqlstate_of",
]
