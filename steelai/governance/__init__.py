"""SteelAI shared research-governance core (T51)."""
from .contract import CONTRACT_PATH, load_governance_contract, validate_governance_contract
from .errors import GovernanceError
from .gates import evaluate_formal_write
from .manifest import (
    COMPLETE_NAME,
    MANIFEST_NAME,
    build_manifest,
    load_verified_manifest,
    seal_package,
    verify_package,
)
from .models import (
    ApprovalDecision,
    ApprovalSnapshot,
    ArtifactRecord,
    EvidenceClass,
    GateDecision,
    GovernanceManifest,
    GovernanceState,
    PublicationResult,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    TransitionRecord,
    VerificationResult,
    require_matching_approval,
    utc_now,
)
from .publishing import create_staging_directory, publish_append_only
from .serialization import canonical_json_bytes, digest_value, sha256_file, write_json_atomic
from .state_machine import authorize_execution, transition_state


__all__ = [
    "ApprovalDecision",
    "ApprovalSnapshot",
    "ArtifactRecord",
    "COMPLETE_NAME",
    "CONTRACT_PATH",
    "EvidenceClass",
    "GateDecision",
    "GovernanceError",
    "GovernanceManifest",
    "GovernanceState",
    "MANIFEST_NAME",
    "PublicationResult",
    "ResearchObjectIdentity",
    "ResultLevel",
    "SourceReference",
    "TransitionRecord",
    "VerificationResult",
    "authorize_execution",
    "build_manifest",
    "canonical_json_bytes",
    "create_staging_directory",
    "digest_value",
    "evaluate_formal_write",
    "load_governance_contract",
    "load_verified_manifest",
    "publish_append_only",
    "require_matching_approval",
    "seal_package",
    "sha256_file",
    "transition_state",
    "utc_now",
    "validate_governance_contract",
    "verify_package",
    "write_json_atomic",
]
