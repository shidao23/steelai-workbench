"""T61 governed MCP tool layer and lightweight A2A task envelope.

This module implements the locally tested SteelAI subset only. It does not
claim complete MCP or A2A interoperability, network discovery, streaming, or
remote agent identity federation.
"""
from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from steelai.agent_evidence_gateway import assert_safe_text, sanitize_structured_evidence
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
from steelai.multi_agent_orchestrator import WORKFLOW_SEQUENCE
from steelai.paths import OUTPUTS, ROOT
from steelai.research_tools import execute_readonly_tool
from steelai.workflow_identity import WorkflowIdentity, validate_workflow_identity_contract


MCP_TOOL_MANIFEST_PATH = ROOT / "config" / "research_mcp_tools_v1.0.json"
A2A_CONTRACT_PATH = ROOT / "config" / "a2a_task_envelope_v1.0.json"
PROTOCOL_OUTPUTS = OUTPUTS / "protocol_calls"
PROTOCOL_VERSION = "1.0.0"
TASK_STATUSES = frozenset({"proposed", "accepted", "running", "completed", "blocked", "rejected"})
_HUMAN_FORBIDDEN = frozenset({"", "ai", "agent", "system", "model", "llm", "gpt", "chatgpt"})


class ResearchProtocolError(GovernanceError):
    """Stable fail-closed MCP/A2A contract error."""


def _error(code: str, message: str, *, state: str = "blocked") -> ResearchProtocolError:
    return ResearchProtocolError(code, state, message)


def _identifier(value: Any, name: str, *, maximum: int = 160) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum or text in {".", ".."} or any(c in text for c in "/\\\r\n\t"):
        raise _error("GOV-SCHEMA-001", f"{name} must be a non-path identifier")
    return text


def _timestamp(value: str, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("GOV-SCHEMA-001", f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise _error("GOV-SCHEMA-001", f"{name} requires a timezone")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("contract must be a JSON object")
    return payload


def load_tool_manifest(path: Path = MCP_TOOL_MANIFEST_PATH) -> dict[str, Any]:
    return _load_json(path)


def load_a2a_contract(path: Path = A2A_CONTRACT_PATH) -> dict[str, Any]:
    return _load_json(path)


def validate_protocol_contracts(tool_path: Path = MCP_TOOL_MANIFEST_PATH, a2a_path: Path = A2A_CONTRACT_PATH) -> dict[str, Any]:
    problems: list[str] = []
    try:
        tools = load_tool_manifest(tool_path)
        a2a = load_a2a_contract(a2a_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": "1.0", "status": "failed", "problems": [str(exc)]}
    if tools.get("manifest_id") != "SteelAI-Research-MCP-Tools-v1.0" or tools.get("schema_version") != "1.0":
        problems.append("MCP tool manifest identity mismatch")
    if tools.get("transport") != "stdio" or tools.get("complete_mcp_or_a2a_compatibility_claimed") is not False:
        problems.append("MCP scope must remain local stdio and limited")
    entries = tools.get("tools", [])
    expected_tools = {
        "query_samples", "get_verified_evidence", "run_descriptive_statistics",
        "run_physics_calculation", "generate_report_candidate",
    }
    if {item.get("tool_id") for item in entries if isinstance(item, Mapping)} != expected_tools:
        problems.append("exactly five frozen research tools are required")
    for item in entries:
        required = {
            "tool_id", "version", "owner_role", "allowed_roles", "permission",
            "requires_task_approval", "timeout_ms", "idempotent", "formal_result_allowed",
            "input_schema", "output_schema", "error_codes",
        }
        if not isinstance(item, Mapping) or set(item) != required:
            problems.append(f"tool {item.get('tool_id', '?') if isinstance(item, Mapping) else '?'} fields mismatch")
            continue
        if item.get("owner_role") not in WORKFLOW_SEQUENCE or set(item.get("allowed_roles", [])) - set(WORKFLOW_SEQUENCE):
            problems.append(f"tool {item.get('tool_id')} contains an unknown role")
        if item.get("idempotent") is not True or item.get("formal_result_allowed") is not False:
            problems.append(f"tool {item.get('tool_id')} must be idempotent and nonformal")
        if not isinstance(item.get("timeout_ms"), int) or not 100 <= item["timeout_ms"] <= 30000:
            problems.append(f"tool {item.get('tool_id')} timeout is outside the frozen limit")
        if item.get("input_schema", {}).get("additionalProperties") is not False:
            problems.append(f"tool {item.get('tool_id')} input schema must be closed")
        if not item.get("error_codes"):
            problems.append(f"tool {item.get('tool_id')} has no stable error codes")
    if a2a.get("contract_id") != "SteelAI-Lightweight-A2A-Task-v1.0" or a2a.get("schema_version") != "1.0":
        problems.append("A2A contract identity mismatch")
    if a2a.get("workflow_identity_contract_id") != "Shidao-Workflow-Identity-v1.0":
        problems.append("A2A workflow identity contract mismatch")
    expected_a2a_fields = {
        "schema_version", "request_id", "task_id", "task_revision", "sender_role",
        "receiver_role", "evidence_refs", "status", "created_at", "updated_at",
        "result_summary", "task_digest",
    }
    if set(a2a.get("required_fields", [])) != expected_a2a_fields:
        problems.append("A2A required fields mismatch")
    identity_contract = validate_workflow_identity_contract()
    if identity_contract.get("status") != "passed":
        problems.extend("workflow identity: " + item for item in identity_contract.get("problems", []))
    if tuple(a2a.get("roles", [])) != WORKFLOW_SEQUENCE:
        problems.append("A2A roles must match the T60 role sequence")
    if set(a2a.get("statuses", [])) != TASK_STATUSES:
        problems.append("A2A status vocabulary mismatch")
    if a2a.get("complete_a2a_protocol_compatibility_claimed") is not False:
        problems.append("complete A2A compatibility must not be claimed")
    return {
        "schema_version": "1.0",
        "status": "passed" if not problems else "failed",
        "tool_manifest_id": tools.get("manifest_id", ""),
        "a2a_contract_id": a2a.get("contract_id", ""),
        "tool_count": len(entries),
        "role_count": len(a2a.get("roles", [])),
        "problems": problems,
    }


@dataclass(frozen=True)
class ProtocolEvidenceReference:
    evidence_id: str
    revision: int
    digest: str
    evidence_class: str
    verification_status: str = "passed"
    permission_status: str = "allowed"

    def __post_init__(self) -> None:
        _identifier(self.evidence_id, "evidence_id")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise _error("GOV-SCHEMA-001", "evidence revision must be positive")
        if len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest):
            raise _error("GOV-SCHEMA-001", "evidence digest must be lowercase SHA-256")
        EvidenceClass(self.evidence_class)
        if self.verification_status != "passed" or self.permission_status != "allowed":
            raise _error("GOV-EVIDENCE-001", "A2A evidence must be verified and permitted")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolEvidenceReference":
        expected = {"evidence_id", "revision", "digest", "evidence_class", "verification_status", "permission_status"}
        if set(value) != expected:
            raise _error("GOV-SCHEMA-001", "evidence reference fields mismatch")
        return cls(**dict(value))


@dataclass(frozen=True)
class A2ATaskEnvelope:
    request_id: str
    task_id: str
    task_revision: int
    sender_role: str
    receiver_role: str
    evidence_refs: tuple[ProtocolEvidenceReference, ...]
    status: str
    created_at: str
    updated_at: str
    result_summary: str

    def __post_init__(self) -> None:
        WorkflowIdentity(self.request_id, self.task_id, None, self.task_revision)
        if self.task_revision < 1:
            raise _error("GOV-SCHEMA-001", "task revision must be positive")
        if self.sender_role not in WORKFLOW_SEQUENCE or self.receiver_role not in WORKFLOW_SEQUENCE:
            raise _error("GOV-AI-AUTH-001", "A2A sender and receiver must be registered T60 roles")
        if self.sender_role == self.receiver_role:
            raise _error("GOV-SCHEMA-001", "A2A sender and receiver must differ")
        if self.status not in TASK_STATUSES:
            raise _error("GOV-STATE-001", "A2A task status is not registered")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        assert_safe_text(self.result_summary, "A2A result summary")

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "request_id": self.request_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "sender_role": self.sender_role,
            "receiver_role": self.receiver_role,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result_summary": self.result_summary,
        }

    @property
    def task_digest(self) -> str:
        return digest_value(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "task_digest": self.task_digest}

    @classmethod
    def create(cls, sender_role: str, receiver_role: str, evidence_refs: Sequence[ProtocolEvidenceReference], *, status: str = "proposed", result_summary: str = "", created_at: str | None = None, request_id: str | None = None, task_id: str | None = None) -> "A2ATaskEnvelope":
        timestamp = created_at or utc_now()
        seed = {"sender_role": sender_role, "receiver_role": receiver_role, "evidence": [item.to_dict() for item in evidence_refs], "created_at": timestamp}
        workflow = WorkflowIdentity.create(seed=seed, request_id=request_id, task_id=task_id)
        return cls(workflow.request_id, workflow.task_id, 1, sender_role, receiver_role, tuple(evidence_refs), status, timestamp, timestamp, result_summary)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "A2ATaskEnvelope":
        expected = {"schema_version", "request_id", "task_id", "task_revision", "sender_role", "receiver_role", "evidence_refs", "status", "created_at", "updated_at", "result_summary", "task_digest"}
        if set(value) != expected or value.get("schema_version") != "1.0":
            raise _error("GOV-SCHEMA-001", "A2A task envelope fields mismatch")
        envelope = cls(
            request_id=value["request_id"], task_id=value["task_id"], task_revision=value["task_revision"],
            sender_role=value["sender_role"], receiver_role=value["receiver_role"],
            evidence_refs=tuple(ProtocolEvidenceReference.from_dict(item) for item in value["evidence_refs"]),
            status=value["status"], created_at=value["created_at"], updated_at=value["updated_at"],
            result_summary=value["result_summary"],
        )
        if value.get("task_digest") != envelope.task_digest:
            raise _error("GOV-INTEGRITY-001", "A2A task digest mismatch", state="invalidated")
        return envelope

    def handoff(self, receiver_role: str, *, status: str, result_summary: str, updated_at: str | None = None) -> "A2ATaskEnvelope":
        return A2ATaskEnvelope(
            request_id=self.request_id,
            task_id=self.task_id,
            task_revision=self.task_revision + 1,
            sender_role=self.receiver_role,
            receiver_role=receiver_role,
            evidence_refs=self.evidence_refs,
            status=status,
            created_at=self.created_at,
            updated_at=updated_at or utc_now(),
            result_summary=result_summary,
        )


@dataclass(frozen=True)
class TaskApprovalPermit:
    approval_id: str
    task_id: str
    task_revision: int
    task_digest: str
    decision: str
    reviewer_id: str

    def __post_init__(self) -> None:
        _identifier(self.approval_id, "approval_id")
        reviewer = self.reviewer_id.strip().casefold()
        if reviewer in _HUMAN_FORBIDDEN or reviewer.startswith(("agent-", "ai-", "model-")):
            raise _error("GOV-AI-AUTH-001", "task approval reviewer must identify a human")
        if self.decision != "approved":
            raise _error("GOV-APPROVAL-001", "task execution requires an approved permit")

    @classmethod
    def create(cls, task: A2ATaskEnvelope, reviewer_id: str) -> "TaskApprovalPermit":
        seed = {"task_id": task.task_id, "task_revision": task.task_revision, "task_digest": task.task_digest, "reviewer_id": reviewer_id}
        return cls("A2AAPR-" + digest_value(seed)[:20].upper(), task.task_id, task.task_revision, task.task_digest, "approved", reviewer_id)

    def matches(self, task: A2ATaskEnvelope) -> bool:
        return self.task_id == task.task_id and self.task_revision == task.task_revision and self.task_digest == task.task_digest

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskApprovalPermit":
        expected = {"approval_id", "task_id", "task_revision", "task_digest", "decision", "reviewer_id"}
        if set(value) != expected:
            raise _error("GOV-SCHEMA-001", "task approval fields mismatch")
        return cls(**dict(value))


@dataclass(frozen=True)
class ProtocolToolRequest:
    request_id: str
    idempotency_key: str
    task: A2ATaskEnvelope
    input_version: str
    arguments: Mapping[str, Any]
    approval: TaskApprovalPermit | None = None

    def __post_init__(self) -> None:
        WorkflowIdentity(self.request_id, self.task.task_id, None, self.task.task_revision)
        if self.request_id != self.task.request_id:
            raise _error("GOV-INTEGRITY-001", "request_id does not match the task envelope", state="invalidated")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolToolRequest":
        required = {"schema_version", "request_id", "idempotency_key", "task", "input_version", "arguments"}
        allowed = required | {"approval"}
        if not required.issubset(value) or not set(value).issubset(allowed) or value.get("schema_version") != "1.0":
            raise _error("GOV-SCHEMA-001", "protocol tool request fields mismatch")
        arguments = value.get("arguments")
        if not isinstance(arguments, Mapping):
            raise _error("GOV-SCHEMA-001", "tool arguments must be an object")
        approval = value.get("approval")
        return cls(
            _identifier(value["request_id"], "request_id"),
            _identifier(value["idempotency_key"], "idempotency_key"),
            A2ATaskEnvelope.from_dict(value["task"]),
            _identifier(value["input_version"], "input_version"),
            dict(arguments),
            TaskApprovalPermit.from_dict(approval) if isinstance(approval, Mapping) else None,
        )

    def digest_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "task": self.task.to_dict(),
            "input_version": self.input_version,
            "arguments": dict(self.arguments),
            "approval": self.approval.to_dict() if self.approval else None,
        }

    @property
    def request_digest(self) -> str:
        return digest_value(self.digest_payload())


ToolBackend = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def _validate_arguments(arguments: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    missing = set(schema.get("required", [])) - set(arguments)
    if unknown or missing:
        raise _error("GOV-SCHEMA-001", f"tool arguments mismatch; missing={sorted(missing)}, extra={sorted(unknown)}")
    clean: dict[str, Any] = {}
    for key, value in arguments.items():
        rule = properties[key]
        if rule.get("type") == "string":
            if not isinstance(value, str) or not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 10000):
                raise _error("GOV-SCHEMA-001", f"argument {key} is invalid")
            clean[key] = _identifier(value, key, maximum=rule.get("maxLength", 160))
        elif rule.get("type") == "array":
            if not isinstance(value, list) or isinstance(value, (str, bytes)):
                raise _error("GOV-SCHEMA-001", f"argument {key} must be an array")
            if not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", 10000):
                raise _error("GOV-SCHEMA-001", f"argument {key} item count is invalid")
            if rule.get("uniqueItems") and len(set(value)) != len(value):
                raise _error("GOV-SCHEMA-001", f"argument {key} must contain unique items")
            clean[key] = [_identifier(item, key) for item in value]
        else:
            raise _error("GOV-SCHEMA-001", f"argument schema for {key} is unsupported")
    return clean


class GovernedResearchToolLayer:
    def __init__(
        self,
        *,
        output_root: Path | None = PROTOCOL_OUTPUTS,
        backend: ToolBackend | None = None,
        tool_manifest_path: Path = MCP_TOOL_MANIFEST_PATH,
        a2a_contract_path: Path = A2A_CONTRACT_PATH,
    ) -> None:
        validation = validate_protocol_contracts(tool_manifest_path, a2a_contract_path)
        if validation.get("status") != "passed":
            raise _error("GOV-SCHEMA-001", "T61 protocol contracts are invalid")
        self.output_root = output_root
        self.backend = backend or self._default_backend
        self._manifest = load_tool_manifest(tool_manifest_path)

    def tool_catalog(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._manifest["tools"]]

    def _definition(self, tool_name: str) -> dict[str, Any]:
        for item in self._manifest["tools"]:
            if item["tool_id"] == tool_name:
                return item
        raise _error("GOV-AI-AUTH-001", "unregistered MCP tool")

    def execute(self, tool_name: str, request_value: Mapping[str, Any]) -> dict[str, Any]:
        definition = self._definition(tool_name)
        request = ProtocolToolRequest.from_dict(request_value)
        if request.task.receiver_role not in definition["allowed_roles"]:
            raise _error("GOV-AI-AUTH-001", "task receiver role is not authorized for this tool")
        arguments = _validate_arguments(request.arguments, definition["input_schema"])
        if definition["requires_task_approval"]:
            if request.approval is None or not request.approval.matches(request.task):
                raise _error("GOV-APPROVAL-001", "current task revision lacks a matching human approval")
        call_id = "MCP-" + digest_value({"tool": tool_name, "idempotency_key": request.idempotency_key})[:20].upper()
        workflow = WorkflowIdentity(
            request.request_id,
            request.task.task_id,
            None,
            request.task.task_revision,
        ).start_run(seed={"tool": tool_name, "idempotency_key": request.idempotency_key})
        existing = self._load_existing(call_id, request.request_digest)
        if existing is not None:
            existing["reused"] = True
            return existing

        status = "completed"
        error_code = ""
        message = "tool completed"
        result: dict[str, Any] = {}
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="steelai-t61")
        future = executor.submit(self.backend, tool_name, arguments)
        try:
            raw = future.result(timeout=definition["timeout_ms"] / 1000)
            if not isinstance(raw, Mapping):
                raise _error("GOV-SCHEMA-001", "tool backend returned a non-object result")
            result = sanitize_structured_evidence(dict(raw))
        except FutureTimeout:
            future.cancel()
            status, error_code, message = "blocked", "GOV-RUNTIME-001", "tool execution timed out"
        except GovernanceError as exc:
            status, error_code, message = "blocked", exc.code, "tool execution was blocked"
        except Exception:
            status, error_code, message = "blocked", "GOV-RUNTIME-001", "tool execution failed"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        response = {
            "schema_version": "1.0",
            "protocol_version": PROTOCOL_VERSION,
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "tool_version": definition["version"],
            "request_id": workflow.request_id,
            "task_id": request.task.task_id,
            "task_revision": request.task.task_revision,
            "run_id": workflow.run_id,
            "caller_role": request.task.receiver_role,
            "input_version": request.input_version,
            "request_sha256": request.request_digest,
            "status": status,
            "error_code": error_code,
            "message": message,
            "result": result,
            "result_sha256": digest_value(result),
            "formal_result": False,
            "human_review_required": True,
            "reused": False,
        }
        if self.output_root is not None:
            self._persist(response, request, definition)
        return response

    def _load_existing(self, call_id: str, request_digest: str) -> dict[str, Any] | None:
        if self.output_root is None:
            return None
        target = self.output_root / call_id
        if not target.exists():
            return None
        verification = verify_package(target)
        if verification.status != "passed":
            raise _error("GOV-INTEGRITY-001", "existing tool receipt is invalidated", state="invalidated")
        payload = json.loads((target / "tool_response.json").read_text(encoding="utf-8"))
        if payload.get("request_sha256") != request_digest:
            raise _error("GOV-DUPLICATE-001", "idempotency key is already bound to different input")
        return payload

    def _persist(self, response: Mapping[str, Any], request: ProtocolToolRequest, definition: Mapping[str, Any]) -> None:
        assert self.output_root is not None
        call_id = str(response["tool_call_id"])
        stage = create_staging_directory(self.output_root, call_id)
        write_json_atomic(stage / "tool_response.json", dict(response))
        receipt = {
            "schema_version": "1.0",
            "tool_call_id": call_id,
            "request_id": response["request_id"],
            "task_id": request.task.task_id,
            "task_revision": request.task.task_revision,
            "run_id": response["run_id"],
            "task_digest": request.task.task_digest,
            "input_version": request.input_version,
            "request_sha256": request.request_digest,
            "tool_name": definition["tool_id"],
            "tool_version": definition["version"],
            "permission": definition["permission"],
            "timeout_ms": definition["timeout_ms"],
            "status": response["status"],
            "error_code": response["error_code"],
            "result_sha256": response["result_sha256"],
            "raw_arguments_persisted": False,
            "formal_write_performed": False,
        }
        write_json_atomic(stage / "tool_receipt.json", receipt)
        identity = ResearchObjectIdentity.from_content(
            "research_protocol_call", call_id, 1,
            {"response": dict(response), "receipt": receipt},
            "steelai.research_protocol",
        )
        sources = tuple(SourceReference(
            source_id=item.evidence_id,
            source_revision=item.revision,
            source_digest=item.digest,
            evidence_class=item.evidence_class,
            source_status=item.verification_status,
        ) for item in request.task.evidence_refs)
        if not sources:
            sources = (SourceReference(
                source_id=request.task.task_id,
                source_revision=request.task.task_revision,
                source_digest=request.task.task_digest,
                evidence_class=EvidenceClass.SYNTHETIC_DEMO_DATA.value,
                source_status="task_envelope_only",
            ),)
        evidence_class = EvidenceClass.SYNTHETIC_DEMO_DATA
        if any(item.evidence_class != EvidenceClass.SYNTHETIC_DEMO_DATA.value for item in request.task.evidence_refs):
            evidence_class = EvidenceClass.REAL_RESEARCH_DATA
        manifest = build_manifest(
            stage,
            publication_id=call_id,
            identity=identity,
            state="complete" if response["status"] == "completed" else "blocked",
            result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=evidence_class,
            sources=sources,
            generated_by="steelai.research_protocol",
            metadata={
                "feature": "T61",
                "protocol_scope": "local_stdio_subset",
                "formal_result": False,
                "human_review_required": True,
                "workflow_identity": {
                    "schema_version": "1.0",
                    "request_id": response["request_id"],
                    "task_id": response["task_id"],
                    "run_id": response["run_id"],
                    "task_revision": response["task_revision"],
                },
            },
        )
        seal_package(stage, manifest)
        publish_append_only(stage, self.output_root / call_id)

    def _default_backend(self, tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if tool_name == "query_samples":
            payload = execute_readonly_tool("list_samples", {})
            return {"samples": payload.get("samples", []), "count": payload.get("count", 0)}
        if tool_name == "get_verified_evidence":
            sample_id = str(arguments["sample_id"])
            payload = execute_readonly_tool("get_sample_bundle", {"sample_id": sample_id})
            tables = sorted(payload.get("data", {}))
            return {"sample_id": sample_id, "evidence_status": "verified", "tables": tables, "bundle_sha256": digest_value(payload)}
        if tool_name == "run_descriptive_statistics":
            sample_ids = list(arguments["sample_ids"])
            rows = [execute_readonly_tool("get_sample_bundle", {"sample_id": sample_id}) for sample_id in sample_ids]
            metrics: dict[str, Any] = {}
            for field in ("ys_mpa", "uts_mpa", "elongation_pct"):
                values = []
                for row in rows:
                    value = row.get("data", {}).get("properties", {}).get(field, "")
                    if value not in ("", None):
                        values.append(float(value))
                metrics[field] = {"count": len(values), "mean": statistics.fmean(values) if values else None}
            return {"method_id": "descriptive-mean-v1", "sample_count": len(sample_ids), "metrics": metrics, "result_scope": "descriptive_only"}
        if tool_name == "run_physics_calculation":
            sample_id = str(arguments["sample_id"])
            payload = execute_readonly_tool("calculate_physics_card", {"sample_id": sample_id})
            return {"sample_id": sample_id, "engine": payload, "model_scope": "empirical_estimate_not_measurement"}
        if tool_name == "generate_report_candidate":
            call_ids = list(arguments["source_call_ids"])
            return {
                "report_status": "working_candidate",
                "source_call_ids": call_ids,
                "sections": ["已确认事实", "当前判断", "待验证假设", "证据与局限", "下一步行动"],
                "human_review_required": True,
                "formal_result": False,
            }
        raise _error("GOV-AI-AUTH-001", "unregistered MCP tool")


def make_tool_request(request_id: str, idempotency_key: str, task: A2ATaskEnvelope, input_version: str, arguments: Mapping[str, Any], approval: TaskApprovalPermit | None = None) -> dict[str, Any]:
    WorkflowIdentity(request_id, task.task_id, None, task.task_revision)
    if request_id != task.request_id:
        raise _error("GOV-INTEGRITY-001", "request_id does not match the task envelope", state="invalidated")
    result = {
        "schema_version": "1.0",
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "task": task.to_dict(),
        "input_version": input_version,
        "arguments": dict(arguments),
    }
    if approval is not None:
        result["approval"] = approval.to_dict()
    return result


def run_t61_handoff_demo(*, output_root: Path | None = PROTOCOL_OUTPUTS) -> dict[str, Any]:
    """Run a fixed synthetic data -> analysis -> report-candidate handoff."""
    stamp = "2026-09-10T00:00:00+00:00"
    refs = (
        ProtocolEvidenceReference("SYNTH-T61-EVIDENCE", 1, digest_value({"fixture": "T61"}), "synthetic_demo_data"),
    )

    def synthetic_backend(tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if tool_name == "query_samples":
            return {"samples": [{"sample_id": "SYNTH-A"}, {"sample_id": "SYNTH-B"}], "count": 2}
        if tool_name == "run_descriptive_statistics":
            return {"method_id": "descriptive-mean-v1", "sample_count": 2, "metrics": {"ys_mpa": {"count": 2, "mean": 925.0}}, "result_scope": "synthetic_descriptive_only"}
        if tool_name == "run_physics_calculation":
            return {"sample_id": "SYNTH-A", "engine": {"status": "passed"}, "model_scope": "synthetic_empirical_estimate"}
        if tool_name == "generate_report_candidate":
            return {"report_status": "working_candidate", "source_call_ids": list(arguments["source_call_ids"]), "human_review_required": True, "formal_result": False}
        if tool_name == "get_verified_evidence":
            return {"sample_id": "SYNTH-A", "evidence_status": "verified", "bundle_sha256": digest_value({"sample": "SYNTH-A"})}
        raise _error("GOV-AI-AUTH-001", "unregistered synthetic tool")

    layer = GovernedResearchToolLayer(output_root=output_root, backend=synthetic_backend)
    data_task = A2ATaskEnvelope.create("planner", "data_steward", refs, status="accepted", result_summary="Synthetic task plan approved for protocol demonstration.", created_at=stamp)
    query = layer.execute("query_samples", make_tool_request(data_task.request_id, "IDEM-T61-QUERY", data_task, "synthetic-registry-v1", {}))
    analysis_task = data_task.handoff("statistics_physics", status="accepted", result_summary=f"Sample registry call completed: {query['tool_call_id']}", updated_at=stamp)
    analysis_approval = TaskApprovalPermit.create(analysis_task, "project_owner_fixture")
    stats = layer.execute("run_descriptive_statistics", make_tool_request(analysis_task.request_id, "IDEM-T61-STATS", analysis_task, "synthetic-data-v1", {"sample_ids": ["SYNTH-A", "SYNTH-B"]}, analysis_approval))
    physics = layer.execute("run_physics_calculation", make_tool_request(analysis_task.request_id, "IDEM-T61-PHYSICS", analysis_task, "physics-registry-v1.0", {"sample_id": "SYNTH-A"}, analysis_approval))
    report_task = analysis_task.handoff("materials_interpreter", status="accepted", result_summary="Deterministic statistics and physics calls completed.", updated_at=stamp)
    report_approval = TaskApprovalPermit.create(report_task, "project_owner_fixture")
    report = layer.execute("generate_report_candidate", make_tool_request(report_task.request_id, "IDEM-T61-REPORT", report_task, "report-contract-v1", {"source_call_ids": [stats["tool_call_id"], physics["tool_call_id"]]}, report_approval))
    return {
        "schema_version": "1.0",
        "demo_id": "T61-STRUCTURED-HANDOFF",
        "status": "passed" if all(item["status"] == "completed" for item in (query, stats, physics, report)) else "failed",
        "roles": ["planner", "data_steward", "statistics_physics", "materials_interpreter"],
        "task_revisions": [data_task.to_dict(), analysis_task.to_dict(), report_task.to_dict()],
        "tool_calls": [query, stats, physics, report],
        "formal_result": False,
        "human_review_required": True,
    }


def protocol_status() -> dict[str, Any]:
    validation = validate_protocol_contracts()
    return {
        **validation,
        "transport": "stdio",
        "protocol_scope": "local_structured_handoff_subset",
        "complete_mcp_compatibility": False,
        "complete_a2a_compatibility": False,
        "formal_results_allowed": False,
    }
