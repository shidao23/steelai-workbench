from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from steelai.paths import AGENT_EVALUATIONS


TRACE_SCHEMA_VERSION = "1.0"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_evaluation_run(evaluation_id: str, root: Path = AGENT_EVALUATIONS) -> dict[str, Any]:
    run_root = root / Path(evaluation_id).name
    manifest = _read_json(run_root / "evaluation_manifest.json", {})
    if not manifest:
        return {}
    manifest["rows"] = _read_json(run_root / "evaluation_results.json", [])
    manifest["report"] = (run_root / "evaluation_report.md").read_text(encoding="utf-8") \
        if (run_root / "evaluation_report.md").exists() else ""
    return manifest


def read_evaluation_history(root: Path = AGENT_EVALUATIONS) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    history = []
    for manifest_path in root.glob("*/evaluation_manifest.json"):
        manifest = _read_json(manifest_path, {})
        summary = manifest.get("summary", {})
        if not manifest or not summary:
            continue
        history.append({
            "evaluation_id": manifest.get("evaluation_id", manifest_path.parent.name),
            "created_at": manifest.get("created_at", ""),
            "model": summary.get("model", ""),
            "case_count": int(summary.get("case_count", 0) or 0),
            "passed_count": int(summary.get("passed_count", 0) or 0),
            "pass_rate": float(summary.get("pass_rate", 0.0) or 0.0),
            "mean_overall_score": float(summary.get("mean_overall_score", 0.0) or 0.0),
            "mean_guardrail_score": float(summary.get("mean_guardrail_score", 0.0) or 0.0),
            "mean_privacy_score": float(summary.get("mean_privacy_score", 0.0) or 0.0),
            "mean_latency_ms": float(summary.get("mean_latency_ms", 0.0) or 0.0),
            "total_tokens": int(summary.get("total_tokens", 0) or 0),
            "selected_case_ids": manifest.get("selected_case_ids", []),
        })
    return sorted(history, key=lambda row: (row["created_at"], row["evaluation_id"]), reverse=True)


def compare_evaluation_runs(
    baseline_id: str,
    candidate_id: str,
    root: Path = AGENT_EVALUATIONS,
) -> dict[str, Any]:
    baseline = load_evaluation_run(baseline_id, root)
    candidate = load_evaluation_run(candidate_id, root)
    if not baseline or not candidate:
        raise ValueError("评测运行不存在或产物不完整。")
    baseline_rows = {row["case_id"]: row for row in baseline.get("rows", [])}
    candidate_rows = {row["case_id"]: row for row in candidate.get("rows", [])}
    common_ids = sorted(set(baseline_rows) & set(candidate_rows))
    rows = []
    for case_id in common_ids:
        left = baseline_rows[case_id]
        right = candidate_rows[case_id]
        delta = float(right.get("overall_score", 0.0)) - float(left.get("overall_score", 0.0))
        if bool(left.get("passed")) and not bool(right.get("passed")):
            status = "regression"
        elif not bool(left.get("passed")) and bool(right.get("passed")):
            status = "improvement"
        elif delta < -0.001:
            status = "regression"
        elif delta > 0.001:
            status = "improvement"
        else:
            status = "stable"
        rows.append({
            "case_id": case_id,
            "title": right.get("title", left.get("title", "")),
            "baseline_passed": bool(left.get("passed")),
            "candidate_passed": bool(right.get("passed")),
            "baseline_score": float(left.get("overall_score", 0.0)),
            "candidate_score": float(right.get("overall_score", 0.0)),
            "score_delta": round(delta, 3),
            "latency_delta_ms": round(
                float(right.get("latency_ms", 0.0)) - float(left.get("latency_ms", 0.0)), 1
            ),
            "status": status,
        })
    left_summary = baseline.get("summary", {})
    right_summary = candidate.get("summary", {})
    return {
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "common_case_count": len(common_ids),
        "regression_count": sum(row["status"] == "regression" for row in rows),
        "improvement_count": sum(row["status"] == "improvement" for row in rows),
        "score_delta": round(
            float(right_summary.get("mean_overall_score", 0.0))
            - float(left_summary.get("mean_overall_score", 0.0)), 3
        ),
        "pass_rate_delta": round(
            float(right_summary.get("pass_rate", 0.0))
            - float(left_summary.get("pass_rate", 0.0)), 3
        ),
        "latency_delta_ms": round(
            float(right_summary.get("mean_latency_ms", 0.0))
            - float(left_summary.get("mean_latency_ms", 0.0)), 1
        ),
        "token_delta": int(right_summary.get("total_tokens", 0) or 0)
        - int(left_summary.get("total_tokens", 0) or 0),
        "rows": rows,
    }


def _stable_id(*parts: str, length: int) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:length]


def build_trace_records(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evaluation_id = str(manifest.get("evaluation_id", "unknown"))
    created_at = str(manifest.get("created_at", ""))
    records = []
    for row in rows:
        case_id = str(row.get("case_id", "unknown"))
        trace_id = _stable_id(evaluation_id, case_id, length=32)
        root_span_id = _stable_id(evaluation_id, case_id, "root", length=16)
        records.append({
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": trace_id,
            "span_id": root_span_id,
            "parent_span_id": "",
            "name": "steelai.agent_evaluation.case",
            "kind": "agent",
            "created_at": created_at,
            "duration_ms": float(row.get("latency_ms", 0.0) or 0.0),
            "status": "ok" if row.get("passed") else "error",
            "attributes": {
                "evaluation_id": evaluation_id,
                "case_id": case_id,
                "category": row.get("category", ""),
                "model": row.get("model", ""),
                "score": row.get("overall_score", 0.0),
                "passed": bool(row.get("passed")),
                "total_tokens": int(row.get("usage", {}).get("total_tokens", 0) or 0),
            },
        })
        tool_trace = row.get("tool_trace", []) or [
            {"tool": name, "status": "completed", "round": None}
            for name in row.get("tools", [])
        ]
        for index, item in enumerate(tool_trace, start=1):
            records.append({
                "schema_version": TRACE_SCHEMA_VERSION,
                "trace_id": trace_id,
                "span_id": _stable_id(evaluation_id, case_id, str(index), length=16),
                "parent_span_id": root_span_id,
                "name": f"steelai.tool.{item.get('tool', 'unknown')}",
                "kind": "tool",
                "created_at": created_at,
                "duration_ms": float(item.get("duration_ms", 0.0) or 0.0),
                "status": "ok" if item.get("status") == "completed" else "error",
                "attributes": {
                    "evaluation_id": evaluation_id,
                    "case_id": case_id,
                    "round": item.get("round"),
                    "sequence": index,
                },
            })
    return records


def write_observability_artifacts(
    run_root: Path,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    records = build_trace_records(manifest, rows)
    trace_path = run_root / "trace_spans.jsonl"
    trace_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    summary = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "evaluation_id": manifest.get("evaluation_id"),
        "trace_count": len(rows),
        "span_count": len(records),
        "privacy": {
            "contains_answers": False,
            "contains_questions": False,
            "contains_tool_arguments": False,
            "contains_local_paths": False,
            "contains_raw_files": False,
        },
        "integration_note": "Portable sanitized spans for a later MLflow/OpenTelemetry adapter.",
    }
    summary_path = run_root / "observability_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "trace_spans": trace_path.name,
        "observability_summary": summary_path.name,
    }
