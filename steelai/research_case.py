from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from steelai.paths import PROCESSED, RESEARCH_CASES, ROOT
from steelai.research_agent import (
    AgentRunResult,
    agent_status,
    execute_readonly_tool,
    run_research_agent,
)


PIPELINE_VERSION = "0.7.0"
PIPELINE_NAME = "SteelAI Research Case Pipeline"
DEFAULT_QUESTION = "为什么R-DQ的低温冲击韧性低于B-DQ？"
CORE_CASE_SAMPLES = frozenset({"B-DQ", "R-DQ"})

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\r\t`\"']+")
_RAW_FILE = re.compile(r"[^\s`\"']+\.(?:ctf|tif|tiff)\b", re.IGNORECASE)
_FORBIDDEN_KEYS = {
    "path",
    "filepath",
    "filename",
    "source_locator",
    "raw_image",
    "raw_data",
    "input_file",
    "output_file",
}


@dataclass(frozen=True)
class ResearchCaseRequest:
    question: str = DEFAULT_QUESTION
    control_id: str = "B-DQ"
    comparison_id: str = "R-DQ"
    use_agent: bool = False

    def validate(self) -> None:
        if not self.question.strip():
            raise ValueError("研究问题不能为空。")
        if self.control_id == self.comparison_id:
            raise ValueError("对照样品和比较样品不能相同。")
        if {self.control_id, self.comparison_id} != CORE_CASE_SAMPLES:
            raise ValueError("v0.7当前只允许B-DQ/R-DQ核心案例；1–14号实验保持排除。")
        if self.use_agent and contains_forbidden_external_content(self.question):
            raise ValueError("研究问题包含本地路径或原始CTF/TIF文件名，不能发送给外部Agent。")


@dataclass
class ResearchCaseResult:
    status: str
    run_id: str
    report: str
    manifest: dict[str, Any]
    report_path: Path
    manifest_path: Path
    snapshot_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "report": self.report,
            "manifest": self.manifest,
            "report_path": str(self.report_path),
            "manifest_path": str(self.manifest_path),
            "snapshot_path": str(self.snapshot_path),
        }


def contains_forbidden_external_content(text: str) -> bool:
    return bool(_ABSOLUTE_PATH.search(text) or _RAW_FILE.search(text))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_directory(directory: Path, pattern: str) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(directory.glob(pattern)):
        if path.is_file():
            rows.append({
                "name": path.name,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            })
    return rows


def _code_snapshot() -> list[dict[str, Any]]:
    names = (
        "research_case.py",
        "research_agent.py",
        "evidence_validation.py",
        "physics.py",
        "analysis.py",
    )
    return [
        {"name": name, "sha256": _sha256(ROOT / "steelai" / name)}
        for name in names
        if (ROOT / "steelai" / name).exists()
    ]


def _privacy_scrub(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if (
                lowered in _FORBIDDEN_KEYS
                or lowered.endswith("_path")
                or lowered.endswith("_filepath")
                or lowered.endswith("_filename")
            ):
                continue
            clean[str(key)] = _privacy_scrub(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_privacy_scrub(item) for item in value]
    if isinstance(value, str):
        text = _ABSOLUTE_PATH.sub("[local-path-redacted]", value)
        return _RAW_FILE.sub("[raw-file-redacted]", text)
    return value


def _stage(
    stages: list[dict[str, Any]],
    stage_id: str,
    label: str,
    function: Callable[[], Any],
) -> Any:
    started = time.perf_counter()
    try:
        output = function()
    except Exception as exc:
        stages.append({
            "stage_id": stage_id,
            "label": label,
            "status": "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "error_type": type(exc).__name__,
        })
        raise
    stages.append({
        "stage_id": stage_id,
        "label": label,
        "status": "completed",
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    })
    return output


def _physics_rows(physics: dict[str, Any]) -> list[str]:
    rows = []
    for sample_id, payload in physics.items():
        values = []
        for item in payload.get("results", []):
            value = item.get("value")
            if value is not None:
                key = item.get("key") or item.get("model_id") or item.get("name")
                values.append(f"{key}={value:g} {item.get('unit', '')}".strip())
        engine = payload.get("engine", "Physics Engine")
        rows.append(f"- **{sample_id}**（{engine}）：" + ("；".join(values) if values else "无可用结果"))
    return rows


def _build_report(
    request: ResearchCaseRequest,
    run_id: str,
    stages: list[dict[str, Any]],
    outputs: dict[str, Any],
    agent_result: AgentRunResult | None,
    data_snapshot: list[dict[str, Any]],
) -> str:
    comparison = outputs["comparison"]
    validation = outputs["validation"]
    lines = [
        "# SteelAI B/R端到端研究任务报告",
        "",
        f"- Run ID: `{run_id}`",
        f"- Pipeline: `{PIPELINE_NAME} v{PIPELINE_VERSION}`",
        f"- 研究问题：{request.question.strip()}",
        f"- 对照 / 比较：`{request.control_id}` / `{request.comparison_id}`",
        f"- 总体就绪度：`{validation.get('overall_readiness', 'unknown')}`",
        f"- 因果推断就绪：`{validation.get('causal_inference_ready', False)}`",
        f"- 机器学习就绪：`{validation.get('machine_learning_ready', False)}`",
        "- 数据范围：仅B-DQ/R-DQ；1–14号实验保持排除",
        "",
        "## 运行状态",
        "",
        "| 阶段 | 状态 | 耗时/ms |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {item['label']} | {item['status']} | {item.get('duration_ms', 0)} |"
        for item in stages
    )

    sections = (
        ("已确认事实", comparison.get("confirmed_facts", [])),
        ("当前判断", comparison.get("judgments", [])),
        ("待验证假设", comparison.get("hypotheses", [])),
        ("下一步行动", comparison.get("next_actions", [])),
        ("局限与提醒", comparison.get("limitations", [])),
    )
    for title, items in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {item}" for item in items) if items else lines.append("- 暂无")

    lines.extend(["", "## Physics Engine经验估算", ""])
    lines.extend(_physics_rows(outputs["physics"]))
    lines.extend([
        "",
        "> 以上均为成分驱动的经验模型估算，不是实验真值。",
        "",
        "## SEM与EBSD证据边界",
        "",
    ])
    low = outputs["ebsd"]["low_resolution"]
    high = outputs["ebsd"]["high_resolution"]
    sem = outputs["autodimple"]
    lines.extend([
        f"- 低分辨率EBSD：{'已有匹配结果' if low.get('available') else '缺失'}；{low.get('boundary', low.get('message', ''))}",
        f"- 高分辨率EBSD：{'已有匹配结果' if high.get('available') else '缺失'}；{high.get('boundary', high.get('message', ''))}",
        f"- AutoDimple：{'已有批量结果' if sem.get('available') else '缺失'}；{sem.get('boundary', sem.get('message', ''))}",
        "- 两个EBSD尺度分别解释，不合并数值；图像、视场和分割对象不作为独立试样重复。",
        "",
        "## 结论验证矩阵",
        "",
    ])
    for claim in validation.get("claims", []):
        lines.extend([
            f"### {claim.get('claim_id')} · {claim.get('claim')}",
            f"- 状态 / 证据等级：`{claim.get('status')}` / `{claim.get('evidence_level')}`",
            f"- 允许表述：{claim.get('allowed_wording')}",
            f"- 禁止表述：{claim.get('prohibited_wording')}",
            f"- 下一步：{claim.get('next_action')}",
            "",
        ])

    lines.extend(["## Research Agent综合", ""])
    if agent_result and agent_result.status == "completed":
        lines.append(_privacy_scrub(agent_result.answer))
    elif request.use_agent and agent_result:
        lines.append(f"- Agent未完成：`{agent_result.status}`。本报告保留确定性离线结果。")
    else:
        lines.append("- 本次未调用外部Agent；报告由确定性Python模块生成。")

    lines.extend(["", "## 可复现性与隐私", ""])
    lines.extend(f"- `{item['name']}`：`{item['sha256'][:16]}…`" for item in data_snapshot)
    lines.extend([
        "- 运行清单记录数据哈希、代码哈希、工具状态、Agent轨迹和科学门控。",
        "- 外部Agent只允许读取已脱敏processed结构化数据与分析摘要。",
        "- 未发送原始图片、CTF/TIF、本地文件路径或论文原文。",
    ])
    return "\n".join(lines).strip() + "\n"


def run_research_case(
    request: ResearchCaseRequest,
    *,
    output_root: Path | None = None,
    agent_runner: Callable[[str], AgentRunResult] | None = None,
) -> ResearchCaseResult:
    request.validate()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = f"BR-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    case_root = (output_root or RESEARCH_CASES) / run_id
    case_root.mkdir(parents=True, exist_ok=False)
    stages: list[dict[str, Any]] = []
    outputs: dict[str, Any] = {}

    data_snapshot = _stage(
        stages,
        "data_snapshot",
        "数据版本与范围检查",
        lambda: _snapshot_directory(PROCESSED, "*.csv"),
    )
    outputs["sample_index"] = _stage(
        stages,
        "sample_check",
        "核心样品完整性检查",
        lambda: execute_readonly_tool("list_samples", {}),
    )
    outputs["comparison"] = _stage(
        stages,
        "deterministic_comparison",
        "确定性B/R结构化对比",
        lambda: execute_readonly_tool("compare_samples", {
            "control_id": request.control_id,
            "comparison_id": request.comparison_id,
        }),
    )
    outputs["physics"] = _stage(
        stages,
        "physics",
        "Physics Engine双样品计算",
        lambda: {
            sample_id: execute_readonly_tool("calculate_physics_card", {"sample_id": sample_id})
            for sample_id in (request.control_id, request.comparison_id)
        },
    )
    outputs["ebsd"] = _stage(
        stages,
        "ebsd",
        "双尺度EBSD结果读取",
        lambda: {
            scale: execute_readonly_tool("get_ebsd_summary", {"scale": scale})
            for scale in ("low_resolution", "high_resolution")
        },
    )
    outputs["autodimple"] = _stage(
        stages,
        "sem_autodimple",
        "AutoDimple批量结果读取",
        lambda: execute_readonly_tool("get_autodimple_summary", {}),
    )
    outputs["validation"] = _stage(
        stages,
        "evidence_validation",
        "证据矩阵与科学门控",
        lambda: execute_readonly_tool("get_evidence_validation_summary", {}),
    )

    agent_result: AgentRunResult | None = None
    if request.use_agent:
        prompt = (
            f"研究任务：{request.question.strip()}\n"
            f"仅比较{request.control_id}与{request.comparison_id}。"
            "请调用只读工具并服从证据验证矩阵；不得请求或输出本地路径、原始图片、CTF/TIF或论文原文。"
        )
        runner = agent_runner or (lambda question: run_research_agent(question, status=agent_status()))
        agent_result = _stage(stages, "agent_synthesis", "Research Agent证据综合", lambda: runner(prompt))
    else:
        stages.append({
            "stage_id": "agent_synthesis",
            "label": "Research Agent证据综合",
            "status": "skipped_by_user",
            "duration_ms": 0.0,
        })

    cleaned_outputs = _privacy_scrub(outputs)
    cleaned_agent = _privacy_scrub(agent_result.to_dict()) if agent_result else {
        "status": "not_requested",
        "tool_trace": [],
    }
    report = _build_report(request, run_id, stages, cleaned_outputs, agent_result, data_snapshot)
    snapshot_path = case_root / "evidence_snapshot.json"
    report_path = case_root / "research_report.md"
    manifest_path = case_root / "run_manifest.json"
    snapshot_path.write_text(
        json.dumps(cleaned_outputs, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    report_path.write_text(report, encoding="utf-8")

    manifest = {
        "schema_version": "1.0",
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "run_id": run_id,
        "status": "completed",
        "created_at": now.isoformat(timespec="seconds"),
        "request": {
            "research_question": request.question.strip(),
            "control_id": request.control_id,
            "comparison_id": request.comparison_id,
            "experiments_1_14_included": False,
        },
        "data_snapshot": data_snapshot,
        "code_snapshot": _code_snapshot(),
        "stages": stages,
        "scientific_readiness": {
            "overall": cleaned_outputs["validation"].get("overall_readiness"),
            "causal_inference_ready": cleaned_outputs["validation"].get("causal_inference_ready"),
            "machine_learning_ready": cleaned_outputs["validation"].get("machine_learning_ready"),
        },
        "agent": cleaned_agent,
        "privacy": {
            "external_provider_allowed": ["de-identified processed structured data", "analysis summaries"],
            "external_provider_prohibited": ["raw images", "CTF/TIF", "local file paths", "thesis text"],
            "raw_files_transmitted": False,
        },
        "artifacts": {
            "report": "research_report.md",
            "evidence_snapshot": "evidence_snapshot.json",
            "manifest": "run_manifest.json",
        },
    }
    manifest = _privacy_scrub(manifest)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return ResearchCaseResult(
        "completed", run_id, report, manifest, report_path, manifest_path, snapshot_path
    )
