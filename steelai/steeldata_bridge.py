"""SteelData result-contract adapter. No SteelData/Pandera imports in SteelAI.

Execution uses the sibling module's own Python; inspection uses bounded stdlib
checksum verification. Only explicitly mapped tensile observations enter intake.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from steelai.data_intake import (
    ID_POLICY_PATH, commit_intake, finalize_intake_package, save_intake_package,
    validate_intake_csv,
)
from steelai.paths import ROOT
from steelai.research_data_contract import CONTRACT_PATH

ADAPTER_VERSION = "1.0"
PROPERTIES = (("ys_mpa", "ys_mpa", "MPa"), ("uts_mpa", "uts_mpa", "MPa"),
              ("el_pct", "elongation_pct", "%"))
SOURCE_STATUSES = ("instrument_export", "verified_from_source", "manual_extraction_verified")
MAX_ARTIFACT = 128 * 1024 * 1024
MAX_PACKAGE = 512 * 1024 * 1024


def validate_selected_files(data_files: list[tuple[str, bytes]], approval_files: list[tuple[str, bytes]]) -> None:
    """Validate browser selections before creating any temporary files.

    Uploaded names are untrusted basenames, not local paths. Reject collisions
    instead of renaming scientific source files or overwriting their content.
    """
    groups = ((data_files, {".csv", ".tsv", ".xlsx"}, 1000, 20 * 1024 * 1024, "实验文件"),
              (approval_files, {".json"}, 40, 2 * 1024 * 1024, "批准文件"))
    for files, suffixes, count_limit, size_limit, label in groups:
        if not files:
            raise ValueError(f"请选择{label}。")
        if len(files) > count_limit:
            raise ValueError(f"{label}最多选择 {count_limit} 个。")
        seen = set()
        for name, content in files:
            if (not isinstance(name, str) or not name or len(name) > 200
                    or name != name.strip() or name.endswith(".")
                    or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                    or name in {".", ".."}
                    or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])", name.split(".")[0])):
                raise ValueError("文件名不安全或不是单个文件名；请检查所选文件。")
            if name.casefold() in seen:
                raise ValueError(f"同名{label}会产生冲突：{name}。请分批处理，系统不会覆盖或自动改名。")
            seen.add(name.casefold())
            if Path(name).suffix.lower() not in suffixes:
                raise ValueError(f"不支持此{label}格式：{name}")
            if not isinstance(content, bytes) or not content or len(content) > size_limit:
                raise ValueError(f"{label}不能为空，且单文件不得超过 {size_limit // (1024 * 1024)} MiB：{name}")
    if sum(len(content) for _, content in data_files) > 100 * 1024 * 1024:
        raise ValueError("实验文件总计不得超过 100 MiB，请分批处理。")
    if sum(len(content) for _, content in approval_files) > 8 * 1024 * 1024:
        raise ValueError("批准文件总计不得超过 8 MiB。")
    for name, content in approval_files:
        try:
            approval = _json(content)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"批准文件不是有效的 JSON 对象：{name}") from exc
        if approval.get("kind") != "human" or not isinstance(approval.get("profile"), dict):
            raise ValueError(f"{name} 不是 v0.2 human 批准记录；不能用普通模板或演示批准替代。")
        if approval.get("profile_sha256") != _digest(approval["profile"]):
            raise ValueError(f"批准文件的模板摘要不匹配：{name}")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _json(payload: bytes):
    value = json.loads(payload.decode("utf-8-sig"), parse_constant=lambda value: _bad_json(value))
    if not isinstance(value, dict):
        raise ValueError("协议 JSON 顶层必须是对象")
    return value


def _bad_json(value):
    raise ValueError(f"JSON contains non-finite literal: {value}")


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"文件超过接入大小上限：{path.name}")
    return payload


def _artifact_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("结果包含非法相对路径")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("结果路径超出运行目录")
    return path


@dataclass
class Inspection:
    root: Path
    manifest: dict
    manifest_sha256: str
    qc: dict
    datasets: list[dict]
    blockers: list[str]
    warnings: list[str]

    @property
    def transferable(self) -> bool:
        return not self.blockers


def inspect_run(run_dir: str | Path) -> Inspection:
    """Verify contract v1 and all declared artifacts before exposing any records.

    Checksums detect corruption, not authenticity against a malicious rewriter.
    Raw sources are hashed but not copied into SteelAI. Consumed JSON bytes are
    held in memory so the preview cannot read a later replacement of that file.
    """
    root = Path(run_dir).resolve()
    manifest_bytes = _read(root / "manifest.json", 4 * 1024 * 1024)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if _read(root / "COMPLETE", 128).decode("ascii").strip() != manifest_hash:
        raise ValueError("结果包未完成或 manifest 校验失败")
    manifest = _json(manifest_bytes)
    if (manifest.get("schema_version") != 1 or manifest.get("module") != "steeldata"
            or manifest.get("complete") is not True):
        raise ValueError("不支持的 SteelData 结果契约")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not {"qc.json", "report.html"}.issubset(artifacts):
        raise ValueError("缺少必需的结果文件清单")
    if len(artifacts) > 6000:
        raise ValueError("结果文件过多，请拆分批次")
    needed = {"qc.json"}
    execution = manifest.get("execution")
    if execution is not None:
        if (not isinstance(execution, dict) or execution.get("schema_version") != 1
                or set(execution) != {
                    "schema_version", "suggestion_id", "suggestion_sha256",
                    "approval_record_sha256", "review_record_sha256", "idempotency_key",
                    "attempt", "audit_files",
                }
                or not isinstance(execution.get("audit_files"), dict)
                or set(execution["audit_files"]) != {"suggestion", "review", "execution_request"}):
            raise ValueError("执行审计链格式无效")
        for name, expected_path in {
            "suggestion": "audit/suggestion.json",
            "review": "audit/review.json",
            "execution_request": "audit/execution_request.json",
        }.items():
            entry = execution["audit_files"].get(name)
            if not isinstance(entry, dict) or entry.get("path") != expected_path:
                raise ValueError("执行审计文件引用无效")
            needed.add(expected_path)
    files = manifest.get("files", [])
    if (not isinstance(files, list) or not files or not all(isinstance(f, dict) for f in files)
            or not isinstance(manifest.get("counts"), dict) or not isinstance(manifest.get("run_id"), str)):
        raise ValueError("运行目录缺少有效的文件清单、计数或 run_id")
    for info in files:
        if info.get("snapshot") not in artifacts:
            raise ValueError("原始文件快照未受校验保护")
        if info.get("dataset_dir"):
            needed.add(info["dataset_dir"] + "/data.json")
    for approval in manifest.get("approvals", []):
        needed.add("approvals/" + approval["profile_id"] + ".json")
    if not needed.issubset(artifacts):
        raise ValueError("数据集或批准记录未受校验保护")
    buffers, total = {}, 0
    for name, expected in artifacts.items():
        payload = _read(_artifact_path(root, name), MAX_ARTIFACT)
        total += len(payload)
        if total > MAX_PACKAGE:
            raise ValueError("结果包超过 512 MiB 接入上限，请拆分批次")
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"结果文件校验失败：{name}")
        if name in needed:
            buffers[name] = payload
    qc = _json(buffers["qc.json"])
    blockers, warnings, datasets = [], [], []
    execution_evidence = None
    if execution is not None:
        suggestion_record = _json(buffers["audit/suggestion.json"])
        review_record = _json(buffers["audit/review.json"])
        execution_request = _json(buffers["audit/execution_request.json"])
        suggested = suggestion_record.get("suggestion")
        if not isinstance(suggested, dict) or suggestion_record.get("suggestion_sha256") != _digest(suggested):
            raise ValueError("映射建议记录摘要无效")
        if set(execution_request) != {
            "schema_version", "trigger", "actor", "suggestion_id", "suggestion_sha256",
            "source_file", "source_sha256", "idempotency_key", "attempt", "requested_at",
        }:
            raise ValueError("执行请求包含未登记字段")
        expected_idempotency = _digest({
            "suggestion_sha256": suggestion_record.get("suggestion_sha256"),
            "approval_record_sha256": execution.get("approval_record_sha256"),
            "review_record_sha256": execution.get("review_record_sha256"),
            "source_sha256": suggested.get("source_sha256"),
        })
        checks = (
            execution.get("suggestion_id") == suggested.get("suggestion_id"),
            execution.get("suggestion_sha256") == suggestion_record.get("suggestion_sha256"),
            execution.get("suggestion_id") == review_record.get("suggestion_id"),
            execution.get("suggestion_sha256") == review_record.get("suggestion_sha256"),
            execution.get("review_record_sha256") == _digest(review_record),
            execution.get("audit_files", {}).get("suggestion", {}).get("sha256") == _digest(suggestion_record),
            execution.get("audit_files", {}).get("review", {}).get("sha256") == _digest(review_record),
            execution.get("audit_files", {}).get("execution_request", {}).get("sha256") == _digest(execution_request),
            execution_request.get("trigger") == "human_approval",
            execution_request.get("actor") == "system",
            execution_request.get("suggestion_id") == execution.get("suggestion_id"),
            execution_request.get("suggestion_sha256") == execution.get("suggestion_sha256"),
            execution_request.get("idempotency_key") == execution.get("idempotency_key"),
            execution_request.get("attempt") == execution.get("attempt"),
            isinstance(execution.get("attempt"), int) and execution.get("attempt") >= 1,
            execution_request.get("source_file") == suggested.get("source_file"),
            execution_request.get("source_sha256") == suggested.get("source_sha256"),
            any(info.get("source_file") == suggested.get("source_file")
                and info.get("source_sha256") == suggested.get("source_sha256") for info in files),
            execution.get("idempotency_key") == expected_idempotency,
            review_record.get("decision") == "approved",
            bool(str(review_record.get("reviewer", "")).strip()),
            bool(str(review_record.get("note", "")).strip()),
        )
        if not all(checks):
            raise ValueError("建议、人工审批与执行请求的审计链不一致")
        execution_evidence = {
            "suggestion": suggestion_record,
            "review": review_record,
            "request": execution_request,
        }
    if manifest.get("synthetic") is not False:
        blockers.append("合成演示数据（或缺少 synthetic=false 声明）只能预览，不能进入真实 processed。")
    if manifest.get("processing_status") != "complete":
        blockers.append("批次尚未全部处理完成；请在 SteelData 修复或明确拆分后重新运行。")
    if manifest.get("qc_status") not in {"passed", "warning"} or qc.get("status") != manifest.get("qc_status"):
        blockers.append("质量检查失败、待审或 QC 状态不一致，禁止入库。")
    if qc.get("values_modified_by_qc") is not False:
        blockers.append("结果未声明 QC 不修改数值。")
    for issue in qc.get("issues", []):
        if issue.get("severity") in {"error", "review"}:
            blockers.append("QC 中仍有 error/review 事项，不能绕过。")
        elif issue.get("severity") == "warning":
            warnings.append(f"{issue.get('code')}: {issue.get('message')}")
        elif issue.get("severity") != "info":
            blockers.append("QC 含未知严重级别，需复核。")
    approvals = {}
    for entry in manifest.get("approvals", []):
        approval = _json(buffers["approvals/" + entry["profile_id"] + ".json"])
        profile = approval.get("profile", {})
        if (_digest(approval) != entry.get("approval_record_sha256")
                or _digest(profile) != entry.get("profile_sha256")
                or approval.get("profile_sha256") != entry.get("profile_sha256")
                or profile.get("profile_id") != entry.get("profile_id")):
            raise ValueError("批准记录或映射摘要不一致")
        if (entry.get("kind") != "human" or approval.get("kind") != "human"
                or not str(approval.get("reviewer", "")).strip()
                or not str(approval.get("note", "")).strip()):
            blockers.append("真实导入必须使用有审核人和说明的 human 批准记录。")
        if execution is not None:
            if (
                entry.get("suggestion_id") != execution.get("suggestion_id")
                or entry.get("suggestion_sha256") != execution.get("suggestion_sha256")
                or entry.get("approval_record_sha256") != execution.get("approval_record_sha256")
                or approval.get("suggestion_id") != execution.get("suggestion_id")
                or approval.get("suggestion_sha256") != execution.get("suggestion_sha256")
                or execution_evidence["review"].get("approval_record_sha256") != entry.get("approval_record_sha256")
                or execution_evidence["review"].get("approval_record") != f"approved_v2/{execution['suggestion_id']}.json"
                or execution_evidence["review"].get("profile_sha256") != entry.get("profile_sha256")
                or _digest(execution_evidence["suggestion"]["suggestion"].get("proposed_profile")) != entry.get("profile_sha256")
            ):
                raise ValueError("批准记录未绑定当前建议与执行审计链")
        approvals[entry["profile_id"]] = profile
    if not approvals:
        blockers.append("缺少明确的模板批准记录。")
    seen_datasets, seen_records = set(), set()
    for info in files:
        if info.get("source_sha256") != artifacts.get(info["snapshot"]):
            raise ValueError("源文件摘要与快照不一致")
        if info.get("status") != "processed" or info.get("qc_status") not in {"passed", "warning"}:
            blockers.append("至少一个文件未处理完成或未通过 QC。")
        if not info.get("dataset_dir"):
            continue
        dataset_name = info["dataset_dir"] + "/data.json"
        if dataset_name in seen_datasets:
            raise ValueError("重复的数据集引用")
        seen_datasets.add(dataset_name)
        data = _json(buffers[dataset_name])
        if not isinstance(data.get("records"), list) or not all(isinstance(r, dict) for r in data["records"]):
            raise ValueError("数据集缺少有效的记录列表")
        if (data.get("schema_version") != 1 or data.get("source_sha256") != info.get("source_sha256")
                or data.get("source_file") != info.get("source_file") or data.get("domain") != info.get("domain")
                or data.get("kind") != info.get("kind") or len(data.get("records", [])) != info.get("records")):
            raise ValueError("数据集与 manifest 不一致")
        data = {**data, "dataset_dir": info["dataset_dir"], "profile_id": info.get("profile_id")}
        profile = approvals.get(info.get("profile_id"), {})
        if profile.get("domain") != data.get("domain"):
            blockers.append("数据集没有对应领域的批准模板。")
        if data.get("domain") != "tensile":
            blockers.append("本版仅将拉伸结果接入性能长表；成分报告和曲线保留在 SteelData，不自动降维。")
        else:
            if data.get("kind") != "table":
                blockers.append("拉伸结果必须是逐试样 table。")
            # Enforce units and physics here even if the approved profile disabled a rule.
            units = data.get("metadata", {}).get("units", {})
            for source, _, unit in PROPERTIES:
                if units.get(source, {}).get("target") != unit:
                    blockers.append(f"{source} 的目标单位不是明确的 {unit}。")
            for row in data.get("records", []):
                identity = row.get("record_id")
                if not identity or identity in seen_records:
                    blockers.append("记录缺少唯一来源标识或出现重复标识。")
                seen_records.add(identity)
                values = [row.get(field) for field, _, _ in PROPERTIES]
                if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                    blockers.append("拉伸必需数值缺失或不是有限数值；不补值、不跳过。")
                elif not (values[1] > values[0] > 0 and 0 < values[2] < 100):
                    blockers.append("拉伸值违反 UTS > YS > 0 或 0 < EL < 100。")
                if not str(row.get("specimen_id", "")).strip():
                    blockers.append("缺少真实 specimen_id，不能编造试样编号。")
                if not all(row.get("source_cells", {}).get(f) for f, _, _ in PROPERTIES):
                    blockers.append("缺少数值对应的原始单元格位置。")
        datasets.append(data)
    if not datasets or not any(d["records"] for d in datasets):
        blockers.append("没有可接入的数据集。")
    if sum(len(d["records"]) for d in datasets) != manifest.get("counts", {}).get("records"):
        raise ValueError("结果记录数不一致")
    return Inspection(root, manifest, manifest_hash, qc, datasets,
                      list(dict.fromkeys(blockers)), list(dict.fromkeys(warnings)))


def mapping_rows(inspection: Inspection) -> list[dict]:
    """No name splitting/default B/R guesses; every source specimen needs a choice."""
    result = {}
    for data in inspection.datasets:
        if data["domain"] != "tensile":
            continue
        for row in data["records"]:
            specimen = str(row.get("specimen_id", ""))
            key = _digest([data["source_file"], specimen])
            result[key] = {"mapping_key": key, "source_file": data["source_file"],
                           "specimen_id": specimen, "sample_id": ""}
    return list(result.values())


def prepare_intake(inspection: Inspection, bindings: dict[str, str], source_status: str, *,
                   project_root: Path = ROOT, contract_path: Path = CONTRACT_PATH,
                   id_policy_path: Path = ID_POLICY_PATH) -> dict:
    if not inspection.transferable:
        raise ValueError("；".join(inspection.blockers))
    if source_status not in SOURCE_STATUSES:
        raise ValueError("请明确选择真实来源状态；标准化不等于来源已经核验。")
    expected = {row["mapping_key"] for row in mapping_rows(inspection)}
    if set(bindings) != expected or any(not isinstance(v, str) or not v.strip() for v in bindings.values()):
        raise ValueError("必须逐一确认所有来源试样的 sample_id 对应关系，不接受缺项或额外映射。")
    rows, provenance = [], []
    for data in inspection.datasets:
        for record in data["records"]:
            sample = bindings[_digest([data["source_file"], str(record["specimen_id"])])]
            for source, target, unit in PROPERTIES:
                origin_id = _digest([data["source_sha256"], data.get("sheet"), record["source_cells"][source], source])
                row = {"sample_id": sample, "specimen_id": record["specimen_id"], "property": target,
                       "value": record[source], "unit": unit, "source_status": source_status,
                       "notes": f"steeldata-origin:{origin_id}; run:{inspection.manifest['run_id']}; record:{record['record_id']}"}
                rows.append(row)
                provenance.append({"key": [sample, record["specimen_id"], target], "origin_id": origin_id,
                                   "record_id": record["record_id"], "source_file": data["source_file"],
                                   "source_sha256": data["source_sha256"], "source_cell": record["source_cells"][source],
                                   "sheet": data.get("sheet"),
                                   "dataset_dir": data["dataset_dir"], "source_field": source,
                                   "target_property": target, "unit": unit,
                                   "process": record.get("process"), "batch_id": record.get("batch_id")})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    content = buffer.getvalue().encode("utf-8-sig")
    report = validate_intake_csv("property_observations", content, project_root=project_root,
                                 contract_path=contract_path, id_policy_path=id_policy_path)
    evidence = {"adapter_version": ADAPTER_VERSION, "run_id": inspection.manifest["run_id"],
                "manifest_sha256": inspection.manifest_sha256, "input_fingerprint": inspection.manifest.get("input_fingerprint"),
                "bindings": bindings, "source_status": source_status, "provenance": provenance,
                "approvals": inspection.manifest["approvals"], "qc_warnings": inspection.warnings,
                "csv_sha256": hashlib.sha256(content).hexdigest()}
    return {"report": report, "csv": content, "evidence": evidence, "preview_sha256": _digest(evidence)}


def commit_run(run_dir, bindings, source_status, expected_preview_sha256, *, reviewer: str, note: str,
               confirmed: bool, project_root: Path = ROOT, contract_path: Path = CONTRACT_PATH,
               id_policy_path: Path = ID_POLICY_PATH) -> dict:
    """Re-open/verify/rebuild at click time; never accept edited staging rows."""
    if not confirmed or not reviewer.strip() or not note.strip():
        raise ValueError("需要人工确认、审核人和审核说明。")
    inspection = inspect_run(run_dir)
    candidate = prepare_intake(inspection, bindings, source_status, project_root=project_root,
                               contract_path=contract_path, id_policy_path=id_policy_path)
    if candidate["preview_sha256"] != expected_preview_sha256:
        raise ValueError("预览后结果、映射或来源状态发生变化，请重新预检并确认。")
    if candidate["report"]["status"] != "ready":
        raise ValueError("；".join(candidate["report"]["errors"]))
    package = save_intake_package(candidate["report"], output_root=project_root / "outputs" / "data_intake")
    evidence = {**candidate["evidence"], "reviewer": reviewer.strip(), "review_note": note.strip(),
                "source_run_dir": str(inspection.root), "preview_sha256": expected_preview_sha256}
    (package["package"] / "steeldata_provenance.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    try:
        result = commit_intake(candidate["report"], project_root=project_root,
                               contract_path=contract_path, id_policy_path=id_policy_path)
    except (ValueError, OSError) as exc:
        finalize_intake_package(package, {"status": "not_committed", "error": str(exc)})
        raise
    finalize_intake_package(package, result)
    return {**result, "intake_id": package["intake_id"], "run_id": inspection.manifest["run_id"],
            "manifest_sha256": inspection.manifest_sha256}


class SteelDataClient:
    """Fixed sibling location and fixed CLI verbs, not an arbitrary shell bridge."""

    def __init__(self, project: Path | None = None):
        self.project = (project or ROOT.parent / "SteelData").resolve()
        self.python = self.project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def availability(self) -> dict:
        try:
            descriptor = _json(_read(self.project / "steeldata.module.json", 65536))
            ready = (descriptor.get("module_id") == "steeldata" and descriptor.get("contract_version") == 1
                     and self.python.is_file() and (self.project / "steeldata" / "__main__.py").is_file())
        except (OSError, ValueError):
            ready = False
        return {"ready": ready, "project": str(self.project), "python": str(self.python)}

    def _call(self, args: list[str], *, accepted=(0,)) -> dict:
        if not self.availability()["ready"]:
            raise ValueError("未找到同级 SteelData 项目及其独立 .venv；已有结果包仍可只读检查。")
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"}}
        env["PYTHONUTF8"] = "1"
        try:
            completed = subprocess.run([str(self.python), "-B", "-m", "steeldata", *args],
                cwd=str(self.project), env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180, shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise ValueError("SteelData 超过 180 秒，已终止本次进程；请查看输出目录后拆分批次重试。") from exc
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise ValueError("SteelData 未返回有效 JSON：" + completed.stderr[-1200:]) from exc
        if completed.returncode not in accepted:
            raise ValueError(payload.get("message", f"SteelData 退出码 {completed.returncode}"))
        return payload

    def doctor(self) -> dict:
        return self._call(["doctor"])

    def list_suggestions(self) -> list[dict]:
        return self._call(["suggestion-list", "--workspace", str(self.project)]).get("suggestions", [])

    def show_suggestion(self, suggestion_id: str) -> dict:
        return self._call([
            "suggestion-show", "--workspace", str(self.project),
            "--suggestion-id", suggestion_id,
        ])

    def review_suggestion(self, suggestion: dict, decision: str, reviewer: str, note: str) -> dict:
        if decision not in {"approve", "reject"}:
            raise ValueError("审批决定必须是 approve 或 reject。")
        if not reviewer.strip() or not note.strip():
            raise ValueError("审批人和审批说明不能为空。")
        return self._call([
            "suggestion-review", "--workspace", str(self.project),
            "--suggestion-id", str(suggestion["suggestion_id"]),
            "--decision", decision,
            "--expected-revision", str(suggestion["revision"]),
            "--expected-sha256", str(suggestion["suggestion_sha256"]),
            "--reviewer", reviewer.strip(), "--note", note.strip(),
        ])

    def suggestion_execution_status(self, suggestion_id: str) -> dict:
        return self._call([
            "suggestion-execution-status", "--workspace", str(self.project),
            "--suggestion-id", suggestion_id,
        ])

    def execute_suggestion(self, suggestion_id: str, expected_sha256: str) -> dict:
        return self._call([
            "suggestion-execute", "--workspace", str(self.project),
            "--suggestion-id", suggestion_id,
            "--expected-sha256", expected_sha256,
        ])

    def intake_evaluation_contract(self) -> dict:
        return self._call(["intake-eval-contract"])

    def run_intake_reference_evaluation(self) -> dict:
        return self._call([
            "intake-eval-reference", "--output",
            str(self.project / "output" / "intake_agent_evaluations"),
        ])

    def run(self, input_dir: str, approval_files: list[str]) -> dict:
        root = Path(input_dir).resolve()
        if not input_dir.strip() or not root.is_dir() or not approval_files:
            raise ValueError("请选择只含本批实验数据的文件夹，并提供已人工批准的 JSON。")
        args = ["run", "--input", str(root)]
        for value in approval_files:
            approval = Path(value).resolve()
            if not approval.is_file():
                raise ValueError("找不到批准文件：" + str(approval))
            args.extend(["--approval", str(approval)])
        args.extend(["--output", str(self.project / "output" / "steelai_runs")])
        return self._call(args, accepted=(0, 2, 3))

    def demo(self) -> dict:
        return self._call(["demo", "--output", str(self.project / "output" / "steelai_demo")])

    def run_selected(self, data_files: list[tuple[str, bytes]], approval_files: list[tuple[str, bytes]]) -> dict:
        """Only selected files enter the batch. Full approval/QC still runs in SteelData.

        Temporary raw copies are removed on success or failure; completed result
        packages retain their normal source snapshots. Original user files are
        never opened for writing and no upload goes to a cloud model.
        """
        validate_selected_files(data_files, approval_files)
        with tempfile.TemporaryDirectory(prefix="steeldata-selected-") as temporary:
            root = Path(temporary)
            inputs, approvals = root / "inputs", root / "approvals"
            inputs.mkdir()
            approvals.mkdir()
            for name, content in data_files:
                with (inputs / name).open("xb") as handle:
                    handle.write(content)
            approval_paths = []
            for name, content in approval_files:
                path = approvals / name
                with path.open("xb") as handle:
                    handle.write(content)
                approval_paths.append(str(path))
            return self.run(str(inputs), approval_paths)
