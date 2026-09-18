"""Deterministic database-row to domain-object hydration for T82.

Every function takes a plain mapping of column values and returns a validated T80
domain object. Nothing here lets a SQLAlchemy ``Row``, a ``Connection`` or an
infrastructure-only column (delivery status, attempts, lease bookkeeping) reach the
domain layer: the payload is re-validated through the frozen
``validate_event_payload`` whitelist and every identifier, digest, revision and
timestamp is re-checked by the dataclass itself.

Timestamps are normalised to timezone-aware ISO-8601 strings so a value read back
from PostgreSQL compares equal to the one that was written.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import RowMapping

from steelai.enterprise_lab.domain.models import (
    ERROR_REDACTION,
    ArtifactReference,
    AuditEvent,
    BackgroundJob,
    DomainError,
    DomainEvent,
    GovernanceState,
    ResultLevel,
    EvidenceClass,
    JobState,
    WorkflowRun,
    validate_event_payload,
)


def _require_governance_state(value: Any, field_name: str) -> str:
    """Validate a state column against the frozen vocabulary with a stable error.

    The ``str``-valued enums raise ``ValueError`` on an unknown member, which would
    otherwise escape the adapter as an unstructured exception; the adapter converts
    it into a redacted ``DomainError`` instead.
    """
    try:
        return GovernanceState(value).value
    except ValueError:
        raise DomainError(
            ERROR_REDACTION, f"{field_name} is not a declared governance state"
        ) from None


def _require_result_level(value: Any) -> str:
    try:
        return ResultLevel(value).value
    except ValueError:
        raise DomainError(ERROR_REDACTION, "result_level is not a declared result level") from None


def _require_evidence_class(value: Any) -> str:
    try:
        return EvidenceClass(value).value
    except ValueError:
        raise DomainError(ERROR_REDACTION, "evidence_class is not a declared evidence class") from None


def _require_job_state(value: Any) -> str:
    try:
        return JobState(value).value
    except ValueError:
        raise DomainError(ERROR_REDACTION, "state is not a declared job state") from None


def to_iso8601(value: Any) -> str:
    """Normalise a timestamp to an ISO-8601 string that always carries a timezone.

    ``TIMESTAMPTZ`` values come back as aware ``datetime`` objects; naive values are
    rejected rather than silently assumed to be UTC.
    """
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("timestamp column must be a datetime or an ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp column must carry a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def to_json_mapping(value: Any) -> dict[str, Any]:
    """Return a plain ``dict`` for a JSONB column, rejecting anything else."""
    if not isinstance(value, Mapping):
        raise ValueError("payload column must be a JSON object")
    return dict(value)


def hydrate_workflow_run(row: RowMapping | Mapping[str, Any]) -> WorkflowRun:
    """Rebuild a :class:`WorkflowRun` from a ``workflow_runs`` row."""
    return WorkflowRun(
        run_id=row["run_id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        state=_require_governance_state(row["state"], "state"),
        revision=row["revision"],
        content_digest=row["content_digest"],
        result_level=_require_result_level(row["result_level"]),
        evidence_class=_require_evidence_class(row["evidence_class"]),
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        created_at=to_iso8601(row["created_at"]),
        updated_at=to_iso8601(row["updated_at"]),
        created_by=row["created_by"],
        next_action=row["next_action"],
    )


def hydrate_artifact_reference(row: RowMapping | Mapping[str, Any]) -> ArtifactReference:
    """Rebuild an :class:`ArtifactReference` from an ``artifact_references`` row."""
    return ArtifactReference(
        artifact_id=row["artifact_id"],
        relative_path=row["relative_path"],
        sha256=row["sha256"],
        artifact_type=row["artifact_type"],
        artifact_version=row["artifact_version"],
        run_id=row["run_id"],
        created_at=to_iso8601(row["created_at"]),
    )


def hydrate_audit_event(row: RowMapping | Mapping[str, Any]) -> AuditEvent:
    """Rebuild an :class:`AuditEvent` from an ``audit_events`` row."""
    return AuditEvent(
        audit_id=row["audit_id"],
        sequence=row["sequence"],
        run_id=row["run_id"],
        action=row["action"],
        actor_role=row["actor_role"],
        actor_id=row["actor_id"],
        summary=row["summary"],
        occurred_at=to_iso8601(row["occurred_at"]),
        object_type=row["object_type"],
        object_id=row["object_id"],
        object_revision=row["object_revision"],
        object_digest=row["object_digest"],
    )


def hydrate_domain_event(row: RowMapping | Mapping[str, Any]) -> DomainEvent:
    """Rebuild a :class:`DomainEvent` from an ``outbox_events`` row.

    ``delivery_status``, ``attempts``, ``available_at``, ``published_at`` and
    ``last_error_code`` are dispatcher infrastructure and are deliberately dropped;
    the payload goes back through the domain whitelist.
    """
    payload = validate_event_payload(to_json_mapping(row["payload"]))
    return DomainEvent(
        event_id=row["event_id"],
        event_type=row["event_type"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        payload=payload,
        occurred_at=to_iso8601(row["occurred_at"]),
    )


def hydrate_background_job(row: RowMapping | Mapping[str, Any]) -> BackgroundJob:
    """Rebuild a :class:`BackgroundJob` from a ``background_jobs`` row.

    ``request_digest`` is stored for the duplicate-key decision and is recomputed by
    ``BackgroundJob.request_digest()``; it is verified instead of carried into the
    domain object.
    """
    job = BackgroundJob(
        job_id=row["job_id"],
        job_type=row["job_type"],
        run_id=row["run_id"],
        state=_require_job_state(row["state"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        idempotency_key=row["idempotency_key"],
        payload_digest=row["payload_digest"],
        created_at=to_iso8601(row["created_at"]),
        updated_at=to_iso8601(row["updated_at"]),
        lease_id=row["lease_id"],
        error_code=row["error_code"],
    )
    stored_digest = row["request_digest"]
    if stored_digest != job.request_digest():
        raise ValueError("stored job request_digest does not match the persisted request fields")
    return job


#: Hydration functions by table name, used by the repositories and the tests.
HYDRATORS = {
    "workflow_runs": hydrate_workflow_run,
    "artifact_references": hydrate_artifact_reference,
    "audit_events": hydrate_audit_event,
    "outbox_events": hydrate_domain_event,
    "background_jobs": hydrate_background_job,
}


__all__ = [
    "HYDRATORS",
    "hydrate_artifact_reference",
    "hydrate_audit_event",
    "hydrate_background_job",
    "hydrate_domain_event",
    "hydrate_workflow_run",
    "to_iso8601",
    "to_json_mapping",
]
