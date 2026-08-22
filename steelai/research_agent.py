from __future__ import annotations

import importlib.util
import json
import os
import re
import time
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from steelai.analysis import build_rule_report
from steelai.automation import AUTODIMPLE_RESULT_ROOT
from steelai.data import numeric, read_rows, sample_bundle
from steelai.ebsd import read_highres_comparison, read_matched_comparison
from steelai.evidence_validation import agent_validation_payload
from steelai.physics import calculate_all
from steelai.settings import load_settings
from steelai.v01_adapter import evaluate as evaluate_v01
from steelai.v01_adapter import is_available as v01_available


AGENT_NAME = "SteelAI Research Agent v0.2"
_ABSOLUTE_PATH_INPUT = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\r\t`\"']+")
_RAW_FILENAME_INPUT = re.compile(r"[^\s`\"']+\.(?:ctf|tif|tiff)\b", re.IGNORECASE)

AGENT_INSTRUCTIONS = """
You are the read-only research coordinator for a wear-resistant steel project.
Use only the provided tools and their structured results. Never invent measurements,
citations, observations, or file contents. Never treat a model estimate as an
experimental measurement. Never turn correlation into causation. EBSD results from
different acquisition scales must not be pooled. Multiple fields from one specimen
are not independent specimen replicates. FCC indexing is not automatically validated
retained austenite, and 3-degree orientation grains are not automatically martensite
blocks, packets, or prior-austenite grains.

Answer in Chinese and use exactly these headings when evidence permits:
## 已确认事实
## 当前判断
## 待验证假设
## 证据与局限
## 下一步行动

Every factual statement must name the tool result or sample identifier that supports
it. If evidence is missing, say that it is insufficient. Do not request or expose raw
file paths. Do not claim that you modified data or ran MATLAB/GPU jobs: all available
tools are read-only. When assessing evidence strength or mechanism claims, call
get_evidence_validation_summary and obey its allowed/prohibited wording and gates.
Keep the answer concise and scientifically cautious.
""".strip()


@dataclass(frozen=True)
class AgentStatus:
    state: str
    enabled: bool
    api_key_present: bool
    package_present: bool
    model: str
    reasoning_effort: str
    max_tool_calls: int
    max_rounds: int
    message: str
    package_version: str = ""
    provider: str = "openai"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "online_ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "enabled": self.enabled,
            "api_key_present": self.api_key_present,
            "package_present": self.package_present,
            "package_version": self.package_version,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "max_tool_calls": self.max_tool_calls,
            "max_rounds": self.max_rounds,
            "message": self.message,
            "provider": self.provider,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
        }


@dataclass
class AgentRunResult:
    status: str
    answer: str
    model: str
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    response_id: str = ""
    error: str = ""
    usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "model": self.model,
            "tool_trace": self.tool_trace,
            "response_id": self.response_id,
            "error": self.error,
            "usage": self.usage,
        }


def _usage_snapshot(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    input_tokens = getattr(usage, "input_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "prompt_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "completion_tokens", 0)
    total_tokens = getattr(usage, "total_tokens", None)
    if total_tokens is None:
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
    return {
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
    }


def _merge_usage(total: dict[str, int], current: dict[str, int]) -> None:
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + current.get(key, 0)


def agent_status() -> AgentStatus:
    settings = load_settings().get("ai", {})
    enabled = bool(settings.get("enabled", False))
    provider = str(os.getenv("STEELAI_AI_PROVIDER") or settings.get("provider", "openai")).lower()
    if provider == "deepseek":
        default_model = "deepseek-v4-flash"
        model_override = os.getenv("DEEPSEEK_MODEL")
        default_key_env = "DEEPSEEK_API_KEY"
        default_base_url = "https://api.deepseek.com/beta"
    else:
        provider = "openai"
        default_model = "gpt-5.6-luna"
        model_override = os.getenv("OPENAI_MODEL")
        default_key_env = "OPENAI_API_KEY"
        default_base_url = ""
    model = str(model_override or settings.get("model", default_model))
    api_key_env = str(settings.get("api_key_env", default_key_env))
    base_url = str(settings.get("base_url", default_base_url))
    effort = str(settings.get("reasoning_effort", "low"))
    max_tool_calls = int(settings.get("max_tool_calls", 6))
    max_rounds = int(settings.get("max_rounds", 4))
    package_present = importlib.util.find_spec("openai") is not None
    api_key_present = bool(os.getenv(api_key_env))
    try:
        package_version = metadata.version("openai") if package_present else ""
    except metadata.PackageNotFoundError:
        package_version = ""

    if not enabled:
        state, message = "disabled", "Agent已在项目配置中关闭。"
    elif not package_present:
        state, message = "offline_missing_package", "未安装openai程序包，Agent保持离线。"
    elif not api_key_present:
        state, message = "offline_missing_key", f"尚未配置{api_key_env}，Agent保持离线。"
    else:
        state, message = "online_ready", f"Agent已连接{provider}，可调用只读科研工具。"
    return AgentStatus(
        state, enabled, api_key_present, package_present, model, effort,
        max_tool_calls, max_rounds, message, package_version,
        provider, api_key_env, base_url,
    )


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_samples",
        "description": "List processed sample IDs and table completeness. Returns structured metadata only; never raw files.",
        "parameters": _empty_schema(),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_sample_bundle",
        "description": "Read the processed composition, process, microstructure and properties rows for one sample. Returns evidence table names and structured fields.",
        "parameters": {
            "type": "object",
            "properties": {"sample_id": {"type": "string", "description": "Exact sample ID returned by list_samples."}},
            "required": ["sample_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "compare_samples",
        "description": "Build the deterministic evidence-bounded comparison of two processed samples. Returns facts, judgments, hypotheses, actions and limitations separately.",
        "parameters": {
            "type": "object",
            "properties": {
                "control_id": {"type": "string", "description": "Control sample ID."},
                "comparison_id": {"type": "string", "description": "Comparison sample ID."},
            },
            "required": ["control_id", "comparison_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "calculate_physics_card",
        "description": "Calculate empirical Ms, Ac1, Ac3, Tnr, Ceq and Pcm estimates from one processed composition. Results include formula source, review status and warnings; all values are model estimates.",
        "parameters": {
            "type": "object",
            "properties": {"sample_id": {"type": "string", "description": "Exact sample ID."}},
            "required": ["sample_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_ebsd_summary",
        "description": "Read an existing acquisition-matched B/R EBSD comparison. Low- and high-resolution groups remain separate and must never be pooled.",
        "parameters": {
            "type": "object",
            "properties": {
                "scale": {
                    "type": "string",
                    "enum": ["low_resolution", "high_resolution"],
                    "description": "Use low_resolution for about 1000x/0.5 um or high_resolution for about 2000x/0.15 um.",
                }
            },
            "required": ["scale"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_autodimple_summary",
        "description": "Read the existing B/R AutoDimple comparison and its image-level interpretation boundary. Does not run segmentation.",
        "parameters": _empty_schema(),
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_evidence_validation_summary",
        "description": "Read the deterministic B/R evidence registry, claim validation matrix and scientific gates. Contains no raw paths or original files.",
        "parameters": _empty_schema(),
        "strict": True,
    },
]


def _require_sample(sample_id: str) -> dict[str, dict[str, str]]:
    bundle = sample_bundle(sample_id)
    if not bundle.get("samples"):
        raise ValueError(f"Unknown sample_id: {sample_id}")
    return bundle


def _sanitize_for_model(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_for_model(item)
            for key, item in value.items()
            if "path" not in key.lower() and "file" not in key.lower()
        }
    if isinstance(value, list):
        return [_sanitize_for_model(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_model(item) for item in value]
    return value


def _list_samples() -> dict[str, Any]:
    tables = ("samples", "composition", "process", "microstructure", "properties")
    result = []
    for row in read_rows("samples"):
        sample_id = row.get("sample_id", "")
        bundle = sample_bundle(sample_id)
        result.append({
            "sample_id": sample_id,
            "steel": row.get("steel", ""),
            "condition": row.get("condition", ""),
            "data_status": row.get("data_status", ""),
            "tables_present": [name for name in tables if bool(bundle.get(name))],
            "tables_missing": [name for name in tables if not bundle.get(name)],
        })
    return {"samples": result, "count": len(result), "source": "data/processed/*.csv"}


def _get_sample_bundle(sample_id: str) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "data": _sanitize_for_model(_require_sample(sample_id)),
        "evidence": [
            "data/processed/samples.csv",
            "data/processed/composition.csv",
            "data/processed/process.csv",
            "data/processed/microstructure.csv",
            "data/processed/properties.csv",
        ],
    }


def _compare_samples(control_id: str, comparison_id: str) -> dict[str, Any]:
    report = build_rule_report(_require_sample(control_id), _require_sample(comparison_id))
    payload = report.to_dict()
    payload.pop("narrative", None)
    payload["evidence"] = {"control": control_id, "comparison": comparison_id, "method": "offline_rules"}
    return payload


def _calculate_physics_card(sample_id: str) -> dict[str, Any]:
    bundle = _require_sample(sample_id)
    steel_id = bundle["samples"].get("steel", "")
    if steel_id in {"B", "R"} and v01_available():
        rows, _composition, _metadata = evaluate_v01(steel_id)
        return {
            "sample_id": sample_id,
            "engine": "WearSteel-AI-v0.1",
            "model_count": len(rows),
            "result_type": "empirical_model_estimates_not_experimental_truth",
            "results": _sanitize_for_model(rows),
            "evidence": "processed composition linked by steel ID",
        }
    composition_row = bundle["composition"]
    composition = {
        key: number
        for key, raw in composition_row.items()
        if key not in {"sample_id", "source_status"} and (number := numeric(raw)) is not None
    }
    results = [item.to_dict() for item in calculate_all(composition, set(composition))]
    return {
        "sample_id": sample_id,
        "engine": "SteelAI built-in fallback",
        "model_count": len(results),
        "result_type": "empirical_model_estimates_not_experimental_truth",
        "results": results,
        "evidence": "data/processed/composition.csv",
    }


def _get_ebsd_summary(scale: str) -> dict[str, Any]:
    if scale == "low_resolution":
        data = read_matched_comparison()
        acquisition = "about 1000x / 0.5 um"
    elif scale == "high_resolution":
        data = read_highres_comparison()
        acquisition = "about 2000x / 0.15 um"
    else:
        raise ValueError(f"Unsupported EBSD scale: {scale}")
    if not data:
        return {"scale": scale, "available": False, "message": "No completed comparison is available."}
    return {
        "scale": scale,
        "acquisition_group": acquisition,
        "available": True,
        "comparison": _sanitize_for_model(data),
        "boundary": "One EBSD field per condition is directional evidence, not an independent specimen-level inference.",
    }


def _get_autodimple_summary() -> dict[str, Any]:
    manifest_path = AUTODIMPLE_RESULT_ROOT / "batch_manifest_v0.1.json"
    comparison_path = AUTODIMPLE_RESULT_ROOT / "br_comparison_v0.1.json"
    if not manifest_path.exists() or not comparison_path.exists():
        return {"available": False, "message": "No completed AutoDimple comparison is available."}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "standard_id": manifest.get("standard_id"),
        "image_count": manifest.get("image_count"),
        "status": manifest.get("status"),
        "comparison": _sanitize_for_model(comparison),
        "boundary": "Image-level bootstrap is descriptive; fields and segmented objects are not independent specimen replicates.",
    }


TOOL_FUNCTIONS = {
    "list_samples": _list_samples,
    "get_sample_bundle": _get_sample_bundle,
    "compare_samples": _compare_samples,
    "calculate_physics_card": _calculate_physics_card,
    "get_ebsd_summary": _get_ebsd_summary,
    "get_autodimple_summary": _get_autodimple_summary,
    "get_evidence_validation_summary": agent_validation_payload,
}


def execute_readonly_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ValueError(f"Unknown or non-whitelisted tool: {name}")
    return _sanitize_for_model(function(**arguments))


def _deepseek_chat_tools() -> list[dict[str, Any]]:
    """Convert Responses tools to DeepSeek's OpenAI-compatible Chat tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
                "strict": item["strict"],
            },
        }
        for item in TOOL_DEFINITIONS
    ]


def _run_deepseek_agent(question: str, client: Any, current: AgentStatus) -> AgentRunResult:
    messages: list[Any] = [
        {"role": "system", "content": AGENT_INSTRUCTIONS},
        {"role": "user", "content": question},
    ]
    trace: list[dict[str, Any]] = []
    total_calls = 0
    last_response_id = ""
    usage_total: dict[str, int] = {}
    try:
        for round_number in range(1, current.max_rounds + 1):
            response = client.chat.completions.create(
                model=current.model,
                messages=messages,
                tools=_deepseek_chat_tools(),
                tool_choice="auto",
                parallel_tool_calls=False,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
            _merge_usage(usage_total, _usage_snapshot(response))
            last_response_id = str(getattr(response, "id", ""))
            message = response.choices[0].message
            messages.append(message)
            calls = list(getattr(message, "tool_calls", None) or [])
            if not calls:
                answer = str(getattr(message, "content", "") or "").strip()
                if not answer:
                    return AgentRunResult("failed", "", current.model, trace, last_response_id, "模型未返回文本结果。", usage_total)
                return AgentRunResult("completed", answer, current.model, trace, last_response_id, usage=usage_total)

            for call in calls:
                total_calls += 1
                if total_calls > current.max_tool_calls:
                    return AgentRunResult(
                        "limit_reached", "", current.model, trace, last_response_id,
                        f"超过只读工具调用上限（{current.max_tool_calls}次）。",
                        usage_total,
                    )
                name = str(getattr(call.function, "name", ""))
                raw_arguments = str(getattr(call.function, "arguments", "{}"))
                tool_started = time.perf_counter()
                try:
                    arguments = json.loads(raw_arguments)
                    tool_result = execute_readonly_tool(name, arguments)
                    trace.append({
                        "round": round_number,
                        "tool": name,
                        "arguments": arguments,
                        "status": "completed",
                        "duration_ms": round((time.perf_counter() - tool_started) * 1000, 1),
                    })
                    output_text = json.dumps(tool_result, ensure_ascii=False, allow_nan=False)
                except Exception as exc:
                    trace.append({
                        "round": round_number,
                        "tool": name,
                        "arguments": raw_arguments,
                        "status": "failed",
                        "error": type(exc).__name__,
                        "duration_ms": round((time.perf_counter() - tool_started) * 1000, 1),
                    })
                    output_text = json.dumps({
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(getattr(call, "id", "")),
                    "content": output_text,
                })
        return AgentRunResult(
            "limit_reached", "", current.model, trace, last_response_id,
            f"超过Agent轮次上限（{current.max_rounds}轮）。",
            usage_total,
        )
    except Exception as exc:
        return AgentRunResult(
            "failed", "", current.model, trace, last_response_id,
            f"{type(exc).__name__}: {exc}",
            usage_total,
        )


def run_research_agent(
    question: str,
    *,
    client: Any | None = None,
    status: AgentStatus | None = None,
) -> AgentRunResult:
    question = question.strip()
    current = status or agent_status()
    if not question:
        return AgentRunResult("invalid_input", "", current.model, error="问题不能为空。")
    if _ABSOLUTE_PATH_INPUT.search(question) or _RAW_FILENAME_INPUT.search(question):
        return AgentRunResult(
            "invalid_input",
            "",
            current.model,
            error="输入包含本地路径或原始CTF/TIF文件名，已在API调用前阻断。",
        )
    if client is None and not current.ready:
        return AgentRunResult("offline", "", current.model, error=current.message)
    if client is None:
        from openai import OpenAI

        client_kwargs = {"api_key": os.getenv(current.api_key_env)}
        if current.base_url:
            client_kwargs["base_url"] = current.base_url
        client = OpenAI(**client_kwargs)

    if current.provider == "deepseek":
        return _run_deepseek_agent(question, client, current)

    input_items: list[Any] = [{"role": "user", "content": question}]
    trace: list[dict[str, Any]] = []
    total_calls = 0
    last_response_id = ""
    usage_total: dict[str, int] = {}
    try:
        for round_number in range(1, current.max_rounds + 1):
            response = client.responses.create(
                model=current.model,
                instructions=AGENT_INSTRUCTIONS,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                parallel_tool_calls=False,
                reasoning={"effort": current.reasoning_effort},
                input=input_items,
                safety_identifier="steelai_local_researcher",
            )
            _merge_usage(usage_total, _usage_snapshot(response))
            last_response_id = str(getattr(response, "id", ""))
            output_items = list(getattr(response, "output", []))
            input_items += output_items
            calls = [item for item in output_items if getattr(item, "type", "") == "function_call"]
            if not calls:
                answer = str(getattr(response, "output_text", "")).strip()
                if not answer:
                    return AgentRunResult("failed", "", current.model, trace, last_response_id, "模型未返回文本结果。", usage_total)
                return AgentRunResult("completed", answer, current.model, trace, last_response_id, usage=usage_total)

            for call in calls:
                total_calls += 1
                if total_calls > current.max_tool_calls:
                    return AgentRunResult(
                        "limit_reached", "", current.model, trace, last_response_id,
                        f"超过只读工具调用上限（{current.max_tool_calls}次）。",
                        usage_total,
                    )
                name = str(getattr(call, "name", ""))
                raw_arguments = str(getattr(call, "arguments", "{}"))
                tool_started = time.perf_counter()
                try:
                    arguments = json.loads(raw_arguments)
                    tool_result = execute_readonly_tool(name, arguments)
                    trace.append({
                        "round": round_number,
                        "tool": name,
                        "arguments": arguments,
                        "status": "completed",
                        "duration_ms": round((time.perf_counter() - tool_started) * 1000, 1),
                    })
                    output_text = json.dumps(tool_result, ensure_ascii=False, allow_nan=False)
                except Exception as exc:
                    trace.append({
                        "round": round_number,
                        "tool": name,
                        "arguments": raw_arguments,
                        "status": "failed",
                        "error": type(exc).__name__,
                        "duration_ms": round((time.perf_counter() - tool_started) * 1000, 1),
                    })
                    output_text = json.dumps({
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }, ensure_ascii=False)
                input_items.append({
                    "type": "function_call_output",
                    "call_id": str(getattr(call, "call_id", "")),
                    "output": output_text,
                })
        return AgentRunResult(
            "limit_reached", "", current.model, trace, last_response_id,
            f"超过Agent轮次上限（{current.max_rounds}轮）。",
            usage_total,
        )
    except Exception as exc:
        return AgentRunResult(
            "failed", "", current.model, trace, last_response_id,
            f"{type(exc).__name__}: {exc}",
            usage_total,
        )
