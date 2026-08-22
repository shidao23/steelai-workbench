from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def matlab_quote(value: str) -> str:
    return value.replace("'", "''")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--status-file", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    sys.path.insert(0, str(project_root))
    from steelai.ebsd import MATLAB_EXE, PILOT_RUN_ID, write_ebsd_status

    config_path = Path(args.config).resolve()
    status_path = Path(args.status_file).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    script_dir = project_root / "model_lab" / "ebsd_mtex"
    statement = (
        f"addpath('{matlab_quote(str(script_dir))}'); "
        f"steelai_ebsd_run('{matlab_quote(str(config_path))}');"
    )
    command = [str(MATLAB_EXE), "-batch", statement]
    write_ebsd_status(
        {
            "job_id": PILOT_RUN_ID,
            "status": "running",
            "started_at": now(),
            "message": "MATLAB/MTEX is processing the selected read-only CTF file.",
            "command": [str(MATLAB_EXE), "-batch", "steelai_ebsd_run(<config>)"],
        },
        status_path,
    )
    completed = subprocess.run(command, cwd=str(project_root), check=False)
    if completed.returncode == 0:
        write_ebsd_status(
            {
                "job_id": PILOT_RUN_ID,
                "status": "completed",
                "finished_at": now(),
                "return_code": 0,
                "message": "B-DQ EBSD pilot completed successfully.",
                "result_root": config["output_dir"],
            },
            status_path,
        )
        return 0

    write_ebsd_status(
        {
            "job_id": PILOT_RUN_ID,
            "status": "failed",
            "finished_at": now(),
            "return_code": completed.returncode,
            "message": "MATLAB/MTEX failed. Review the EBSD job log.",
        },
        status_path,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
