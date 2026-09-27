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

from steelai.agent_evidence_gateway import (
    AGENT_GATEWAY_OUTPUTS,
    ALLOWED_AGENT_TOOLS,
    AgentEvidenceGateway,
    AgentGatewayError,
)
from steelai.governance import digest_value
from steelai.research_tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS, execute_readonly_tool
from steelai.settings import load_settings

# The read-only tool catalog and executor are owned by ``steelai.research_tools``.
# ``TOOL_DEFINITIONS``/``TOOL_FUNCTIONS``/``execute_readonly_tool`` remain importable
# here only as a backward-compatible facade for existing SteelAI callers; new
# agent, bridge and protocol code must import them from ``steelai.research_tools``.


AGENT_NAME = "SteelAI Research Agent v0.3"
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
For double-hit softening cases, use get_thermal_softening_case and cite acquisition
IDs. Preserve values above 100 percent as QC warnings, not recrystallized
fractions. The 2-percent and 5-percent methods use different sigma_m definitions;
the Zhang Ling thesis also uses first-hit end stress rather than this project's
first-hit peak stress. Do not transfer the thesis's Nb2/Nb4 mechanism to B-DQ/R-DQ.

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
    gateway_id: str = ""
    send_summary: dict[str, Any] = field(default_factory=dict)
    structured_output: dict[str, Any] = field(default_factory=dict)
    audit_package: str = ""
    manifest_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "model": self.model,
            "tool_trace": self.tool_trace,
            "response_id": self.response_id,
            "error": self.error,
            "usage": self.usage,
            "gateway_id": self.gateway_id,
            "send_summary": self.send_summary,
            "structured_output": self.structured_output,
            "audit_package": self.audit_package,
            "manifest_sha256": self.manifest_sha256,
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
    socks_proxy_configured = any(
        str(os.getenv(name, "")).lower().startswith(("socks4:", "socks5:", "socks5h:"))
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
    )
    proxy_dependency_missing = socks_proxy_configured and importlib.util.find_spec("socksio") is None
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
    elif proxy_dependency_missing:
        state, message = "offline_missing_proxy_dependency", "本机使用 SOCKS 代理，但当前 Python 环境缺少 socksio；Agent 请求尚不可用。"
    else:
        state, message = "online_ready", f"Agent已连接{provider}，可调用只读科研工具。"
    return AgentStatus(
        state, enabled, api_key_present, package_present, model, effort,
        max_tool_calls, max_rounds, message, package_version,
        provider, api_key_env, base_url,
    )


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


def _run_deepseek_agent(
    question: str,
    client: Any,
    current: AgentStatus,
    gateway: AgentEvidenceGateway,
) -> AgentRunResult:
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
            gateway.before_model_call()
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
                    tool_result = gateway.execute_evidence_tool(
                        name,
                        arguments,
                        execute_readonly_tool,
                        round_number=round_number,
                    )
                    duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    trace.append({
                        "round": round_number,
                        "tool": name,
                        "arguments_sha256": digest_value(arguments),
                        "evidence_id": tool_result["_gateway"]["evidence_id"],
                        "status": "completed",
                        "duration_ms": duration_ms,
                    })
                    output_text = json.dumps(tool_result, ensure_ascii=False, allow_nan=False)
                except Exception as exc:
                    duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    failed_audit = gateway.record_failed_tool(
                        name,
                        raw_arguments,
                        round_number=round_number,
                        error=exc,
                        duration_ms=duration_ms,
                    )
                    trace.append({
                        "round": round_number,
                        "tool": failed_audit["tool"],
                        "arguments_sha256": digest_value(raw_arguments),
                        "status": failed_audit["status"],
                        "error_code": failed_audit["error_code"],
                        "duration_ms": duration_ms,
                    })
                    output_text = json.dumps({
                        "error": getattr(exc, "code", type(exc).__name__),
                        "message": "Tool evidence was unavailable or blocked by the gateway.",
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


def _run_openai_agent(
    question: str,
    *,
    client: Any,
    current: AgentStatus,
    gateway: AgentEvidenceGateway,
) -> AgentRunResult:
    input_items: list[Any] = [{"role": "user", "content": question}]
    trace: list[dict[str, Any]] = []
    total_calls = 0
    last_response_id = ""
    usage_total: dict[str, int] = {}
    try:
        for round_number in range(1, current.max_rounds + 1):
            gateway.before_model_call()
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
                    tool_result = gateway.execute_evidence_tool(
                        name,
                        arguments,
                        execute_readonly_tool,
                        round_number=round_number,
                    )
                    trace.append({
                        "round": round_number,
                        "tool": name,
                        "arguments_sha256": digest_value(arguments),
                        "evidence_id": tool_result["_gateway"]["evidence_id"],
                        "status": "completed",
                        "duration_ms": round((time.perf_counter() - tool_started) * 1000, 1),
                    })
                    output_text = json.dumps(tool_result, ensure_ascii=False, allow_nan=False)
                except Exception as exc:
                    duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    failed_audit = gateway.record_failed_tool(
                        name,
                        raw_arguments,
                        round_number=round_number,
                        error=exc,
                        duration_ms=duration_ms,
                    )
                    trace.append({
                        "round": round_number,
                        "tool": failed_audit["tool"],
                        "arguments_sha256": digest_value(raw_arguments),
                        "status": failed_audit["status"],
                        "error_code": failed_audit["error_code"],
                        "duration_ms": duration_ms,
                    })
                    output_text = json.dumps({
                        "error": getattr(exc, "code", type(exc).__name__),
                        "message": "Tool evidence was unavailable or blocked by the gateway.",
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


def run_research_agent(
    question: str,
    *,
    client: Any | None = None,
    status: AgentStatus | None = None,
    gateway_output_root: str | Path | None = None,
) -> AgentRunResult:
    """Run the cloud agent through the T55 fail-closed evidence gateway.

    A caller-supplied client is treated as a test/integration client and keeps
    the audit in memory unless ``gateway_output_root`` is explicitly supplied.
    Normal UI runs publish an append-only audit package before returning.
    """
    question = question.strip()
    current = status or agent_status()
    if not question:
        return AgentRunResult("invalid_input", "", current.model, error="问题不能为空。")
    if _ABSOLUTE_PATH_INPUT.search(question) or _RAW_FILENAME_INPUT.search(question):
        return AgentRunResult(
            "invalid_input",
            "",
            current.model,
            error="输入包含本地路径或受保护原始文件名，已在API调用前阻断。",
        )
    if client is None and not current.ready:
        return AgentRunResult("offline", "", current.model, error=current.message)

    persist_root: str | Path | None = gateway_output_root
    if persist_root is None and client is None:
        persist_root = AGENT_GATEWAY_OUTPUTS
    try:
        gateway = AgentEvidenceGateway(
            question,
            current.provider,
            current.model,
            tuple(sorted(ALLOWED_AGENT_TOOLS)),
            output_root=Path(persist_root) if persist_root is not None else None,
        )
    except AgentGatewayError as exc:
        return AgentRunResult(
            "invalid_input", "", current.model,
            error=f"{exc.code}: 输入未通过Agent证据网关。",
        )

    try:
        if client is None:
            from openai import OpenAI

            client_kwargs = {"api_key": os.getenv(current.api_key_env)}
            if current.base_url:
                client_kwargs["base_url"] = current.base_url
            client = OpenAI(**client_kwargs)

        if current.provider == "deepseek":
            raw = _run_deepseek_agent(question, client, current, gateway)
        else:
            raw = _run_openai_agent(
                question,
                client=client,
                current=current,
                gateway=gateway,
            )
        finalized = gateway.finalize(
            status=raw.status,
            answer=raw.answer,
            response_id=raw.response_id,
            usage=raw.usage,
            error=raw.error,
        )
        raw.status = finalized["status"]
        raw.answer = finalized["answer"]
        raw.error = finalized["error"]
        raw.gateway_id = finalized["gateway_id"]
        raw.send_summary = finalized["send_summary"]
        raw.structured_output = finalized["structured_output"]
        raw.audit_package = finalized["audit_package"]
        raw.manifest_sha256 = finalized["manifest_sha256"]
        return raw
    except Exception as exc:
        gateway.abandon()
        return AgentRunResult(
            "blocked",
            "",
            current.model,
            error=f"Agent证据网关审计失败：{type(exc).__name__}",
            gateway_id=gateway.gateway_id,
        )
