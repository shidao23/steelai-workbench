"""T82 real PostgreSQL integration tests.

Every test here runs against a dedicated PostgreSQL container and is skipped unless
``STEELAI_TEST_DATABASE_URL`` names a safe test database (the database name must
contain both ``steelai`` and ``test``).

Concurrency tests use a bounded thread pool, a ``Barrier`` and a join timeout, so a
deadlock fails the test instead of hanging the suite. No test prints a connection
string and no test writes anything a production system would read.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import sqlalchemy
from sqlalchemy import func, select, text

from steelai.enterprise_lab.adapters.postgresql.config import POSTGRESQL_SCHEMA
from steelai.enterprise_lab.adapters.postgresql.repositories import PostgreSQLUnitOfWorkFactory
from steelai.enterprise_lab.adapters.postgresql.schema import (
    artifact_references,
    audit_events,
    background_jobs,
    outbox_events,
    workflow_runs,
)
from steelai.enterprise_lab.application.services import (
    AuditEntryRequest,
    EnterpriseWorkflowService,
    RunArtifactRequest,
    WorkflowRunRequest,
)
from steelai.enterprise_lab.domain.models import (
    ERROR_ARTIFACT_CONFLICT,
    ERROR_AUDIT_APPEND_ONLY,
    ERROR_EVENT_ORDER,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_JOB_TRANSITION,
    ERROR_REVISION_CONFLICT,
    ERROR_STORE_NOT_ACTIVE,
    ArtifactReference,
    AuditEvent,
    BackgroundJob,
    DomainError,
    DomainEvent,
    JobState,
    WorkflowRun,
    utc_now,
)
from steelai.enterprise_lab.ports.repositories import RunFilters


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
ALEMBIC_INI = ROOT / "alembic-enterprise.ini"
TEST_DATABASE_URL_ENV_VAR = "STEELAI_TEST_DATABASE_URL"
TEST_DATABASE_ONLY_ENV_VAR = "STEELAI_ENTERPRISE_TEST_DATABASE_ONLY"

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64

#: Tables cleared between tests. ``TRUNCATE`` is used because the append-only trigger
#: correctly refuses row-level DELETE on ``audit_events``; truncation is a DDL-level
#: reset performed by the test harness, not an application code path.
CLEAR_TRUNCATE_SQL = (
    f"TRUNCATE TABLE {POSTGRESQL_SCHEMA}.artifact_references, {POSTGRESQL_SCHEMA}.audit_events, "
    f"{POSTGRESQL_SCHEMA}.outbox_events, {POSTGRESQL_SCHEMA}.background_jobs, "
    f"{POSTGRESQL_SCHEMA}.workflow_runs"
)


def _test_database_url() -> str | None:
    value = os.environ.get(TEST_DATABASE_URL_ENV_VAR, "").strip()
    if not value:
        return None
    name = value.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if "steelai" not in name or "test" not in name:
        return None
    return value


def _artifact(path: str = "enterprise/demo/manifest.json", digest: str = DIGEST_A) -> RunArtifactRequest:
    return RunArtifactRequest(
        relative_path=path,
        sha256=digest,
        artifact_type="governance_manifest",
        artifact_version="v1",
    )


def _request(**overrides: object) -> WorkflowRunRequest:
    payload: dict[str, object] = {
        "project_id": "PRJ-T82-DEMO",
        "task_id": "task_t82demo001",
        "idempotency_key": "idem-t82-demo-001",
        "run_id": "run_t82demo001",
        "artifacts": (_artifact(),),
        "audit_entries": (
            AuditEntryRequest(action="run-registered", summary="named human review of synthetic metadata"),
        ),
    }
    payload.update(overrides)
    return WorkflowRunRequest(**payload)  # type: ignore[arg-type]


def _audit_event(
    sequence: int,
    *,
    run_id: str = "run_t82demo001",
    action: str = "run-registered",
) -> AuditEvent:
    return AuditEvent.create(
        sequence=sequence,
        run_id=run_id,
        action=action,
        actor_role="human",
        actor_id="owner",
        summary="named human review of synthetic metadata",
        object_type="workflow_run",
        object_id=run_id,
        object_revision=1,
        object_digest="run_" + DIGEST_A,
    )


def _domain_event(sequence: int, *, run_id: str = "run_t82demo001") -> DomainEvent:
    return DomainEvent.create(
        event_type="enterprise.workflow_run.registered",
        run_id=run_id,
        sequence=sequence,
        payload={"state": "draft", "revision": 1, "summary": "outbox ordering probe"},
    )


@unittest.skipUnless(
    _test_database_url() is not None,
    "STEELAI_TEST_DATABASE_URL with a database name containing both 'steelai' and 'test' is required",
)
class PostgreSqlRepositoryIntegrationTests(unittest.TestCase):
    """The T82 acceptance scenarios against a real PostgreSQL server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.url = _test_database_url()
        assert cls.url is not None
        separator = "&" if "?" in cls.url else "?"
        cls.url = f"{cls.url}{separator}connect_timeout=10"
        cls.env = {TEST_DATABASE_ONLY_ENV_VAR: "1", "STEELAI_ENTERPRISE_DATABASE_URL": cls.url}
        cls.engine = cls._make_engine()
        cls._migrate("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._migrate("downgrade", "base")
        finally:
            cls.engine.dispose()

    # -- helpers ---------------------------------------------------------------
    @classmethod
    def _make_engine(cls):
        return sqlalchemy.create_engine(cls.url, poolclass=sqlalchemy.pool.QueuePool, pool_size=5, max_overflow=5)

    @classmethod
    def _migrate(cls, *args: str) -> None:
        environment = dict(os.environ)
        environment.pop(TEST_DATABASE_URL_ENV_VAR, None)
        environment.update(cls.env)
        completed = subprocess.run(
            [str(PYTHON), "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            # Fail loudly instead of letting later tests run against a missing schema.
            raise AssertionError(
                f"alembic {' '.join(args)} failed with exit {completed.returncode}: "
                f"{completed.stderr.strip()[-400:]}"
            )

    def setUp(self) -> None:
        self.factory = PostgreSQLUnitOfWorkFactory(self.engine)
        self.service = EnterpriseWorkflowService(self.factory)
        with self.engine.begin() as connection:
            connection.execute(text(CLEAR_TRUNCATE_SQL))

    def _counts(self, engine: Any | None = None) -> dict[str, int]:
        target = engine or self.engine
        with target.connect() as connection:
            return {
                "runs": connection.execute(select(func.count()).select_from(workflow_runs)).scalar_one(),
                "artifacts": connection.execute(
                    select(func.count()).select_from(artifact_references)
                ).scalar_one(),
                "audits": connection.execute(select(func.count()).select_from(audit_events)).scalar_one(),
                "events": connection.execute(select(func.count()).select_from(outbox_events)).scalar_one(),
                "jobs": connection.execute(select(func.count()).select_from(background_jobs)).scalar_one(),
            }

    def _run_after_barrier(self, action: Callable[[], Any], barrier: threading.Barrier) -> tuple[str, Any]:
        """Run ``action`` on a worker thread after a shared barrier, bounded in time."""
        try:
            barrier.wait(timeout=15)
        except threading.BrokenBarrierError:  # pragma: no cover - defensive
            return ("barrier-timeout", None)
        try:
            return ("ok", action())
        except DomainError as exc:
            return (exc.code, exc)
        except Exception as exc:  # noqa: BLE001 - the test asserts on the outcome
            return (f"unexpected:{type(exc).__name__}", exc)

    def _concurrently(
        self,
        actions: list[Callable[[], Any]],
        *,
        timeout: float = 30.0,
    ) -> list[tuple[str, Any]]:
        barrier = threading.Barrier(len(actions))
        pool = ThreadPoolExecutor(max_workers=len(actions))
        try:
            futures = [pool.submit(self._run_after_barrier, action, barrier) for action in actions]
            return [future.result(timeout=timeout) for future in futures]
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def _seed_run(self, run_id: str = "run_t82demo001", key: str = "idem-t82-demo-001") -> WorkflowRun:
        with self.factory.unit_of_work() as unit:
            run, _ = unit.runs.create_run(
                WorkflowRun.create(
                    run_id=run_id,
                    project_id="PRJ-T82-DEMO",
                    task_id="task_t82demo001",
                    idempotency_key=key,
                    request_digest=DIGEST_A,
                ),
                idempotency_key=key,
            )
            unit.commit()
        return run

    def _seed_job(
        self,
        job_id: str = "job_t82demo001",
        key: str = "idem-job-t82-001",
        *,
        max_attempts: int = 3,
    ) -> BackgroundJob:
        self._seed_run()
        with self.factory.unit_of_work() as unit:
            job, _ = unit.jobs.enqueue(
                BackgroundJob.create(
                    job_id=job_id,
                    job_type="artifact-verify",
                    run_id="run_t82demo001",
                    idempotency_key=key,
                    payload_digest=DIGEST_C,
                    max_attempts=max_attempts,
                )
            )
            unit.commit()
        return job

    # -- 1: full vertical flow -------------------------------------------------
    def test_service_completes_the_vertical_flow_on_postgresql(self) -> None:
        result = self.service.start_workflow_run(_request())
        self.assertTrue(result.committed)
        self.assertFalse(result.reused)
        self.assertEqual(result.run_id, "run_t82demo001")
        self.assertEqual(len(result.artifact_ids), 1)
        self.assertEqual(len(result.audit_ids), 1)
        self.assertEqual(len(result.event_ids), 2)

    # -- 2: one commit makes everything visible --------------------------------
    def test_run_artifact_audit_and_outbox_are_visible_after_one_commit(self) -> None:
        result = self.service.start_workflow_run(_request())
        counts = self._counts()
        self.assertEqual(counts, {"runs": 1, "artifacts": 1, "audits": 1, "events": 2, "jobs": 0})

        with self.factory.unit_of_work() as unit:
            run = unit.runs.get_run(result.run_id)
            self.assertIsInstance(run, WorkflowRun)
            self.assertEqual(run.request_digest, result.request_digest)
            references = unit.artifacts.list_for_run(result.run_id)
            self.assertEqual([item.artifact_id for item in references], list(result.artifact_ids))
            audits = unit.audits.list_events(result.run_id)
            self.assertEqual([item.audit_id for item in audits], list(result.audit_ids))
            events = unit.events.replay(result.run_id)
            self.assertEqual([item.event_id for item in events], list(result.event_ids))
            self.assertEqual([item.sequence for item in events], [1, 2])
            unit.rollback()

        with self.engine.connect() as connection:
            delivered = connection.execute(
                select(outbox_events.c.delivery_status, outbox_events.c.attempts)
            ).all()
            self.assertEqual(delivered, [("pending", 0), ("pending", 0)])

    # -- 3: injected failures roll everything back -----------------------------
    def test_failure_in_each_write_stage_rolls_back_every_table(self) -> None:
        baseline = self._counts()
        self.assertEqual(baseline, {"runs": 0, "artifacts": 0, "audits": 0, "events": 0, "jobs": 0})

        stages = ("after_run", "after_artifact", "after_audit", "after_event")
        for stage in stages:
            with self.subTest(stage=stage):
                unit = self.factory.unit_of_work()
                with self.assertRaises(RuntimeError):
                    with unit:
                        run, _ = unit.runs.create_run(
                            WorkflowRun.create(
                                run_id=f"run_t82{stage}",
                                project_id="PRJ-T82-DEMO",
                                task_id="task_t82demo001",
                                idempotency_key=f"idem-{stage}",
                                request_digest=DIGEST_A,
                            ),
                            idempotency_key=f"idem-{stage}",
                        )
                        if stage == "after_run":
                            raise RuntimeError("injected")
                        unit.artifacts.register(
                            ArtifactReference.create(
                                relative_path=f"enterprise/demo/{stage}.json",
                                sha256=DIGEST_B,
                                artifact_type="governance_manifest",
                                artifact_version="v1",
                                run_id=run.run_id,
                            )
                        )
                        if stage == "after_artifact":
                            raise RuntimeError("injected")
                        unit.audits.append(
                            AuditEvent.create(
                                sequence=unit.audits.count() + 1,
                                run_id=run.run_id,
                                action="run-registered",
                                actor_role="human",
                                actor_id="owner",
                                summary="named human review of synthetic metadata",
                                object_type="workflow_run",
                                object_id=run.run_id,
                                object_revision=run.revision,
                                object_digest=run.content_digest,
                            )
                        )
                        if stage == "after_audit":
                            raise RuntimeError("injected")
                        event = DomainEvent.create(
                            event_type="enterprise.workflow_run.registered",
                            run_id=run.run_id,
                            sequence=unit.events.next_sequence(run.run_id),
                            payload={"state": run.state, "revision": run.revision, "summary": "workflow run registered"},
                        )
                        unit.events.publish(event)
                        raise RuntimeError("injected")
                self.assertTrue(unit.rolled_back)
                self.assertEqual(self._counts(), baseline, f"{stage} left a partial write")

    # -- 4: isolation of uncommitted work --------------------------------------
    def test_uncommitted_rows_are_invisible_to_a_second_connection(self) -> None:
        unit = self.factory.unit_of_work()
        with unit:
            unit.runs.create_run(
                WorkflowRun.create(
                    run_id="run_t82isolation",
                    project_id="PRJ-T82-DEMO",
                    task_id="task_t82demo001",
                    idempotency_key="idem-t82-isolation",
                    request_digest=DIGEST_A,
                ),
                idempotency_key="idem-t82-isolation",
            )
            self.assertEqual(self._counts()["runs"], 0, "an uncommitted row must be invisible")
            unit.commit()
        self.assertEqual(self._counts()["runs"], 1, "the committed row must be visible")

    # -- 5: identical replay ---------------------------------------------------
    def test_identical_replay_adds_no_rows_and_returns_the_original_ids(self) -> None:
        first = self.service.start_workflow_run(_request())
        counts_after_first = self._counts()
        second = self.service.start_workflow_run(_request())
        self.assertTrue(second.reused)
        self.assertEqual(second.run_id, first.run_id)
        self.assertEqual(second.audit_ids, first.audit_ids)
        self.assertEqual(second.event_ids, first.event_ids)
        self.assertEqual(self._counts(), counts_after_first)

    # -- 6: concurrent idempotency --------------------------------------------
    def test_concurrent_conflicting_idempotency_key_lets_exactly_one_win(self) -> None:
        def contender(task_id: str, digest_key: str) -> Callable[[], Any]:
            def action():
                return self.service.start_workflow_run(
                    _request(
                        task_id=task_id,
                        run_id=None,
                        idempotency_key="idem-t82-race",
                        artifacts=(_artifact(path=f"enterprise/demo/{digest_key}.json"),),
                    )
                )

            return action

        # Same key, different request content, launched as simultaneously as possible.
        outcomes = self._concurrently([contender("task_t82race001", "one"), contender("task_t82race002", "two")])
        codes = sorted(code for code, _ in outcomes)
        self.assertEqual(codes.count("ok"), 1, outcomes)
        self.assertIn(ERROR_IDEMPOTENCY_CONFLICT, codes, outcomes)
        counts = self._counts()
        self.assertEqual(counts["runs"], 1)
        self.assertEqual(counts["artifacts"], 1, "the losing contender must leave no partial write")
        self.assertEqual(counts["audits"], 1)
        self.assertEqual(counts["events"], 2)

    # -- 6b: identity binding is checked before any write ----------------------
    def test_create_run_identity_mismatch_writes_nothing(self) -> None:
        """A key that disagrees with the run's own key must not touch the database."""
        baseline = self._counts()
        run = WorkflowRun.create(
            run_id="run_t82identity",
            project_id="PRJ-T82-DEMO",
            task_id="task_t82demo001",
            idempotency_key="idem-t82-identity",
            request_digest=DIGEST_A,
        )
        unit = self.factory.unit_of_work()
        with unit:
            with self.assertRaises(DomainError) as captured:
                unit.runs.create_run(run, idempotency_key="idem-t82-identity-other")
            self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
            self.assertEqual(captured.exception.details["run_id"], run.run_id)
            self.assertIsNone(unit.runs.get_run(run.run_id))
            unit.commit()
        self.assertEqual(self._counts(), baseline, "the refused call wrote a row")

        # The matching key is accepted and lands in exactly one table.
        with self.factory.unit_of_work() as unit:
            stored, reused = unit.runs.create_run(run, idempotency_key=run.idempotency_key)
            self.assertFalse(reused)
            self.assertEqual(stored.run_id, run.run_id)
            unit.commit()
        self.assertEqual(self._counts(), {**baseline, "runs": 1})

    def test_artifact_registration_rejects_a_directly_constructed_conflict(self) -> None:
        """A repeated artifact_id with different content is a conflict, not a reuse."""
        self._seed_run()
        base = ArtifactReference.create(
            relative_path="enterprise/demo/manifest.json",
            sha256=DIGEST_B,
            artifact_type="governance_manifest",
            artifact_version="v1",
            run_id="run_t82demo001",
        )
        with self.factory.unit_of_work() as unit:
            _, reused = unit.artifacts.register(base)
            self.assertFalse(reused)
            unit.commit()

        conflicting = ArtifactReference(
            artifact_id=base.artifact_id,
            relative_path=base.relative_path,
            sha256=DIGEST_C,
            artifact_type=base.artifact_type,
            artifact_version=base.artifact_version,
            run_id=base.run_id,
            created_at=base.created_at,
        )
        self.assertEqual(conflicting.artifact_id, base.artifact_id)
        with self.factory.unit_of_work() as unit:
            with self.assertRaises(DomainError) as captured:
                unit.artifacts.register(conflicting)
            self.assertEqual(captured.exception.code, ERROR_ARTIFACT_CONFLICT)
            self.assertEqual(captured.exception.details["artifact_id"], base.artifact_id)
            unit.rollback()
        self.assertEqual(self._counts()["artifacts"], 1)

        # The identical reference is still a reuse, not a second row.
        with self.factory.unit_of_work() as unit:
            _, reused = unit.artifacts.register(base)
            self.assertTrue(reused)
            unit.commit()
        self.assertEqual(self._counts()["artifacts"], 1)

    # -- 7: optimistic concurrency --------------------------------------------
    def test_two_concurrent_state_updates_leave_one_winner(self) -> None:
        self._seed_run()
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def update(state: str) -> Callable[[], Any]:
            def action():
                unit = self.factory.unit_of_work()
                with unit:
                    # Read the same revision in both transactions, then update
                    # simultaneously so the guarded UPDATE is the real race.
                    with lock:
                        current = unit.runs.get_run("run_t82demo001")
                    barrier.wait(timeout=15)
                    updated = unit.runs.update_run_state(
                        current.run_id,
                        expected_revision=1,
                        state=state,
                        updated_at=utc_now(),
                    )
                    unit.commit()
                return updated

            return action

        outcomes = self._concurrently([update("needs_human"), update("approved")])
        codes = sorted(code for code, _ in outcomes)
        self.assertEqual(codes.count("ok"), 1, outcomes)
        self.assertIn(ERROR_REVISION_CONFLICT, codes, outcomes)
        with self.factory.unit_of_work() as unit:
            stored = unit.runs.get_run("run_t82demo001")
            self.assertEqual(stored.revision, 2)
            unit.rollback()

    # -- 8: global audit sequence under concurrency ----------------------------
    def test_concurrent_audit_appends_all_succeed_with_a_unique_ordered_sequence(self) -> None:
        """Every overlapping writer succeeds: the lock serialises, it does not reject.

        ``count()`` and ``append()`` take the same transaction advisory lock, so a
        caller that computes ``count() + 1`` and then appends holds the lock across
        both calls. No writer has to inspect a conflict, retry or re-derive its
        sequence. The barrier is only set before the concurrent section - never while
        one transaction already holds the lock, which would deadlock the test.
        """
        self._seed_run()

        def append(index: int) -> Callable[[], Any]:
            def action():
                with self.factory.unit_of_work() as unit:
                    stored = unit.audits.append(
                        AuditEvent.create(
                            sequence=unit.audits.count() + 1,
                            run_id="run_t82demo001",
                            action=f"concurrent-step-{index}",
                            actor_role="human",
                            actor_id="owner",
                            summary="named human review of synthetic metadata",
                            object_type="workflow_run",
                            object_id="run_t82demo001",
                            object_revision=1,
                            object_digest="run_" + DIGEST_A,
                        )
                    )
                    unit.commit()
                return stored.sequence

            return action

        outcomes = self._concurrently([append(index) for index in range(4)])
        accepted = sorted(value for code, value in outcomes if code == "ok")
        rejected = [code for code, _ in outcomes if code != "ok"]
        self.assertEqual(rejected, [], outcomes)
        self.assertEqual(accepted, [1, 2, 3, 4], outcomes)
        with self.factory.unit_of_work() as unit:
            events = unit.audits.list_events("run_t82demo001")
            sequences = [item.sequence for item in events]
            self.assertEqual(sequences, [1, 2, 3, 4])
            self.assertEqual(len(sequences), len(set(sequences)), "audit sequences must be unique")
            unit.rollback()

    def test_two_overlapping_audit_writers_both_succeed_with_one_and_two(self) -> None:
        """Two transactions that each compute ``count() + 1`` must both succeed."""
        self._seed_run()

        def worker(index: int) -> Callable[[], Any]:
            def action():
                unit = self.factory.unit_of_work()
                with unit:
                    event = AuditEvent.create(
                        sequence=unit.audits.count() + 1,
                        run_id="run_t82demo001",
                        action=f"serial-step-{index}",
                        actor_role="human",
                        actor_id="owner",
                        summary="named human review of synthetic metadata",
                        object_type="workflow_run",
                        object_id="run_t82demo001",
                        object_revision=1,
                        object_digest="run_" + DIGEST_A,
                    )
                    stored = unit.audits.append(event)
                    unit.commit()
                return stored.sequence

            return action

        outcomes = self._concurrently([worker(1), worker(2)])
        accepted = sorted(value for code, value in outcomes if code == "ok")
        rejected = [code for code, _ in outcomes if code != "ok"]
        self.assertEqual(rejected, [], outcomes)
        self.assertEqual(accepted, [1, 2], outcomes)
        with self.factory.unit_of_work() as unit:
            sequences = [item.sequence for item in unit.audits.list_events("run_t82demo001")]
            self.assertEqual(sequences, [1, 2], sequences)
            unit.rollback()

    def test_a_stale_or_out_of_order_sequence_is_refused_before_any_write(self) -> None:
        """A directly supplied stale or gapped sequence still fails closed."""
        self._seed_run()
        with self.factory.unit_of_work() as unit:
            unit.audits.append(_audit_event(sequence=1))
            unit.events.publish(_domain_event(sequence=1))
            unit.commit()

        with self.factory.unit_of_work() as unit:
            with self.assertRaises(DomainError) as stale_audit:
                unit.audits.append(_audit_event(sequence=1))
            self.assertEqual(stale_audit.exception.code, ERROR_AUDIT_APPEND_ONLY)
            self.assertEqual(stale_audit.exception.details["expected_sequence"], 2)
            self.assertEqual(stale_audit.exception.details["supplied_sequence"], 1)
            unit.rollback()

        with self.factory.unit_of_work() as unit:
            with self.assertRaises(DomainError) as gapped_event:
                unit.events.publish(_domain_event(sequence=5))
            self.assertEqual(gapped_event.exception.code, ERROR_EVENT_ORDER)
            self.assertEqual(gapped_event.exception.details["expected_sequence"], 2)
            self.assertEqual(gapped_event.exception.details["supplied"], 5)
            unit.rollback()

        counts = self._counts()
        self.assertEqual(counts["audits"], 1, "the refused append must not have written")
        self.assertEqual(counts["events"], 1, "the refused publish must not have written")

    # -- 9: per-run outbox sequence under concurrency --------------------------
    def test_two_overlapping_outbox_writers_both_succeed_with_one_and_two(self) -> None:
        """``next_sequence`` and ``publish`` share the per-run lock, so both succeed."""
        self._seed_run()

        def worker(index: int) -> Callable[[], Any]:
            def action():
                unit = self.factory.unit_of_work()
                with unit:
                    sequence = unit.events.next_sequence("run_t82demo001")
                    unit.events.publish(
                        DomainEvent.create(
                            event_type="enterprise.workflow_run.registered",
                            run_id="run_t82demo001",
                            sequence=sequence,
                            payload={
                                "state": "draft",
                                "revision": 1,
                                "summary": "overlapping outbox append",
                            },
                        )
                    )
                    unit.commit()
                return sequence

            return action

        outcomes = self._concurrently([worker(1), worker(2)])
        accepted = sorted(value for code, value in outcomes if code == "ok")
        rejected = [code for code, _ in outcomes if code != "ok"]
        self.assertEqual(rejected, [], outcomes)
        self.assertEqual(accepted, [1, 2], outcomes)
        with self.factory.unit_of_work() as unit:
            sequences = [item.sequence for item in unit.events.replay("run_t82demo001")]
            self.assertEqual(sequences, [1, 2], sequences)
            unit.rollback()

    def test_sequential_outbox_appends_stay_contiguous(self) -> None:
        """Without a simultaneous read both writers succeed with distinct sequences."""
        self._seed_run()
        sequences: list[int] = []
        for _ in range(3):
            with self.factory.unit_of_work() as unit:
                sequence = unit.events.next_sequence("run_t82demo001")
                unit.events.publish(
                    DomainEvent.create(
                        event_type="enterprise.workflow_run.registered",
                        run_id="run_t82demo001",
                        sequence=sequence,
                        payload={"state": "draft", "revision": 1, "summary": "sequential outbox append"},
                    )
                )
                sequences.append(sequence)
                unit.commit()
        self.assertEqual(sequences, [1, 2, 3])
        with self.factory.unit_of_work() as unit:
            replayed = [item.sequence for item in unit.events.replay("run_t82demo001")]
            self.assertEqual(replayed, [1, 2, 3])
            self.assertEqual(len(set(replayed)), len(replayed))
            unit.rollback()

    # -- 10: concurrent leasing -------------------------------------------------
    def test_two_overlapping_transactions_lease_two_different_jobs(self) -> None:
        """``FOR UPDATE SKIP LOCKED`` lets two transactions hold two jobs at once.

        Leasing takes **no** advisory lock: the two transactions lease two different
        rows and the barrier after each lease can only pass when both of them hold
        their own row lock, which proves the leases really overlap. The barrier is
        safe here precisely because the lease never blocks on the other transaction.
        """
        self._seed_job()
        self._seed_job(job_id="job_t82demo002", key="idem-job-t82-002")
        both_leased = threading.Barrier(2)

        def worker(index: int) -> Callable[[], Any]:
            def action():
                unit = self.factory.unit_of_work()
                with unit:
                    job = unit.jobs.lease()
                    # Only passes when both transactions already hold their lease and
                    # neither has committed yet.
                    both_leased.wait(timeout=20)
                    unit.commit()
                return job

            return action

        outcomes = self._concurrently([worker(0), worker(1)])
        codes = [code for code, _ in outcomes]
        self.assertEqual(codes, ["ok", "ok"], outcomes)
        leased = sorted(value.job_id for _, value in outcomes if value is not None)
        self.assertEqual(leased, ["job_t82demo001", "job_t82demo002"], outcomes)
        with self.factory.unit_of_work() as unit:
            jobs = {item.job_id: item for item in unit.jobs.list_jobs()}
            self.assertEqual({job.state for job in jobs.values()}, {JobState.LEASED.value})
            self.assertEqual(len({job.lease_id for job in jobs.values()}), 2, "each lease is its own")
            unit.rollback()

    def test_lease_returns_none_while_the_only_job_is_locked_elsewhere(self) -> None:
        """The second transaction skips the locked row and gets ``None`` immediately."""
        self._seed_job()
        holder_has_lease = threading.Event()
        release_holder = threading.Event()
        second_finished = threading.Event()
        results: dict[str, Any] = {}

        def holder() -> None:
            unit = self.factory.unit_of_work()
            with unit:
                results["holder"] = unit.jobs.lease()
                holder_has_lease.set()
                # Hold the row lock until the second transaction has finished.
                release_holder.wait(timeout=20)
                unit.commit()

        def second() -> None:
            self.assertTrue(holder_has_lease.wait(timeout=20))
            unit = self.factory.unit_of_work()
            with unit:
                results["second"] = unit.jobs.lease()
                unit.rollback()
            second_finished.set()

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            first = pool.submit(holder)
            other = pool.submit(second)
            # The second transaction must finish while the first one still holds the
            # row: a blocking lock would have waited for the commit instead.
            self.assertTrue(
                second_finished.wait(timeout=20),
                "lease() waited for the other transaction instead of skipping the locked row",
            )
            self.assertIsNotNone(results.get("holder"))
            self.assertIsNone(results["second"], "the locked job must not be leased twice")
            release_holder.set()
            first.result(timeout=20)
            other.result(timeout=20)
        finally:
            release_holder.set()
            pool.shutdown(wait=True, cancel_futures=True)
        with self.factory.unit_of_work() as unit:
            stored = unit.jobs.get(results["holder"].job_id)
            self.assertEqual(stored.state, JobState.LEASED.value)
            self.assertEqual(len(unit.jobs.list_jobs()), 1)
            unit.rollback()

    # -- 11: concurrent job state transitions ----------------------------------
    def test_concurrent_complete_and_fail_leave_exactly_one_winner(self) -> None:
        """Both callers target the same leased row; the loser reads the latest state."""
        self._seed_job()
        with self.factory.unit_of_work() as unit:
            leased = unit.jobs.lease()
            self.assertIsNotNone(leased)
            unit.commit()

        def worker(finish: str) -> Callable[[], Any]:
            def action():
                unit = self.factory.unit_of_work()
                with unit:
                    if finish == "complete":
                        job = unit.jobs.complete(leased.job_id)
                    else:
                        job = unit.jobs.fail(leased.job_id, error_code="ENT-JOB-001")
                    unit.commit()
                return job

            return action

        outcomes = self._concurrently([worker("complete"), worker("fail")])
        winners = [value for code, value in outcomes if code == "ok"]
        losers = [code for code, _ in outcomes if code != "ok"]
        self.assertEqual(len(winners), 1, outcomes)
        self.assertEqual(losers, [ERROR_JOB_TRANSITION], outcomes)
        with self.factory.unit_of_work() as unit:
            stored = unit.jobs.get(leased.job_id)
            # The winner's outcome is intact: the loser did not overwrite it.
            self.assertEqual(stored.state, winners[0].state)
            self.assertEqual(stored.updated_at, winners[0].updated_at)
            self.assertEqual(stored.error_code, winners[0].error_code)
            self.assertIn(stored.state, {JobState.SUCCEEDED.value, JobState.FAILED.value})
            unit.rollback()

    def test_retry_attempt_limit_is_enforced_on_the_locked_row(self) -> None:
        """The attempts budget is checked inside the lock, on the current row."""
        self._seed_job(max_attempts=1)
        with self.factory.unit_of_work() as unit:
            leased = unit.jobs.lease()
            unit.commit()
        with self.factory.unit_of_work() as unit:
            failed = unit.jobs.fail(leased.job_id, error_code="ENT-JOB-001")
            unit.commit()
        self.assertEqual(failed.state, JobState.FAILED.value)

        with self.factory.unit_of_work() as unit:
            with self.assertRaises(DomainError) as captured:
                unit.jobs.retry(leased.job_id)
            self.assertEqual(captured.exception.code, ERROR_JOB_TRANSITION)
            self.assertEqual(captured.exception.details["attempts"], 1)
            self.assertEqual(captured.exception.details["max_attempts"], 1)
            unit.rollback()

        with self.factory.unit_of_work() as unit:
            stored = unit.jobs.get(leased.job_id)
            self.assertEqual(stored.state, JobState.FAILED.value, "the refused retry changed nothing")
            self.assertEqual(stored.attempts, 1)
            unit.rollback()

    # -- 12: handle lifetime after the boundary --------------------------------
    def test_all_five_handles_are_dead_after_commit_and_after_rollback(self) -> None:
        for close in ("commit", "rollback"):
            with self.subTest(close=close):
                unit = self.factory.unit_of_work()
                with unit:
                    handles = (unit.runs, unit.audits, unit.artifacts, unit.events, unit.jobs)
                    getattr(unit, close)()
                actions = (
                    lambda h: h.get_run("run_t82demo001"),
                    lambda h: h.list_events(None),
                    lambda h: h.count(),
                    lambda h: h.next_sequence("run_t82demo001"),
                    lambda h: h.list_jobs(),
                )
                for handle, action in zip(handles, actions):
                    with self.assertRaises(DomainError) as captured:
                        action(handle)
                    self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)

    # -- 13: the audit trigger still protects the table ------------------------
    def test_audit_update_and_delete_are_still_rejected_by_the_trigger(self) -> None:
        self._seed_run()
        with self.factory.unit_of_work() as unit:
            unit.audits.append(
                AuditEvent.create(
                    sequence=1,
                    run_id="run_t82demo001",
                    action="run-registered",
                    actor_role="human",
                    actor_id="owner",
                    summary="named human review of synthetic metadata",
                    object_type="workflow_run",
                    object_id="run_t82demo001",
                    object_revision=1,
                    object_digest="run_" + DIGEST_A,
                )
            )
            unit.commit()
        with self.engine.begin() as connection:
            with self.assertRaises(sqlalchemy.exc.IntegrityError) as update_error:
                connection.execute(
                    text(
                        f"UPDATE {POSTGRESQL_SCHEMA}.audit_events SET summary = 'changed' "
                        "WHERE run_id = 'run_t82demo001'"
                    )
                )
            self.assertEqual(getattr(update_error.exception.orig, "sqlstate", None), "23001")
        with self.engine.begin() as connection:
            with self.assertRaises(sqlalchemy.exc.IntegrityError) as delete_error:
                connection.execute(
                    text(f"DELETE FROM {POSTGRESQL_SCHEMA}.audit_events WHERE run_id = 'run_t82demo001'")
                )
            self.assertEqual(getattr(delete_error.exception.orig, "sqlstate", None), "23001")
        self.assertEqual(self._counts()["audits"], 1)

    # -- 14/15: domain objects and pool hygiene --------------------------------
    def test_repositories_return_domain_objects_only(self) -> None:
        self._seed_run()
        self._seed_job()
        with self.factory.unit_of_work() as unit:
            self.assertIsInstance(unit.runs.get_run("run_t82demo001"), WorkflowRun)
            self.assertIsInstance(unit.runs.list_runs(RunFilters(project_id="PRJ-T82-DEMO"))[0], WorkflowRun)
            self.assertIsInstance(unit.jobs.get("job_t82demo001"), BackgroundJob)
            self.assertIsInstance(unit.jobs.list_jobs()[0], BackgroundJob)
            unit.rollback()

    def test_connections_are_returned_to_the_pool_without_open_transactions(self) -> None:
        pool = self.engine.pool
        before = pool.checkedout()
        for _ in range(5):
            with self.factory.unit_of_work() as unit:
                unit.runs.list_runs()
                unit.rollback()
        self.assertEqual(pool.checkedout(), before, "the pool must not leak checked-out connections")
        with self.engine.connect() as connection:
            active = connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'")
            ).scalar_one()
        self.assertEqual(active, 0, "no transaction may be left open")


if __name__ == "__main__":
    unittest.main()
