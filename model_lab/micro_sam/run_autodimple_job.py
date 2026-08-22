from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AutoDimple as a SteelAI background job.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    started_at = now()
    write_status(
        args.status_file,
        {
            "job_id": "autodimple_br10",
            "status": "running",
            "started_at": started_at,
            "message": "AutoDimple B/R batch is running in the background.",
        },
    )
    command = [
        sys.executable,
        str(root / "model_lab" / "micro_sam" / "run_batch_autodimple.py"),
        "--project-root",
        str(root),
        "--manifest",
        str(root / "data" / "index" / "model_lab_pilot.csv"),
        "--standard",
        str(root / "config" / "micro_sam_auto_standard_v0.2.json"),
        "--checkpoint",
        str(root / "model_lab" / "micro_sam" / "weights" / "sam_vit_b_01ec64.pth"),
        "--output-root",
        str(root / "outputs" / "model_lab" / "auto_dimple" / "BR10_1000x_v0.1"),
    ]
    try:
        result = subprocess.run(command, cwd=str(root), check=False)
        batch_manifest = root / "outputs" / "model_lab" / "auto_dimple" / "BR10_1000x_v0.1" / "batch_manifest_v0.1.json"
        success = result.returncode == 0 and batch_manifest.exists()
        payload = {
            "job_id": "autodimple_br10",
            "status": "completed" if success else "failed",
            "started_at": started_at,
            "finished_at": now(),
            "return_code": result.returncode,
            "message": "AutoDimple B/R batch completed successfully." if success else "AutoDimple batch failed. Read the log for details.",
            "result_available": batch_manifest.exists(),
            "result_root": str(batch_manifest.parent),
        }
        write_status(args.status_file, payload)
        return 0 if success else 1
    except Exception as exc:
        write_status(
            args.status_file,
            {
                "job_id": "autodimple_br10",
                "status": "failed",
                "started_at": started_at,
                "finished_at": now(),
                "message": f"AutoDimple job failed: {exc}",
                "result_available": False,
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
