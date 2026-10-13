"""WO-31 §3 — 科研薄 API（FastAPI）。

一个进程同时提供：

* ``/api/*``：项目/任务/文件/运行/产物/能力的 JSON 接口；
* ``/``：已构建的 React 单页（``frontend/dist``，同源提供，避免跨源与凭据转发）；
* ``/research``：科研专用 Streamlit 反代（可选，见 §4）。

写入型请求校验可信 ``Origin``；所有路径/文件名/标识都经过 :mod:`security` 守卫。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from steelai.paths import ROOT
from steelai.web_api import mapping, registry, runner, session as session_store, tools
from steelai.web_api.config import config
from steelai.web_api.security import GuardError, check_origin, interpreter_is_trusted
from steelai.web_api.tabular import TableError, read_table
from steelai.web_api.runner import RunRecord

FRONTEND_DIST = ROOT / "frontend" / "dist"
PREVIEW_ROWS = 25
NO_SESSION = "未申请会话令牌（本地最小会话 /api/session 先换取）"
READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}

app = FastAPI(title="SteelAI 科研薄 API", version="0.2.0", docs_url="/api/docs",
              openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config().allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


def _guard(callable_):
    try:
        return callable_()
    except GuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _capability_of(request: Request, capability: str) -> session_store.Session:
    """Resolve and authorise the caller for *capability*.

    A **missing** token is a 401. A token that exists but lacks the capability
    is a 403 with the reason; an AI session can never pass ``review:human``.
    The client-side ``reviewer``/``actor`` strings never grant anything.
    """
    header = str(request.headers.get("authorization", "") or "").strip()
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    try:
        return session_store.require(token, capability)
    except GuardError as exc:
        message = str(exc)
        if not message.startswith("该会话没有此能力"):
            raise HTTPException(status_code=401, detail=message) from exc
        raise HTTPException(status_code=403, detail=message) from exc


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method in {"POST", "DELETE", "PUT", "PATCH"}:
        if not check_origin(request.headers.get("origin"), config().allowed_origins):
            return JSONResponse(status_code=403, content={"detail": "不可信来源"})
    return await call_next(request)


# --------------------------------------------------------------------------- #
# 能力与健康
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict:
    cfg = config()
    return {
        "status": "ok",
        "workspace_root": str(cfg.workspace_root),
        "work_root": str(cfg.work_root),
        "run_root": str(cfg.run_root),
        "allowed_origins": list(cfg.allowed_origins),
        "research_app_url": cfg.streamlit_url,
        "frontend_built": FRONTEND_DIST.is_dir(),
        # 解释器只来自服务端解析（环境变量/被忽略的 config/settings.toml），
        # 客户端永远不能提交。这里如实报告它是否落在已登记的可信根内。
        "tools": {
            tool_id: {
                "interpreter": str(item.interpreter) if item.interpreter else None,
                "registered": item.interpreter is not None,
                "trusted": interpreter_is_trusted(item.interpreter, cfg.trusted_tool_roots),
            }
            for tool_id, item in cfg.tools.items()
        },
    }


@app.get("/api/capabilities")
def capabilities() -> dict:
    return {"tools": tools.capabilities()}


# --------------------------------------------------------------------------- #
# 本地会话（WO-32 §2）
# --------------------------------------------------------------------------- #

@app.post("/api/session")
def post_session(request: Request, payload: dict = Body(...)) -> dict:
    """Issue a local capability token for this loopback-only API.

    ``client="browser"`` asks for the in-page human session and **must** arrive
    with a trusted ``Origin`` (a same-origin POST always sends one). ``client="ai"``
    asks for the restricted assistant session: read + advise + approved
    execution, never a human review. The server decides the capability set; a
    caller never chooses its own permissions.
    """
    client = str(payload.get("client", "") or "").strip().lower()
    try:
        return session_store.issue(
            client,
            origin=request.headers.get("origin"),
            allowed_origins=config().allowed_origins,
        )
    except GuardError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/session")
def get_session(request: Request) -> dict:
    """Describe the current session (capabilities, never a re-issueable list)."""
    header = str(request.headers.get("authorization", "") or "").strip()
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    try:
        record = session_store.verify(token)
    except GuardError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"session": record.as_dict()}


# --------------------------------------------------------------------------- #
# 项目 / 任务
# --------------------------------------------------------------------------- #

@app.get("/api/projects")
def get_projects(request: Request) -> dict:
    _capability_of(request, "projects:read")
    projects, notes = registry.list_projects()
    return {"projects": [registry.project_summary(item) for item in projects], "notes": notes}


@app.get("/api/projects/{project_id}/tasks")
def get_tasks(project_id: str, request: Request) -> dict:
    _capability_of(request, "tasks:read")
    tasks = _guard(lambda: registry.list_tasks(project_id))
    return {"project_id": project_id, "tasks": [item.__dict__ for item in tasks]}


@app.post("/api/projects/{project_id}/tasks")
def post_task(project_id: str, request: Request, payload: dict = Body(...)) -> dict:
    _capability_of(request, "tasks:write")
    task = _guard(lambda: registry.create_task(
        project_id,
        str(payload.get("task_id", "")).strip(),
        str(payload.get("title", "")).strip(),
        str(payload.get("note", "")),
    ))
    return {"task": task.__dict__}


@app.get("/api/projects/{project_id}/tasks/{task_id}/context")
def get_context(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "tasks:read")
    return _guard(lambda: registry.task_context(project_id, task_id))


@app.get("/api/projects/{project_id}/tasks/{task_id}/files")
def get_files(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "files:read")
    files = _guard(lambda: registry.list_input_files(project_id, task_id))
    return {"files": files}


@app.post("/api/projects/{project_id}/tasks/{task_id}/upload")
async def post_upload(project_id: str, task_id: str, request: Request,
                      file: UploadFile = File(...)) -> dict:
    _capability_of(request, "files:write")
    payload = await file.read()
    result = _guard(lambda: registry.register_upload(project_id, task_id, file.filename or "", payload))
    return {"uploaded": result}


@app.delete("/api/projects/{project_id}/tasks/{task_id}/files/{file_id}")
def delete_file(project_id: str, task_id: str, file_id: str, request: Request) -> dict:
    _capability_of(request, "files:write")
    _guard(lambda: registry.delete_input(project_id, task_id, file_id))
    return {"deleted": file_id}


@app.get("/api/projects/{project_id}/tasks/{task_id}/preview")
def get_preview(project_id: str, task_id: str, file_id: str, request: Request) -> dict:
    _capability_of(request, "files:read")
    path = _guard(lambda: registry.input_path(project_id, task_id, file_id))
    return _guard(lambda: _preview(path))


@app.get("/api/projects/{project_id}/tasks/{task_id}/handoff")
def get_handoff(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "files:read")
    context = _guard(lambda: registry.task_context(project_id, task_id))
    return {"handoff_markdown": context["handoff_markdown"]}


@app.post("/api/projects/{project_id}/tasks/{task_id}/handoff")
def post_handoff(project_id: str, task_id: str, request: Request, payload: dict = Body(...)) -> dict:
    _capability_of(request, "handoff:write")
    markdown = str(payload.get("markdown", ""))
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="接手摘要不能为空")
    _guard(lambda: registry.write_handoff(project_id, task_id, markdown))
    return {"written": True}


# --------------------------------------------------------------------------- #
# 运行
# --------------------------------------------------------------------------- #

@app.post("/api/projects/{project_id}/tasks/{task_id}/runs")
def post_run(project_id: str, task_id: str, request: Request, payload: dict = Body(...)) -> dict:
    session = _capability_of(request, "runs:create")
    tool_id = str(payload.get("tool_id", "")).strip()
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params 必须是对象")
    # 运行归属按提交这一刻冻结：回调/慢响应不能把结果写到另一个当前项目。
    record = _guard(lambda: runner.create_run(
        project_id, task_id, tool_id, params,
        actor=session.actor_kind, session_id=session.session_id,
        actor_kind=session.actor_kind,
    ))
    return {"run": record}


@app.get("/api/projects/{project_id}/tasks/{task_id}/runs")
def get_task_runs(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "runs:read")
    return {"runs": runner.list_runs(project_id, task_id)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    _capability_of(request, "runs:read")
    return {"run": _guard(lambda: runner.load_record(run_id).as_dict())}


@app.get("/api/runs/{run_id}/artifacts/{rel:path}")
def get_artifact(run_id: str, rel: str, request: Request):
    _capability_of(request, "artifacts:read")
    path, meta = _guard(lambda: runner.artifact_for_download(run_id, rel))
    return FileResponse(path, filename=path.name, media_type=_media_type(path))


@app.get("/api/projects/{project_id}/tasks/{task_id}/artifacts")
def get_task_artifacts(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "artifacts:read")
    rows: list[dict] = []
    for record in runner.list_runs(project_id, task_id):
        for artifact in record.get("artifacts", []):
            rows.append({
                **artifact,
                "run_id": record["run_id"],
                "tool_id": record["tool_id"],
                "tool_label": record.get("tool_label", record["tool_id"]),
                "status": record["status"],
                "created": record["created"],
            })
    return {"artifacts": rows}


def _promote_guard(payload: dict) -> RunRecord:
    reviewer = str(payload.get("reviewer", "")).strip()
    run_id = str(payload.get("run_id", "")).strip()
    if not reviewer or reviewer.lower() in {
            "system", "agent", "auto", "automatic", "web", "ai", "assistant", "bot"}:
        raise HTTPException(status_code=400, detail="晋升需要具名人工审批人，不能用系统/代理名")
    record = _guard(lambda: runner.load_record(run_id))
    if record.status != "succeeded":
        raise HTTPException(status_code=409, detail="只有成功的运行才能晋升")
    return record


@app.post("/api/projects/{project_id}/tasks/{task_id}/promote")
def post_promote(project_id: str, task_id: str, request: Request, payload: dict = Body(...)) -> dict:
    """候选成果晋升：必须具名人工审批，且要接上原 owner 的晋升流程。"""
    _capability_of(request, "review:human")
    record = _promote_guard(payload)
    return JSONResponse(status_code=501, content={
        "detail": "晋升尚未接通：原 owner 的正式成果晋升流程未在本单接线。",
        "status": "not_connected",
        "candidate": {
            "run_id": record.run_id,
            "artifacts": record.artifacts,
            "requested_reviewer": str(payload.get("reviewer", "")).strip(),
        },
        "note": "候选仍保留在任务 runs/ 下，不会被自动 accepted 或覆盖 CURRENT。",
    })


# --------------------------------------------------------------------------- #
# WO-32 §1 — 网页映射 / 候选 profile / 具名人工确认 / 运行前复核
# --------------------------------------------------------------------------- #

@app.get("/api/mapping-contract")
def get_mapping_contract() -> dict:
    """The SteelData mapping contract the web form must obey.

    直接来自 :mod:`steelai.web_api.mapping`（它与 SteelData 的 Profile 合同同源），
    前端不另抄一份——否则两份表迟早对不上，页面就会"看起来能选、保存才报错"。
    """
    return {
        "domains": sorted(mapping.DOMAINS),
        "layouts": sorted(mapping.LAYOUTS),
        "allowed_targets": {key: sorted(value) for key, value in mapping.ALLOWED_TARGETS.items()},
        "text_targets": sorted(mapping.TEXT_TARGETS),
        "targets": dict(mapping.TARGETS),
        "allowed_units": {key: sorted(value) for key, value in mapping.ALLOWED_UNITS.items()},
        "required_targets": {key: sorted(value) for key, value in mapping.REQUIRED_TARGETS.items()},
        "supported_formats": sorted(mapping.SUPPORTED_SUFFIXES),
    }


@app.get("/api/projects/{project_id}/tasks/{task_id}/describe-input")
def get_describe_input(project_id: str, task_id: str, file_id: str, request: Request) -> dict:
    """Read-only description of one uploaded file: real columns, units, problems."""
    _capability_of(request, "files:read")
    return _guard(lambda: mapping.describe_input(project_id, task_id, file_id))


@app.get("/api/projects/{project_id}/tasks/{task_id}/profiles")
def get_profiles(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "files:read")
    return {"profiles": _guard(lambda: mapping.list_profiles(project_id, task_id))}


@app.post("/api/projects/{project_id}/tasks/{task_id}/mapping")
def post_mapping(project_id: str, task_id: str, request: Request, payload: dict = Body(...)) -> dict:
    """Save the web mapping as a candidate SteelData profile for this task."""
    _capability_of(request, "tasks:write")
    return _guard(lambda: mapping.save_candidate(project_id, task_id, payload))


@app.get("/api/projects/{project_id}/tasks/{task_id}/preview-profile")
def get_preview_profile(project_id: str, task_id: str, profile_id: str, request: Request) -> dict:
    """SteelData's own read-only preview of a saved candidate profile."""
    _capability_of(request, "files:read")
    return _guard(lambda: mapping.preview_profile(project_id, task_id, profile_id))


@app.get("/api/projects/{project_id}/tasks/{task_id}/reviews")
def get_reviews(project_id: str, task_id: str, request: Request) -> dict:
    _capability_of(request, "files:read")
    return {"reviews": _guard(lambda: mapping.list_reviews(project_id, task_id))}


@app.post("/api/projects/{project_id}/tasks/{task_id}/review")
def post_review(project_id: str, task_id: str, request: Request, payload: dict = Body(...)) -> dict:
    """Record an explicit human approve/reject through SteelData's own approve.

    Requires the ``review:human`` capability: an ``ai`` session is refused here
    even when it submits a perfectly-worded reviewer name.
    """
    session = _capability_of(request, "review:human")
    synthetic = str(request.query_params.get("synthetic", "")).lower() in {"1", "true", "yes"}
    return _guard(lambda: mapping.review_candidate(project_id, task_id, payload, session,
                                                   synthetic=synthetic))


@app.get("/api/projects/{project_id}/tasks/{task_id}/approval")
def get_approval(project_id: str, task_id: str, approval_file: str, request: Request) -> dict:
    """Resolve an approval reference for ``steeldata.run`` with its provenance."""
    _capability_of(request, "files:read")
    return _guard(lambda: mapping.approval_for_run(project_id, task_id, approval_file))


@app.get("/api/projects/{project_id}/tasks/{task_id}/research-url")
def get_research_url(project_id: str, task_id: str, request: Request) -> dict:
    """The scoped Streamlit URL for the embedded legacy research page.

    Built **server-side** and validated against the registry, so the iframe can
    never be pointed at an arbitrary URL by a client, and switching
    project/task yields a different, re-validated URL.
    """
    _capability_of(request, "files:read")
    context = _guard(lambda: registry.task_context(project_id, task_id))
    return {
        "url": f"{config().streamlit_url}?project_id={project_id}&task_id={task_id}",
        "base_url": config().streamlit_url,
        "project_id": context["project_id"],
        "task_id": context["task_id"],
        "task_root": context["root"],
        "shared_context": True,
        "note": ("该地址由服务端按已登记的 project/task 生成并带 query 参数；"
                 "旧页是否真的消费同一上下文需在该页实际验证（见 HANDOFF）。"),
    }


# --------------------------------------------------------------------------- #
# 预览实现（只读，不改写输入）
# --------------------------------------------------------------------------- #

def _media_type(path: Path) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp",
        ".html": "text/html", ".json": "application/json", ".csv": "text/csv",
        ".txt": "text/plain", ".md": "text/markdown", ".npy": "application/octet-stream",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(path.suffix.lower(), "application/octet-stream")


def _image_size(path: Path) -> dict:
    """Read pixel dimensions from the file header without decoding the image."""
    with path.open("rb") as handle:
        head = handle.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", head[16:24])
            return {"format": "png", "width": width, "height": height}
        if head[:2] == b"\xff\xd8":
            handle.seek(2)
            while True:
                marker = handle.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    break
                length = struct.unpack(">H", handle.read(2))[0]
                if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3):
                    data = handle.read(5)
                    height, width = struct.unpack(">HH", data[1:5])
                    return {"format": "jpeg", "width": width, "height": height}
                handle.seek(length - 2, 1)
        if head[:2] == b"BM":
            width, height = struct.unpack("<ii", head[18:26])
            return {"format": "bmp", "width": abs(width), "height": abs(height)}
    return {"format": path.suffix.lstrip(".").lower(), "width": None, "height": None}


def _preview(path: Path) -> dict:
    if not path.is_file():
        raise GuardError("文件不存在")
    suffix = path.suffix.lower()
    size = path.stat().st_size
    base = {"file_id": path.name, "size": size, "suffix": suffix}

    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        return {**base, "kind": "image", "image": _image_size(path),
                "note": "仅读取文件头尺寸，不解码、不修改输入。"}

    # 表格式输入统一走 tabular 合同（csv 严格解析、逻辑记录计数、坏编码不静默替换），
    # 与 SteelData 自己的解析保持一致；预览与后续处理对同一份字节给同一解释。
    if suffix in {".csv", ".tsv", ".xlsx"}:
        try:
            view = read_table(path)
        except TableError as exc:
            return {**base, "kind": "error", "problem": str(exc),
                    "note": mapping.SUPPORTED_FORMATS_NOTE, "columns": [], "rows": [],
                    "records": 0, "delimiter": ""}
        payload = {
            "kind": "workbook" if view.suffix == ".xlsx" else "table",
            "delimiter": view.delimiter,
            "delimiter_source": view.delimiter_source,
            "sheet": view.sheet,
            "sheets": view.sheets,
            "has_formulas": view.has_formulas,
            "columns": view.columns,
            "rows": view.rows[:PREVIEW_ROWS],
            "records": view.records,
            "total_lines": view.records,       # 逻辑记录数，不是物理行数
            "physical_lines": view.physical_lines,
            "truncated": view.truncated,
            "ragged_rows": view.ragged_rows,
            "duplicate_headers": view.duplicate_headers,
            "empty_headers": view.empty_headers,
            "notes": view.notes,
            "encoding": view.encoding,
        }
        return {**base, **payload}

    if suffix == ".json":
        try:
            text = path.read_text(encoding="utf-8-sig")
            data = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {**base, "kind": "error", "problem": f"JSON 无法按 UTF-8 解析：{exc}",
                    "note": "不做 errors='replace' 静默替换；请确认文件编码。",
                    "columns": [], "rows": [], "records": 0}
        return {**base, "kind": "json", "json_head": _truncate_json(data)}

    if suffix in {".txt", ".md", ".yaml", ".yml"}:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            return {**base, "kind": "error", "problem": f"文本不是 UTF-8：{exc}",
                    "note": "不做 errors='replace' 静默替换。",
                    "columns": [], "rows": [], "records": 0}
        return {**base, "kind": "text", "text": text[:4000], "truncated": len(text) > 4000}

    return {**base, "kind": "binary", "note": "该类型不提供文本预览，可直接下载。"}


def _truncate_json(value, depth: int = 0):
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        return {key: _truncate_json(item, depth + 1) for key, item in list(value.items())[:20]}
    if isinstance(value, list):
        return [_truncate_json(item, depth + 1) for item in value[:10]]
    return value


# --------------------------------------------------------------------------- #
# 前端静态资源（同源提供，避免跨源与凭据转发）
# --------------------------------------------------------------------------- #

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
