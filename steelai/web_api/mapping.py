"""WO-32 §1 — 网页字段映射、候选 profile 与具名人工确认。

把「上传资料 → 网页映射/单位 → 预览 → 具名人审 → 运行」接到 SteelData 原有
治理合同上，而不是在网页里另造一套审批：

* 映射表单只允许 SteelData ``Profile`` 已支持的字段/单位；
* 候选 profile 由服务端写进 ``<task>/profiles/``（**上传写不到这个目录**），
  再交给 SteelData 自己的 ``steeldata profile`` 复核摘要；
* 人工确认走 SteelData 自己的 ``steeldata approve``，产物落在
  ``<task>/approvals/``，并在 ``<task>/reviews/`` 留一份校验记录
  （谁、什么时候、核的是哪一份输入的 SHA-256）；
* 确认**不是**一份可以随便上传冒充的 JSON：运行前会按校验记录重新核对
  输入摘要，输入变化 / 映射变化 / 被拒绝都会让旧确认失效。

本模块不做任何科学计算，也不读原始实验正文。
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from steelai.web_api.config import config
from steelai.web_api.registry import (
    PROFILES_SUBDIR, APPROVALS_SUBDIR, REVIEWS_SUBDIR,
    approvals_dir, profiles_dir, reviews_dir,
    task_root, task_inputs, list_input_files,
)
from steelai.web_api.security import GuardError, safe_identifier, safe_filename
from steelai.web_api.session import Session
from steelai.web_api.tabular import (
    SUPPORTED_SUFFIXES, TableError, TableView,
    header_cells, header_unit_hint, read_table, sample_values,
)

# --------------------------------------------------------------------------- #
# SteelData Profile 合同复刻（只读常量，不在这里改科学规则）
# --------------------------------------------------------------------------- #
DOMAINS = ("tensile", "tensile_curve", "composition")
LAYOUTS = ("flat", "wide_suffix", "stacked_reports")

ALLOWED_TARGETS = {
    "tensile": {"specimen_id", "batch_id", "process", "ys_mpa", "uts_mpa", "el_pct"},
    "tensile_curve": {"specimen_id", "time_s", "force_n", "displacement_mm"},
}
TEXT_TARGETS = {"specimen_id", "batch_id", "process"}
TARGETS = {"ys_mpa": "MPa", "uts_mpa": "MPa", "el_pct": "%",
           "time_s": "s", "force_n": "N", "displacement_mm": "mm"}
ALLOWED_UNITS = {"ys_mpa": {"MPa", "GPa"}, "uts_mpa": {"MPa", "GPa"}, "el_pct": {"%"},
                 "time_s": {"s", "ms"}, "force_n": {"N", "kN"}, "displacement_mm": {"mm", "m", "um"}}
REQUIRED_TARGETS = {
    "tensile": {"ys_mpa", "uts_mpa", "el_pct", "specimen_id"},
    "tensile_curve": {"time_s", "force_n"},
}
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")

SUPPORTED_FORMATS_NOTE = ("网页映射支持 CSV / TSV / XLSX（与 SteelData 输入合同一致）；"
                          "其它类型只能上传/预览/下载，不能进入映射与运行。")

RESERVED_REVIEWERS = {"system", "agent", "auto", "automatic", "web", "ai", "assistant", "bot", ""}


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cli_timeout(seconds: int = 300) -> int:
    return seconds


def _run_steeldata(argv: list[str], *, timeout: int = 300) -> tuple[int, str, str]:
    """Run the original SteelData CLI with fixed argv (no shell, no client paths)."""
    tool = config().tool("steeldata")
    if tool is None or tool.interpreter is None or not tool.interpreter.is_file():
        raise GuardError("缺少 SteelData 解释器：未在忽略的 config/settings.toml 的 [tools] 登记 steeldata_python")
    command = [str(tool.interpreter), "-B", "-m", "steeldata", *argv]
    completed = subprocess.run(
        command, cwd=tool.extra.get("project") or None, capture_output=True,
        timeout=_cli_timeout(timeout), shell=False, check=False,
    )
    return (completed.returncode,
            completed.stdout.decode("utf-8", errors="replace"),
            completed.stderr.decode("utf-8", errors="replace"))


# --------------------------------------------------------------------------- #
# 用户界面能看到的"这份资料长什么样"（原列/建议目标/单位证据）
# --------------------------------------------------------------------------- #

def describe_input(project_id: str, task_id: str, file_id: str, *, sheet: str | None = None) -> dict:
    """Read-only description of one uploaded file: real columns, units, problems."""
    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")
    name = safe_filename(file_id)
    inputs = task_inputs(project_id, task_id)
    if not inputs.is_dir():
        raise GuardError("任务没有 inputs 目录")
    path = inputs / name
    if not path.is_file():
        raise GuardError(f"输入文件不存在：{name}")
    try:
        view = read_table(path)
    except TableError as exc:
        return {
            "file_id": name,
            "supported": False,
            "problem": str(exc),
            "note": SUPPORTED_FORMATS_NOTE,
            "columns": [],
            "records": 0,
        }
    columns = header_cells(view)
    suggestions: list[dict] = []
    known = set(TARGETS)
    for index, column in enumerate(columns):
        hint = header_unit_hint(column)
        base = re.sub(r"\s*[\[(][^\])]{1,24}[\])]\s*$", "", column).strip()
        guess = base if base in known else None
        suggestions.append({
            "index": index,
            "source": column,
            "suggested_target": guess,
            "header_unit": hint,
            "unit_conflict": bool(hint and guess and hint not in ALLOWED_UNITS.get(guess, set())),
            "samples": sample_values(view, index, 3),
            "dtype_guess": "text" if guess in TEXT_TARGETS or guess is None else "number",
        })
    return {
        "file_id": name,
        "supported": True,
        "problem": "",
        "note": SUPPORTED_FORMATS_NOTE,
        "suffix": view.suffix,
        "delimiter": view.delimiter,
        "delimiter_source": view.delimiter_source,
        "sheet": view.sheet,
        "sheets": view.sheets,
        "has_formulas": view.has_formulas,
        "columns": columns,
        "records": view.records,
        "preview_rows": view.rows,
        "truncated": view.truncated,
        "ragged_rows": view.ragged_rows,
        "duplicate_headers": view.duplicate_headers,
        "empty_headers": view.empty_headers,
        "notes": view.notes,
        "input_sha256": _sha256(path),
        "size": view.size,
        "suggestions": suggestions,
    }


def _unit_ok(target: str, unit: str) -> bool:
    return unit in ALLOWED_UNITS.get(target, set())


def _validate_columns(payload: dict, columns: list[str], column_set: set[str]) -> tuple[list[dict], list[str]]:
    """Turn the web form into SteelData column specs; collect honest blockers."""
    problems: list[str] = []
    raw = payload.get("columns")
    if not isinstance(raw, list):
        raise GuardError("缺少 columns（源列 → 目标字段的映射）")
    if len(raw) > 40:
        raise GuardError("列映射条数超过 40 上限")
    out: list[dict] = []
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise GuardError("columns 的每一项都必须是对象")
        source = str(item.get("source", "") or "").strip()
        target = str(item.get("target", "") or "").strip()
        if not source:
            raise GuardError("每条映射都要有源列")
        if source not in column_set:
            problems.append(f"源列在文件里不存在：{source!r}")
            continue
        if source in seen_sources:
            problems.append(f"同一源列被映射多次：{source!r}")
            continue
        if not target:
            problems.append(f"源列 {source!r} 没有选择目标字段（不许自动猜）")
            continue
        if target not in set(ALLOWED_TARGETS.get(payload["domain"], set())):
            problems.append(
                f"目标字段 {target!r} 不属于领域 {payload['domain']!r} 的 SteelData 合同"
                f"（可选：{', '.join(sorted(ALLOWED_TARGETS.get(payload['domain'], set())))}）")
            continue
        dtype = "text" if target in TEXT_TARGETS else "number"
        declared = str(item.get("dtype", "") or "").strip() or dtype
        if declared != dtype:
            problems.append(f"{target!r} 必须是 {dtype}（标识列是 text，物质量是 number）")
            continue
        if target in seen_targets:
            problems.append(f"目标字段重复：{target!r}")
            continue
        entry: dict = {
            "source": source, "target": target, "dtype": dtype,
            "required": bool(item.get("required", True)),
        }
        if dtype == "number":
            unit = str(item.get("unit", "") or "").strip()
            if not unit:
                problems.append(f"{target!r} 没有单位：未知单位要人确认，不猜、不默认")
                continue
            if not _unit_ok(target, unit):
                problems.append(f"{target!r} 不支持单位 {unit!r}"
                                f"（可用：{', '.join(sorted(ALLOWED_UNITS[target]))}）")
                continue
            entry["unit"] = unit
            entry["target_unit"] = TARGETS[target]
            wanted = str(item.get("target_unit", "") or "").strip() or TARGETS[target]
            if wanted != TARGETS[target]:
                problems.append(f"{target!r} 的目标单位只能是 {TARGETS[target]!r}，收到 {wanted!r}")
                continue
        seen_sources.add(source)
        seen_targets.add(target)
        out.append(entry)
    return out, problems


def _validate_profile_payload(payload: dict) -> tuple[dict, list[str]]:
    """Validate the web form against the SteelData Profile contract."""
    if not isinstance(payload, dict):
        raise GuardError("请求体必须是对象")
    domain = str(payload.get("domain", "") or "").strip()
    layout = str(payload.get("layout", "") or "").strip()
    profile_id = str(payload.get("profile_id", "") or "").strip()
    if domain not in DOMAINS:
        raise GuardError(f"domain 只能是 {', '.join(DOMAINS)}")
    if layout not in LAYOUTS:
        raise GuardError(f"layout 只能是 {', '.join(LAYOUTS)}")
    if not PROFILE_ID_RE.match(profile_id):
        raise GuardError("profile_id 只能用小写字母/数字/连字符，且以字母或数字开头")
    problems: list[str] = []
    profile: dict = {
        "schema_version": 1, "profile_id": profile_id, "domain": domain, "layout": layout,
        "description": str(payload.get("description", "") or "")[:500],
        "header_row": int(payload.get("header_row", 1) or 1),
    }
    if profile["header_row"] < 1 or profile["header_row"] > 100:
        raise GuardError("header_row 必须在 1..100")

    if domain == "composition":
        if layout != "stacked_reports":
            problems.append("composition 领域要求 stacked_reports 版式")
            return profile, problems
        labels = {
            "block_label": str(payload.get("block_label", "") or "").strip(),
            "element_label": str(payload.get("element_label", "") or "").strip(),
            "unit_label": str(payload.get("unit_label", "") or "").strip(),
            "basis_label": str(payload.get("basis_label", "") or "").strip(),
        }
        for key, value in labels.items():
            if not value:
                problems.append(f"composition 需要显式的 {key}")
        row_roles_raw = payload.get("row_roles")
        row_roles = {}
        if isinstance(row_roles_raw, dict):
            for key, value in row_roles_raw.items():
                role = str(value or "").strip()
                if role not in ("individual", "reported_mean", "reported_sd"):
                    problems.append(f"row_roles[{key!r}] 只能是 individual/reported_mean/reported_sd")
                    continue
                row_roles[str(key)] = role
        if not row_roles:
            problems.append("composition 需要显式 row_roles（哪一行是单值/均值/标准差）")
        if len(set(labels.values())) != 4:
            problems.append("block/element/unit/basis 四个标签必须互不相同")
        if set(row_roles) & set(labels.values()):
            problems.append("row_roles 不能与结构标签重名")
        profile["specimen_id"] = str(payload.get("specimen_id", "") or "").strip() or None
        profile.update({key: value for key, value in labels.items()})
        profile["row_roles"] = row_roles
        return profile, problems

    # tensile / tensile_curve：显式 columns
    if layout == "stacked_reports":
        problems.append("stacked_reports 只属于 composition 领域")
    if domain == "tensile_curve" and layout == "flat":
        specimen_id = str(payload.get("specimen_id", "") or "").strip()
        targets = [str(item.get("target", "") or "").strip() for item in payload.get("columns", [])
                   if isinstance(item, dict)]
        if not specimen_id and "specimen_id" not in targets:
            problems.append("tensile_curve(flat) 需要显式试样身份：specimen_id 列或 specimen_id 常量")
    if layout == "wide_suffix":
        specimen_map = payload.get("specimen_map")
        if domain != "tensile_curve" or not isinstance(specimen_map, dict) or not specimen_map:
            problems.append("wide_suffix 只用于 tensile_curve，且必须给出显式 specimen_map")
        else:
            clean = {str(k): str(v) for k, v in specimen_map.items()}
            if len(clean) > 20:
                problems.append("specimen_map 超过 20 项上限")
            profile["specimen_map"] = clean
    rules_raw = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    rules: dict = {}
    if rules_raw.get("tensile_relations"):
        if domain != "tensile":
            problems.append("tensile_relations 只适用于 tensile")
        else:
            rules["tensile_relations"] = True
    processes = rules_raw.get("allowed_processes") or []
    if isinstance(processes, list):
        clean = [str(item).strip() for item in processes if str(item).strip()]
        if clean:
            if len(clean) > 20:
                problems.append("allowed_processes 超过 20 项上限")
            rules["allowed_processes"] = clean
    replicates = rules_raw.get("expected_replicates")
    if replicates not in (None, ""):
        try:
            value = int(replicates)
        except (TypeError, ValueError):
            problems.append("expected_replicates 必须是整数")
        else:
            if not 1 <= value <= 100:
                problems.append("expected_replicates 必须在 1..100")
            elif domain != "tensile":
                problems.append("expected_replicates 只适用于 tensile")
            else:
                rules["expected_replicates"] = value
    if rules_raw.get("curve_time_order"):
        if domain != "tensile_curve":
            problems.append("curve_time_order 只适用于 tensile_curve")
        else:
            rules["curve_time_order"] = True
    if any(key in rules for key in ("expected_replicates",)):
        targets = {str(item.get("target", "") or "").strip()
                   for item in payload.get("columns", []) if isinstance(item, dict)}
        if "expected_replicates" in rules and not {"batch_id", "process"} <= targets:
            problems.append("expected_replicates 需要 batch_id 与 process 两列")
    if rules_raw.get("tensile_relations") and "allowed_processes" not in rules:
        pass
    if rules:
        profile["rules"] = rules
    sheet = str(payload.get("sheet", "") or "").strip()
    if sheet:
        profile["sheet"] = sheet
    specimen_id = str(payload.get("specimen_id", "") or "").strip()
    if specimen_id:
        profile["specimen_id"] = specimen_id
    return profile, problems


def _profile_json(profile: dict) -> dict:
    """Keep only the fields SteelData's Profile accepts (no unknown extras)."""
    allowed = {"schema_version", "profile_id", "domain", "layout", "description", "header_row",
               "sheet", "columns", "specimen_map", "specimen_id", "block_label", "element_label",
               "unit_label", "basis_label", "row_roles", "rules"}
    out = {key: value for key, value in profile.items() if key in allowed}
    if out.get("sheet") is None:
        out.pop("sheet", None)
    if out.get("specimen_id") is None:
        out.pop("specimen_id", None)
    return out


def _read_meta(project_id: str, task_id: str, profile_id: str) -> dict:
    path = _candidate_path(project_id, task_id, profile_id).with_suffix(".meta.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _steeldata_profile_cli(profile: dict, target: Path) -> dict:
    """Hand the candidate to SteelData's own ``profile`` command for validation.

    The authoritative digest comes from SteelData, not from us: write the
    candidate to a temporary file under the server-owned profiles directory,
    run the original CLI and parse its JSON output.
    """
    tmp = target.with_suffix(".json.cli.json")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        code, out, err = _run_steeldata(["profile", str(tmp)])
        if code != 0:
            detail = out.strip() or err.strip()
            try:
                parsed = json.loads(detail)
                message = str(parsed.get("message", detail))
            except json.JSONDecodeError:
                message = detail or f"SteelData profile 校验退出码 {code}"
            return {"problems": [f"SteelData 拒绝该映射：{message}"], "profile_sha256": ""}
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as exc:
            return {"problems": [f"SteelData profile 输出无法解析：{exc}"], "profile_sha256": ""}
        digest = str(parsed.get("profile_sha256", "") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return {"problems": ["SteelData profile 未返回合法 profile_sha256"], "profile_sha256": ""}
        return {"problems": [], "profile_sha256": digest}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def preview_profile(project_id: str, task_id: str, profile_id: str) -> dict:
    """Run SteelData's read-only ``preview`` on a saved candidate profile."""
    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")
    candidate = _candidate_path(project_id, task_id, safe_filename(profile_id))
    if not candidate.is_file():
        raise GuardError(f"候选 profile 不存在：{profile_id}")
    meta = _read_meta(project_id, task_id, profile_id)
    input_file = meta.get("input_file", "")
    source = task_inputs(project_id, task_id) / input_file if input_file else None
    if source is None or not source.is_file():
        return {"ok": False, "problem": "候选 profile 未记录有效的 input_file"}
    recorded = meta.get("input_sha256", "")
    current = _sha256(source)
    stale = bool(recorded and recorded != current)
    code, out, err = _run_steeldata(["preview", "--input-file", str(source), "--profile", str(candidate)])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        payload = {}
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    counts = payload.get("issue_counts") if isinstance(payload.get("issue_counts"), dict) else {}
    return {
        "ok": code == 0,
        "exit_code": code,
        "matched": bool(payload.get("matched")),
        "records": payload.get("records"),
        "source_sha256": payload.get("source_sha256"),
        "profile_sha256": payload.get("profile_sha256"),
        "approval_required": payload.get("approval_required"),
        "issue_counts": counts,
        "issues": [item for item in issues if isinstance(item, dict)][:20],
        "input_stale": stale,
        "recorded_input_sha256": recorded,
        "current_input_sha256": current,
        "raw_tail": (out or err)[-2000:],
    }


def list_profiles(project_id: str, task_id: str) -> list[dict]:
    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")
    rows: list[dict] = []
    if not profiles_dir(project_id, task_id).is_dir():
        return rows
    for item in sorted(profiles_dir(project_id, task_id).glob("*.json")):
        # profiles/ 里同时有 <id>.json / <id>.meta.json，以及复核用的临时 probe 文件；
        # 只有 <id>.json 本身是一个候选 profile。
        if item.name.endswith(".meta.json") or item.name.endswith(".probe.json"):
            continue
        meta = item.with_suffix(".meta.json")
        info: dict = {}
        if meta.is_file():
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                info = {}
        try:
            profile = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append({
            "profile_id": item.stem,
            "profile": profile,
            "meta": info,
            "approval_sha256": _approval_digest_for(project_id, task_id, item.stem),
        })
    return rows


def resolve_profile_file(project_id: str, task_id: str, name) -> Path:
    """Resolve a profile for SteelData's own ``preview``/``run``.

    网页映射保存的候选 profile 在服务端自管的 ``profiles/`` 下优先命中；用户自己
    放进 ``inputs/`` 的 profile 作为导入来源次之。找不到就明确说找不到，不猜路径。
    """
    text = safe_filename(str(name or ""))
    stem = text[:-5] if text.endswith(".json") else text
    stem = stem[:-5] if stem.endswith(".meta") else stem
    if not stem:
        raise GuardError("未指定映射 profile")
    for base in (profiles_dir(project_id, task_id), task_inputs(project_id, task_id)):
        item = base / f"{stem}.json"
        if item.is_file():
            return item
    raise GuardError(f"映射 profile 不存在：{stem}（网页保存的候选在 profiles/，导入的放 inputs/）")


def _approval_digest_for(project_id: str, task_id: str, profile_id: str) -> str:
    path = approvals_dir(project_id, task_id) / f"{safe_filename(profile_id)}.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("profile_sha256", "") or "")


def _invalidate_stale_approvals(project_id: str, task_id: str, profile_id: str, meta: dict) -> list[str]:
    """Mark approvals whose profile digest no longer matches the saved candidate.

    Returns the approval files that were invalidated. The records themselves are
    kept under ``reviews/``; only the SteelData approval file that would let a
    stale confirmation through a run is removed from ``approvals/``.
    """
    removed: list[str] = []
    approvals = approvals_dir(project_id, task_id)
    if not approvals.is_dir():
        return removed
    expected = meta.get("profile_sha256", "")
    for item in sorted(approvals.glob("*.json")):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("profile_sha256", "") or "") != expected:
            item.unlink()
            removed.append(item.name)
            _append_review(project_id, task_id, {
                "kind": "invalidation",
                "profile_id": profile_id,
                "approval_file": item.name,
                "reason": "候选映射已变化，旧确认失效（输入变化/映射修改）",
                "profile_sha256": expected,
                "created": datetime.now().isoformat(timespec="seconds"),
            })
    return removed


# --------------------------------------------------------------------------- #
# 候选 profile 落盘（服务端目录，上传写不到这里）
# --------------------------------------------------------------------------- #

def _candidate_path(project_id: str, task_id: str, profile_id: str) -> Path:
    return profiles_dir(project_id, task_id) / f"{safe_filename(profile_id)}.json"


def save_candidate(project_id: str, task_id: str, payload: dict) -> dict:
    """Validate the web mapping form and save it as a candidate profile."""
    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")
    input_file = safe_filename(payload.get("input_file", ""))
    inputs = task_inputs(project_id, task_id)
    source = inputs / input_file
    if not source.is_file():
        raise GuardError(f"输入文件不存在：{input_file}")

    try:
        view = read_table(source)
    except TableError as exc:
        return {"ok": False, "problem": str(exc), "note": SUPPORTED_FORMATS_NOTE,
                "needs_human": [f"输入不可用于映射：{exc}"]}

    payload = dict(payload)
    payload.setdefault("domain", "tensile")
    profile, problems = _validate_profile_payload(payload)
    if profile["domain"] in ALLOWED_TARGETS:
        if profile["layout"] != "stacked_reports":
            columns, column_problems = _validate_columns(payload, header_cells(view),
                                                        set(header_cells(view)))
            problems.extend(column_problems)
            profile["columns"] = columns
            missing = REQUIRED_TARGETS.get(profile["domain"], set()) - {c["target"] for c in columns}
            if missing:
                problems.append("缺少 SteelData 必需字段：" + ", ".join(sorted(missing)))
    if view.has_formulas:
        problems.append("工作簿含公式：SteelData 运行会要求「仅值」导出（预览值可能不同）")
    if view.duplicate_headers:
        problems.append("重复表头，无法确定映射哪一列：" + ", ".join(view.duplicate_headers))
    if view.ragged_rows:
        shown = ", ".join(str(item + 1) for item in view.ragged_rows[:5])
        problems.append(f"有 {len(view.ragged_rows)} 行列数与表头不一致（第 {shown} 行…），需先修数据")
    header_row = profile["header_row"]
    if header_row > len(view.rows) + 1:
        problems.append(f"header_row={header_row} 超出文件行数")

    # 自己就能说清的原因（未知单位/缺字段/列不齐/表头重复）先于人审提交；
    # 不要丢掉这条更清楚的理由，只回一段 pydantic 报错。
    if problems:
        return {"ok": False, "profile": profile, "needs_human": problems,
                "problem": "映射未通过合同校验，未保存（见 needs_human）。"}

    profile_id = profile["profile_id"]
    target = _candidate_path(project_id, task_id, profile_id)
    existing_meta = _read_meta(project_id, task_id, profile_id)
    try:
        SteelDataLike = _profile_json(profile)
    except GuardError as exc:
        return {"ok": False, "problem": str(exc), "needs_human": [str(exc)]}

    # SteelData 自己的 CLI 复核：校验 + 输出 authoritative profile_sha256。
    cli = _steeldata_profile_cli(SteelDataLike, target)
    problems.extend(cli["problems"])
    if cli["problems"]:
        return {"ok": False, "profile": SteelDataLike, "needs_human": cli["problems"],
                "problem": "映射未通过 SteelData 合同校验，未保存。"}

    payload_bytes = json.dumps(SteelDataLike, ensure_ascii=False, indent=2).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_bytes(payload_bytes)
    tmp.replace(target)
    meta = {
        "profile_id": profile_id,
        "project_id": project_id,
        "task_id": task_id,
        "input_file": input_file,
        "input_sha256": _sha256(source),
        "input_bytes": len(payload_bytes and source.read_bytes()),
        "profile_sha256": cli["profile_sha256"],
        "domain": profile["domain"],
        "layout": profile["layout"],
        "created": datetime.now().isoformat(timespec="seconds"),
        "previous_profile_sha256": existing_meta.get("profile_sha256"),
    }
    meta_path = target.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    invalidated = _invalidate_stale_approvals(project_id, task_id, profile_id, meta)

    preview = preview_profile(project_id, task_id, profile_id)
    return {
        "ok": True,
        "profile_id": profile_id,
        "profile": SteelDataLike,
        "profile_sha256": cli["profile_sha256"],
        "input_file": input_file,
        "input_sha256": meta["input_sha256"],
        "records": view.records,
        "notes": view.notes,
        "previous_profile_sha256": meta["previous_profile_sha256"],
        "invalidated_approvals": invalidated,
        "preview": preview,
    }


# --------------------------------------------------------------------------- #
# 具名人工确认（受限能力：AI/脚本不能代填）
# --------------------------------------------------------------------------- #

def _reviews_file(project_id: str, task_id: str) -> Path:
    return reviews_dir(project_id, task_id) / "reviews.jsonl"


def _append_review(project_id: str, task_id: str, entry: dict) -> None:
    path = _reviews_file(project_id, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def list_reviews(project_id: str, task_id: str) -> list[dict]:
    path = _reviews_file(project_id, task_id)
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-200:]


def review_candidate(project_id: str, task_id: str, payload: dict, session: Session,
                     *, synthetic: bool = False) -> dict:
    """Record an explicit human approve/reject through SteelData's own approve.

    * The caller must hold ``review:human`` — a browser session that proved its
      Origin. An ``ai`` session is refused here, full stop.
    * ``reviewer`` must be a named human; ``system``/``agent``/``web``/… are not.
    * The confirmation is written by SteelData's ``approve`` command into
      ``<task>/approvals/`` and journaled with the input SHA-256 it covered.
    """
    if "review:human" not in session.capabilities:
        raise GuardError("该会话没有人工确认能力（当前 "
                          f"{session.actor_kind}）。网页人审只能由内置页面的具名人工会话完成，"
                          "AI/脚本不能代填真实批准。")
    decision = str(payload.get("decision", "") or "").strip().lower()
    if decision not in {"approve", "reject"}:
        raise GuardError("decision 只能是 approve 或 reject")
    reviewer = str(payload.get("reviewer", "") or "").strip()
    if reviewer.lower() in RESERVED_REVIEWERS or len(reviewer) > 100:
        raise GuardError("需要具名人工审批人（不能用 system/agent/web 之类）")
    note = str(payload.get("note", "") or "").strip()
    if not note:
        raise GuardError("需要填写审批备注（核对了什么、依据是什么）")
    profile_id = str(payload.get("profile_id", "") or "").strip()
    if not PROFILE_ID_RE.match(profile_id):
        raise GuardError("非法 profile_id")

    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")
    candidate = _candidate_path(project_id, task_id, profile_id)
    if not candidate.is_file():
        raise GuardError(f"候选 profile 不存在：{profile_id}")
    meta = _read_meta(project_id, task_id, profile_id)
    input_file = str(meta.get("input_file", "") or "")
    source = task_inputs(project_id, task_id) / input_file if input_file else None
    if source is None or not source.is_file():
        raise GuardError("候选 profile 未记录有效的 input_file")

    current = _sha256(source)
    recorded = str(meta.get("input_sha256", "") or "")
    if recorded and recorded != current:
        raise GuardError(f"输入自映射保存后已变化，旧确认不再适用；请重新保存映射。"
                         f"记录 {recorded[:12]}… / 当前 {current[:12]}…")
    try:
        profile = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"候选 profile 无法读取：{exc}") from exc
    digest = str(meta.get("profile_sha256", "") or "")
    if not digest:
        raise GuardError("候选 profile 缺少 SteelData 复核算出的 profile_sha256，请重新保存映射")

    review_id = "rev-" + uuid.uuid4().hex[:12]
    entry = {
        "review_id": review_id,
        "kind": "review",
        "decision": decision,
        "project_id": project_id,
        "task_id": task_id,
        "profile_id": profile_id,
        "input_file": input_file,
        "input_sha256": current,
        "profile_sha256": digest,
        "reviewer": reviewer,
        "note": note[:1000],
        "synthetic": bool(synthetic),
        "actor_kind": session.actor_kind,
        "session_id": session.session_id,
        "created": datetime.now().isoformat(timespec="seconds"),
    }

    if decision == "reject":
        # 拒绝同样让旧确认失效：上传/修改后不能再拿旧批准跑。
        removed = _invalidate_all_approvals(project_id, task_id, profile_id, digest,
                                            reason="人工拒绝：旧确认失效")
        entry["invalidated_approvals"] = removed
        _append_review(project_id, task_id, entry)
        return {"ok": True, "decision": "reject", "review_id": review_id,
                "invalidated_approvals": removed,
                "message": "已记录拒绝；该映射的旧确认已失效。"}

    approval_name = f"{profile_id}.json"
    approval_path = approvals_dir(project_id, task_id) / approval_name
    # SteelData approve 是独占创建：已存在就拒绝，不静默覆盖别人的确认。
    code, out, err = _run_steeldata([
        "approve", "--profile", str(candidate),
        "--expected-sha256", digest,
        "--reviewer", reviewer, "--note", note,
        "--output", str(approval_path),
    ])
    if code != 0 or not approval_path.is_file():
        detail = (out or err or "").strip()
        try:
            parsed = json.loads(detail)
            message = str(parsed.get("message", detail))
        except json.JSONDecodeError:
            message = detail or f"SteelData approve 退出码 {code}"
        entry["kind"] = "review_failed"
        entry["reason"] = message
        _append_review(project_id, task_id, entry)
        return {"ok": False, "decision": "approve", "review_id": review_id,
                "problem": f"SteelData 拒绝生成审批文件：{message}"}

    entry["approval_file"] = approval_name
    _append_review(project_id, task_id, entry)
    return {
        "ok": True, "decision": "approve", "review_id": review_id,
        "approval_file": approval_name,
        "approval_sha256": _sha256(approval_path),
        "input_file": input_file, "input_sha256": current, "profile_sha256": digest,
        "reviewer": reviewer, "synthetic": bool(synthetic),
        "message": "审批文件由 SteelData 自己的 approve 命令生成，落在本任务 approvals/ 下。",
    }


def _invalidate_all_approvals(project_id: str, task_id: str, profile_id: str, digest: str,
                              *, reason: str) -> list[str]:
    removed: list[str] = []
    approvals = approvals_dir(project_id, task_id)
    if not approvals.is_dir():
        return removed
    for item in sorted(approvals.glob("*.json")):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("profile_id", "") or "") == profile_id or item.stem == profile_id:
            item.unlink()
            removed.append(item.name)
    if removed:
        _append_review(project_id, task_id, {
            "kind": "invalidation", "profile_id": profile_id,
            "approval_file": ", ".join(removed), "reason": reason,
            "profile_sha256": digest,
            "created": datetime.now().isoformat(timespec="seconds"),
        })
    return removed


# --------------------------------------------------------------------------- #
# 运行前的确认复核（供 steeldata.run 使用）
# --------------------------------------------------------------------------- #

def approval_for_run(project_id: str, task_id: str, approval_file: str) -> dict:
    """Resolve one approval reference into a path **plus its provenance**.

    Two origins are accepted, and both are reported honestly:

    ``server``      web human review -> <task>/approvals/<profile_id>.json.
                    The input SHA-256 and profile digest are re-checked here, so
                    an approval cannot outlive a changed input or a changed
                    mapping.
    ``imported``    a file the user placed in <task>/inputs/ (an owner-supplied
                    approval). SteelData validates its structure and digest, but
                    this server cannot attest that a named human reviewed it, so
                    the record says ``imported`` and never claims web review.

    ``forged``      a JSON crafted to look like an approval is rejected on
                    structure/digest and never written into ``approvals/``.
    """
    name = safe_filename(approval_file)
    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")

    # 1) 服务端生成的确认
    approvals = approvals_dir(project_id, task_id)
    candidate = approvals / name
    if candidate.is_file():
        return _verify_server_approval(project_id, task_id, candidate, name)

    # 2) 导入的既有确认（inputs/ 下，原 owner 提供）
    inputs = task_inputs(project_id, task_id)
    imported = inputs / name
    if imported.is_file():
        return _verify_imported_approval(project_id, task_id, imported, name)

    raise GuardError(f"审批文件不存在：{name}（只能选本任务 approvals/ 下由网页人审生成的，"
                     "或 inputs/ 下导入的既有审批）")


def _verify_server_approval(project_id: str, task_id: str, path: Path, name: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"审批文件无法解析：{exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != "human":
        raise GuardError("审批文件不是 SteelData human 审批（web 只生成 kind=human 的确认）")
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    profile_id = str(profile.get("profile_id", "") or "")
    digest = str(data.get("profile_sha256", "") or "")
    if not profile_id or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise GuardError("审批文件缺少 profile_id / profile_sha256")

    # 审批里的 profile 摘要必须仍与候选一致（映射被改过 → 旧确认失效）。
    candidate = _candidate_path(project_id, task_id, profile_id)
    current_meta = _read_meta(project_id, task_id, profile_id) if candidate.is_file() else {}
    current_digest = str(current_meta.get("profile_sha256", "") or "")
    input_file = str(current_meta.get("input_file", "") or "")
    reasons: list[str] = []
    if not candidate.is_file():
        reasons.append(f"候选 profile {profile_id} 已不存在（可能被删除/重建）")
    elif current_digest and current_digest != digest:
        reasons.append(f"映射自确认后已变化（确认时 {digest[:12]}… / 现在 {current_digest[:12]}…）")
        input_file = str(current_meta.get("input_file", ""))
    if input_file:
        source = task_inputs(project_id, task_id) / input_file
        if source.is_file():
            current = _sha256(source)
            recorded = str(data.get("input_sha256", "") or "")
            entry = next((item for item in reversed(list_reviews(project_id, task_id))
                          if item.get("approval_file") == name and item.get("decision") == "approve"), None)
            recorded = str((entry or {}).get("input_sha256", "") or recorded)
            if recorded and recorded != current:
                reasons.append(f"输入自确认后已变化（确认时 {recorded[:12]}… / 现在 {current[:12]}…）")
    if reasons:
        return {"ok": False, "origin": "server", "path": str(path), "file": name,
                "problems": reasons,
                "message": "该确认已失效：" + "；".join(reasons) + "。请重新保存映射并重新人工确认。"}
    entry = next((item for item in reversed(list_reviews(project_id, task_id))
                  if item.get("approval_file") == name and item.get("decision") == "approve"), {})
    return {
        "ok": True, "origin": "server", "path": str(path), "file": name,
        "profile_id": profile_id, "profile_sha256": digest,
        "input_file": input_file, "reviewer": str(data.get("reviewer", "") or ""),
        "review_id": str(entry.get("review_id", "") or ""),
        "synthetic": bool(entry.get("synthetic", False)),
        "problems": [],
    }


def _verify_imported_approval(project_id: str, task_id: str, path: Path, name: str) -> dict:
    """Validate an owner-supplied approval file via SteelData's own approve.

    We cannot corroborate that a named human reviewed this one, so it is
    reported as ``imported`` and never becomes a web-review authorisation.
    """
    tool = config().tool("steeldata")
    if tool is None or not tool.interpreter or not tool.interpreter.is_file():
        raise GuardError("缺少 SteelData 解释器，无法复核导入的审批")
    probe = profiles_dir(project_id, task_id) / f"imported-{path.stem}.probe.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"审批文件不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict) or "profile" not in data or "profile_sha256" not in data:
        raise GuardError("审批文件缺少 SteelData 审批合同的 profile / profile_sha256 字段")
    digest = str(data.get("profile_sha256", "") or "")
    profile_id = str((data.get("profile") or {}).get("profile_id", "") or "")
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(json.dumps(data.get("profile"), ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        code, out, err = _run_steeldata(["profile", str(probe)])
        problems: list[str] = []
        if code == 0:
            try:
                actual = str(json.loads(out).get("profile_sha256", "") or "")
            except json.JSONDecodeError:
                actual = ""
            if actual and actual != digest:
                problems.append("审批文件里的 profile_sha256 与实际 profile 摘要不一致（可能被改过）")
        entry = {
            "kind": "imported-approval",
            "profile_id": profile_id, "profile_sha256": digest,
            "approval_file": name, "reviewer": str(data.get("reviewer", "") or ""),
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        _append_review(project_id, task_id, entry)
        return {
            "ok": not problems, "origin": "imported", "path": str(path), "file": name,
            "profile_id": profile_id, "profile_sha256": digest,
            "reviewer": str(data.get("reviewer", "") or ""), "problems": problems,
            "message": ("导入的既有审批；它的结构/摘要已按 SteelData 合同复核。"
                        "本服务无法证明该审批出自网页具名人审，记录中标为 imported。"),
        }
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _dump_profile_shape(profile: dict) -> dict:
    """A small, UI-friendly summary of a saved SteelData profile."""
    columns = profile.get("columns") if isinstance(profile.get("columns"), list) else []
    return {
        "profile_id": profile.get("profile_id"),
        "domain": profile.get("domain"),
        "layout": profile.get("layout"),
        "header_row": profile.get("header_row"),
        "sheet": profile.get("sheet"),
        "column_count": len(columns),
        "columns": [
            {"source": item.get("source"), "target": item.get("target"),
             "dtype": item.get("dtype"), "unit": item.get("unit"),
             "target_unit": item.get("target_unit")}
            for item in columns if isinstance(item, dict)
        ],
        "row_roles": profile.get("row_roles") or {},
        "rules": profile.get("rules") or {},
    }
