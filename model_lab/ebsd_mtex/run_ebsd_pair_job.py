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


def run_mtex(matlab_exe: Path, project_root: Path, config_path: Path) -> int:
    script_dir = project_root / "model_lab" / "ebsd_mtex"
    statement = (
        f"addpath('{matlab_quote(str(script_dir))}'); "
        f"steelai_ebsd_run('{matlab_quote(str(config_path))}');"
    )
    completed = subprocess.run([str(matlab_exe), "-batch", statement], cwd=str(project_root), check=False)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--b-config", required=True)
    parser.add_argument("--r-config", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    sys.path.insert(0, str(project_root))
    from steelai.ebsd import MATLAB_EXE, write_ebsd_status
    from steelai.ebsd_comparison import write_comparison

    b_config_path = Path(args.b_config).resolve()
    r_config_path = Path(args.r_config).resolve()
    status_path = Path(args.status_file).resolve()
    pair_id = args.pair_id
    output_root = Path(args.output_root).resolve()
    configs = [("B-DQ", b_config_path), ("R-DQ", r_config_path)]
    outputs: dict[str, Path] = {}

    for sample_id, config_path in configs:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        outputs[sample_id] = Path(config["output_dir"])
        write_ebsd_status(
            {
                "job_id": pair_id,
                "status": "running",
                "current_sample": sample_id,
                "started_at": now(),
                "message": f"MATLAB/MTEX is processing {sample_id}.",
            },
            status_path,
        )
        return_code = run_mtex(MATLAB_EXE, project_root, config_path)
        if return_code != 0:
            write_ebsd_status(
                {
                    "job_id": pair_id,
                    "status": "failed",
                    "current_sample": sample_id,
                    "finished_at": now(),
                    "return_code": return_code,
                    "message": f"MATLAB/MTEX failed while processing {sample_id}.",
                },
                status_path,
            )
            return return_code

    artifacts = write_comparison(outputs["B-DQ"], outputs["R-DQ"], output_root)
    write_ebsd_status(
        {
            "job_id": pair_id,
            "status": "completed",
            "finished_at": now(),
            "return_code": 0,
            "message": "Matched B-DQ and R-DQ EBSD comparison completed successfully.",
            "outputs": {name: str(path) for name, path in artifacts.items()},
        },
        status_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
