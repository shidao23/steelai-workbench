"""Stable governance data classes and JSON round-trip formats."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from .contract import load_governance_contract
from .errors import GovernanceError
from .serialization import canonical_json_bytes, digest_value


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class GovernanceState(str, Enum):
    DRAFT = "draft"
    NEEDS_HUMAN = "needs_human"
    APPROVED = "approved"
    RUNNING = "running"
    PASSED = "passed"
    WARNING = "warning"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    INVALIDATED = "invalidated"


class ResultLevel(str, Enum):
    WORKING_CANDIDATE = "working_candidate"
    SYNTHETIC_DEMO_ONLY = "synthetic_demo_only"
    MODEL_RESULT = "model_result"
    VERIFIED_OUTPUT = "verified_output"
    ACCEPTED_EVIDENCE = "accepted_evidence"
    HUMAN_CONCLUSION = "human_conclusion"


class EvidenceClass(str, Enum):
    REAL_RESEARCH_DATA = "real_research_data"
    SYNTHETIC_DEMO_DATA = "synthetic_demo_data"
    MODEL_OUTPUT = "model_output"
    HUMAN_CONCLUSION = "human_conclusion"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    WARNING_ACCEPTED = "warning_accepted"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_timestamp(value: str, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


def _validate_digest(value: str, field_name: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError(f"{field_name} must be a non-empty identifier of at most 160 characters")
    if value in {".", ".."} or any(char in value for char in ("/", "\\", "\r", "\n", "\t")):
        raise ValueError(f"{field_name} must not be a path")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], record_name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{record_name} fields mismatch; missing={missing}, extra={extra}")


@dataclass(frozen=True)
class ResearchObjectIdentity:
    object_type: str
    object_id: str
    revision: int
    content_digest: str
    created_at: str
    created_by: str

    def __post_init__(self) -> None:
        _validate_identifier(self.object_type, "object_type")
        _validate_identifier(self.object_id, "object_id")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        _validate_digest(self.content_digest, "content_digest")
        _validate_timestamp(self.created_at, "created_at")
        if not self.created_by.strip():
            raise ValueError("created_by is required")

    @classmethod
    def from_content(
        cls,
        object_type: str,
        object_id: str,
        revision: int,
        content: Any,
        created_by: str,
        *,
        created_at: str | None = None,
    ) -> "ResearchObjectIdentity":
        return cls(
            object_type=object_type,
            object_id=object_id,
            revision=revision,
            content_digest=digest_value(content),
            created_at=created_at or utc_now(),
            created_by=created_by,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_type": self.object_type,
            "object_id": self.object_id,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResearchObjectIdentity":
        expected = {"object_type", "object_id", "revision", "content_digest", "created_at", "created_by"}
        _require_exact_keys(value, expected, "research object identity")
        return cls(**{key: value[key] for key in (
            "object_type", "object_id", "revision", "content_digest", "created_at", "created_by",
        )})


@dataclass(frozen=True)
class SourceReference:
    source_id: str
    source_revision: int
    source_digest: str
    evidence_class: str
    source_status: str
    relative_locator: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.source_id, "source_id")
        if not isinstance(self.source_revision, int) or isinstance(self.source_revision, bool) or self.source_revision < 1:
            raise ValueError("source_revision must be a positive integer")
        _validate_digest(self.source_digest, "source_digest")
        EvidenceClass(self.evidence_class)
        if not self.source_status.strip():
            raise ValueError("source_status is required")
        if self.relative_locator is not None:
            locator = PurePosixPath(self.relative_locator)
            if (
                not self.relative_locator
                or locator.is_absolute()
                or ".." in locator.parts
                or "." in locator.parts
                or "\\" in self.relative_locator
                or ":" in self.relative_locator
            ):
                raise ValueError("relative_locator must be a safe relative POSIX path")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_digest": self.source_digest,
            "evidence_class": self.evidence_class,
            "source_status": self.source_status,
        }
        if self.relative_locator is not None:
            result["relative_locator"] = self.relative_locator
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceReference":
        required = {"source_id", "source_revision", "source_digest", "evidence_class", "source_status"}
        allowed = required | {"relative_locator"}
        actual = set(value)
        if not required.issubset(actual) or not actual.issubset(allowed):
            raise ValueError(
                f"source reference fields mismatch; missing={sorted(required - actual)}, "
                f"extra={sorted(actual - allowed)}"
            )
        return cls(
            source_id=value["source_id"],
            source_revision=value["source_revision"],
            source_digest=value["source_digest"],
            evidence_class=value["evidence_class"],
            source_status=value["source_status"],
            relative_locator=value.get("relative_locator"),
        )


@dataclass(frozen=True)
class ApprovalSnapshot:
    approval_id: str
    object_type: str
    object_id: str
    object_revision: int
    object_digest: str
    decision: str
    reviewer_id: str
    decided_at: str
    scope: str
    rationale: str
    governance_contract_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.approval_id, "approval_id")
        _validate_identifier(self.object_type, "object_type")
        _validate_identifier(self.object_id, "object_id")
        if not isinstance(self.object_revision, int) or isinstance(self.object_revision, bool) or self.object_revision < 1:
            raise ValueError("object_revision must be a positive integer")
        _validate_digest(self.object_digest, "object_digest")
        ApprovalDecision(self.decision)
        normalized = self.reviewer_id.strip().casefold()
        forbidden = {"ai", "agent", "system", "deepseek", "chatgpt", "gpt", "llm", "model"}
        if not normalized or normalized in forbidden or normalized.startswith(("agent-", "ai-", "model-")):
            raise GovernanceError(
                "GOV-AI-AUTH-001",
                GovernanceState.BLOCKED.value,
                "reviewer_id must identify an accountable human",
            )
        _validate_timestamp(self.decided_at, "decided_at")
        if not self.scope.strip() or not self.rationale.strip():
            raise ValueError("approval scope and rationale are required")
        expected_contract = load_governance_contract()["contract_id"]
        if self.governance_contract_id != expected_contract:
            raise ValueError("approval uses an unknown governance contract")

    @classmethod
    def create(
        cls,
        identity: ResearchObjectIdentity,
        decision: str | ApprovalDecision,
        reviewer_id: str,
        scope: str,
        rationale: str,
        *,
        decided_at: str | None = None,
        approval_id: str | None = None,
    ) -> "ApprovalSnapshot":
        decision_value = ApprovalDecision(decision).value
        timestamp = decided_at or utc_now()
        contract_id = load_governance_contract()["contract_id"]
        seed = {
            "identity": identity.to_dict(),
            "decision": decision_value,
            "reviewer_id": reviewer_id,
            "decided_at": timestamp,
            "scope": scope,
            "rationale": rationale,
            "governance_contract_id": contract_id,
        }
        return cls(
            approval_id=approval_id or "APR-" + digest_value(seed)[:20].upper(),
            object_type=identity.object_type,
            object_id=identity.object_id,
            object_revision=identity.revision,
            object_digest=identity.content_digest,
            decision=decision_value,
            reviewer_id=reviewer_id,
            decided_at=timestamp,
            scope=scope,
            rationale=rationale,
            governance_contract_id=contract_id,
        )

    def matches(self, identity: ResearchObjectIdentity) -> bool:
        return (
            self.object_type == identity.object_type
            and self.object_id == identity.object_id
            and self.object_revision == identity.revision
            and self.object_digest == identity.content_digest
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "object_revision": self.object_revision,
            "object_digest": self.object_digest,
            "decision": self.decision,
            "reviewer_id": self.reviewer_id,
            "decided_at": self.decided_at,
            "scope": self.scope,
            "rationale": self.rationale,
            "governance_contract_id": self.governance_contract_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApprovalSnapshot":
        fields = (
            "approval_id", "object_type", "object_id", "object_revision", "object_digest",
            "decision", "reviewer_id", "decided_at", "scope", "rationale",
            "governance_contract_id",
        )
        _require_exact_keys(value, set(fields), "approval snapshot")
        return cls(**{key: value[key] for key in fields})


def require_matching_approval(
    identity: ResearchObjectIdentity,
    approval: ApprovalSnapshot | None,
    allowed_decisions: Iterable[str | ApprovalDecision] = (ApprovalDecision.APPROVED,),
) -> ApprovalSnapshot:
    allowed = {ApprovalDecision(value).value for value in allowed_decisions}
    if approval is None or approval.decision not in allowed or not approval.matches(identity):
        raise GovernanceError(
            "GOV-APPROVAL-001",
            GovernanceState.BLOCKED.value,
            "a current hash-bound human approval is required",
            details={"object_id": identity.object_id, "allowed_decisions": sorted(allowed)},
        )
    return approval


@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        candidate = PurePosixPath(self.path)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or "." in candidate.parts
            or "\\" in self.path
            or ":" in self.path
        ):
            raise ValueError("artifact path must be a safe relative POSIX path")
        _validate_digest(self.sha256, "artifact sha256")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRecord":
        _require_exact_keys(value, {"path", "sha256", "size_bytes"}, "artifact record")
        return cls(path=value["path"], sha256=value["sha256"], size_bytes=value["size_bytes"])


@dataclass(frozen=True)
class GovernanceManifest:
    contract_id: str
    manifest_version: str
    publication_id: str
    identity: ResearchObjectIdentity
    state: str
    result_level: str
    evidence_class: str
    sources: tuple[SourceReference, ...]
    approvals: tuple[ApprovalSnapshot, ...]
    artifacts: tuple[ArtifactRecord, ...]
    generated_at: str
    generated_by: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    publication_fingerprint: str = ""

    def __post_init__(self) -> None:
        contract = load_governance_contract()
        if self.contract_id != contract["contract_id"] or self.manifest_version != "1.0":
            raise ValueError("unsupported governance manifest contract or version")
        _validate_identifier(self.publication_id, "publication_id")
        GovernanceState(self.state)
        ResultLevel(self.result_level)
        EvidenceClass(self.evidence_class)
        _validate_timestamp(self.generated_at, "generated_at")
        if not self.generated_by.strip():
            raise ValueError("generated_by is required")
        if len({item.source_id for item in self.sources}) != len(self.sources):
            raise ValueError("source references must be unique")
        if len({item.approval_id for item in self.approvals}) != len(self.approvals):
            raise ValueError("approval snapshots must be unique")
        if len({item.path for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact paths must be unique")
        normalized_metadata = json.loads(canonical_json_bytes(dict(self.metadata)))
        object.__setattr__(self, "metadata", normalized_metadata)
        if self.publication_fingerprint:
            _validate_digest(self.publication_fingerprint, "publication_fingerprint")

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "manifest_version": self.manifest_version,
            "publication_id": self.publication_id,
            "identity": self.identity.to_dict(),
            "state": self.state,
            "result_level": self.result_level,
            "evidence_class": self.evidence_class,
            "sources": [item.to_dict() for item in self.sources],
            "approvals": [item.to_dict() for item in self.approvals],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "generated_by": self.generated_by,
            "metadata": dict(self.metadata),
        }

    def expected_fingerprint(self) -> str:
        return digest_value(self.fingerprint_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.fingerprint_payload(),
            "generated_at": self.generated_at,
            "publication_fingerprint": self.publication_fingerprint or self.expected_fingerprint(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GovernanceManifest":
        expected = {
            "contract_id", "manifest_version", "publication_id", "identity", "state",
            "result_level", "evidence_class", "sources", "approvals", "artifacts",
            "generated_at", "generated_by", "metadata", "publication_fingerprint",
        }
        _require_exact_keys(value, expected, "governance manifest")
        return cls(
            contract_id=value["contract_id"],
            manifest_version=value["manifest_version"],
            publication_id=value["publication_id"],
            identity=ResearchObjectIdentity.from_dict(value["identity"]),
            state=value["state"],
            result_level=value["result_level"],
            evidence_class=value["evidence_class"],
            sources=tuple(SourceReference.from_dict(item) for item in value.get("sources", [])),
            approvals=tuple(ApprovalSnapshot.from_dict(item) for item in value.get("approvals", [])),
            artifacts=tuple(ArtifactRecord.from_dict(item) for item in value.get("artifacts", [])),
            generated_at=value["generated_at"],
            generated_by=value["generated_by"],
            metadata=value.get("metadata", {}),
            publication_fingerprint=value.get("publication_fingerprint", ""),
        )


@dataclass(frozen=True)
class TransitionRecord:
    transition_id: str
    object_type: str
    object_id: str
    object_revision: int
    object_digest: str
    from_state: str
    to_state: str
    actor: str
    occurred_at: str
    approval_id: str | None
    governance_contract_id: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    state: str
    checks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "state": self.state, "checks": list(self.checks)}


@dataclass(frozen=True)
class VerificationResult:
    status: str
    publication_id: str | None
    manifest_digest: str | None
    artifact_count: int
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "publication_id": self.publication_id,
            "manifest_digest": self.manifest_digest,
            "artifact_count": self.artifact_count,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class PublicationResult:
    status: str
    publication_id: str
    destination: str
    reused: bool
    manifest_digest: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)
