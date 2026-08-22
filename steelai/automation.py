from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from steelai.paths import OUTPUTS, ROOT
from steelai.settings import load_settings


AUTOMATION_ROOT = OUTPUTS / "automation"
AUTODIMPLE_STATUS = AUTOMATION_ROOT / "autodimple_br10_status.json"
AUTODIMPLE_LOG = AUTOMATION_ROOT / "autodimple_br10.log"
AUTODIMPLE_RESULT_ROOT = OUTPUTS / "model_lab" / "auto_dimple" / "BR10_1000x_v0.1"
AUTODIMPLE_BATCH_MANIFEST = AUTODIMPLE_RESULT_ROOT / "batch_manifest_v0.1.json"
_specialists = load_settings().get("specialists", {})
_micro_sam_python = str(_specialists.get("micro_sam_python", "")).strip()
CONDA_PYTHON = Path(_micro_sam_python).expanduser() if _micro_sam_python else ROOT / "runtime" / "not_configured" / "micro-sam-python"
JOB_RUNNER = ROOT / "model_lab" / "micro_sam" / "run_autodimple_job.py"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_status(payload: dict[str, Any], path: Path = AUTODIMPLE_STATUS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_job_status(path: Path = AUTODIMPLE_STATUS) -> dict[str, Any]:
    status = _read_json(path)
    if not status:
        status = {
            "job_id": "autodimple_br10",
            "status": "ready" if AUTODIMPLE_BATCH_MANIFEST.exists() else "idle",
            "message": "Existing batch results are available." if AUTODIMPLE_BATCH_MANIFEST.exists() else "Not run yet.",
        }
    status["result_available"] = AUTODIMPLE_BATCH_MANIFEST.exists()
    status["result_root"] = str(AUTODIMPLE_RESULT_ROOT)
    return status


def read_log_tail(path: Path = AUTODIMPLE_LOG, max_lines: int = 80) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def launch_autodimple_batch() -> dict[str, Any]:
    current = read_job_status()
    if current.get("status") == "running":
        return current
    if not CONDA_PYTHON.exists():
        raise FileNotFoundError(f"Conda Python was not found: {CONDA_PYTHON}")
    if not JOB_RUNNER.exists():
        raise FileNotFoundError(f"Job runner was not found: {JOB_RUNNER}")

    AUTOMATION_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        str(CONDA_PYTHON),
        str(JOB_RUNNER),
        "--project-root",
        str(ROOT),
        "--status-file",
        str(AUTODIMPLE_STATUS),
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with AUTODIMPLE_LOG.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=environment,
            creationflags=creation_flags,
            close_fds=True,
        )
    status = {
        "job_id": "autodimple_br10",
        "status": "running",
        "pid": process.pid,
        "started_at": _now(),
        "message": "AutoDimple B/R batch is running in the background.",
        "result_available": AUTODIMPLE_BATCH_MANIFEST.exists(),
        "result_root": str(AUTODIMPLE_RESULT_ROOT),
    }
    write_status(status)
    return status
