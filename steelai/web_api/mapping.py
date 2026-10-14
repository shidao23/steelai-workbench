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
import threading
import uuid
from datetime import datetime
from pathlib import Path

from steelai.web_api.config import config
from steelai.web_api.registry import (
    PROFILES_SUBDIR, APPROVALS_SUBDIR, REVIEWS_SUBDIR,
    approvals_dir, profiles_dir, reviews_dir,
    task_root, task_inputs, list_input_files,
)
from steelai.web_api.security import ConflictError, GuardError, safe_identifier, safe_filename
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

# WO-34 §1：一次「确认」必须绑定人所看见的**完整对象**（项目/任务/profile 身份、
# 输入 file_id+字节 SHA、profile 内容 SHA、有效修订、逻辑表头）。核对与落盘之间
# 若有并发的保存/换绑/拒绝，就不能「核旧值后落盘新对象」。这里用一把进程内可重入锁
# 串行化 save_candidate / review_candidate 的关键段——服务是单进程回环服务，
# 这是最小实现；不引入企业锁服务。SteelData 自己的 approve --expected-sha256
# 仍是第二道闸（profile 文件在核对后被换，CLI 会拒绝）。
_CONTENT_LOCK = threading.RLock()


def _content_fingerprint(*, input_file: str, input_sha256: str, profile_sha256: str,
                         sheet: str | None, header_row: int) -> str:
    """A digest over the **effective content** a confirmation covers.

    它把「输入身份 + 输入字节 + profile 内容 + 逻辑表」合在一起：任一变化都算
    新的有效版本（revision +1、旧确认失效）；只有四项全同才算「无变化重存」。
    """
    import hashlib

    canonical = json.dumps({
        "input_file": str(input_file or ""),
        "input_sha256": str(input_sha256 or ""),
        "profile_sha256": str(profile_sha256 or ""),
        "sheet": str(sheet or ""),
        "header_row": int(header_row or 1),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def confirmation_snapshot(project_id: str, task_id: str, profile_id: str) -> dict:
    """The server-generated, immutable "what the human is looking at" object.

    WO-34 §1：前端必须从**实际展示的对象**读取这份快照，并在确认时原样交回；
    服务端按同一快照做 compare-and-set，缺字段/过期/不同一律 409。它不是前端
    自己拼出来的摘要——project/task/profile 身份、输入 file_id+SHA、profile
    内容 SHA、有效修订都在服务端这里生成。
    """
    meta = _read_meta(project_id, task_id, profile_id)
    return {
        "project_id": project_id,
        "task_id": task_id,
        "profile_id": str(meta.get("profile_id") or profile_id),
        "input_file": str(meta.get("input_file", "") or ""),
        "input_sha256": str(meta.get("input_sha256", "") or ""),
        "input_bytes": int(meta.get("input_bytes") or 0),
        "profile_sha256": str(meta.get("profile_sha256", "") or ""),
        "revision": int(meta.get("revision") or 0),
        "content_fingerprint": str(meta.get("content_fingerprint", "") or ""),
        "sheet": meta.get("sheet") or "",
        "header_row": int(meta.get("header_row") or 1),
        "domain": str(meta.get("domain", "") or ""),
        "layout": str(meta.get("layout", "") or ""),
    }


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

def describe_input(project_id: str, task_id: str, file_id: str, *,
                   sheet: str | None = None, header_row: int = 1) -> dict:
    """Read-only description of one uploaded file: real columns, units, problems.

    ``sheet``/``header_row`` 是**用户实际选的那张表与那一行**；默认值只是让页面
    先有东西可看，多工作表时会明确标 ``sheet_required``，不假装第一张表就是答案。
    """
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
    if header_row < 1 or header_row > 100:
        raise GuardError("header_row 必须在 1..100")
    try:
        view = read_table(path, sheet=sheet or None, header_row=header_row)
    except TableError as exc:
        return {
            "file_id": name,
            "supported": False,
            "problem": str(exc),
            "note": SUPPORTED_FORMATS_NOTE,
            "columns": [],
            "records": 0,
            "sheet": sheet or None,
            "sheets": [],
            "sheet_required": False,
            "header_row": header_row,
            "input_sha256": _sha256(path),
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
        "sheet_required": view.sheet_required,
        "header_row": view.header_row,
        "has_formulas": view.has_formulas,
        "cached_rows": view.cached_rows,
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
            "snapshot": confirmation_snapshot(project_id, task_id, item.stem),
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


def _archive_approval(project_id: str, task_id: str, item: Path) -> str:
    """Move a superseded approval out of ``approvals/`` but keep the evidence.

    WO-33 §2：被引用过的审批版本不能被悄悄擦掉。失效的审批文件挪到
    ``reviews/invalidated/``（带时间戳前缀，只追加、不覆盖），这样
    ``approvals/`` 里不会留下能被误用的旧授权，而历史证据仍在任务目录内。
    """
    import shutil

    archive = reviews_dir(project_id, task_id) / "invalidated"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = archive / f"{stamp}__{item.name}"
    if target.exists():  # pragma: no cover - same-second double invalidation
        target = archive / f"{stamp}__{uuid.uuid4().hex[:6]}__{item.name}"
    try:
        shutil.move(str(item), str(target))
    except OSError:
        try:
            item.unlink()
        except OSError:
            pass
        return ""
    return target.relative_to(reviews_dir(project_id, task_id)).as_posix()


def _invalidate_stale_approvals(project_id: str, task_id: str, profile_id: str, meta: dict) -> list[str]:
    """Invalidate **only this profile's** approval when its **effective content** changed.

    WO-32 的实现遍历了全任务的审批并逐份比对摘要，于是「保存一份无关的
    profile」会把别的 profile 的有效批准一起删掉（WO-33 §2 第 3 条复现）。
    这里只处理 ``profile_id`` 自己的审批文件。

    WO-34 §1：审批绑定的是「人所看见的那份输入与版本」，所以失效判据不只看
    profile 摘要，还要看**输入身份（file_id）+ 字节 SHA**——把同字节的 ``a.csv``
    改绑成 ``same.csv`` 也必须让旧确认失效，否则 SHA 相同就能被暗批：

    * 有效内容指纹一致（同一 profile 原样重存）→ 不动，批准继续有效；
    * 指纹变化 → 该审批失效，挪进 ``reviews/invalidated/`` 并只追加一条记录；
    * 其它 profile 的审批**完全不碰**。

    Returns the approval files that were invalidated (as archived names).
    """
    removed: list[str] = []
    approvals = approvals_dir(project_id, task_id)
    if not approvals.is_dir():
        return removed
    expected = str(meta.get("content_fingerprint", "") or "")
    expected_profile = str(meta.get("profile_sha256", "") or "")
    item = approvals / f"{safe_filename(profile_id)}.json"
    if not item.is_file():
        return removed
    try:
        data = json.loads(item.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return removed
    bound_id = str((data.get("profile") or {}).get("profile_id", "") or "")
    if bound_id and bound_id != profile_id:
        # 文件名与内容指向不同 profile：不认这份审批，也不动别人的。
        return removed

    # 审批当时复核记录里的输入身份（file_id + 字节 SHA）与内容指纹。
    entry = next((row for row in reversed(list_reviews(project_id, task_id))
                  if row.get("approval_file") == item.name and row.get("decision") == "approve"), {})
    bound_input_file = str(entry.get("input_file", "") or "")
    bound_input_sha = str(entry.get("input_sha256", "") or "")
    approval_profile_sha = str(data.get("profile_sha256", "") or "")
    bound_fingerprint = str(entry.get("content_fingerprint", "") or "")

    # 无变化重存：有效内容指纹一致 → 批准继续有效（不因每次点击保存而无意义撤销）。
    if expected and bound_fingerprint and bound_fingerprint == expected:
        return removed
    # 没有指纹记录的旧审批：退回到「profile 摘要 + 输入身份」逐项比对。
    same_profile = approval_profile_sha == expected_profile
    same_input_identity = (
        (not bound_input_file or bound_input_file == str(meta.get("input_file", "") or ""))
        and (not bound_input_sha or bound_input_sha == str(meta.get("input_sha256", "") or ""))
    )
    if same_profile and same_input_identity:
        return removed

    archived = _archive_approval(project_id, task_id, item)
    removed.append(item.name)
    reasons = []
    if not same_profile:
        reasons.append("映射内容已变化")
    if not same_input_identity:
        reasons.append("输入身份或字节已变化")
    _append_review(project_id, task_id, {
        "kind": "invalidation",
        "profile_id": profile_id,
        "approval_file": item.name,
        "archived_as": archived,
        "reason": "该确认覆盖的输入/映射已变化，旧确认失效（只影响这一个 profile）："
                  + "、".join(reasons),
        "previous_profile_sha256": approval_profile_sha,
        "profile_sha256": expected_profile,
        "bound_input_file": bound_input_file,
        "current_input_file": str(meta.get("input_file", "") or ""),
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

    # 用户选的那张表/那一行必须先进 read_table，否则「预览看到的列」与「保存的映射」
    # 会针对不同的工作表——这正是 WO-33 §1 要求消除的不一致。
    wanted_sheet = str(payload.get("sheet", "") or "").strip() or None
    try:
        wanted_header = int(payload.get("header_row", 1) or 1)
    except (TypeError, ValueError):
        raise GuardError("header_row 必须是整数") from None
    if not 1 <= wanted_header <= 100:
        raise GuardError("header_row 必须在 1..100")
    try:
        view = read_table(source, sheet=wanted_sheet, header_row=wanted_header)
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
        problems.append("工作簿含公式：SteelData 会拒绝这种文件，需先导出「仅值」版本"
                        "（预览另列的缓存值仅供辨认，不是本次运行会读到的内容）")
    if view.sheet_required and not wanted_sheet:
        problems.append("该工作簿有多个工作表（" + "、".join(view.sheets) +
                        "）：SteelData 要求 profile 显式写明 sheet，请先选定要用的工作表")
    if view.duplicate_headers:
        problems.append("重复表头，无法确定映射哪一列：" + ", ".join(view.duplicate_headers))
    if view.ragged_rows:
        shown = ", ".join(str(item + 1) for item in view.ragged_rows[:5])
        problems.append(f"有 {len(view.ragged_rows)} 行列数与表头不一致（第 {shown} 行…），需先修数据")
    header_row = profile["header_row"]
    if header_row != view.header_row:
        problems.append(f"header_row={header_row} 与实际读表用的第 {view.header_row} 行不一致，"
                        "请重新读取该输入后再保存")

    # 自己就能说清的原因（未知单位/缺字段/列不齐/表头重复）先于人审提交；
    # 不要丢掉这条更清楚的理由，只回一段 pydantic 报错。
    if problems:
        return {"ok": False, "profile": profile, "needs_human": problems,
                "problem": "映射未通过合同校验，未保存（见 needs_human）。"}

    profile_id = profile["profile_id"]
    target = _candidate_path(project_id, task_id, profile_id)
    input_sha = _sha256(source)
    try:
        SteelDataLike = _profile_json(profile)
    except GuardError as exc:
        return {"ok": False, "problem": str(exc), "needs_human": [str(exc)]}

    # WO-34 §1：整个「读旧 meta → 写候选/新 meta → 按指纹失效旧确认」必须在同一把
    # 进程内锁里完成，否则并发的保存/换绑可能「核旧值后落盘新对象」。
    with _CONTENT_LOCK:
        existing_meta = _read_meta(project_id, task_id, profile_id)
        # SteelData 自己的 CLI 复核：校验 + 输出 authoritative profile_sha256。
        cli = _steeldata_profile_cli(SteelDataLike, target)
        problems.extend(cli["problems"])
        if cli["problems"]:
            return {"ok": False, "profile": SteelDataLike, "needs_human": cli["problems"],
                    "problem": "映射未通过 SteelData 合同校验，未保存。"}

        fingerprint = _content_fingerprint(
            input_file=input_file, input_sha256=input_sha,
            profile_sha256=cli["profile_sha256"], sheet=view.sheet, header_row=view.header_row)
        previous_fingerprint = str(existing_meta.get("content_fingerprint", "") or "")
        # 只有**有效内容**变化才 +1：真正相同的输入身份/字节/映射重存不递增，
        # 也就不会无意义地撤销批准（WO-34 §1）。
        unchanged = bool(previous_fingerprint) and previous_fingerprint == fingerprint
        revision = int(existing_meta.get("revision") or 0) + (0 if unchanged else 1)
        if revision < 1:
            revision = 1

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
            "input_sha256": input_sha,
            "input_bytes": source.stat().st_size,
            "profile_sha256": cli["profile_sha256"],
            "domain": profile["domain"],
            "layout": profile["layout"],
            "sheet": view.sheet,
            "header_row": view.header_row,
            "revision": revision,
            "content_fingerprint": fingerprint,
            "created": datetime.now().isoformat(timespec="seconds"),
            "previous_profile_sha256": existing_meta.get("profile_sha256"),
        }
        meta_path = target.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        invalidated = _invalidate_stale_approvals(project_id, task_id, profile_id, meta)
        snapshot = confirmation_snapshot(project_id, task_id, profile_id)

    preview = preview_profile(project_id, task_id, profile_id)
    return {
        "ok": True,
        "profile_id": profile_id,
        "profile": SteelDataLike,
        "profile_sha256": cli["profile_sha256"],
        "input_file": input_file,
        "input_sha256": input_sha,
        "revision": revision,
        "unchanged": unchanged,
        "content_fingerprint": fingerprint,
        "snapshot": snapshot,
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

    * The caller must hold ``review:human`` — a browser session that completed
      the local pairing. An ``ai`` session is refused here, full stop.
    * ``reviewer`` must be a named human; ``system``/``agent``/``web``/… are not.
    * WO-33 §2: the caller must submit the **exact snapshot it displayed**
      (``expected_profile_sha256`` + ``expected_input_sha256``). This is a
      compare-and-set: a mismatch is a 409 and the server never substitutes the
      newest values — otherwise a confirmation of v1 would silently bless v2.
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

    # WO-34 §1：确认必须绑定人所看见的**完整对象**。以下字段缺一不可，
    # 且都要与实际展示对象一致；服务端绝不用当前值补缺（缺 → 可行动报错）。
    expected_project = str(payload.get("expected_project_id", "") or "").strip()
    expected_task = str(payload.get("expected_task_id", "") or "").strip()
    expected_profile = str(payload.get("expected_profile_sha256", "") or "").strip().lower()
    expected_input_file = str(payload.get("expected_input_file", "") or "").strip()
    expected_input = str(payload.get("expected_input_sha256", "") or "").strip().lower()
    missing: list[str] = []
    if not expected_project:
        missing.append("expected_project_id（你看到的项目）")
    if not expected_task:
        missing.append("expected_task_id（你看到的任务）")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_profile):
        missing.append("expected_profile_sha256（你看到的映射内容摘要）")
    if not expected_input_file:
        missing.append("expected_input_file（你看到的输入文件名）")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_input):
        missing.append("expected_input_sha256（你看到的输入字节摘要）")
    try:
        expected_revision = int(payload.get("expected_revision"))
    except (TypeError, ValueError):
        expected_revision = -1
        missing.append("expected_revision（你看到的映射修订）")
    if missing:
        raise GuardError(
            "确认必须绑定你实际看到的那一份（缺字段，服务器不会替你补当前值）："
            + "；".join(missing) + "。请重新读取该输入与候选映射后再确认。")

    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")

    # 读元数据 → 核对 → 原 CLI approve → 写审批/审计：整段在同一把进程内锁里，
    # 与并发的保存/换绑/拒绝串行，避免「核旧值后落盘新对象」（WO-34 §1）。
    with _CONTENT_LOCK:
        candidate = _candidate_path(project_id, task_id, profile_id)
        if not candidate.is_file():
            raise GuardError(f"候选 profile 不存在：{profile_id}")
        meta = _read_meta(project_id, task_id, profile_id)
        input_file = str(meta.get("input_file", "") or "")
        source = task_inputs(project_id, task_id) / input_file if input_file else None
        if source is None or not source.is_file():
            raise GuardError("候选 profile 未记录有效的 input_file")
        current = _sha256(source)
        digest = str(meta.get("profile_sha256", "") or "")
        if not digest:
            raise GuardError("候选 profile 缺少 SteelData 复核算出的 profile_sha256，请重新保存映射")
        current_revision = int(meta.get("revision") or 0)
        current_fingerprint = str(meta.get("content_fingerprint", "") or "")

        # ---- compare-and-set：只批用户看见的那一版，过期就 409 --------------- #
        stale: list[str] = []
        if expected_project != project_id:
            stale.append(f"项目已变化（你看到 {expected_project} / 现在 {project_id}）")
        if expected_task != task_id:
            stale.append(f"任务已变化（你看到 {expected_task} / 现在 {task_id}）")
        if expected_profile != digest:
            stale.append(f"映射内容已变化（你看到 {expected_profile[:12]}… / 现在 {digest[:12]}…）")
        if expected_input_file != input_file:
            stale.append(f"输入身份已变化（你看到 {expected_input_file} / 现在 {input_file}）")
        if expected_input != current:
            stale.append(f"输入字节已变化（你看到 {expected_input[:12]}… / 现在 {current[:12]}…）")
        if expected_revision != current_revision:
            stale.append(f"映射修订已变化（你看到 r{expected_revision} / 现在 r{current_revision}）")
        if stale:
            _append_review(project_id, task_id, {
                "kind": "review_stale",
                "decision": decision,
                "project_id": project_id, "task_id": task_id, "profile_id": profile_id,
                "input_file": input_file,
                "expected_project_id": expected_project, "expected_task_id": expected_task,
                "expected_profile_sha256": expected_profile,
                "expected_input_file": expected_input_file,
                "expected_input_sha256": expected_input,
                "expected_revision": expected_revision,
                "current_profile_sha256": digest,
                "current_input_file": input_file,
                "current_input_sha256": current,
                "current_revision": current_revision,
                "reason": "；".join(stale),
                "reviewer": reviewer,
                "synthetic": bool(synthetic),
                "actor_kind": session.actor_kind,
                "session_id": session.session_id,
                "created": datetime.now().isoformat(timespec="seconds"),
            })
            raise ConflictError(
                "你确认的那一版已经不是当前版本：" + "；".join(stale) +
                "。请重新读取该输入与候选映射后再确认（服务器不会自动替你批最新版）。")
        try:
            profile = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GuardError(f"候选 profile 无法读取：{exc}") from exc

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
            "profile_revision": current_revision,
            "content_fingerprint": current_fingerprint,
            "expected_project_id": expected_project,
            "expected_task_id": expected_task,
            "expected_profile_sha256": expected_profile,
            "expected_input_file": expected_input_file,
            "expected_input_sha256": expected_input,
            "expected_revision": expected_revision,
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
        # --expected-sha256 用**用户提交的期望值**（上面已核过它等于当前版本），
        # 不用服务器当前值顶替。
        code, out, err = _run_steeldata([
            "approve", "--profile", str(candidate),
            "--expected-sha256", expected_profile,
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

        # 落盘后再核对一次：审批文件里的 profile 摘要必须等于用户看到的版本；
        # 否则丢弃该文件，绝不留下可被 run 误用的错配批准（WO-34 §1）。
        mismatch = _verify_written_approval(approval_path, expected_profile)
        if mismatch:
            entry["kind"] = "review_failed"
            entry["reason"] = mismatch
            _append_review(project_id, task_id, entry)
            try:
                approval_path.unlink()
            except OSError:
                pass
            return {"ok": False, "decision": "approve", "review_id": review_id,
                    "problem": mismatch}

        entry["approval_file"] = approval_name
        entry["approval_sha256"] = _sha256(approval_path)
        _append_review(project_id, task_id, entry)
        return {
            "ok": True, "decision": "approve", "review_id": review_id,
            "approval_file": approval_name,
            "approval_sha256": _sha256(approval_path),
            "profile_id": profile_id,
            "input_file": input_file, "input_sha256": current, "profile_sha256": digest,
            "revision": current_revision,
            "reviewer": reviewer, "synthetic": bool(synthetic),
            "message": "审批文件由 SteelData 自己的 approve 命令生成，落在本任务 approvals/ 下。",
        }


def _verify_written_approval(path: Path, expected_profile: str) -> str:
    """Return a problem string if the freshly written approval does not match.

    WO-34 §1：approve 与并发的保存可能交错；即使 CLI 用了 ``--expected-sha256``，
    落盘后再核一次「审批文件里的 profile 摘要 == 用户看到的版本」，不一致就丢弃，
    不留下一份可用于 run 的错配批准。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"审批文件写入后无法解析：{exc}"
    if not isinstance(data, dict) or data.get("kind") != "human":
        return "审批文件不是 SteelData human 审批"
    if str(data.get("profile_sha256", "") or "") != expected_profile:
        return ("审批文件记录的 profile 摘要与你确认的版本不一致"
                "（可能在校对后映射被替换），已丢弃该审批，请重新读取后再确认。")
    return ""


def _invalidate_all_approvals(project_id: str, task_id: str, profile_id: str, digest: str,
                              *, reason: str) -> list[str]:
    """Invalidate the approvals of **one** profile (used by an explicit reject).

    与 :func:`_invalidate_stale_approvals` 一样只动 ``profile_id`` 自己：
    拒绝一个映射不该让同任务其它已批准的映射失效。
    """
    removed: list[str] = []
    archived_names: list[str] = []
    approvals = approvals_dir(project_id, task_id)
    if not approvals.is_dir():
        return removed
    for item in sorted(approvals.glob("*.json")):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        bound_id = str((data.get("profile") or {}).get("profile_id", "") or "")
        if bound_id != profile_id and item.stem != profile_id:
            continue
        archived = _archive_approval(project_id, task_id, item)
        removed.append(item.name)
        if archived:
            archived_names.append(archived)
    if removed:
        _append_review(project_id, task_id, {
            "kind": "invalidation", "profile_id": profile_id,
            "approval_file": ", ".join(removed),
            "archived_as": ", ".join(archived_names),
            "reason": reason,
            "profile_sha256": digest,
            "created": datetime.now().isoformat(timespec="seconds"),
        })
    return removed


# --------------------------------------------------------------------------- #
# 运行前的确认复核（供 steeldata.run 使用）
# --------------------------------------------------------------------------- #

def approval_for_run(project_id: str, task_id: str, approval_file: str, *,
                     input_file: str | None = None) -> dict:
    """Resolve one approval reference into a path **plus its provenance**.

    WO-33 §2：审批只覆盖「人所看见的那份输入与版本」。所以除了复核审批本身
    没过期，还要把**本次实际选中的 source** 与审批绑定的输入身份/SHA 完整比对，
    不同就是 ``needs_human``——不能因为「同一任务、列名相同」就放行另一个文件。

    ``server``      web human review -> <task>/approvals/<profile_id>.json.
                    Re-checks the profile digest **and** the bound input's
                    name + SHA-256 against the selected source.
    ``imported``    a file the user placed in <task>/inputs/. Its structure can be
                    checked, but this server cannot attest which input it covers,
                    so it is **not** a run authorisation: the result is
                    ``needs_human`` with the path to a proper web review.
    ``forged``      a JSON crafted to look like an approval is rejected on
                    structure/digest and never written into ``approvals/``.
    """
    name = safe_filename(approval_file)
    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")

    selected_name = ""
    selected_sha = ""
    if input_file:
        selected = safe_filename(input_file)
        selected_path = task_inputs(project_id, task_id) / selected
        if not selected_path.is_file():
            raise GuardError(f"输入文件不存在：{selected}")
        selected_name = selected
        selected_sha = _sha256(selected_path)

    # 1) 服务端生成的确认
    approvals = approvals_dir(project_id, task_id)
    candidate = approvals / name
    if candidate.is_file():
        return _verify_server_approval(project_id, task_id, candidate, name,
                                       selected_name=selected_name, selected_sha=selected_sha)

    # 2) 导入的既有确认（inputs/ 下，原 owner 提供）
    inputs = task_inputs(project_id, task_id)
    imported = inputs / name
    if imported.is_file():
        return _verify_imported_approval(project_id, task_id, imported, name,
                                         selected_name=selected_name, selected_sha=selected_sha)

    raise GuardError(f"审批文件不存在：{name}（只能选本任务 approvals/ 下由网页人审生成的，"
                     "或 inputs/ 下导入的既有审批）")


def _verify_server_approval(project_id: str, task_id: str, path: Path, name: str, *,
                            selected_name: str = "", selected_sha: str = "") -> dict:
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

    entry = next((item for item in reversed(list_reviews(project_id, task_id))
                  if item.get("approval_file") == name and item.get("decision") == "approve"), {})
    # 审批绑定的输入身份：优先取审批时的复核记录，其次取候选 meta。
    candidate = _candidate_path(project_id, task_id, profile_id)
    current_meta = _read_meta(project_id, task_id, profile_id) if candidate.is_file() else {}
    bound_file = str(entry.get("input_file") or current_meta.get("input_file", "") or "")
    bound_sha = str(entry.get("input_sha256") or data.get("input_sha256", "")
                    or current_meta.get("input_sha256", "") or "")

    reasons: list[str] = []
    if not candidate.is_file():
        reasons.append(f"候选 profile {profile_id} 已不存在（可能被删除/重建）")
    else:
        current_digest = str(current_meta.get("profile_sha256", "") or "")
        if current_digest and current_digest != digest:
            reasons.append(f"映射自确认后已变化（确认时 {digest[:12]}… / 现在 {current_digest[:12]}…）")

    # 审批覆盖的那份输入本身必须还在、且没被换过字节。
    if bound_file:
        bound_path = task_inputs(project_id, task_id) / bound_file
        if not bound_path.is_file():
            reasons.append(f"审批覆盖的输入 {bound_file} 已不在本任务 inputs/ 里")
        elif bound_sha:
            now_sha = _sha256(bound_path)
            if now_sha != bound_sha:
                reasons.append(f"审批覆盖的输入 {bound_file} 已被改动"
                               f"（确认时 {bound_sha[:12]}… / 现在 {now_sha[:12]}…）")

    # 本次真正要跑的 source 必须与审批绑定的输入一致（名字与字节都比）。
    if selected_name:
        if not bound_file:
            reasons.append("该审批没有可核对的输入绑定，无法证明它覆盖本次选中的文件")
        else:
            if selected_name != bound_file:
                reasons.append(f"本次选的是 {selected_name}，但该审批只覆盖 {bound_file}"
                               "（同一任务的不同输入不能互相顶替）")
            elif selected_sha and bound_sha and selected_sha != bound_sha:
                reasons.append(f"本次选中的 {selected_name} 与审批覆盖的字节不一致"
                               f"（审批 {bound_sha[:12]}… / 本次 {selected_sha[:12]}…）")

    if reasons:
        return {"ok": False, "origin": "server", "path": str(path), "file": name,
                "profile_id": profile_id, "profile_sha256": digest,
                "bound_input_file": bound_file, "bound_input_sha256": bound_sha,
                "selected_input_file": selected_name, "selected_input_sha256": selected_sha,
                "problems": reasons,
                "message": "该确认与本次运行不匹配：" + "；".join(reasons) +
                           "。请对本次要用的输入重新保存映射并重新人工确认。"}
    return {
        "ok": True, "origin": "server", "path": str(path), "file": name,
        "profile_id": profile_id, "profile_sha256": digest,
        "profile_revision": int(current_meta.get("revision") or 0),
        "input_file": bound_file, "input_sha256": bound_sha,
        "bound_input_file": bound_file, "bound_input_sha256": bound_sha,
        "selected_input_file": selected_name, "selected_input_sha256": selected_sha,
        "reviewer": str(data.get("reviewer", "") or ""),
        "review_id": str(entry.get("review_id", "") or ""),
        "synthetic": bool(entry.get("synthetic", False)),
        "problems": [],
    }


def _verify_imported_approval(project_id: str, task_id: str, path: Path, name: str, *,
                              selected_name: str = "", selected_sha: str = "") -> dict:
    """Validate an owner-supplied approval file, but never let it authorise a run.

    WO-33 §2：结构合法或带一个 reviewer 字符串，**不能**证明本次输入已获准。
    这个分支以前可以绕过新的输入绑定（只查「审批里的 input 还在」就放行别的
    source），现在如实返回 ``needs_human`` 并给出网页人审这条可用路径。
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
            "selected_input_file": selected_name, "selected_input_sha256": selected_sha,
            "used_for_run": False,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        _append_review(project_id, task_id, entry)
        needs = list(problems) + [
            "导入的审批没有可核对的输入绑定：本服务无法证明它覆盖本次选中的输入"
            + (f"（{selected_name}）" if selected_name else "") + "，因此不能作为本次运行的授权。",
        ]
        return {
            "ok": False, "origin": "imported", "path": str(path), "file": name,
            "profile_id": profile_id, "profile_sha256": digest,
            "bound_input_file": "", "bound_input_sha256": "",
            "selected_input_file": selected_name, "selected_input_sha256": selected_sha,
            "reviewer": str(data.get("reviewer", "") or ""), "problems": problems,
            "needs_human": needs,
            "message": ("导入的既有审批：结构与摘要已按 SteelData 合同复核，"
                        "但无法证明它覆盖本次输入，标为 imported 且不用于运行。"
                        "请在「数据处理」页对本输入重新保存映射并由具名人工确认，"
                        "再按该确认运行。"),
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
