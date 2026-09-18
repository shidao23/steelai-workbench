"""Shared request/task/run identity for Streamlit, MCP and governed packages."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from steelai.governance.serialization import digest_value
from steelai.paths import ROOT


WORKFLOW_IDENTITY_CONTRACT_PATH = ROOT / "config" / "workflow_identity_v1.0.json"
_PATTERNS = {
    "request_id": re.compile(r"^request_[a-z0-9][a-z0-9_-]{5,63}$"),
    "task_id": re.compile(r"^task_[a-z0-9][a-z0-9_-]{5,63}$"),
    "run_id": re.compile(r"^run_[a-z0-9][a-z0-9_-]{5,63}$"),
}


def _validate_id(value: Any, field_name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _PATTERNS[field_name].fullmatch(value):
        raise ValueError(f"{field_name} is not a canonical Shidao workflow identifier")
    return value


def _derived_id(prefix: str, seed: Any) -> str:
    return prefix + digest_value({"kind": prefix[:-1], "seed": seed})[:24]


def validate_workflow_identity_contract(
    path: str | Path = WORKFLOW_IDENTITY_CONTRACT_PATH,
) -> dict[str, Any]:
    problems: list[str] = []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "failed", "problems": [str(exc)]}
    if payload.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    if payload.get("contract_id") != "Shidao-Workflow-Identity-v1.0":
        problems.append("contract_id mismatch")
    if payload.get("canonical_fields") != ["request_id", "task_id", "run_id", "task_revision"]:
        problems.append("canonical fields mismatch")
    if payload.get("platform_field_aliases") != {
        "request_id": "requestId",
        "task_id": "taskId",
        "run_id": "runId",
        "task_revision": "taskRevision",
    }:
        problems.append("platform aliases mismatch")
    if payload.get("prefixes") != {
        "request_id": "request_",
        "task_id": "task_",
        "run_id": "run_",
    }:
        problems.append("identifier prefixes mismatch")
    return {
        "schema_version": "1.0",
        "contract_id": payload.get("contract_id", ""),
        "status": "passed" if not problems else "failed",
        "problems": problems,
    }


@dataclass(frozen=True)
class WorkflowIdentity:
    request_id: str
    task_id: str
    run_id: str | None
    task_revision: int = 1

    def __post_init__(self) -> None:
        _validate_id(self.request_id, "request_id")
        _validate_id(self.task_id, "task_id")
        _validate_id(self.run_id, "run_id", nullable=True)
        if (
            not isinstance(self.task_revision, int)
            or isinstance(self.task_revision, bool)
            or self.task_revision < 1
        ):
            raise ValueError("task_revision must be a positive integer")

    @classmethod
    def create(
        cls,
        *,
        seed: Any | None = None,
        request_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        task_revision: int = 1,
    ) -> "WorkflowIdentity":
        identity_seed = seed if seed is not None else {"nonce": uuid.uuid4().hex}
        return cls(
            request_id=request_id or _derived_id("request_", identity_seed),
            task_id=task_id or _derived_id("task_", {"request": identity_seed}),
            run_id=run_id,
            task_revision=task_revision,
        )

    def start_run(self, *, seed: Any | None = None, run_id: str | None = None) -> "WorkflowIdentity":
        if self.run_id is not None:
            if run_id is not None and run_id != self.run_id:
                raise ValueError("workflow identity is already bound to a different run_id")
            return self
        run_seed = seed if seed is not None else {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "nonce": uuid.uuid4().hex,
        }
        return replace(self, run_id=run_id or _derived_id("run_", run_seed))

    def revise_task(self) -> "WorkflowIdentity":
        return replace(self, run_id=None, task_revision=self.task_revision + 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "request_id": self.request_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "task_revision": self.task_revision,
        }

    def to_platform_fields(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "taskId": self.task_id,
            "runId": self.run_id,
            "taskRevision": self.task_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, require_run: bool = False) -> "WorkflowIdentity":
        expected = {"schema_version", "request_id", "task_id", "run_id", "task_revision"}
        if set(value) != expected or value.get("schema_version") != "1.0":
            raise ValueError("workflow identity fields mismatch")
        identity = cls(
            request_id=value["request_id"],
            task_id=value["task_id"],
            run_id=value["run_id"],
            task_revision=value["task_revision"],
        )
        if require_run and identity.run_id is None:
            raise ValueError("run_id is required after execution starts")
        return identity


def coerce_workflow_identity(
    value: WorkflowIdentity | Mapping[str, Any] | None,
    *,
    seed: Any,
    require_run: bool,
) -> WorkflowIdentity:
    if isinstance(value, WorkflowIdentity):
        identity = value
    elif isinstance(value, Mapping):
        identity = WorkflowIdentity.from_dict(value)
    else:
        identity = WorkflowIdentity.create()
    return identity.start_run(seed={"identity": identity.to_dict(), "operation": seed}) if require_run else identity
