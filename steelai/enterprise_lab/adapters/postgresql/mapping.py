"""Domain-to-PostgreSQL mapping contract for the Enterprise Lab (T81).

This module documents and machine-checks how the frozen T80 domain objects map
to the PostgreSQL tables. It deliberately contains **no repository and no unit of
work**: T81 establishes the schema and the mapping contract, T82 implements the
adapters that satisfy the existing ports.

The mapping is expressed as data so tests can prove that every persisted domain
field is covered and that infrastructure-only columns never leak into the domain.

Row-construction helpers below are pure functions from a domain object to a plain
dictionary of column values. They perform no I/O, open no session and are the
single place T82 will reuse for INSERT statements.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from steelai.enterprise_lab.domain.models import (
    ArtifactReference,
    AuditEvent,
    BackgroundJob,
    DomainEvent,
    WorkflowRun,
)


@dataclass(frozen=True)
class TableMapping:
    """Declarative description of one domain object to table mapping.

    Three groups of columns are distinguished:

    - ``fields``: a column that mirrors a domain attribute one to one;
    - ``adaptation_fields``: a column that still carries a domain value but whose
      shape is chosen by the database (for example ``payload`` as JSONB), so the
      domain attribute name and the column name can differ;
    - ``infrastructure_fields``: a column the domain object has no attribute for
      at all, filled under explicit non-domain rules (outbox dispatcher state).
    """

    table_name: str
    domain_object: str
    fields: tuple[tuple[str, str], ...]
    infrastructure_fields: tuple[str, ...] = ()
    adaptation_fields: tuple[tuple[str, str], ...] = ()
    notes: str = ""

    def domain_fields(self) -> tuple[str, ...]:
        return tuple(column for column, _ in self.fields) + tuple(
            column for column, _ in self.adaptation_fields
        )

    def domain_attributes(self) -> tuple[str, ...]:
        return tuple(attribute for _, attribute in self.fields) + tuple(
            attribute for _, attribute in self.adaptation_fields
        )


#: Delivery states of the outbox row. Not a domain state: the delivery lifecycle
#: belongs to the future dispatcher, not to DomainEvent.
DELIVERY_PENDING = "pending"


WORKFLOW_RUN_MAPPING = TableMapping(
    table_name="workflow_runs",
    domain_object="WorkflowRun",
    fields=(
        ("run_id", "run_id"),
        ("project_id", "project_id"),
        ("task_id", "task_id"),
        ("state", "state"),
        ("revision", "revision"),
        ("content_digest", "content_digest"),
        ("result_level", "result_level"),
        ("evidence_class", "evidence_class"),
        ("idempotency_key", "idempotency_key"),
        ("request_digest", "request_digest"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
        ("created_by", "created_by"),
        ("next_action", "next_action"),
    ),
    notes="Every persisted WorkflowRun field maps one to one; project_id stays an externally validated identifier.",
)

ARTIFACT_REFERENCE_MAPPING = TableMapping(
    table_name="artifact_references",
    domain_object="ArtifactReference",
    fields=(
        ("artifact_id", "artifact_id"),
        ("relative_path", "relative_path"),
        ("sha256", "sha256"),
        ("artifact_type", "artifact_type"),
        ("artifact_version", "artifact_version"),
        ("run_id", "run_id"),
        ("created_at", "created_at"),
    ),
    notes="Reference and digest only: no file bytes, no absolute path, no approval meaning.",
)

AUDIT_EVENT_MAPPING = TableMapping(
    table_name="audit_events",
    domain_object="AuditEvent",
    fields=(
        ("audit_id", "audit_id"),
        ("sequence", "sequence"),
        ("run_id", "run_id"),
        ("action", "action"),
        ("actor_role", "actor_role"),
        ("actor_id", "actor_id"),
        ("summary", "summary"),
        ("occurred_at", "occurred_at"),
        ("object_type", "object_type"),
        ("object_id", "object_id"),
        ("object_revision", "object_revision"),
        ("object_digest", "object_digest"),
    ),
    notes="Append-only: the initial migration adds a trigger that rejects UPDATE and DELETE.",
)

OUTBOX_EVENT_MAPPING = TableMapping(
    table_name="outbox_events",
    domain_object="DomainEvent",
    fields=(
        ("event_id", "event_id"),
        ("event_type", "event_type"),
        ("run_id", "run_id"),
        ("sequence", "sequence"),
        ("occurred_at", "occurred_at"),
    ),
    adaptation_fields=(("payload", "payload"),),
    infrastructure_fields=(
        "delivery_status",
        "attempts",
        "available_at",
        "published_at",
        "last_error_code",
    ),
    notes=(
        "DomainEvent becomes an outbox row. payload is the redacted DomainEvent payload stored as JSONB, so "
        "the column is an adaptation of a domain value; delivery_status, attempts, available_at, published_at "
        "and last_error_code are dispatcher infrastructure that outbox_event_row() fills with explicit "
        "defaults. T81 creates the table only: no dispatcher, no Kafka and no exactly-once claim."
    ),
)

BACKGROUND_JOB_MAPPING = TableMapping(
    table_name="background_jobs",
    domain_object="BackgroundJob",
    fields=(
        ("job_id", "job_id"),
        ("job_type", "job_type"),
        ("run_id", "run_id"),
        ("state", "state"),
        ("attempts", "attempts"),
        ("max_attempts", "max_attempts"),
        ("idempotency_key", "idempotency_key"),
        ("request_digest", "request_digest"),
        ("payload_digest", "payload_digest"),
        ("created_at", "created_at"),
        ("updated_at", "updated_at"),
        ("lease_id", "lease_id"),
        ("error_code", "error_code"),
    ),
    notes=(
        "request_digest is the persisted idempotency binding required for a stable duplicate-key "
        "decision; it is derived by BackgroundJob.request_digest() rather than passed in, and "
        "background_job_row() always fills it from the domain object."
    ),
)

TABLE_MAPPINGS = (
    WORKFLOW_RUN_MAPPING,
    ARTIFACT_REFERENCE_MAPPING,
    AUDIT_EVENT_MAPPING,
    OUTBOX_EVENT_MAPPING,
    BACKGROUND_JOB_MAPPING,
)


def workflow_run_row(run: WorkflowRun) -> dict[str, Any]:
    """Column values for one ``workflow_runs`` row. Pure function, no I/O."""
    return {
        "run_id": run.run_id,
        "project_id": run.project_id,
        "task_id": run.task_id,
        "state": run.state,
        "revision": run.revision,
        "content_digest": run.content_digest,
        "result_level": run.result_level,
        "evidence_class": run.evidence_class,
        "idempotency_key": run.idempotency_key,
        "request_digest": run.request_digest,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "created_by": run.created_by,
        "next_action": run.next_action,
    }


def artifact_reference_row(reference: ArtifactReference) -> dict[str, Any]:
    """Column values for one ``artifact_references`` row. Pure function, no I/O."""
    return {
        "artifact_id": reference.artifact_id,
        "run_id": reference.run_id,
        "relative_path": reference.relative_path,
        "sha256": reference.sha256,
        "artifact_type": reference.artifact_type,
        "artifact_version": reference.artifact_version,
        "created_at": reference.created_at,
    }


def audit_event_row(event: AuditEvent) -> dict[str, Any]:
    """Column values for one ``audit_events`` row. Pure function, no I/O."""
    return {
        "audit_id": event.audit_id,
        "sequence": event.sequence,
        "run_id": event.run_id,
        "action": event.action,
        "actor_role": event.actor_role,
        "actor_id": event.actor_id,
        "summary": event.summary,
        "occurred_at": event.occurred_at,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "object_revision": event.object_revision,
        "object_digest": event.object_digest,
    }


def outbox_event_row(
    event: DomainEvent,
    *,
    delivery_status: str = DELIVERY_PENDING,
    attempts: int = 0,
    available_at: str | None = None,
) -> dict[str, Any]:
    """Column values for one ``outbox_events`` row, including dispatcher defaults.

    The domain layer never sets delivery state, so those values are explicit
    dispatcher-side inputs rather than domain fields.
    """
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "payload": dict(event.payload),
        "occurred_at": event.occurred_at,
        "delivery_status": delivery_status,
        "attempts": attempts,
        "available_at": available_at or event.occurred_at,
        "published_at": None,
        "last_error_code": None,
    }


def background_job_row(job: BackgroundJob) -> dict[str, Any]:
    """Column values for one ``background_jobs`` row. Pure function, no I/O."""
    return {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "run_id": job.run_id,
        "state": job.state,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "idempotency_key": job.idempotency_key,
        "request_digest": job.request_digest(),
        "payload_digest": job.payload_digest,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "lease_id": job.lease_id,
        "error_code": job.error_code,
    }


ROW_BUILDERS = {
    "workflow_runs": workflow_run_row,
    "artifact_references": artifact_reference_row,
    "audit_events": audit_event_row,
    "outbox_events": outbox_event_row,
    "background_jobs": background_job_row,
}


def mapping_report() -> dict[str, Mapping[str, Any]]:
    """A machine-readable summary of the mapping contract for tests and reports."""
    return {
        item.table_name: {
            "domain_object": item.domain_object,
            "domain_fields": item.domain_fields(),
            "domain_attributes": item.domain_attributes(),
            "infrastructure_fields": item.infrastructure_fields,
            "notes": item.notes,
        }
        for item in TABLE_MAPPINGS
    }


__all__ = [
    "ARTIFACT_REFERENCE_MAPPING",
    "AUDIT_EVENT_MAPPING",
    "BACKGROUND_JOB_MAPPING",
    "DELIVERY_PENDING",
    "OUTBOX_EVENT_MAPPING",
    "ROW_BUILDERS",
    "TABLE_MAPPINGS",
    "TableMapping",
    "WORKFLOW_RUN_MAPPING",
    "artifact_reference_row",
    "audit_event_row",
    "background_job_row",
    "mapping_report",
    "outbox_event_row",
    "workflow_run_row",
]
