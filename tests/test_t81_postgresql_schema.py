"""T81 PostgreSQL schema, configuration and mapping contract tests.

These tests are fully offline: they import the optional PostgreSQL boundary, which
requires SQLAlchemy/Alembic/Psycopg to be installed, but they never connect to a
database, never read a research file and never write the repository tree.
"""
from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import unittest
from dataclasses import fields as dataclass_fields
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, PrimaryKeyConstraint, UniqueConstraint

from steelai.enterprise_lab.adapters.postgresql import schema as schema_module
from steelai.enterprise_lab.adapters.postgresql.config import (
    DATABASE_URL_ENV_VAR,
    ERROR_INVALID_DATABASE_URL,
    ERROR_MISSING_DATABASE_URL,
    ERROR_NOT_A_POSTGRESQL_URL,
    ALEMBIC_VERSION_TABLE,
    POSTGRESQL_SCHEMA,
    REDACTED,
    EnterpriseDatabaseConfig,
    EnterpriseDatabaseConfigError,
    create_engine_from_config,
    load_database_config,
    redact_database_url,
    resolve_database_url,
    validate_offline_dialect,
)
from steelai.enterprise_lab.adapters.postgresql.constraints import (
    CONTENT_DIGEST_REGEX,
    DELIVERY_STATUS_VALUES,
    EVIDENCE_CLASS_VALUES,
    GOVERNANCE_STATE_VALUES,
    JOB_STATE_VALUES,
    NAMING_CONVENTION,
    RELATIVE_PATH_BLOCKED_SEGMENTS,
    RESULT_LEVEL_VALUES,
    SHA256_LOWERCASE_REGEX,
)
from steelai.enterprise_lab.adapters.postgresql.mapping import ROW_BUILDERS, TABLE_MAPPINGS
from steelai.enterprise_lab.domain.models import (
    EvidenceClass,
    GovernanceState,
    JobState,
    ResultLevel,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "steelai" / "enterprise_lab"
POSTGRES_PACKAGE = PACKAGE / "adapters" / "postgresql"
PYTHON = Path(sys.executable)

EXPECTED_TABLES = {
    "workflow_runs",
    "artifact_references",
    "audit_events",
    "outbox_events",
    "background_jobs",
}

#: The Alembic version table stores ``version_num`` as ``VARCHAR(32)``.
ALEMBIC_VERSION_NUM_WIDTH = 32

#: Placeholder URL whose password contains characters that must never survive
#: redaction. The password is percent-encoded, as a valid URL requires.
SPECIAL_PASSWORD = "p%40ss%3Aw%2Frd%3F%23%5B%5D%27%22%25%26%3D"
SPECIAL_PASSWORD_DECODED = "p@ss:w/rd?#[]'\"%&="
SPECIAL_URL = (
    f"postgresql+psycopg://steelai_user:{SPECIAL_PASSWORD}@db.internal:5432/steelai_enterprise_test"
    "?sslmode=require"
)

FORBIDDEN_RUNTIME_MODULES = ("sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg")

FINGERPRINT_AREAS = ("data/processed", "config")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.add("." * node.level + (node.module or ""))
            elif node.module:
                modules.add(node.module)
    return modules


def _tree_fingerprint() -> dict[str, str]:
    fingerprint: dict[str, str] = {}
    for area in FINGERPRINT_AREAS:
        base = ROOT / area
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            fingerprint[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return fingerprint


class SchemaStructureTests(unittest.TestCase):
    """Requirement A1-A4: the expected tables, schema, names and constraints."""

    def test_metadata_contains_exactly_the_five_business_tables(self) -> None:
        self.assertEqual(set(schema_module.schema_table_names()), EXPECTED_TABLES)
        self.assertEqual(len(schema_module.metadata.tables), len(EXPECTED_TABLES))

    def test_every_table_lives_in_the_dedicated_schema(self) -> None:
        for name in EXPECTED_TABLES:
            self.assertEqual(schema_module.table(name).schema, POSTGRESQL_SCHEMA)
        self.assertEqual(schema_module.metadata.schema, POSTGRESQL_SCHEMA)
        self.assertEqual(POSTGRESQL_SCHEMA, "steelai_enterprise")

    def test_every_constraint_and_index_has_a_stable_name(self) -> None:
        expected = {
            "workflow_runs": {
                "pk_workflow_runs",
                "uq_workflow_runs_idempotency_key",
                "ck_workflow_runs_request_digest_lowercase_hex",
                "ck_workflow_runs_content_digest_format",
                "ck_workflow_runs_state_declared",
                "ck_workflow_runs_result_level_declared",
                "ck_workflow_runs_evidence_class_declared",
                "ck_workflow_runs_revision_positive",
            },
            "artifact_references": {
                "pk_artifact_references",
                "uq_artifact_references_relative_path",
                "ck_artifact_references_sha256_lowercase_hex",
                "ck_artifact_references_relative_path_posix",
                "fk_artifact_references_run_id_workflow_runs",
            },
            "audit_events": {
                "pk_audit_events",
                "uq_audit_events_sequence",
                "ck_audit_events_sequence_positive",
                "ck_audit_events_revision_positive",
                "ck_audit_events_object_digest_format",
                "fk_audit_events_run_id_workflow_runs",
            },
            "outbox_events": {
                "pk_outbox_events",
                "uq_outbox_events_run_id_sequence",
                "ck_outbox_events_sequence_positive",
                "ck_outbox_events_delivery_status_declared",
                "ck_outbox_events_payload_is_json_object",
                "ck_outbox_events_attempts_non_negative",
                "fk_outbox_events_run_id_workflow_runs",
            },
            "background_jobs": {
                "pk_background_jobs",
                "uq_background_jobs_idempotency_key",
                "ck_background_jobs_request_digest_lowercase_hex",
                "ck_background_jobs_payload_digest_lowercase_hex",
                "ck_background_jobs_state_declared",
                "ck_background_jobs_attempts_positive",
                "ck_background_jobs_max_attempts_positive",
                "ck_background_jobs_attempts_within_limit",
                "fk_background_jobs_run_id_workflow_runs",
            },
        }
        for table_name, names in expected.items():
            with self.subTest(table=table_name):
                self.assertEqual({c.name for c in schema_module.table(table_name).constraints}, names)
        expected_indexes = {
            "ix_workflow_runs_project_id",
            "ix_workflow_runs_task_id",
            "ix_workflow_runs_state",
            "ix_workflow_runs_created_at",
            "ix_artifact_references_run_id",
            "ix_audit_events_run_id",
            "ix_outbox_events_delivery_status_available_at",
            "ix_background_jobs_state_created_at",
        }
        actual_indexes = {
            index.name for table in schema_module.metadata.tables.values() for index in table.indexes
        }
        self.assertEqual(actual_indexes, expected_indexes)
        for index in (
            index for table in schema_module.metadata.tables.values() for index in table.indexes
        ):
            self.assertIsInstance(index, Index)
            self.assertLessEqual(len(index.name), 63)

    def test_primary_and_foreign_keys_match_the_domain_identity(self) -> None:
        expectations = {
            "workflow_runs": ("run_id", ()),
            "artifact_references": ("artifact_id", ("run_id",)),
            "audit_events": ("audit_id", ("run_id",)),
            "outbox_events": ("event_id", ("run_id",)),
            "background_jobs": ("job_id", ("run_id",)),
        }
        for table_name, (primary_key, foreign_keys) in expectations.items():
            table = schema_module.table(table_name)
            with self.subTest(table=table_name):
                self.assertEqual([column.name for column in table.primary_key.columns], [primary_key])
                actual = sorted(
                    column.name
                    for constraint in table.constraints
                    if isinstance(constraint, ForeignKeyConstraint)
                    for column in constraint.columns
                )
                self.assertEqual(actual, sorted(foreign_keys))
                for constraint in table.constraints:
                    if isinstance(constraint, ForeignKeyConstraint):
                        for element in constraint.elements:
                            self.assertEqual(element.column.table.schema, POSTGRESQL_SCHEMA)
                            self.assertEqual(element.target_fullname.split(".")[1], "workflow_runs")

    def test_declared_check_regexes_and_value_sets(self) -> None:
        self.assertEqual(SHA256_LOWERCASE_REGEX, "^[0-9a-f]{64}$")
        self.assertEqual(CONTENT_DIGEST_REGEX, "^[a-z]{2,8}_[0-9a-f]{32,64}$")
        self.assertEqual(set(GOVERNANCE_STATE_VALUES), {state.value for state in GovernanceState})
        self.assertEqual(set(RESULT_LEVEL_VALUES), {level.value for level in ResultLevel})
        self.assertEqual(set(EVIDENCE_CLASS_VALUES), {item.value for item in EvidenceClass})
        self.assertEqual(set(JOB_STATE_VALUES), {state.value for state in JobState})
        self.assertEqual(
            tuple(DELIVERY_STATUS_VALUES), ("pending", "publishing", "published", "failed")
        )
        self.assertEqual(RELATIVE_PATH_BLOCKED_SEGMENTS, (".", ".."))
        # The schema module re-exports the shared contract constants.
        self.assertEqual(schema_module.SHA256_LOWERCASE_REGEX, SHA256_LOWERCASE_REGEX)
        self.assertEqual(schema_module.NAMING_CONVENTION, NAMING_CONVENTION)

    def test_key_checks_are_present_with_the_expected_semantics(self) -> None:
        def check_sql(table_name: str, constraint_name: str) -> str:
            for constraint in schema_module.table(table_name).constraints:
                if isinstance(constraint, CheckConstraint) and constraint.name == constraint_name:
                    return str(constraint.sqltext)
            raise AssertionError(f"{constraint_name} missing on {table_name}")

        self.assertIn("revision >= 1", check_sql("workflow_runs", "ck_workflow_runs_revision_positive"))
        self.assertIn("state IN (", check_sql("workflow_runs", "ck_workflow_runs_state_declared"))
        self.assertIn(
            "^[0-9a-f]{64}$",
            check_sql("workflow_runs", "ck_workflow_runs_request_digest_lowercase_hex"),
        )
        self.assertIn("attempts >= 1", check_sql("background_jobs", "ck_background_jobs_attempts_positive"))
        self.assertIn(
            "attempts <= max_attempts",
            check_sql("background_jobs", "ck_background_jobs_attempts_within_limit"),
        )
        self.assertIn(
            "jsonb_typeof(payload) = 'object'",
            check_sql("outbox_events", "ck_outbox_events_payload_is_json_object"),
        )
        self.assertIn(
            "delivery_status IN (",
            check_sql("outbox_events", "ck_outbox_events_delivery_status_declared"),
        )

    def test_relative_path_check_rejects_every_unsafe_shape(self) -> None:
        relative_path_sql = None
        for constraint in schema_module.table("artifact_references").constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name == (
                "ck_artifact_references_relative_path_posix"
            ):
                relative_path_sql = str(constraint.sqltext)
        self.assertIsNotNone(relative_path_sql)
        # Bare "." and ".." are blocked explicitly, not only as path components.
        self.assertIn("relative_path NOT IN ('.', '..')", relative_path_sql)
        for fragment in (
            "relative_path <> ''",
            "relative_path NOT LIKE '/%'",
            "strpos(relative_path, ':') = 0",
            "relative_path NOT LIKE '../%'",
            "relative_path NOT LIKE './%'",
            "relative_path NOT LIKE '%/../%'",
            "relative_path NOT LIKE '%/./%'",
            "relative_path NOT LIKE '%/..'",
            "relative_path NOT LIKE '%/.'",
            "relative_path NOT LIKE '%//%'",
        ):
            self.assertIn(fragment, relative_path_sql)
        self.assertIn("'%\\\\%'", relative_path_sql)

    def test_no_postgresql_native_enum_is_used_for_states(self) -> None:
        for table in schema_module.metadata.tables.values():
            for column in table.columns:
                self.assertNotIn(
                    "ENUM",
                    str(column.type).upper(),
                    f"{table.name}.{column.name} must stay a string column with a CHECK constraint",
                )
        source = (POSTGRES_PACKAGE / "schema.py").read_text(encoding="utf-8")
        self.assertNotIn("sa.Enum", source)
        self.assertNotIn("create_type", source)

    def test_indexes_stay_minimal_and_expected(self) -> None:
        counts = {table.name: len(table.indexes) for table in schema_module.metadata.tables.values()}
        self.assertEqual(
            counts,
            {
                "workflow_runs": 4,
                "artifact_references": 1,
                "audit_events": 1,
                "outbox_events": 1,
                "background_jobs": 1,
            },
        )


class MappingContractTests(unittest.TestCase):
    """Requirement A14: the schema covers the domain objects completely."""

    def test_every_persisted_domain_field_is_mapped(self) -> None:
        from steelai.enterprise_lab.domain.models import (
            ArtifactReference,
            AuditEvent,
            BackgroundJob,
            DomainEvent,
            WorkflowRun,
        )

        domain_objects = {
            "WorkflowRun": WorkflowRun,
            "ArtifactReference": ArtifactReference,
            "AuditEvent": AuditEvent,
            "DomainEvent": DomainEvent,
            "BackgroundJob": BackgroundJob,
        }
        for mapping in TABLE_MAPPINGS:
            with self.subTest(table=mapping.table_name):
                table = schema_module.table(mapping.table_name)
                mapped_columns = set(mapping.domain_fields())
                mapped_attributes = set(mapping.domain_attributes())
                domain = domain_objects[mapping.domain_object]
                available = _domain_attribute_names(domain)
                self.assertEqual(
                    sorted(mapped_attributes - available), [], f"{mapping.domain_object} attributes missing"
                )
                for field in dataclass_fields(domain):
                    self.assertIn(
                        field.name,
                        mapped_columns,
                        f"{mapping.domain_object}.{field.name} is not mapped to {mapping.table_name}",
                    )
                self.assertTrue(mapped_columns.issubset({column.name for column in table.columns}))
                infrastructure = set(mapping.infrastructure_fields)
                self.assertEqual(mapped_columns & infrastructure, set())
                self.assertEqual(
                    mapped_columns | infrastructure,
                    {column.name for column in table.columns},
                )

    def test_infrastructure_only_columns_are_limited_to_the_outbox(self) -> None:
        from steelai.enterprise_lab.domain.models import (
            ArtifactReference,
            AuditEvent,
            BackgroundJob,
            DomainEvent,
            WorkflowRun,
        )

        domain_objects = {
            "WorkflowRun": WorkflowRun,
            "ArtifactReference": ArtifactReference,
            "AuditEvent": AuditEvent,
            "DomainEvent": DomainEvent,
            "BackgroundJob": BackgroundJob,
        }
        for mapping in TABLE_MAPPINGS:
            infrastructure = set(mapping.infrastructure_fields)
            with self.subTest(table=mapping.table_name):
                self.assertEqual(infrastructure, INFRASTRUCTURE_COLUMNS.get(mapping.table_name, set()))
                available = _domain_attribute_names(domain_objects[mapping.domain_object])
                self.assertEqual(sorted(set(mapping.domain_fields()) - available), [])
                for column in infrastructure:
                    self.assertNotIn(column, available)
        self.assertEqual(
            {mapping.table_name for mapping in TABLE_MAPPINGS if mapping.infrastructure_fields},
            {"outbox_events"},
        )
        self.assertEqual(
            {mapping.table_name for mapping in TABLE_MAPPINGS if mapping.adaptation_fields},
            {"outbox_events"},
        )

    def test_row_builders_produce_only_known_column_values(self) -> None:
        from steelai.enterprise_lab.domain.models import (
            ArtifactReference,
            AuditEvent,
            BackgroundJob,
            DomainEvent,
            WorkflowRun,
        )

        run = WorkflowRun.create(
            run_id="run_t81demo001",
            project_id="PRJ-T81-DEMO",
            task_id="task_t81demo001",
            idempotency_key="idem-t81-demo-001",
            request_digest="a" * 64,
        )
        reference = ArtifactReference.create(
            relative_path="enterprise/demo/manifest.json",
            sha256="b" * 64,
            artifact_type="governance_manifest",
            artifact_version="v1",
            run_id=run.run_id,
        )
        audit = AuditEvent.create(
            sequence=1,
            run_id=run.run_id,
            action="run-registered",
            actor_role="human",
            actor_id="owner",
            summary="named human review of synthetic metadata",
            object_type="workflow_run",
            object_id=run.run_id,
            object_revision=1,
            object_digest=run.content_digest,
        )
        event = DomainEvent.create(
            event_type="enterprise.workflow_run.registered",
            run_id=run.run_id,
            sequence=1,
            payload={"state": "draft", "revision": 1, "summary": "workflow run registered"},
        )
        job = BackgroundJob.create(
            job_id="job_t81demo001",
            job_type="artifact-verify",
            run_id=run.run_id,
            idempotency_key="idem-job-t81-001",
            payload_digest="c" * 64,
        )
        rows = {
            "workflow_runs": ROW_BUILDERS["workflow_runs"](run),
            "artifact_references": ROW_BUILDERS["artifact_references"](reference),
            "audit_events": ROW_BUILDERS["audit_events"](audit),
            "outbox_events": ROW_BUILDERS["outbox_events"](event),
            "background_jobs": ROW_BUILDERS["background_jobs"](job),
        }
        for table_name, row in rows.items():
            with self.subTest(table=table_name):
                table = schema_module.table(table_name)
                self.assertEqual(set(row), {column.name for column in table.columns})
                for column in (item for item in table.columns if not item.nullable):
                    self.assertIsNotNone(row[column.name], f"{table_name}.{column.name} must be filled")
                    self.assertNotEqual(row[column.name], "", f"{table_name}.{column.name} must not be empty")
        self.assertEqual(rows["outbox_events"]["delivery_status"], "pending")
        self.assertEqual(rows["outbox_events"]["attempts"], 0)
        self.assertEqual(rows["background_jobs"]["request_digest"], job.request_digest())
        self.assertEqual(rows["workflow_runs"]["request_digest"], "a" * 64)

    def test_outbox_payload_stays_redacted(self) -> None:
        from steelai.enterprise_lab.domain.models import DomainEvent

        event = DomainEvent.create(
            event_type="enterprise.workflow_run.registered",
            run_id="run_t81demo001",
            sequence=1,
            payload={"state": "draft", "revision": 1, "summary": "workflow run registered"},
        )
        row = ROW_BUILDERS["outbox_events"](event)
        self.assertIsInstance(row["payload"], dict)
        self.assertEqual(set(row["payload"]), {"state", "revision", "summary"})


#: Columns that are the only dispatcher-infrastructure columns in the schema.
#: Everything else maps to a real domain attribute: ``payload`` is an adaptation of
#: the DomainEvent payload stored as JSONB, and ``request_digest`` is backed by
#: ``BackgroundJob.request_digest()``.
INFRASTRUCTURE_COLUMNS = {
    "outbox_events": {
        "delivery_status",
        "attempts",
        "available_at",
        "published_at",
        "last_error_code",
    },
}


def _domain_attribute_names(domain_object: type) -> set[str]:
    """Return the persisted field names of a frozen dataclass domain object.

    Frozen dataclasses keep their field descriptors in ``__dataclass_fields__``
    rather than as class attributes, so a plain ``hasattr`` check is not enough.
    The derived ``request_digest()`` method is included because the job table
    persists it.
    """
    names = set(domain_object.__dataclass_fields__)
    if hasattr(domain_object, "request_digest"):
        names.add("request_digest")
    return names


class DatabaseConfigurationTests(unittest.TestCase):
    """Requirement A9-A10: explicit configuration, redaction and fail-closed."""

    def test_missing_url_fails_closed_without_any_default(self) -> None:
        with self.assertRaises(EnterpriseDatabaseConfigError) as captured:
            resolve_database_url(None, environ={})
        self.assertEqual(captured.exception.code, ERROR_MISSING_DATABASE_URL)
        self.assertIn(DATABASE_URL_ENV_VAR, captured.exception.message)
        with self.assertRaises(EnterpriseDatabaseConfigError):
            load_database_config(None, environ={})

    def test_url_is_only_read_from_the_argument_or_the_declared_variable(self) -> None:
        explicit = "postgresql+psycopg://user:pw@localhost:5432/steelai_enterprise_test"
        self.assertEqual(resolve_database_url(explicit, environ={}), explicit)
        self.assertEqual(
            resolve_database_url(None, environ={DATABASE_URL_ENV_VAR: explicit}), explicit
        )
        with self.assertRaises(EnterpriseDatabaseConfigError) as captured:
            resolve_database_url(None, environ={"DATABASE_URL": explicit, "PGURL": explicit})
        self.assertEqual(captured.exception.code, ERROR_MISSING_DATABASE_URL)

    def test_non_postgresql_and_wrong_driver_urls_are_refused(self) -> None:
        for url, code in (
            ("sqlite:///demo.db", ERROR_NOT_A_POSTGRESQL_URL),
            ("postgresql://user:pw@localhost:5432/steelai_test", ERROR_NOT_A_POSTGRESQL_URL),
            ("postgresql+psycopg2://user:pw@localhost:5432/steelai_test", ERROR_NOT_A_POSTGRESQL_URL),
            ("postgresql+asyncpg://user:pw@localhost:5432/steelai_test", ERROR_NOT_A_POSTGRESQL_URL),
            ("postgresql+psycopg://user:pw@localhost", ERROR_INVALID_DATABASE_URL),
        ):
            with self.subTest(url=url), self.assertRaises(EnterpriseDatabaseConfigError) as captured:
                EnterpriseDatabaseConfig(url=url)
            self.assertEqual(captured.exception.code, code)

    def test_psycopg3_dialect_is_required_and_detected(self) -> None:
        self.assertEqual(
            validate_offline_dialect("postgresql+psycopg://u:p@localhost:5432/steelai_enterprise_test"),
            "postgresql+psycopg",
        )

    def test_redaction_removes_passwords_including_special_characters(self) -> None:
        redacted = redact_database_url(SPECIAL_URL)
        self.assertNotIn(SPECIAL_PASSWORD, redacted)
        self.assertNotIn(SPECIAL_PASSWORD_DECODED, redacted)
        self.assertNotIn("steelai_user", redacted)
        self.assertNotIn("db.internal", redacted)
        self.assertIn(REDACTED, redacted)
        self.assertIn("steelai_enterprise_test", redacted)
        for fragment in ("p%40ss", "s%3Aw", "sslmode=require", "db.internal"):
            self.assertNotIn(fragment, redacted)
        self.assertEqual(redact_database_url(""), "<empty>")
        self.assertEqual(redact_database_url("not a url"), "<unparsable database url>")

    def test_config_repr_and_errors_never_leak_credentials(self) -> None:
        config = EnterpriseDatabaseConfig(url=SPECIAL_URL)
        self.assertNotIn(SPECIAL_PASSWORD, str(config))
        self.assertNotIn(SPECIAL_PASSWORD, repr(config))
        self.assertNotIn(SPECIAL_PASSWORD, str(config.describe()))
        self.assertNotIn("steelai_user", config.describe()["safe_url"])
        self.assertNotIn("db.internal", config.describe()["safe_url"])
        self.assertEqual(config.describe()["target"]["database"], "steelai_enterprise_test")
        with self.assertRaises(EnterpriseDatabaseConfigError) as captured:
            EnterpriseDatabaseConfig(url="postgresql+psycopg://user:secret@localhost:5432")
        self.assertNotIn("secret", str(captured.exception))
        self.assertNotIn("secret", str(captured.exception.to_dict()))

    def test_engine_factory_is_explicit_and_never_connects(self) -> None:
        captured: dict[str, object] = {}

        def fake_engine_factory(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return "engine-placeholder"

        config = load_database_config(
            "postgresql+psycopg://user:pw@localhost:5432/steelai_enterprise_test", environ={}
        )
        engine = create_engine_from_config(config, engine_factory=fake_engine_factory)
        self.assertEqual(engine, "engine-placeholder")
        self.assertEqual(captured["url"], config.url)
        self.assertTrue(captured["pool_pre_ping"])
        self.assertEqual(captured["connect_args"], {"application_name": "steelai-enterprise-lab"})

    def test_importing_config_opens_no_connection(self) -> None:
        code = (
            "import sys\n"
            "import steelai.enterprise_lab.adapters.postgresql.config as config\n"
            "created = []\n"
            "import sqlalchemy\n"
            "sqlalchemy.create_engine = lambda *a, **k: created.append(a)\n"
            "config.load_database_config('postgresql+psycopg://u:p@localhost:5432/steelai_enterprise_test', environ={})\n"
            "print(len(created))\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "0")

    def test_version_table_and_schema_are_declared_centrally(self) -> None:
        self.assertEqual(ALEMBIC_VERSION_TABLE, "alembic_version_enterprise")
        ini = (ROOT / "alembic-enterprise.ini").read_text(encoding="utf-8")
        self.assertIn(f"version_table = {ALEMBIC_VERSION_TABLE}", ini)
        self.assertIn(f"version_table_schema = {POSTGRESQL_SCHEMA}", ini)
        # The version_num column is a VARCHAR(32), so revision ids stay short.
        self.assertEqual(ALEMBIC_VERSION_NUM_WIDTH, 32)


class IsolationTests(unittest.TestCase):
    """Requirement A11-A13: the optional boundary never reaches the default app."""

    def test_importing_the_lab_does_not_load_database_frameworks(self) -> None:
        code = (
            "import sys\n"
            "import steelai.enterprise_lab  # noqa: F401\n"
            "import steelai.enterprise_lab.adapters.memory  # noqa: F401\n"
            f"print(','.join(m for m in {FORBIDDEN_RUNTIME_MODULES!r} if m in sys.modules))\n"
            "print('steelai.enterprise_lab.adapters.postgresql' in sys.modules)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2, completed.stdout)
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "False")

    def test_default_application_does_not_import_the_postgresql_boundary(self) -> None:
        code = (
            "import sys\n"
            "import app  # noqa: F401\n"
            f"loaded = [m for m in {FORBIDDEN_RUNTIME_MODULES!r} if m in sys.modules]\n"
            "print(','.join(loaded))\n"
            "print('steelai.enterprise_lab.adapters.postgresql' in sys.modules)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2, completed.stdout)
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "False")

    def test_inner_layers_have_no_database_framework_dependency(self) -> None:
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            parts = path.relative_to(PACKAGE).parts
            layer = parts[0] if len(parts) > 1 else ""
            if layer not in {"domain", "application", "ports"}:
                continue
            for module in _imported_modules(path):
                if module.split(".")[0] in FORBIDDEN_RUNTIME_MODULES:
                    offenders.append(f"{path.name}: {module}")
        self.assertEqual(offenders, [])

    def test_lab_entry_points_do_not_pre_import_the_postgresql_package(self) -> None:
        for relative in ("__init__.py", "adapters/__init__.py"):
            path = PACKAGE / relative
            with self.subTest(file=relative):
                modules = _imported_modules(path)
                self.assertFalse(
                    any("postgresql" in module for module in modules),
                    f"{relative} must not import the PostgreSQL boundary",
                )

    def test_memory_adapters_still_work_without_touching_the_database(self) -> None:
        from steelai.enterprise_lab.adapters.memory import MemoryUnitOfWorkFactory

        factory = MemoryUnitOfWorkFactory()
        with factory.unit_of_work() as unit:
            self.assertEqual(unit.runs.list_runs(), [])
            unit.rollback()

    def test_research_data_and_method_registry_are_unchanged(self) -> None:
        before = _tree_fingerprint()
        self.assertIn("config/thermal_softening_method_registry_v1.0.json", before)
        self.assertIn("data/processed/thermal_simulation_features.csv", before)
        self.assertEqual(_tree_fingerprint(), before)


if __name__ == "__main__":
    unittest.main()
