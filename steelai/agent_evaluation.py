from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable
from zoneinfo import ZoneInfo

from steelai.governance import digest_value
from steelai.paths import AGENT_EVALUATIONS, ROOT
from steelai.agent_observability import write_observability_artifacts
from steelai.research_agent import AgentRunResult, TOOL_DEFINITIONS, agent_status, run_research_agent


EVALUATION_VERSION = "0.9.0"
BENCHMARK_PATH = ROOT / "config" / "agent_eval_benchmark_v0.1.json"
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\r\t`\"']+")
_RAW_FILENAME = re.compile(r"[^\s`\"']+\.(?:ctf|tif|tiff)\b", re.IGNORECASE)
_WEIGHTS = {
    "status_score": 0.10,
    "tool_score": 0.25,
    "evidence_score": 0.25,
    "guardrail_score": 0.25,
    "privacy_score": 0.15,
}


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    category: str
    title: str
    question: str
    expected_statuses: tuple[str, ...]
    expected_calls: tuple[dict[str, Any], ...]
    required_groups: tuple[tuple[str, ...], ...]
    forbidden_phrases: tuple[str, ...]

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "BenchmarkCase":
        return cls(
            case_id=str(row["case_id"]),
            category=str(row["category"]),
            title=str(row["title"]),
            question=str(row["question"]),
            expected_statuses=tuple(row.get("expected_statuses", ["completed"])),
            expected_calls=tuple(row.get("expected_calls", [])),
            required_groups=tuple(tuple(group) for group in row.get("required_groups", [])),
            forbidden_phrases=tuple(row.get("forbidden_phrases", [])),
        )


@dataclass
class AgentEvaluationResult:
    evaluation_id: str
    status: str
    summary: dict[str, Any]
    rows: list[dict[str, Any]]
    report: str
    result_path: Path
    report_path: Path
    manifest_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "status": self.status,
            "summary": self.summary,
            "rows": self.rows,
            "report": self.report,
            "result_path": str(self.result_path),
            "report_path": str(self.report_path),
            "manifest_path": str(self.manifest_path),
        }


def load_benchmark(path: Path = BENCHMARK_PATH) -> tuple[dict[str, Any], list[BenchmarkCase]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [BenchmarkCase.from_dict(row) for row in data.get("cases", [])]
    return data, cases


def benchmark_contract(path: Path = BENCHMARK_PATH) -> dict[str, Any]:
    data, cases = load_benchmark(path)
    tool_names = {item["name"] for item in TOOL_DEFINITIONS}
    ids = [case.case_id for case in cases]
    unknown_tools = sorted({
        call.get("tool", "")
        for case in cases
        for call in case.expected_calls
        if call.get("tool") not in tool_names
    })
    categories = sorted({case.category for case in cases})
    privacy_cases = [case.case_id for case in cases if case.category == "privacy_and_permission"]
    problems = []
    if len(ids) != len(set(ids)):
        problems.append("case_id不唯一")
    if unknown_tools:
        problems.append("存在未授权工具：" + ", ".join(unknown_tools))
    if len(cases) < 20:
        problems.append("标准问题少于20个")
    if len(privacy_cases) < 3:
        problems.append("隐私与权限案例不足3个")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "benchmark_id": data.get("benchmark_id"),
        "schema_version": data.get("schema_version"),
        "case_count": len(cases),
        "category_count": len(categories),
        "categories": categories,
        "privacy_case_count": len(privacy_cases),
        "authorized_tool_count": len(tool_names),
        "unknown_tools": unknown_tools,
        "benchmark_sha256": digest,
        "status": "passed" if not problems else "failed",
        "problems": problems,
    }


def _call_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if expected.get("tool") != actual.get("tool"):
        return False
    expected_arguments = expected.get("arguments", {})
    if actual.get("arguments_sha256"):
        return actual.get("arguments_sha256") == digest_value(expected_arguments)
    actual_arguments = actual.get("arguments", {})
    return all(actual_arguments.get(key) == value for key, value in expected_arguments.items())


def _score_expected_calls(case: BenchmarkCase, trace: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not case.expected_calls:
        return 1.0, []
    matched = []
    missing = []
    for expected in case.expected_calls:
        if any(_call_matches(expected, actual) for actual in trace):
            matched.append(expected)
        else:
            missing.append(f"{expected.get('tool')}({expected.get('arguments', {})})")
    return len(matched) / len(case.expected_calls), missing


def _score_required_groups(case: BenchmarkCase, answer: str) -> tuple[float, list[list[str]]]:
    if not case.required_groups:
        return 1.0, []
    lowered = answer.lower()
    missing = [list(group) for group in case.required_groups if not any(term.lower() in lowered for term in group)]
    return (len(case.required_groups) - len(missing)) / len(case.required_groups), missing


def _privacy_safe(text: str) -> bool:
    return not (_ABSOLUTE_PATH.search(text) or _RAW_FILENAME.search(text))


def _redact_text(text: str) -> str:
    text = _ABSOLUTE_PATH.sub("[synthetic-local-path-redacted]", text)
    return _RAW_FILENAME.sub("[raw-filename-redacted]", text)


def evaluate_agent_result(
    case: BenchmarkCase,
    result: AgentRunResult,
    *,
    latency_ms: float = 0.0,
    pass_threshold: float = 0.8,
) -> dict[str, Any]:
    answer = str(result.answer or "")
    status_score = 1.0 if result.status in case.expected_statuses else 0.0
    tool_score, missing_calls = _score_expected_calls(case, result.tool_trace)
    evidence_score, missing_groups = _score_required_groups(case, answer)
    forbidden_hits = [term for term in case.forbidden_phrases if term.lower() in answer.lower()]
    guardrail_score = 0.0 if forbidden_hits else 1.0
    privacy_score = 1.0 if _privacy_safe(answer) else 0.0
    scores = {
        "status_score": status_score,
        "tool_score": round(tool_score, 3),
        "evidence_score": round(evidence_score, 3),
        "guardrail_score": guardrail_score,
        "privacy_score": privacy_score,
    }
    overall = sum(scores[name] * weight for name, weight in _WEIGHTS.items())
    passed = overall >= pass_threshold and guardrail_score == 1.0 and privacy_score == 1.0
    usage = getattr(result, "usage", {}) or {}
    return {
        "case_id": case.case_id,
        "category": case.category,
        "title": case.title,
        "question": _redact_text(case.question),
        "status": result.status,
        "model": result.model,
        "passed": passed,
        "overall_score": round(overall, 3),
        **scores,
        "latency_ms": round(latency_ms, 1),
        "tool_count": len(result.tool_trace),
        "tools": [item.get("tool", "") for item in result.tool_trace],
        "tool_trace": [
            {
                "round": item.get("round"),
                "tool": item.get("tool", ""),
                "status": item.get("status", ""),
                "duration_ms": float(item.get("duration_ms", 0.0) or 0.0),
            }
            for item in result.tool_trace
        ],
        "missing_expected_calls": missing_calls,
        "missing_required_groups": missing_groups,
        "forbidden_hits": forbidden_hits,
        "usage": usage,
        "answer": _redact_text(answer),
        "error": _redact_text(str(result.error or "")),
    }


def _aggregate(rows: list[dict[str, Any]], benchmark_id: str, model: str) -> dict[str, Any]:
    score_names = ["overall_score", *_WEIGHTS]
    categories = sorted({row["category"] for row in rows})
    category_scores = {
        category: round(mean(row["overall_score"] for row in rows if row["category"] == category), 3)
        for category in categories
    }
    total_tokens = sum(int(row.get("usage", {}).get("total_tokens", 0) or 0) for row in rows)
    return {
        "benchmark_id": benchmark_id,
        "model": model,
        "case_count": len(rows),
        "passed_count": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 3) if rows else 0.0,
        **{
            f"mean_{name}": round(mean(row[name] for row in rows), 3) if rows else 0.0
            for name in score_names
        },
        "mean_latency_ms": round(mean(row["latency_ms"] for row in rows), 1) if rows else 0.0,
        "total_tokens": total_tokens,
        "category_scores": category_scores,
    }


def evaluation_report_markdown(
    evaluation_id: str,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# SteelAI Research Agent Evaluation Report",
        "",
        f"- Evaluation ID: `{evaluation_id}`",
        f"- Benchmark: `{summary['benchmark_id']}`",
        f"- Model: `{summary['model']}`",
        f"- Cases: {summary['case_count']}",
        f"- Pass rate: {summary['pass_rate'] * 100:.1f}%",
        f"- Mean score: {summary['mean_overall_score'] * 100:.1f}/100",
        f"- Privacy score: {summary['mean_privacy_score'] * 100:.1f}/100",
        f"- Scientific guardrail score: {summary['mean_guardrail_score'] * 100:.1f}/100",
        f"- Mean latency: {summary['mean_latency_ms']:.1f} ms",
        f"- Recorded tokens: {summary['total_tokens']}",
        "",
        "## Category Scores",
        "",
    ]
    lines.extend(f"- {category}: {score * 100:.1f}/100" for category, score in summary["category_scores"].items())
    lines.extend(["", "## Case Results", ""])
    for row in rows:
        lines.extend([
            f"### {row['case_id']} · {row['title']}",
            f"- Result: `{'PASS' if row['passed'] else 'FAIL'}` · score {row['overall_score'] * 100:.1f}/100",
            f"- Status / tools: `{row['status']}` / {', '.join(row['tools']) or 'none'}",
            f"- Scores: tool={row['tool_score']}, evidence={row['evidence_score']}, guardrail={row['guardrail_score']}, privacy={row['privacy_score']}",
            f"- Missing calls: {row['missing_expected_calls'] or 'none'}",
            f"- Missing concepts: {row['missing_required_groups'] or 'none'}",
            f"- Forbidden hits: {row['forbidden_hits'] or 'none'}",
            "",
        ])
    lines.extend([
        "## Interpretation Boundary",
        "",
        "- This benchmark evaluates the current B-DQ/R-DQ tool-grounded workflow, not general intelligence.",
        "- Scores are deterministic contract checks; they do not replace expert review of scientific correctness.",
        "- Experiments 1-14 remain excluded, and no raw images, CTF/TIF, local paths or thesis text are benchmark inputs.",
    ])
    return "\n".join(lines).strip() + "\n"


def run_agent_evaluation(
    case_ids: list[str],
    *,
    runner: Callable[[BenchmarkCase], AgentRunResult] | None = None,
    output_root: Path | None = None,
) -> AgentEvaluationResult:
    benchmark, all_cases = load_benchmark()
    case_map = {case.case_id: case for case in all_cases}
    if not case_ids:
        raise ValueError("至少选择一个评测案例。")
    unknown = [case_id for case_id in case_ids if case_id not in case_map]
    if unknown:
        raise ValueError("未知评测案例：" + ", ".join(unknown))
    selected = [case_map[case_id] for case_id in case_ids]
    current = agent_status()
    if runner is None and not current.ready:
        raise RuntimeError(current.message)
    live_runner = runner or (lambda case: run_research_agent(case.question, status=current))
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    evaluation_id = f"AE-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    evaluation_root = (output_root or AGENT_EVALUATIONS) / evaluation_id
    evaluation_root.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in selected:
        started = time.perf_counter()
        result = live_runner(case)
        latency_ms = (time.perf_counter() - started) * 1000
        rows.append(evaluate_agent_result(
            case,
            result,
            latency_ms=latency_ms,
            pass_threshold=float(benchmark.get("pass_threshold", 0.8)),
        ))
    model = next((row["model"] for row in rows if row.get("model")), current.model)
    summary = _aggregate(rows, str(benchmark["benchmark_id"]), model)
    report = evaluation_report_markdown(evaluation_id, summary, rows)
    result_path = evaluation_root / "evaluation_results.json"
    report_path = evaluation_root / "evaluation_report.md"
    manifest_path = evaluation_root / "evaluation_manifest.json"
    result_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")
    manifest = {
        "schema_version": "1.1",
        "evaluation_version": EVALUATION_VERSION,
        "evaluation_id": evaluation_id,
        "created_at": now.isoformat(timespec="seconds"),
        "status": "completed",
        "benchmark_contract": benchmark_contract(),
        "selected_case_ids": case_ids,
        "summary": summary,
        "scoring_weights": _WEIGHTS,
        "privacy": {
            "raw_files_transmitted": False,
            "prohibited": ["raw images", "CTF/TIF", "local file paths", "thesis text"],
        },
        "artifacts": {
            "results": "evaluation_results.json",
            "report": "evaluation_report.md",
            "manifest": "evaluation_manifest.json",
        },
    }
    manifest["artifacts"].update(write_observability_artifacts(evaluation_root, manifest, rows))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return AgentEvaluationResult(
        evaluation_id, "completed", summary, rows, report, result_path, report_path, manifest_path
    )


def read_latest_evaluation(root: Path = AGENT_EVALUATIONS) -> dict[str, Any]:
    if not root.exists():
        return {}
    manifests = sorted(root.glob("*/evaluation_manifest.json"), reverse=True)
    if not manifests:
        return {}
    try:
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        result_path = manifests[0].parent / "evaluation_results.json"
        report_path = manifests[0].parent / "evaluation_report.md"
        manifest["rows"] = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else []
        manifest["report"] = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        return manifest
    except (OSError, json.JSONDecodeError):
        return {}
