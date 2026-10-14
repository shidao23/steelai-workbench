"""WO-31 §3 — 运行记录与受控子进程执行。

设计约束（工单 §3）：

* **每 run 唯一**：``run-<uuid12>``，输出目录一次一建，重复提交不会覆盖既有运行。
* **受控子进程 + 最小状态**：固定 argv、``shell=False``、有超时、并发上限固定；
  不引入常驻调度器，也不新建数据库——状态就是磁盘上的一个 JSON。
* **刷新能读回**：状态落在 ``outputs/research_web/index/<run_id>.json``，
  页面刷新后按 run_id 重新读取。
* **失败如实**：``failed`` / ``timeout`` / ``blocked`` 原样保留退出码与输出尾部。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from steelai.web_api.config import config
from steelai.web_api.registry import task_root
from steelai.web_api.security import GuardError, safe_identifier
from steelai.web_api.tools import build_argv, missing_asset_reason

MAX_CONCURRENT_RUNS = 2
DEFAULT_TIMEOUT = 900
TIMEOUTS = {"microsam.predict": 1800, "calphad.equilibrium": 1200}
TAIL_CHARS = 4000
SECRET_MARKERS = ("KEY", "TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "DATABASE_URL")
ARTIFACT_SUFFIXES = {
    ".csv", ".json", ".png", ".npy", ".html", ".md", ".txt", ".xlsx", ".tdb", ".log",
}


@dataclass
class RunRecord:
    run_id: str
    project_id: str
    task_id: str
    tool_id: str
    tool_label: str
    params: dict
    status: str
    created: str
    started: str = ""
    finished: str = ""
    exit_code: int | None = None
    output_dir: str = ""
    artifacts: list[dict] = field(default_factory=list)
    result_dirs: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str = ""
    actor: str = "web"
    session_id: str = ""
    actor_kind: str = ""
    approval_origin: str = ""
    approval_file: str = ""
    approval_profile_id: str = ""
    approval_profile_sha256: str = ""
    approval_revision: int = 0
    approval_input_file: str = ""
    approval_input_sha256: str = ""
    approval_reviewer: str = ""
    approval_review_id: str = ""
    approval_synthetic: bool = False
    actual_input_file: str = ""
    actual_input_sha256: str = ""
    duration_sec: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_FUTURES: dict[str, object] = {}


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_RUNS, thread_name_prefix="research-run")
    return _EXECUTOR


def index_dir() -> Path:
    path = config().run_root / "index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = config().run_root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_path(run_id: str) -> Path:
    return index_dir() / f"{safe_identifier(run_id, 'run 标识')}.json"


def save_record(record: RunRecord) -> None:
    path = _record_path(record.run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_record(run_id: str) -> RunRecord:
    path = _record_path(run_id)
    if not path.is_file():
        raise GuardError(f"运行不存在：{run_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunRecord(**data)


def list_runs(project_id: str | None = None, task_id: str | None = None,
              limit: int = 100) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(index_dir().glob("run-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if project_id and data.get("project_id") != project_id:
            continue
        if task_id and data.get("task_id") != task_id:
            continue
        rows.append(data)
        if len(rows) >= limit:
            break
    return rows


def run_output_dir(project_id: str, task_id: str, run_id: str) -> Path:
    root = task_root(project_id, task_id) / "runs" / safe_identifier(run_id, "run 标识")
    return root


def _subprocess_env() -> dict[str, str]:
    """Minimal, credential-free environment for a tool subprocess."""
    keep = {"PATH", "Path", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "WINDIR",
            "COMSPEC", "PATHEXT", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
            "LOCALAPPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS", "OS", "LANG"}
    env = {key: value for key, value in os.environ.items() if key in keep}
    for key in list(env):
        if any(marker in key.upper() for marker in SECRET_MARKERS):
            env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _collect_artifacts(root: Path) -> list[dict]:
    rows: list[dict] = []
    if not root.is_dir():
        return rows
    for item in sorted(root.rglob("*")):
        if not item.is_file() or item.suffix.lower() not in ARTIFACT_SUFFIXES:
            continue
        digest = hashlib.sha256()
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        rows.append({
            "name": item.name,
            "rel": item.relative_to(root).as_posix(),
            "size": item.stat().st_size,
            "sha256": digest.hexdigest(),
        })
    return rows


def _execute(record: RunRecord, interpreter: Path, argv: list[str], cwd: Path) -> None:
    out_dir = Path(record.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record.status = "running"
    record.started = datetime.now().isoformat(timespec="seconds")
    save_record(record)
    timeout = TIMEOUTS.get(record.tool_id, DEFAULT_TIMEOUT)
    command = [str(interpreter), *argv]
    started = datetime.now()
    try:
        completed = subprocess.run(
            command, cwd=str(cwd) if cwd.is_dir() else None,
            capture_output=True, timeout=timeout, shell=False,
            env=_subprocess_env(), check=False,
        )
        record.exit_code = completed.returncode
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        record.status = "succeeded" if completed.returncode == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        record.status = "timeout"
        record.error = f"超过 {timeout}s 未结束"
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else ""
    except (OSError, ValueError) as exc:
        record.status = "failed"
        record.error = f"无法启动子进程：{exc}"
        stdout, stderr = "", ""
    record.finished = datetime.now().isoformat(timespec="seconds")
    record.duration_sec = round((datetime.now() - started).total_seconds(), 3)
    record.stdout_tail = stdout[-TAIL_CHARS:]
    record.stderr_tail = stderr[-TAIL_CHARS:]
    record.artifacts = _collect_artifacts(out_dir)
    try:
        from steelai.web_api.tools import discover_result_dirs

        record.result_dirs = discover_result_dirs(out_dir)
    except Exception:  # noqa: BLE001 - a discovery failure must not fail the run
        record.result_dirs = []
    try:
        (log_dir() / f"{record.run_id}.log").write_text(
            f"$ {interpreter} {' '.join(argv)}\n\n--- stdout ---\n{stdout}\n\n--- stderr ---\n{stderr}\n",
            encoding="utf-8")
    except OSError:
        pass
    save_record(record)


def _prune_stage(root: Path, *, keep_days: int = 7) -> None:
    """Drop ``.stage/<run_id>/`` 暂存目录里超期的条目，避免任务目录无界增长。

    只清理超过 `keep_days` 的运行暂存；近期运行的输入快照保留着，方便对照
    manifest 复核"这次到底用了哪份字节"。
    """
    import shutil

    stage = root / ".stage"
    if not stage.is_dir():
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    for child in stage.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(child.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def create_run(project_id: str, task_id: str, tool_id: str, params: dict | None = None,
               actor: str = "web", session_id: str = "", actor_kind: str = "") -> dict:
    params = dict(params or {})
    reason = missing_asset_reason(tool_id)
    from steelai.web_api.tools import capability

    cap = capability(tool_id)
    if not cap.get("available", True):
        record = RunRecord(
            run_id="run-" + uuid.uuid4().hex[:12], project_id=project_id, task_id=task_id,
            tool_id=tool_id, tool_label=cap.get("label", tool_id), params=params,
            status="blocked", created=datetime.now().isoformat(timespec="seconds"),
            error=reason or "工具不可用", actor=actor, session_id=session_id,
            actor_kind=actor_kind,
        )
        save_record(record)
        return record.as_dict()

    root = task_root(project_id, task_id)
    if not (root / "TASK.md").is_file():
        raise GuardError(f"任务不存在：{project_id}/{task_id}")

    run_id = "run-" + uuid.uuid4().hex[:12]
    out_dir = root / "runs" / run_id
    if out_dir.exists():  # pragma: no cover - uuid collision is effectively impossible
        raise GuardError("运行标识冲突，请重试")

    existing_runs = sorted(item.name for item in (root / "runs").iterdir() if item.is_dir()) \
        if (root / "runs").is_dir() else []
    _prune_stage(root)
    provenance: dict = {}
    interpreter, argv, cwd = build_argv(
        tool_id, params, task_inputs=root / "inputs", out_dir=out_dir,
        run_id=run_id, existing_runs=existing_runs,
        project_id=project_id, task_id=task_id, provenance=provenance)

    if not Path(interpreter).is_file():
        record = RunRecord(
            run_id=run_id, project_id=project_id, task_id=task_id, tool_id=tool_id,
            tool_label=cap.get("label", tool_id), params=params, status="blocked",
            created=datetime.now().isoformat(timespec="seconds"),
            output_dir=str(out_dir), error=f"解释器不存在：{interpreter}", actor=actor,
            session_id=session_id, actor_kind=actor_kind, **provenance,
        )
        save_record(record)
        return record.as_dict()

    record = RunRecord(
        run_id=run_id, project_id=project_id, task_id=task_id, tool_id=tool_id,
        tool_label=cap.get("label", tool_id), params=params, status="queued",
        created=datetime.now().isoformat(timespec="seconds"),
        output_dir=str(out_dir), actor=actor, session_id=session_id,
        actor_kind=actor_kind, **provenance,
    )
    save_record(record)
    with _LOCK:
        _FUTURES[run_id] = _executor().submit(_execute, record, Path(interpreter), argv, Path(cwd))
    return record.as_dict()


def artifact_path(run_id: str, rel: str) -> Path:
    from steelai.web_api.security import resolve_under

    record = load_record(run_id)
    root = Path(record.output_dir)
    return resolve_under(root, rel)


def artifact_for_download(run_id: str, rel: str) -> tuple[Path, dict]:
    record = load_record(run_id)
    target = artifact_path(run_id, rel)
    if not target.is_file():
        raise GuardError("产物不存在")
    match = next((item for item in record.artifacts if item["rel"] == rel), None)
    return target, (match or {"name": target.name, "rel": rel, "size": target.stat().st_size})


def wait_for(run_id: str, timeout: float = 5.0) -> dict:
    """Test/CLI helper: block briefly so a synchronous caller can read a final state."""
    with _LOCK:
        future = _FUTURES.get(run_id)
    if future is not None:
        try:
            future.result(timeout=timeout)
        except Exception:  # noqa: BLE001 - the record already carries the failure
            pass
    return load_record(run_id).as_dict()
