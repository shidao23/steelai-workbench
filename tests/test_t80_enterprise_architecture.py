"""T80 Enterprise Lab architecture and in-memory contract tests.

Everything here is public synthetic metadata. The suite never reads a research
file, never writes the repository tree, never writes the system temporary
directory and never starts a service.
"""
from __future__ import annotations

import ast
import gc
import hashlib
import inspect
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from steelai.enterprise_lab import (
    ArtifactReference,
    AuditEntryRequest,
    AuditEvent,
    BackgroundJob,
    DomainEvent,
    EnterpriseProject,
    EnterpriseWorkflowService,
    JobState,
    RunArtifactRequest,
    RunFilters,
    WorkflowRun,
    WorkflowRunRequest,
    start_workflow_run,
)
from steelai.enterprise_lab.adapters.memory import (
    MemoryArtifactStore,
    MemoryAuditRepository,
    MemoryEventPublisher,
    MemoryJobQueue,
    MemoryRunRepository,
    MemoryStore,
    MemoryUnitOfWork,
    MemoryUnitOfWorkFactory,
)
from steelai.enterprise_lab.domain.models import (
    ERROR_ARTIFACT_CONFLICT,
    ERROR_AUDIT_APPEND_ONLY,
    ERROR_EVENT_ORDER,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_JOB_TRANSITION,
    ERROR_REDACTION,
    ERROR_REVISION_CONFLICT,
    ERROR_STORE_NOT_ACTIVE,
    RUN_STATES,
    DomainError,
    sanitize_summary,
    utc_now,
)
from steelai.enterprise_lab.ports.artifacts import ArtifactStore
from steelai.enterprise_lab.ports.events import EventPublisher, replay_events
from steelai.enterprise_lab.ports.jobs import JobQueue
from steelai.enterprise_lab.ports.repositories import AuditRepository, RunRepository
from steelai.governance.models import GovernanceState


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "steelai" / "enterprise_lab"
PYTHON = Path(sys.executable)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

#: Enterprise components that must stay optional in T80.
FORBIDDEN_RUNTIME_MODULES = (
    "fastapi",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "kafka",
    "confluent_kafka",
    "aiokafka",
    "redis",
    "celery",
    "opentelemetry",
    "docker",
)

#: Repository areas fingerprinted to prove the adapters write nothing.
FINGERPRINT_AREAS = ("steelai", "config", "data/processed")
FINGERPRINT_EXCLUDED_NAMES = {"__pycache__", ".pytest_cache"}

EVENT_PAYLOAD_FIELDS = frozenset(
    {
        "project_id",
        "task_id",
        "state",
        "previous_state",
        "revision",
        "result_level",
        "evidence_class",
        "summary",
        "artifact_id",
        "artifact_sha256",
    }
)


def _synthetic_artifact(
    path: str = "enterprise/demo/manifest.json",
    digest: str = DIGEST_A,
) -> RunArtifactRequest:
    return RunArtifactRequest(
        relative_path=path,
        sha256=digest,
        artifact_type="governance_manifest",
        artifact_version="v1",
    )


def _synthetic_request(**overrides: object) -> WorkflowRunRequest:
    payload: dict[str, object] = {
        "project_id": "PRJ-T80-DEMO",
        "task_id": "task_t80demo001",
        "idempotency_key": "idem-t80-demo-001",
        "run_id": "run_t80demo001",
        "artifacts": (_synthetic_artifact(),),
        "audit_entries": (
            AuditEntryRequest(action="run-registered", summary="named human review of synthetic metadata"),
        ),
    }
    payload.update(overrides)
    return WorkflowRunRequest(**payload)  # type: ignore[arg-type]


def _run(value: str = "run_t80demo001", **overrides: object) -> WorkflowRun:
    payload: dict[str, object] = {
        "run_id": value,
        "project_id": "PRJ-T80-DEMO",
        "task_id": "task_t80demo001",
        "idempotency_key": "idem-t80-demo-001",
        "request_digest": DIGEST_A,
    }
    payload.update(overrides)
    return WorkflowRun.create(**payload)  # type: ignore[arg-type]


def _run_digest(run_id: str = "run_t80demo001") -> str:
    return _run(run_id).content_digest


def _run_with_digest(
    run_id: str = "run_t80demo001",
    digest: str = DIGEST_A,
    *,
    idempotency_key: str = "idem-t80-demo-001",
) -> WorkflowRun:
    return WorkflowRun.create(
        run_id=run_id,
        project_id="PRJ-T80-DEMO",
        task_id="task_t80demo001",
        idempotency_key=idempotency_key,
        request_digest=digest,
    )


def _workflow_run_fields(digest: object) -> dict[str, object]:
    """Minimal constructor payload used to probe request_digest rejection."""
    return {
        "run_id": "run_t80demo001",
        "project_id": "PRJ-T80-DEMO",
        "task_id": "task_t80demo001",
        "state": GovernanceState.DRAFT.value,
        "revision": 1,
        "content_digest": _run().content_digest,
        "result_level": "working_candidate",
        "evidence_class": "synthetic_demo_data",
        "idempotency_key": "idem-t80-demo-001",
        "request_digest": digest,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def _reference(path: str = "enterprise/demo/manifest.json", digest: str = DIGEST_A) -> ArtifactReference:
    return ArtifactReference.create(
        relative_path=path,
        sha256=digest,
        artifact_type="governance_manifest",
        artifact_version="v1",
        run_id="run_t80demo001",
    )


def _audit(run_id: str = "run_t80demo001", sequence: int = 1, **overrides: object) -> AuditEvent:
    payload: dict[str, object] = {
        "sequence": sequence,
        "run_id": run_id,
        "action": "run-registered",
        "actor_role": "human",
        "actor_id": "owner",
        "summary": "named human review of synthetic metadata",
        "object_type": "workflow_run",
        "object_id": run_id,
        "object_revision": 1,
        "object_digest": _run_digest(run_id),
    }
    payload.update(overrides)
    return AuditEvent.create(**payload)  # type: ignore[arg-type]


def _event(sequence: int = 1, **overrides: object) -> DomainEvent:
    payload: dict[str, object] = {
        "event_type": "enterprise.workflow_run.registered",
        "run_id": "run_t80demo001",
        "sequence": sequence,
        "payload": {"state": "draft", "revision": 1, "summary": "workflow run registered"},
    }
    payload.update(overrides)
    return DomainEvent.create(**payload)  # type: ignore[arg-type]


def _job(job_id: str = "job_t80demo001", **overrides: object) -> BackgroundJob:
    payload: dict[str, object] = {
        "job_id": job_id,
        "job_type": "artifact-verify",
        "run_id": "run_t80demo001",
        "idempotency_key": "idem-job-001",
        "payload_digest": DIGEST_A,
    }
    payload.update(overrides)
    return BackgroundJob.create(**payload)  # type: ignore[arg-type]


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names plus relative imports written as ``..package``."""
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


def _forbidden_io_calls(path: Path) -> list[str]:
    """Find real filesystem/process calls in a module, ignoring prose and strings."""
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


def _hexagon_report() -> dict[str, list[str]]:
    """Report the two dependency-rule violations the baseline layers must never contain.

    ``third_party_imports``: an enterprise framework imported by a T80 baseline
    layer. The scanned set is the domain, application and ports layers plus the
    T80 ``adapters.memory`` module, because those are the layers the optional
    framework ban protects: the inner layers stay framework-free and the in-memory
    adapter stays dependency-free.

    An explicitly optional adapter package added later (for example
    ``adapters/postgresql``, introduced by T81) may legitimately import its own
    framework, so such a package is outside this baseline scan. Its own regression
    suite enforces that the framework never reaches the inner layers or the default
    application.

    ``outward_imports``: an inner layer (domain, application, ports) importing an
    adapter. The adapters themselves may legitimately import the ports.
    """
    third_party: list[str] = []
    outward: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        modules = _imported_modules(path)
        parts = path.relative_to(PACKAGE).parts
        layer = parts[0] if len(parts) > 1 else ""
        is_baseline_layer = layer in {"domain", "application", "ports"} or (
            layer == "adapters" and path.name == "memory.py"
        )
        if is_baseline_layer:
            third_party.extend(item for item in modules if item.split(".")[0] in FORBIDDEN_RUNTIME_MODULES)
        outward_prefixes = {
            "domain": ("..",),  # the domain depends on nothing inside the package
            "application": ("..adapters",),
            "ports": ("..adapters", "..application"),
        }
        if layer in outward_prefixes:
            if any(item.startswith(outward_prefixes[layer]) for item in modules):
                outward.append(f"{path.name}: {layer} imports an outward layer")
    return {"third_party_imports": sorted(set(third_party)), "outward_imports": sorted(set(outward))}


def _tree_fingerprint() -> dict[str, str]:
    fingerprint: dict[str, str] = {}
    for area in FINGERPRINT_AREAS:
        base = ROOT / area
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or FINGERPRINT_EXCLUDED_NAMES & set(path.parts):
                continue
            fingerprint[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return fingerprint


class ImportIsolationTests(unittest.TestCase):
    """Requirements 1 and 2: optional module, default application unchanged."""

    def test_module_imports_without_any_enterprise_dependency(self) -> None:
        forbidden = ", ".join(repr(name) for name in FORBIDDEN_RUNTIME_MODULES)
        code = (
            "import sys\n"
            "import steelai.enterprise_lab as lab\n"
            f"loaded = [name for name in ({forbidden},) if name in sys.modules]\n"
            "print(','.join(loaded))\n"
            "print(lab.EnterpriseWorkflowService.__name__)\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2, completed.stdout)
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "EnterpriseWorkflowService")

    def test_runtime_surface_does_not_depend_on_forbidden_packages(self) -> None:
        report = _hexagon_report()
        self.assertEqual(report["third_party_imports"], [])
        self.assertEqual(report["outward_imports"], [])

    def test_current_application_never_imports_enterprise_lab(self) -> None:
        candidates = [ROOT / "app.py"]
        candidates.extend(sorted((ROOT / "pages").glob("*.py")))
        candidates.extend(
            path for path in sorted((ROOT / "steelai").rglob("*.py")) if PACKAGE not in path.parents
        )
        offenders: list[str] = []
        for path in candidates:
            if any("enterprise_lab" in item for item in _imported_modules(path)):
                offenders.append(str(path.relative_to(ROOT)).replace("\\", "/"))
        self.assertEqual(offenders, [])

    def test_default_application_entry_point_still_imports(self) -> None:
        code = (
            "import sys\n"
            "import app\n"
            "assert 'steelai.enterprise_lab' not in sys.modules, 'app must not import the lab'\n"
            "print('ok')\n"
        )
        completed = subprocess.run(
            [str(PYTHON), "-B", "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "ok")


class HexagonalStructureTests(unittest.TestCase):
    """The dependency rule: domain <- application -> ports <- adapters."""

    def test_expected_layer_files_exist(self) -> None:
        for relative in (
            "__init__.py",
            "domain/__init__.py",
            "domain/models.py",
            "application/__init__.py",
            "application/services.py",
            "ports/__init__.py",
            "ports/repositories.py",
            "ports/artifacts.py",
            "ports/events.py",
            "ports/jobs.py",
            "adapters/__init__.py",
            "adapters/memory.py",
        ):
            self.assertTrue((PACKAGE / relative).is_file(), relative)

    def test_domain_layer_performs_no_io(self) -> None:
        path = PACKAGE / "domain" / "models.py"
        modules = _imported_modules(path)
        self.assertEqual(sorted({"os", "io", "socket", "tempfile", "shutil"} & modules), [])
        self.assertEqual(sorted(item for item in modules if item.startswith("..")), [])
        self.assertEqual(_forbidden_io_calls(path), [])

    def test_application_layer_imports_ports_but_not_adapters(self) -> None:
        path = PACKAGE / "application" / "services.py"
        modules = _imported_modules(path)
        ports = sorted(item for item in modules if item.startswith("..ports"))
        self.assertTrue(ports, sorted(modules))
        self.assertEqual(sorted(item for item in modules if "adapter" in item), [])
        self.assertEqual(_forbidden_io_calls(path), [])

    def test_ports_are_protocols_and_adapters_satisfy_them(self) -> None:
        for port in (RunRepository, AuditRepository, ArtifactStore, EventPublisher, JobQueue):
            self.assertTrue(getattr(port, "_is_protocol", False), port)
        factory = MemoryUnitOfWorkFactory()
        with factory.unit_of_work() as unit:
            self.assertIsInstance(unit.runs, RunRepository)
            self.assertIsInstance(unit.audits, AuditRepository)
            self.assertIsInstance(unit.artifacts, ArtifactStore)
            self.assertIsInstance(unit.events, EventPublisher)
            self.assertIsInstance(unit.jobs, JobQueue)
            unit.rollback()

    def test_in_memory_adapter_writes_no_repository_file(self) -> None:
        before = _tree_fingerprint()
        factory = MemoryUnitOfWorkFactory()
        EnterpriseWorkflowService(factory).start_workflow_run(_synthetic_request())
        self.assertEqual(_tree_fingerprint(), before)

    def test_in_memory_adapter_writes_no_system_temp_file(self) -> None:
        temp_root = Path(tempfile.gettempdir()).resolve()
        before = {item.name for item in temp_root.iterdir()}
        factory = MemoryUnitOfWorkFactory()
        EnterpriseWorkflowService(factory).start_workflow_run(_synthetic_request())
        leaked = {item.name for item in temp_root.iterdir()} - before
        self.assertEqual({name for name in leaked if "t80" in name.lower()}, set())

    def test_in_memory_adapter_has_no_file_or_process_surface(self) -> None:
        path = PACKAGE / "adapters" / "memory.py"
        modules = _imported_modules(path)
        self.assertEqual(sorted({"tempfile", "shutil", "subprocess", "socket", "os", "pathlib"} & modules), [])
        self.assertEqual(_forbidden_io_calls(path), [])
        source = path.read_text(encoding="utf-8")
        self.assertIn("no repository file and no system temporary directory", source)

    def test_artifact_store_surface_carries_references_only(self) -> None:
        public_methods = {
            name
            for name, _ in inspect.getmembers(MemoryArtifactStore, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        self.assertEqual(public_methods, {"register", "get", "list_for_run", "count"})
        for forbidden in ("read", "write", "upload", "download", "bytes", "content", "data"):
            for port in (MemoryArtifactStore, ArtifactStore):
                self.assertFalse(hasattr(port, forbidden), f"{port.__name__}.{forbidden}")


class DomainModelTests(unittest.TestCase):
    """Requirements 3 and 5: explicit identity/state, no paths, secrets or values."""

    def test_workflow_run_carries_stable_identity_state_and_digest(self) -> None:
        run = _run()
        self.assertEqual(run.revision, 1)
        self.assertEqual(run.state, GovernanceState.DRAFT.value)
        self.assertEqual(run.content_digest, run.expected_digest())
        self.assertTrue(run.content_digest.startswith("run_"))
        self.assertIn("+00:00", run.created_at)
        self.assertEqual(run.request_digest, DIGEST_A)
        self.assertEqual(run.to_dict()["result_level"], "working_candidate")

    def test_request_digest_is_mandatory_and_hexadecimal(self) -> None:
        for bad_digest in ("", "a" * 63, "a" * 65, "z" * 64, "A" * 64, " " + "a" * 63):
            with self.subTest(digest=bad_digest), self.assertRaises(DomainError) as captured:
                WorkflowRun(**_workflow_run_fields(bad_digest))  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_REDACTION)

    def test_create_requires_an_explicit_request_digest(self) -> None:
        with self.assertRaises(TypeError):
            WorkflowRun.create(  # type: ignore[call-arg]
                run_id="run_t80demo001",
                project_id="PRJ-T80-DEMO",
                task_id="task_t80demo001",
                idempotency_key="idem-t80-demo-001",
            )
        with self.assertRaises(DomainError):
            WorkflowRun.create(
                run_id="run_t80demo001",
                project_id="PRJ-T80-DEMO",
                task_id="task_t80demo001",
                idempotency_key="idem-t80-demo-001",
                request_digest="not-a-digest",
            )

    def test_state_change_preserves_the_bound_request_digest(self) -> None:
        run = _run()
        updated = run.evolves_to(state="needs_human", revision=2, updated_at=utc_now())
        self.assertEqual(updated.request_digest, run.request_digest)
        self.assertEqual(_run().request_digest, DIGEST_A)

    def test_state_change_produces_a_new_revision_and_digest(self) -> None:
        run = _run()
        updated = run.evolves_to(state="needs_human", revision=2, updated_at=utc_now())
        self.assertEqual(run.state, "draft")
        self.assertEqual(updated.revision, 2)
        self.assertNotEqual(run.content_digest, updated.content_digest)

    def test_model_output_cannot_be_registered_as_experimental_evidence(self) -> None:
        with self.assertRaises(DomainError):
            _run(result_level="accepted_evidence", evidence_class="model_output")

    def test_run_states_reuse_the_frozen_governance_vocabulary(self) -> None:
        self.assertEqual(
            sorted(state.value for state in RUN_STATES),
            sorted(state.value for state in GovernanceState),
        )

    def test_project_carries_stable_id_and_version(self) -> None:
        project = EnterpriseProject.create("PRJ-T80-DEMO", "enterprise boundary demonstration")
        self.assertEqual(project.project_id, "PRJ-T80-DEMO")
        self.assertEqual(project.schema_version, "1.0")
        self.assertIn("+00:00", project.created_at)
        with self.assertRaises(DomainError):
            EnterpriseProject.create("PRJ-T80-DEMO", "yield stress 355")

    def test_artifact_reference_rejects_absolute_and_traversal_paths(self) -> None:
        for bad_path in (
            "C:/demo/manifest.json",
            r"C:\demo\manifest.json",
            "/var/tmp/manifest.json",
            "../manifest.json",
            "enterprise/../manifest.json",
            "enterprise//manifest.json",
            "enterprise\\manifest.json",
            "",
        ):
            with self.subTest(path=bad_path), self.assertRaises(DomainError) as captured:
                _reference(bad_path)
            self.assertEqual(captured.exception.code, ERROR_ARTIFACT_CONFLICT)

    def test_artifact_reference_rejects_empty_and_malformed_hash(self) -> None:
        for bad_digest in ("", "A" * 64, "a" * 63, "z" * 64, "a" * 65, "  " + "a" * 62):
            with self.subTest(digest=bad_digest), self.assertRaises(DomainError):
                _reference(digest=bad_digest)

    def test_artifact_identity_is_stable_for_identical_metadata(self) -> None:
        first = _reference()
        second = _reference()
        self.assertEqual(first.artifact_id, second.artifact_id)
        self.assertTrue(first.artifact_id.startswith("art_"))
        self.assertNotEqual(first.artifact_id, _reference(digest=DIGEST_B).artifact_id)

    def test_redacted_summary_refuses_raw_values_paths_and_secrets(self) -> None:
        self.assertEqual(sanitize_summary("named human review", "summary"), "named human review")
        for bad in (
            "yield stress 355",
            "C:/demo/report.csv",
            r"\\server\share",
            "token: sk-abcdefghijkl",
            "https://example.invalid/path",
            "multi\nline",
            "",
        ):
            with self.subTest(value=bad), self.assertRaises(DomainError) as captured:
                sanitize_summary(bad, "summary")
            self.assertEqual(captured.exception.code, ERROR_REDACTION)

    def test_domain_event_payload_rejects_values_paths_and_nested_objects(self) -> None:
        for payload in (
            {"summary": "yield stress 355"},
            {"raw_values": [355.0, 12.5]},
            {"artifact_path": "enterprise/demo/manifest.json"},
            {"absolute_path": "C:/demo/report.csv"},
            {"note": "token: sk-abcdefghijkl"},
        ):
            with self.subTest(payload=payload), self.assertRaises(DomainError) as captured:
                DomainEvent.create(
                    event_type="enterprise.workflow_run.registered",
                    run_id="run_t80demo001",
                    sequence=1,
                    payload=payload,
                )
            self.assertEqual(captured.exception.code, ERROR_REDACTION)

    def test_domain_event_carries_only_redacted_structured_fields(self) -> None:
        event = _event()
        self.assertTrue(set(event.payload).issubset(EVENT_PAYLOAD_FIELDS))
        # Every accepted payload field is exercised here, so a future field that
        # could carry a raw value, a path or a secret fails this test.
        full = DomainEvent.create(
            event_type="enterprise.workflow_run.registered",
            run_id="run_t80demo001",
            sequence=1,
            payload={
                "project_id": "PRJ-T80-DEMO",
                "task_id": "task_t80demo001",
                "state": "draft",
                "previous_state": "needs_human",
                "revision": 1,
                "result_level": "working_candidate",
                "evidence_class": "synthetic_demo_data",
                "summary": "workflow run registered",
                "artifact_id": "art_demo",
                "artifact_sha256": DIGEST_A,
            },
        )
        self.assertEqual(set(full.payload), EVENT_PAYLOAD_FIELDS)
        # Identifier fields may contain digits; their shape is validated as a
        # stable identifier and can never be a value, a path or a secret.
        identifier_fields = {"project_id", "task_id", "state", "previous_state", "result_level", "evidence_class"}
        for key, value in full.payload.items():
            if key == "revision":
                self.assertIsInstance(value, int)
                continue
            self.assertIsInstance(value, str, key)
            if key.endswith("_sha256"):
                continue
            if key in identifier_fields:
                self.assertRegex(value, r"^[A-Za-z0-9][A-Za-z0-9._-]*$", key)
                continue
            for character in "0123456789/\\":
                self.assertNotIn(character, value, f"{key} carries a value or a path character")
        self.assertNotIn("355", str(event.to_dict()))

    def test_domain_event_rejects_a_non_sha256_hash_field(self) -> None:
        with self.assertRaises(DomainError):
            DomainEvent.create(
                event_type="enterprise.workflow_run.registered",
                run_id="run_t80demo001",
                sequence=1,
                payload={"artifact_sha256": "not-a-digest", "summary": "artifact reference registered"},
            )

    def test_domain_event_identity_is_stable_and_content_bound(self) -> None:
        first = DomainEvent.create(
            event_type="enterprise.workflow_run.registered",
            run_id="run_t80demo001",
            sequence=1,
            payload={"state": "draft", "revision": 1, "summary": "workflow run registered"},
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        same = DomainEvent.create(
            event_type="enterprise.workflow_run.registered",
            run_id="run_t80demo001",
            sequence=1,
            payload={"state": "draft", "revision": 1, "summary": "workflow run registered"},
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(first.event_id, same.event_id)
        self.assertNotEqual(first.content_digest(), _event(sequence=2).content_digest())

    def test_job_identity_requires_declared_state_and_attempt_bounds(self) -> None:
        job = _job()
        self.assertEqual(job.state, JobState.QUEUED.value)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.max_attempts, 3)
        invalid_state = {
            "job_id": "job_t80demo001",
            "job_type": "artifact-verify",
            "run_id": "run_t80demo001",
            "state": "unknown",
            "attempts": 1,
            "max_attempts": 3,
            "idempotency_key": "idem-job-001",
            "payload_digest": DIGEST_A,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with self.assertRaises(ValueError):
            BackgroundJob(**invalid_state)  # type: ignore[arg-type]
        with self.assertRaises(DomainError):
            BackgroundJob(**{**invalid_state, "state": JobState.QUEUED.value, "attempts": 5})  # type: ignore[arg-type]


def _abandon_a_unit_of_work_with_a_write(factory: MemoryUnitOfWorkFactory) -> MemoryRunRepository:
    """Open a unit of work, write, and drop it without committing.

    The retired unit of work lives only in this frame, so returning the store and
    a saved repository handle leaves nothing else pointing at it.
    """
    abandoned = factory.unit_of_work()
    abandoned.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
    return abandoned.runs


class MemoryAdapterContractTests(unittest.TestCase):
    """Requirement 4: the in-memory contract for every port."""

    def setUp(self) -> None:
        self.factory = MemoryUnitOfWorkFactory()

    def test_create_and_read_a_run(self) -> None:
        with self.factory.unit_of_work() as unit:
            stored, reused = unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
            self.assertFalse(reused)
            self.assertEqual(stored.state, "draft")
            self.assertEqual(unit.runs.get_run("run_t80demo001"), stored)
            self.assertIsNone(unit.runs.get_run("run_missing001"))
            unit.commit()
        with self.factory.unit_of_work() as unit:
            self.assertIsNotNone(unit.runs.get_run("run_t80demo001"))
            unit.rollback()

    def test_idempotent_create_reuses_identical_content(self) -> None:
        with self.factory.unit_of_work() as unit:
            first, reused = unit.runs.create_run(
                _run_with_digest(), idempotency_key="idem-t80-demo-001"
            )
            self.assertFalse(reused)
            second, reused_again = unit.runs.create_run(
                _run_with_digest(), idempotency_key="idem-t80-demo-001"
            )
            self.assertTrue(reused_again)
            self.assertEqual(first.run_id, second.run_id)
            self.assertEqual(first.request_digest, second.request_digest)
            unit.commit()
        self.assertEqual(len(self.factory.store.state["runs"]), 1)

    def test_idempotency_key_bound_to_different_content_fails_closed(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.runs.create_run(_run_with_digest(), idempotency_key="idem-t80-demo-001")
            with self.assertRaises(DomainError) as captured:
                unit.runs.create_run(
                    _run_with_digest("run_t80demo002", DIGEST_B, idempotency_key="idem-t80-demo-001"),
                    idempotency_key="idem-t80-demo-001",
                )
            self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
            unit.rollback()
        self.assertEqual(self.factory.store.state["runs"], {})

    def test_run_filters_select_by_project_task_state_and_level(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
            unit.runs.create_run(
                _run("run_t80demo002", task_id="task_t80demo002", idempotency_key="idem-t80-demo-002"),
                idempotency_key="idem-t80-demo-002",
            )
            unit.runs.update_run_state(
                "run_t80demo002",
                expected_revision=1,
                state="needs_human",
                updated_at=utc_now(),
            )
            self.assertEqual(len(unit.runs.list_runs()), 2)
            self.assertEqual(len(unit.runs.list_runs(RunFilters(task_id="task_t80demo002"))), 1)
            self.assertEqual(len(unit.runs.list_runs(RunFilters(states=("needs_human",)))), 1)
            self.assertEqual(len(unit.runs.list_runs(RunFilters(states=("complete",)))), 0)
            self.assertEqual(len(unit.runs.list_runs(RunFilters(project_id="PRJ-OTHER"))), 0)
            self.assertEqual(len(unit.runs.list_runs(RunFilters(result_level="working_candidate"))), 2)
            unit.commit()

    def test_optimistic_concurrency_rejects_a_stale_revision(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
            first = unit.runs.update_run_state(
                "run_t80demo001",
                expected_revision=1,
                state="needs_human",
                updated_at=utc_now(),
            )
            self.assertEqual(first.revision, 2)
            with self.assertRaises(DomainError) as captured:
                unit.runs.update_run_state(
                    "run_t80demo001",
                    expected_revision=1,
                    state="approved",
                    updated_at=utc_now(),
                )
            self.assertEqual(captured.exception.code, ERROR_REVISION_CONFLICT)
            unit.rollback()
        self.assertEqual(self.factory.store.state["runs"], {})

    def test_audit_repository_is_append_only_and_ordered(self) -> None:
        with self.factory.unit_of_work() as unit:
            first = unit.audits.append(_audit(sequence=1))
            second = unit.audits.append(_audit(sequence=2, action="artifact-registered"))
            self.assertEqual([first.sequence, second.sequence], [1, 2])
            self.assertEqual(unit.audits.count(), 2)
            with self.assertRaises(DomainError) as captured:
                unit.audits.append(first)
            self.assertEqual(captured.exception.code, ERROR_AUDIT_APPEND_ONLY)
            with self.assertRaises(DomainError):
                unit.audits.append(_audit(sequence=7))
            self.assertEqual(unit.audits.count(), 2)
            self.assertEqual(len(unit.audits.list_events("run_t80demo001")), 2)
            unit.commit()
        for forbidden in ("update", "delete", "remove", "replace", "overwrite"):
            self.assertFalse(hasattr(MemoryAuditRepository, forbidden), forbidden)

    def test_artifact_store_registers_references_only_and_is_idempotent(self) -> None:
        reference = _reference()
        with self.factory.unit_of_work() as unit:
            stored, reused = unit.artifacts.register(reference)
            self.assertFalse(reused)
            again, reused_again = unit.artifacts.register(reference)
            self.assertTrue(reused_again)
            self.assertEqual(stored.artifact_id, again.artifact_id)
            self.assertEqual(len(unit.artifacts.list_for_run("run_t80demo001")), 1)
            self.assertEqual(unit.artifacts.count(), 1)
            self.assertEqual(unit.artifacts.get(stored.artifact_id), stored)
            with self.assertRaises(DomainError) as captured:
                unit.artifacts.register(_reference(digest=DIGEST_B))
            self.assertEqual(captured.exception.code, ERROR_ARTIFACT_CONFLICT)
            unit.rollback()
        self.assertEqual(self.factory.store.state["artifacts"], {})

    def test_events_replay_in_creation_order_and_refuse_gaps(self) -> None:
        with self.factory.unit_of_work() as unit:
            self.assertEqual(unit.events.next_sequence("run_t80demo001"), 1)
            unit.events.publish(_event(sequence=1))
            unit.events.publish(
                _event(sequence=2, payload={"state": "draft", "revision": 2, "summary": "second event"})
            )
            with self.assertRaises(DomainError) as captured:
                unit.events.publish(_event(sequence=4))
            self.assertEqual(captured.exception.code, ERROR_EVENT_ORDER)
            replayed = replay_events(unit.events, "run_t80demo001")
            self.assertEqual([item["sequence"] for item in replayed], [1, 2])
            self.assertEqual(unit.events.count(), 2)
            unit.commit()

    def test_job_queue_supports_enqueue_lease_complete_fail_and_retry(self) -> None:
        with self.factory.unit_of_work() as unit:
            job, reused = unit.jobs.enqueue(_job())
            self.assertFalse(reused)
            again, reused_again = unit.jobs.enqueue(_job())
            self.assertTrue(reused_again)
            self.assertEqual(job.job_id, again.job_id)
            leased = unit.jobs.lease()
            self.assertIsNotNone(leased)
            self.assertEqual(leased.state, JobState.LEASED.value)
            self.assertIsNone(unit.jobs.lease())
            failed = unit.jobs.fail(leased.job_id, error_code="ENT-JOB-ERR")
            self.assertEqual(failed.state, JobState.FAILED.value)
            self.assertEqual(failed.error_code, "ENT-JOB-ERR")
            retrying = unit.jobs.retry(leased.job_id)
            self.assertEqual(retrying.state, JobState.RETRYING.value)
            self.assertEqual(retrying.attempts, 2)
            self.assertEqual(unit.jobs.lease().state, JobState.LEASED.value)
            done = unit.jobs.complete(leased.job_id)
            self.assertEqual(done.state, JobState.SUCCEEDED.value)
            cancelled, _ = unit.jobs.enqueue(_job("job_t80demo002", idempotency_key="idem-job-002"))
            self.assertEqual(unit.jobs.cancel(cancelled.job_id).state, JobState.CANCELLED.value)
            self.assertEqual(len(unit.jobs.list_jobs()), 2)
            unit.commit()

    def test_job_queue_rejects_illegal_transitions(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.jobs.enqueue(_job())
            with self.assertRaises(DomainError) as captured:
                unit.jobs.complete("job_t80demo001")
            self.assertEqual(captured.exception.code, ERROR_JOB_TRANSITION)
            with self.assertRaises(DomainError):
                unit.jobs.retry("job_t80demo001")
            leased = unit.jobs.lease()
            unit.jobs.complete(leased.job_id)
            for action in (
                lambda: unit.jobs.complete(leased.job_id),
                lambda: unit.jobs.fail(leased.job_id, error_code="ENT-JOB-ERR"),
                lambda: unit.jobs.retry(leased.job_id),
                lambda: unit.jobs.cancel(leased.job_id),
            ):
                with self.assertRaises(DomainError):
                    action()
            unit.rollback()
        self.assertEqual(self.factory.store.state["jobs"], {})

    def test_job_retry_stops_at_max_attempts(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.jobs.enqueue(_job(max_attempts=2))
            leased = unit.jobs.lease()
            unit.jobs.fail(leased.job_id, error_code="ENT-JOB-ERR")
            unit.jobs.retry(leased.job_id)
            unit.jobs.lease()
            unit.jobs.fail(leased.job_id, error_code="ENT-JOB-ERR")
            with self.assertRaises(DomainError):
                unit.jobs.retry(leased.job_id)
            self.assertEqual(unit.jobs.get(leased.job_id).attempts, 2)
            unit.rollback()

    def test_job_enqueue_rejects_a_conflicting_request_for_the_same_key(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.jobs.enqueue(_job())
            with self.assertRaises(DomainError) as captured:
                unit.jobs.enqueue(_job(payload_digest=DIGEST_B))
            self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
            unit.rollback()

    def test_job_idempotency_key_binds_one_job_id(self) -> None:
        with self.factory.unit_of_work() as unit:
            first, reused = unit.jobs.enqueue(_job())
            self.assertFalse(reused)
            self.assertEqual(first.job_id, "job_t80demo001")

            # Same key, same job id, different payload: refused.
            with self.assertRaises(DomainError) as payload_conflict:
                unit.jobs.enqueue(_job(payload_digest=DIGEST_B))
            self.assertEqual(payload_conflict.exception.code, ERROR_IDEMPOTENCY_CONFLICT)

            # Same key, different job id: refused even when the payload matches.
            with self.assertRaises(DomainError) as job_conflict:
                unit.jobs.enqueue(_job("job_t80demo002"))
            self.assertEqual(job_conflict.exception.code, ERROR_IDEMPOTENCY_CONFLICT)

            # Same key, different job id AND different payload: refused.
            with self.assertRaises(DomainError) as both_conflict:
                unit.jobs.enqueue(_job("job_t80demo003", payload_digest=DIGEST_B))
            self.assertEqual(both_conflict.exception.code, ERROR_IDEMPOTENCY_CONFLICT)

            self.assertEqual(len(unit.jobs.list_jobs()), 1)
            unit.rollback()

    def test_job_id_cannot_be_reused_with_a_different_idempotency_key(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.jobs.enqueue(_job())
            with self.assertRaises(DomainError) as captured:
                unit.jobs.enqueue(_job(idempotency_key="idem-job-002"))
            self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
            self.assertEqual(len(unit.jobs.list_jobs()), 1)
            unit.rollback()

    def test_job_request_digest_is_stable_and_covers_every_request_field(self) -> None:
        baseline = _job().request_digest()
        self.assertEqual(baseline, _job().request_digest())
        for changed in (
            _job("job_t80demo002"),
            _job(job_type="artifact-hash"),
            _job(run_id="run_t80demo002"),
            _job(idempotency_key="idem-job-002"),
            _job(payload_digest=DIGEST_B),
            _job(max_attempts=5),
        ):
            with self.subTest(job=changed.job_id):
                self.assertNotEqual(baseline, changed.request_digest())

    def test_job_index_is_kept_per_idempotency_key(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.jobs.enqueue(_job())
            unit.jobs.enqueue(_job("job_t80demo002", idempotency_key="idem-job-002"))
            index = unit.working_state["job_idempotency"]
            self.assertEqual(
                {key: value["job_id"] for key, value in index.items()},
                {"idem-job-001": "job_t80demo001", "idem-job-002": "job_t80demo002"},
            )
            unit.commit()
        self.assertEqual(len(self.factory.store.state["jobs"]), 2)

    def test_committed_state_is_unchanged_while_a_unit_of_work_is_writing(self) -> None:
        unit = self.factory.unit_of_work()
        committed = self.factory.store.state
        unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
        unit.audits.append(_audit(sequence=1))
        unit.artifacts.register(_reference())
        unit.events.publish(_event(sequence=1))
        unit.jobs.enqueue(_job())

        # The committed state is untouched: the unit of work mutates a private
        # working copy only.
        for key in ("runs", "idempotency", "audits", "artifacts", "events", "jobs", "job_idempotency"):
            self.assertEqual(committed[key], {}, key)
        self.assertIs(self.factory.store.state, committed)
        # The staged writes are visible inside the unit of work itself.
        self.assertEqual(len(unit.working_state["runs"]), 1)
        self.assertEqual(len(unit.working_state["audits"]), 1)
        self.assertEqual(len(unit.working_state["events"]["run_t80demo001"]), 1)
        unit.rollback()

    def test_run_repository_only_accepts_runs_with_a_valid_request_digest(self) -> None:
        for bad_digest in ("", "a" * 63, "a" * 65, "Z" * 64, "A" * 64):
            with self.subTest(digest=bad_digest), self.assertRaises(DomainError) as captured:
                WorkflowRun(**_workflow_run_fields(bad_digest))  # type: ignore[arg-type]
            self.assertEqual(captured.exception.code, ERROR_REDACTION)
        unit = self.factory.unit_of_work()
        stored, reused = unit.runs.create_run(
            _run_with_digest(), idempotency_key="idem-t80-demo-001"
        )
        self.assertFalse(reused)
        self.assertEqual(stored.request_digest, DIGEST_A)
        self.assertEqual(unit.runs.get_run("run_t80demo001").request_digest, DIGEST_A)
        unit.rollback()

    def test_committed_flag_is_per_unit_of_work_and_survives_later_commits(self) -> None:
        first = self.factory.unit_of_work()
        self.assertFalse(first.committed)
        first.runs.create_run(_run_with_digest(), idempotency_key="idem-t80-demo-001")
        self.assertFalse(first.committed)
        first.commit()
        self.assertTrue(first.committed)

        second = self.factory.unit_of_work()
        second.runs.create_run(
            _run_with_digest("run_t80demo002", DIGEST_B, idempotency_key="idem-t80-demo-002"),
            idempotency_key="idem-t80-demo-002",
        )
        second.commit()

        # A later commit must not rewrite the first unit of work's own result.
        self.assertTrue(first.committed)
        self.assertTrue(second.committed)
        self.assertTrue(first.committed)

        third = self.factory.unit_of_work()
        third.runs.create_run(
            _run_with_digest("run_t80demo003", DIGEST_A, idempotency_key="idem-t80-demo-003"),
            idempotency_key="idem-t80-demo-003",
        )
        third.rollback()
        self.assertFalse(third.committed)
        self.assertTrue(first.committed)
        reader = self.factory.unit_of_work()
        self.assertEqual(
            sorted(item.run_id for item in reader.runs.list_runs()),
            ["run_t80demo001", "run_t80demo002"],
        )
        reader.rollback()

    def test_rollback_leaves_no_partial_write(self) -> None:
        with self.factory.unit_of_work() as unit:
            unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
            unit.audits.append(_audit(sequence=1))
            unit.artifacts.register(_reference())
            unit.events.publish(_event(sequence=1))
            unit.jobs.enqueue(_job())
            unit.rollback()
        state = self.factory.store.state
        for key in ("runs", "idempotency", "audits", "artifacts", "events", "jobs", "job_idempotency"):
            self.assertEqual(state[key], {}, key)

    def test_commit_makes_the_result_visible_to_the_next_unit_of_work(self) -> None:
        unit = self.factory.unit_of_work()
        unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
        unit.commit()

        reader = self.factory.unit_of_work()
        self.assertEqual([item.run_id for item in reader.runs.list_runs()], ["run_t80demo001"])
        reader.rollback()

    def test_rollback_result_is_invisible_to_the_next_unit_of_work(self) -> None:
        unit = self.factory.unit_of_work()
        unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
        unit.rollback()

        reader = self.factory.unit_of_work()
        self.assertIsNone(reader.runs.get_run("run_t80demo001"))
        self.assertIsNone(reader.runs.get_run_by_idempotency_key("idem-t80-demo-001"))
        self.assertEqual(reader.runs.list_runs(), [])
        reader.rollback()

    def test_overlapping_units_of_work_are_refused(self) -> None:
        first = self.factory.unit_of_work()
        first.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")

        # T80 supports no overlapping transactions: a second unit of work is
        # refused instead of being allowed to observe the first one's private
        # uncommitted data.
        with self.assertRaises(DomainError) as captured:
            self.factory.unit_of_work()
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        self.assertEqual(self.factory.store.state["runs"], {})

        first.commit()
        second = self.factory.unit_of_work()
        # The only thing a later unit of work can see is the committed state.
        self.assertEqual([item.run_id for item in second.runs.list_runs()], ["run_t80demo001"])
        second.rollback()

    def test_a_discarded_unit_of_work_releases_the_single_writer_guard(self) -> None:
        handle = _abandon_a_unit_of_work_with_a_write(self.factory)
        gc.collect()

        # An abandoned unit of work must not lock the store: the guard is a weak
        # reference, so once the caller drops its unit of work the next one can
        # open and the abandoned write is gone because it was never committed.
        self.assertIsNone(self.factory.store.active_unit)
        self.assertEqual(self.factory.store.state["runs"], {})
        with self.assertRaises(DomainError) as captured:
            handle.list_runs()
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        recovered = self.factory.unit_of_work()
        self.assertEqual(recovered.runs.list_runs(), [])
        recovered.rollback()

    def test_saved_repository_reference_is_unusable_after_commit(self) -> None:
        unit = self.factory.unit_of_work()
        handle = unit.runs
        unit.commit()
        self._assert_all_operations_refused(handle)

    def test_saved_repository_reference_is_unusable_after_rollback(self) -> None:
        unit = self.factory.unit_of_work()
        handle = unit.runs
        unit.rollback()
        self._assert_all_operations_refused(handle)

    def _assert_all_operations_refused(self, handle: MemoryRunRepository) -> None:
        operations = (
            lambda: handle.list_runs(),
            lambda: handle.get_run("run_t80demo001"),
            lambda: handle.get_run_by_idempotency_key("idem-t80-demo-001"),
            lambda: handle.create_run(_run(), idempotency_key="idem-t80-demo-001"),
            lambda: handle.update_run_state(
                "run_t80demo001",
                expected_revision=1,
                state="needs_human",
                updated_at=utc_now(),
            ),
        )
        for operation in operations:
            with self.assertRaises(DomainError) as captured:
                operation()
            self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_every_saved_repository_handle_is_unusable_after_the_unit_closes(self) -> None:
        unit = self.factory.unit_of_work()
        handles = (unit.runs, unit.audits, unit.artifacts, unit.events, unit.jobs)
        unit.rollback()
        operations = (
            lambda: handles[0].list_runs(),
            lambda: handles[1].count(),
            lambda: handles[2].count(),
            lambda: handles[3].count(),
            lambda: handles[4].list_jobs(),
        )
        for operation in operations:
            with self.assertRaises(DomainError) as captured:
                operation()
            self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)

    def test_adapters_are_born_bound_to_one_unit_of_work(self) -> None:
        unit = self.factory.unit_of_work()
        for repository in (unit.runs, unit.audits, unit.artifacts, unit.events, unit.jobs):
            with self.subTest(repository=type(repository).__name__):
                self.assertIs(repository._uow_ref(), unit)
        unit.rollback()

    def test_unit_of_work_refuses_use_after_it_closed(self) -> None:
        unit = self.factory.unit_of_work()
        unit.commit()
        with self.assertRaises(DomainError) as captured:
            unit.runs.list_runs()
        self.assertEqual(captured.exception.code, ERROR_STORE_NOT_ACTIVE)
        with self.assertRaises(DomainError):
            unit.commit()
        with self.assertRaises(DomainError):
            unit.rollback()
        with self.assertRaises(DomainError):
            unit.working_state

    def test_context_manager_rolls_back_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.factory.unit_of_work() as unit:
                unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
                raise RuntimeError("synthetic failure inside the transaction")
        self.assertEqual(self.factory.store.state["runs"], {})

    def test_transaction_boundary_is_explicit_and_not_a_database_claim(self) -> None:
        unit = MemoryUnitOfWork(self.factory.store)
        self.assertFalse(unit.committed)
        unit.runs.create_run(_run(), idempotency_key="idem-t80-demo-001")
        unit.commit()
        self.assertTrue(unit.committed)
        documentation = (PACKAGE / "adapters" / "memory.py").read_text(encoding="utf-8")
        self.assertIn("does not claim database transaction semantics", documentation)
        self.assertIn("used for demonstration only", documentation)
        self.assertIn("always holds the committed state", documentation)


class VerticalFlowTests(unittest.TestCase):
    """The documented minimal use case, end to end inside one transaction."""

    def setUp(self) -> None:
        self.factory = MemoryUnitOfWorkFactory()
        self.service = EnterpriseWorkflowService(self.factory)

    def test_vertical_flow_commits_run_artifact_audit_and_event(self) -> None:
        result = self.service.start_workflow_run(_synthetic_request())
        self.assertFalse(result.reused)
        self.assertTrue(result.committed)
        self.assertEqual(result.run_id, "run_t80demo001")
        self.assertEqual(result.state, GovernanceState.DRAFT.value)
        self.assertEqual(result.revision, 1)
        self.assertEqual(len(result.artifact_ids), 1)
        self.assertEqual(len(result.audit_ids), 1)
        self.assertEqual(len(result.event_ids), 2)

        state = self.factory.store.state
        self.assertEqual(set(state["runs"]), {"run_t80demo001"})
        self.assertEqual(len(state["idempotency"]), 1)
        self.assertEqual(len(state["artifacts"]), 1)
        self.assertEqual(len(state["audits"]), 1)
        self.assertEqual([item.sequence for item in state["events"]["run_t80demo001"]], [1, 2])

    def test_vertical_flow_reuses_identical_input_without_duplicate_records(self) -> None:
        first = self.service.start_workflow_run(_synthetic_request())
        second = self.service.start_workflow_run(_synthetic_request())
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.content_digest, second.content_digest)
        self.assertEqual(first.audit_ids, second.audit_ids)
        self.assertEqual(first.event_ids, second.event_ids)
        self.assertEqual(len(self.factory.store.state["audits"]), 1)
        self.assertEqual(len(self.factory.store.state["events"]["run_t80demo001"]), 2)

    def test_vertical_flow_conflicting_replay_fails_closed(self) -> None:
        self.service.start_workflow_run(_synthetic_request())
        with self.assertRaises(DomainError) as captured:
            self.service.start_workflow_run(
                _synthetic_request(task_id="task_t80demo002", run_id="run_t80demo002")
            )
        self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
        self.assertEqual(set(self.factory.store.state["runs"]), {"run_t80demo001"})

    def test_request_digest_is_stable_and_free_of_runtime_timestamps(self) -> None:
        request = _synthetic_request()
        self.assertEqual(request.request_digest(), _synthetic_request().request_digest())
        self.assertRegex(request.request_digest(), r"^[0-9a-f]{64}$")
        # The digest covers every side-effecting field and nothing time based, so
        # two calls at different moments agree while any content change differs.
        changed = {
            "project_id": {"project_id": "PRJ-T80-OTHER"},
            "task_id": {"task_id": "task_t80demo002"},
            "module_version": {"module_version": "t80-demo-other"},
            "result_level": {"result_level": "verified_output"},
            "evidence_class": {"evidence_class": "model_output"},
            "next_action": {"next_action": "awaiting named human sign off"},
            "created_by": {"created_by": "external_tool"},
            "artifacts": {"artifacts": (_synthetic_artifact(digest=DIGEST_B),)},
            "artifact_path": {"artifacts": (_synthetic_artifact(path="enterprise/demo/other.json"),)},
            "audit_entries": {
                "audit_entries": (AuditEntryRequest(action="artifact-registered", summary="second audit entry"),)
            },
            "event_note": {"event_note": "workflow run registered again"},
        }
        for label, overrides in changed.items():
            with self.subTest(field=label):
                self.assertNotEqual(request.request_digest(), _synthetic_request(**overrides).request_digest())

    def test_every_changed_request_field_conflicts_before_any_side_effect(self) -> None:
        self.service.start_workflow_run(_synthetic_request())
        tracked = ("runs", "idempotency", "audits", "artifacts", "events", "jobs", "job_idempotency")
        committed = {key: len(self.factory.store.state[key]) for key in tracked}
        changes = (
            {"next_action": "awaiting named human sign off"},
            {"event_note": "workflow run registered again"},
            {"module_version": "t80-demo-other"},
            {"created_by": "external_tool"},
            {"audit_entries": (AuditEntryRequest(action="artifact-registered", summary="second audit entry"),)},
            {"artifacts": (_synthetic_artifact(digest=DIGEST_B),)},
            {"artifacts": (_synthetic_artifact(path="enterprise/demo/other.json"),)},
        )
        for overrides in changes:
            with self.subTest(overrides=sorted(overrides)):
                with self.assertRaises(DomainError) as captured:
                    self.service.start_workflow_run(_synthetic_request(**overrides))
                self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
                self.assertEqual(
                    {key: len(self.factory.store.state[key]) for key in tracked},
                    committed,
                )

    def test_identical_request_replay_reuses_the_same_binding(self) -> None:
        first = self.service.start_workflow_run(_synthetic_request())
        second = self.service.start_workflow_run(_synthetic_request())
        self.assertEqual(first.request_digest, second.request_digest)
        self.assertEqual(first.run_id, second.run_id)
        self.assertTrue(second.reused)
        self.assertEqual(len(self.factory.store.state["runs"]), 1)
        self.assertEqual(len(self.factory.store.state["audits"]), 1)

    def test_same_content_with_a_different_run_id_needs_its_own_idempotency_key(self) -> None:
        first = self.service.start_workflow_run(_synthetic_request())
        # A different explicit run id with the same key is refused, because the
        # binding is one key -> one run.
        with self.assertRaises(DomainError) as captured:
            self.service.start_workflow_run(_synthetic_request(run_id="run_t80demo009"))
        self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
        self.assertEqual(set(self.factory.store.state["runs"]), {"run_t80demo001"})

        # With its own key and its own artifact reference the same content
        # creates a second, independent run instead of being blocked.
        second = self.service.start_workflow_run(
            _synthetic_request(
                run_id="run_t80demo009",
                idempotency_key="idem-t80-demo-009",
                artifacts=(_synthetic_artifact(path="enterprise/demo/run-nine.json"),),
            )
        )
        self.assertFalse(first.reused)
        self.assertFalse(second.reused)
        self.assertEqual(
            set(self.factory.store.state["runs"]),
            {"run_t80demo001", "run_t80demo009"},
        )
        self.assertEqual(len(self.factory.store.state["artifacts"]), 2)

    def test_rejected_replay_leaves_the_committed_state_untouched(self) -> None:
        self.service.start_workflow_run(_synthetic_request())
        tracked = ("runs", "idempotency", "audits", "artifacts", "events", "jobs", "job_idempotency")
        before = {key: len(self.factory.store.state[key]) for key in tracked}
        variants = (
            _synthetic_request(event_note="workflow run registered again"),
            _synthetic_request(artifacts=(_synthetic_artifact(digest=DIGEST_B),)),
            _synthetic_request(
                audit_entries=(AuditEntryRequest(action="artifact-registered", summary="second audit entry"),)
            ),
            _synthetic_request(next_action="awaiting named human sign off"),
            _synthetic_request(run_id="run_t80demo009"),
        )
        for variant in variants:
            with self.subTest(variant=variant.request_digest()[:8]):
                with self.assertRaises(DomainError) as captured:
                    self.service.start_workflow_run(variant)
                self.assertEqual(captured.exception.code, ERROR_IDEMPOTENCY_CONFLICT)
        self.assertEqual({key: len(self.factory.store.state[key]) for key in tracked}, before)

    def test_vertical_flow_failure_commits_nothing(self) -> None:
        with self.assertRaises(DomainError):
            self.service.start_workflow_run(
                _synthetic_request(
                    artifacts=(
                        _synthetic_artifact(),
                        _synthetic_artifact(digest=DIGEST_B),
                    )
                )
            )
        state = self.factory.store.state
        for key in ("runs", "idempotency", "audits", "artifacts", "events"):
            self.assertEqual(state[key], {}, key)

    def test_convenience_entry_point_matches_the_service(self) -> None:
        result = start_workflow_run(_synthetic_request(), unit_of_work_factory=self.factory)
        self.assertEqual(result.run_id, "run_t80demo001")
        self.assertTrue(result.committed)

    def test_service_advances_state_under_optimistic_concurrency(self) -> None:
        self.service.start_workflow_run(_synthetic_request())
        advanced = self.service.advance_state(
            "run_t80demo001",
            expected_revision=1,
            state="needs_human",
        )
        self.assertEqual((advanced.state, advanced.revision), ("needs_human", 2))
        with self.assertRaises(DomainError) as captured:
            self.service.advance_state("run_t80demo001", expected_revision=1, state="approved")
        self.assertEqual(captured.exception.code, ERROR_REVISION_CONFLICT)

    def test_service_read_paths_do_not_mutate_the_store(self) -> None:
        self.service.start_workflow_run(_synthetic_request())
        before = {key: len(value) for key, value in self.factory.store.state.items()}
        self.assertIsNotNone(self.service.read_run("run_t80demo001"))
        self.assertEqual(len(self.service.list_runs(RunFilters(project_id="PRJ-T80-DEMO"))), 1)
        after = {key: len(value) for key, value in self.factory.store.state.items()}
        self.assertEqual(before, after)

    def test_service_output_is_fully_redacted(self) -> None:
        result = self.service.start_workflow_run(_synthetic_request())
        rendered = str(result.to_dict())
        self.assertNotIn("C:", rendered)
        self.assertNotIn("sk-", rendered)
        for event in self.factory.store.state["events"]["run_t80demo001"]:
            rendered_event = str(event.to_dict())
            self.assertNotIn("/", rendered_event)
            self.assertNotIn("\\", rendered_event)
            self.assertNotIn("355", rendered_event)
            self.assertTrue(set(event.payload).issubset(EVENT_PAYLOAD_FIELDS))

    def test_service_uses_no_environment_variable_or_network(self) -> None:
        source = inspect.getsource(EnterpriseWorkflowService)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("socket", source)
        modules = _imported_modules(PACKAGE / "application" / "services.py")
        self.assertFalse({"os", "socket", "tempfile", "shutil"} & modules)


if __name__ == "__main__":
    unittest.main()
