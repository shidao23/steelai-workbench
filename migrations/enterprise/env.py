"""Alembic environment for the optional Enterprise Lab PostgreSQL schema.

The database URL is resolved only from an explicit runtime override or from
``STEELAI_ENTERPRISE_DATABASE_URL``; nothing is stored in the ini file, no ``.env``
is read and no connection is opened at import time.

Two safety gates protect against pointing migrations at the wrong database:

- ``STEELAI_ENTERPRISE_TEST_DATABASE_ONLY=1`` restricts migration runs to
  databases whose name contains both ``steelai`` and ``test``; the integration
  test sets it;
- ``STEELAI_ENTERPRISE_ALLOW_ANY_DATABASE=1`` is the explicit, documented opt-in
  for a dedicated development database with any other name.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from steelai.enterprise_lab.adapters.postgresql.config import (
    ALEMBIC_VERSION_TABLE,
    DATABASE_URL_ENV_VAR,
    ERROR_UNSAFE_MIGRATION_TARGET,
    POSTGRESQL_SCHEMA,
    EnterpriseDatabaseConfig,
    EnterpriseDatabaseConfigError,
    describe_database_target,
)
from steelai.enterprise_lab.adapters.postgresql.schema import metadata


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

ALLOW_ANY_DATABASE_ENV_VAR = "STEELAI_ENTERPRISE_ALLOW_ANY_DATABASE"
TEST_DATABASE_ONLY_ENV_VAR = "STEELAI_ENTERPRISE_TEST_DATABASE_ONLY"


def _is_test_database(name: str) -> bool:
    lowered = (name or "").lower()
    return "steelai" in lowered and "test" in lowered


def _resolve_url() -> str:
    """Resolve the migration target URL without ever printing it."""
    override = config.get_main_option("sqlalchemy.url", None)
    explicit = override if override and override.strip() else None
    url = explicit or os.environ.get(DATABASE_URL_ENV_VAR)
    if not url or not url.strip():
        raise EnterpriseDatabaseConfigError(
            "ENT-DB-CONFIG-001",
            f"migrations need a database URL; set {DATABASE_URL_ENV_VAR} or pass one explicitly",
        )
    return EnterpriseDatabaseConfig(url=url).url


def guard_migration_target(url: str, environ: dict[str, str] | None = None) -> str:
    """Refuse to migrate a database that is not clearly a SteelAI test database.

    Returns the resolved database name so callers can log a safe identifier. The
    URL itself is never rendered.
    """
    source = os.environ if environ is None else environ
    name = describe_database_target(url).get("database", "")
    if _is_test_database(name):
        return name
    if source.get(TEST_DATABASE_ONLY_ENV_VAR) == "1":
        raise EnterpriseDatabaseConfigError(
            ERROR_UNSAFE_MIGRATION_TARGET,
            "refusing to run migrations: the target database name must contain both "
            "'steelai' and 'test' while the test-database-only guard is set",
        )
    if source.get(ALLOW_ANY_DATABASE_ENV_VAR) == "1":
        return name
    raise EnterpriseDatabaseConfigError(
        ERROR_UNSAFE_MIGRATION_TARGET,
        "refusing to run migrations against a database whose name does not contain both "
        "'steelai' and 'test'; set the explicit allow-any-database opt-in for a dedicated "
        "development database",
    )


def _common_configuration() -> dict:
    return {
        "target_metadata": target_metadata,
        "include_schemas": True,
        "version_table": ALEMBIC_VERSION_TABLE,
        "version_table_schema": POSTGRESQL_SCHEMA,
        "compare_type": True,
        "compare_server_default": True,
    }


def run_migrations_offline() -> None:
    """Emit SQL for the migration without connecting to any database."""
    url = _resolve_url()
    config.set_main_option("sqlalchemy.url", url)
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_configuration(),
    )
    with context.begin_transaction():
        # In offline mode Alembic emits the version table (inside the dedicated
        # schema) before it runs the first revision, so the schema statement has
        # to come first for the generated SQL to be executable top to bottom.
        context.static_output(f'CREATE SCHEMA IF NOT EXISTS "{POSTGRESQL_SCHEMA}";')
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a real database."""
    url = _resolve_url()
    guard_migration_target(url)
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # The version table lives in the dedicated schema, which must exist
        # before Alembic writes its first revision row. This is the only DDL
        # issued outside a migration revision; the baseline migration repeats it
        # idempotently so the schema is part of the reviewed migration too.
        connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{POSTGRESQL_SCHEMA}"')
        connection.commit()
        context.configure(connection=connection, **_common_configuration())
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
