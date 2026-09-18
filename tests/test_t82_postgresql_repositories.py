"""T82 offline tests: PostgreSQL adapter contract without a database.

Nothing here opens a connection. The suite covers the pieces that can be proven
without a server - error classification, row hydration (round-tripping through the
frozen domain validators), stable advisory-lock keys, unit-of-work handle lifetime,
and the isolation rules that keep the default application database-free.

The real database scenarios live in ``tests/test_t82_postgresql_integration.py``
and only run when ``STEELAI_TEST_DATABASE_URL`` names a safe test database.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import sqlalchemy
from sqlalchemy.exc import IntegrityError

from steelai.enterprise_lab.adapters.memory import MemoryUnitOfWorkFactory
from steelai.enterprise_lab.adapters.postgresql import _locks as lock_module
from steelai.enterprise_lab.adapters.postgresql import repositories as repositories_module
from steelai.enterprise_lab.adapters.postgresql._locks import (
    LOCK_NAMESPACE,
    LOCK_SCOPE_AUDIT_SEQUENCE,
    LOCK_SCOPE_EVENT_SEQUENCE,
    advisory_lock_key,
    audit_sequence_lock_key,
    event_sequence_lock_key,
)
from steelai.enterprise_lab.adapters.postgresql.errors import (
    CONSTRAINT_ERROR_CODES,
    ERROR_CHECK_CONSTRAINT,
    ERROR_DATABASE,
    ERROR_SERIALIZATION,
    ERROR_TRIGGER_REJECTED,
    SQLSTATE_CHECK_VIOLATION,
    SQLSTATE_FOREIGN_KEY_VIOLATION,
    SQLSTATE_RESTRICT_VIOLATION,
    SQLSTATE_SERIALIZATION_FAILURE,
    SQLSTATE_UNIQUE_VIOLATION,
    constraint_name_of,
    is_redaction_safe,
    map_database_error,
    sqlstate_of,
)
from steelai.enterprise_lab.adapters.postgresql.hydration import (
    hydrate_artifact_reference,
    hydrate_audit_event,
    hydrate_background_job,
    hydrate_domain_event,
    hydrate_workflow_run,
    to_iso8601,
)
from steelai.enterprise_lab.adapters.postgresql.mapping import (
    artifact_reference_row,
    workflow_run_row,
)
from steelai.enterprise_lab.adapters.postgresql.repositories import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from steelai.enterprise_lab.domain.models import (
    ERROR_ARTIFACT_CONFLICT,
    ERROR_AUDIT_APPEND_ONLY,
    ERROR_EVENT_ORDER,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_JOB_TRANSITION,
    ERROR_REVISION_CONFLICT,
    ERROR_STORE_NOT_ACTIVE,
    ERROR_UNKNOWN_RUN,
    ArtifactReference,
    AuditEvent,
    BackgroundJob,
    DomainError,
    DomainEvent,
    WorkflowRun,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "steelai" / "enterprise_lab"
POSTGRES_PACKAGE = PACKAGE / "adapters" / "postgresql"
PYTHON = Path(sys.executable)

FORBIDDEN_RUNTIME_MODULES = ("sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg")

#: A syntactically valid URL that is never meant to be connected to in this file.
#: ``connect_timeout`` is set so an accidental connection fails in seconds instead
#: of hanging the suite.
PLACEHOLDER_URL = (
    "postgresql+psycopg://placeholder:placeholder@127.0.0.1:1/steelai_enterprise_test"
    "?connect_timeout=2"
)


class _FakeDriverError(Exception):
    """Stand-in for a Psycopg error, carrying only structured diagnostics."""

    def __init__(self, sqlstate: str, constraint: str | None = None, message: str = "driver message") -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = type("Diag", (), {"constraint_name": constraint})()


def _integrity_error(sqlstate: str, constraint: str | None = None) -> IntegrityError:
    return IntegrityError("statement (redacted)", {}, _FakeDriverError(sqlstate, constraint))


def _run(run_id: str = "run_t82demo001", digest: str = "a" * 64) -> WorkflowRun:
    return WorkflowRun.create(
        run_id=run_id,
        project_id="PRJ-T82-DEMO",
        task_id="task_t82demo001",
        idempotency_key="idem-t82-demo-001",
        request_digest=digest,
    )


def _workflow_run_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "run_id": "run_t82demo001",
        "project_id": "PRJ-T82-DEMO",
        "task_id": "task_t82demo001",
        "state": "draft",
        "revision": 1,
        "content_digest": "run_" + "a" * 64,
        "result_level": "working_candidate",
        "evidence_class": "synthetic_demo_data",
        "idempotency_key": "idem-t82-demo-001",
        "request_digest": "b" * 64,
        "created_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
        "updated_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
        "created_by": "system",
        "next_action": "awaiting named human review",
    }
    row.update(overrides)
    return row


class ErrorMappingTests(unittest.TestCase):
    """Database failures are classified from SQLSTATE and constraint name only."""

    def test_sqlstate_and_constraint_are_read_structurally(self) -> None:
        error = _integrity_error(SQLSTATE_UNIQUE_VIOLATION, "uq_workflow_runs_idempotency_key")
        self.assertEqual(sqlstate_of(error), SQLSTATE_UNIQUE_VIOLATION)
        self.assertEqual(constraint_name_of(error), "uq_workflow_runs_idempotency_key")

    def test_known_constraints_map_to_existing_governance_codes(self) -> None:
        expectations = {
            "uq_workflow_runs_idempotency_key": ERROR_IDEMPOTENCY_CONFLICT,
            "uq_background_jobs_idempotency_key": ERROR_IDEMPOTENCY_CONFLICT,
            "uq_artifact_references_relative_path": ERROR_ARTIFACT_CONFLICT,
            "fk_audit_events_run_id_workflow_runs": ERROR_UNKNOWN_RUN,
            "ck_artifact_references_relative_path_posix": ERROR_ARTIFACT_CONFLICT,
            "ck_workflow_runs_revision_positive": ERROR_REVISION_CONFLICT,
            "ck_background_jobs_attempts_within_limit": ERROR_JOB_TRANSITION,
            "uq_outbox_events_run_id_sequence": ERROR_EVENT_ORDER,
            "uq_audit_events_sequence": ERROR_AUDIT_APPEND_ONLY,
        }
        for constraint, code in expectations.items():
            with self.subTest(constraint=constraint):
                mapped = map_database_error(_integrity_error(SQLSTATE_UNIQUE_VIOLATION, constraint))
                self.assertIsInstance(mapped, DomainError)
                self.assertEqual(mapped.code, code)
                self.assertEqual(mapped.details["constraint"], constraint)
                self.assertEqual(mapped.details["sqlstate"], SQLSTATE_UNIQUE_VIOLATION)
                self.assertTrue(is_redaction_safe(mapped))

    def test_unknown_constraint_falls_back_to_a_stable_adapter_error(self) -> None:
        check = map_database_error(_integrity_error(SQLSTATE_CHECK_VIOLATION, "ck_something_new"))
        self.assertEqual(check.code, ERROR_CHECK_CONSTRAINT)
        unique = map_database_error(_integrity_error(SQLSTATE_UNIQUE_VIOLATION, "uq_something_new"))
        self.assertEqual(unique.code, ERROR_DATABASE)
        foreign = map_database_error(_integrity_error(SQLSTATE_FOREIGN_KEY_VIOLATION, None))
        self.assertEqual(foreign.code, ERROR_UNKNOWN_RUN)
        for error in (check, unique, foreign):
            self.assertTrue(is_redaction_safe(error))

    def test_append_only_trigger_rejection_maps_to_the_audit_code(self) -> None:
        mapped = map_database_error(_integrity_error(SQLSTATE_RESTRICT_VIOLATION, None))
        self.assertEqual(mapped.code, ERROR_AUDIT_APPEND_ONLY)
        self.assertEqual(mapped.details["sqlstate"], SQLSTATE_RESTRICT_VIOLATION)
        override = map_database_error(
            _integrity_error(SQLSTATE_RESTRICT_VIOLATION, None),
            mutate_audit_error_code=ERROR_TRIGGER_REJECTED,
        )
        self.assertEqual(override.code, ERROR_TRIGGER_REJECTED)

    def test_serialization_failure_is_reported_as_a_concurrency_conflict(self) -> None:
        mapped = map_database_error(_integrity_error(SQLSTATE_SERIALIZATION_FAILURE))
        self.assertEqual(mapped.code, ERROR_SERIALIZATION)

    def test_unclassified_driver_error_is_sanitised(self) -> None:
        leaky = _FakeDriverError("99999", None, "postgresql://user:secret@host/db failed")
        mapped = map_database_error(leaky)
        self.assertEqual(mapped.code, ERROR_DATABASE)
        self.assertNotIn("secret", str(mapped))
        self.assertNotIn("host", str(mapped))
        self.assertNotIn("postgresql://", str(mapped))
        self.assertEqual(mapped.details["error_type"], "_FakeDriverError")
        self.assertTrue(is_redaction_safe(mapped))

    def test_mapping_table_only_uses_declared_constraint_names(self) -> None:
        from steelai.enterprise_lab.adapters.postgresql import schema

        declared = {
            constraint.name
            for table in schema.metadata.tables.values()
            for constraint in table.constraints
            if constraint.name
        }
        unknown = sorted(set(CONSTRAINT_ERROR_CODES) - declared)
        self.assertEqual(unknown, [], "mapping references constraints that the schema does not declare")


class HydrationTests(unittest.TestCase):
    """Rows come back as validated domain objects, never as SQLAlchemy rows."""

    def test_timestamps_are_normalised_to_aware_iso8601(self) -> None:
        naive = dt.datetime(2026, 9, 17, 10, 0)
        with self.assertRaises(ValueError):
            to_iso8601(naive)
        self.assertEqual(to_iso8601(dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc)), "2026-09-17T10:00:00+00:00")
        self.assertEqual(to_iso8601("2026-09-17T12:00:00+02:00"), "2026-09-17T10:00:00+00:00")

    def test_workflow_run_hydration_preserves_every_identifier(self) -> None:
        row = _workflow_run_row()
        run = hydrate_workflow_run(row)
        self.assertIsInstance(run, WorkflowRun)
        self.assertEqual(run.run_id, row["run_id"])
        self.assertEqual(run.request_digest, row["request_digest"])
        self.assertEqual(run.content_digest, row["content_digest"])
        self.assertEqual(run.revision, row["revision"])
        self.assertEqual(run.idempotency_key, row["idempotency_key"])
        self.assertEqual(run.created_at, "2026-09-17T10:00:00+00:00")

    def test_hydrated_run_rejects_invalid_stored_values(self) -> None:
        for broken in (
            {"request_digest": "NOTHEX"},
            {"content_digest": "sha256_short"},
            {"state": "made_up_state"},
            {"revision": 0},
        ):
            with self.subTest(broken=broken), self.assertRaises(DomainError):
                hydrate_workflow_run(_workflow_run_row(**broken))

    def test_artifact_audit_and_job_hydration_round_trip(self) -> None:
        reference = ArtifactReference.create(
            relative_path="enterprise/demo/manifest.json",
            sha256="c" * 64,
            artifact_type="governance_manifest",
            artifact_version="v1",
            run_id="run_t82demo001",
            created_at="2026-09-17T10:00:00+00:00",
        )
        hydrated_reference = hydrate_artifact_reference(
            {
                "artifact_id": reference.artifact_id,
                "run_id": reference.run_id,
                "relative_path": reference.relative_path,
                "sha256": reference.sha256,
                "artifact_type": reference.artifact_type,
                "artifact_version": reference.artifact_version,
                "created_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
            }
        )
        self.assertEqual(hydrated_reference, reference)

        audit = AuditEvent.create(
            sequence=1,
            run_id="run_t82demo001",
            action="run-registered",
            actor_role="human",
            actor_id="owner",
            summary="named human review of synthetic metadata",
            object_type="workflow_run",
            object_id="run_t82demo001",
            object_revision=1,
            object_digest="run_" + "a" * 64,
            occurred_at="2026-09-17T10:00:00+00:00",
        )
        hydrated_audit = hydrate_audit_event(
            {
                "audit_id": audit.audit_id,
                "sequence": audit.sequence,
                "run_id": audit.run_id,
                "action": audit.action,
                "actor_role": audit.actor_role,
                "actor_id": audit.actor_id,
                "summary": audit.summary,
                "occurred_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
                "object_type": audit.object_type,
                "object_id": audit.object_id,
                "object_revision": audit.object_revision,
                "object_digest": audit.object_digest,
            }
        )
        self.assertEqual(hydrated_audit, audit)

        job = BackgroundJob.create(
            job_id="job_t82demo001",
            job_type="artifact-verify",
            run_id="run_t82demo001",
            idempotency_key="idem-job-t82-001",
            payload_digest="d" * 64,
            created_at="2026-09-17T10:00:00+00:00",
        )
        hydrated_job = hydrate_background_job(
            {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "run_id": job.run_id,
                "state": job.state,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "idempotency_key": job.idempotency_key,
                "request_digest": job.request_digest(),
                "payload_digest": job.payload_digest,
                "created_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
                "updated_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
                "lease_id": None,
                "error_code": None,
            }
        )
        self.assertEqual(hydrated_job, job)

    def test_job_hydration_verifies_the_stored_request_digest(self) -> None:
        row = {
            "job_id": "job_t82demo001",
            "job_type": "artifact-verify",
            "run_id": "run_t82demo001",
            "state": "queued",
            "attempts": 1,
            "max_attempts": 3,
            "idempotency_key": "idem-job-t82-001",
            "request_digest": "f" * 64,
            "payload_digest": "d" * 64,
            "created_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
            "updated_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
            "lease_id": None,
            "error_code": None,
        }
        with self.assertRaises(ValueError):
            hydrate_background_job(row)

    def test_domain_event_hydration_drops_infrastructure_columns(self) -> None:
        event = DomainEvent.create(
            event_type="enterprise.workflow_run.registered",
            run_id="run_t82demo001",
            sequence=1,
            payload={"state": "draft", "revision": 1, "summary": "workflow run registered"},
            occurred_at="2026-09-17T10:00:00+00:00",
        )
        hydrated = hydrate_domain_event(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "payload": dict(event.payload),
                "occurred_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
                "delivery_status": "pending",
                "attempts": 0,
                "available_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
                "published_at": None,
                "last_error_code": None,
            }
        )
        self.assertEqual(hydrated, event)
        self.assertNotIn("delivery_status", hydrated.to_dict())

    def test_domain_event_hydration_reapplies_the_payload_whitelist(self) -> None:
        row = {
            "event_id": "evt_" + "a" * 64,
            "event_type": "enterprise.workflow_run.registered",
            "run_id": "run_t82demo001",
            "sequence": 1,
            "payload": {"raw_values": [1.0, 2.0]},
            "occurred_at": dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.timezone.utc),
        }
        with self.assertRaises(DomainError):
            hydrate_domain_event(row)
        with self.assertRaises(ValueError):
            hydrate_domain_event({**row, "payload": ["not", "a", "mapping"]})

    def test_hydration_never_returns_sqlalchemy_objects(self) -> None:
        run = hydrate_workflow_run(_workflow_run_row())
        self.assertNotIsInstance(run, sqlalchemy.Row)
        self.assertNotIsInstance(run, dict)
        self.assertIsInstance(run, WorkflowRun)


class AdvisoryLockTests(unittest.TestCase):
    """Lock keys are stable, namespaced and never derived from ``hash()``."""

    def test_keys_are_stable_across_processes(self) -> None:
        code = (
            "from steelai.enterprise_lab.adapters.postgresql._locks import audit_sequence_lock_key,"
            " event_sequence_lock_key;"
            "print(audit_sequence_lock_key(), event_sequence_lock_key('run_t82demo001'))"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        in_process = f"{audit_sequence_lock_key()} {event_sequence_lock_key('run_t82demo001')}"
        self.assertEqual(completed.stdout.strip(), in_process)

    def test_keys_are_namespaced_and_in_range(self) -> None:
        # Only two scopes exist: job leasing deliberately uses no advisory lock, it
        # relies on FOR UPDATE SKIP LOCKED so overlapping transactions can proceed.
        self.assertEqual(
            sorted(name for name in dir(lock_module) if name.startswith("LOCK_SCOPE_")),
            ["LOCK_SCOPE_AUDIT_SEQUENCE", "LOCK_SCOPE_EVENT_SEQUENCE"],
        )
        self.assertFalse(hasattr(lock_module, "job_lease_lock_key"))
        for key in (audit_sequence_lock_key(), event_sequence_lock_key("run_x")):
            self.assertGreater(key, 0)
            self.assertLess(key, 1 << 63)

    def test_different_scopes_and_identities_do_not_collide(self) -> None:
        keys = {
            audit_sequence_lock_key(),
            event_sequence_lock_key("run_a"),
            event_sequence_lock_key("run_b"),
        }
        self.assertEqual(len(keys), 3)
        self.assertNotEqual(
            advisory_lock_key(LOCK_SCOPE_AUDIT_SEQUENCE),
            advisory_lock_key(LOCK_SCOPE_EVENT_SEQUENCE, "run_a"),
        )

    def test_namespace_reduces_but_never_claims_to_eliminate_collisions(self) -> None:
        """The namespace is a mitigation, and the docs must not claim more."""
        self.assertEqual(LOCK_NAMESPACE, "steelai-t82-enterprise-lab")
        digest = hashlib.sha256(f"{LOCK_NAMESPACE}\x1f{LOCK_SCOPE_AUDIT_SEQUENCE}".encode()).digest()
        expected = int.from_bytes(digest[:8], "big") % (1 << 63)
        self.assertEqual(audit_sequence_lock_key(), expected)
        source = (POSTGRES_PACKAGE / "_locks.py").read_text(encoding="utf-8")
        self.assertIn("reduces the chance", source)
        for forbidden in ("never collide", "cannot collide", "impossible to collide", "绝不可能"):
            self.assertNotIn(forbidden, source)

    def test_no_python_hash_is_used_for_keys(self) -> None:
        source = (POSTGRES_ROOT := POSTGRES_PACKAGE / "_locks.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "hash", "advisory lock keys must not use Python hash()")
        self.assertIn("sha256", source)


class _FakeTransaction:
    """Minimal transaction double: records commit/rollback without a server.

    ``commit_error`` / ``rollback_error`` let a test drive the failure lifecycle:
    the double still counts the attempt before raising.
    """

    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
    ) -> None:
        self.committed = False
        self.rolled_back = False
        self.commit_attempts = 0
        self.rollback_attempts = 0
        self._commit_error = commit_error
        self._rollback_error = rollback_error

    def commit(self) -> None:
        self.commit_attempts += 1
        if self._commit_error is not None:
            raise self._commit_error
        self.committed = True

    def rollback(self) -> None:
        self.rollback_attempts += 1
        if self._rollback_error is not None:
            raise self._rollback_error
        self.rolled_back = True


class _FakeConnection:
    def __init__(
        self,
        *,
        transaction: _FakeTransaction | None = None,
        begin_error: BaseException | None = None,
        execute_error: BaseException | None = None,
    ) -> None:
        self.transaction = transaction if transaction is not None else _FakeTransaction()
        self.closed = False
        self.close_attempts = 0
        self.statements: list[str] = []
        self._begin_error = begin_error
        self._execute_error = execute_error

    def begin(self) -> _FakeTransaction:
        if self._begin_error is not None:
            raise self._begin_error
        return self.transaction

    def execute(self, statement: object, parameters: object = None) -> None:
        self.statements.append(str(statement))
        if self._execute_error is not None:
            raise self._execute_error

    def close(self) -> None:
        self.close_attempts += 1
        self.closed = True


class _FakeEngine:
    """Engine double exposing only what the unit of work actually uses."""

    def __init__(
        self,
        *,
        connect_error: BaseException | None = None,
        transaction: _FakeTransaction | None = None,
        begin_error: BaseException | None = None,
        execute_error: BaseException | None = None,
    ) -> None:
        self.connections: list[_FakeConnection] = []
        self.connect_attempts = 0
        self.url = sqlalchemy.engine.url.make_url(PLACEHOLDER_URL)
        self._connect_error = connect_error
        self._transaction = transaction
        self._begin_error = begin_error
        self._execute_error = execute_error

    def connect(self) -> _FakeConnection:
        self.connect_attempts += 1
        if self._connect_error is not None:
            raise self._connect_error
        connection = _FakeConnection(
            transaction=self._transaction,
            begin_error=self._begin_error,
            execute_error=self._execute_error,
        )
        self.connections.append(connection)
        return connection


class _FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeResult:
    """Result double: hands the queued rows to ``mappings()``/``scalar_one()``."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)

    def scalar_one(self) -> object:
        return self._rows[0]


class _ScriptedConnection(_FakeConnection):
    """Connection double that answers ``execute`` from a queue of row batches."""

    def __init__(self, responses: list[list[dict[str, object]]] | None = None) -> None:
        super().__init__()
        self.responses = list(responses or [])

    def execute(self, statement: object, parameters: object = None) -> _FakeResult:
        self.statements.append(str(statement))
        return _FakeResult(self.responses.pop(0) if self.responses else [])


class _ScriptedEngine(_FakeEngine):
    """Engine double whose one connection answers from queued row batches."""

    def __init__(self, responses: list[list[dict[str, object]]] | None = None) -> None:
        super().__init__()
        self.responses = list(responses or [])

    def connect(self) -> _ScriptedConnection:
        self.connect_attempts += 1
        connection = _ScriptedConnection(self.responses)
        self.connections.append(connection)
        return connection


class UnitOfWorkLifetimeTests(unittest.TestCase):
    """Handle lifetime and the per-unit commit flag, using an engine double."""

    def setUp(self) -> None:
        # No server is involved: the double records connect/commit/rollback/close.
        self.engine = _FakeEngine()
        self.factory = PostgreSQLUnitOfWorkFactory(self.engine)  # type: ignore[arg-type]

    def test_factory_requires_an_explicit_engine(self) -> None:
        with self.assertRaises(TypeError):
            PostgreSQLUnitOfWorkFactory()  # type: ignore[call-arg]
        self.assertIs(self.factory.engine, self.engine)

    def test_no_connection_is_opened_until_the_boundary_starts(self) -> None:
        unit = self.factory.unit_of_work()
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)
        self.assertEqual(self.engine.connections, [])
        # Reading a repository property requires an open, started transaction.
        with self.assertRaises(DomainError) as captured:
            unit.runs
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        self.assertEqual(self.engine.connections, [])

    def test_entering_the_boundary_checks_out_one_connection(self) -> None:
        with self.factory.unit_of_work() as unit:
            self.assertEqual(len(self.engine.connections), 1)
            self.assertIsNotNone(unit.runs)
        self.assertTrue(self.engine.connections[0].closed)

    def test_handles_are_unusable_after_rollback(self) -> None:
        unit = self.factory.unit_of_work()
        with unit:
            handles = (unit.runs, unit.audits, unit.artifacts, unit.events, unit.jobs)
            unit.rollback()
        self.assertTrue(unit.rolled_back)
        self.assertFalse(unit.committed)
        self.assertTrue(self.engine.connections[0].transaction.rolled_back)
        self.assertTrue(self.engine.connections[0].closed)
        for handle, action in zip(
            handles,
            (
                lambda h: h.get_run("run_t82demo001"),
                lambda h: h.count(),
                lambda h: h.count(),
                lambda h: h.count(),
                lambda h: h.list_jobs(),
            ),
        ):
            with self.subTest(handle=type(handle).__name__):
                with self.assertRaises(DomainError) as captured:
                    action(handle)
                self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_commit_flag_is_per_unit_of_work(self) -> None:
        first = self.factory.unit_of_work()
        self.assertFalse(first.committed)
        with first:
            first.commit()
        self.assertTrue(first.committed)
        self.assertFalse(first.rolled_back)
        self.assertTrue(self.engine.connections[0].transaction.committed)
        # A later unit of work must not rewrite the first one's own outcome.
        second = self.factory.unit_of_work()
        self.assertFalse(second.committed)
        with second:
            pass
        self.assertFalse(second.committed)
        self.assertTrue(second.rolled_back)
        self.assertTrue(first.committed)

    def test_leaving_the_block_without_a_result_rolls_back(self) -> None:
        unit = self.factory.unit_of_work()
        with unit:
            unit.runs
        self.assertFalse(unit.committed)
        self.assertTrue(unit.rolled_back)
        self.assertTrue(self.engine.connections[0].transaction.rolled_back)

    def test_leaving_the_block_always_rolls_back(self) -> None:
        unit = self.factory.unit_of_work()
        with self.assertRaises(RuntimeError):
            with unit:
                raise RuntimeError("synthetic failure inside the transaction")
        self.assertFalse(unit.committed)
        self.assertTrue(unit.rolled_back)
        self.assertTrue(self.engine.connections[0].transaction.rolled_back)
        self.assertTrue(self.engine.connections[0].closed)
        with self.assertRaises(DomainError):
            unit.commit()

    def test_saved_repository_handle_is_unusable_after_commit(self) -> None:
        unit = self.factory.unit_of_work()
        with unit:
            handle = unit.runs
            unit.commit()
        with self.assertRaises(DomainError) as captured:
            handle.list_runs()
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_repository_handles_are_bound_to_one_unit_of_work(self) -> None:
        first = self.factory.unit_of_work()
        second = self.factory.unit_of_work()
        self.assertIsNot(first._context, second._context)
        with first:
            first_handle = first.runs
            with second:
                self.assertIsNot(first_handle, second.runs)
                second.rollback()
            first.rollback()

    def test_describe_exposes_no_credentials(self) -> None:
        described = str(self.factory.describe())
        self.assertNotIn("placeholder", described)
        self.assertNotIn("127.0.0.1", described)
        self.assertIn("steelai_enterprise_test", described)


class UnitOfWorkFailureTests(unittest.TestCase):
    """Failure lifecycle: connect, begin, commit and rollback must all fail closed."""

    def _factory(self, engine: _FakeEngine) -> PostgreSQLUnitOfWorkFactory:
        return PostgreSQLUnitOfWorkFactory(engine)  # type: ignore[arg-type]

    def test_commit_or_rollback_before_the_boundary_starts_fails_closed(self) -> None:
        engine = _FakeEngine()
        unit = self._factory(engine).unit_of_work()
        for action, name in ((unit.commit, "commit"), (unit.rollback, "rollback")):
            with self.subTest(action=name), self.assertRaises(DomainError) as captured:
                action()
            self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        # Refusing the call must not have opened anything.
        self.assertEqual(engine.connections, [])
        self.assertEqual(engine.connect_attempts, 0)
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)

    def test_commit_or_rollback_after_the_boundary_closed_fails_closed(self) -> None:
        engine = _FakeEngine()
        factory = self._factory(engine)
        committed = factory.unit_of_work()
        with committed:
            committed.commit()
        rolled = factory.unit_of_work()
        with rolled:
            rolled.rollback()
        for unit in (committed, rolled):
            for action, name in ((unit.commit, "commit"), (unit.rollback, "rollback")):
                with self.subTest(closed=unit is committed, action=name), self.assertRaises(
                    DomainError
                ) as captured:
                    action()
                self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        self.assertTrue(committed.committed)
        self.assertTrue(rolled.rolled_back)

    def test_connect_failure_is_sanitised_and_opens_nothing(self) -> None:
        engine = _FakeEngine(
            connect_error=RuntimeError("could not connect to postgresql://user:secret@127.0.0.1:1/db")
        )
        unit = self._factory(engine).unit_of_work()
        with self.assertRaises(DomainError) as captured:
            with unit:
                pass  # pragma: no cover - entering must already fail
        error = captured.exception
        self.assertEqual(error.code, ERROR_DATABASE)
        self.assertEqual(error.details["error_type"], "RuntimeError")
        self.assertNotIn("secret", str(error))
        self.assertNotIn("127.0.0.1", str(error))
        self.assertNotIn("postgresql://", str(error))
        self.assertTrue(is_redaction_safe(error))
        self.assertEqual(engine.connect_attempts, 1)
        self.assertEqual(engine.connections, [])
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)
        # The boundary is closed for good: no handle and no later commit.
        with self.assertRaises(DomainError) as dead_handle:
            unit.runs
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)
        with self.assertRaises(DomainError) as dead_commit:
            unit.commit()
        self.assertEqual(dead_commit.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_begin_failure_closes_the_checked_out_connection_immediately(self) -> None:
        engine = _FakeEngine(begin_error=RuntimeError("could not begin a transaction"))
        unit = self._factory(engine).unit_of_work()
        with self.assertRaises(DomainError) as captured:
            with unit:
                pass  # pragma: no cover - entering must already fail
        self.assertEqual(captured.exception.code, ERROR_DATABASE)
        self.assertEqual(len(engine.connections), 1)
        connection = engine.connections[0]
        # The connection that ``connect()`` handed out is closed at once: a failed
        # start must never leak a pooled connection.
        self.assertEqual(connection.close_attempts, 1)
        self.assertTrue(connection.closed)
        # begin() never succeeded, so there is nothing to roll back.
        self.assertEqual(connection.transaction.rollback_attempts, 0)
        self.assertEqual(connection.transaction.commit_attempts, 0)
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)
        with self.assertRaises(DomainError) as dead_handle:
            unit.runs
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)
        with self.assertRaises(DomainError) as dead_commit:
            unit.commit()
        self.assertEqual(dead_commit.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_commit_failure_rolls_back_closes_and_kills_the_boundary(self) -> None:
        transaction = _FakeTransaction(
            commit_error=RuntimeError("the server refused postgresql://user:secret@host/db")
        )
        engine = _FakeEngine(transaction=transaction)
        factory = self._factory(engine)
        unit = factory.unit_of_work()
        with self.assertRaises(DomainError) as captured:
            with unit:
                handle = unit.runs
                unit.commit()
        error = captured.exception
        self.assertEqual(error.code, ERROR_DATABASE)
        self.assertEqual(error.details["error_type"], "RuntimeError")
        self.assertNotIn("secret", str(error))
        self.assertNotIn("postgresql://", str(error))
        self.assertEqual(transaction.commit_attempts, 1)
        # Rollback is attempted immediately, then the connection is closed.
        self.assertEqual(transaction.rollback_attempts, 1)
        self.assertTrue(transaction.rolled_back)
        self.assertEqual(engine.connections[0].close_attempts, 1)
        self.assertTrue(engine.connections[0].closed)
        self.assertFalse(unit.committed)
        self.assertTrue(unit.rolled_back)
        with self.assertRaises(DomainError) as dead_handle:
            handle.list_runs()
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)
        with self.assertRaises(DomainError) as dead_commit:
            unit.commit()
        self.assertEqual(dead_commit.exception.code, ERROR_STORE_NOT_ACTIVE)
        # A failed boundary must not leak its connection into the next one.
        clean_engine = _FakeEngine()
        second = self._factory(clean_engine).unit_of_work()
        with second:
            second.commit()
        self.assertTrue(second.committed)
        self.assertTrue(clean_engine.connections[0].closed)
        self.assertIsNot(second, unit)

    def test_commit_failure_with_a_failing_rollback_still_closes_and_reports_commit(self) -> None:
        transaction = _FakeTransaction(
            commit_error=RuntimeError("commit refused"),
            rollback_error=RuntimeError("rollback refused"),
        )
        engine = _FakeEngine(transaction=transaction)
        unit = self._factory(engine).unit_of_work()
        with self.assertRaises(DomainError) as captured:
            with unit:
                unit.commit()
        # The rollback failure must not mask the sanitised commit error.
        self.assertEqual(captured.exception.code, ERROR_DATABASE)
        self.assertIn("commit", str(captured.exception))
        self.assertNotIn("rollback refused", str(captured.exception))
        self.assertEqual(transaction.rollback_attempts, 1)
        self.assertFalse(transaction.rolled_back)
        self.assertEqual(engine.connections[0].close_attempts, 1)
        self.assertTrue(engine.connections[0].closed)
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)

    def test_failing_rollback_never_masks_the_original_exception(self) -> None:
        transaction = _FakeTransaction(rollback_error=RuntimeError("rollback refused"))
        engine = _FakeEngine(transaction=transaction)
        unit = self._factory(engine).unit_of_work()
        with self.assertRaises(RuntimeError) as captured:
            with unit:
                handle = unit.runs
                raise RuntimeError("synthetic failure inside the transaction")
        self.assertIn("synthetic failure inside the transaction", str(captured.exception))
        self.assertEqual(transaction.rollback_attempts, 1)
        self.assertEqual(engine.connections[0].close_attempts, 1)
        self.assertTrue(engine.connections[0].closed)
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)
        with self.assertRaises(DomainError) as dead_handle:
            handle.list_runs()
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_explicit_rollback_failure_is_reported_and_closes_the_boundary(self) -> None:
        """An explicit ``rollback()`` the driver refuses must not look successful."""
        transaction = _FakeTransaction(
            rollback_error=RuntimeError("rollback refused for postgresql://user:secret@127.0.0.1:1/db")
        )
        engine = _FakeEngine(transaction=transaction)
        unit = self._factory(engine).unit_of_work()
        with unit:
            handle = unit.runs
            with self.assertRaises(DomainError) as captured:
                unit.rollback()
        error = captured.exception
        self.assertEqual(error.code, ERROR_DATABASE)
        self.assertNotIn("secret", str(error))
        self.assertNotIn("postgresql://", str(error))
        self.assertNotIn("127.0.0.1", str(error))
        self.assertTrue(is_redaction_safe(error))
        # The failed rollback is not reported as a rollback: the boundary is closed.
        self.assertFalse(unit.rolled_back)
        self.assertFalse(unit.committed)
        self.assertEqual(transaction.rollback_attempts, 1)
        self.assertEqual(engine.connections[0].close_attempts, 1)
        self.assertTrue(engine.connections[0].closed)
        with self.assertRaises(DomainError) as dead_handle:
            handle.list_runs()
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)
        # A second attempt reports the lifecycle error, not the driver failure again.
        with self.assertRaises(DomainError) as again:
            unit.rollback()
        self.assertEqual(again.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_automatic_rollback_failure_on_a_clean_exit_is_reported(self) -> None:
        """Leaving an uncommitted ``with`` block cleanly must not swallow the failure."""
        transaction = _FakeTransaction(rollback_error=RuntimeError("rollback refused"))
        engine = _FakeEngine(transaction=transaction)
        unit = self._factory(engine).unit_of_work()
        with self.assertRaises(DomainError) as captured:
            with unit:
                handle = unit.runs
        error = captured.exception
        self.assertEqual(error.code, ERROR_DATABASE)
        self.assertTrue(is_redaction_safe(error))
        self.assertEqual(transaction.rollback_attempts, 1)
        self.assertEqual(engine.connections[0].close_attempts, 1)
        self.assertTrue(engine.connections[0].closed)
        self.assertFalse(unit.committed)
        self.assertFalse(unit.rolled_back)
        with self.assertRaises(DomainError) as dead_handle:
            handle.list_runs()
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)


class AdvisoryLockFailureTests(unittest.TestCase):
    """A failing advisory-lock statement is classified, never propagated raw."""

    def _unit(self, error: BaseException) -> tuple[Any, _FakeEngine]:
        engine = _FakeEngine(execute_error=error)
        unit = PostgreSQLUnitOfWorkFactory(engine).unit_of_work()  # type: ignore[arg-type]
        return unit, engine

    def test_unclassified_lock_failure_is_sanitised(self) -> None:
        leaky = _FakeDriverError(
            "99999",
            None,
            "could not take lock on postgresql://steelai:t0psecret@127.0.0.1:5432/steelai_enterprise_test",
        )
        unit, engine = self._unit(leaky)
        with self.assertRaises(DomainError) as captured:
            with unit:
                handle = unit.audits
                unit.audits.count()
        error = captured.exception
        self.assertEqual(error.code, ERROR_DATABASE)
        self.assertNotIn("t0psecret", str(error))
        self.assertNotIn("postgresql://", str(error))
        self.assertNotIn("127.0.0.1", str(error))
        self.assertNotIn("could not take lock", str(error))
        self.assertTrue(is_redaction_safe(error))
        # The statement never reached the table query: only the lock was attempted.
        self.assertEqual(len(engine.connections[0].statements), 1)
        self.assertIn("pg_advisory_xact_lock", engine.connections[0].statements[0])
        self.assertTrue(engine.connections[0].closed)
        self.assertFalse(unit.committed)
        # The exception left the block, so the automatic rollback ran and succeeded.
        self.assertTrue(unit.rolled_back)
        with self.assertRaises(DomainError) as dead_handle:
            handle.count()
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_lock_failure_keeps_only_structured_safe_fields(self) -> None:
        driver_error = _FakeDriverError(
            SQLSTATE_SERIALIZATION_FAILURE,
            None,
            "serialization failure on postgresql://steelai:leaked@db-host:5432/steelai_enterprise_test",
        )
        unit, engine = self._unit(driver_error)
        with self.assertRaises(DomainError) as captured:
            with unit:
                handle = unit.events
                unit.events.next_sequence("run_t82demo001")
        error = captured.exception
        self.assertEqual(error.code, ERROR_SERIALIZATION)
        self.assertEqual(error.details["sqlstate"], SQLSTATE_SERIALIZATION_FAILURE)
        self.assertNotIn("leaked", str(error))
        self.assertNotIn("db-host", str(error))
        self.assertTrue(is_redaction_safe(error))
        self.assertTrue(engine.connections[0].closed)
        with self.assertRaises(DomainError) as dead_handle:
            handle.next_sequence("run_t82demo001")
        self.assertEqual(dead_handle.exception.code, ERROR_STORE_NOT_ACTIVE)


class IdentityBindingTests(unittest.TestCase):
    """The caller's idempotency key must be the run's own key, checked before SQL."""

    def setUp(self) -> None:
        self.engine = _FakeEngine()
        self.factory = PostgreSQLUnitOfWorkFactory(self.engine)  # type: ignore[arg-type]

    def test_create_run_rejects_a_mismatched_key_without_running_any_sql(self) -> None:
        run = _run()
        unit = self.factory.unit_of_work()
        with unit:
            with self.assertRaises(DomainError) as captured:
                unit.runs.create_run(run, idempotency_key="idem-t82-demo-other")
            self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
            self.assertEqual(captured.exception.details["run_id"], run.run_id)
            # Fail closed before the adapter touches the connection at all.
            self.assertEqual(self.engine.connections[0].statements, [])
            unit.rollback()

    def test_matching_key_is_not_refused_locally(self) -> None:
        run = _run()
        stored = workflow_run_row(run)
        engine = _ScriptedEngine(responses=[[stored]])
        unit = PostgreSQLUnitOfWorkFactory(engine).unit_of_work()  # type: ignore[arg-type]
        with unit:
            reused_run, reused = unit.runs.create_run(run, idempotency_key=run.idempotency_key)
            # The local check did not fire: the adapter reached the SELECT and
            # recognised the existing row as a reuse.
            self.assertTrue(reused)
            self.assertEqual(reused_run.run_id, run.run_id)
            self.assertEqual(len(engine.connections[0].statements), 1)
            self.assertIn("SELECT", engine.connections[0].statements[0].upper())
            unit.rollback()

    def test_memory_create_run_rejects_a_mismatched_key_without_writing(self) -> None:
        factory = MemoryUnitOfWorkFactory()
        unit = factory.unit_of_work()
        with unit:
            with self.assertRaises(DomainError) as captured:
                unit.runs.create_run(_run(), idempotency_key="idem-t82-demo-other")
            self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
            self.assertEqual(unit.runs.list_runs(), [])
            self.assertIsNone(unit.runs.get_run_by_idempotency_key("idem-t82-demo-other"))
            unit.commit()
        self.assertEqual(factory.store.state["runs"], {})
        self.assertEqual(factory.store.state["idempotency"], {})

    def test_closed_handle_reports_the_lifecycle_error_before_the_identity_error(self) -> None:
        """The unit-of-work check wins over an argument check, even with both wrong."""
        unit = self.factory.unit_of_work()
        with unit:
            handle = unit.runs
            unit.commit()
        with self.assertRaises(DomainError) as captured:
            handle.create_run(_run(), idempotency_key="idem-t82-demo-other")
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        # The lifecycle check ran first, so the closed boundary issued no statement.
        self.assertEqual(self.engine.connections[0].statements, [])
        self.assertTrue(self.engine.connections[0].closed)

    def test_memory_closed_handle_reports_the_lifecycle_error_before_the_identity_error(self) -> None:
        factory = MemoryUnitOfWorkFactory()
        unit = factory.unit_of_work()
        with unit:
            handle = unit.runs
            unit.commit()
        with self.assertRaises(DomainError) as captured:
            handle.create_run(_run(), idempotency_key="idem-t82-demo-other")
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        self.assertEqual(factory.store.state["runs"], {})
        self.assertEqual(factory.store.state["idempotency"], {})


class ArtifactIdentityConflictTests(unittest.TestCase):
    """A repeated ``artifact_id`` is reused only when every persisted field matches.

    The conflicting object is constructed directly instead of going through
    ``ArtifactReference.create``, so the derived content identity cannot hide a
    field-level difference.
    """

    CREATED_AT = "2026-09-17T10:00:00+00:00"

    def _base(self) -> ArtifactReference:
        return ArtifactReference.create(
            relative_path="enterprise/demo/manifest.json",
            sha256="c" * 64,
            artifact_type="governance_manifest",
            artifact_version="v1",
            run_id="run_t82demo001",
            created_at=self.CREATED_AT,
        )

    def _conflicting(self, base: ArtifactReference, **overrides: str) -> ArtifactReference:
        fields: dict[str, str] = {
            "artifact_id": base.artifact_id,
            "relative_path": base.relative_path,
            "sha256": base.sha256,
            "artifact_type": base.artifact_type,
            "artifact_version": base.artifact_version,
            "run_id": base.run_id,
            "created_at": base.created_at,
        }
        fields.update(overrides)
        return ArtifactReference(**fields)  # type: ignore[arg-type]

    def _postgres_unit(self, stored: ArtifactReference) -> tuple[object, _ScriptedEngine]:
        engine = _ScriptedEngine(responses=[[artifact_reference_row(stored)]])
        unit = PostgreSQLUnitOfWorkFactory(engine).unit_of_work()  # type: ignore[arg-type]
        return unit, engine

    def test_postgresql_reuses_only_when_every_persisted_field_matches(self) -> None:
        base = self._base()
        unit, engine = self._postgres_unit(base)
        with unit:  # type: ignore[union-attr]
            stored, reused = unit.artifacts.register(base)  # type: ignore[union-attr]
            self.assertTrue(reused)
            self.assertEqual(stored, base)
            # One SELECT and no INSERT: a match is a reuse, not a second write.
            self.assertEqual(len(engine.connections[0].statements), 1)
            unit.rollback()  # type: ignore[union-attr]

    def test_postgresql_rejects_directly_constructed_conflicts(self) -> None:
        base = self._base()
        conflicts = {
            "relative_path": "enterprise/demo/other.json",
            "sha256": "e" * 64,
            "artifact_type": "evidence_bundle",
            "artifact_version": "v2",
            "run_id": "run_t82demo002",
            "created_at": "2026-09-17T11:00:00+00:00",
        }
        for field_name, value in conflicts.items():
            with self.subTest(field=field_name):
                unit, engine = self._postgres_unit(base)
                conflict = self._conflicting(base, **{field_name: value})
                self.assertEqual(conflict.artifact_id, base.artifact_id)
                with unit:  # type: ignore[union-attr]
                    with self.assertRaises(DomainError) as captured:
                        unit.artifacts.register(conflict)  # type: ignore[union-attr]
                    self.assertEqual(captured.exception.code, ERROR_ARTIFACT_CONFLICT)
                    self.assertEqual(captured.exception.details["artifact_id"], base.artifact_id)
                    self.assertEqual(len(engine.connections[0].statements), 1)
                    unit.rollback()  # type: ignore[union-attr]

    def test_memory_rejects_directly_constructed_conflicts(self) -> None:
        base = self._base()
        conflicts = {
            "relative_path": "enterprise/demo/other.json",
            "sha256": "e" * 64,
            "artifact_type": "evidence_bundle",
            "artifact_version": "v2",
            "run_id": "run_t82demo002",
            "created_at": "2026-09-17T11:00:00+00:00",
        }
        for field_name, value in conflicts.items():
            with self.subTest(field=field_name):
                factory = MemoryUnitOfWorkFactory()
                unit = factory.unit_of_work()
                with unit:
                    stored, reused = unit.artifacts.register(base)
                    self.assertFalse(reused)
                    self.assertEqual(stored, base)
                    conflict = self._conflicting(base, **{field_name: value})
                    with self.assertRaises(DomainError) as captured:
                        unit.artifacts.register(conflict)
                    self.assertEqual(captured.exception.code, ERROR_ARTIFACT_CONFLICT)
                    self.assertEqual(captured.exception.details["artifact_id"], base.artifact_id)
                    # The refused registration left the staged state at one artifact.
                    self.assertEqual(unit.artifacts.get(base.artifact_id), base)
                    self.assertEqual(unit.artifacts.count(), 1)
                    self.assertEqual(factory.store.state["artifacts"], {})
                    unit.commit()
                self.assertEqual(factory.store.state["artifacts"], {base.artifact_id: base})

    def test_memory_reuses_a_directly_constructed_identical_reference(self) -> None:
        base = self._base()
        identical = self._conflicting(base)
        self.assertEqual(identical, base)
        factory = MemoryUnitOfWorkFactory()
        unit = factory.unit_of_work()
        with unit:
            unit.artifacts.register(base)
            stored, reused = unit.artifacts.register(identical)
            self.assertTrue(reused)
            self.assertEqual(stored, base)
            self.assertEqual(unit.artifacts.count(), 1)
            unit.commit()
        self.assertEqual(len(factory.store.state["artifacts"]), 1)


class IsolationTests(unittest.TestCase):
    """The optional adapter never reaches the default application."""

    def test_inner_layers_do_not_import_database_frameworks(self) -> None:
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

    def test_lab_entry_points_do_not_import_the_postgresql_package(self) -> None:
        for relative in ("__init__.py", "adapters/__init__.py"):
            with self.subTest(file=relative):
                modules = _imported_modules(PACKAGE / relative)
                self.assertFalse(any("postgresql" in module for module in modules), sorted(modules))

    def test_importing_the_lab_and_memory_adapter_loads_no_database_package(self) -> None:
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

    def test_default_application_does_not_import_the_adapter(self) -> None:
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
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "False")

    def test_adapter_opens_no_connection_when_only_imported(self) -> None:
        code = (
            "import sqlalchemy\n"
            "opened = []\n"
            "original = sqlalchemy.engine.Engine.connect\n"
            "sqlalchemy.engine.Engine.connect = lambda self, *a, **k: opened.append(1)\n"
            "import steelai.enterprise_lab.adapters.postgresql as adapter\n"
            "engine = sqlalchemy.create_engine('postgresql+psycopg://u:p@127.0.0.1:1/steelai_enterprise_test')\n"
            "factory = adapter.PostgreSQLUnitOfWorkFactory(engine)\n"
            "print(len(opened))\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "0")

    def test_repository_module_contains_no_orm_or_session_usage(self) -> None:
        source = (POSTGRES_PACKAGE / "repositories.py").read_text(encoding="utf-8")
        for forbidden in ("declarative_base", "sessionmaker", "Session(", "orm.", "scoped_session"):
            self.assertNotIn(forbidden, source, f"the adapter must not use {forbidden}")
        self.assertIn("with_for_update(skip_locked=True)", source)
        self.assertIn("on_conflict_do_nothing", source)
        self.assertIn("pg_advisory_xact_lock", (_context_source := (POSTGRES_PACKAGE / "_context.py").read_text(encoding="utf-8")))

    def test_research_data_and_method_registry_are_unchanged(self) -> None:
        before = _tree_fingerprint()
        self.assertIn("config/thermal_softening_method_registry_v1.0.json", before)
        self.assertEqual(_tree_fingerprint(), before)


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
    for area in ("data/processed", "config"):
        base = ROOT / area
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                fingerprint[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return fingerprint


if __name__ == "__main__":
    unittest.main()
