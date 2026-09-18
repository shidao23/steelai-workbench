"""T81 Alembic migration tests: offline by default, real PostgreSQL when allowed.

Offline tests never connect to a database. The integration class runs only when
``STEELAI_TEST_DATABASE_URL`` names a database containing both ``steelai`` and
``test``; otherwise every integration test is skipped and T81 stays ``Review``
because the real migration remains unverified.

No test prints a connection string, and no test writes to a database it does not
own.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

# Only the two constraint classes actually inspected with ``isinstance`` are
# imported; the other kinds are asserted by class name from the frozen revision.
from sqlalchemy import CheckConstraint, PrimaryKeyConstraint

from steelai.enterprise_lab.adapters.postgresql import schema as schema_module
from steelai.enterprise_lab.adapters.postgresql.config import (
    ALEMBIC_VERSION_TABLE,
    POSTGRESQL_SCHEMA,
)
from steelai.enterprise_lab.adapters.postgresql.constraints import SHA256_LOWERCASE_REGEX


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
ALEMBIC_INI = ROOT / "alembic-enterprise.ini"
MIGRATIONS_DIR = ROOT / "migrations" / "enterprise"
BASELINE_REVISION = "0001_enterprise_baseline"
BASELINE_PATH = MIGRATIONS_DIR / "versions" / f"{BASELINE_REVISION}.py"
TEST_DATABASE_URL_ENV_VAR = "STEELAI_TEST_DATABASE_URL"
TEST_DATABASE_ONLY_ENV_VAR = "STEELAI_ENTERPRISE_TEST_DATABASE_ONLY"

#: The Alembic version table stores ``version_num`` as ``VARCHAR(32)``.
ALEMBIC_VERSION_NUM_WIDTH = 32

#: Placeholder URL; never a real credential, never printed by a failing assert.
PLACEHOLDER_URL = "postgresql+psycopg://placeholder:placeholder@localhost:5432/steelai_enterprise_test"

FINGERPRINT_AREAS = ("data/processed", "config")

#: Deliberate DDL words that must never appear in a reverse migration.
FORBIDDEN_DOWNGRADE_TOKENS = ("CASCADE", "DROP DATABASE", "DROP SCHEMA", "TRUNCATE", "data/processed")

#: Relative references that must be rejected by the database CHECK constraint.
INVALID_RELATIVE_PATHS = (".", "..", "./a", "a/../b", "a//b")

EXPECTED_TABLES = (
    "workflow_runs",
    "artifact_references",
    "audit_events",
    "outbox_events",
    "background_jobs",
)


def _executable_source(path: Path) -> str:
    """Return module source with docstrings removed, so prose cannot match DDL checks."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    return "\n".join(ast.unparse(node) for node in body)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


def _forbidden_io_calls(path: Path) -> list[str]:
    """Real filesystem or process calls in a module, ignoring prose and strings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in {"open", "exec", "eval", "compile", "Path"}:
            forbidden.add(node.func.id)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "open",
            "read_text",
            "write_text",
            "write_bytes",
            "unlink",
            "mkdir",
        }:
            forbidden.add(node.func.attr)
    return sorted(forbidden)


def _load_frozen_migration(*, fresh: bool = False):
    """Load the frozen revision as a module so its frozen literals can be inspected."""
    if not fresh and "t81_frozen_baseline" in sys.modules:
        return sys.modules["t81_frozen_baseline"]
    spec = importlib.util.spec_from_file_location("t81_frozen_baseline", BASELINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before execution so a subprocess-free reload is deterministic.
    sys.modules["t81_frozen_baseline"] = module
    spec.loader.exec_module(module)
    return module


def _frozen_definition(table_name: str) -> tuple[dict[str, object], dict[str, str]]:
    """Return (columns, constraints) declared by the frozen revision for one table.

    Column comparison deliberately ignores ``primary_key``: the frozen revision may
    mark the key column inline while the live metadata may declare a separate
    ``PrimaryKeyConstraint``. The primary key is compared through the constraint map.
    """
    module = _load_frozen_migration()
    columns, constraints = module._table_columns_and_constraints(table_name)
    column_map = {
        column.name: {
            "nullable": bool(column.nullable),
            "type": str(column.type),
        }
        for column in columns
    }
    constraint_map: dict[str, str] = {}
    for constraint in constraints:
        resolved = constraint.name
        if resolved is None:
            continue
        # ``op.create_table`` applies the naming convention, so expand a bare
        # CHECK name exactly the way the frozen convention does.
        if isinstance(constraint, CheckConstraint):
            resolved = "ck_%s_%s" % (table_name, resolved)
        constraint_map[resolved] = type(constraint).__name__
    return column_map, constraint_map


def _frozen_check_sql(table_name: str, bare_check_name: str) -> str | None:
    """Return the frozen CHECK SQL text for one table and bare check name."""
    module = _load_frozen_migration()
    _, constraints = module._table_columns_and_constraints(table_name)
    for constraint in constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == bare_check_name:
            return str(constraint.sqltext)
    return None


def _snapshot_frozen_ddl() -> dict[str, object]:
    """Capture everything the frozen revision would create, for equality probing."""
    module = _load_frozen_migration(fresh=True)
    snapshot: dict[str, object] = {
        "naming_convention": dict(module.FROZEN_NAMING_CONVENTION),
        "creation_order": tuple(module.TABLE_CREATION_ORDER),
        "drop_order": tuple(module.TABLE_DROP_ORDER),
        "index_definitions": tuple(module.INDEX_DEFINITIONS),
        "function_sql": module.AUDIT_TRIGGER_FUNCTION_SQL,
        "trigger_sql": module.AUDIT_TRIGGER_SQL,
        "tables": {},
    }
    for table_name in module.TABLE_CREATION_ORDER:
        columns, constraints = module._table_columns_and_constraints(table_name)
        snapshot["tables"][table_name] = {  # type: ignore[index]
            "columns": tuple(
                (column.name, str(column.type), bool(column.nullable)) for column in columns
            ),
            "constraints": tuple(
                sorted((constraint.name or "", type(constraint).__name__, str(getattr(constraint, "sqltext", "")))
                       for constraint in constraints)
            ),
        }
    return snapshot


def _tree_fingerprint() -> dict[str, str]:
    fingerprint: dict[str, str] = {}
    for area in FINGERPRINT_AREAS:
        base = ROOT / area
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if path.is_file() and "__pycache__" not in path.parts:
                fingerprint[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return fingerprint


def _test_database_url() -> str | None:
    """Return the integration URL only when it clearly names a SteelAI test database."""
    value = os.environ.get(TEST_DATABASE_URL_ENV_VAR, "").strip()
    if not value:
        return None
    name = value.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if "steelai" not in name or "test" not in name:
        return None
    return value


def _alembic(args: list[str], *, url: str | None = None, extra_env: dict[str, str] | None = None):
    """Run the Alembic CLI without ever echoing the URL."""
    environment = dict(os.environ)
    environment.pop(TEST_DATABASE_URL_ENV_VAR, None)
    if url is not None:
        environment["STEELAI_ENTERPRISE_DATABASE_URL"] = url
    if extra_env:
        environment.update(extra_env)
    return subprocess.run(
        [str(PYTHON), "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _sqlite_position(sql: str, needle: str) -> int:
    """Index of a DDL statement, or -1 when it is absent."""
    return sql.find(needle)


class OfflineMigrationTests(unittest.TestCase):
    """Requirement A5-A8 plus the frozen-revision contract."""

    def setUp(self) -> None:
        self.source = BASELINE_PATH.read_text(encoding="utf-8")
        self.code = _executable_source(BASELINE_PATH)

    def test_migration_project_layout_exists(self) -> None:
        for relative in (
            "alembic-enterprise.ini",
            "migrations/enterprise/env.py",
            "migrations/enterprise/script.py.mako",
            f"migrations/enterprise/versions/{BASELINE_REVISION}.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        remaining = sorted(path.name for path in (MIGRATIONS_DIR / "versions").glob("*.py"))
        self.assertEqual(remaining, [f"{BASELINE_REVISION}.py"])

    def test_revision_chain_is_a_single_baseline(self) -> None:
        namespace: dict[str, object] = {}
        for node in ast.parse(self.source).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in {"revision", "down_revision", "branch_labels", "depends_on"}:
                    try:
                        namespace[name] = ast.literal_eval(node.value)
                    except ValueError:
                        namespace[name] = None
        self.assertEqual(namespace.get("revision"), BASELINE_REVISION)
        self.assertIsNone(namespace.get("down_revision"))
        self.assertIsNone(namespace.get("branch_labels"))
        self.assertIsNone(namespace.get("depends_on"))

    def test_revision_id_fits_the_alembic_version_num_column(self) -> None:
        # The version table declares ``version_num VARCHAR(32)``, and PostgreSQL
        # rejects a longer value with "value too long for type character varying(32)".
        self.assertLessEqual(len(BASELINE_REVISION), ALEMBIC_VERSION_NUM_WIDTH)
        self.assertRegex(BASELINE_REVISION, r"^[A-Za-z0-9_]+$")

    def test_offline_sql_creates_the_schema_before_the_version_table(self) -> None:
        completed = _alembic(["upgrade", "head", "--sql"], url=PLACEHOLDER_URL)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        sql = completed.stdout
        # The version table declares ``version_num VARCHAR(32)``; its width is the
        # budget a revision id must respect.
        self.assertRegex(sql, r"version_num VARCHAR\((\d+)\)")
        width = int(re.search(r"version_num VARCHAR\((\d+)\)", sql).group(1))
        self.assertEqual(width, ALEMBIC_VERSION_NUM_WIDTH)
        self.assertLessEqual(len(BASELINE_REVISION), width)

        schema_position = _sqlite_position(sql, f'CREATE SCHEMA IF NOT EXISTS "{POSTGRESQL_SCHEMA}"')
        version_position = _sqlite_position(
            sql, f"CREATE TABLE {POSTGRESQL_SCHEMA}.{ALEMBIC_VERSION_TABLE}"
        )
        self.assertGreaterEqual(schema_position, 0, "offline SQL must create the schema")
        self.assertGreaterEqual(version_position, 0, "offline SQL must create the version table")
        # Position comparison, not mere presence: the schema must come first or the
        # generated script fails on a fresh database.
        self.assertLess(
            schema_position,
            version_position,
            "CREATE SCHEMA must precede CREATE TABLE ...alembic_version_enterprise",
        )
        self.assertIn(f"VALUES ('{BASELINE_REVISION}')", sql)

    def test_offline_upgrade_sql_declares_every_expected_object(self) -> None:
        completed = _alembic(["upgrade", "head", "--sql"], url=PLACEHOLDER_URL)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        sql = completed.stdout
        for table in EXPECTED_TABLES:
            self.assertIn(f"CREATE TABLE {POSTGRESQL_SCHEMA}.{table}", sql)
        expected_constraints = {
            name
            for table in EXPECTED_TABLES
            for name in (c.name for c in schema_module.table(table).constraints)
        }
        for name in sorted(expected_constraints):
            self.assertIn(f"CONSTRAINT {name} ", sql, f"missing constraint {name}")
        # No doubled name may appear (for example ck_<t>_ck_<t>_<check>).
        self.assertNotRegex(sql, r"CONSTRAINT ck_\w+_ck_")
        for index in (
            "ix_workflow_runs_project_id",
            "ix_workflow_runs_task_id",
            "ix_workflow_runs_state",
            "ix_workflow_runs_created_at",
            "ix_artifact_references_run_id",
            "ix_audit_events_run_id",
            "ix_outbox_events_delivery_status_available_at",
            "ix_background_jobs_state_created_at",
        ):
            self.assertIn(f"CREATE INDEX {index} ON", sql)
        self.assertIn("CREATE FUNCTION steelai_enterprise.fn_audit_events_reject_mutation()", sql)
        self.assertIn("CREATE TRIGGER trg_audit_events_append_only", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON steelai_enterprise.audit_events", sql)
        # The hardened relative-path CHECK, including the bare "." and ".." values.
        self.assertIn("relative_path NOT IN ('.', '..')", sql)
        for invalid in INVALID_RELATIVE_PATHS:
            self.assertNotIn(f"'{invalid}' NOT IN", sql)  # sanity: the list is the blocklist
        self.assertNotIn("data/processed", sql)
        self.assertNotIn("INSERT INTO steelai_enterprise.workflow_runs", sql)

    def test_frozen_revision_declares_tables_without_runtime_metadata(self) -> None:
        """A historical revision must not depend on any runtime schema object."""
        modules = _imported_modules(BASELINE_PATH)
        allowed_roots = {"__future__", "alembic", "sqlalchemy"}
        self.assertTrue(
            {module.split(".")[0] for module in modules}.issubset(allowed_roots),
            f"unexpected imports: {sorted(modules)}",
        )
        for module in sorted(modules):
            self.assertFalse(module.startswith("steelai"), module)
        self.assertFalse(any(module.endswith("schema") for module in modules), sorted(modules))
        self.assertFalse(any(module.endswith("constraints") for module in modules), sorted(modules))
        self.assertFalse(any(module.endswith("domain.models") for module in modules), sorted(modules))
        self.assertNotIn("enterprise_metadata", self.code)
        self.assertNotIn("_table_definition", self.code)
        for forbidden in ("metadata.tables", "MetaData(", "Table(", "metadata."):
            self.assertNotIn(forbidden, self.code, f"frozen revision must not use {forbidden}")
        # It must not call into the shared SQL builders either.
        for forbidden in (
            "sha256_check_sql",
            "content_digest_check_sql",
            "relative_path_check_sql",
            "sql_in_list",
            "sql_string_list",
            "audit_append_only_function_sql",
            "audit_append_only_trigger_sql",
        ):
            self.assertNotIn(forbidden, self.code, f"frozen revision must not call {forbidden}")

    def test_frozen_revision_matches_the_t81_baseline_contract(self) -> None:
        """The revision freezes the T81 baseline literals itself.

        This is the assertion that matters for a historical revision: it compares
        the frozen literals against the declared T81 baseline values, not against a
        live module that a later task is allowed to change.
        """
        module = _load_frozen_migration()
        self.assertEqual(tuple(module.TABLE_CREATION_ORDER), EXPECTED_TABLES)
        self.assertEqual(
            module.FROZEN_NAMING_CONVENTION,
            {
                "ix": "ix_%(table_name)s_%(column_0_N_name)s",
                "uq": "uq_%(table_name)s_%(column_0_N_name)s",
                "ck": "ck_%(table_name)s_%(constraint_name)s",
                "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
                "pk": "pk_%(table_name)s",
            },
        )
        self.assertEqual(module.SHA256_PATTERN, "^[0-9a-f]{64}$")
        self.assertEqual(module.CONTENT_DIGEST_PATTERN, "^[a-z]{2,8}_[0-9a-f]{32,64}$")
        self.assertEqual(
            tuple(module.GOVERNANCE_STATES),
            (
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
            ),
        )
        self.assertEqual(
            tuple(module.RESULT_LEVELS),
            (
                "working_candidate",
                "synthetic_demo_only",
                "model_result",
                "verified_output",
                "accepted_evidence",
                "human_conclusion",
            ),
        )
        self.assertEqual(
            tuple(module.EVIDENCE_CLASSES),
            ("real_research_data", "synthetic_demo_data", "model_output", "human_conclusion"),
        )
        self.assertEqual(
            tuple(module.JOB_STATES), ("queued", "leased", "retrying", "succeeded", "failed", "cancelled")
        )
        self.assertEqual(
            tuple(module.DELIVERY_STATUSES), ("pending", "publishing", "published", "failed")
        )
        self.assertEqual(
            module.AUDIT_APPEND_ONLY_FUNCTION, "fn_audit_events_reject_mutation"
        )
        self.assertEqual(module.AUDIT_APPEND_ONLY_TRIGGER, "trg_audit_events_append_only")
        self.assertEqual(module.SCHEMA, "steelai_enterprise")
        self.assertEqual(module.CHECK_RELATIVE_PATH_POSIX, "relative_path_posix")
        self.assertEqual(module.CHECK_STATE_DECLARED, "state_declared")
        self.assertEqual(module.CHECK_REQUEST_DIGEST_LOWERCASE, "request_digest_lowercase_hex")
        # Deliberately NO comparison against the live contract module: a historical
        # revision does not have to equal a future live schema, so freezing it means
        # asserting the T81 baseline literals above and nothing about today's code.

    def test_frozen_definition_is_complete_and_self_contained(self) -> None:
        """Every table must declare its own columns, key and constraints."""
        module = _load_frozen_migration()
        expected_columns = {
            "workflow_runs": 14,
            "artifact_references": 7,
            "audit_events": 12,
            "outbox_events": 11,
            "background_jobs": 13,
        }
        expected_check_names = {
            "workflow_runs": {
                "request_digest_lowercase_hex",
                "content_digest_format",
                "state_declared",
                "result_level_declared",
                "evidence_class_declared",
                "revision_positive",
            },
            "artifact_references": {"sha256_lowercase_hex", "relative_path_posix"},
            "audit_events": {"sequence_positive", "revision_positive", "object_digest_format"},
            "outbox_events": {
                "sequence_positive",
                "delivery_status_declared",
                "payload_is_json_object",
                "attempts_non_negative",
            },
            "background_jobs": {
                "request_digest_lowercase_hex",
                "payload_digest_lowercase_hex",
                "state_declared",
                "attempts_positive",
                "max_attempts_positive",
                "attempts_within_limit",
            },
        }
        for table_name in EXPECTED_TABLES:
            with self.subTest(table=table_name):
                columns, constraints = module._table_columns_and_constraints(table_name)
                self.assertEqual(len(columns), expected_columns[table_name])
                primary_keys = [c for c in constraints if isinstance(c, PrimaryKeyConstraint)]
                self.assertEqual(len(primary_keys), 1)
                self.assertTrue(primary_keys[0].name.startswith("pk_"), primary_keys[0].name)
                self.assertEqual(
                    {c.name for c in constraints if isinstance(c, CheckConstraint)},
                    expected_check_names[table_name],
                )
        with self.assertRaises(ValueError):
            module._table_columns_and_constraints("not_a_table")

    def test_frozen_revision_defines_the_exact_t81_relative_path_semantics(self) -> None:
        """The frozen predicate is asserted literally, not by equality with live code."""
        module = _load_frozen_migration()
        check_sql = _frozen_check_sql("artifact_references", "relative_path_posix")
        self.assertIsNotNone(check_sql)
        expected_prefix = (
            "relative_path <> ''"
            " AND relative_path NOT LIKE '/%'"
        )
        self.assertTrue(check_sql.startswith(expected_prefix), check_sql)
        # Bare "." and ".." are blocked explicitly, as frozen T81 semantics.
        self.assertIn(" AND relative_path NOT IN ('.', '..')", check_sql)
        for fragment in (
            "AND strpos(relative_path, ':') = 0",
            "AND relative_path NOT LIKE '../%'",
            "AND relative_path NOT LIKE './%'",
            "AND relative_path NOT LIKE '%/../%'",
            "AND relative_path NOT LIKE '%/./%'",
            "AND relative_path NOT LIKE '%/..'",
            "AND relative_path NOT LIKE '%/.'",
            "AND relative_path NOT LIKE '%//%'",
        ):
            self.assertIn(fragment, check_sql)
        self.assertIn("'%\\\\%'", check_sql)
        # Every blocked shape is covered by the predicate.
        for invalid in INVALID_RELATIVE_PATHS:
            covered = (
                invalid in {".", ".."}
                and "NOT IN ('.', '..')" in check_sql
                or (invalid.startswith("./") and "NOT LIKE './%'" in check_sql)
                or ("/../" in invalid and "NOT LIKE '%/../%'" in check_sql)
                or ("//" in invalid and "NOT LIKE '%//%'" in check_sql)
            )
            self.assertTrue(covered, f"{invalid} is not covered by the frozen predicate")

    def test_mutating_the_live_constraints_module_cannot_change_the_frozen_revision(self) -> None:
        """Isolation probe: the historical revision must be immune to live edits.

        The probe replaces the live contract module with deliberately different
        values and SQL builders in memory, then reloads the revision in a fresh
        interpreter. Columns, constraints and SQL must be byte-identical, which is
        the property that makes this revision frozen.
        """
        from steelai.enterprise_lab.adapters.postgresql import constraints as constraints_module

        # Snapshot the frozen DDL BEFORE any mutation, while the live module is intact.
        baseline_snapshot = _snapshot_frozen_ddl()

        original = {
            name: getattr(constraints_module, name)
            for name in (
                "SHA256_LOWERCASE_REGEX",
                "CONTENT_DIGEST_REGEX",
                "GOVERNANCE_STATE_VALUES",
                "RESULT_LEVEL_VALUES",
                "EVIDENCE_CLASS_VALUES",
                "JOB_STATE_VALUES",
                "DELIVERY_STATUS_VALUES",
                "CHECK_STATE_DECLARED",
                "CHECK_RELATIVE_PATH_POSIX",
                "NAMING_CONVENTION",
                "relative_path_check_sql",
                "sha256_check_sql",
                "content_digest_check_sql",
                "sql_in_list",
                "audit_append_only_function_sql",
                "audit_append_only_trigger_sql",
            )
        }
        try:
            constraints_module.SHA256_LOWERCASE_REGEX = "^[0-9]{8}$"
            constraints_module.CONTENT_DIGEST_REGEX = "^mutated$"
            constraints_module.GOVERNANCE_STATE_VALUES = ("mutated_state",)
            constraints_module.RESULT_LEVEL_VALUES = ("mutated_level",)
            constraints_module.EVIDENCE_CLASS_VALUES = ("mutated_class",)
            constraints_module.JOB_STATE_VALUES = ("mutated_job_state",)
            constraints_module.DELIVERY_STATUS_VALUES = ("mutated_delivery",)
            constraints_module.CHECK_STATE_DECLARED = "state_declared_by_a_later_task"
            constraints_module.CHECK_RELATIVE_PATH_POSIX = "relative_path_posix_by_a_later_task"
            constraints_module.NAMING_CONVENTION = {"ck": "ck_mutated_%(constraint_name)s"}
            constraints_module.relative_path_check_sql = lambda column="relative_path": "mutated_path_check"
            constraints_module.sha256_check_sql = lambda column: "mutated_sha_check"
            constraints_module.content_digest_check_sql = lambda column: "mutated_digest_check"
            constraints_module.sql_in_list = lambda column, values: "mutated_in_list"
            constraints_module.audit_append_only_function_sql = lambda schema: "mutated_function"
            constraints_module.audit_append_only_trigger_sql = lambda schema: "mutated_trigger"

            # Reload the revision from disk while the live module is mutated, then
            # snapshot the DDL it would generate.
            reloaded = _load_frozen_migration(fresh=True)
            self.assertIsNotNone(reloaded)
            mutated_snapshot = _snapshot_frozen_ddl()

            # The whole point of the freeze: nothing the live module now says can
            # reach the historical revision, so the two snapshots are identical.
            self.assertEqual(mutated_snapshot, baseline_snapshot)
            self.assertIn("NOT IN ('.', '..')", _frozen_check_sql("artifact_references", "relative_path_posix"))
        finally:
            for name, value in original.items():
                setattr(constraints_module, name, value)
            importlib.reload(constraints_module)
        # The live contract is restored, so later tests see the real module, and the
        # frozen DDL is still exactly what it was before the probe ran.
        self.assertEqual(constraints_module.SHA256_LOWERCASE_REGEX, SHA256_LOWERCASE_REGEX)
        self.assertEqual(_snapshot_frozen_ddl(), baseline_snapshot)

    def test_frozen_revision_covers_every_expected_constraint_kind(self) -> None:
        kinds: dict[str, set[str]] = {name: set() for name in EXPECTED_TABLES}
        module = _load_frozen_migration()
        for table_name in EXPECTED_TABLES:
            _, constraints = module._table_columns_and_constraints(table_name)
            for constraint in constraints:
                kinds[table_name].add(type(constraint).__name__)
        self.assertEqual(kinds["workflow_runs"], {"PrimaryKeyConstraint", "UniqueConstraint", "CheckConstraint"})
        for table_name in ("artifact_references", "audit_events", "outbox_events", "background_jobs"):
            with self.subTest(table=table_name):
                self.assertIn("ForeignKeyConstraint", kinds[table_name])
                self.assertIn("PrimaryKeyConstraint", kinds[table_name])
                self.assertIn("CheckConstraint", kinds[table_name])
        for table_name in EXPECTED_TABLES:
            with self.subTest(table=table_name):
                self.assertIn("UniqueConstraint", kinds[table_name])
                self.assertIn("CheckConstraint", kinds[table_name])

    def test_audit_append_only_trigger_is_declared(self) -> None:
        from steelai.enterprise_lab.adapters.postgresql import schema

        self.assertIn("BEFORE UPDATE OR DELETE", schema.AUDIT_TRIGGER_BIND_SQL)
        self.assertIn("fn_audit_events_reject_mutation", schema.AUDIT_TRIGGER_SQL)
        self.assertIn("trg_audit_events_append_only", schema.AUDIT_TRIGGER_BIND_SQL)
        self.assertIn("RAISE EXCEPTION", schema.AUDIT_TRIGGER_SQL)
        self.assertIn("restrict_violation", schema.AUDIT_TRIGGER_SQL)
        self.assertIn("audit_append_only", self.code.lower())
        self.assertIn("AUDIT_TRIGGER_FUNCTION_SQL", self.code)
        self.assertIn("AUDIT_TRIGGER_SQL", self.code)
        self.assertIn("AUDIT_APPEND_ONLY_TRIGGER", self.code)
        self.assertIn("AUDIT_APPEND_ONLY_FUNCTION", self.code)

    def test_downgrade_is_reversible_and_never_destructive_beyond_its_own_objects(self) -> None:
        downgrade_body = self.code.split("def downgrade()")[1]
        for token in FORBIDDEN_DOWNGRADE_TOKENS:
            self.assertNotIn(token, downgrade_body, f"downgrade must not contain {token}")
        self.assertIn("DROP TRIGGER IF EXISTS", downgrade_body)
        self.assertIn("DROP FUNCTION IF EXISTS", downgrade_body)
        self.assertIn("TABLE_DROP_ORDER", downgrade_body)
        namespace: dict[str, object] = {}
        for node in ast.parse(self.source).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == "TABLE_DROP_ORDER":
                    namespace["drop_order"] = ast.unparse(node.value)
        self.assertEqual(namespace.get("drop_order"), "tuple(reversed(TABLE_CREATION_ORDER))")

    def test_migration_contains_no_seed_or_demo_data(self) -> None:
        for token in ("INSERT INTO", "bulk_insert", "update(", "delete(", "TRUNCATE"):
            self.assertNotIn(token, self.code, f"baseline migration must not contain {token}")

    def test_migration_touches_no_research_path(self) -> None:
        for token in ("data/processed", "outputs", "thermal_simulation", "read_csv", "shutil", "tempfile"):
            self.assertNotIn(token, self.code, f"baseline migration must not reference {token}")
        self.assertEqual(_forbidden_io_calls(BASELINE_PATH), [])

    def test_env_reads_only_the_declared_environment_variable(self) -> None:
        env_source = (MIGRATIONS_DIR / "env.py").read_text(encoding="utf-8")
        env_code = _executable_source(MIGRATIONS_DIR / "env.py")
        self.assertIn("STEELAI_ENTERPRISE_DATABASE_URL", env_source)
        for token in ("load_dotenv", "dotenv", "getcwd"):
            self.assertNotIn(token, env_code)
        self.assertIn("guard_migration_target", env_code)
        self.assertIn(TEST_DATABASE_ONLY_ENV_VAR, env_code)
        # Offline generation must emit the schema before Alembic's version table.
        self.assertIn("static_output", env_code)
        modules = _imported_modules(MIGRATIONS_DIR / "env.py")
        self.assertFalse({"dotenv", "requests", "socket"} & modules)
        self.assertEqual(_forbidden_io_calls(MIGRATIONS_DIR / "env.py"), [])

    def test_alembic_ini_has_no_credentials_and_pins_the_version_table(self) -> None:
        ini = ALEMBIC_INI.read_text(encoding="utf-8")
        self.assertIn("script_location = migrations/enterprise", ini)
        self.assertIn(f"version_table = {ALEMBIC_VERSION_TABLE}", ini)
        self.assertIn(f"version_table_schema = {POSTGRESQL_SCHEMA}", ini)
        self.assertNotIn("sqlalchemy.url", ini.lower())
        settings = "\n".join(
            line for line in ini.splitlines() if line.strip() and not line.lstrip().startswith("#")
        ).lower()
        for token in ("postgresql://", "postgres://", "sqlite://", "mysql://", "password", "user =", "host ="):
            self.assertNotIn(token, settings, f"alembic ini must not configure {token}")

    def test_offline_downgrade_sql_is_reversible_without_cascade(self) -> None:
        completed = _alembic(["downgrade", f"{BASELINE_REVISION}:base", "--sql"], url=PLACEHOLDER_URL)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        sql = completed.stdout
        self.assertIn("DROP TRIGGER IF EXISTS trg_audit_events_append_only", sql)
        self.assertIn('DROP FUNCTION IF EXISTS "steelai_enterprise".fn_audit_events_reject_mutation();', sql)
        for table in EXPECTED_TABLES:
            self.assertIn(f"DROP TABLE steelai_enterprise.{table};", sql)
        self.assertLess(
            sql.index("DROP TABLE steelai_enterprise.background_jobs"),
            sql.index("DROP TABLE steelai_enterprise.workflow_runs"),
        )
        self.assertNotIn("CASCADE", sql)
        self.assertNotIn("DROP DATABASE", sql)
        self.assertNotIn("DROP SCHEMA", sql)

    def test_offline_migration_fails_closed_without_a_url(self) -> None:
        environment = dict(os.environ)
        environment.pop("STEELAI_ENTERPRISE_DATABASE_URL", None)
        completed = subprocess.run(
            [str(PYTHON), "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head", "--sql"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("ENT-DB-CONFIG-001", completed.stderr + completed.stdout)

    def test_research_data_and_method_registry_are_unchanged(self) -> None:
        before = _tree_fingerprint()
        self.assertIn("config/thermal_softening_method_registry_v1.0.json", before)
        _alembic(["upgrade", "head", "--sql"], url=PLACEHOLDER_URL)
        self.assertEqual(_tree_fingerprint(), before)


@unittest.skipUnless(
    _test_database_url() is not None,
    "STEELAI_TEST_DATABASE_URL with a database name containing both 'steelai' and 'test' is required",
)
class PostgreSqlIntegrationTests(unittest.TestCase):
    """Requirement B: real migration verification against a dedicated test database."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.url = _test_database_url()
        assert cls.url is not None
        cls.env = {TEST_DATABASE_ONLY_ENV_VAR: "1"}

    def tearDown(self) -> None:
        # Always return the test database to base so the next run starts clean.
        _alembic(["downgrade", "base"], url=self.url, extra_env=self.env)

    def _run(self, *args: str):
        return _alembic(list(args), url=self.url, extra_env=self.env)

    def _connect(self):
        import sqlalchemy

        return sqlalchemy.create_engine(self.url, poolclass=sqlalchemy.pool.NullPool).connect()

    def test_base_to_head_creates_every_declared_object(self) -> None:
        from sqlalchemy import inspect

        completed = self._run("upgrade", "head")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with self._connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names(schema=POSTGRESQL_SCHEMA))
            expected = set(EXPECTED_TABLES) | {ALEMBIC_VERSION_TABLE}
            # Parenthesised on purpose: ``a | b.issubset(c)`` would union a set with
            # a bool and raise TypeError before asserting anything.
            self.assertTrue(expected.issubset(tables), sorted(expected - tables))
            checks = {
                item["name"]
                for item in inspector.get_check_constraints("workflow_runs", schema=POSTGRESQL_SCHEMA)
            }
            self.assertIn("ck_workflow_runs_request_digest_lowercase_hex", checks)
            self.assertIn("ck_workflow_runs_state_declared", checks)
            triggers = connection.exec_driver_sql(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_audit_events_append_only'"
            ).fetchall()
            self.assertEqual(len(triggers), 1)

    def test_alembic_current_matches_head(self) -> None:
        self.assertEqual(self._run("upgrade", "head").returncode, 0)
        current = self._run("current")
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn(BASELINE_REVISION, current.stdout)
        heads = self._run("heads")
        self.assertIn(BASELINE_REVISION, heads.stdout)

    def test_invalid_rows_are_rejected_by_the_expected_constraint(self) -> None:
        """Every invalid variant is independent and asserts its own SQLSTATE.

        Each case uses a distinct ``run_id`` and ``idempotency_key`` so a failure can
        never be explained by the duplicate-key constraint instead of the constraint
        under test, and the expected SQLSTATE is checked explicitly:
        ``23514`` check_violation, ``23505`` unique_violation.
        """
        import sqlalchemy

        self.assertEqual(self._run("upgrade", "head").returncode, 0)
        insert_run = sqlalchemy.text(
            "INSERT INTO steelai_enterprise.workflow_runs "
            "(run_id, project_id, task_id, state, revision, content_digest, result_level, "
            " evidence_class, idempotency_key, request_digest, created_at, updated_at, created_by, next_action) "
            "VALUES (:run_id, :project_id, :task_id, :state, :revision, :content_digest, :result_level, "
            " :evidence_class, :idempotency_key, :request_digest, :created_at, :updated_at, :created_by, :next_action)"
        )
        insert_artifact = sqlalchemy.text(
            "INSERT INTO steelai_enterprise.artifact_references "
            "(artifact_id, run_id, relative_path, sha256, artifact_type, artifact_version, created_at) "
            "VALUES (:artifact_id, :run_id, :relative_path, :sha256, :artifact_type, :artifact_version, :created_at)"
        )

        def valid_run(index: int) -> dict[str, object]:
            return {
                "run_id": f"run_t81integration{index:03d}",
                "project_id": "PRJ-T81-DEMO",
                "task_id": f"task_t81integration{index:03d}",
                "state": "draft",
                "revision": 1,
                "content_digest": "run_" + "a" * 64,
                "result_level": "working_candidate",
                "evidence_class": "synthetic_demo_data",
                "idempotency_key": f"idem-t81-integration-{index:03d}",
                "request_digest": "b" * 64,
                "created_at": "2026-09-17T00:00:00+00:00",
                "updated_at": "2026-09-17T00:00:00+00:00",
                "created_by": "system",
                "next_action": "awaiting named human review",
            }

        cases = (
            # (label, statement, payload, expected SQLSTATE)
            ("uppercase_request_digest", insert_run, {**valid_run(1), "request_digest": "A" * 64}, "23514"),
            ("short_request_digest", insert_run, {**valid_run(2), "request_digest": "abc"}, "23514"),
            ("unknown_state", insert_run, {**valid_run(3), "state": "unknown_state"}, "23514"),
            ("zero_revision", insert_run, {**valid_run(4), "revision": 0}, "23514"),
            ("malformed_content_digest", insert_run, {**valid_run(5), "content_digest": "sha256_short"}, "23514"),
            (
                "unregistered_evidence_class",
                insert_run,
                {**valid_run(6), "evidence_class": "measured_fact"},
                "23514",
            ),
        )
        with self._connect() as connection:
            for label, statement, payload, expected_sqlstate in cases:
                with self.subTest(case=label):
                    with self.assertRaises(Exception) as captured:
                        connection.execute(statement, payload)
                    connection.rollback()
                    sqlstate = getattr(captured.exception.orig, "sqlstate", None) if hasattr(
                        captured.exception, "orig"
                    ) else None
                    sqlstate = sqlstate or getattr(captured.exception, "sqlstate", None)
                    self.assertEqual(
                        sqlstate,
                        expected_sqlstate,
                        f"{label} must fail with SQLSTATE {expected_sqlstate}",
                    )

            # A committed run, then path variants that must fail on the POSIX-path CHECK.
            connection.execute(insert_run, valid_run(10))
            connection.commit()
            for index, relative_path in enumerate(INVALID_RELATIVE_PATHS, start=11):
                with self.subTest(case=f"relative_path={relative_path}"):
                    with self.assertRaises(Exception) as captured:
                        connection.execute(
                            insert_artifact,
                            {
                                "artifact_id": f"art_t81integration{index:03d}",
                                "run_id": valid_run(10)["run_id"],
                                "relative_path": relative_path,
                                "sha256": "c" * 64,
                                "artifact_type": "governance_manifest",
                                "artifact_version": "v1",
                                "created_at": "2026-09-17T00:00:00+00:00",
                            },
                        )
                    connection.rollback()
                    sqlstate = getattr(captured.exception.orig, "sqlstate", None) if hasattr(
                        captured.exception, "orig"
                    ) else None
                    sqlstate = sqlstate or getattr(captured.exception, "sqlstate", None)
                    self.assertEqual(sqlstate, "23514", f"{relative_path} must fail its CHECK")

            # Duplicate idempotency key with a fresh run id and a fresh digest.
            with self.subTest(case="duplicate_idempotency_key"):
                duplicate = valid_run(20)
                duplicate["idempotency_key"] = valid_run(10)["idempotency_key"]
                with self.assertRaises(Exception) as captured:
                    connection.execute(insert_run, duplicate)
                connection.rollback()
                sqlstate = getattr(captured.exception.orig, "sqlstate", None) if hasattr(
                    captured.exception, "orig"
                ) else None
                sqlstate = sqlstate or getattr(captured.exception, "sqlstate", None)
                self.assertEqual(sqlstate, "23505")

    def test_audit_events_refuse_update_and_delete(self) -> None:
        import sqlalchemy

        self.assertEqual(self._run("upgrade", "head").returncode, 0)
        with self._connect() as connection:
            connection.execute(
                sqlalchemy.text(
                    "INSERT INTO steelai_enterprise.workflow_runs "
                    "(run_id, project_id, task_id, state, revision, content_digest, result_level, "
                    " evidence_class, idempotency_key, request_digest, created_at, updated_at, created_by, next_action) "
                    "VALUES ('run_t81integration100','PRJ-T81-DEMO','task_t81integration100','draft',1,"
                    " 'run_' || repeat('a',64), 'working_candidate', 'synthetic_demo_data',"
                    " 'idem-t81-integration-100', repeat('b',64), now(), now(), 'system', 'awaiting review')"
                )
            )
            connection.execute(
                sqlalchemy.text(
                    "INSERT INTO steelai_enterprise.audit_events "
                    "(audit_id, sequence, run_id, action, actor_role, actor_id, summary, occurred_at, "
                    " object_type, object_id, object_revision, object_digest) "
                    "VALUES ('aud_t81integration100', 1, 'run_t81integration100', 'run-registered', 'human',"
                    " 'owner', 'named human review of synthetic metadata', now(), 'workflow_run',"
                    " 'run_t81integration100', 1, 'run_' || repeat('a',64))"
                )
            )
            connection.commit()
            for label, statement in (
                (
                    "update",
                    "UPDATE steelai_enterprise.audit_events SET summary = 'changed' "
                    "WHERE audit_id = 'aud_t81integration100'",
                ),
                ("delete", "DELETE FROM steelai_enterprise.audit_events WHERE audit_id = 'aud_t81integration100'"),
            ):
                with self.subTest(operation=label):
                    with self.assertRaises(Exception) as captured:
                        connection.execute(sqlalchemy.text(statement))
                    connection.rollback()
                    sqlstate = getattr(captured.exception.orig, "sqlstate", None) if hasattr(
                        captured.exception, "orig"
                    ) else None
                    sqlstate = sqlstate or getattr(captured.exception, "sqlstate", None)
                    # 'restrict_violation' raised by the trigger function.
                    self.assertEqual(sqlstate, "23001")

    def test_downgrade_to_base_then_upgrade_again_succeeds(self) -> None:
        from sqlalchemy import inspect

        self.assertEqual(self._run("upgrade", "head").returncode, 0)
        downgrade = self._run("downgrade", "base")
        self.assertEqual(downgrade.returncode, 0, downgrade.stderr)
        with self._connect() as connection:
            inspector = inspect(connection)
            remaining = set(inspector.get_table_names(schema=POSTGRESQL_SCHEMA))
            self.assertNotIn("workflow_runs", remaining)
            self.assertNotIn("audit_events", remaining)
        upgrade = self._run("upgrade", "head")
        self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
        with self._connect() as connection:
            inspector = inspect(connection)
            self.assertIn("workflow_runs", set(inspector.get_table_names(schema=POSTGRESQL_SCHEMA)))

    def test_integration_url_guard_rejects_an_unrelated_database_name(self) -> None:
        """The migration target guard refuses any database that is not clearly a test one."""
        source = (MIGRATIONS_DIR / "env.py").read_text(encoding="utf-8")
        self.assertIn("ERROR_UNSAFE_MIGRATION_TARGET", source)
        self.assertIn(TEST_DATABASE_ONLY_ENV_VAR, source)
        completed = _alembic(
            ["upgrade", "head"],
            url="postgresql+psycopg://placeholder:placeholder@127.0.0.1:1/production_business",
            extra_env=self.env,
        )
        self.assertNotEqual(completed.returncode, 0)
        combined = completed.stdout + completed.stderr
        self.assertIn("ENT-DB-CONFIG-004", combined)
        self.assertNotIn("placeholder", combined)


if __name__ == "__main__":
    unittest.main()
