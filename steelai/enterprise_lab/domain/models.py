"""Stable domain objects for the SteelAI Enterprise Lab (T80).

Every object carries an explicit stable ID, revision, state, creation time and
content digest. Digests reuse the shared governance canonical-JSON + SHA-256
rule, and run states reuse the frozen T50 governance vocabulary, so the
Enterprise Lab does not introduce a second scientific state machine.

Hard boundaries enforced here:

- no raw experimental values: descriptive text fields reject digits, so a value
  can never travel through a run record, an audit record or a domain event;
- no absolute paths, UNC paths, URL schemes or path separators in identifiers or
  text summaries; artifact references accept a safe relative POSIX path only;
- no secrets: the listed credential patterns are rejected;
- no model output presented as experimental fact: ``WorkflowRun`` refuses
  ``model_output`` combined with ``accepted_evidence``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping

from steelai.governance.errors import GovernanceError
from steelai.governance.models import EvidenceClass, GovernanceState, ResultLevel
from steelai.governance.serialization import digest_value


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
#: Stable content identities derived from the canonical JSON digest, e.g.
#: ``run_<40 hex>``, matching the existing ``request_``/``task_``/``run_`` family.
CONTENT_DIGEST_PATTERN = re.compile(r"^[a-z]{2,8}_[0-9a-f]{32,64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,159}$")
_ABSOLUTE_PATH_PATTERN = re.compile(r"(?:^|[\s(\[])(?:[A-Za-z]:[\\/]|[\\/]{2}|/(?:[A-Za-z0-9._-]+/)+)")
_SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{12,}|gh[opusr]_[A-Za-z0-9]{12,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|://|(?:password|passwd|secret|token|apikey|api_key)\s*[:=])",
    re.IGNORECASE,
)

#: Text fields that must stay descriptive: IDs, states, versions, hashes and a
#: redacted summary are allowed; raw measurements and paths are not.
TEXT_FORBIDDEN_CHARACTERS = "0123456789/\\<>|"

#: Run states usable by the Enterprise Lab. Values are the frozen T50 states.
RUN_STATES = (
    GovernanceState.DRAFT,
    GovernanceState.NEEDS_HUMAN,
    GovernanceState.APPROVED,
    GovernanceState.RUNNING,
    GovernanceState.PASSED,
    GovernanceState.WARNING,
    GovernanceState.REJECTED,
    GovernanceState.BLOCKED,
    GovernanceState.COMPLETE,
    GovernanceState.INVALIDATED,
)

#: Human accountability roles that the Enterprise Lab records.
ACTOR_ROLES = ("human", "system", "external_tool")

#: Error codes. ``GOV-*`` codes are inherited from the shared governance core;
#: ``ENT-*`` codes are owned by the Enterprise Lab.
ERROR_IDEMPOTENCY_CONFLICT = "ENT-IDEMPOTENCY-001"
ERROR_REVISION_CONFLICT = "ENT-CONCURRENCY-001"
ERROR_UNKNOWN_RUN = "ENT-NOTFOUND-001"
ERROR_AUDIT_APPEND_ONLY = "ENT-AUDIT-001"
ERROR_ARTIFACT_CONFLICT = "ENT-ARTIFACT-001"
ERROR_JOB_TRANSITION = "ENT-JOB-001"
ERROR_STORE_NOT_ACTIVE = "ENT-UOW-001"
ERROR_EVENT_ORDER = "ENT-EVENT-001"
ERROR_REDACTION = "ENT-REDACTION-001"


class DomainError(GovernanceError):
    """Fail-closed Enterprise Lab rejection with a stable code and state."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code, GovernanceState.BLOCKED.value, message, details=dict(details or {}))


class JobState(str, Enum):
    """Background-job lifecycle. T80 defines the states only; no worker exists."""

    QUEUED = "queued"
    LEASED = "leased"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Legal job transitions. T80 implements no concurrent worker, so the queue
#: itself must refuse every illegal path.
ALLOWED_JOB_TRANSITIONS: Mapping[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.LEASED, JobState.CANCELLED}),
    JobState.LEASED: frozenset({JobState.SUCCEEDED, JobState.FAILED}),
    JobState.RETRYING: frozenset({JobState.LEASED, JobState.CANCELLED}),
    JobState.FAILED: frozenset({JobState.RETRYING}),
    JobState.SUCCEEDED: frozenset(),
    JobState.CANCELLED: frozenset(),
}

TERMINAL_JOB_STATES = frozenset({JobState.SUCCEEDED, JobState.CANCELLED})


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with an explicit timezone."""
    return datetime.now(timezone.utc).isoformat()


def validate_timestamp(value: str, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DomainError(ERROR_REDACTION, f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DomainError(ERROR_REDACTION, f"{field_name} must include a timezone")
    return value


def validate_digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise DomainError(ERROR_REDACTION, f"{field_name} must be a lowercase SHA-256 digest")
    return value


def validate_content_digest(value: str, field_name: str) -> str:
    """Accept the stable ``prefix_<hex>`` content identity of a domain object."""
    if not isinstance(value, str) or not CONTENT_DIGEST_PATTERN.fullmatch(value):
        raise DomainError(
            ERROR_REDACTION,
            f"{field_name} must be a stable content identity such as run_<hex>",
        )
    return value


def validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise DomainError(
            ERROR_REDACTION,
            f"{field_name} must be a stable identifier, not a path or free text",
        )
    return value


def validate_revision(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DomainError(ERROR_REDACTION, f"{field_name} must be a positive integer")
    return value


def validate_relative_reference(value: str, field_name: str) -> str:
    """Accept a safe relative POSIX path only (no absolute path, no traversal)."""
    if not isinstance(value, str) or not value or len(value) > 240:
        raise DomainError(ERROR_ARTIFACT_CONFLICT, f"{field_name} must be a non-empty relative reference")
    if "\\" in value or ":" in value or "\x00" in value:
        raise DomainError(ERROR_ARTIFACT_CONFLICT, f"{field_name} must not contain a drive or backslash")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise DomainError(ERROR_ARTIFACT_CONFLICT, f"{field_name} must not be absolute or contain traversal")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise DomainError(ERROR_ARTIFACT_CONFLICT, f"{field_name} must contain only non-empty path segments")
    return value


def sanitize_summary(value: str, field_name: str, *, max_length: int = 240) -> str:
    """Validate a redacted descriptive summary.

    Digit-free by construction: a raw experimental value, a size, a path and a
    credential all require characters that this boundary refuses.
    """
    if not isinstance(value, str) or not value.strip():
        raise DomainError(ERROR_REDACTION, f"{field_name} must be a non-empty summary")
    if len(value) > max_length:
        raise DomainError(ERROR_REDACTION, f"{field_name} must be at most {max_length} characters")
    if any(character in value for character in TEXT_FORBIDDEN_CHARACTERS):
        raise DomainError(
            ERROR_REDACTION,
            f"{field_name} must be a redacted summary without digits, paths or separators",
            details={"forbidden_characters": TEXT_FORBIDDEN_CHARACTERS},
        )
    if "\r" in value or "\n" in value or "\t" in value:
        raise DomainError(ERROR_REDACTION, f"{field_name} must be a single-line summary")
    if _ABSOLUTE_PATH_PATTERN.search(value) or _SECRET_PATTERN.search(value):
        raise DomainError(ERROR_REDACTION, f"{field_name} contains a path or credential pattern")
    return value


def _content_digest(prefix: str, fields: Mapping[str, Any]) -> str:
    return prefix + digest_value(dict(fields))


@dataclass(frozen=True)
class EnterpriseProject:
    """A named container for run records. Business metadata only."""

    project_id: str
    name: str
    created_at: str = field(default_factory=utc_now)
    created_by: str = "system"
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        validate_identifier(self.project_id, "project_id")
        sanitize_summary(self.name, "name", max_length=120)
        validate_timestamp(self.created_at, "created_at")
        if self.schema_version != "1.0":
            raise DomainError(ERROR_REDACTION, "project schema_version must be 1.0")

    @classmethod
    def create(cls, project_id: str, name: str, *, created_by: str = "system", created_at: str | None = None) -> "EnterpriseProject":
        return cls(
            project_id=project_id,
            name=name,
            created_at=created_at or utc_now(),
            created_by=created_by,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ArtifactReference:
    """A registered reference to an artifact: relative path, SHA-256, type, version.

    The Enterprise Lab never carries artifact bytes. Large files stay in the
    existing CSV/manifest hash packages, a future file store or an object store;
    the database or index keeps the reference and the digest only.
    """

    artifact_id: str
    relative_path: str
    sha256: str
    artifact_type: str
    artifact_version: str
    run_id: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        validate_identifier(self.artifact_id, "artifact_id")
        validate_relative_reference(self.relative_path, "relative_path")
        validate_digest(self.sha256, "sha256")
        validate_identifier(self.artifact_type, "artifact_type")
        validate_identifier(self.artifact_version, "artifact_version")
        validate_identifier(self.run_id, "run_id")
        validate_timestamp(self.created_at, "created_at")

    @classmethod
    def create(
        cls,
        *,
        relative_path: str,
        sha256: str,
        artifact_type: str,
        artifact_version: str,
        run_id: str,
        created_at: str | None = None,
    ) -> "ArtifactReference":
        validate_relative_reference(relative_path, "relative_path")
        validate_digest(sha256, "sha256")
        seed = {
            "relative_path": relative_path,
            "sha256": sha256,
            "artifact_type": artifact_type,
            "artifact_version": artifact_version,
            "run_id": run_id,
        }
        return cls(
            artifact_id=_content_digest("art_", seed),
            relative_path=relative_path,
            sha256=sha256,
            artifact_type=artifact_type,
            artifact_version=artifact_version,
            run_id=run_id,
            created_at=created_at or utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "artifact_type": self.artifact_type,
            "artifact_version": self.artifact_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class WorkflowRun:
    """A workflow run record: identity, state, revision and content digests.

    ``request_digest`` is mandatory: every stored run carries the digest of the
    request that created it, because idempotent reuse and conflict detection are
    decided by comparing that digest.
    """

    run_id: str
    project_id: str
    task_id: str
    state: str
    revision: int
    content_digest: str
    result_level: str
    evidence_class: str
    idempotency_key: str
    request_digest: str
    created_at: str
    updated_at: str
    created_by: str = "system"
    next_action: str = "awaiting human review"

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, "run_id")
        validate_identifier(self.project_id, "project_id")
        validate_identifier(self.task_id, "task_id")
        GovernanceState(self.state)
        validate_revision(self.revision, "revision")
        validate_content_digest(self.content_digest, "content_digest")
        level = ResultLevel(self.result_level)
        evidence = EvidenceClass(self.evidence_class)
        validate_identifier(self.idempotency_key, "idempotency_key")
        validate_digest(self.request_digest, "request_digest")
        validate_timestamp(self.created_at, "created_at")
        validate_timestamp(self.updated_at, "updated_at")
        sanitize_summary(self.next_action, "next_action", max_length=200)
        if evidence is EvidenceClass.MODEL_OUTPUT and level is ResultLevel.ACCEPTED_EVIDENCE:
            raise DomainError(
                ERROR_REDACTION,
                "model output cannot be registered as accepted experimental evidence",
            )

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        project_id: str,
        task_id: str,
        idempotency_key: str,
        request_digest: str,
        created_by: str = "system",
        state: str = GovernanceState.DRAFT.value,
        result_level: str = ResultLevel.WORKING_CANDIDATE.value,
        evidence_class: str = EvidenceClass.SYNTHETIC_DEMO_DATA.value,
        next_action: str = "awaiting human review",
        created_at: str | None = None,
    ) -> "WorkflowRun":
        timestamp = created_at or utc_now()
        fields = cls.declarative_fields(
            run_id=run_id,
            project_id=project_id,
            task_id=task_id,
            state=state,
            result_level=result_level,
            evidence_class=evidence_class,
            created_by=created_by,
            next_action=next_action,
        )
        return cls(
            run_id=run_id,
            project_id=project_id,
            task_id=task_id,
            state=state,
            revision=1,
            content_digest=_content_digest("run_", fields),
            result_level=result_level,
            evidence_class=evidence_class,
            idempotency_key=idempotency_key,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=created_by,
            next_action=next_action,
            request_digest=request_digest,
        )

    @staticmethod
    def declarative_fields(
        *,
        run_id: str,
        project_id: str,
        task_id: str,
        state: str,
        result_level: str,
        evidence_class: str,
        created_by: str,
        next_action: str,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "project_id": project_id,
            "task_id": task_id,
            "state": state,
            "result_level": result_level,
            "evidence_class": evidence_class,
            "created_by": created_by,
            "next_action": next_action,
        }

    def declarative(self) -> dict[str, Any]:
        return self.declarative_fields(
            run_id=self.run_id,
            project_id=self.project_id,
            task_id=self.task_id,
            state=self.state,
            result_level=self.result_level,
            evidence_class=self.evidence_class,
            created_by=self.created_by,
            next_action=self.next_action,
        )

    def expected_digest(self) -> str:
        return _content_digest("run_", self.declarative())

    def evolves_to(
        self,
        *,
        state: str,
        revision: int,
        updated_at: str,
        result_level: str | None = None,
        next_action: str | None = None,
    ) -> "WorkflowRun":
        """Return the next revision of this run; a stored record is never mutated."""
        updated = WorkflowRun.create(
            run_id=self.run_id,
            project_id=self.project_id,
            task_id=self.task_id,
            idempotency_key=self.idempotency_key,
            created_by=self.created_by,
            state=state,
            result_level=result_level or self.result_level,
            evidence_class=self.evidence_class,
            next_action=next_action or self.next_action,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )
        return WorkflowRun(
            run_id=updated.run_id,
            project_id=updated.project_id,
            task_id=updated.task_id,
            state=updated.state,
            revision=revision,
            content_digest=updated.content_digest,
            result_level=updated.result_level,
            evidence_class=updated.evidence_class,
            idempotency_key=updated.idempotency_key,
            created_at=self.created_at,
            updated_at=updated_at,
            created_by=updated.created_by,
            next_action=updated.next_action,
            request_digest=updated.request_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "state": self.state,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "result_level": self.result_level,
            "evidence_class": self.evidence_class,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "next_action": self.next_action,
            "request_digest": self.request_digest,
        }


@dataclass(frozen=True)
class AuditEvent:
    """An append-only audit record. There is no update or delete path."""

    audit_id: str
    sequence: int
    run_id: str
    action: str
    actor_role: str
    actor_id: str
    summary: str
    occurred_at: str
    object_type: str
    object_id: str
    object_revision: int
    object_digest: str

    def __post_init__(self) -> None:
        validate_identifier(self.audit_id, "audit_id")
        validate_revision(self.sequence, "sequence")
        validate_identifier(self.run_id, "run_id")
        validate_identifier(self.action, "action")
        if self.actor_role not in ACTOR_ROLES:
            raise DomainError(ERROR_AUDIT_APPEND_ONLY, "actor_role must be a declared governance actor")
        validate_identifier(self.actor_id, "actor_id")
        sanitize_summary(self.summary, "summary")
        validate_timestamp(self.occurred_at, "occurred_at")
        validate_identifier(self.object_type, "object_type")
        validate_identifier(self.object_id, "object_id")
        validate_revision(self.object_revision, "object_revision")
        validate_content_digest(self.object_digest, "object_digest")

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        run_id: str,
        action: str,
        actor_role: str,
        actor_id: str,
        summary: str,
        object_type: str,
        object_id: str,
        object_revision: int,
        object_digest: str,
        occurred_at: str | None = None,
    ) -> "AuditEvent":
        timestamp = occurred_at or utc_now()
        seed = {
            "sequence": sequence,
            "run_id": run_id,
            "action": action,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "summary": summary,
            "occurred_at": timestamp,
            "object_type": object_type,
            "object_id": object_id,
            "object_revision": object_revision,
            "object_digest": object_digest,
        }
        return cls(
            audit_id=_content_digest("aud_", seed),
            sequence=sequence,
            run_id=run_id,
            action=action,
            actor_role=actor_role,
            actor_id=actor_id,
            summary=summary,
            occurred_at=timestamp,
            object_type=object_type,
            object_id=object_id,
            object_revision=object_revision,
            object_digest=object_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "sequence": self.sequence,
            "run_id": self.run_id,
            "action": self.action,
            "actor_role": self.actor_role,
            "actor_id": self.actor_id,
            "summary": self.summary,
            "occurred_at": self.occurred_at,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "object_revision": self.object_revision,
            "object_digest": self.object_digest,
        }


@dataclass(frozen=True)
class DomainEvent:
    """A structured domain event: IDs, states, versions, hashes and a summary.

    This is the payload a future Transactional Outbox would persist and a future
    Kafka publisher would carry. It never contains raw experimental values,
    absolute paths, credentials or artifact bytes.
    """

    event_id: str
    event_type: str
    run_id: str
    sequence: int
    payload: Mapping[str, Any]
    occurred_at: str

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, "event_id")
        validate_identifier(self.event_type, "event_type")
        validate_identifier(self.run_id, "run_id")
        validate_revision(self.sequence, "sequence")
        validate_timestamp(self.occurred_at, "occurred_at")
        object.__setattr__(self, "payload", validate_event_payload(self.payload))

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        run_id: str,
        sequence: int,
        payload: Mapping[str, Any],
        occurred_at: str | None = None,
    ) -> "DomainEvent":
        timestamp = occurred_at or utc_now()
        normalized = validate_event_payload(payload)
        seed = {
            "event_type": event_type,
            "run_id": run_id,
            "sequence": sequence,
            "payload": normalized,
            "occurred_at": timestamp,
        }
        return cls(
            event_id=_content_digest("evt_", seed),
            event_type=event_type,
            run_id=run_id,
            sequence=sequence,
            payload=normalized,
            occurred_at=timestamp,
        )

    def content_digest(self) -> str:
        return digest_value(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class BackgroundJob:
    """A background-job record. T80 defines the contract, not a worker."""

    job_id: str
    job_type: str
    run_id: str
    state: str
    attempts: int
    max_attempts: int
    idempotency_key: str
    payload_digest: str
    created_at: str
    updated_at: str
    lease_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.job_id, "job_id")
        validate_identifier(self.job_type, "job_type")
        validate_identifier(self.run_id, "run_id")
        JobState(self.state)
        validate_revision(self.attempts, "attempts")
        validate_revision(self.max_attempts, "max_attempts")
        if self.attempts > self.max_attempts:
            raise DomainError(ERROR_JOB_TRANSITION, "attempts cannot exceed max_attempts")
        validate_identifier(self.idempotency_key, "idempotency_key")
        validate_digest(self.payload_digest, "payload_digest")
        validate_timestamp(self.created_at, "created_at")
        validate_timestamp(self.updated_at, "updated_at")
        if self.lease_id is not None:
            validate_identifier(self.lease_id, "lease_id")
        if self.error_code is not None:
            validate_identifier(self.error_code, "error_code")

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        job_type: str,
        run_id: str,
        idempotency_key: str,
        payload_digest: str,
        max_attempts: int = 3,
        created_at: str | None = None,
    ) -> "BackgroundJob":
        timestamp = created_at or utc_now()
        return cls(
            job_id=job_id,
            job_type=job_type,
            run_id=run_id,
            state=JobState.QUEUED.value,
            attempts=1,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            payload_digest=payload_digest,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def request_digest(self) -> str:
        """Stable digest of the enqueue request, without any runtime timestamp.

        The queue binds ``idempotency_key`` to this digest, so reusing a key with
        a different job, run, type, payload or attempt budget is refused instead
        of silently reusing the first job.
        """
        return digest_value(
            {
                "job_id": self.job_id,
                "job_type": self.job_type,
                "run_id": self.run_id,
                "idempotency_key": self.idempotency_key,
                "payload_digest": self.payload_digest,
                "max_attempts": self.max_attempts,
            }
        )

    def transition(
        self,
        to_state: JobState | str,
        *,
        updated_at: str,
        lease_id: str | None = None,
        error_code: str | None = None,
        count_attempt: bool = False,
        clear_lease: bool = False,
    ) -> "BackgroundJob":
        """Apply one legal state transition, without adding any new state.

        ``lease_id`` sets a new lease; ``clear_lease=True`` explicitly removes the current
        one (a worker that finished, terminally failed or lost its lease must not leave a
        stale lease behind). ``clear_lease`` and ``lease_id`` are mutually exclusive, and
        the default behaviour - keep the current lease - is unchanged.
        """
        target = JobState(to_state)
        if clear_lease and lease_id is not None:
            raise DomainError(
                ERROR_JOB_TRANSITION,
                "a transition cannot set and clear the lease at the same time",
                details={"job_id": self.job_id},
            )
        allowed = ALLOWED_JOB_TRANSITIONS[JobState(self.state)]
        if target not in allowed:
            raise DomainError(
                ERROR_JOB_TRANSITION,
                f"illegal background job transition: {self.state}->{target.value}",
                details={"job_id": self.job_id, "from": self.state, "to": target.value},
            )
        attempts = self.attempts + 1 if count_attempt else self.attempts
        if attempts > self.max_attempts:
            raise DomainError(
                ERROR_JOB_TRANSITION,
                "background job exhausted its attempts",
                details={"job_id": self.job_id, "attempts": attempts},
            )
        if clear_lease:
            resolved_lease: str | None = None
        else:
            resolved_lease = lease_id if lease_id is not None else self.lease_id
        return BackgroundJob(
            job_id=self.job_id,
            job_type=self.job_type,
            run_id=self.run_id,
            state=target.value,
            attempts=attempts,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            payload_digest=self.payload_digest,
            created_at=self.created_at,
            updated_at=updated_at,
            lease_id=resolved_lease,
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "state": self.state,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "idempotency_key": self.idempotency_key,
            "payload_digest": self.payload_digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lease_id": self.lease_id,
            "error_code": self.error_code,
            "request_digest": self.request_digest(),
        }


_EVENT_PAYLOAD_FIELDS = frozenset(
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


def validate_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the structured, redacted event payload.

    Only ID, state, version, hash and summary fields are accepted. Anything else
    (raw values, nested objects, paths, bytes) is rejected.
    """
    if not isinstance(payload, Mapping) or not payload:
        raise DomainError(ERROR_REDACTION, "domain event payload must be a non-empty mapping")
    unknown = sorted(set(payload) - _EVENT_PAYLOAD_FIELDS)
    if unknown:
        raise DomainError(
            ERROR_REDACTION,
            "domain event payload may only carry ids, states, versions, hashes and summaries",
            details={"unknown_fields": unknown},
        )
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key.endswith("_sha256"):
            normalized[key] = validate_digest(value, key)
        elif key in {"revision"}:
            normalized[key] = validate_revision(value, key)
        elif key in {"state", "previous_state"}:
            normalized[key] = GovernanceState(value).value
        elif key == "result_level":
            normalized[key] = ResultLevel(value).value
        elif key == "evidence_class":
            normalized[key] = EvidenceClass(value).value
        elif key == "summary":
            normalized[key] = sanitize_summary(value, key)
        else:
            normalized[key] = validate_identifier(value, key)
    return normalized
