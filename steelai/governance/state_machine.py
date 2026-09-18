"""Global state transition enforcement."""
from __future__ import annotations

from datetime import datetime

from .contract import load_governance_contract
from .errors import GovernanceError
from .models import (
    ApprovalDecision,
    ApprovalSnapshot,
    GovernanceState,
    ResearchObjectIdentity,
    TransitionRecord,
    require_matching_approval,
    utc_now,
)
from .serialization import digest_value


_ACTORS = {"human", "system", "external_tool"}


def _actor_allowed(declared: str, actual: str) -> bool:
    if declared == "human_or_system":
        return actual in {"human", "system"}
    return declared == actual


def transition_state(
    identity: ResearchObjectIdentity,
    from_state: str | GovernanceState,
    to_state: str | GovernanceState,
    *,
    actor: str,
    approval: ApprovalSnapshot | None = None,
    occurred_at: str | None = None,
) -> TransitionRecord:
    source = GovernanceState(from_state).value
    target = GovernanceState(to_state).value
    if actor not in _ACTORS:
        raise GovernanceError("GOV-STATE-001", GovernanceState.BLOCKED.value, "unknown transition actor")

    contract = load_governance_contract()
    transition = next(
        (
            item for item in contract["allowed_transitions"]
            if item["from"] == source and item["to"] == target
        ),
        None,
    )
    if transition is None or not _actor_allowed(transition["actor"], actor):
        raise GovernanceError(
            "GOV-STATE-001",
            GovernanceState.BLOCKED.value,
            f"state transition is not allowed: {source}->{target} by {actor}",
        )

    if target == GovernanceState.APPROVED.value:
        require_matching_approval(identity, approval, (ApprovalDecision.APPROVED,))
    elif target == GovernanceState.REJECTED.value:
        require_matching_approval(identity, approval, (ApprovalDecision.REJECTED,))
    elif target == GovernanceState.RUNNING.value:
        require_matching_approval(identity, approval, (ApprovalDecision.APPROVED,))
    elif source == GovernanceState.WARNING.value and target == GovernanceState.COMPLETE.value:
        require_matching_approval(identity, approval, (ApprovalDecision.WARNING_ACCEPTED,))

    timestamp = occurred_at or utc_now()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("occurred_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    seed = {
        "identity": identity.to_dict(),
        "from_state": source,
        "to_state": target,
        "actor": actor,
        "occurred_at": timestamp,
        "approval_id": approval.approval_id if approval else None,
        "governance_contract_id": contract["contract_id"],
    }
    return TransitionRecord(
        transition_id="TRN-" + digest_value(seed)[:20].upper(),
        object_type=identity.object_type,
        object_id=identity.object_id,
        object_revision=identity.revision,
        object_digest=identity.content_digest,
        from_state=source,
        to_state=target,
        actor=actor,
        occurred_at=timestamp,
        approval_id=approval.approval_id if approval else None,
        governance_contract_id=contract["contract_id"],
    )


def authorize_execution(
    identity: ResearchObjectIdentity,
    current_state: str | GovernanceState,
    approval: ApprovalSnapshot | None,
    *,
    occurred_at: str | None = None,
) -> TransitionRecord:
    """The only shared gateway into running."""
    return transition_state(
        identity,
        current_state,
        GovernanceState.RUNNING,
        actor="system",
        approval=approval,
        occurred_at=occurred_at,
    )
