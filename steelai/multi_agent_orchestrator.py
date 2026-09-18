"""T60 governed multi-agent orchestration for materials research.

The implementation is deliberately lightweight: roles are responsibility and
permission boundaries, not independent autonomous processes. All tool access is
allow-listed, all handoffs are auditable, and only named humans can approve or
terminate checkpoints.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from steelai.governance import (
    ApprovalSnapshot,
    EvidenceClass,
    GovernanceError,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    build_manifest,
    create_staging_directory,
    digest_value,
    publish_append_only,
    seal_package,
    utc_now,
    write_json_atomic,
)
from steelai.paths import OUTPUTS, ROOT


ROLE_CONTRACT_PATH = ROOT / "config" / "multi_agent_roles_v1.0.json"
MULTI_AGENT_OUTPUTS = OUTPUTS / "multi_agent_runs"
ORCHESTRATOR_VERSION = "1.0.0"
WORKFLOW_SEQUENCE = (
    "planner",
    "data_steward",
    "statistics_physics",
    "materials_interpreter",
    "reviewer",
)
ALLOWED_TOOLS = frozenset({
    "list_governed_capabilities",
    "read_verified_evidence",
    "descriptive_statistics",
    "physics_card",
    "bounded_material_interpretation",
    "validate_claim_evidence",
})
HUMAN_DECISIONS = frozenset({"approved", "rejected", "terminated"})
_FORBIDDEN_REVIEWERS = frozenset({"", "ai", "agent", "system", "llm", "model", "gpt", "chatgpt"})


class MultiAgentError(GovernanceError):
    """A stable fail-closed orchestration error."""


def _error(code: str, message: str, *, state: str = "blocked") -> MultiAgentError:
    return MultiAgentError(code, state, message)


def _safe_identifier(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 160 or text in {".", ".."} or any(c in text for c in "/\\\r\n\t"):
        raise ValueError(f"{field_name} must be a non-path identifier")
    return text


def load_multi_agent_contract(path: Path = ROLE_CONTRACT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("multi-agent contract must be a JSON object")
    return payload


def validate_multi_agent_contract(path: Path = ROLE_CONTRACT_PATH) -> dict[str, Any]:
    problems: list[str] = []
    try:
        payload = load_multi_agent_contract(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": "1.0", "status": "failed", "problems": [str(exc)]}

    if payload.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    if payload.get("contract_id") != "SteelAI-Materials-Multi-Agent-v1.0":
        problems.append("contract_id mismatch")
    if tuple(payload.get("workflow_sequence", [])) != WORKFLOW_SEQUENCE:
        problems.append("workflow_sequence must contain the five frozen roles in order")
    roles = payload.get("roles", [])
    if not isinstance(roles, list) or len(roles) != len(WORKFLOW_SEQUENCE):
        problems.append("exactly five role contracts are required")
        roles = []
    role_ids = [item.get("role_id") for item in roles if isinstance(item, Mapping)]
    if tuple(role_ids) != WORKFLOW_SEQUENCE:
        problems.append("role contracts do not match workflow_sequence")
    for role in roles:
        if not isinstance(role, Mapping):
            problems.append("role contract must be an object")
            continue
        required = {"role_id", "label", "inputs", "outputs", "allowed_tools", "denied_authorities", "stop_conditions"}
        if set(role) != required:
            problems.append(f"role {role.get('role_id', '?')} fields mismatch")
        if set(role.get("allowed_tools", [])) - ALLOWED_TOOLS:
            problems.append(f"role {role.get('role_id', '?')} has a non-allow-listed tool")
        denied = set(role.get("denied_authorities", []))
        if not {"human_approval", "formal_write", "source_mutation", "shell_execution"}.issubset(denied):
            problems.append(f"role {role.get('role_id', '?')} lacks mandatory authority denials")
        if not role.get("stop_conditions"):
            problems.append(f"role {role.get('role_id', '?')} has no stop conditions")
    checkpoints = payload.get("human_checkpoints", [])
    checkpoint_ids = [item.get("checkpoint_id") for item in checkpoints if isinstance(item, Mapping)]
    if checkpoint_ids != ["plan_approval", "result_acceptance"]:
        problems.append("two frozen human checkpoints are required")
    for checkpoint in checkpoints:
        if set(checkpoint.get("allowed_decisions", [])) != HUMAN_DECISIONS:
            problems.append(f"checkpoint {checkpoint.get('checkpoint_id', '?')} decision set mismatch")
    policy = payload.get("execution_policy", {})
    if policy.get("tool_retry_limit") != 1:
        problems.append("tool_retry_limit must be one")
    for flag in ("append_only_trace", "cloud_model_optional", "offline_deterministic_processing_required"):
        if policy.get(flag) is not True:
            problems.append(f"execution_policy.{flag} must be true")
    for flag in ("persist_raw_tool_arguments", "persist_raw_model_prompts"):
        if policy.get(flag) is not False:
            problems.append(f"execution_policy.{flag} must be false")
    return {
        "schema_version": "1.0",
        "status": "passed" if not problems else "failed",
        "contract_id": payload.get("contract_id", ""),
        "role_count": len(roles),
        "checkpoint_count": len(checkpoints),
        "problems": problems,
    }


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    revision: int
    digest: str
    evidence_class: str
    verification_status: str = "passed"
    permission_status: str = "allowed"

    def __post_init__(self) -> None:
        _safe_identifier(self.evidence_id, "evidence_id")
        if self.revision < 1:
            raise ValueError("evidence revision must be positive")
        if len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest):
            raise ValueError("evidence digest must be lowercase SHA-256")
        EvidenceClass(self.evidence_class)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HumanCheckpointDecision:
    checkpoint_id: str
    decision: str
    reviewer_id: str
    rationale: str
    decided_at: str

    def __post_init__(self) -> None:
        _safe_identifier(self.checkpoint_id, "checkpoint_id")
        if self.decision not in HUMAN_DECISIONS:
            raise ValueError("unsupported human checkpoint decision")
        reviewer = self.reviewer_id.strip().casefold()
        if reviewer in _FORBIDDEN_REVIEWERS or reviewer.startswith(("agent-", "ai-", "model-")):
            raise _error("GOV-AI-AUTH-001", "checkpoint reviewer must identify an accountable human")
        if not self.rationale.strip():
            raise ValueError("checkpoint rationale is required")

    @classmethod
    def create(cls, checkpoint_id: str, decision: str, reviewer_id: str, rationale: str, *, decided_at: str | None = None) -> "HumanCheckpointDecision":
        return cls(checkpoint_id, decision, reviewer_id, rationale, decided_at or utc_now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HandoffRecord:
    handoff_id: str
    task_id: str
    from_role: str
    to_role: str
    responsibility_role: str
    evidence_refs: tuple[str, ...]
    output_status: str
    occurred_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_refs"] = list(self.evidence_refs)
        return data


@dataclass(frozen=True)
class ToolCallRecord:
    sequence: int
    role_id: str
    tool_name: str
    arguments_sha256: str
    attempt: int
    status: str
    result_sha256: str
    error_code: str
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MultiAgentOutcome:
    run_id: str
    status: str
    error_code: str
    message: str
    cloud_status: str
    interpretation_mode: str
    deterministic_outputs_ready: bool
    handoffs: list[HandoffRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    role_outputs: dict[str, Any] = field(default_factory=dict)
    human_decisions: list[HumanCheckpointDecision] = field(default_factory=list)
    audit_package: str = ""
    manifest_sha256: str = ""
    reused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "error_code": self.error_code,
            "message": self.message,
            "cloud_status": self.cloud_status,
            "interpretation_mode": self.interpretation_mode,
            "deterministic_outputs_ready": self.deterministic_outputs_ready,
            "handoffs": [item.to_dict() for item in self.handoffs],
            "tool_calls": [item.to_dict() for item in self.tool_calls],
            "role_outputs": self.role_outputs,
            "human_decisions": [item.to_dict() for item in self.human_decisions],
            "audit_package": self.audit_package,
            "manifest_sha256": self.manifest_sha256,
            "reused": self.reused,
        }


ToolExecutor = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def _default_tool_executor(tool_name: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence_ids = list(payload.get("evidence_ids", []))
    if tool_name == "list_governed_capabilities":
        return {"capabilities": ["verified_evidence", "descriptive_statistics", "physics_card", "bounded_interpretation"]}
    if tool_name == "read_verified_evidence":
        return {"evidence_ids": evidence_ids, "verified_count": len(evidence_ids)}
    if tool_name == "descriptive_statistics":
        return {"method_id": "descriptive-summary-v1", "evidence_count": len(evidence_ids), "status": "passed"}
    if tool_name == "physics_card":
        return {"registry": "physics-model-registry-v1.0", "status": "passed", "result_type": "model_estimate"}
    if tool_name == "bounded_material_interpretation":
        return {
            "claims": [{
                "claim_id": "CLAIM-1",
                "claim_type": "bounded_interpretation",
                "text": "已登记证据支持继续进行描述性比较；科学结论仍需人工复核。",
                "evidence_ids": evidence_ids,
            }],
            "limitations": ["不做因果判断", "不把模型估算写成实验真值"],
        }
    if tool_name == "validate_claim_evidence":
        claims = payload.get("claims", [])
        unsupported = [item.get("claim_id", "unknown") for item in claims if not item.get("evidence_ids")]
        return {"status": "passed" if not unsupported else "blocked", "unsupported_claims": unsupported}
    raise _error("GOV-AI-AUTH-001", "requested tool is not allow-listed")


class MaterialsMultiAgentOrchestrator:
    def __init__(self, *, output_root: Path | None = MULTI_AGENT_OUTPUTS, tool_executor: ToolExecutor | None = None, retry_limit: int = 1) -> None:
        if retry_limit != 1:
            raise ValueError("T60 freezes exactly one retry after the first tool failure")
        if validate_multi_agent_contract().get("status") != "passed":
            raise _error("GOV-SCHEMA-001", "multi-agent role contract is invalid")
        self.output_root = output_root
        self.tool_executor = tool_executor or _default_tool_executor
        self.retry_limit = retry_limit

    def run(
        self,
        request: str,
        evidence: Sequence[EvidenceReference],
        decisions: Mapping[str, HumanCheckpointDecision],
        *,
        cloud_available: bool = True,
        started_at: str | None = None,
        scenario: str = "standard",
    ) -> MultiAgentOutcome:
        request_text = str(request).strip()
        if not request_text:
            raise _error("GOV-SCHEMA-001", "research request is empty")
        timestamp = started_at or utc_now()
        run_seed = {
            "request_sha256": digest_value(request_text),
            "evidence": [item.to_dict() for item in evidence],
            "scenario": scenario,
            "started_at": timestamp,
        }
        run_id = "T60-" + digest_value(run_seed)[:20].upper()
        outcome = MultiAgentOutcome(
            run_id=run_id,
            status="running",
            error_code="",
            message="workflow started",
            cloud_status="available" if cloud_available else "unavailable",
            interpretation_mode="cloud_bounded" if cloud_available else "deterministic_fallback",
            deterministic_outputs_ready=False,
        )
        evidence_ids = tuple(item.evidence_id for item in evidence)

        def handoff(from_role: str, to_role: str, task: str, status: str, refs: Sequence[str] = evidence_ids) -> None:
            sequence = len(outcome.handoffs) + 1
            identity = {
                "run_id": run_id,
                "sequence": sequence,
                "from_role": from_role,
                "to_role": to_role,
                "task": task,
                "status": status,
                "evidence_refs": list(refs),
            }
            outcome.handoffs.append(HandoffRecord(
                handoff_id="HANDOFF-" + digest_value(identity)[:16].upper(),
                task_id=task,
                from_role=from_role,
                to_role=to_role,
                responsibility_role=to_role,
                evidence_refs=tuple(refs),
                output_status=status,
                occurred_at=timestamp,
            ))

        def call(role_id: str, tool_name: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
            if tool_name not in ALLOWED_TOOLS:
                raise _error("GOV-AI-AUTH-001", "role requested a non-allow-listed tool")
            argument_digest = digest_value(dict(payload))
            last_error: Exception | None = None
            for attempt in range(1, self.retry_limit + 2):
                started = time.perf_counter()
                try:
                    result = self.tool_executor(tool_name, payload)
                    if not isinstance(result, Mapping):
                        raise ValueError("tool output must be a JSON object")
                    outcome.tool_calls.append(ToolCallRecord(
                        len(outcome.tool_calls) + 1, role_id, tool_name, argument_digest,
                        attempt, "completed", digest_value(dict(result)), "",
                        round((time.perf_counter() - started) * 1000, 3),
                    ))
                    return dict(result)
                except Exception as exc:  # executor errors are normalized and raw text is not persisted
                    last_error = exc
                    code = exc.code if isinstance(exc, GovernanceError) else "GOV-RUNTIME-001"
                    outcome.tool_calls.append(ToolCallRecord(
                        len(outcome.tool_calls) + 1, role_id, tool_name, argument_digest,
                        attempt, "failed", "", code,
                        round((time.perf_counter() - started) * 1000, 3),
                    ))
            raise _error("GOV-RUNTIME-001", f"allow-listed tool failed after retry: {tool_name}") from last_error

        def stop(status: str, code: str, message: str, *, role: str, task: str) -> MultiAgentOutcome:
            outcome.status = status
            outcome.error_code = code
            outcome.message = message
            handoff(role, "human_owner", task, status)
            return self._persist(outcome, evidence, request_text, timestamp)

        handoff("human_request", "planner", "decompose_research_request", "received", ())
        capabilities = call("planner", "list_governed_capabilities", {})
        outcome.role_outputs["planner"] = {
            "request_sha256": digest_value(request_text),
            "task_sequence": list(WORKFLOW_SEQUENCE),
            "capabilities": capabilities.get("capabilities", []),
            "stop_conditions_registered": True,
        }
        plan_decision = decisions.get("plan_approval")
        if plan_decision is None:
            return stop("needs_human", "GOV-APPROVAL-001", "plan approval is required", role="planner", task="approve_task_plan")
        if plan_decision.checkpoint_id != "plan_approval":
            raise ValueError("plan decision checkpoint mismatch")
        outcome.human_decisions.append(plan_decision)
        if plan_decision.decision == "rejected":
            return stop("rejected", "GOV-APPROVAL-001", "human rejected the task plan", role="planner", task="plan_rejected")
        if plan_decision.decision == "terminated":
            return stop("blocked", "GOV-STATE-001", "human terminated the workflow", role="planner", task="human_termination")

        handoff("planner", "data_steward", "collect_verified_evidence", "approved")
        if not evidence or any(item.verification_status != "passed" or item.permission_status != "allowed" for item in evidence):
            return stop("blocked", "GOV-EVIDENCE-001", "verified permitted evidence is insufficient", role="data_steward", task="evidence_insufficient")
        try:
            evidence_bundle = call("data_steward", "read_verified_evidence", {"evidence_ids": list(evidence_ids)})
        except MultiAgentError as exc:
            return stop("blocked", exc.code, str(exc), role="data_steward", task="evidence_tool_failed")
        outcome.role_outputs["data_steward"] = evidence_bundle

        handoff("data_steward", "statistics_physics", "run_deterministic_analysis", "verified")
        try:
            statistics = call("statistics_physics", "descriptive_statistics", {"evidence_ids": list(evidence_ids)})
            physics = call("statistics_physics", "physics_card", {"evidence_ids": list(evidence_ids)})
        except MultiAgentError as exc:
            return stop("blocked", exc.code, str(exc), role="statistics_physics", task="deterministic_tool_failed")
        outcome.role_outputs["statistics_physics"] = {"statistics": statistics, "physics": physics}
        outcome.deterministic_outputs_ready = True

        handoff("statistics_physics", "materials_interpreter", "draft_bounded_interpretation", "passed")
        if cloud_available:
            try:
                interpretation = call("materials_interpreter", "bounded_material_interpretation", {"evidence_ids": list(evidence_ids)})
            except MultiAgentError as exc:
                return stop("blocked", exc.code, str(exc), role="materials_interpreter", task="interpretation_tool_failed")
        else:
            interpretation = {
                "claims": [{
                    "claim_id": "CLAIM-OFFLINE-1",
                    "claim_type": "bounded_interpretation",
                    "text": "云模型不可用；确定性数据与物理结果已保留，科学解释等待人工复核。",
                    "evidence_ids": list(evidence_ids),
                }],
                "limitations": ["离线降级未生成云模型解释", "不做因果判断"],
            }
        outcome.role_outputs["materials_interpreter"] = interpretation

        handoff("materials_interpreter", "reviewer", "validate_claim_evidence", "candidate")
        claims = interpretation.get("claims", [])
        known = set(evidence_ids)
        unsupported = [
            str(item.get("claim_id", "unknown"))
            for item in claims
            if not item.get("evidence_ids") or not set(item.get("evidence_ids", [])).issubset(known)
        ]
        review = call("reviewer", "validate_claim_evidence", {"claims": claims})
        unsupported.extend(str(item) for item in review.get("unsupported_claims", []))
        unsupported = sorted(set(unsupported))
        outcome.role_outputs["reviewer"] = {
            "status": "blocked" if unsupported else "passed",
            "unsupported_claims": unsupported,
            "human_approval_authority": False,
        }
        if unsupported:
            return stop("blocked", "GOV-EVIDENCE-001", "reviewer blocked unsupported claims", role="reviewer", task="unsupported_claim_blocked")

        result_decision = decisions.get("result_acceptance")
        if result_decision is None:
            return stop("needs_human", "GOV-APPROVAL-001", "result acceptance is required", role="reviewer", task="accept_or_reject_result")
        if result_decision.checkpoint_id != "result_acceptance":
            raise ValueError("result decision checkpoint mismatch")
        outcome.human_decisions.append(result_decision)
        if result_decision.decision == "rejected":
            return stop("rejected", "GOV-APPROVAL-001", "human rejected the candidate result", role="reviewer", task="result_rejected")
        if result_decision.decision == "terminated":
            return stop("blocked", "GOV-STATE-001", "human terminated the workflow", role="reviewer", task="human_termination")

        outcome.status = "complete"
        outcome.message = "governed multi-agent workflow completed with human acceptance"
        handoff("reviewer", "human_owner", "accepted_workflow_result", "complete")
        return self._persist(outcome, evidence, request_text, timestamp)

    def _persist(self, outcome: MultiAgentOutcome, evidence: Sequence[EvidenceReference], request: str, generated_at: str) -> MultiAgentOutcome:
        if self.output_root is None:
            return outcome
        stage = create_staging_directory(self.output_root, outcome.run_id)
        public_trace = outcome.to_dict()
        public_trace["request_sha256"] = digest_value(request)
        public_trace.pop("audit_package", None)
        public_trace.pop("manifest_sha256", None)
        public_trace.pop("reused", None)
        write_json_atomic(stage / "workflow_trace.json", public_trace)
        summary = {
            "schema_version": "1.0",
            "run_id": outcome.run_id,
            "status": outcome.status,
            "error_code": outcome.error_code,
            "cloud_status": outcome.cloud_status,
            "interpretation_mode": outcome.interpretation_mode,
            "deterministic_outputs_ready": outcome.deterministic_outputs_ready,
            "handoff_count": len(outcome.handoffs),
            "tool_call_count": len(outcome.tool_calls),
            "human_checkpoint_count": len(outcome.human_decisions),
            "raw_prompt_persisted": False,
            "raw_tool_arguments_persisted": False,
            "formal_write_performed": False,
        }
        write_json_atomic(stage / "run_summary.json", summary)
        identity = ResearchObjectIdentity.from_content(
            "multi_agent_run",
            outcome.run_id,
            1,
            {"trace": public_trace, "summary": summary},
            "steelai.multi_agent_orchestrator",
            created_at=generated_at,
        )
        approvals = ()
        accepted = next((item for item in outcome.human_decisions if item.checkpoint_id == "result_acceptance" and item.decision == "approved"), None)
        if accepted is not None:
            approvals = (ApprovalSnapshot.create(
                identity,
                "approved",
                accepted.reviewer_id,
                "T60 multi-agent workflow candidate result",
                accepted.rationale,
                decided_at=accepted.decided_at,
            ),)
        source_records = tuple(SourceReference(
            source_id=item.evidence_id,
            source_revision=item.revision,
            source_digest=item.digest,
            evidence_class=item.evidence_class,
            source_status=item.verification_status,
        ) for item in evidence)
        if not source_records:
            source_records = (SourceReference(
                source_id="REQUEST-" + digest_value(request)[:20].upper(),
                source_revision=1,
                source_digest=digest_value(request),
                evidence_class=EvidenceClass.SYNTHETIC_DEMO_DATA.value,
                source_status="request_only",
            ),)
        evidence_class = (
            EvidenceClass.SYNTHETIC_DEMO_DATA
            if all(item.evidence_class == EvidenceClass.SYNTHETIC_DEMO_DATA.value for item in evidence)
            else EvidenceClass.REAL_RESEARCH_DATA
        )
        result_level = ResultLevel.WORKING_CANDIDATE
        if outcome.status == "complete" and evidence_class == EvidenceClass.SYNTHETIC_DEMO_DATA:
            result_level = ResultLevel.SYNTHETIC_DEMO_ONLY
        manifest = build_manifest(
            stage,
            publication_id=outcome.run_id,
            identity=identity,
            state=outcome.status,
            result_level=result_level,
            evidence_class=evidence_class,
            sources=source_records,
            approvals=approvals,
            generated_by="steelai.multi_agent_orchestrator",
            generated_at=generated_at,
            metadata={
                "feature": "T60",
                "contract_id": "SteelAI-Materials-Multi-Agent-v1.0",
                "cloud_model_optional": True,
                "formal_write": False,
            },
        )
        manifest_digest = seal_package(stage, manifest)
        published = publish_append_only(stage, self.output_root / outcome.run_id)
        outcome.audit_package = published.destination
        outcome.manifest_sha256 = manifest_digest
        outcome.reused = published.reused
        return outcome


def _demo_evidence() -> tuple[EvidenceReference, ...]:
    return (
        EvidenceReference(
            "SYNTH-T60-DATA",
            1,
            digest_value({"fixture": "T60", "kind": "data"}),
            EvidenceClass.SYNTHETIC_DEMO_DATA.value,
        ),
        EvidenceReference(
            "SYNTH-T60-PHYSICS",
            1,
            digest_value({"fixture": "T60", "kind": "physics"}),
            EvidenceClass.SYNTHETIC_DEMO_DATA.value,
        ),
    )


def run_t60_demo(scenario: str, *, output_root: Path | None = MULTI_AGENT_OUTPUTS) -> MultiAgentOutcome:
    """Run frozen synthetic success/failure/offline demonstrations."""
    allowed = {"success", "insufficient_evidence", "tool_failure", "offline_success"}
    if scenario not in allowed:
        raise ValueError(f"unknown T60 demo scenario: {scenario}")
    decisions = {
        "plan_approval": HumanCheckpointDecision.create(
            "plan_approval", "approved", "project_owner_fixture",
            "Frozen synthetic T60 plan approval fixture; not a real research approval.",
            decided_at="2026-09-10T00:00:00+00:00",
        ),
        "result_acceptance": HumanCheckpointDecision.create(
            "result_acceptance", "approved", "project_owner_fixture",
            "Frozen synthetic T60 result acceptance fixture; engineering demonstration only.",
            decided_at="2026-09-10T00:00:00+00:00",
        ),
    }
    evidence = () if scenario == "insufficient_evidence" else _demo_evidence()

    def failing_executor(tool_name: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if tool_name == "descriptive_statistics":
            raise RuntimeError("synthetic tool failure")
        return _default_tool_executor(tool_name, payload)

    return MaterialsMultiAgentOrchestrator(
        output_root=output_root,
        tool_executor=failing_executor if scenario == "tool_failure" else None,
    ).run(
        "使用公开合成证据完成材料数据、描述统计、物理卡和受限解释演示。",
        evidence,
        decisions,
        cloud_available=scenario != "offline_success",
        started_at="2026-09-10T00:00:00+00:00",
        scenario=scenario,
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run frozen T60 governed multi-agent demonstrations.")
    parser.add_argument("scenario", choices=("success", "insufficient_evidence", "tool_failure", "offline_success"))
    args = parser.parse_args()
    result = run_t60_demo(args.scenario)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status in {"complete", "blocked", "needs_human", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
