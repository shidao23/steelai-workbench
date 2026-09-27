"""T55 privacy-first evidence gateway for cloud research agents.

Only verified, allow-listed structured evidence crosses this boundary. The
gateway persists hashes and operational summaries, never questions, answers,
tool arguments or raw tool payloads.
"""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from steelai.governance import (
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
    verify_package,
    write_json_atomic,
)
from steelai.image_model_governance import list_image_model_result_index
from steelai.paths import OUTPUTS
from steelai.research_data_contract import validate_research_data_contract


AGENT_GATEWAY_OUTPUTS = OUTPUTS / "agent_gateway"
GATEWAY_VERSION = "1.0.0"
ALLOWED_AGENT_TOOLS = frozenset({
    "list_samples",
    "get_sample_bundle",
    "compare_samples",
    "calculate_physics_card",
    "get_ebsd_summary",
    "get_autodimple_summary",
    "get_evidence_validation_summary",
    "get_thermal_softening_case",
})
RESTRICTED_OUTPUT_SECTIONS = (
    "已确认事实",
    "当前判断",
    "待验证假设",
    "证据与局限",
    "下一步行动",
)

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\r\t`\"']+")
_PROTECTED_RAW_FILE = re.compile(
    r"[^\s`\"']+\.(?:ctf|ang|tif|tiff|hdr|zarr|pth|pt|onnx|h5|hdf5)\b",
    re.IGNORECASE,
)
_SECRET = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|token|secret)\s*[:=]\s*[^\s,;]+)",
    re.IGNORECASE,
)
_SENSITIVE_EXACT_KEYS = {
    "path", "filepath", "file_path", "filename", "file_name", "locator",
    "source_locator", "raw_path", "raw_file", "raw_filename", "api_key",
    "source", "sources", "directory", "root", "token", "secret", "prompt",
    "question", "answer", "content",
}


class AgentGatewayError(GovernanceError):
    """A fail-closed evidence, privacy or permission rejection."""


def _gateway_error(code: str, message: str, *, state: str = "blocked") -> AgentGatewayError:
    return AgentGatewayError(code, state, message)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower()
    return (
        normalized in _SENSITIVE_EXACT_KEYS
        or normalized.endswith(("_path", "_filepath", "_filename", "_locator", "_secret", "_token"))
        or normalized.startswith(("raw_", "private_"))
    )


def assert_safe_text(value: str, label: str = "content") -> str:
    text = str(value)
    if _ABSOLUTE_PATH.search(text):
        raise _gateway_error("GOV-PRIVACY-001", f"{label} contains a local absolute path")
    if _PROTECTED_RAW_FILE.search(text):
        raise _gateway_error("GOV-PRIVACY-001", f"{label} contains a protected raw filename")
    if _SECRET.search(text):
        raise _gateway_error("GOV-PRIVACY-001", f"{label} contains a possible credential")
    return text


def sanitize_structured_evidence(value: Any) -> Any:
    """Remove denied fields and block sensitive values before model egress."""
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                continue
            clean[str(key)] = sanitize_structured_evidence(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [sanitize_structured_evidence(item) for item in value]
    if isinstance(value, str):
        return assert_safe_text(value, "structured evidence value")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise _gateway_error("GOV-SCHEMA-001", "evidence contains a non-JSON value")


def _validate_arguments(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if tool_name not in ALLOWED_AGENT_TOOLS:
        raise _gateway_error("GOV-AI-AUTH-001", "Agent requested a non-allow-listed tool")
    if not isinstance(arguments, Mapping):
        raise _gateway_error("GOV-SCHEMA-001", "tool arguments must be a JSON object")
    safe = sanitize_structured_evidence(dict(arguments))
    if safe != dict(arguments):
        raise _gateway_error("GOV-PRIVACY-001", "sensitive tool arguments were blocked")
    allowed_arguments = {
        "list_samples": set(),
        "get_sample_bundle": {"sample_id"},
        "compare_samples": {"control_id", "comparison_id"},
        "calculate_physics_card": {"sample_id"},
        "get_ebsd_summary": {"scale"},
        "get_autodimple_summary": set(),
        "get_evidence_validation_summary": set(),
        "get_thermal_softening_case": {"case_id"},
    }[tool_name]
    if set(safe) != allowed_arguments:
        raise _gateway_error("GOV-AI-AUTH-001", "tool arguments do not match the fixed read-only contract")
    return safe


def normalize_restricted_output(answer: str) -> dict[str, Any]:
    """Convert provider prose to the stable five-section explanation contract."""
    text = assert_safe_text(answer, "model response").strip()
    sections: dict[str, list[str]] = {name: [] for name in RESTRICTED_OUTPUT_SECTIONS}
    current: str | None = None
    unclassified: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = line.lstrip("#").strip()
        if heading in sections:
            current = heading
            continue
        if not line:
            continue
        value = line[1:].strip() if line.startswith(("-", "*")) else line
        if current is None:
            unclassified.append(value)
        else:
            sections[current].append(value)
    if unclassified:
        sections["证据与局限"].extend(f"未分类模型文本：{item}" for item in unclassified)
    missing = [name for name, values in sections.items() if not values]
    return {
        "schema_version": "1.0",
        "contract_id": "SteelAI-Restricted-Agent-Explanation-v1.0",
        "contract_status": "passed" if not missing else "warning",
        "sections": sections,
        "missing_sections": missing,
        "boundaries": {
            "human_approval": False,
            "formal_write": False,
            "shell_execution": False,
            "scientific_conclusion": False,
            "requires_human_review": True,
        },
    }


@dataclass(frozen=True)
class EvidencePermit:
    evidence_id: str
    source_digest: str
    evidence_class: str
    verification_status: str
    permission_status: str
    tool_name: str
    scope: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class AgentEvidenceGateway:
    question: str
    provider: str
    model: str
    allowed_tools: tuple[str, ...]
    output_root: Path | None = None
    started_at: str = field(default_factory=utc_now)
    evidence_permits: dict[str, EvidencePermit] = field(default_factory=dict)
    tool_audit: list[dict[str, Any]] = field(default_factory=list)
    request_sequence: int = 0
    _stage: Path | None = field(init=False, default=None)
    _contract_snapshot: dict[str, Any] | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.question = assert_safe_text(self.question.strip(), "research question")
        if not self.question:
            raise _gateway_error("GOV-SCHEMA-001", "research question is empty")
        self.provider = assert_safe_text(self.provider.strip(), "provider identity")
        self.model = assert_safe_text(self.model.strip(), "model identity")
        if not self.provider or not self.model:
            raise _gateway_error("GOV-RUNTIME-001", "provider and model identity are required")
        if set(self.allowed_tools) - ALLOWED_AGENT_TOOLS:
            raise _gateway_error("GOV-AI-AUTH-001", "gateway contains an unauthorized tool")
        seed = {
            "question_digest": digest_value(self.question),
            "provider": self.provider,
            "model": self.model,
            "started_at": self.started_at,
        }
        self.gateway_id = "AGENTGW-" + digest_value(seed)[:20].upper()
        if self.output_root is not None:
            self._stage = create_staging_directory(self.output_root, self.gateway_id)
            self._write_send_summary()

    @property
    def question_digest(self) -> str:
        return digest_value(self.question)

    def send_summary(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "gateway_version": GATEWAY_VERSION,
            "gateway_id": self.gateway_id,
            "provider": self.provider,
            "model": self.model,
            "question_sha256": self.question_digest,
            "question_character_count": len(self.question),
            "request_sequence": self.request_sequence,
            "allowed_tools": list(self.allowed_tools),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_class": item.evidence_class,
                    "verification_status": item.verification_status,
                    "permission_status": item.permission_status,
                    "tool_name": item.tool_name,
                    "payload_or_source_sha256": item.source_digest,
                }
                for item in self.evidence_permits.values()
            ],
            "privacy": {
                "raw_question_persisted": False,
                "raw_answer_persisted": False,
                "tool_arguments_persisted": False,
                "tool_payloads_persisted": False,
                "absolute_paths_allowed": False,
                "protected_filenames_allowed": False,
                "credentials_allowed": False,
            },
            "authority": {
                "read_only": True,
                "approval_allowed": False,
                "formal_write_allowed": False,
                "shell_allowed": False,
            },
        }

    def _write_send_summary(self) -> None:
        if self._stage is not None:
            write_json_atomic(self._stage / "send_summary.json", self.send_summary())

    def before_model_call(self) -> dict[str, Any]:
        self.request_sequence += 1
        self._write_send_summary()
        return self.send_summary()

    def _research_contract(self) -> dict[str, Any]:
        if self._contract_snapshot is None:
            self._contract_snapshot = validate_research_data_contract()
        if self._contract_snapshot.get("contract_status") != "passed":
            raise _gateway_error("GOV-EVIDENCE-001", "research data contract is not verified")
        return self._contract_snapshot

    def _permit_for_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> EvidencePermit:
        safe_arguments = _validate_arguments(tool_name, arguments)
        if tool_name in {
            "list_samples", "get_sample_bundle", "compare_samples", "calculate_physics_card",
        }:
            contract = self._research_contract()
            source_digest = digest_value({
                "contract_id": contract.get("contract_id"),
                "contract_status": contract.get("contract_status"),
                "sample_count": contract.get("sample_count"),
                "tables": contract.get("tables"),
            })
            evidence_class = EvidenceClass.REAL_RESEARCH_DATA.value
            scope = "contract-verified structured processed evidence"
        elif tool_name == "get_evidence_validation_summary":
            source_digest = digest_value({
                "policy": "SteelAI evidence validation",
                "tool": tool_name,
                "version": GATEWAY_VERSION,
            })
            evidence_class = EvidenceClass.HUMAN_CONCLUSION.value
            scope = "deterministic evidence and claim boundary policy"
        elif tool_name == "get_thermal_softening_case":
            from steelai.thermal_softening_case import load_softening_case

            case = load_softening_case(str(safe_arguments["case_id"]))
            source_digest = digest_value(case)
            evidence_class = EvidenceClass.REAL_RESEARCH_DATA.value
            scope = "hash-verified approved T75 data with literature-linked draft; conclusions need human review"
        else:
            modality = "EBSD" if tool_name == "get_ebsd_summary" else "SEM"
            reviewed = [
                row for row in list_image_model_result_index()
                if row.get("modality") == modality and row.get("evidence_eligible") is True
                and row.get("governance_state") == "complete"
            ]
            if not reviewed:
                raise _gateway_error(
                    "GOV-EVIDENCE-001",
                    f"{modality} evidence has no verified and human-reviewed T54 result",
                    state="needs_human",
                )
            safe_review = [{
                "review_id": row.get("review_id"),
                "run_id": row.get("run_id"),
                "task_id": row.get("task_id"),
                "result_level": row.get("result_level"),
                "accepted_output_ids": row.get("accepted_output_ids", []),
            } for row in reviewed]
            source_digest = digest_value(safe_review)
            evidence_class = EvidenceClass.MODEL_OUTPUT.value
            scope = f"verified human-reviewed {modality} model results"
        permit_digest = digest_value({
            "tool": tool_name,
            "arguments_digest": digest_value(safe_arguments),
            "source_digest": source_digest,
            "scope": scope,
        })
        return EvidencePermit(
            evidence_id="AGEVID-" + permit_digest[:20].upper(),
            source_digest=source_digest,
            evidence_class=evidence_class,
            verification_status="passed",
            permission_status="allowed",
            tool_name=tool_name,
            scope=scope,
        )

    def execute_evidence_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        executor: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        round_number: int,
        duration_ms: float | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        safe_arguments = _validate_arguments(tool_name, arguments)
        permit = self._permit_for_tool(tool_name, safe_arguments)
        raw_result = executor(tool_name, safe_arguments)
        if not isinstance(raw_result, Mapping):
            raise _gateway_error("GOV-SCHEMA-001", "tool output must be a JSON object")
        safe_result = sanitize_structured_evidence(raw_result)
        payload_digest = digest_value(safe_result)
        evidence_id = "AGEVID-" + digest_value({
            "permit_id": permit.evidence_id,
            "payload_digest": payload_digest,
        })[:20].upper()
        evidence = EvidencePermit(
            evidence_id=evidence_id,
            source_digest=payload_digest,
            evidence_class=permit.evidence_class,
            verification_status=permit.verification_status,
            permission_status=permit.permission_status,
            tool_name=permit.tool_name,
            scope=permit.scope,
        )
        self.evidence_permits[evidence.evidence_id] = evidence
        self.tool_audit.append({
            "round": round_number,
            "tool": tool_name,
            "arguments_sha256": digest_value(safe_arguments),
            "evidence_id": evidence.evidence_id,
            "status": "completed",
            "duration_ms": duration_ms if duration_ms is not None else round(
                (time.perf_counter() - started) * 1000,
                1,
            ),
        })
        self._write_send_summary()
        enriched = dict(safe_result)
        enriched["_gateway"] = {
            "evidence_id": evidence.evidence_id,
            "verification_status": "passed",
            "permission_status": "allowed",
            "payload_sha256": payload_digest,
        }
        return enriched

    def record_failed_tool(
        self,
        tool_name: str,
        arguments: Any,
        *,
        round_number: int,
        error: Exception,
        duration_ms: float,
    ) -> dict[str, Any]:
        safe_tool = str(tool_name) if tool_name in ALLOWED_AGENT_TOOLS else "blocked_non_allowlisted_tool"
        error_code = getattr(error, "code", type(error).__name__)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(error_code)):
            error_code = type(error).__name__
        record = {
            "round": round_number,
            "tool": safe_tool,
            "arguments_sha256": digest_value(arguments),
            "evidence_id": None,
            "status": "blocked" if isinstance(error, GovernanceError) else "failed",
            "error_code": str(error_code),
            "duration_ms": duration_ms,
        }
        self.tool_audit.append(record)
        return dict(record)

    def finalize(
        self,
        *,
        status: str,
        answer: str,
        response_id: str,
        usage: Mapping[str, Any],
        error: str,
    ) -> dict[str, Any]:
        structured: dict[str, Any] = {}
        final_status = status
        final_error = error
        if answer:
            try:
                structured = normalize_restricted_output(answer)
            except AgentGatewayError as exc:
                final_status = "blocked"
                final_error = f"{exc.code}: model response failed the privacy boundary"
                answer = ""
        summary = self.send_summary()
        audit = {
            "schema_version": "1.0",
            "gateway_id": self.gateway_id,
            "gateway_version": GATEWAY_VERSION,
            "provider": self.provider,
            "model": self.model,
            "status": final_status,
            "question_sha256": self.question_digest,
            "response_sha256": digest_value(answer) if answer else None,
            "response_id_sha256": digest_value(response_id) if response_id else None,
            "structured_output_contract_status": structured.get("contract_status", "not_available"),
            "structured_section_counts": {
                name: len(structured.get("sections", {}).get(name, []))
                for name in RESTRICTED_OUTPUT_SECTIONS
            },
            "tool_calls": self.tool_audit,
            "evidence_ids": sorted(self.evidence_permits),
            "usage": {
                key: int(usage.get(key, 0) or 0)
                for key in ("input_tokens", "output_tokens", "total_tokens")
            },
            "failure": {
                "present": bool(final_error),
                "error_type": final_error.split(":", 1)[0] if final_error else None,
                "raw_error_persisted": False,
            },
            "raw_question_persisted": False,
            "raw_answer_persisted": False,
            "raw_tool_arguments_persisted": False,
            "raw_tool_payloads_persisted": False,
            "human_review_required": True,
        }
        package = ""
        manifest_digest = ""
        if self._stage is not None:
            write_json_atomic(self._stage / "send_summary.json", summary)
            write_json_atomic(self._stage / "agent_run_audit.json", audit)
            write_json_atomic(self._stage / "restricted_output_contract.json", {
                "schema_version": "1.0",
                "contract_id": "SteelAI-Restricted-Agent-Explanation-v1.0",
                "contract_status": structured.get("contract_status", "not_available"),
                "section_counts": audit["structured_section_counts"],
                "boundaries": structured.get("boundaries", {
                    "human_approval": False,
                    "formal_write": False,
                    "shell_execution": False,
                    "scientific_conclusion": False,
                    "requires_human_review": True,
                }),
            })
            completed_at = utc_now()
            identity_payload = {
                "send_summary": summary,
                "audit": audit,
            }
            identity = ResearchObjectIdentity(
                object_type="agent_gateway_run",
                object_id=self.gateway_id,
                revision=1,
                content_digest=digest_value(identity_payload),
                created_at=completed_at,
                created_by="steelai-agent-evidence-gateway",
            )
            sources = [SourceReference(
                source_id="REQUEST-" + self.question_digest[:20].upper(),
                source_revision=1,
                source_digest=self.question_digest,
                evidence_class=EvidenceClass.HUMAN_CONCLUSION.value,
                source_status="user_question_validated_not_persisted",
            )]
            for permit in self.evidence_permits.values():
                sources.append(SourceReference(
                    source_id=permit.evidence_id,
                    source_revision=1,
                    source_digest=permit.source_digest,
                    evidence_class=permit.evidence_class,
                    source_status="verified_allowed_structured_evidence",
                ))
            manifest = build_manifest(
                self._stage,
                publication_id=self.gateway_id,
                identity=identity,
                state="complete" if final_status == "completed" else "blocked",
                result_level=ResultLevel.WORKING_CANDIDATE,
                evidence_class=EvidenceClass.MODEL_OUTPUT,
                sources=sources,
                generated_by="steelai-agent-evidence-gateway",
                generated_at=completed_at,
                metadata={
                    "provider": self.provider,
                    "model": self.model,
                    "tool_call_count": len(self.tool_audit),
                    "human_review_required": True,
                    "formal_write_allowed": False,
                },
            )
            seal_package(self._stage, manifest)
            destination = self.output_root.resolve() / self.gateway_id
            publication = publish_append_only(self._stage, destination)
            package = publication.destination
            manifest_digest = publication.manifest_digest
            self._stage = None
        return {
            "status": final_status,
            "answer": answer,
            "error": final_error,
            "structured_output": structured,
            "send_summary": summary,
            "gateway_id": self.gateway_id,
            "audit_package": package,
            "manifest_sha256": manifest_digest,
        }

    def abandon(self) -> None:
        if self._stage is not None and self._stage.exists():
            shutil.rmtree(self._stage)
            self._stage = None


def preview_agent_send_summary(
    question: str,
    *,
    provider: str,
    model: str,
    allowed_tools: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    gateway = AgentEvidenceGateway(question, provider, model, tuple(allowed_tools), output_root=None)
    return gateway.send_summary()


def inspect_agent_gateway_package(package: str | Path) -> dict[str, Any]:
    return verify_package(package).to_dict()
