"""QC and formal-write decisions shared by governed workspaces."""
from __future__ import annotations

from collections.abc import Iterable

from .errors import GovernanceError
from .models import (
    ApprovalDecision,
    ApprovalSnapshot,
    EvidenceClass,
    GateDecision,
    GovernanceState,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    require_matching_approval,
)


def evaluate_formal_write(
    identity: ResearchObjectIdentity,
    *,
    state: str | GovernanceState,
    result_level: str | ResultLevel,
    evidence_class: str | EvidenceClass,
    sources: Iterable[SourceReference],
    approvals: Iterable[ApprovalSnapshot],
    qc_status: str,
    provenance_complete: bool,
    manifest_valid: bool,
    destination_allowed: bool,
    append_only: bool,
) -> GateDecision:
    """Fail closed unless all ten T50 formal-write conditions are satisfied."""
    state_value = GovernanceState(state).value
    result_value = ResultLevel(result_level).value
    class_value = EvidenceClass(evidence_class).value
    source_records = tuple(sources)
    approval_records = tuple(approvals)

    if state_value not in {"passed", "warning", "complete"}:
        raise GovernanceError("GOV-STATE-001", "blocked", "formal write requires passed, warning or complete")
    if not source_records:
        raise GovernanceError("GOV-SOURCE-001", "blocked", "formal write requires a registered source")
    if class_value == EvidenceClass.SYNTHETIC_DEMO_DATA.value:
        raise GovernanceError("GOV-RESULT-001", "blocked", "synthetic demo data cannot enter a formal evidence store")
    compatibility = {
        EvidenceClass.REAL_RESEARCH_DATA.value: {"verified_output", "accepted_evidence"},
        EvidenceClass.MODEL_OUTPUT.value: {"model_result"},
        EvidenceClass.HUMAN_CONCLUSION.value: {"human_conclusion"},
    }
    if result_value not in compatibility[class_value]:
        raise GovernanceError("GOV-RESULT-001", "blocked", "result level does not match evidence class")

    approved = next((item for item in approval_records if item.decision == "approved" and item.matches(identity)), None)
    require_matching_approval(identity, approved, (ApprovalDecision.APPROVED,))
    if qc_status not in {"passed", "warning"}:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "declared QC did not pass")
    if qc_status == "warning" or state_value == "warning":
        warning_approval = next(
            (item for item in approval_records if item.decision == "warning_accepted" and item.matches(identity)),
            None,
        )
        require_matching_approval(identity, warning_approval, (ApprovalDecision.WARNING_ACCEPTED,))
    if not provenance_complete or not manifest_valid:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "provenance and manifest integrity are required")
    if not destination_allowed or not append_only:
        raise GovernanceError("GOV-WRITE-001", "blocked", "destination must be allow-listed and append-only")

    return GateDecision(
        allowed=True,
        state=GovernanceState.COMPLETE.value,
        checks=(
            "FW-IDENTITY", "FW-SOURCE", "FW-SCHEMA", "FW-APPROVAL", "FW-QC",
            "FW-PROVENANCE", "FW-INTEGRITY", "FW-CLASS", "FW-APPEND", "FW-STATE",
        ),
    )
