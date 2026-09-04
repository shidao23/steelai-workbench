from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from steelai.paths import PROJECT_LOG


SESSION_SCHEMA_VERSION = "1.0"
SESSION_FEATURE_VERSION = "0.13.0"
RESEARCH_SESSIONS = PROJECT_LOG / "research_sessions"
CORE_SAMPLES = frozenset({"B-DQ", "R-DQ"})
SESSION_STATUSES = ("planned", "active", "blocked", "completed", "archived")
STAGE_STATUSES = ("pending", "in_progress", "blocked", "completed", "skipped")
FINDING_CATEGORIES = ("confirmed_fact", "current_judgment", "hypothesis", "limitation")
ACTION_STATUSES = ("open", "in_progress", "done", "cancelled")

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\r\t`\"']+")
_RAW_FILE = re.compile(r"[^\s`\"']+\.(?:ctf|tif|tiff)\b", re.IGNORECASE)


WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_id": "br_integrated_case",
        "label": "B/R综合研究任务",
        "description": "从数据检查到Physics、SEM、双尺度EBSD、证据门控和研究报告。",
        "default_question": "为什么R-DQ的低温冲击韧性低于B-DQ？",
        "stages": (
            ("define_question", "确认研究问题与B/R范围", True),
            ("check_data", "检查processed数据与科学边界", True),
            ("run_br_case", "运行端到端B/R研究任务", True),
            ("review_evidence", "复核事实、判断、假设和禁止表述", True),
            ("record_next_action", "记录下一步实验或数据行动", True),
        ),
    },
    {
        "template_id": "new_sample_data_check",
        "label": "新增数据质量检查",
        "description": "预检新的B/R结构化记录、层级、单位、来源状态和主键冲突。",
        "default_question": "本次新增B/R数据是否满足研究数据契约并可安全追加？",
        "stages": (
            ("identify_data_layer", "确认数据层和真实实验层级", True),
            ("prepare_template", "使用受控模板整理记录", True),
            ("run_dry_check", "运行本地预检", True),
            ("review_provenance", "复核来源、单位和独立性", True),
            ("commit_or_reject", "明确决定追加或退回修正", True),
        ),
    },
    {
        "template_id": "physics_calibration",
        "label": "Physics实验校正",
        "description": "匹配实验值、模型版本和残差，不覆盖原始经验公式。",
        "default_question": "现有实验值能否支持对Physics模型进行有来源记录的评价或校正？",
        "stages": (
            ("select_quantity", "选择物理量和公式版本", True),
            ("verify_experiment", "核对实验值、单位和来源", True),
            ("calculate_residual", "计算模型值与残差", True),
            ("assess_applicability", "检查适用范围和不确定度", True),
            ("decide_calibration", "决定保持原式或建立独立校正版", True),
        ),
    },
    {
        "template_id": "ebsd_dual_scale",
        "label": "EBSD双尺度比较",
        "description": "分别分析两个采集尺度，保持field与specimen层级，不合并统计。",
        "default_question": "B-DQ与R-DQ在两个独立EBSD尺度上的方向性差异是否一致？",
        "stages": (
            ("verify_acquisition", "核对采集组和元数据匹配", True),
            ("run_low_resolution", "读取或运行低分辨率分析", True),
            ("run_high_resolution", "读取或运行高分辨率分析", True),
            ("compare_unpooled", "分别比较两个尺度", True),
            ("record_ebsd_boundary", "记录视场与术语边界", True),
        ),
    },
    {
        "template_id": "sem_fracture",
        "label": "SEM断口分析",
        "description": "按试样层级解释AutoDimple结果，避免图像和对象伪重复。",
        "default_question": "B-DQ与R-DQ的探索性断口形貌差异能支持哪些方向性判断？",
        "stages": (
            ("verify_sem_metadata", "核对倍率、像素和试样层级", True),
            ("review_segmentation", "复核分割标准和警告", True),
            ("compare_images", "执行图像层级描述性比较", True),
            ("check_bootstrap", "检查区间与伪重复边界", True),
            ("record_sem_boundary", "记录允许表述和验证需求", True),
        ),
    },
)

REQUIRED_SESSION_FIELDS = {
    "schema_version", "feature_version", "session_id", "revision", "title",
    "research_question", "workflow_template_id", "sample_ids", "status",
    "created_at", "updated_at", "stages", "findings", "next_actions",
    "run_references", "data_boundary",
}


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _assert_safe_text(value: str, field: str) -> str:
    text = str(value).strip()
    if _ABSOLUTE_PATH.search(text) or _RAW_FILE.search(text):
        raise ValueError(f"{field}不能包含本地绝对路径或原始CTF/TIF文件名；请改用证据索引或相对运行编号。")
    return text


def workflow_templates() -> list[dict[str, Any]]:
    return [
        {
            **template,
            "stages": [
                {"stage_id": stage_id, "label": label, "required": required}
                for stage_id, label, required in template["stages"]
            ],
        }
        for template in WORKFLOW_TEMPLATES
    ]


def template_by_id(template_id: str) -> dict[str, Any]:
    template = next((item for item in workflow_templates() if item["template_id"] == template_id), None)
    if template is None:
        raise KeyError(f"未知科研工作流模板：{template_id}")
    return template


def _session_path(session_id: str, root: Path) -> Path:
    clean = str(session_id).strip()
    if not re.fullmatch(r"RS-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", clean):
        raise ValueError("session_id格式无效。")
    return root / f"{clean}.json"


def _write_session(session: dict[str, Any], root: Path, expected_revision: int | None = None) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    path = _session_path(session["session_id"], root)
    if expected_revision is not None and path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if int(current.get("revision", 0)) != expected_revision:
            raise RuntimeError("科研会话已在其他位置更新，请刷新后重试。")
    payload = dict(session)
    payload["updated_at"] = _now()
    payload["revision"] = int(payload.get("revision", 0)) + 1
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return payload


def create_session(
    title: str,
    research_question: str,
    workflow_template_id: str,
    sample_ids: list[str] | tuple[str, ...],
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    clean_title = _assert_safe_text(title, "标题")
    clean_question = _assert_safe_text(research_question, "研究问题")
    if not clean_title or not clean_question:
        raise ValueError("标题和研究问题不能为空。")
    selected_samples = list(dict.fromkeys(str(item).strip() for item in sample_ids if str(item).strip()))
    if not selected_samples or not set(selected_samples) <= CORE_SAMPLES:
        raise ValueError("v0.13科研会话只允许B-DQ/R-DQ；1–14号实验保持排除。")
    template = template_by_id(workflow_template_id)
    stamp = datetime.now(ZoneInfo("Asia/Shanghai"))
    session_id = f"RS-{stamp.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    created_at = stamp.isoformat(timespec="seconds")
    session = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "feature_version": SESSION_FEATURE_VERSION,
        "session_id": session_id,
        "revision": 0,
        "title": clean_title,
        "research_question": clean_question,
        "workflow_template_id": workflow_template_id,
        "sample_ids": selected_samples,
        "status": "planned",
        "created_at": created_at,
        "updated_at": created_at,
        "stages": [
            {**stage, "status": "pending", "notes": "", "updated_at": created_at}
            for stage in template["stages"]
        ],
        "findings": [],
        "next_actions": [],
        "run_references": [],
        "data_boundary": {
            "included_samples": selected_samples,
            "experiments_1_14_included": False,
            "raw_source_files_copied": False,
            "absolute_paths_stored": False,
        },
    }
    return _write_session(session, root)


def load_session(session_id: str, *, root: Path = RESEARCH_SESSIONS) -> dict[str, Any]:
    path = _session_path(session_id, root)
    if not path.exists():
        raise FileNotFoundError(f"科研会话不存在：{session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions(*, root: Path = RESEARCH_SESSIONS) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    sessions = []
    for path in root.glob("RS-*.json"):
        try:
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)


def update_session_status(
    session_id: str,
    status: str,
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    if status not in SESSION_STATUSES:
        raise ValueError(f"不支持的会话状态：{status}")
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    session["status"] = status
    return _write_session(session, root, revision)


def update_stage(
    session_id: str,
    stage_id: str,
    status: str,
    notes: str = "",
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    if status not in STAGE_STATUSES:
        raise ValueError(f"不支持的阶段状态：{status}")
    clean_notes = _assert_safe_text(notes, "阶段备注")
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    stage = next((item for item in session["stages"] if item["stage_id"] == stage_id), None)
    if stage is None:
        raise KeyError(f"会话中没有阶段：{stage_id}")
    stage.update({"status": status, "notes": clean_notes, "updated_at": _now()})
    if status == "blocked":
        session["status"] = "blocked"
    elif status == "in_progress" and session["status"] in {"planned", "blocked"}:
        session["status"] = "active"
    return _write_session(session, root, revision)


def continue_session(session_id: str, *, root: Path = RESEARCH_SESSIONS) -> dict[str, Any]:
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    next_stage = next((item for item in session["stages"] if item["status"] in {"pending", "blocked"}), None)
    if next_stage is not None:
        next_stage.update({"status": "in_progress", "updated_at": _now()})
        session["status"] = "active"
    return _write_session(session, root, revision)


def add_finding(
    session_id: str,
    category: str,
    text: str,
    evidence_references: list[str] | None = None,
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    if category not in FINDING_CATEGORIES:
        raise ValueError(f"不支持的发现类别：{category}")
    clean_text = _assert_safe_text(text, "科研发现")
    if not clean_text:
        raise ValueError("科研发现不能为空。")
    references = [_assert_safe_text(item, "证据引用") for item in (evidence_references or []) if str(item).strip()]
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    session["findings"].append({
        "finding_id": f"F-{uuid.uuid4().hex[:8]}",
        "category": category,
        "text": clean_text,
        "evidence_references": references,
        "created_at": _now(),
    })
    return _write_session(session, root, revision)


def add_next_action(
    session_id: str,
    text: str,
    priority: str = "medium",
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    if priority not in {"high", "medium", "low"}:
        raise ValueError(f"不支持的优先级：{priority}")
    clean_text = _assert_safe_text(text, "下一步行动")
    if not clean_text:
        raise ValueError("下一步行动不能为空。")
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    session["next_actions"].append({
        "action_id": f"A-{uuid.uuid4().hex[:8]}",
        "text": clean_text,
        "priority": priority,
        "status": "open",
        "created_at": _now(),
    })
    return _write_session(session, root, revision)


def update_action_status(
    session_id: str,
    action_id: str,
    status: str,
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    if status not in ACTION_STATUSES:
        raise ValueError(f"不支持的行动状态：{status}")
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    action = next((item for item in session["next_actions"] if item["action_id"] == action_id), None)
    if action is None:
        raise KeyError(f"会话中没有行动：{action_id}")
    action["status"] = status
    return _write_session(session, root, revision)


def attach_run(
    session_id: str,
    run_id: str,
    pipeline_version: str,
    status: str,
    artifact: str,
    *,
    root: Path = RESEARCH_SESSIONS,
) -> dict[str, Any]:
    clean_run_id = _assert_safe_text(run_id, "run_id")
    clean_artifact = _assert_safe_text(artifact, "运行产物引用")
    if Path(clean_artifact).is_absolute():
        raise ValueError("运行产物必须使用项目内相对引用。")
    session = load_session(session_id, root=root)
    revision = int(session["revision"])
    if not any(item.get("run_id") == clean_run_id for item in session["run_references"]):
        session["run_references"].append({
            "run_id": clean_run_id,
            "pipeline_version": str(pipeline_version),
            "status": str(status),
            "artifact": clean_artifact,
            "attached_at": _now(),
        })
    stage = next((item for item in session["stages"] if item["stage_id"] == "run_br_case"), None)
    if stage is not None and status == "completed":
        stage.update({"status": "completed", "notes": f"已关联运行 {clean_run_id}", "updated_at": _now()})
    if session["status"] == "planned":
        session["status"] = "active"
    return _write_session(session, root, revision)


def session_summary(session: dict[str, Any]) -> dict[str, Any]:
    stages = session.get("stages", [])
    completed = sum(item.get("status") in {"completed", "skipped"} for item in stages)
    total = len(stages)
    open_actions = sum(item.get("status") in {"open", "in_progress"} for item in session.get("next_actions", []))
    current_stage = next((item for item in stages if item.get("status") == "in_progress"), None)
    if current_stage is None:
        current_stage = next((item for item in stages if item.get("status") in {"pending", "blocked"}), None)
    return {
        "session_id": session.get("session_id"),
        "title": session.get("title"),
        "template": session.get("workflow_template_id"),
        "status": session.get("status"),
        "progress": f"{completed}/{total}",
        "progress_ratio": round(completed / total, 3) if total else 1.0,
        "current_stage": current_stage.get("label", "已无待处理阶段") if current_stage else "已无待处理阶段",
        "open_actions": open_actions,
        "run_count": len(session.get("run_references", [])),
        "updated_at": session.get("updated_at"),
    }


def research_session_dashboard(*, root: Path = RESEARCH_SESSIONS) -> dict[str, Any]:
    sessions = list_sessions(root=root)
    summaries = [session_summary(item) for item in sessions]
    open_actions = []
    for session in sessions:
        for action in session.get("next_actions", []):
            if action.get("status") in {"open", "in_progress"}:
                open_actions.append({
                    "session_id": session["session_id"],
                    "session_title": session["title"],
                    **action,
                })
    return {
        "session_count": len(sessions),
        "active_count": sum(item.get("status") == "active" for item in sessions),
        "blocked_count": sum(item.get("status") == "blocked" for item in sessions),
        "completed_count": sum(item.get("status") == "completed" for item in sessions),
        "open_action_count": len(open_actions),
        "sessions": summaries,
        "open_actions": open_actions,
    }


def validate_session_contract(*, root: Path = RESEARCH_SESSIONS) -> dict[str, Any]:
    problems: list[str] = []
    templates = workflow_templates()
    template_ids = [item["template_id"] for item in templates]
    if len(template_ids) != len(set(template_ids)):
        problems.append("工作流模板ID重复。")
    for template in templates:
        stage_ids = [item["stage_id"] for item in template["stages"]]
        if not stage_ids or len(stage_ids) != len(set(stage_ids)):
            problems.append(f"{template['template_id']} 的阶段为空或重复。")
    checked = 0
    if root.exists():
        for path in root.glob("RS-*.json"):
            checked += 1
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{path.name}无法读取：{exc}")
                continue
            missing = sorted(REQUIRED_SESSION_FIELDS - set(session))
            if missing:
                problems.append(f"{path.name}缺少字段：{', '.join(missing)}")
            if session.get("status") not in SESSION_STATUSES:
                problems.append(f"{path.name}的状态无效。")
            if not set(session.get("sample_ids", [])) <= CORE_SAMPLES:
                problems.append(f"{path.name}包含超范围样品。")
            if session.get("data_boundary", {}).get("experiments_1_14_included") is not False:
                problems.append(f"{path.name}未明确排除1–14号实验。")
    return {
        "status": "passed" if not problems else "failed",
        "schema_version": SESSION_SCHEMA_VERSION,
        "feature_version": SESSION_FEATURE_VERSION,
        "template_count": len(templates),
        "session_count": checked,
        "problems": problems,
    }
