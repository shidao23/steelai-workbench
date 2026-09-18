"""T52 governance adapter shared by manual CSV and SteelData intake routes."""
from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from steelai.data_intake import _safe_report, commit_intake, commit_intake_batch
from steelai.governance import (
    ApprovalDecision,
    ApprovalSnapshot,
    EvidenceClass,
    GovernanceError,
    GovernanceState,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    TransitionRecord,
    authorize_execution,
    build_manifest,
    create_staging_directory,
    evaluate_formal_write,
    publish_append_only,
    seal_package,
    transition_state,
    utc_now,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS, ROOT
from steelai.research_data_contract import CONTRACT_PATH
from steelai.data_intake import ID_POLICY_PATH
from steelai.workflow_identity import WorkflowIdentity, coerce_workflow_identity


GOVERNED_INTAKE_OUTPUTS = OUTPUTS / "governed_data_intake"


@dataclass(frozen=True)
class IntakeGovernanceRecord:
    intake_id: str
    route: str
    state: str
    identity: ResearchObjectIdentity
    workflow_identity: WorkflowIdentity
    source: SourceReference
    approvals: tuple[ApprovalSnapshot, ...]
    transitions: tuple[TransitionRecord, ...]
    validation_status: str
    issue_codes: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "intake_id": self.intake_id,
            "route": self.route,
            "state": self.state,
            "identity": self.identity.to_dict(),
            "workflow_identity": self.workflow_identity.to_dict(),
            "source": self.source.to_dict(),
            "approvals": [item.to_dict() for item in self.approvals],
            "transitions": [item.to_dict() for item in self.transitions],
            "validation_status": self.validation_status,
            "issue_codes": list(self.issue_codes),
            "created_at": self.created_at,
        }


def intake_issue_codes(report: Mapping[str, Any]) -> tuple[str, ...]:
    messages = [str(item) for item in (*report.get("errors", []), *report.get("warnings", []))]
    codes: list[str] = []
    for message in messages:
        if "单位" in message or "unit" in message.casefold():
            codes.append("GOV-UNIT-001")
        elif any(token in message for token in ("样品", "试样", "specimen", "对应", "映射")):
            codes.append("GOV-IDENTITY-001")
        elif any(token in message for token in ("主键", "重复", "已接入", "覆盖")):
            codes.append("GOV-DUPLICATE-001")
        else:
            codes.append("GOV-SCHEMA-001" if report.get("errors") else "GOV-WARNING-001")
    return tuple(dict.fromkeys(codes))


def preview_intake_governance(report: Mapping[str, Any]) -> dict[str, Any]:
    codes = intake_issue_codes(report)
    if report.get("errors"):
        hard = {"GOV-DUPLICATE-001", "GOV-SCHEMA-001"}
        state = "blocked" if hard.intersection(codes) else "needs_human"
    elif report.get("warnings"):
        state = "needs_human"
    else:
        state = "draft"
    return {"state": state, "issue_codes": list(codes), "can_request_approval": not report.get("errors")}


def _record_identity(report: Mapping[str, Any], route: str, created_at: str) -> ResearchObjectIdentity:
    content = {
        "route": route,
        "table_name": report.get("table_name"),
        "destination": report.get("destination"),
        "content_sha256": report.get("content_sha256"),
        "columns": report.get("columns", []),
        "row_count": report.get("row_count"),
    }
    digest_seed = ResearchObjectIdentity.from_content(
        "data_intake",
        "INTAKE-SEED",
        1,
        content,
        "steelai-data-intake-adapter",
        created_at=created_at,
    ).content_digest
    return ResearchObjectIdentity(
        object_type="data_intake",
        object_id="INTAKE-" + digest_seed[:20].upper(),
        revision=1,
        content_digest=digest_seed,
        created_at=created_at,
        created_by="steelai-data-intake-adapter",
    )


def prepare_intake_governance(
    report: Mapping[str, Any],
    *,
    route: str,
    reviewer_id: str | None = None,
    rationale: str | None = None,
    confirmed: bool = False,
    source_id: str | None = None,
    source_digest: str | None = None,
    evidence_class: str | EvidenceClass = EvidenceClass.REAL_RESEARCH_DATA,
    decided_at: str | None = None,
    workflow_identity: WorkflowIdentity | Mapping[str, Any] | None = None,
) -> IntakeGovernanceRecord:
    if route not in {"standard_csv", "external_file", "steeldata", "thermal_simulation"}:
        raise ValueError("route must be standard_csv, external_file, steeldata or thermal_simulation")
    timestamp = decided_at or utc_now()
    identity = _record_identity(report, route, timestamp)
    workflow = coerce_workflow_identity(
        workflow_identity,
        seed={
            "route": route,
            "table_name": report.get("table_name"),
            "content_sha256": report.get("content_sha256"),
            "object_id": identity.object_id,
        },
        require_run=confirmed,
    )
    digest = source_digest or str(report.get("content_sha256", ""))
    statuses = sorted({str(row.get("source_status", "")).strip() for row in report.get("rows", []) if row.get("source_status")})
    source = SourceReference(
        source_id=source_id or "SOURCE-" + digest[:20].upper(),
        source_revision=1,
        source_digest=digest,
        evidence_class=EvidenceClass(evidence_class).value,
        source_status="+".join(statuses) or "unregistered",
    )
    preview = preview_intake_governance(report)
    state = preview["state"]
    approvals: tuple[ApprovalSnapshot, ...] = ()
    transitions: tuple[TransitionRecord, ...] = ()
    if report.get("errors"):
        return IntakeGovernanceRecord(
            identity.object_id, route, state, identity, workflow, source, approvals, transitions,
            str(report.get("status", "blocked")), tuple(preview["issue_codes"]), timestamp,
        )
    if not confirmed or not reviewer_id or not reviewer_id.strip() or not rationale or not rationale.strip():
        return IntakeGovernanceRecord(
            identity.object_id, route, state, identity, workflow, source, approvals, transitions,
            str(report.get("status", "ready")), tuple(preview["issue_codes"]), timestamp,
        )

    approval = ApprovalSnapshot.create(
        identity,
        ApprovalDecision.APPROVED,
        reviewer_id.strip(),
        f"{route} append-only admission",
        rationale.strip(),
        decided_at=timestamp,
    )
    approvals_list = [approval]
    initial_state = state
    approved_transition = transition_state(
        identity,
        initial_state,
        GovernanceState.APPROVED,
        actor="human",
        approval=approval,
        occurred_at=timestamp,
    )
    if report.get("warnings"):
        approvals_list.append(ApprovalSnapshot.create(
            identity,
            ApprovalDecision.WARNING_ACCEPTED,
            reviewer_id.strip(),
            f"{route} validation warnings",
            rationale.strip() + " | Warnings accepted: " + " ; ".join(map(str, report["warnings"])),
            decided_at=timestamp,
        ))
    return IntakeGovernanceRecord(
        identity.object_id,
        route,
        GovernanceState.APPROVED.value,
        identity,
        workflow,
        source,
        tuple(approvals_list),
        (approved_transition,),
        str(report.get("status", "ready")),
        tuple(preview["issue_codes"]),
        timestamp,
    )


def _write_normalized_csv(path: Path, report: Mapping[str, Any]) -> None:
    columns = list(report.get("columns", []))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report.get("rows", []))


def _publish_audit(
    record: IntakeGovernanceRecord,
    report: Mapping[str, Any],
    commit_result: Mapping[str, Any],
    *,
    output_root: Path,
    extra_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    destination = output_root.resolve() / record.intake_id
    stage = create_staging_directory(output_root, record.intake_id)
    try:
        write_json_atomic(stage / "validation_manifest.json", _safe_report(dict(report), include_rows=False))
        _write_normalized_csv(stage / "normalized_staging.csv", report)
        write_json_atomic(stage / "commit_result.json", dict(commit_result))
        write_json_atomic(stage / "governance_record.json", record.to_dict())
        for name, value in (extra_artifacts or {}).items():
            if Path(name).name != name or not name.endswith(".json"):
                raise ValueError("extra governance artifacts must be simple JSON filenames")
            write_json_atomic(stage / name, dict(value))
        result_level = (
            ResultLevel.ACCEPTED_EVIDENCE
            if record.state == GovernanceState.COMPLETE.value
            else ResultLevel.WORKING_CANDIDATE
        )
        manifest = build_manifest(
            stage,
            publication_id=record.intake_id,
            identity=record.identity,
            state=record.state,
            result_level=result_level,
            evidence_class=record.source.evidence_class,
            sources=(record.source,),
            approvals=record.approvals,
            generated_by="steelai-data-intake-adapter",
            generated_at=record.created_at,
            metadata={
                "route": record.route,
                "validation_status": record.validation_status,
                "workflow_identity": record.workflow_identity.to_dict(),
            },
        )
        seal_package(stage, manifest)
        verification = verify_package(stage)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "intake audit package failed verification")
        if record.state == GovernanceState.COMPLETE.value:
            evaluate_formal_write(
                record.identity,
                state=record.state,
                result_level=result_level,
                evidence_class=record.source.evidence_class,
                sources=(record.source,),
                approvals=record.approvals,
                qc_status="warning" if report.get("warnings") else "passed",
                provenance_complete=True,
                manifest_valid=True,
                destination_allowed=True,
                append_only=True,
            )
        publication = publish_append_only(stage, destination)
        return {
            "governance_state": record.state,
            "governance_intake_id": record.intake_id,
            "request_id": record.workflow_identity.request_id,
            "task_id": record.workflow_identity.task_id,
            "run_id": record.workflow_identity.run_id,
            "task_revision": record.workflow_identity.task_revision,
            "governance_package": str(destination),
            "governance_manifest_sha256": publication.manifest_digest,
            "governance_reused": publication.reused,
        }
    except Exception:
        expected_prefix = f".tmp-{record.intake_id}-"
        if (
            stage.exists()
            and stage.parent.resolve() == output_root.resolve()
            and stage.name.startswith(expected_prefix)
        ):
            shutil.rmtree(stage)
        raise


def commit_standard_intake_governed(
    report: dict[str, Any],
    *,
    reviewer_id: str,
    rationale: str,
    confirmed: bool,
    route: str = "standard_csv",
    source_id: str | None = None,
    source_digest: str | None = None,
    evidence_class: str | EvidenceClass = EvidenceClass.REAL_RESEARCH_DATA,
    project_root: Path = ROOT,
    contract_path: Path = CONTRACT_PATH,
    id_policy_path: Path = ID_POLICY_PATH,
    output_root: Path | None = None,
    decided_at: str | None = None,
    extra_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    workflow_identity: WorkflowIdentity | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    record = prepare_intake_governance(
        report,
        route=route,
        reviewer_id=reviewer_id,
        rationale=rationale,
        confirmed=confirmed,
        source_id=source_id,
        source_digest=source_digest,
        evidence_class=evidence_class,
        decided_at=decided_at,
        workflow_identity=workflow_identity,
    )
    if record.state != GovernanceState.APPROVED.value:
        code = record.issue_codes[0] if record.issue_codes else "GOV-APPROVAL-001"
        raise GovernanceError(code, record.state, "intake is not approved for execution")
    approval = next(item for item in record.approvals if item.decision == "approved")
    running = authorize_execution(record.identity, record.state, approval, occurred_at=record.created_at)
    record = replace(record, state="running", transitions=(*record.transitions, running))
    try:
        result = commit_intake(
            report,
            project_root=project_root,
            contract_path=contract_path,
            id_policy_path=id_policy_path,
        )
    except (ValueError, OSError) as exc:
        blocked = transition_state(record.identity, "running", "blocked", actor="system")
        record = replace(record, state="blocked", transitions=(*record.transitions, blocked))
        try:
            _publish_audit(
                record,
                report,
                {"status": "not_committed", "error": str(exc)},
                output_root=output_root or project_root / "outputs" / "governed_data_intake",
                extra_artifacts=extra_artifacts,
            )
        except (GovernanceError, OSError, ValueError):
            pass
        raise

    if report.get("warnings"):
        warning = transition_state(record.identity, "running", "warning", actor="system")
        warning_approval = next(item for item in record.approvals if item.decision == "warning_accepted")
        complete = transition_state(
            record.identity,
            "warning",
            "complete",
            actor="human",
            approval=warning_approval,
        )
        transitions = (*record.transitions, warning, complete)
    else:
        passed = transition_state(record.identity, "running", "passed", actor="system")
        complete = transition_state(record.identity, "passed", "complete", actor="system")
        transitions = (*record.transitions, passed, complete)
    record = replace(record, state="complete", transitions=transitions)
    governance = _publish_audit(
        record,
        report,
        result,
        output_root=output_root or project_root / "outputs" / "governed_data_intake",
        extra_artifacts=extra_artifacts,
    )
    return {**result, **governance}


def commit_intake_batch_governed(
    reports: list[dict[str, Any]],
    batch_report: dict[str, Any],
    *,
    reviewer_id: str,
    rationale: str,
    confirmed: bool,
    source_id: str,
    source_digest: str,
    project_root: Path = ROOT,
    contract_path: Path = CONTRACT_PATH,
    id_policy_path: Path = ID_POLICY_PATH,
    output_root: Path | None = None,
    extra_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    workflow_identity: WorkflowIdentity | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Govern and transactionally append a related multi-table intake."""
    record = prepare_intake_governance(
        batch_report,
        route="thermal_simulation",
        reviewer_id=reviewer_id,
        rationale=rationale,
        confirmed=confirmed,
        source_id=source_id,
        source_digest=source_digest,
        workflow_identity=workflow_identity,
    )
    if record.state != GovernanceState.APPROVED.value:
        code = record.issue_codes[0] if record.issue_codes else "GOV-APPROVAL-001"
        raise GovernanceError(code, record.state, "batch intake is not approved for execution")
    approval = next(item for item in record.approvals if item.decision == "approved")
    running = authorize_execution(record.identity, record.state, approval, occurred_at=record.created_at)
    record = replace(record, state="running", transitions=(*record.transitions, running))
    try:
        result = commit_intake_batch(
            reports, project_root=project_root, contract_path=contract_path,
            id_policy_path=id_policy_path,
        )
    except (ValueError, OSError) as exc:
        blocked = transition_state(record.identity, "running", "blocked", actor="system")
        record = replace(record, state="blocked", transitions=(*record.transitions, blocked))
        try:
            _publish_audit(
                record, batch_report, {"status": "not_committed", "error": str(exc)},
                output_root=output_root or project_root / "outputs" / "governed_data_intake",
                extra_artifacts=extra_artifacts,
            )
        except (GovernanceError, OSError, ValueError):
            pass
        raise
    passed = transition_state(record.identity, "running", "passed", actor="system")
    complete = transition_state(record.identity, "passed", "complete", actor="system")
    record = replace(record, state="complete", transitions=(*record.transitions, passed, complete))
    governance = _publish_audit(
        record, batch_report, result,
        output_root=output_root or project_root / "outputs" / "governed_data_intake",
        extra_artifacts=extra_artifacts,
    )
    return {**result, **governance}


def commit_steeldata_intake_governed(
    run_dir: str | Path,
    bindings: dict[str, str],
    source_status: str,
    expected_preview_sha256: str,
    *,
    reviewer_id: str,
    rationale: str,
    confirmed: bool,
    project_root: Path = ROOT,
    contract_path: Path = CONTRACT_PATH,
    id_policy_path: Path = ID_POLICY_PATH,
    decided_at: str | None = None,
    workflow_identity: WorkflowIdentity | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild the SteelData candidate and admit it through the same governed append gate."""
    from steelai.steeldata_bridge import inspect_run, prepare_intake

    inspection = inspect_run(run_dir)
    candidate = prepare_intake(
        inspection,
        bindings,
        source_status,
        project_root=project_root,
        contract_path=contract_path,
        id_policy_path=id_policy_path,
    )
    if candidate["preview_sha256"] != expected_preview_sha256:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "SteelData preview changed after review")
    result = commit_standard_intake_governed(
        candidate["report"],
        reviewer_id=reviewer_id,
        rationale=rationale,
        confirmed=confirmed,
        route="steeldata",
        source_id="STEELDATA-" + str(inspection.manifest["run_id"]),
        source_digest=inspection.manifest_sha256,
        project_root=project_root,
        contract_path=contract_path,
        id_policy_path=id_policy_path,
        decided_at=decided_at,
        extra_artifacts={"steeldata_provenance.json": candidate["evidence"]},
        workflow_identity=workflow_identity,
    )
    return {
        **result,
        "source_run_id": inspection.manifest["run_id"],
        "steeldata_run_id": inspection.manifest["run_id"],
        "source_manifest_sha256": inspection.manifest_sha256,
    }
