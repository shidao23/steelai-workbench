"""T52 governed Physics Engine runs and model-card packages."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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
    evaluate_formal_write,
    load_verified_manifest,
    publish_append_only,
    seal_package,
    transition_state,
    utc_now,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS
from steelai.physics import (
    MODEL_FAMILIES,
    PhysicsResult,
    calculate_all,
    compare_with_experimental_observations,
    default_model_ids,
    model_by_id,
    model_card_markdown,
)


PHYSICS_RUN_OUTPUTS = OUTPUTS / "physics_runs"


@dataclass(frozen=True)
class PhysicsGovernancePreview:
    run_id: str
    state: str
    identity_digest: str
    input_snapshot: dict[str, Any]
    results: tuple[PhysicsResult, ...]
    comparisons: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    error_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "state": self.state,
            "identity_digest": self.identity_digest,
            "input_snapshot": self.input_snapshot,
            "results": [item.to_dict() for item in self.results],
            "comparisons": list(self.comparisons),
            "warnings": list(self.warnings),
            "error_codes": list(self.error_codes),
        }


def preview_physics_governance(
    sample_id: str,
    composition: Mapping[str, float | None],
    *,
    provided_fields: set[str] | None = None,
    selected_models: Mapping[str, str] | None = None,
    observations: list[dict[str, str]] | None = None,
    source_status: str = "registered_composition_snapshot",
) -> PhysicsGovernancePreview:
    provided = set(provided_fields) if provided_fields is not None else {
        key for key, value in composition.items() if value is not None
    }
    selected = default_model_ids()
    selected.update(dict(selected_models or {}))
    results = tuple(calculate_all(dict(composition), provided, selected))
    model_snapshots = []
    for family in MODEL_FAMILIES:
        model = model_by_id(selected[family])
        model_snapshots.append({
            "model_id": model["model_id"],
            "model_version": model["model_version"],
            "model_family": model["model_family"],
            "formula_or_backend": model["formula_or_backend"],
            "required_inputs": model["required_inputs"],
            "output_unit": model["output_unit"],
            "applicability": model["applicability"],
            "applicable_composition_range": model["applicable_composition_range"],
            "review_status": model["review_status"],
            "calibration_status": model["calibration_status"],
            "residual": model["residual"],
        })
    input_snapshot = {
        "sample_id": sample_id,
        "composition_wt_pct": {key: composition[key] for key in sorted(provided) if composition.get(key) is not None},
        "provided_fields": sorted(provided),
        "source_status": source_status,
        "models": model_snapshots,
        "missing_values_are_zero": False,
        "result_type": "empirical_model_estimate_not_experimental_truth",
    }
    comparisons = tuple(compare_with_experimental_observations(
        sample_id,
        list(results),
        list(observations or []),
    ))
    missing = [item for item in results if item.value is None]
    warnings = tuple(dict.fromkeys(warning for item in results for warning in item.warnings))
    payload = {
        "input_snapshot": input_snapshot,
        "results": [item.to_dict() for item in results],
        "comparisons": comparisons,
    }
    identity_digest = digest_value(payload)
    state = "blocked" if missing else "needs_human" if warnings else "draft"
    codes = (
        ("GOV-SCHEMA-001",)
        if missing
        else ("GOV-SCOPE-001",) if warnings else ()
    )
    return PhysicsGovernancePreview(
        run_id="PHYSICS-" + identity_digest[:20].upper(),
        state=state,
        identity_digest=identity_digest,
        input_snapshot=input_snapshot,
        results=results,
        comparisons=comparisons,
        warnings=warnings,
        error_codes=codes,
    )


def run_governed_physics(
    sample_id: str,
    composition: Mapping[str, float | None],
    *,
    reviewer_id: str,
    rationale: str,
    accept_warnings: bool,
    provided_fields: set[str] | None = None,
    selected_models: Mapping[str, str] | None = None,
    observations: list[dict[str, str]] | None = None,
    source_status: str = "registered_composition_snapshot",
    output_root: Path = PHYSICS_RUN_OUTPUTS,
    decided_at: str | None = None,
) -> dict[str, Any]:
    preview = preview_physics_governance(
        sample_id,
        composition,
        provided_fields=provided_fields,
        selected_models=selected_models,
        observations=observations,
        source_status=source_status,
    )
    if preview.state == "blocked":
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "missing physics input; no value was substituted with zero")
    if preview.warnings and not accept_warnings:
        raise GovernanceError("GOV-SCOPE-001", "needs_human", "applicability warnings require explicit human acceptance")
    if not reviewer_id.strip() or not rationale.strip():
        raise GovernanceError("GOV-APPROVAL-001", "needs_human", "reviewer and rationale are required")

    destination = output_root.resolve() / preview.run_id
    if destination.exists():
        verification = verify_package(destination)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing Physics run is invalidated")
        existing = load_verified_manifest(destination)
        if existing.identity.content_digest != preview.identity_digest:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "Physics run identity conflicts with existing content")
        return {
            "status": "complete",
            "governance_state": existing.state,
            "run_id": existing.publication_id,
            "package": str(destination),
            "manifest_sha256": verification.manifest_digest,
            "reused": True,
            "preview": preview.to_dict(),
        }

    timestamp = decided_at or utc_now()
    identity = ResearchObjectIdentity(
        object_type="physics_run",
        object_id=preview.run_id,
        revision=1,
        content_digest=preview.identity_digest,
        created_at=timestamp,
        created_by="steelai-physics-governance-adapter",
    )
    source = SourceReference(
        source_id="COMPOSITION-" + sample_id,
        source_revision=1,
        source_digest=digest_value({
            "sample_id": sample_id,
            "composition_wt_pct": preview.input_snapshot["composition_wt_pct"],
            "source_status": source_status,
        }),
        evidence_class=EvidenceClass.REAL_RESEARCH_DATA.value,
        source_status=source_status,
        relative_locator="data/processed/composition.csv",
    )
    approval = ApprovalSnapshot.create(
        identity,
        ApprovalDecision.APPROVED,
        reviewer_id.strip(),
        "Physics formula set, input snapshot and declared applicability",
        rationale.strip(),
        decided_at=timestamp,
    )
    initial_state = "needs_human" if preview.warnings else "draft"
    approved = transition_state(identity, initial_state, "approved", actor="human", approval=approval, occurred_at=timestamp)
    running = authorize_execution(identity, "approved", approval, occurred_at=timestamp)
    approvals = [approval]
    transitions = [approved, running]
    if preview.warnings:
        warning = transition_state(identity, "running", "warning", actor="system", occurred_at=timestamp)
        warning_approval = ApprovalSnapshot.create(
            identity,
            ApprovalDecision.WARNING_ACCEPTED,
            reviewer_id.strip(),
            "Physics applicability warnings",
            rationale.strip() + " | Warnings accepted: " + " ; ".join(preview.warnings),
            decided_at=timestamp,
        )
        complete = transition_state(
            identity,
            "warning",
            "complete",
            actor="human",
            approval=warning_approval,
            occurred_at=timestamp,
        )
        approvals.append(warning_approval)
        transitions.extend((warning, complete))
        qc_status = "warning"
    else:
        passed = transition_state(identity, "running", "passed", actor="system", occurred_at=timestamp)
        complete = transition_state(identity, "passed", "complete", actor="system", occurred_at=timestamp)
        transitions.extend((passed, complete))
        qc_status = "passed"

    stage = create_staging_directory(output_root, preview.run_id)
    try:
        write_json_atomic(stage / "input_snapshot.json", preview.input_snapshot)
        write_json_atomic(stage / "results.json", {
            "result_type": "empirical_model_estimate_not_experimental_truth",
            "results": [item.to_dict() for item in preview.results],
        })
        write_json_atomic(stage / "experimental_comparison.json", {
            "residual_definition": "model_value - experimental_value",
            "comparisons": list(preview.comparisons),
        })
        cards = stage / "model_cards"
        cards.mkdir()
        for result in preview.results:
            (cards / f"{result.model_id}.md").write_text(model_card_markdown(result.model_id), encoding="utf-8")
        run_record = {
            "schema_version": "1.0",
            "run_id": preview.run_id,
            "state": "complete",
            "identity": identity.to_dict(),
            "source": source.to_dict(),
            "approvals": [item.to_dict() for item in approvals],
            "transitions": [item.to_dict() for item in transitions],
            "warnings": list(preview.warnings),
            "qc_status": qc_status,
            "result_type": "empirical_model_estimate_not_experimental_truth",
        }
        write_json_atomic(stage / "run_record.json", run_record)
        manifest = build_manifest(
            stage,
            publication_id=preview.run_id,
            identity=identity,
            state="complete",
            result_level=ResultLevel.MODEL_RESULT,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=(source,),
            approvals=tuple(approvals),
            generated_by="steelai-physics-governance-adapter",
            generated_at=timestamp,
            metadata={
                "sample_id": sample_id,
                "model_count": len(preview.results),
                "qc_status": qc_status,
                "result_type": "empirical_model_estimate_not_experimental_truth",
            },
        )
        seal_package(stage, manifest)
        verification = verify_package(stage)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "Physics package failed verification")
        evaluate_formal_write(
            identity,
            state="complete",
            result_level=ResultLevel.MODEL_RESULT,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=(source,),
            approvals=tuple(approvals),
            qc_status=qc_status,
            provenance_complete=True,
            manifest_valid=True,
            destination_allowed=True,
            append_only=True,
        )
        publication = publish_append_only(stage, destination)
    except Exception:
        expected_prefix = f".tmp-{preview.run_id}-"
        if (
            stage.exists()
            and stage.parent.resolve() == output_root.resolve()
            and stage.name.startswith(expected_prefix)
        ):
            shutil.rmtree(stage)
        raise
    return {
        "status": "complete",
        "governance_state": "complete",
        "run_id": preview.run_id,
        "package": str(destination),
        "manifest_sha256": publication.manifest_digest,
        "reused": publication.reused,
        "preview": preview.to_dict(),
    }
