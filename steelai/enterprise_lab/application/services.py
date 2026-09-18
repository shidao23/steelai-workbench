"""Application services of the Enterprise Lab.

The service demonstrates one minimal vertical flow inside a single transaction
boundary and nothing else:

    create workflow run
      -> register artifact metadata
      -> append audit event
      -> publish domain event
      -> commit the unit of work

Only public synthetic metadata is used. The service never reads a research file,
never opens the repository tree, never calls a database or broker and never
touches the system temporary directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from steelai.governance.models import EvidenceClass, GovernanceState, ResultLevel
from steelai.governance.serialization import digest_value

from ..domain.models import (
    ACTOR_ROLES,
    ArtifactReference,
    AuditEvent,
    DomainError,
    DomainEvent,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_REDACTION,
    WorkflowRun,
    sanitize_summary,
    utc_now,
    validate_identifier,
    validate_relative_reference,
)
from ..ports.repositories import RunFilters, UnitOfWork


class UnitOfWorkFactory(Protocol):
    """Creates unit-of-work transactions over one storage backend.

    T82 replaces the in-memory implementation with a PostgreSQL-backed one; the
    application service needs no change. Reads use the same explicit unit of work
    and are simply rolled back, so there is one transaction boundary only.
    """

    def unit_of_work(self) -> UnitOfWork:
        ...


@dataclass(frozen=True)
class RunArtifactRequest:
    """Public synthetic artifact metadata: a reference, a digest, a type, a version."""

    relative_path: str
    sha256: str
    artifact_type: str
    artifact_version: str

    def __post_init__(self) -> None:
        validate_relative_reference(self.relative_path, "relative_path")
        validate_identifier(self.artifact_type, "artifact_type")
        validate_identifier(self.artifact_version, "artifact_version")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise DomainError(ERROR_REDACTION, "sha256 must be a lowercase SHA-256 digest")

    def declarative(self) -> dict[str, str]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "artifact_type": self.artifact_type,
            "artifact_version": self.artifact_version,
        }


@dataclass(frozen=True)
class AuditEntryRequest:
    """Requested append-only audit record."""

    action: str
    summary: str
    actor_role: str = "human"
    actor_id: str = "owner"

    def __post_init__(self) -> None:
        validate_identifier(self.action, "action")
        sanitize_summary(self.summary, "summary")
        validate_identifier(self.actor_id, "actor_id")
        if self.actor_role not in ACTOR_ROLES:
            raise DomainError(ERROR_REDACTION, "actor_role must be a declared governance actor")

    def declarative(self) -> dict[str, str]:
        return {
            "action": self.action,
            "summary": self.summary,
            "actor_role": self.actor_role,
            "actor_id": self.actor_id,
        }


@dataclass(frozen=True)
class WorkflowRunRequest:
    """Input of the vertical flow. Synthetic metadata only."""

    project_id: str
    task_id: str
    idempotency_key: str
    run_id: str | None = None
    module_version: str = "t80-demo"
    result_level: str = ResultLevel.WORKING_CANDIDATE.value
    evidence_class: str = EvidenceClass.SYNTHETIC_DEMO_DATA.value
    next_action: str = "awaiting named human review"
    created_by: str = "system"
    artifacts: tuple[RunArtifactRequest, ...] = ()
    audit_entries: tuple[AuditEntryRequest, ...] = ()
    event_note: str = "workflow run registered"

    def __post_init__(self) -> None:
        validate_identifier(self.project_id, "project_id")
        validate_identifier(self.task_id, "task_id")
        validate_identifier(self.idempotency_key, "idempotency_key")
        validate_identifier(self.module_version, "module_version")
        ResultLevel(self.result_level)
        EvidenceClass(self.evidence_class)
        sanitize_summary(self.next_action, "next_action")
        sanitize_summary(self.event_note, "event_note")
        validate_identifier(self.created_by, "created_by")
        if self.run_id is not None:
            validate_identifier(self.run_id, "run_id")

    def request_digest(self) -> str:
        """Stable digest of this request, covering every side-effecting field.

        Covered: project, task, module version, result level, evidence class,
        next action, creator, artifacts, audit entries and the event note. No
        runtime timestamp (or derived run id) is included, so the digest is
        reproducible and identical replay is recognised as the same request.
        """
        return digest_value(
            {
                "project_id": self.project_id,
                "task_id": self.task_id,
                "module_version": self.module_version,
                "result_level": self.result_level,
                "evidence_class": self.evidence_class,
                "next_action": self.next_action,
                "created_by": self.created_by,
                "artifacts": [item.declarative() for item in self.artifacts],
                "audit_entries": [item.declarative() for item in self.audit_entries],
                "event_note": self.event_note,
            }
        )


@dataclass(frozen=True)
class WorkflowRunResult:
    """Output of the vertical flow, fully redacted."""

    run_id: str
    state: str
    revision: int
    content_digest: str
    reused: bool
    request_digest: str = ""
    artifact_ids: tuple[str, ...] = ()
    artifact_digests: tuple[str, ...] = ()
    audit_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    committed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "reused": self.reused,
            "request_digest": self.request_digest,
            "artifact_ids": list(self.artifact_ids),
            "artifact_digests": list(self.artifact_digests),
            "audit_ids": list(self.audit_ids),
            "event_ids": list(self.event_ids),
            "committed": self.committed,
        }


def _replay_result(
    stored: WorkflowRun,
    *,
    request_digest: str,
    references: Sequence[Any],
    audit_ids: Sequence[str],
    event_ids: Sequence[str],
) -> WorkflowRunResult:
    return WorkflowRunResult(
        run_id=stored.run_id,
        state=stored.state,
        revision=stored.revision,
        content_digest=stored.content_digest,
        reused=True,
        request_digest=request_digest,
        artifact_ids=tuple(item.artifact_id for item in references),
        artifact_digests=tuple(item.sha256 for item in references),
        audit_ids=tuple(audit_ids),
        event_ids=tuple(event_ids),
        committed=True,
    )


def _derived_run_id(idempotency_key: str, request: WorkflowRunRequest) -> str:
    return "run_" + digest_value(
        {"idempotency_key": idempotency_key, "request_digest": request.request_digest()}
    )[:40]


class EnterpriseWorkflowService:
    """Minimal vertical use case over the Enterprise Lab ports."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def start_workflow_run(self, request: WorkflowRunRequest) -> WorkflowRunResult:
        # The request digest is computed from the full request before any
        # side effect, and the run id is derived from it, so a replay is
        # recognised as the same request and a changed request fails closed.
        request_digest = request.request_digest()
        run_id = request.run_id or _derived_run_id(request.idempotency_key, request)
        run = WorkflowRun.create(
            run_id=run_id,
            project_id=request.project_id,
            task_id=request.task_id,
            idempotency_key=request.idempotency_key,
            request_digest=request_digest,
            created_by=request.created_by,
            state=GovernanceState.DRAFT.value,
            result_level=request.result_level,
            evidence_class=request.evidence_class,
            next_action=request.next_action,
        )
        with self._unit_of_work_factory.unit_of_work() as unit:
            # Idempotency is decided inside this one transaction, before any
            # artifact, audit record or domain event is written. The replay branch
            # only reads existing records and is rolled back on exit.
            known = unit.runs.get_run_by_idempotency_key(request.idempotency_key)
            if known is not None:
                if known.request_digest != request_digest or known.run_id != run_id:
                    raise DomainError(
                        ERROR_IDEMPOTENCY_CONFLICT,
                        "idempotency key is already bound to a different run request",
                        details={
                            "idempotency_key": request.idempotency_key,
                            "bound_run_id": known.run_id,
                        },
                    )
                replayed = _replay_result(
                    known,
                    request_digest=request_digest,
                    references=unit.artifacts.list_for_run(known.run_id),
                    audit_ids=[item.audit_id for item in unit.audits.list_events(known.run_id)],
                    event_ids=[item.event_id for item in unit.events.replay(known.run_id)],
                )
                unit.rollback()
                return replayed

            # create_run re-validates the binding and is still the only writer of
            # the run record, so the guard holds even if the probe above changes.
            stored, reused = unit.runs.create_run(run, idempotency_key=request.idempotency_key)
            if reused:
                replayed = _replay_result(
                    stored,
                    request_digest=request_digest,
                    references=unit.artifacts.list_for_run(stored.run_id),
                    audit_ids=[item.audit_id for item in unit.audits.list_events(stored.run_id)],
                    event_ids=[item.event_id for item in unit.events.replay(stored.run_id)],
                )
                unit.rollback()
                return replayed
            artifact_ids: list[str] = []
            artifact_digests: list[str] = []
            for item in request.artifacts:
                reference = ArtifactReference.create(
                    relative_path=item.relative_path,
                    sha256=item.sha256,
                    artifact_type=item.artifact_type,
                    artifact_version=item.artifact_version,
                    run_id=stored.run_id,
                )
                reference, _ = unit.artifacts.register(reference)
                artifact_ids.append(reference.artifact_id)
                artifact_digests.append(reference.sha256)
            audit_ids = self._append_audits(unit, stored, request)
            event_ids = self._publish_events(unit, stored, request, artifact_digests)
            unit.commit()
        return WorkflowRunResult(
            run_id=stored.run_id,
            state=stored.state,
            revision=stored.revision,
            content_digest=stored.content_digest,
            reused=reused,
            artifact_ids=tuple(artifact_ids),
            artifact_digests=tuple(artifact_digests),
            audit_ids=tuple(audit_ids),
            event_ids=tuple(event_ids),
            request_digest=request_digest,
            committed=True,
        )

    def _append_audits(
        self,
        unit: UnitOfWork,
        run: WorkflowRun,
        request: WorkflowRunRequest,
    ) -> list[str]:
        audit_ids: list[str] = []
        entries = request.audit_entries or (
            AuditEntryRequest(action="run-registered", summary="workflow run registered"),
        )
        for entry in entries:
            event = AuditEvent.create(
                sequence=unit.audits.count() + 1,
                run_id=run.run_id,
                action=entry.action,
                actor_role=entry.actor_role,
                actor_id=entry.actor_id,
                summary=entry.summary,
                object_type="workflow_run",
                object_id=run.run_id,
                object_revision=run.revision,
                object_digest=run.content_digest,
            )
            unit.audits.append(event)
            audit_ids.append(event.audit_id)
        return audit_ids

    def _publish_events(
        self,
        unit: UnitOfWork,
        run: WorkflowRun,
        request: WorkflowRunRequest,
        artifact_digests: Sequence[str],
    ) -> list[str]:
        event_ids: list[str] = []
        payloads = [
            {
                "project_id": run.project_id,
                "task_id": run.task_id,
                "state": run.state,
                "previous_state": run.state,
                "revision": run.revision,
                "result_level": run.result_level,
                "evidence_class": run.evidence_class,
                "summary": request.event_note,
            }
        ]
        for digest in artifact_digests:
            payloads.append(
                {
                    "state": run.state,
                    "revision": run.revision,
                    "artifact_sha256": digest,
                    "summary": "artifact reference registered",
                }
            )
        for payload in payloads:
            event = DomainEvent.create(
                event_type="enterprise.workflow_run.registered",
                run_id=run.run_id,
                sequence=unit.events.next_sequence(run.run_id),
                payload=payload,
            )
            unit.events.publish(event)
            event_ids.append(event.event_id)
        return event_ids

    def read_run(self, run_id: str) -> WorkflowRun | None:
        """Read one run inside a unit of work and roll it back."""
        with self._unit_of_work_factory.unit_of_work() as unit:
            run = unit.runs.get_run(run_id)
            unit.rollback()
        return run

    def list_runs(self, filters: RunFilters | None = None) -> Sequence[WorkflowRun]:
        """List runs inside a unit of work and roll it back."""
        with self._unit_of_work_factory.unit_of_work() as unit:
            runs = unit.runs.list_runs(filters)
            unit.rollback()
        return runs

    def advance_state(
        self,
        run_id: str,
        *,
        expected_revision: int,
        state: str,
    ) -> WorkflowRun:
        """Advance a run state under an explicit optimistic-concurrency check."""
        with self._unit_of_work_factory.unit_of_work() as unit:
            updated = unit.runs.update_run_state(
                run_id,
                expected_revision=expected_revision,
                state=state,
                updated_at=utc_now(),
            )
            unit.commit()
        return updated


def start_workflow_run(
    request: WorkflowRunRequest,
    *,
    unit_of_work_factory: UnitOfWorkFactory,
) -> WorkflowRunResult:
    """Convenience entry point for the documented vertical flow."""
    return EnterpriseWorkflowService(unit_of_work_factory).start_workflow_run(request)


__all__ = [
    "AuditEntryRequest",
    "EnterpriseWorkflowService",
    "RunArtifactRequest",
    "UnitOfWorkFactory",
    "WorkflowRunRequest",
    "WorkflowRunResult",
    "start_workflow_run",
]
