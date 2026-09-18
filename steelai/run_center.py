"""T56 lightweight unified run and accepted-result index.

The center is read-only. It normalizes governed packages, the frozen flagship
demo, research sessions and the local automation status without copying result
payloads or exposing absolute local paths.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from steelai.flagship_demo import verify_flagship_demo
from steelai.governance import load_verified_manifest, verify_package
from steelai.paths import OUTPUTS, PROJECT_LOG, ROOT
from steelai.research_session import list_sessions


RUN_CENTER_VERSION = "1.0.0"
PORTFOLIO_ACCEPTANCE_REGISTRY = ROOT / "config" / "portfolio_acceptance_v1.0.json"
PORTFOLIO_RESULT_LEVELS = frozenset({"accepted_evidence", "model_result", "human_conclusion"})
HUMAN_ACCEPTANCE_DECISIONS = frozenset({"approved", "warning_accepted"})


@dataclass(frozen=True)
class RunSource:
    root_name: str
    module: str
    object_type: str
    next_label: str
    next_url: str


RUN_SOURCES = (
    RunSource("governed_data_intake", "数据接入", "governed_data_intake", "打开数据处理", "/intake"),
    RunSource("physics_runs", "Physics Engine", "physics_run", "打开物理计算", "/analysis?module=physics"),
    RunSource("governed_statistics", "可追溯统计", "statistics_result", "打开可追溯统计", "/analysis?module=statistics"),
    RunSource("image_model_tasks", "图像与模型任务", "image_model_task", "打开模型实验室", "/advanced?module=model_lab"),
    RunSource("image_model_runs", "图像与模型运行", "image_model_run", "打开模型实验室", "/advanced?module=model_lab"),
    RunSource("image_model_reviews", "图像结果复核", "image_model_review", "打开组织分析", "/analysis?module=ebsd"),
    RunSource("agent_gateway", "Agent 证据网关", "agent_gateway_run", "打开 AI 助手", "/assistant"),
    RunSource("multi_agent_runs", "多智能体协作", "multi_agent_run", "打开多智能体协作", "/advanced?module=multi_agent"),
    RunSource("protocol_calls", "MCP 工具调用", "research_protocol_call", "打开多智能体协作", "/advanced?module=multi_agent"),
    RunSource("real_data_cases", "真实数据案例", "real_data_model_case", "打开真实数据案例", "/advanced?module=real_data"),
    RunSource("agent_workflow_evaluations", "智能体流程评估", "agent_workflow_evaluation", "打开助手评测", "/advanced?module=evaluation"),
    RunSource("portfolio_releases", "岗位作品集发布", "portfolio_release", "打开作品集与发布", "/portfolio"),
)

FILTER_LABELS = (
    "需要我处理",
    "全部",
    "待人工确认",
    "被阻止",
    "完整性失效",
    "进行中",
    "已完成",
    "已验收成果",
)


@dataclass(frozen=True)
class RunCenterRecord:
    task_id: str
    title: str
    module: str
    object_type: str
    state: str
    state_group: str
    integrity_status: str
    updated_at: str
    reviewer_id: str
    result_level: str
    evidence_class: str
    result_location: str
    portfolio_eligible: bool
    portfolio_reason: str
    next_label: str
    next_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_location(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except (OSError, ValueError):
        return "unavailable"


def _state_group(state: str, integrity_status: str = "passed") -> str:
    if integrity_status != "passed" or state == "invalidated":
        return "invalidated"
    if state in {"draft", "needs_human", "warning"}:
        return "needs_human"
    if state in {"blocked", "rejected", "failed", "canceled"}:
        return "blocked"
    if state in {"running", "approved", "active", "planned", "idle", "ready"}:
        return "running"
    if state in {"complete", "completed", "passed", "archived"}:
        return "completed"
    return "needs_human"


def _approval_summary(identity: Any, approvals: Iterable[Any]) -> tuple[str, bool]:
    reviewer = ""
    accepted = False
    for approval in approvals:
        if not approval.matches(identity):
            continue
        decision = str(getattr(approval, "decision", ""))
        reviewer_id = str(getattr(approval, "reviewer_id", ""))
        if reviewer_id:
            reviewer = reviewer_id
        if decision in HUMAN_ACCEPTANCE_DECISIONS:
            accepted = True
    return reviewer, accepted


def _portfolio_decision(
    *,
    state: str,
    result_level: str,
    integrity_status: str,
    human_accepted: bool,
) -> tuple[bool, str]:
    if integrity_status != "passed":
        return False, "完整性未通过"
    if state != "complete":
        return False, "尚未达到 complete"
    if not human_accepted:
        return False, "缺少具名人工验收"
    if result_level not in PORTFOLIO_RESULT_LEVELS:
        return False, "结果等级仍是中间产物"
    return True, "complete 且已有具名人工验收"


def _governed_records(outputs_root: Path, repository_root: Path) -> list[RunCenterRecord]:
    records: list[RunCenterRecord] = []
    for source in RUN_SOURCES:
        parent = outputs_root / source.root_name
        try:
            packages = sorted(
                (item for item in parent.iterdir() if item.is_dir() and not item.name.startswith(".tmp-")),
                key=lambda item: item.name,
            ) if parent.is_dir() else []
        except OSError:
            packages = []
        for package in packages:
            try:
                verification = verify_package(package)
            except (OSError, ValueError):
                verification = None
            if verification is None or verification.status != "passed":
                records.append(RunCenterRecord(
                    task_id=package.name,
                    title=package.name,
                    module=source.module,
                    object_type=source.object_type,
                    state="invalidated",
                    state_group="invalidated",
                    integrity_status="invalidated",
                    updated_at="",
                    reviewer_id="",
                    result_level="",
                    evidence_class="",
                    result_location=_safe_location(package, repository_root),
                    portfolio_eligible=False,
                    portfolio_reason="完整性未通过",
                    next_label=source.next_label,
                    next_url=source.next_url,
                ))
                continue
            try:
                manifest = load_verified_manifest(package)
            except (OSError, ValueError):
                continue
            reviewer, accepted = _approval_summary(manifest.identity, manifest.approvals)
            eligible, reason = _portfolio_decision(
                state=manifest.state,
                result_level=manifest.result_level,
                integrity_status="passed",
                human_accepted=accepted,
            )
            records.append(RunCenterRecord(
                task_id=manifest.publication_id,
                title=manifest.publication_id,
                module=source.module,
                object_type=manifest.identity.object_type,
                state=manifest.state,
                state_group=_state_group(manifest.state),
                integrity_status="passed",
                updated_at=manifest.generated_at,
                reviewer_id=reviewer,
                result_level=manifest.result_level,
                evidence_class=manifest.evidence_class,
                result_location=_safe_location(package, repository_root),
                portfolio_eligible=eligible,
                portfolio_reason=reason,
                next_label=source.next_label,
                next_url=source.next_url,
            ))
    return records


def load_portfolio_acceptances(path: Path = PORTFOLIO_ACCEPTANCE_REGISTRY) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    if payload.get("schema_version") != "1.0" or payload.get("registry_id") != "SteelAI-Portfolio-Acceptance-v1.0":
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("entries", []):
        if not isinstance(row, Mapping):
            continue
        record_id = str(row.get("record_id", ""))
        if (
            record_id
            and "/" not in record_id
            and "\\" not in record_id
            and row.get("decision") in HUMAN_ACCEPTANCE_DECISIONS
            and str(row.get("reviewer_id", "")).strip()
            and str(row.get("scope", "")).strip()
        ):
            result[record_id] = dict(row)
    return result


def _flagship_records(
    outputs_root: Path,
    repository_root: Path,
    acceptance_registry: Path,
) -> list[RunCenterRecord]:
    parent = outputs_root / "flagship_demo"
    acceptances = load_portfolio_acceptances(acceptance_registry)
    try:
        packages = sorted((item for item in parent.glob("T40-*") if item.is_dir()), key=lambda item: item.name)
    except OSError:
        packages = []
    records: list[RunCenterRecord] = []
    for package in packages:
        try:
            verification = verify_flagship_demo(package)
        except (OSError, ValueError):
            verification = {"status": "failed"}
        integrity = "passed" if verification.get("status") == "passed" else "invalidated"
        acceptance = acceptances.get(package.name, {})
        eligible = integrity == "passed" and bool(acceptance)
        records.append(RunCenterRecord(
            task_id=package.name,
            title="T40 公开合成旗舰演示",
            module="旗舰演示",
            object_type="synthetic_flagship_demo",
            state="complete" if integrity == "passed" else "invalidated",
            state_group="completed" if integrity == "passed" else "invalidated",
            integrity_status=integrity,
            updated_at=str(acceptance.get("accepted_on", "")),
            reviewer_id=str(acceptance.get("reviewer_id", "")),
            result_level="synthetic_demo_only",
            evidence_class="synthetic_demo_data",
            result_location=_safe_location(package, repository_root),
            portfolio_eligible=eligible,
            portfolio_reason=(
                "完整性通过且已登记人工验收；仅展示工程能力"
                if eligible else "尚无有效的人工验收登记或完整性未通过"
            ),
            next_label="打开旗舰演示",
            next_url="/advanced?module=flagship",
        ))
    return records


def _session_records(session_root: Path, repository_root: Path) -> list[RunCenterRecord]:
    records: list[RunCenterRecord] = []
    for session in list_sessions(root=session_root):
        session_id = str(session.get("session_id", ""))
        state = str(session.get("status", "planned"))
        records.append(RunCenterRecord(
            task_id=session_id,
            title=str(session.get("title", session_id)),
            module="科研会话",
            object_type="research_session",
            state=state,
            state_group=_state_group(state),
            integrity_status="not_governed",
            updated_at=str(session.get("updated_at", "")),
            reviewer_id="",
            result_level="working_candidate",
            evidence_class="human_conclusion",
            result_location=_safe_location(session_root / f"{session_id}.json", repository_root),
            portfolio_eligible=False,
            portfolio_reason="科研会话不是已验收成果",
            next_label="继续科研会话",
            next_url="/projects?module=session",
        ))
    return records


def _automation_records(outputs_root: Path, repository_root: Path) -> list[RunCenterRecord]:
    status_path = outputs_root / "automation" / "autodimple_br10_status.json"
    status = _read_json(status_path)
    if not status:
        return []
    state = str(status.get("status", "idle"))
    return [RunCenterRecord(
        task_id=str(status.get("job_id", "autodimple_br10")),
        title="B/R AutoDimple 自动化任务",
        module="自动化任务",
        object_type="automation_job",
        state=state,
        state_group=_state_group(state),
        integrity_status="not_governed",
        updated_at=str(status.get("finished_at") or status.get("started_at") or ""),
        reviewer_id="",
        result_level="working_candidate",
        evidence_class="model_output",
        result_location=_safe_location(status_path, repository_root),
        portfolio_eligible=False,
        portfolio_reason="自动化状态不是人工验收结果",
        next_label="打开任务与结果",
        next_url="/advanced?module=automation",
    )]


def collect_run_records(
    *,
    repository_root: Path = ROOT,
    outputs_root: Path = OUTPUTS,
    session_root: Path = PROJECT_LOG / "research_sessions",
    acceptance_registry: Path = PORTFOLIO_ACCEPTANCE_REGISTRY,
) -> list[RunCenterRecord]:
    records = _governed_records(outputs_root, repository_root)
    records.extend(_flagship_records(outputs_root, repository_root, acceptance_registry))
    records.extend(_session_records(session_root, repository_root))
    records.extend(_automation_records(outputs_root, repository_root))
    return sorted(records, key=lambda item: (item.updated_at, item.task_id), reverse=True)


def filter_run_records(records: Iterable[RunCenterRecord], label: str) -> list[RunCenterRecord]:
    rows = list(records)
    if label == "需要我处理":
        return [
            item for item in rows
            if item.state_group in {"needs_human", "blocked", "invalidated"}
        ]
    if label == "全部":
        return rows
    if label == "待人工确认":
        return [item for item in rows if item.state_group == "needs_human"]
    if label == "被阻止":
        return [item for item in rows if item.state_group == "blocked"]
    if label == "完整性失效":
        return [item for item in rows if item.state_group == "invalidated"]
    if label == "进行中":
        return [item for item in rows if item.state_group == "running"]
    if label == "已完成":
        return [item for item in rows if item.state_group == "completed"]
    if label == "已验收成果":
        return [item for item in rows if item.portfolio_eligible]
    raise ValueError(f"unknown run-center filter: {label}")


def accepted_portfolio_results(records: Iterable[RunCenterRecord]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in records if item.portfolio_eligible]


def run_center_snapshot(**kwargs: Any) -> dict[str, Any]:
    records = collect_run_records(**kwargs)
    return {
        "schema_version": "1.0",
        "feature_version": RUN_CENTER_VERSION,
        "record_count": len(records),
        "counts": {
            "running": sum(item.state_group == "running" for item in records),
            "needs_human": sum(item.state_group == "needs_human" for item in records),
            "blocked": sum(item.state_group == "blocked" for item in records),
            "invalidated": sum(item.state_group == "invalidated" for item in records),
            "completed": sum(item.state_group == "completed" for item in records),
            "portfolio_eligible": sum(item.portfolio_eligible for item in records),
        },
        "records": [item.to_dict() for item in records],
    }
