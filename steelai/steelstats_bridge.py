"""SteelStats isolated-CLI adapter over a verified SteelData result package.

SteelAI owns the human review and converts only verified specimen-level tensile
records into the frozen T30 file contract. SteelStats remains a sibling module
with its own Python environment; this file never imports its implementation.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from steelai.paths import OUTPUTS, ROOT
from steelai.settings import load_settings
from steelai.steeldata_bridge import (
    SYNTHETIC_PREVIEW_BLOCKER, Inspection, inspect_run, mapping_rows,
)


ADAPTER_VERSION = "1.0"
CONTRACT_ID = "SteelStats-Statistical-Input-v1.0"
METHOD_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*@[0-9]+\.[0-9]+\.[0-9]+")
FORBIDDEN_REVIEWERS = {"system", "agent", "auto", "automatic"}
TARGETS = (
    ("ys_mpa", "ys_mpa", "MPa"),
    ("uts_mpa", "uts_mpa", "MPa"),
    ("el_pct", "elongation_pct", "%"),
)
INPUT_FILES = ("analysis_plan.json", "units.csv", "observations.csv", "decisions.csv")


def _publish_directory(staging: Path, destination: Path) -> None:
    """Handle brief Windows scanner locks without weakening no-overwrite publication."""
    for attempt in range(5):
        try:
            staging.rename(destination)
            return
        except PermissionError:
            if attempt == 4 or destination.exists():
                raise
            time.sleep(0.1 * (attempt + 1))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_json(value: Any) -> str:
    return _digest_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8"))


def _csv_bytes(fields: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _reviewed_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("统计审核时间必须是带时区的 ISO 时间。") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("统计审核时间必须包含时区。")
    return value


def _validate_review(method_version: str, reviewer: str, reviewed_at: str) -> tuple[str, str, str]:
    method = method_version.strip()
    human = reviewer.strip()
    if not METHOD_VERSION_RE.fullmatch(method):
        raise ValueError("方法版本必须使用 method-id@MAJOR.MINOR.PATCH，例如 tensile-iso6892-1@1.0.0。")
    if not human or human.casefold() in FORBIDDEN_REVIEWERS:
        raise ValueError("统计纳入决定必须填写真实人工审核人，不能由 system 或 Agent 代替。")
    return method, human, _reviewed_at(reviewed_at.strip())


def _validated_bindings(inspection: Inspection, bindings: dict[str, str]) -> dict[str, str]:
    expected = {item["mapping_key"] for item in mapping_rows(inspection)}
    normalized = {
        str(key): str(value).strip() for key, value in bindings.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    if set(normalized) != expected or any(not value for value in normalized.values()):
        raise ValueError("必须逐一人工确认所有来源试样的 sample_id；不能缺项、增加额外映射或自动猜测。")
    if any(len(value) > 100 or any(ord(char) < 32 for char in value) for value in normalized.values()):
        raise ValueError("sample_id 含不安全字符或长度超过 100。")
    return normalized


def _build_input_files(
    inspection: Inspection,
    bindings: dict[str, str],
    method_version: str,
    reviewer: str,
    reviewed_at: str,
    *,
    allow_synthetic: bool = False,
) -> dict[str, bytes]:
    blockers = list(inspection.blockers)
    is_synthetic = inspection.manifest.get("synthetic") is True
    if allow_synthetic and is_synthetic:
        blockers = [item for item in blockers if item != SYNTHETIC_PREVIEW_BLOCKER]
    if blockers:
        raise ValueError("SteelData 结果包不可用于统计：" + "；".join(blockers))
    bindings = _validated_bindings(inspection, bindings)
    method_version, reviewer, reviewed_at = _validate_review(method_version, reviewer, reviewed_at)
    run_id = str(inspection.manifest.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("SteelData 结果包缺少 run_id。")

    plan_seed = {
        "adapter_version": ADAPTER_VERSION,
        "steeldata_manifest_sha256": inspection.manifest_sha256,
        "bindings": bindings,
        "method_version": method_version,
    }
    plan = {
        "plan_id": "STEELAI-T33-" + _digest_json(plan_seed)[:16].upper(),
        "contract_id": CONTRACT_ID,
        "plan_version": "1.0.0",
        "analysis_level": "between_specimen",
        "statistical_unit_type": "specimen",
        "group_keys": ["sample_id", "quantity", "unit", "method_version"],
        "target_quantities": [target for _, target, _ in TARGETS],
        "method_versions": {target: method_version for _, target, _ in TARGETS},
        "missing_policy": "exclude_with_record_no_imputation",
        "quality_policy": "passed_only",
        "summary_policy": "descriptive_only_not_raw_replicate",
        "decision_policy": "human_record_required",
    }
    evidence_ref = "steeldata-manifest-sha256:" + inspection.manifest_sha256
    unit_rows: list[dict[str, Any]] = []
    observation_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    seen_specimens: set[str] = set()
    source_qc_by_dataset = {
        str(item.get("dataset_dir")): str(item.get("qc_status", ""))
        for item in inspection.manifest.get("files", [])
    }

    for dataset in sorted(inspection.datasets, key=lambda item: (str(item.get("source_file")), str(item.get("dataset_dir")))):
        if dataset.get("domain") != "tensile" or dataset.get("kind") != "table":
            raise ValueError("T33 当前只接受 SteelData 的逐试样拉伸 table，不自动降维其他领域数据。")
        for record in sorted(dataset["records"], key=lambda item: str(item.get("record_id"))):
            specimen_id = str(record.get("specimen_id", "")).strip()
            mapping_key = _digest_json([dataset["source_file"], specimen_id])
            sample_id = bindings[mapping_key]
            if specimen_id in seen_specimens:
                raise ValueError(f"SteelData 结果包重复出现物理试样 {specimen_id}；请在源端确认后再统计。")
            seen_specimens.add(specimen_id)
            unit_rows.append({
                "unit_id": specimen_id,
                "unit_type": "specimen",
                "parent_unit_id": sample_id,
                "parent_unit_type": "sample",
                "sample_id": sample_id,
                "specimen_id": specimen_id,
                "unit_status": "synthetic_fixture" if is_synthetic else "verified",
                "notes": f"SteelAI SteelStats bridge {ADAPTER_VERSION}; SteelData run {run_id}; manifest {inspection.manifest_sha256}",
            })
            source_qc = source_qc_by_dataset.get(str(dataset.get("dataset_dir")), "")
            for source_field, quantity, unit in TARGETS:
                observation_id = "STSAI-OBS-" + _digest_json([
                    inspection.manifest_sha256,
                    dataset.get("dataset_dir"),
                    record.get("record_id"),
                    quantity,
                ])[:20].upper()
                observation_rows.append({
                    "observation_id": observation_id,
                    "subject_type": "specimen",
                    "subject_id": specimen_id,
                    "sample_id": sample_id,
                    "specimen_id": specimen_id,
                    "quantity": quantity,
                    "value": record[source_field],
                    "unit": unit,
                    "quality_status": "passed",
                    "measurement_role": "individual",
                    "missing_reason": "",
                    "method_version": method_version,
                    "report_id": run_id,
                    "source_record_id": record["record_id"],
                    "notes": f"SteelData dataset {dataset['dataset_dir']}; source QC {source_qc}",
                })
                decision_rows.append({
                    "observation_id": observation_id,
                    "decision": "include",
                    "reason_code": "eligible_predeclared",
                    "reviewer": reviewer,
                    "reviewed_at": reviewed_at,
                    "evidence_ref": evidence_ref,
                })
    if not unit_rows or not observation_rows:
        raise ValueError("SteelData 结果包没有可转换的逐试样拉伸观测。")

    return {
        "analysis_plan.json": _json_bytes(plan),
        "units.csv": _csv_bytes(
            ("unit_id", "unit_type", "parent_unit_id", "parent_unit_type", "sample_id", "specimen_id", "unit_status", "notes"),
            unit_rows,
        ),
        "observations.csv": _csv_bytes(
            ("observation_id", "subject_type", "subject_id", "sample_id", "specimen_id", "quantity", "value", "unit", "quality_status", "measurement_role", "missing_reason", "method_version", "report_id", "source_record_id", "notes"),
            observation_rows,
        ),
        "decisions.csv": _csv_bytes(
            ("observation_id", "decision", "reason_code", "reviewer", "reviewed_at", "evidence_ref"),
            decision_rows,
        ),
    }


def prepare_statistical_input(
    run_dir: str | Path,
    bindings: dict[str, str],
    method_version: str,
    reviewer: str,
    reviewed_at: str,
    *,
    output_root: Path = OUTPUTS / "steelstats_inputs",
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """Create one append-only T30 bundle without writing inside SteelData."""
    inspection = inspect_run(run_dir)
    root = output_root.resolve()
    if root == inspection.root or root.is_relative_to(inspection.root):
        raise ValueError("统计输入输出目录不能位于 SteelData 结果包内。")
    files = _build_input_files(
        inspection, bindings, method_version, reviewer, reviewed_at,
        allow_synthetic=allow_synthetic,
    )
    package_digest = _digest_json({name: _digest_bytes(content) for name, content in sorted(files.items())})
    bundle_id = "SSB-" + package_digest[:20].upper()
    destination = root / bundle_id
    if destination.exists():
        if not destination.is_dir() or any(
            not (destination / name).is_file() or (destination / name).read_bytes() != content
            for name, content in files.items()
        ) or {path.name for path in destination.iterdir()} != set(INPUT_FILES):
            raise ValueError("已有统计输入包与当前内容不一致；为保护审计现场不会覆盖。")
        reused = True
    else:
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".tmp-{bundle_id}-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            for name, content in files.items():
                (staging / name).write_bytes(content)
            _publish_directory(staging, destination)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        reused = False
    return {
        "status": "ready",
        "adapter_version": ADAPTER_VERSION,
        "bundle_id": bundle_id,
        "bundle_dir": str(destination),
        "reused": reused,
        "steeldata_run_id": inspection.manifest["run_id"],
        "steeldata_manifest_sha256": inspection.manifest_sha256,
        "steeldata_qc_status": inspection.manifest["qc_status"],
        "steeldata_warnings": inspection.warnings,
        "counts": {
            "specimens": len({row["specimen_id"] for row in mapping_rows(inspection)}),
            "observations": sum(len(dataset["records"]) for dataset in inspection.datasets) * len(TARGETS),
        },
    }


class SteelStatsConfigError(RuntimeError):
    """``tools.steelstats_project`` is configured but cannot be used.

    Raised only for real configuration faults (settings read/parse failure,
    non-mapping ``[tools]`` table, non-string path value). Genuinely
    unconfigured states (missing field, empty or whitespace-only value)
    return ``None`` from :func:`configured_steelstats_project` so callers may
    keep the legacy sibling lookup. Error text never quotes the configured
    value, so settings contents or secrets cannot leak through it.
    """


def configured_steelstats_project() -> Path | None:
    """Resolve ``tools.steelstats_project`` from the existing settings loader.

    Missing field, empty string or whitespace-only counts as *unconfigured*
    and returns ``None`` (callers keep the legacy sibling lookup). A value
    that exists but is unusable — settings file unreadable or unparsable,
    ``[tools]`` not a table, or a non-string path — raises
    :class:`SteelStatsConfigError` instead of silently falling back.
    Relative configured paths are interpreted against the Workbench ROOT.
    """
    try:
        settings = load_settings()
    except (OSError, ValueError) as exc:
        raise SteelStatsConfigError(
            "Workbench 设置文件读取或解析失败，无法确定 SteelStats 项目位置。") from exc
    tools = settings.get("tools")
    if tools is None:
        return None
    if not isinstance(tools, dict):
        raise SteelStatsConfigError(
            "Workbench 设置中的 [tools] 段不是表，无法读取 steelstats_project 字段。")
    value = tools.get("steelstats_project")
    if value is None:
        return None
    if not isinstance(value, str):
        raise SteelStatsConfigError(
            "tools.steelstats_project 已配置但不是字符串路径，拒绝回退到旧同级位置。")
    if not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    return (path if path.is_absolute() else (ROOT / path)).resolve()


class SteelStatsClient:
    """Call only the documented SteelStats CLI using its independent runtime."""

    def __init__(self, project: Path | None = None):
        self.config_error: str | None = None
        if project is not None:
            self.project: Path | None = Path(project).resolve()
            self.project_source = "explicit"
        else:
            try:
                configured = configured_steelstats_project()
            except SteelStatsConfigError as exc:
                self.project = None
                self.project_source = "config_error"
                self.config_error = str(exc)
            else:
                if configured is not None:
                    self.project = configured
                    self.project_source = "configured"
                else:
                    self.project = (ROOT.parent / "SteelStats").resolve()
                    self.project_source = "legacy_sibling"
        if self.project is not None:
            self.python = self.project / ".venv" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python")

    def availability(self) -> dict[str, Any]:
        if self.project is None:
            return {
                "ready": False, "project": None, "python": None,
                "reason": "config_error", "detail": self.config_error,
            }
        result = {"ready": False, "project": str(self.project), "python": str(self.python)}
        try:
            descriptor = json.loads((self.project / "steelstats.module.json").read_text(encoding="utf-8"))
            invocation = descriptor.get("invocation", {})
            declared = (
                descriptor.get("module_id") == "steelstats"
                and descriptor.get("contract_version") == 1
                and invocation.get("kind") == "isolated_cli"
                and invocation.get("report_command") == "report"
                and invocation.get("verify_command") == "verify-report"
            )
        except (OSError, ValueError, TypeError):
            return {**result, "reason": "invalid_module_descriptor"}
        if not declared:
            return {**result, "reason": "unsupported_module_descriptor"}
        if not self.python.is_file() or not (self.project / "steelstats" / "__main__.py").is_file():
            return {**result, "reason": "runtime_files_missing"}
        env = {
            key: value for key, value in os.environ.items()
            if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"}
        }
        env["PYTHONUTF8"] = "1"
        try:
            completed = subprocess.run(
                [str(self.python), "-B", "-m", "steelstats", "contract"],
                cwd=str(self.project), env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10, shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {**result, "reason": "runtime_probe_failed"}
        if completed.returncode != 0 or not isinstance(payload, dict) or payload.get("status") != "passed":
            return {**result, "reason": "runtime_probe_rejected"}
        return {**result, "ready": True, "reason": "ready", "runtime": payload}

    def _call(self, args: list[str], *, accepted: tuple[int, ...] = (0,)) -> dict[str, Any]:
        if self.project is None:
            raise ValueError(
                f"SteelStats 未就绪：{self.config_error}"
                "请修正 config/settings.toml 的 tools.steelstats_project，"
                "或在调用时显式传入有效的 SteelStats 项目路径。")
        if not self.availability()["ready"]:
            raise ValueError(
                f"SteelStats 未就绪：未找到有效项目、模块描述或其独立 .venv（当前定位 {self.project}）。")
        env = {
            key: value for key, value in os.environ.items()
            if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"}
        }
        env["PYTHONUTF8"] = "1"
        try:
            completed = subprocess.run(
                [str(self.python), "-B", "-m", "steelstats", *args],
                cwd=str(self.project),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("SteelStats 超过 180 秒，已终止本次调用；SteelData 源包没有被修改。") from exc
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise ValueError("SteelStats 未返回有效 JSON：" + completed.stderr[-1200:]) from exc
        if not isinstance(payload, dict):
            raise ValueError("SteelStats 返回值不是 JSON 对象。")
        if completed.returncode not in accepted:
            details = payload.get("problems") or [payload.get("message") or f"退出码 {completed.returncode}"]
            raise ValueError("SteelStats 拒绝生成报告：" + "；".join(map(str, details)))
        return payload

    def publish(self, bundle: Path, output_root: Path) -> dict[str, Any]:
        bundle = bundle.resolve()
        output_root = output_root.resolve()
        payload = self._call(["report", str(bundle), "--output", str(output_root)])
        analysis_id = str(payload.get("analysis_id", ""))
        report_dir = Path(str(payload.get("report_dir", ""))).resolve()
        if (
            payload.get("status") != "complete"
            or not analysis_id.startswith("STS-")
            or report_dir.parent != output_root
            or report_dir.name != analysis_id
            or payload.get("verification", {}).get("status") != "passed"
        ):
            raise ValueError("SteelStats 返回的报告身份或完整性状态无效。")
        expected = {
            "report": report_dir / "statistics_report.md",
            "result": report_dir / "statistics_result.json",
            "manifest": report_dir / "report_manifest.json",
        }
        for key, path in expected.items():
            if Path(str(payload.get(key, ""))).resolve() != path or not path.is_file():
                raise ValueError("SteelStats 返回的报告文件引用无效。")
        return payload

    def verify(self, package: Path) -> dict[str, Any]:
        payload = self._call(["verify-report", str(package.resolve())])
        if payload.get("status") != "passed" or payload.get("problems"):
            raise ValueError("SteelStats 报告包未通过独立复核。")
        return payload


def run_statistics_from_steeldata(
    run_dir: str | Path,
    bindings: dict[str, str],
    method_version: str,
    reviewer: str,
    reviewed_at: str,
    *,
    input_root: Path = OUTPUTS / "steelstats_inputs",
    report_root: Path = OUTPUTS / "steelstats_reports",
    client: SteelStatsClient | None = None,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """Prepare, publish and verify without ever opening SteelData files for writing."""
    source = Path(run_dir).resolve()
    report_root = report_root.resolve()
    if report_root == source or report_root.is_relative_to(source):
        raise ValueError("统计报告输出目录不能位于 SteelData 结果包内。")
    prepared = prepare_statistical_input(
        source,
        bindings,
        method_version,
        reviewer,
        reviewed_at,
        output_root=input_root,
        allow_synthetic=allow_synthetic,
    )
    module = client or SteelStatsClient()
    published = module.publish(Path(prepared["bundle_dir"]), report_root)
    verified = module.verify(Path(published["report_dir"]))
    quality_status = "warning" if (
        prepared["steeldata_qc_status"] == "warning"
        or verified.get("result_status") == "warning"
        or prepared["steeldata_warnings"]
    ) else "passed"
    return {
        "status": "complete",
        "adapter_version": ADAPTER_VERSION,
        "quality_status": quality_status,
        "analysis_id": published["analysis_id"],
        "report": published["report"],
        "result": published["result"],
        "report_dir": published["report_dir"],
        "input_bundle": prepared["bundle_dir"],
        "input_bundle_id": prepared["bundle_id"],
        "input_reused": prepared["reused"],
        "report_reused": bool(published.get("reused")),
        "source": {
            "run_id": prepared["steeldata_run_id"],
            "manifest_sha256": prepared["steeldata_manifest_sha256"],
            "qc_status": prepared["steeldata_qc_status"],
            "warnings": prepared["steeldata_warnings"],
            "modified": False,
        },
        "statistics": {
            "status": verified.get("result_status"),
            "method_version": verified.get("statistics_method_version"),
            "verification": verified["status"],
        },
    }
