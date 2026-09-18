"""T63 fixed comparison harness for human, single-agent and multi-agent workflows.

The harness freezes tasks and scoring before measurements. It prepares a
measurement sheet and evaluates only records explicitly marked ``measured``.
Instrumentation calibration records prove the schema and report path, but are
excluded from any efficiency or quality advantage conclusion.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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
from steelai.paths import OUTPUTS, ROOT


BENCHMARK_PATH = ROOT / "config" / "agent_workflow_benchmark_v1.0.json"
BENCHMARK_OUTPUTS = OUTPUTS / "agent_workflow_evaluations"
WORKFLOWS = ("human_only", "single_agent", "multi_agent")
MEASUREMENT_KINDS = ("measured", "instrumentation_calibration")
STATUSES = ("completed", "failed", "blocked", "canceled")
TEMPLATE_COLUMNS = (
    "run_group_id", "task_id", "workflow", "repetition", "measurement_kind",
    "started_at", "finished_at", "elapsed_seconds", "status", "passed_checks",
    "critical_errors", "human_revision_count", "input_tokens", "output_tokens",
    "cloud_cost_usd", "present_trace_fields", "runner_identity", "notes",
)


def load_benchmark(path: Path = BENCHMARK_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "T63 benchmark contract is unreadable") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "T63 benchmark contract must be an object")
    return payload


def validate_benchmark(path: Path = BENCHMARK_PATH) -> dict[str, Any]:
    problems: list[str] = []
    payload = load_benchmark(path)
    if payload.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    if payload.get("benchmark_id") != "SteelAI-T63-Agent-Workflow-Benchmark-v1.0":
        problems.append("benchmark_id mismatch")
    if tuple(payload.get("workflows", [])) != WORKFLOWS:
        problems.append("three workflows must be frozen in the declared order")
    if payload.get("repetitions_per_task") != 2:
        problems.append("two repetitions per task are required")
    tasks = payload.get("tasks", [])
    if not isinstance(tasks, list) or len(tasks) != 4:
        problems.append("exactly four fixed tasks are required")
        tasks = []
    categories = {task.get("category") for task in tasks if isinstance(task, Mapping)}
    expected_categories = {"data_check", "statistics_interpretation", "physics_calculation", "report_organization"}
    if categories != expected_categories:
        problems.append("task set must cover the four frozen research categories")
    task_ids: set[str] = set()
    for task in tasks:
        required = {"task_id", "category", "title", "input_version", "goal", "public_input", "required_checks", "critical_errors"}
        if not isinstance(task, Mapping) or set(task) != required:
            problems.append("task fields mismatch")
            continue
        task_id = str(task["task_id"])
        if task_id in task_ids or not task_id.startswith("T63-"):
            problems.append("task IDs must be unique stable T63 identifiers")
        task_ids.add(task_id)
        if not task["required_checks"] or not task["critical_errors"]:
            problems.append(f"{task_id} requires checks and critical errors")
    traces = payload.get("trace_fields_by_workflow", {})
    if set(traces) != set(WORKFLOWS) or any(not traces.get(workflow) for workflow in WORKFLOWS):
        problems.append("trace fields must be defined for every workflow")
    rule = payload.get("decision_rule", {})
    if rule.get("minimum_complete_repetitions") != 2:
        problems.append("decision rule must require two complete repetitions")
    if rule.get("failed_runs_must_be_retained") is not True or rule.get("cost_must_be_reported") is not True:
        problems.append("failure retention and cost reporting must be mandatory")
    privacy = payload.get("privacy", {})
    if privacy.get("raw_prompts_and_answers_in_governance_package") is not False:
        problems.append("raw prompts and answers must not enter governance packages")
    return {
        "schema_version": "1.0",
        "status": "passed" if not problems else "failed",
        "benchmark_id": payload.get("benchmark_id"),
        "contract_sha256": digest_value(payload),
        "task_count": len(tasks),
        "workflow_count": len(payload.get("workflows", [])),
        "required_measurement_count": len(tasks) * len(WORKFLOWS) * int(payload.get("repetitions_per_task", 0)),
        "problems": problems,
    }


def _split_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split("|") if item.strip())
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError("list field must be pipe-delimited text or a sequence")


def _nonnegative_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


@dataclass(frozen=True)
class WorkflowRunRecord:
    run_group_id: str
    task_id: str
    workflow: str
    repetition: int
    measurement_kind: str
    started_at: str
    finished_at: str
    elapsed_seconds: float
    status: str
    passed_checks: tuple[str, ...]
    critical_errors: tuple[str, ...]
    human_revision_count: int
    input_tokens: int
    output_tokens: int
    cloud_cost_usd: float
    present_trace_fields: tuple[str, ...]
    runner_identity: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("passed_checks", "critical_errors", "present_trace_fields"):
            value[key] = list(value[key])
        value["record_sha256"] = digest_value(value)
        return value


def validate_record(raw: Mapping[str, Any], contract: Mapping[str, Any]) -> WorkflowRunRecord:
    task_map = {task["task_id"]: task for task in contract["tasks"]}
    workflow = str(raw.get("workflow", ""))
    task_id = str(raw.get("task_id", ""))
    if workflow not in WORKFLOWS:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "unknown T63 workflow")
    if task_id not in task_map:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "unknown T63 task")
    try:
        repetition = int(raw.get("repetition", 0))
    except (TypeError, ValueError) as exc:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "repetition must be an integer") from exc
    if repetition not in range(1, int(contract["repetitions_per_task"]) + 1):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "repetition is outside the frozen range")
    measurement_kind = str(raw.get("measurement_kind", ""))
    status = str(raw.get("status", ""))
    if measurement_kind not in MEASUREMENT_KINDS or status not in STATUSES:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "measurement_kind or status is invalid")
    started_at = str(raw.get("started_at", ""))
    finished_at = str(raw.get("finished_at", ""))
    if measurement_kind == "measured":
        try:
            started = datetime.fromisoformat(started_at)
            finished = datetime.fromisoformat(finished_at)
        except ValueError as exc:
            raise GovernanceError(
                "GOV-SCHEMA-001", "blocked", "measured records require ISO-8601 timestamps",
            ) from exc
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise GovernanceError(
                "GOV-SCHEMA-001", "blocked", "measured timestamps require timezones and chronological order",
            )
    checks = _split_list(raw.get("passed_checks"))
    errors = _split_list(raw.get("critical_errors"))
    trace_fields = _split_list(raw.get("present_trace_fields"))
    task = task_map[task_id]
    if set(checks) - set(task["required_checks"]):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "run contains an unknown passed check")
    if set(errors) - set(task["critical_errors"]):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "run contains an unknown critical error")
    if set(trace_fields) - set(contract["trace_fields_by_workflow"][workflow]):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "run contains an unknown trace field")
    revisions = int(raw.get("human_revision_count", 0))
    input_tokens = int(raw.get("input_tokens", 0))
    output_tokens = int(raw.get("output_tokens", 0))
    if min(revisions, input_tokens, output_tokens) < 0:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "counts must be nonnegative")
    run_group_id = str(raw.get("run_group_id", "")).strip()
    runner_identity = str(raw.get("runner_identity", "")).strip()
    if not run_group_id or any(char in run_group_id for char in "/\\\r\n\t"):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "run_group_id must be a stable identifier")
    if not runner_identity or any(char in runner_identity for char in "/\\\r\n\t"):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "runner_identity is required")
    return WorkflowRunRecord(
        run_group_id=run_group_id,
        task_id=task_id,
        workflow=workflow,
        repetition=repetition,
        measurement_kind=measurement_kind,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=_nonnegative_number(raw.get("elapsed_seconds", 0), "elapsed_seconds"),
        status=status,
        passed_checks=checks,
        critical_errors=errors,
        human_revision_count=revisions,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cloud_cost_usd=_nonnegative_number(raw.get("cloud_cost_usd", 0), "cloud_cost_usd"),
        present_trace_fields=trace_fields,
        runner_identity=runner_identity,
        notes=str(raw.get("notes", ""))[:500],
    )


def load_measurement_csv(path: Path, contract_path: Path = BENCHMARK_PATH) -> list[WorkflowRunRecord]:
    contract = load_benchmark(contract_path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise GovernanceError("GOV-SOURCE-001", "blocked", "T63 measurement CSV is unavailable") from exc
    if not rows or tuple(rows[0]) != TEMPLATE_COLUMNS:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "T63 measurement CSV columns differ from the frozen template")
    return [validate_record(row, contract) for row in rows]


def _template_rows(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    trace_fields = contract["trace_fields_by_workflow"]
    for task in contract["tasks"]:
        for workflow in WORKFLOWS:
            for repetition in range(1, int(contract["repetitions_per_task"]) + 1):
                rows.append({
                    "run_group_id": "T63-MEASURED-01",
                    "task_id": task["task_id"],
                    "workflow": workflow,
                    "repetition": repetition,
                    "measurement_kind": "measured",
                    "started_at": "",
                    "finished_at": "",
                    "elapsed_seconds": "",
                    "status": "",
                    "passed_checks": "|".join(task["required_checks"]),
                    "critical_errors": "",
                    "human_revision_count": "",
                    "input_tokens": "",
                    "output_tokens": "",
                    "cloud_cost_usd": "",
                    "present_trace_fields": "|".join(trace_fields[workflow]),
                    "runner_identity": "",
                    "notes": "",
                })
    return rows


def _calibration_records(contract: Mapping[str, Any]) -> list[WorkflowRunRecord]:
    records: list[WorkflowRunRecord] = []
    for task in contract["tasks"]:
        for workflow in WORKFLOWS:
            records.append(validate_record({
                "run_group_id": "T63-INSTRUMENTATION-CALIBRATION",
                "task_id": task["task_id"],
                "workflow": workflow,
                "repetition": 1,
                "measurement_kind": "instrumentation_calibration",
                "started_at": "not_measured",
                "finished_at": "not_measured",
                "elapsed_seconds": 0,
                "status": "completed",
                "passed_checks": task["required_checks"],
                "critical_errors": [],
                "human_revision_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cloud_cost_usd": 0,
                "present_trace_fields": contract["trace_fields_by_workflow"][workflow],
                "runner_identity": "instrumentation-self-check",
                "notes": "Schema calibration only; excluded from workflow advantage conclusions.",
            }, contract))
    return records


def evaluate_records(records: Sequence[WorkflowRunRecord], contract: Mapping[str, Any]) -> dict[str, Any]:
    measured = [record for record in records if record.measurement_kind == "measured"]
    required_keys = {
        (task["task_id"], workflow, repetition)
        for task in contract["tasks"]
        for workflow in WORKFLOWS
        for repetition in range(1, int(contract["repetitions_per_task"]) + 1)
    }
    observed_keys = [(record.task_id, record.workflow, record.repetition) for record in measured]
    duplicates = len(observed_keys) != len(set(observed_keys))
    missing = sorted(required_keys - set(observed_keys))
    extra = sorted(set(observed_keys) - required_keys)
    task_map = {task["task_id"]: task for task in contract["tasks"]}
    rows: list[dict[str, Any]] = []
    for workflow in WORKFLOWS:
        subset = [record for record in measured if record.workflow == workflow]
        completed = [
            record for record in subset
            if record.status == "completed" and set(record.passed_checks) == set(task_map[record.task_id]["required_checks"])
            and not record.critical_errors
        ]
        trace_values = [
            len(set(record.present_trace_fields)) / len(contract["trace_fields_by_workflow"][workflow])
            for record in subset
        ]
        elapsed = [record.elapsed_seconds for record in subset]
        rows.append({
            "workflow": workflow,
            "measured_run_count": len(subset),
            "completion_rate": len(completed) / len(subset) if subset else None,
            "critical_error_count": sum(len(record.critical_errors) for record in subset),
            "mean_human_revisions": statistics.fmean(record.human_revision_count for record in subset) if subset else None,
            "median_elapsed_seconds": statistics.median(elapsed) if elapsed else None,
            "input_tokens": sum(record.input_tokens for record in subset),
            "output_tokens": sum(record.output_tokens for record in subset),
            "cloud_cost_usd": sum(record.cloud_cost_usd for record in subset),
            "trace_completeness": statistics.fmean(trace_values) if trace_values else None,
            "failed_or_blocked_runs": sum(record.status in {"failed", "blocked", "canceled"} for record in subset),
        })
    complete = not missing and not extra and not duplicates
    conclusion = "insufficient_evidence"
    advantages: dict[str, bool] = {"single_agent": False, "multi_agent": False}
    if complete:
        baseline = next(row for row in rows if row["workflow"] == "human_only")
        for workflow in ("single_agent", "multi_agent"):
            row = next(item for item in rows if item["workflow"] == workflow)
            advantages[workflow] = bool(
                row["completion_rate"] >= baseline["completion_rate"]
                and row["critical_error_count"] <= baseline["critical_error_count"]
                and row["trace_completeness"] >= baseline["trace_completeness"]
                and (
                    row["median_elapsed_seconds"] <= baseline["median_elapsed_seconds"] * 0.9
                    or row["mean_human_revisions"] <= baseline["mean_human_revisions"] - 0.5
                )
            )
        if advantages["single_agent"] and advantages["multi_agent"]:
            conclusion = "both_agent_workflows_meet_frozen_advantage_rule"
        elif advantages["multi_agent"]:
            conclusion = "multi_agent_meets_frozen_advantage_rule"
        elif advantages["single_agent"]:
            conclusion = "single_agent_meets_frozen_advantage_rule"
        else:
            conclusion = "no_agent_workflow_advantage_detected"
    return {
        "schema_version": "1.0",
        "benchmark_id": contract["benchmark_id"],
        "measured_record_count": len(measured),
        "required_record_count": len(required_keys),
        "coverage_complete": complete,
        "duplicates_present": duplicates,
        "missing_measurements": [list(item) for item in missing],
        "unexpected_measurements": [list(item) for item in extra],
        "workflow_results": rows,
        "advantage_rule_results": advantages,
        "conclusion": conclusion,
        "calibration_records_excluded": sum(record.measurement_kind != "measured" for record in records),
    }


def _report(result: Mapping[str, Any]) -> str:
    lines = [
        "# T63 人工与智能体流程评估",
        "",
        "## 当前结论",
        "",
    ]
    if result["conclusion"] == "insufficient_evidence":
        lines.append(
            f"当前只有评测结构校准记录，真实测量为 {result['measured_record_count']} / {result['required_record_count']}。"
            "因此不能声称单智能体或多智能体提高了效率、质量或可控性。"
        )
    else:
        lines.append(f"固定判定结果为 `{result['conclusion']}`。该判断只适用于本任务集和本次记录。")
    lines.extend([
        "",
        "## 固定比较范围",
        "",
        "同一任务集覆盖数据检查、统计解释、Physics 输入判断和证据约束报告整理。"
        "人工、单智能体和多智能体各运行两次；任务、输入版本、目标、检查项和关键错误在运行前冻结。",
        "",
        "## 对照结果",
        "",
        "| 流程 | 实测数 | 完成率 | 关键错误 | 平均人工修订 | 中位耗时秒 | Token | 云端费用美元 | 追溯完整率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in result["workflow_results"]:
        def show(value: Any, digits: int = 3) -> str:
            return "待测" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)
        lines.append(
            f"| {row['workflow']} | {row['measured_run_count']} | {show(row['completion_rate'])} | "
            f"{row['critical_error_count']} | {show(row['mean_human_revisions'])} | "
            f"{show(row['median_elapsed_seconds'])} | {row['input_tokens'] + row['output_tokens']} | "
            f"{row['cloud_cost_usd']:.6f} | {show(row['trace_completeness'])} |"
        )
    lines.extend([
        "",
        "## 结论边界",
        "",
        "校准记录只证明表结构、评分和报告能够运行，不代表人工或智能体的真实表现。"
        "失败、阻断和取消记录必须保留。只有 24 条真实记录完整覆盖三种流程后，系统才执行冻结优势判定。",
        "",
        "任何优势结论都必须同时满足完成率、关键错误、追溯完整率以及耗时或人工修订门槛。"
        "Token 和费用只描述成本，不单独证明质量。",
    ])
    return "\n".join(lines).strip() + "\n"


def _write_template(path: Path, contract: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        writer.writerows(_template_rows(contract))


def _write_comparison(path: Path, result: Mapping[str, Any]) -> None:
    rows = result["workflow_results"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def publish_benchmark_package(
    records: Sequence[WorkflowRunRecord] | None = None,
    *,
    output_root: Path = BENCHMARK_OUTPUTS,
    contract_path: Path = BENCHMARK_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validation = validate_benchmark(contract_path)
    if validation["status"] != "passed":
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "T63 benchmark contract failed validation")
    contract = load_benchmark(contract_path)
    current_records = list(records) if records is not None else _calibration_records(contract)
    result = evaluate_records(current_records, contract)
    seed = {
        "benchmark_id": contract["benchmark_id"],
        "contract_sha256": validation["contract_sha256"],
        "records_sha256": digest_value([record.to_dict() for record in current_records]),
        "result_sha256": digest_value(result),
    }
    digest = digest_value(seed)
    publication_id = "T63-EVAL-" + digest[:20].upper()
    destination = output_root.resolve() / publication_id
    if destination.exists():
        verification = verify_package(destination)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing T63 package is invalidated")
        return {
            "status": "needs_human" if result["conclusion"] == "insufficient_evidence" else "passed",
            "publication_id": publication_id,
            "package": str(destination),
            "reused": True,
            "manifest_sha256": verification.manifest_digest,
            "evaluation": result,
        }
    timestamp = generated_at or utc_now()
    identity = ResearchObjectIdentity(
        object_type="agent_workflow_evaluation",
        object_id=publication_id,
        revision=1,
        content_digest=digest,
        created_at=timestamp,
        created_by="steelai.agent_workflow_benchmark",
    )
    sources = (
        SourceReference(
            source_id="T63-FIXED-TASK-SET",
            source_revision=1,
            source_digest=validation["contract_sha256"],
            evidence_class=EvidenceClass.SYNTHETIC_DEMO_DATA.value,
            source_status="public_and_synthetic_frozen_benchmark",
        ),
    )
    stage = create_staging_directory(output_root, publication_id)
    try:
        write_json_atomic(stage / "benchmark_contract.json", contract)
        with (stage / "raw_run_records.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in current_records:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        _write_template(stage / "measurement_template.csv", contract)
        _write_comparison(stage / "comparison_results.csv", result)
        write_json_atomic(stage / "evaluation_result.json", result)
        (stage / "evaluation_report.md").write_text(_report(result), encoding="utf-8")
        manifest = build_manifest(
            stage,
            publication_id=publication_id,
            identity=identity,
            state="needs_human" if result["conclusion"] == "insufficient_evidence" else "passed",
            result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=sources,
            generated_by="steelai.agent_workflow_benchmark",
            generated_at=timestamp,
            metadata={
                "feature": "T63",
                "measured_record_count": result["measured_record_count"],
                "required_record_count": result["required_record_count"],
                "failed_runs_retained": True,
                "calibration_excluded_from_advantage": True,
                "human_review_required": True,
                "portfolio_eligible": False,
            },
        )
        seal_package(stage, manifest)
        publication = publish_append_only(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "status": "needs_human" if result["conclusion"] == "insufficient_evidence" else "passed",
        "publication_id": publication_id,
        "package": publication.destination,
        "reused": publication.reused,
        "manifest_sha256": publication.manifest_digest,
        "evaluation": result,
    }


def latest_evaluation(output_root: Path = BENCHMARK_OUTPUTS) -> dict[str, Any] | None:
    if not output_root.is_dir():
        return None
    packages = sorted((path for path in output_root.glob("T63-EVAL-*") if path.is_dir()), reverse=True)
    for package in packages:
        if verify_package(package).status != "passed":
            continue
        try:
            result = json.loads((package / "evaluation_result.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return {
            "publication_id": package.name,
            "status": "needs_human" if result["conclusion"] == "insufficient_evidence" else "passed",
            "evaluation": result,
            "measurement_template": f"outputs/agent_workflow_evaluations/{package.name}/measurement_template.csv",
            "report": f"outputs/agent_workflow_evaluations/{package.name}/evaluation_report.md",
        }
    return None


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or evaluate the fixed T63 workflow benchmark")
    parser.add_argument("--records", type=Path, help="completed measurement CSV; omit to prepare the benchmark")
    parser.add_argument("--output-root", type=Path, default=BENCHMARK_OUTPUTS)
    parser.add_argument("--validate-contract", action="store_true")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if arguments.validate_contract:
            result = validate_benchmark()
        else:
            records = load_measurement_csv(arguments.records) if arguments.records else None
            result = publish_benchmark_package(records, output_root=arguments.output_root)
    except (GovernanceError, ValueError) as exc:
        payload = exc.to_dict() if isinstance(exc, GovernanceError) else {"status": "blocked", "message": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"passed", "needs_human"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
