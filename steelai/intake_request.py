"""Metadata-only intake request registration for Streamlit selections.

This module deliberately knows nothing about parsing, SteelData execution, or
research-data commits.  It turns an explicit file/folder selection into one
auditable request/task identity and keeps that identity stable in the current
Streamlit session.
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import re
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from steelai.event_log import record_event
from steelai.paths import ROOT
from steelai.workflow_identity import WorkflowIdentity


_ROUTE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_TARGET = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_FIELDS = {
    "file_name", "file_names", "path", "absolute_path", "folder_reference",
    "raw_content", "content_bytes",
}
_SESSION_PREFIX = "_steelai_intake_request:"
INTAKE_REQUEST_CONTRACT_PATH = ROOT / "config" / "intake_request_event_v1.0.json"


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_intake_request_contract(
    path: str | Path = INTAKE_REQUEST_CONTRACT_PATH,
) -> dict[str, Any]:
    problems: list[str] = []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "failed", "problems": [str(exc)]}
    if payload.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    if payload.get("contract_id") != "Shidao-Intake-Request-Event-v1.0":
        problems.append("contract_id mismatch")
    if payload.get("event_type") != "intake_request" or payload.get("state") != "selected":
        problems.append("event type or initial state mismatch")
    if payload.get("identity_fields") != ["request_id", "task_id", "run_id", "task_revision"]:
        problems.append("identity fields mismatch")
    if payload.get("selection_fields") != [
        "kind", "item_count", "total_size_bytes", "extensions",
        "selection_sha256", "reference_scope",
    ]:
        problems.append("selection fields mismatch")
    invariants = payload.get("invariants", {})
    expected_flags = {
        "execution_started": False,
        "research_data_written": False,
        "raw_content_persisted": False,
        "absolute_path_persisted": False,
        "folder_scanned_during_registration": False,
    }
    if invariants.get("run_id_before_execution", "missing") is not None:
        problems.append("run_id_before_execution must be null")
    if any(invariants.get(key) is not value for key, value in expected_flags.items()):
        problems.append("pre-execution invariants mismatch")
    return {
        "schema_version": "1.0",
        "contract_id": payload.get("contract_id", ""),
        "status": "passed" if not problems else "failed",
        "problems": problems,
    }


@dataclass(frozen=True)
class IntakeSelection:
    """Sanitized selection metadata; source names, paths and bytes are absent."""

    kind: str
    item_count: int | None
    total_size_bytes: int | None
    extensions: tuple[str, ...]
    selection_sha256: str
    reference_scope: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "item_count": self.item_count,
            "total_size_bytes": self.total_size_bytes,
            "extensions": list(self.extensions),
            "selection_sha256": self.selection_sha256,
            "reference_scope": self.reference_scope,
        }


@dataclass(frozen=True)
class IntakeRequestRegistration:
    identity: WorkflowIdentity
    selection: IntakeSelection
    event: Mapping[str, Any]
    created: bool


def validate_intake_request_evidence(evidence: Mapping[str, Any]) -> None:
    """Fail closed if an intake event grows beyond its metadata-only contract."""
    expected = {
        "schema_version", "request_id", "task_id", "run_id", "task_revision",
        "route", "state", "selection", "execution_started", "research_data_written",
        "raw_content_persisted", "absolute_path_persisted",
    }
    if "target_table" in evidence:
        expected.add("target_table")
    if set(evidence) != expected:
        raise ValueError("intake request evidence fields mismatch")
    WorkflowIdentity.from_dict({
        key: evidence[key]
        for key in ("schema_version", "request_id", "task_id", "run_id", "task_revision")
    })
    if evidence["run_id"] is not None or evidence["state"] != "selected":
        raise ValueError("intake request must remain pre-execution")
    if any(evidence[key] is not False for key in (
        "execution_started", "research_data_written", "raw_content_persisted",
        "absolute_path_persisted",
    )):
        raise ValueError("intake request pre-execution flags mismatch")
    if not isinstance(evidence["route"], str) or not _ROUTE.fullmatch(evidence["route"]):
        raise ValueError("invalid intake route")
    if "target_table" in evidence and (
        not isinstance(evidence["target_table"], str)
        or not _TARGET.fullmatch(evidence["target_table"])
    ):
        raise ValueError("invalid target table")
    selection = evidence["selection"]
    if not isinstance(selection, Mapping) or set(selection) != {
        "kind", "item_count", "total_size_bytes", "extensions",
        "selection_sha256", "reference_scope",
    }:
        raise ValueError("intake selection fields mismatch")
    if not isinstance(selection["selection_sha256"], str) or not _SHA256.fullmatch(
        selection["selection_sha256"]
    ):
        raise ValueError("selection_sha256 is invalid")
    if selection["kind"] == "uploaded_files":
        if (
            not isinstance(selection["item_count"], int)
            or isinstance(selection["item_count"], bool)
            or selection["item_count"] < 1
            or not isinstance(selection["total_size_bytes"], int)
            or isinstance(selection["total_size_bytes"], bool)
            or selection["total_size_bytes"] < 0
            or selection["reference_scope"] != "aggregate_metadata_only"
        ):
            raise ValueError("uploaded selection metadata is invalid")
    elif selection["kind"] == "folder_reference":
        if (
            selection["item_count"] is not None
            or selection["total_size_bytes"] is not None
            or selection["extensions"] != []
            or selection["reference_scope"] != "reference_only_not_scanned"
        ):
            raise ValueError("folder selection metadata is invalid")
    else:
        raise ValueError("unsupported intake selection kind")
    if not isinstance(selection["extensions"], list) or any(
        not isinstance(extension, str) or not _SAFE_EXTENSION.fullmatch(extension)
        for extension in selection["extensions"]
    ):
        raise ValueError("selection extensions are not sanitized")
    if _FORBIDDEN_FIELDS.intersection(evidence) or _FORBIDDEN_FIELDS.intersection(selection):
        raise ValueError("intake request contains forbidden persisted fields")


def uploaded_file_selection(uploads: Iterable[Any]) -> IntakeSelection:
    """Build aggregate metadata without retaining file names or source bytes."""
    descriptors: list[dict[str, Any]] = []
    total_size = 0
    extensions: set[str] = set()
    for upload in uploads:
        payload = upload.getvalue()
        if not isinstance(payload, bytes):
            raise ValueError("uploaded file content must be bytes")
        candidate_extension = Path(str(getattr(upload, "name", ""))).suffix.lower()
        extension = candidate_extension if _SAFE_EXTENSION.fullmatch(candidate_extension) else ""
        if extension:
            extensions.add(extension)
        size = len(payload)
        total_size += size
        descriptors.append({
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "extension": extension,
            "size_bytes": size,
        })
    if not descriptors:
        raise ValueError("at least one uploaded file is required")
    descriptors.sort(key=lambda item: (item["content_sha256"], item["extension"], item["size_bytes"]))
    return IntakeSelection(
        kind="uploaded_files",
        item_count=len(descriptors),
        total_size_bytes=total_size,
        extensions=tuple(sorted(extensions)),
        selection_sha256=_digest({"kind": "uploaded_files", "files": descriptors}),
        reference_scope="aggregate_metadata_only",
    )


def folder_reference_selection(folder_reference: str) -> IntakeSelection:
    """Register a user-supplied folder reference without resolving or scanning it."""
    supplied = str(folder_reference).strip().strip('"')
    if not supplied:
        raise ValueError("folder reference is required")
    normalized = ntpath.normcase(ntpath.normpath(supplied))
    return IntakeSelection(
        kind="folder_reference",
        item_count=None,
        total_size_bytes=None,
        extensions=(),
        selection_sha256=_digest({"kind": "folder_reference", "reference": normalized}),
        reference_scope="reference_only_not_scanned",
    )


def register_intake_request(
    session_state: MutableMapping[str, Any],
    *,
    route: str,
    selection: IntakeSelection,
    target_table: str | None = None,
    event_recorder: Callable[..., Mapping[str, Any]] | None = None,
) -> IntakeRequestRegistration:
    """Create one event per changed selection and retain its identity in-session."""
    if not _ROUTE.fullmatch(route):
        raise ValueError("invalid intake route")
    if target_table is not None and not _TARGET.fullmatch(target_table):
        raise ValueError("invalid target table")

    slot = _SESSION_PREFIX + route + ":" + (target_table or "_")
    current = session_state.get(slot)
    if isinstance(current, Mapping) and current.get("selection_sha256") == selection.selection_sha256:
        try:
            identity = WorkflowIdentity.from_dict(current["workflow_identity"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            saved_event = current.get("event")
            return IntakeRequestRegistration(
                identity=identity,
                selection=selection,
                event=dict(saved_event) if isinstance(saved_event, Mapping) else {},
                created=False,
            )

    identity = WorkflowIdentity.create()
    evidence: dict[str, Any] = {
        "schema_version": "1.0",
        **identity.to_dict(),
        "route": route,
        "state": "selected",
        "selection": selection.to_dict(),
        "execution_started": False,
        "research_data_written": False,
        "raw_content_persisted": False,
        "absolute_path_persisted": False,
    }
    if target_table is not None:
        evidence["target_table"] = target_table
    validate_intake_request_evidence(evidence)
    recorder = event_recorder or record_event
    recorded = recorder(
        "intake_request",
        "Streamlit 数据选择已登记",
        "已登记选择元数据；尚未执行导入或写入研究数据。",
        evidence=evidence,
        tags=["streamlit", "intake-request", "metadata-only", "not-executed"],
    )
    event = dict(recorded) if isinstance(recorded, Mapping) else {
        "event_type": "intake_request",
        "evidence": evidence,
    }
    session_state[slot] = {
        "selection_sha256": selection.selection_sha256,
        "workflow_identity": identity.to_dict(),
        "event": event,
    }
    return IntakeRequestRegistration(
        identity=identity,
        selection=selection,
        event=event,
        created=True,
    )
