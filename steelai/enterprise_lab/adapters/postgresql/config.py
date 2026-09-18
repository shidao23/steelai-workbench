"""Explicit PostgreSQL configuration and engine factory for the Enterprise Lab.

This module is part of the optional PostgreSQL boundary. Importing it requires
SQLAlchemy and Psycopg 3, and it is therefore never imported by
``steelai.enterprise_lab``, ``steelai.enterprise_lab.adapters`` or the default
application.

Boundary rules enforced here:

- the connection string comes only from an explicit argument or from
  ``STEELAI_ENTERPRISE_DATABASE_URL``;
- a missing connection string fails closed with :class:`EnterpriseDatabaseConfigError`;
- there is no default connection string, no user name, no password and no host;
- ``.env`` is never read or written;
- a full connection string or password is never rendered: ``str``/``repr`` of the
  configuration and every error message go through :func:`redact_database_url`;
- no connection is opened at import time, and no global Session is created.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

import sqlalchemy
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import QueuePool


DATABASE_URL_ENV_VAR = "STEELAI_ENTERPRISE_DATABASE_URL"
POSTGRESQL_SCHEMA = "steelai_enterprise"
ALEMBIC_VERSION_TABLE = "alembic_version_enterprise"

ERROR_MISSING_DATABASE_URL = "ENT-DB-CONFIG-001"
ERROR_INVALID_DATABASE_URL = "ENT-DB-CONFIG-002"
ERROR_NOT_A_POSTGRESQL_URL = "ENT-DB-CONFIG-003"
ERROR_UNSAFE_MIGRATION_TARGET = "ENT-DB-CONFIG-004"

#: Redaction marker used everywhere a secret could otherwise leak.
REDACTED = "***"


class EnterpriseDatabaseConfigError(RuntimeError):
    """Fail-closed configuration error that never carries credentials."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict[str, Any]:
        return {"status": "blocked", "error_code": self.code, "message": self.message, "details": self.details}


def redact_database_url(url: str) -> str:
    """Return a log-safe rendering of a database URL.

    The user name, the password, every query-string value and any host are
    replaced, so no credential, account name or endpoint can leak into a log,
    an exception or a test report. Unparsable input is reduced to a fixed marker
    instead of being echoed back.
    """
    if not isinstance(url, str) or not url.strip():
        return "<empty>"
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 - any parser failure must not leak the input
        return "<unparsable database url>"
    safe = parsed.set(
        username=REDACTED,
        password=REDACTED if parsed.password else None,
        host=REDACTED,
    )
    if parsed.query:
        safe = safe.set(query={key: REDACTED for key in parsed.query})
    return safe.render_as_string(hide_password=False)


def describe_database_target(url: str) -> dict[str, str]:
    """Describe a target without exposing user, password, host or port."""
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001
        return {"driver": "unknown", "database": "unknown"}
    return {
        "driver": parsed.drivername,
        "database": parsed.database or "",
    }


@dataclass(frozen=True)
class EnterpriseDatabaseConfig:
    """Resolved PostgreSQL settings. Never renders credentials."""

    url: str
    schema: str = POSTGRESQL_SCHEMA
    echo: bool = False
    pool_pre_ping: bool = True
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout_seconds: int = 30
    application_name: str = "steelai-enterprise-lab"

    def __post_init__(self) -> None:
        parsed = _parse_postgresql_url(self.url)
        if not parsed.database:
            raise EnterpriseDatabaseConfigError(
                ERROR_INVALID_DATABASE_URL, "database URL must name a database"
            )
        if self.pool_size < 1 or self.max_overflow < 0 or self.pool_timeout_seconds < 1:
            raise EnterpriseDatabaseConfigError(
                ERROR_INVALID_DATABASE_URL, "pool settings must be positive"
            )
        if not self.schema or not self.schema.isidentifier():
            raise EnterpriseDatabaseConfigError(ERROR_INVALID_DATABASE_URL, "schema must be an identifier")

    @property
    def safe_url(self) -> str:
        return redact_database_url(self.url)

    def describe(self) -> dict[str, Any]:
        """A metadata summary that is safe to print or store in a report."""
        return {
            "target": describe_database_target(self.url),
            "safe_url": self.safe_url,
            "schema": self.schema,
            "pool_pre_ping": self.pool_pre_ping,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
        }

    def __str__(self) -> str:
        return self.safe_url

    def __repr__(self) -> str:
        return (
            f"EnterpriseDatabaseConfig(safe_url={self.safe_url!r}, schema={self.schema!r}, "
            f"pool_pre_ping={self.pool_pre_ping!r})"
        )


def _parse_postgresql_url(url: str):
    if not isinstance(url, str) or not url.strip():
        raise EnterpriseDatabaseConfigError(
            ERROR_MISSING_DATABASE_URL,
            f"a database URL is required; pass one explicitly or set {DATABASE_URL_ENV_VAR}",
        )
    try:
        parsed = make_url(url)
    except Exception as exc:  # noqa: BLE001
        raise EnterpriseDatabaseConfigError(
            ERROR_INVALID_DATABASE_URL, "database URL is not a valid SQLAlchemy URL"
        ) from None
    if parsed.get_backend_name() != "postgresql":
        raise EnterpriseDatabaseConfigError(
            ERROR_NOT_A_POSTGRESQL_URL,
            "only PostgreSQL URLs are supported by the Enterprise Lab persistence baseline",
            details={"backend": parsed.get_backend_name()},
        )
    driver = parsed.get_driver_name()
    if driver != "psycopg":
        raise EnterpriseDatabaseConfigError(
            ERROR_NOT_A_POSTGRESQL_URL,
            "the PostgreSQL URL must select the Psycopg 3 driver, for example postgresql+psycopg://",
            details={"driver": driver},
        )
    return parsed


def resolve_database_url(
    url: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the URL from an explicit argument or the declared environment variable.

    Nothing else is consulted: no configuration file, no ``.env``, no default.
    """
    if url is not None and str(url).strip():
        return str(url)
    source = os.environ if environ is None else environ
    from_environment = source.get(DATABASE_URL_ENV_VAR)
    if from_environment is not None and from_environment.strip():
        return from_environment
    raise EnterpriseDatabaseConfigError(
        ERROR_MISSING_DATABASE_URL,
        f"no database URL supplied; pass one explicitly or set {DATABASE_URL_ENV_VAR}",
        details={"environment_variable": DATABASE_URL_ENV_VAR},
    )


def load_database_config(
    url: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    schema: str = POSTGRESQL_SCHEMA,
    echo: bool = False,
) -> EnterpriseDatabaseConfig:
    """Build a validated configuration object without opening any connection."""
    return EnterpriseDatabaseConfig(url=resolve_database_url(url, environ=environ), schema=schema, echo=echo)


def create_engine_from_config(
    config: EnterpriseDatabaseConfig,
    *,
    engine_factory: Any = None,
) -> Engine:
    """Create a synchronous SQLAlchemy engine for Psycopg 3.

    ``pool_pre_ping`` is enabled so a dropped connection is detected instead of
    being handed to a caller. Nothing is connected here: SQLAlchemy connects on
    first use, so this function is safe to call during configuration.
    """
    factory = engine_factory or sqlalchemy.create_engine
    return factory(
        config.url,
        echo=config.echo,
        poolclass=QueuePool,
        pool_pre_ping=config.pool_pre_ping,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout_seconds,
        connect_args={"application_name": config.application_name},
    )


def create_enterprise_engine(
    url: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    schema: str = POSTGRESQL_SCHEMA,
    echo: bool = False,
    engine_factory: Any = None,
) -> Engine:
    """Resolve configuration and return an engine without connecting."""
    config = load_database_config(url, environ=environ, schema=schema, echo=echo)
    return create_engine_from_config(config, engine_factory=engine_factory)


def validate_offline_dialect(url: str) -> str:
    """Confirm the URL maps to the SQLAlchemy Psycopg 3 dialect, without connecting."""
    parsed = _parse_postgresql_url(url)
    return f"{parsed.get_backend_name()}+{parsed.get_driver_name()}"


__all__ = [
    "ALEMBIC_VERSION_TABLE",
    "DATABASE_URL_ENV_VAR",
    "EnterpriseDatabaseConfig",
    "EnterpriseDatabaseConfigError",
    "ERROR_INVALID_DATABASE_URL",
    "ERROR_MISSING_DATABASE_URL",
    "ERROR_NOT_A_POSTGRESQL_URL",
    "ERROR_UNSAFE_MIGRATION_TARGET",
    "POSTGRESQL_SCHEMA",
    "REDACTED",
    "create_engine_from_config",
    "create_enterprise_engine",
    "describe_database_target",
    "load_database_config",
    "redact_database_url",
    "resolve_database_url",
    "validate_offline_dialect",
]
