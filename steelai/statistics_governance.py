"""T53 governance adapter for verified SteelStats descriptive reports."""
from __future__ import annotations

import csv
import json
import shutil
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
    sha256_file,
    transition_state,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS
from steelai.steelstats_bridge import SteelStatsClient, run_statistics_from_steeldata


GOVERNED_STATISTICS_OUTPUTS = OUTPUTS / "governed_statistics"
INPUT_FILES = ("analysis_plan.json", "units.csv", "observations.csv", "decisions.csv")
REPORT_FILES = ("statistics_report.md", "statistics_result.json", "report_manifest.json", "COMPLETE")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", f"JSON artifact must be an object: {path.name}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"cannot read CSV artifact: {path.name}") from exc


def _required_files(root: Path, names: tuple[str, ...], label: str) -> dict[str, Path]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"{label} directory does not exist")
    result: dict[str, Path] = {}
    for name in names:
        path = (resolved / name).resolve()
        if path.parent != resolved or path.is_symlink() or not path.is_file():
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"{label} is missing {name}")
        result[name] = path
    return result


def build_statistics_statement_policy(
    statistics_result: Mapping[str, Any],
    *,
    governance_state: str,
    evidence_class: str,
    quality_status: str,
) -> dict[str, Any]:
    """Bind descriptive wording to the verified result state and evidence level."""
    groups = [item for item in statistics_result.get("groups", []) if isinstance(item, dict)]
    group_sizes = [
        int(item.get("statistics", {}).get("n", 0))
        for item in groups
        if isinstance(item.get("statistics"), dict)
    ]
    minimum_group_n = min(group_sizes) if group_sizes else 0
    synthetic = evidence_class == EvidenceClass.SYNTHETIC_DEMO_DATA.value
    if governance_state != "complete" or not groups:
        evidence_level = "NA"
    elif synthetic:
        evidence_level = "NA"
    elif quality_status == "passed" and minimum_group_n >= 3:
        evidence_level = "L3"
    elif minimum_group_n >= 2:
        evidence_level = "L2"
    else:
        evidence_level = "L1"

    allowed = [] if governance_state != "complete" else [
        "可按登记的统计单位和分组报告 n、均值、中位数、样本标准差、最小值、最大值和极差。",
        "可描述已登记组之间的数值方向，但必须明确这是描述性比较。",
    ]
    cautious = [
        f"当前最低组样本量为 n={minimum_group_n}，解释时必须同时报告样本量和统计单位。",
        "所有表述必须附带方法版本、纳入决定、来源摘要和现有 QC 局限。",
    ]
    if quality_status == "warning":
        cautious.append("报告包含 warning，必须逐项保留缺失、排除或来源警告，不得只摘取均值。")
    if synthetic:
        cautious.append("该包为合成演示，只能说明流程能力，不能作为实验事实。")
    prohibited = [
        "不得把描述性差异写成统计显著差异或总体无差异。",
        "不得从组间均值方向推出材料成分、工艺或组织的因果作用。",
        "不得把 SteelStats 输出写回或覆盖 SteelData 观测和正式科研长表。",
        "不得省略统计单位、组样本量、排除记录和来源状态。",
    ]
    if governance_state != "complete":
        prohibited.insert(0, "当前治理状态不是 complete，不得引用该结果形成科研表述。")
    return {
        "schema_version": "1.0",
        "policy_id": "SteelAI-Statistics-Statement-Policy-v1.0",
        "governance_state": governance_state,
        "evidence_class": evidence_class,
        "evidence_level": evidence_level,
        "quality_status": quality_status,
        "minimum_group_n": minimum_group_n,
        "inferential_statistics_performed": False,
        "causal_inference_allowed": False,
        "allowed_statements": allowed,
        "cautious_statements": cautious,
        "prohibited_statements": prohibited,
        "prohibited_claim_tokens": ["统计显著", "显著差异", "证明因果", "导致了", "总体无差异"],
    }


def _registry(
    run_result: Mapping[str, Any],
    plan: Mapping[str, Any],
    units: list[dict[str, str]],
    observations: list[dict[str, str]],
    decisions: list[dict[str, str]],
    statistics_result: Mapping[str, Any],
) -> dict[str, Any]:
    decision_by_observation = {row.get("observation_id", ""): row for row in decisions}
    observation_ids = {row.get("observation_id", "") for row in observations}
    if "" in observation_ids or observation_ids != set(decision_by_observation):
        raise GovernanceError(
            "GOV-SCHEMA-001",
            "blocked",
            "every statistical observation must have exactly one inclusion decision",
        )
    group_records = []
    for item in statistics_result.get("groups", []):
        included = item.get("included_unit_observations", [])
        group_records.append({
            "group": item.get("group", {}),
            "n": item.get("statistics", {}).get("n"),
            "qc_status": item.get("qc", {}).get("status"),
            "interpretation": item.get("interpretation"),
            "observation_ids": [row.get("observation_id") for row in included],
            "statistical_unit_ids": [row.get("statistical_unit_id") for row in included],
        })
    source = run_result.get("source", {})
    return {
        "schema_version": "1.0",
        "registry_id": "STATREG-" + digest_value({
            "analysis_id": run_result.get("analysis_id"),
            "source_manifest": source.get("manifest_sha256"),
            "plan_id": plan.get("plan_id"),
        })[:20].upper(),
        "analysis_id": run_result.get("analysis_id"),
        "statistical_unit_type": plan.get("statistical_unit_type"),
        "group_keys": plan.get("group_keys", []),
        "analysis_plan_id": plan.get("plan_id"),
        "analysis_plan_version": plan.get("plan_version"),
        "experimental_method_versions": plan.get("method_versions", {}),
        "statistics_method_version": statistics_result.get("statistics_method_version"),
        "source": {
            "steeldata_run_id": source.get("run_id"),
            "steeldata_manifest_sha256": source.get("manifest_sha256"),
            "steeldata_qc_status": source.get("qc_status"),
            "steeldata_modified": source.get("modified"),
        },
        "counts": {
            "statistical_units": len(units),
            "observations": len(observations),
            "inclusion_decisions": len(decisions),
            "groups": len(group_records),
        },
        "statistical_units": [{
            "unit_id": row.get("unit_id"),
            "unit_type": row.get("unit_type"),
            "sample_id": row.get("sample_id"),
            "specimen_id": row.get("specimen_id"),
            "unit_status": row.get("unit_status"),
        } for row in units],
        "observation_decisions": [{
            "observation_id": row.get("observation_id"),
            "decision": row.get("decision"),
            "reason_code": row.get("reason_code"),
            "reviewer": row.get("reviewer"),
            "reviewed_at": row.get("reviewed_at"),
            "evidence_ref": row.get("evidence_ref"),
        } for row in decisions],
        "groups": group_records,
        "boundaries": {
            "descriptive_only": True,
            "inferential_statistics": False,
            "causal_inference": False,
            "source_writeback": False,
        },
    }


def _traceable_report(
    publication_id: str,
    registry: Mapping[str, Any],
    policy: Mapping[str, Any],
    original_report: str,
) -> str:
    source = registry["source"]
    lines = [
        "# SteelAI 可追溯描述统计报告",
        "",
        f"- 治理结果 ID：`{publication_id}`",
        f"- SteelStats 分析 ID：`{registry['analysis_id']}`",
        f"- 统计单位：`{registry['statistical_unit_type']}`",
        f"- 实验方法版本：`{', '.join(sorted(set(registry['experimental_method_versions'].values())))}`",
        f"- 统计方法版本：`{registry['statistics_method_version']}`",
        f"- SteelData 来源运行：`{source['steeldata_run_id']}`",
        f"- SteelData Manifest SHA-256：`{source['steeldata_manifest_sha256']}`",
        f"- 证据等级：`{policy['evidence_level']}`",
        f"- 质量状态：`{policy['quality_status']}`",
        "",
        "## 允许表述",
        "",
        *[f"- {item}" for item in policy["allowed_statements"]],
        "",
        "## 谨慎表述",
        "",
        *[f"- {item}" for item in policy["cautious_statements"]],
        "",
        "## 禁止表述",
        "",
        *[f"- {item}" for item in policy["prohibited_statements"]],
        "",
        "## SteelStats 原始描述统计报告",
        "",
        original_report.rstrip(),
        "",
    ]
    return "\n".join(lines)


def register_statistics_result(
    run_result: Mapping[str, Any],
    *,
    reviewer_id: str,
    rationale: str,
    reviewed_at: str,
    accept_warnings: bool,
    output_root: Path = GOVERNED_STATISTICS_OUTPUTS,
) -> dict[str, Any]:
    """Wrap a verified SteelStats report without modifying its source or input bundle."""
    if run_result.get("status") != "complete" or run_result.get("statistics", {}).get("verification") != "passed":
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "SteelStats result is not independently verified")
    if not reviewer_id.strip() or not rationale.strip():
        raise GovernanceError("GOV-APPROVAL-001", "needs_human", "reviewer and rationale are required")

    input_root = Path(str(run_result.get("input_bundle", ""))).resolve()
    report_root = Path(str(run_result.get("report_dir", ""))).resolve()
    input_files = _required_files(input_root, INPUT_FILES, "statistics input bundle")
    report_files = _required_files(report_root, REPORT_FILES, "SteelStats report package")
    plan = _read_json(input_files["analysis_plan.json"])
    units = _read_csv(input_files["units.csv"])
    observations = _read_csv(input_files["observations.csv"])
    decisions = _read_csv(input_files["decisions.csv"])
    result_data = _read_json(report_files["statistics_result.json"])
    if result_data.get("analysis_id") != run_result.get("analysis_id"):
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "SteelStats analysis identity mismatch")
    decision_reviewers = {row.get("reviewer", "").strip() for row in decisions}
    decision_times = {row.get("reviewed_at", "").strip() for row in decisions}
    if decision_reviewers != {reviewer_id.strip()} or decision_times != {reviewed_at.strip()}:
        raise GovernanceError(
            "GOV-APPROVAL-001",
            "blocked",
            "governance approval must match every recorded inclusion decision",
        )

    quality_status = str(run_result.get("quality_status", ""))
    if quality_status not in {"passed", "warning"}:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "statistics QC did not pass")
    if quality_status == "warning" and not accept_warnings:
        raise GovernanceError("GOV-SCOPE-001", "needs_human", "statistics warnings require explicit acceptance")

    synthetic = bool(units) and all(row.get("unit_status") == "synthetic_fixture" for row in units)
    evidence_class = (
        EvidenceClass.SYNTHETIC_DEMO_DATA.value if synthetic else EvidenceClass.REAL_RESEARCH_DATA.value
    )
    artifact_digests = {
        f"input/{name}": sha256_file(path) for name, path in input_files.items()
    } | {
        f"steelstats/{name}": sha256_file(path) for name, path in report_files.items()
    }
    identity_digest = digest_value({
        "analysis_id": run_result.get("analysis_id"),
        "source_manifest_sha256": run_result.get("source", {}).get("manifest_sha256"),
        "artifacts": artifact_digests,
    })
    publication_id = "STAT-" + identity_digest[:20].upper()
    identity = ResearchObjectIdentity(
        object_type="statistics_report",
        object_id=publication_id,
        revision=1,
        content_digest=identity_digest,
        created_at=reviewed_at,
        created_by="steelai-statistics-governance-adapter",
    )
    source_manifest = str(run_result.get("source", {}).get("manifest_sha256", ""))
    sources = (
        SourceReference(
            source_id="STEELDATA-" + str(run_result.get("source", {}).get("run_id", "UNKNOWN")),
            source_revision=1,
            source_digest=source_manifest,
            evidence_class=evidence_class,
            source_status=str(run_result.get("source", {}).get("qc_status", "unknown")),
        ),
        SourceReference(
            source_id="STEELSTATS-" + str(run_result.get("analysis_id")),
            source_revision=1,
            source_digest=sha256_file(report_files["report_manifest.json"]),
            evidence_class=evidence_class,
            source_status="independently_verified",
        ),
    )
    approval = ApprovalSnapshot.create(
        identity,
        ApprovalDecision.APPROVED,
        reviewer_id.strip(),
        "statistical units, inclusion decisions, methods and source binding",
        rationale.strip(),
        decided_at=reviewed_at,
    )
    initial_state = "needs_human" if quality_status == "warning" else "draft"
    approved = transition_state(
        identity, initial_state, "approved", actor="human", approval=approval, occurred_at=reviewed_at,
    )
    running = authorize_execution(identity, "approved", approval, occurred_at=reviewed_at)
    approvals = [approval]
    transitions = [approved, running]
    if quality_status == "warning":
        warning = transition_state(identity, "running", "warning", actor="system", occurred_at=reviewed_at)
        warning_approval = ApprovalSnapshot.create(
            identity,
            ApprovalDecision.WARNING_ACCEPTED,
            reviewer_id.strip(),
            "SteelData and SteelStats warnings",
            rationale.strip() + " | Statistics warnings explicitly accepted.",
            decided_at=reviewed_at,
        )
        complete = transition_state(
            identity, "warning", "complete", actor="human", approval=warning_approval, occurred_at=reviewed_at,
        )
        approvals.append(warning_approval)
        transitions.extend((warning, complete))
    else:
        passed = transition_state(identity, "running", "passed", actor="system", occurred_at=reviewed_at)
        complete = transition_state(identity, "passed", "complete", actor="system", occurred_at=reviewed_at)
        transitions.extend((passed, complete))

    registry = _registry(run_result, plan, units, observations, decisions, result_data)
    policy = build_statistics_statement_policy(
        result_data,
        governance_state="complete",
        evidence_class=evidence_class,
        quality_status=quality_status,
    )
    traceability = {
        "schema_version": "1.0",
        "report_identity": identity.to_dict(),
        "source_manifest_sha256": source_manifest,
        "analysis_plan": "input/analysis_plan.json",
        "statistical_units": "input/units.csv",
        "observations": "input/observations.csv",
        "inclusion_decisions": "input/decisions.csv",
        "statistics_result": "steelstats/statistics_result.json",
        "statistics_report": "steelstats/statistics_report.md",
        "statement_policy": "evidence_statement_rules.json",
    }
    governance_record = {
        "schema_version": "1.0",
        "publication_id": publication_id,
        "state": "complete",
        "identity": identity.to_dict(),
        "sources": [item.to_dict() for item in sources],
        "approvals": [item.to_dict() for item in approvals],
        "transitions": [item.to_dict() for item in transitions],
        "quality_status": quality_status,
        "evidence_level": policy["evidence_level"],
    }

    stage = create_staging_directory(output_root, publication_id)
    try:
        (stage / "input").mkdir()
        (stage / "steelstats").mkdir()
        for name, path in input_files.items():
            shutil.copyfile(path, stage / "input" / name)
        for name, path in report_files.items():
            shutil.copyfile(path, stage / "steelstats" / name)
        write_json_atomic(stage / "statistics_registry.json", registry)
        write_json_atomic(stage / "evidence_statement_rules.json", policy)
        write_json_atomic(stage / "traceability_index.json", traceability)
        write_json_atomic(stage / "governance_record.json", governance_record)
        original_report = report_files["statistics_report.md"].read_text(encoding="utf-8")
        (stage / "traceable_statistics_report.md").write_text(
            _traceable_report(publication_id, registry, policy, original_report),
            encoding="utf-8",
        )
        result_level = (
            ResultLevel.SYNTHETIC_DEMO_ONLY if synthetic else ResultLevel.ACCEPTED_EVIDENCE
        )
        manifest = build_manifest(
            stage,
            publication_id=publication_id,
            identity=identity,
            state="complete",
            result_level=result_level,
            evidence_class=evidence_class,
            sources=sources,
            approvals=tuple(approvals),
            generated_by="steelai-statistics-governance-adapter",
            generated_at=reviewed_at,
            metadata={
                "analysis_id": run_result.get("analysis_id"),
                "quality_status": quality_status,
                "evidence_level": policy["evidence_level"],
                "descriptive_only": True,
                "inferential_statistics": False,
                "causal_inference": False,
            },
        )
        seal_package(stage, manifest)
        verification = verify_package(stage)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "statistics package failed verification")
        if not synthetic:
            evaluate_formal_write(
                identity,
                state="complete",
                result_level=result_level,
                evidence_class=evidence_class,
                sources=sources,
                approvals=tuple(approvals),
                qc_status=quality_status,
                provenance_complete=True,
                manifest_valid=True,
                destination_allowed=True,
                append_only=True,
            )
        destination = output_root.resolve() / publication_id
        publication = publish_append_only(stage, destination)
    except Exception:
        expected_prefix = f".tmp-{publication_id}-"
        if (
            stage.exists()
            and stage.parent.resolve() == output_root.resolve()
            and stage.name.startswith(expected_prefix)
        ):
            shutil.rmtree(stage)
        raise
    return {
        **dict(run_result),
        "governance_state": "complete",
        "governance_id": publication_id,
        "governance_package": str(destination),
        "governance_manifest_sha256": publication.manifest_digest,
        "governance_reused": publication.reused,
        "governance_report": str(destination / "traceable_statistics_report.md"),
        "evidence_level": policy["evidence_level"],
        "statement_policy": policy,
    }


def run_governed_statistics_from_steeldata(
    run_dir: str | Path,
    bindings: dict[str, str],
    method_version: str,
    reviewer: str,
    reviewed_at: str,
    *,
    rationale: str,
    accept_warnings: bool,
    input_root: Path = OUTPUTS / "steelstats_inputs",
    report_root: Path = OUTPUTS / "steelstats_reports",
    governance_root: Path = GOVERNED_STATISTICS_OUTPUTS,
    client: SteelStatsClient | None = None,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    result = run_statistics_from_steeldata(
        run_dir,
        bindings,
        method_version,
        reviewer,
        reviewed_at,
        input_root=input_root,
        report_root=report_root,
        client=client,
        allow_synthetic=allow_synthetic,
    )
    return register_statistics_result(
        result,
        reviewer_id=reviewer,
        rationale=rationale,
        reviewed_at=reviewed_at,
        accept_warnings=accept_warnings,
        output_root=governance_root,
    )


def inspect_governed_statistics(package: str | Path) -> dict[str, Any]:
    root = Path(package).resolve()
    verification = verify_package(root)
    result: dict[str, Any] = {
        "package": str(root),
        "status": verification.status,
        "manifest_sha256": verification.manifest_digest,
        "problems": list(verification.problems),
    }
    if verification.status != "passed":
        return result
    manifest = load_verified_manifest(root)
    registry = _read_json(root / "statistics_registry.json")
    policy = _read_json(root / "evidence_statement_rules.json")
    return {
        **result,
        "governance_state": manifest.state,
        "governance_id": manifest.publication_id,
        "evidence_class": manifest.evidence_class,
        "evidence_level": policy["evidence_level"],
        "quality_status": policy["quality_status"],
        "analysis_id": registry["analysis_id"],
        "registry": registry,
        "statement_policy": policy,
        "report": str(root / "traceable_statistics_report.md"),
    }


def latest_governed_statistics_status(
    output_root: Path = GOVERNED_STATISTICS_OUTPUTS,
) -> dict[str, Any] | None:
    root = output_root.resolve()
    if not root.is_dir():
        return None
    candidates = [
        path for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".tmp-")
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    return inspect_governed_statistics(latest)
