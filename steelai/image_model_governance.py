"""T54 governance for EBSD, SEM and isolated image/model tasks.

The adapter records source and output digests but deliberately never copies raw
images, EBSD maps, weights or other heavyweight artifacts into Workbench.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping

from steelai.governance import (
    ApprovalDecision,
    ApprovalSnapshot,
    EvidenceClass,
    GovernanceError,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    authorize_execution,
    build_manifest,
    create_staging_directory,
    digest_value,
    load_verified_manifest,
    publish_append_only,
    seal_package,
    sha256_file,
    transition_state,
    utc_now,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS


IMAGE_MODEL_TASK_OUTPUTS = OUTPUTS / "image_model_tasks"
IMAGE_MODEL_RUN_OUTPUTS = OUTPUTS / "image_model_runs"
IMAGE_MODEL_REVIEW_OUTPUTS = OUTPUTS / "image_model_reviews"
SUPPORTED_MODALITIES = {"EBSD", "SEM"}
RUN_OUTCOMES = {"completed", "partial", "failed", "canceled"}


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", f"{name} is required")
    if len(text) > 160 or any(char in text for char in ("/", "\\", "\r", "\n", "\t")):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", f"{name} must be a stable identifier")
    return text


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", f"JSON artifact must be an object: {path.name}")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _source_records(sources: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[SourceReference]]:
    registry: list[dict[str, Any]] = []
    references: list[SourceReference] = []
    seen: set[str] = set()
    for raw in sources:
        source_id = _required_text(raw.get("source_id"), "source_id")
        if source_id in seen:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "source_id must be unique within one task")
        seen.add(source_id)
        modality = _required_text(raw.get("modality"), "modality").upper()
        if modality not in SUPPORTED_MODALITIES:
            raise GovernanceError("GOV-SCHEMA-001", "blocked", "modality must be EBSD or SEM")
        source_path = Path(str(raw.get("source_path") or "")).expanduser()
        if not source_path.is_file() or source_path.is_symlink():
            raise GovernanceError("GOV-SOURCE-001", "blocked", f"registered source is unavailable: {source_id}")
        if _inside(source_path, OUTPUTS):
            raise GovernanceError("GOV-SOURCE-001", "blocked", "raw source cannot be a Workbench output")
        status = str(raw.get("source_status") or "read_only_registered").strip()
        if status not in {"read_only_registered", "read_only_verified"}:
            raise GovernanceError("GOV-SOURCE-001", "blocked", "image source must be explicitly read-only")
        digest = sha256_file(source_path)
        record = {
            "source_id": source_id,
            "source_revision": int(raw.get("source_revision", 1)),
            "source_digest": digest,
            "source_size_bytes": source_path.stat().st_size,
            "source_status": status,
            "modality": modality,
            "sample_id": _required_text(raw.get("sample_id"), "sample_id"),
            "specimen_id": _required_text(raw.get("specimen_id"), "specimen_id"),
            "image_field_id": _required_text(raw.get("image_field_id"), "image_field_id"),
            "private_locator_digest": digest_value(str(source_path.resolve())),
            "raw_file_copied": False,
        }
        registry.append(record)
        references.append(SourceReference(
            source_id=source_id,
            source_revision=record["source_revision"],
            source_digest=digest,
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA.value,
            source_status=status,
        ))
    if not registry:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "at least one EBSD or SEM source is required")
    return registry, references


def _references_from_registry(registry: Iterable[Mapping[str, Any]]) -> list[SourceReference]:
    return [
        SourceReference(
            source_id=str(item["source_id"]),
            source_revision=int(item["source_revision"]),
            source_digest=str(item["source_digest"]),
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA.value,
            source_status=str(item["source_status"]),
        )
        for item in registry
    ]


def preview_image_model_task(
    task_key: str,
    *,
    modality: str,
    task_type: str,
    sources: Iterable[Mapping[str, Any]],
    software_id: str,
    software_version: str,
    model_id: str,
    model_version: str,
    parameters: Mapping[str, Any],
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and freeze one proposed isolated image/model task."""
    task_key = _required_text(task_key, "task_key")
    modality = _required_text(modality, "modality").upper()
    if modality not in SUPPORTED_MODALITIES:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "modality must be EBSD or SEM")
    source_registry, _ = _source_records(sources)
    environment_record = {
        "environment_id": _required_text(environment.get("environment_id"), "environment_id"),
        "runtime": _required_text(environment.get("runtime"), "runtime"),
        "runtime_version": _required_text(environment.get("runtime_version"), "runtime_version"),
        "isolated_from_workbench": environment.get("isolated_from_workbench") is True,
        "hardware_profile": str(environment.get("hardware_profile") or "not_recorded"),
    }
    if not environment_record["isolated_from_workbench"]:
        raise GovernanceError("GOV-RUNTIME-001", "blocked", "heavy model runtime must remain isolated from Workbench")
    if not isinstance(parameters, Mapping) or not parameters:
        raise GovernanceError("GOV-PARAM-001", "needs_human", "a versioned parameter set is required")
    payload = {
        "schema_version": "1.0",
        "task_key": task_key,
        "task_type": _required_text(task_type, "task_type"),
        "modality": modality,
        "sources": source_registry,
        "software": {
            "software_id": _required_text(software_id, "software_id"),
            "software_version": _required_text(software_version, "software_version"),
        },
        "model": {
            "model_id": _required_text(model_id, "model_id"),
            "model_version": _required_text(model_version, "model_version"),
        },
        "parameters": json.loads(json.dumps(dict(parameters), ensure_ascii=False, sort_keys=True)),
        "environment": environment_record,
        "boundaries": {
            "raw_sources_read_only": True,
            "raw_sources_copied": False,
            "heavy_runtime_isolated": True,
            "result_requires_human_review": True,
            "model_output_is_measurement": False,
        },
    }
    content_digest = digest_value(payload)
    return {
        **payload,
        "task_id": "IMGTASK-" + content_digest[:20].upper(),
        "content_digest": content_digest,
        "governance_state": "needs_human",
    }


def register_image_model_task(
    task_key: str,
    *,
    modality: str,
    task_type: str,
    sources: Iterable[Mapping[str, Any]],
    software_id: str,
    software_version: str,
    model_id: str,
    model_version: str,
    parameters: Mapping[str, Any],
    environment: Mapping[str, Any],
    reviewer_id: str,
    rationale: str,
    decided_at: str | None = None,
    output_root: Path = IMAGE_MODEL_TASK_OUTPUTS,
) -> dict[str, Any]:
    source_values = list(sources)
    preview = preview_image_model_task(
        task_key,
        modality=modality,
        task_type=task_type,
        sources=source_values,
        software_id=software_id,
        software_version=software_version,
        model_id=model_id,
        model_version=model_version,
        parameters=parameters,
        environment=environment,
    )
    reviewer = reviewer_id.strip()
    if not reviewer or not rationale.strip():
        raise GovernanceError("GOV-APPROVAL-001", "needs_human", "parameter reviewer and rationale are required")
    destination = output_root.resolve() / preview["task_id"]
    if destination.exists():
        verification = verify_package(destination)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing image task package is invalidated")
        existing = load_verified_manifest(destination)
        if existing.identity.content_digest != preview["content_digest"]:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "task identity conflicts with existing content")
        return {
            "status": "approved",
            "task_id": preview["task_id"],
            "package": str(destination),
            "manifest_sha256": verification.manifest_digest,
            "reused": True,
            "preview": preview,
        }

    timestamp = decided_at or utc_now()
    identity = ResearchObjectIdentity(
        object_type="image_model_task",
        object_id=preview["task_id"],
        revision=1,
        content_digest=preview["content_digest"],
        created_at=timestamp,
        created_by="steelai-image-model-governance-adapter",
    )
    approval = ApprovalSnapshot.create(
        identity,
        ApprovalDecision.APPROVED,
        reviewer,
        "Image/model sources, parameter set and isolated runtime",
        rationale.strip(),
        decided_at=timestamp,
    )
    approved = transition_state(identity, "needs_human", "approved", actor="human", approval=approval, occurred_at=timestamp)
    source_references = _references_from_registry(preview["sources"])
    stage = create_staging_directory(output_root, preview["task_id"])
    try:
        write_json_atomic(stage / "image_task_manifest.json", preview)
        write_json_atomic(stage / "governance_record.json", {
            "schema_version": "1.0",
            "identity": identity.to_dict(),
            "approval": approval.to_dict(),
            "transitions": [approved.to_dict()],
            "state": "approved",
        })
        manifest = build_manifest(
            stage,
            publication_id=preview["task_id"],
            identity=identity,
            state="approved",
            result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=source_references,
            approvals=(approval,),
            generated_by="steelai-image-model-governance-adapter",
            generated_at=timestamp,
            metadata={"modality": preview["modality"], "task_type": preview["task_type"], "raw_files_copied": False},
        )
        seal_package(stage, manifest)
        publication = publish_append_only(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "status": "approved",
        "task_id": preview["task_id"],
        "package": publication.destination,
        "manifest_sha256": publication.manifest_digest,
        "reused": publication.reused,
        "preview": preview,
    }


def _output_records(outputs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in outputs:
        output_id = _required_text(raw.get("output_id"), "output_id")
        if output_id in seen:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "output_id must be unique within one run")
        seen.add(output_id)
        path = Path(str(raw.get("path") or "")).expanduser()
        if not path.is_file() or path.is_symlink():
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"declared output is unavailable: {output_id}")
        records.append({
            "output_id": output_id,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "media_type": str(raw.get("media_type") or "application/octet-stream"),
            "private_locator_digest": digest_value(str(path.resolve())),
            "artifact_copied": False,
        })
    return records


def record_image_model_run(
    task_package: str | Path,
    *,
    outcome: str,
    outputs: Iterable[Mapping[str, Any]] = (),
    attempt: int = 1,
    rerun_of: str | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    output_root: Path = IMAGE_MODEL_RUN_OUTPUTS,
) -> dict[str, Any]:
    task_root = Path(task_package).resolve()
    task_verification = verify_package(task_root)
    if task_verification.status != "passed":
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "image/model task package is invalidated")
    task_manifest = load_verified_manifest(task_root)
    if task_manifest.identity.object_type != "image_model_task" or task_manifest.state != "approved":
        raise GovernanceError("GOV-STATE-001", "blocked", "run requires an approved image/model task")
    task = _read_json(task_root / "image_task_manifest.json")
    outcome = str(outcome).strip().lower()
    if outcome not in RUN_OUTCOMES:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "run outcome is not supported")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "attempt must be a positive integer")
    output_records = _output_records(outputs)
    if outcome in {"completed", "partial"} and not output_records:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "completed or partial run requires registered outputs")
    if outcome in {"failed", "canceled"} and output_records:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "failed or canceled run must not claim result outputs")
    if outcome == "failed" and not error_code:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "failed run requires an error code")

    started = started_at or utc_now()
    finished = finished_at or utc_now()
    record = {
        "schema_version": "1.0",
        "task_id": task_manifest.publication_id,
        "task_manifest_sha256": task_verification.manifest_digest,
        "task_content_digest": task_manifest.identity.content_digest,
        "modality": task["modality"],
        "task_type": task["task_type"],
        "software": task["software"],
        "model": task["model"],
        "parameters": task["parameters"],
        "environment": task["environment"],
        "attempt": attempt,
        "rerun_of": rerun_of,
        "technical_outcome": outcome,
        "started_at": started,
        "finished_at": finished,
        "error": {"code": error_code, "summary": error_summary},
        "outputs": output_records,
        "boundaries": {
            "outputs_copied": False,
            "human_review_required": outcome in {"completed", "partial"},
            "formal_evidence_allowed": False,
            "model_output_is_measurement": False,
        },
    }
    content_digest = digest_value(record)
    run_id = "IMGRUN-" + content_digest[:20].upper()
    state = "needs_human" if outcome in {"completed", "partial"} else "blocked"
    destination = output_root.resolve() / run_id
    if destination.exists():
        verification = verify_package(destination)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing image/model run is invalidated")
        existing = load_verified_manifest(destination)
        if existing.identity.content_digest != content_digest:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "run identity conflicts with existing content")
        return {
            "status": state,
            "run_id": run_id,
            "technical_outcome": outcome,
            "package": str(destination),
            "manifest_sha256": verification.manifest_digest,
            "reused": True,
        }

    identity = ResearchObjectIdentity(
        object_type="image_model_run",
        object_id=run_id,
        revision=1,
        content_digest=content_digest,
        created_at=finished,
        created_by="registered-isolated-runtime",
    )
    source = SourceReference(
        source_id=task_manifest.publication_id,
        source_revision=1,
        source_digest=task_verification.manifest_digest or task_manifest.identity.content_digest,
        evidence_class=EvidenceClass.MODEL_OUTPUT.value,
        source_status="approved_task_configuration",
    )
    stage = create_staging_directory(output_root, run_id)
    try:
        write_json_atomic(stage / "model_run_record.json", {**record, "run_id": run_id, "governance_state": state})
        write_json_atomic(stage / "result_traceability.json", {
            "schema_version": "1.0",
            "run_id": run_id,
            "task_id": task_manifest.publication_id,
            "source_ids": [item["source_id"] for item in task["sources"]],
            "output_ids": [item["output_id"] for item in output_records],
            "parameter_digest": digest_value(task["parameters"]),
            "environment_digest": digest_value(task["environment"]),
            "review_state": state,
        })
        manifest = build_manifest(
            stage,
            publication_id=run_id,
            identity=identity,
            state=state,
            result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=(source,),
            generated_by="steelai-image-model-governance-adapter",
            generated_at=finished,
            metadata={"technical_outcome": outcome, "attempt": attempt, "rerun_of": rerun_of, "requires_human_review": state == "needs_human"},
        )
        seal_package(stage, manifest)
        publication = publish_append_only(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "status": state,
        "run_id": run_id,
        "technical_outcome": outcome,
        "package": publication.destination,
        "manifest_sha256": publication.manifest_digest,
        "reused": publication.reused,
    }


def review_image_model_run(
    run_package: str | Path,
    *,
    reviewer_id: str,
    decision: str,
    rationale: str,
    scope: str,
    accepted_output_ids: Iterable[str] | None = None,
    decided_at: str | None = None,
    output_root: Path = IMAGE_MODEL_REVIEW_OUTPUTS,
) -> dict[str, Any]:
    run_root = Path(run_package).resolve()
    verification = verify_package(run_root)
    if verification.status != "passed":
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "image/model run package is invalidated")
    run_manifest = load_verified_manifest(run_root)
    run = _read_json(run_root / "model_run_record.json")
    if run_manifest.state != "needs_human" or run["technical_outcome"] not in {"completed", "partial"}:
        raise GovernanceError("GOV-STATE-001", "blocked", "only completed or partial needs_human runs can be reviewed")
    decision = str(decision).strip().lower()
    if decision not in {"approved", "warning_accepted", "rejected"}:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "review decision is not supported")
    if run["technical_outcome"] == "partial" and decision == "approved":
        raise GovernanceError("GOV-WARNING-001", "needs_human", "partial results require warning_accepted or rejected")
    if run["technical_outcome"] == "completed" and decision == "warning_accepted":
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "warning_accepted is reserved for partial results")
    reviewer = reviewer_id.strip()
    if not reviewer or not rationale.strip() or not scope.strip():
        raise GovernanceError("GOV-APPROVAL-001", "needs_human", "reviewer, rationale and scope are required")
    available_ids = {item["output_id"] for item in run["outputs"]}
    accepted_ids = sorted(set(accepted_output_ids or available_ids))
    if not set(accepted_ids).issubset(available_ids):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "review references an unknown output_id")
    if decision != "rejected" and not accepted_ids:
        raise GovernanceError("GOV-EVIDENCE-001", "needs_human", "an accepted model result needs at least one output")

    timestamp = decided_at or utc_now()
    review_payload = {
        "schema_version": "1.0",
        "run_id": run_manifest.publication_id,
        "run_manifest_sha256": verification.manifest_digest,
        "technical_outcome": run["technical_outcome"],
        "decision": decision,
        "reviewer_id": reviewer,
        "decided_at": timestamp,
        "scope": scope.strip(),
        "rationale": rationale.strip(),
        "accepted_output_ids": accepted_ids if decision != "rejected" else [],
        "evidence_class": EvidenceClass.MODEL_OUTPUT.value,
        "is_experimental_measurement": False,
    }
    content_digest = digest_value(review_payload)
    review_id = "IMGREVIEW-" + content_digest[:20].upper()
    identity = ResearchObjectIdentity(
        object_type="image_model_review",
        object_id=review_id,
        revision=1,
        content_digest=content_digest,
        created_at=timestamp,
        created_by="human-image-model-review",
    )
    if decision == "rejected":
        approval = ApprovalSnapshot.create(
            identity, ApprovalDecision.REJECTED, reviewer, scope.strip(), rationale.strip(), decided_at=timestamp
        )
        transitions = [transition_state(identity, "needs_human", "rejected", actor="human", approval=approval, occurred_at=timestamp)]
        approvals = [approval]
        state = "rejected"
        result_level = ResultLevel.WORKING_CANDIDATE
        evidence_eligible = False
    else:
        approval = ApprovalSnapshot.create(
            identity, ApprovalDecision.APPROVED, reviewer, scope.strip(), rationale.strip(), decided_at=timestamp
        )
        approved = transition_state(identity, "needs_human", "approved", actor="human", approval=approval, occurred_at=timestamp)
        running = authorize_execution(identity, "approved", approval, occurred_at=timestamp)
        approvals = [approval]
        if decision == "warning_accepted":
            warning = transition_state(identity, "running", "warning", actor="system", occurred_at=timestamp)
            warning_approval = ApprovalSnapshot.create(
                identity,
                ApprovalDecision.WARNING_ACCEPTED,
                reviewer,
                scope.strip(),
                rationale.strip() + " | Partial result limitation explicitly accepted.",
                decided_at=timestamp,
            )
            complete = transition_state(identity, "warning", "complete", actor="human", approval=warning_approval, occurred_at=timestamp)
            approvals.append(warning_approval)
            transitions = [approved, running, warning, complete]
        else:
            passed = transition_state(identity, "running", "passed", actor="system", occurred_at=timestamp)
            complete = transition_state(identity, "passed", "complete", actor="human", occurred_at=timestamp)
            transitions = [approved, running, passed, complete]
        state = "complete"
        result_level = ResultLevel.MODEL_RESULT
        evidence_eligible = True

    destination = output_root.resolve() / review_id
    if destination.exists():
        existing_verification = verify_package(destination)
        if existing_verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing image/model review is invalidated")
        existing = load_verified_manifest(destination)
        if existing.identity.content_digest != content_digest:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "review identity conflicts with existing content")
        return {
            "status": state,
            "review_id": review_id,
            "package": str(destination),
            "manifest_sha256": existing_verification.manifest_digest,
            "evidence_eligible": evidence_eligible,
            "reused": True,
        }

    source = SourceReference(
        source_id=run_manifest.publication_id,
        source_revision=1,
        source_digest=verification.manifest_digest or run_manifest.identity.content_digest,
        evidence_class=EvidenceClass.MODEL_OUTPUT.value,
        source_status="needs_human_model_result",
    )
    stage = create_staging_directory(output_root, review_id)
    try:
        write_json_atomic(stage / "human_review.json", review_payload)
        write_json_atomic(stage / "result_index_record.json", {
            "schema_version": "1.0",
            "review_id": review_id,
            "run_id": run_manifest.publication_id,
            "task_id": run["task_id"],
            "modality": run["modality"],
            "model": run["model"],
            "software": run["software"],
            "technical_outcome": run["technical_outcome"],
            "governance_state": state,
            "result_level": result_level.value,
            "evidence_eligible": evidence_eligible,
            "accepted_output_ids": review_payload["accepted_output_ids"],
            "source_ids": [
                item["source_id"]
                for item in _read_json(task_package_from_run(run_root) / "image_task_manifest.json").get("sources", [])
            ],
            "statement_boundary": "reviewed model result; not an experimental measurement or automatic scientific conclusion",
        })
        write_json_atomic(stage / "governance_record.json", {
            "schema_version": "1.0",
            "identity": identity.to_dict(),
            "approvals": [item.to_dict() for item in approvals],
            "transitions": [item.to_dict() for item in transitions],
            "state": state,
        })
        manifest = build_manifest(
            stage,
            publication_id=review_id,
            identity=identity,
            state=state,
            result_level=result_level,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=(source,),
            approvals=approvals,
            generated_by="steelai-image-model-governance-adapter",
            generated_at=timestamp,
            metadata={"technical_outcome": run["technical_outcome"], "review_decision": decision, "evidence_eligible": evidence_eligible},
        )
        seal_package(stage, manifest)
        publication = publish_append_only(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "status": state,
        "review_id": review_id,
        "package": publication.destination,
        "manifest_sha256": publication.manifest_digest,
        "evidence_eligible": evidence_eligible,
        "reused": publication.reused,
    }


def task_package_from_run(run_package: str | Path) -> Path:
    run_root = Path(run_package).resolve()
    run = _read_json(run_root / "model_run_record.json")
    task_root = IMAGE_MODEL_TASK_OUTPUTS.resolve() / str(run["task_id"])
    if not task_root.is_dir():
        # Tests and portable stores can place sibling roots under one parent.
        candidate = run_root.parent.parent / "tasks" / str(run["task_id"])
        if candidate.is_dir():
            task_root = candidate
    verification = verify_package(task_root)
    if verification.status != "passed":
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "source task for image/model run is invalidated")
    if verification.manifest_digest != run.get("task_manifest_sha256"):
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "run no longer binds the registered task manifest")
    return task_root


def inspect_image_model_package(package: str | Path) -> dict[str, Any]:
    root = Path(package).resolve()
    verification = verify_package(root)
    result = verification.to_dict()
    if verification.status == "passed":
        manifest = load_verified_manifest(root)
        result.update({
            "state": manifest.state,
            "result_level": manifest.result_level,
            "evidence_class": manifest.evidence_class,
            "publication_id": manifest.publication_id,
            "metadata": dict(manifest.metadata),
        })
    return result


def list_image_model_result_index(output_root: Path = IMAGE_MODEL_REVIEW_OUTPUTS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not output_root.is_dir():
        return rows
    for package in sorted((path for path in output_root.iterdir() if path.is_dir()), reverse=True):
        verification = verify_package(package)
        if verification.status != "passed" or not (package / "result_index_record.json").is_file():
            continue
        row = _read_json(package / "result_index_record.json")
        row["package"] = str(package)
        row["integrity_status"] = "passed"
        rows.append(row)
    return rows
