from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from steelai.paths import OUTPUTS, ROOT
from steelai.settings import load_settings


def _specialist_path(key: str) -> Path:
    value = str(load_settings().get("specialists", {}).get(key, "")).strip()
    return Path(value).expanduser() if value else ROOT / "runtime" / "not_configured" / key


PILOT_SAMPLE_ID = "B-DQ"
PILOT_RUN_ID = "B-DQ_region2_1000x_pilot_v0.1"
PILOT_CTF = _specialist_path("ebsd_pilot_ctf")
B_MATCHED_CTF = _specialist_path("ebsd_b_matched_ctf")
R_MATCHED_CTF = _specialist_path("ebsd_r_matched_ctf")
R_HIGHRES_CTF = _specialist_path("ebsd_r_highres_ctf")
MATLAB_EXE = _specialist_path("matlab_exe")
MTEX_ROOT = _specialist_path("mtex_root")
EBSD_OUTPUT_ROOT = OUTPUTS / "ebsd" / PILOT_RUN_ID
EBSD_AUTOMATION_ROOT = OUTPUTS / "automation"
EBSD_STATUS = EBSD_AUTOMATION_ROOT / "ebsd_b_dq_pilot_status.json"
EBSD_LOG = EBSD_AUTOMATION_ROOT / "ebsd_b_dq_pilot.log"
EBSD_CONFIG = EBSD_OUTPUT_ROOT / "job_config.json"
EBSD_SUMMARY = EBSD_OUTPUT_ROOT / "summary.json"
EBSD_GRAINS = EBSD_OUTPUT_ROOT / "grains.csv"
EBSD_RUNNER = ROOT / "model_lab" / "ebsd_mtex" / "run_ebsd_job.py"
MATLAB_ENTRYPOINT = ROOT / "model_lab" / "ebsd_mtex" / "steelai_ebsd_run.m"
BR_PAIR_ID = "BR_DQ_1000x_step0.5_v0.1"
BR_OUTPUT_ROOT = OUTPUTS / "ebsd" / BR_PAIR_ID
BR_B_OUTPUT = BR_OUTPUT_ROOT / "B-DQ"
BR_R_OUTPUT = BR_OUTPUT_ROOT / "R-DQ"
BR_B_CONFIG = BR_B_OUTPUT / "job_config.json"
BR_R_CONFIG = BR_R_OUTPUT / "job_config.json"
BR_STATUS = EBSD_AUTOMATION_ROOT / "ebsd_br_pair_status.json"
BR_LOG = EBSD_AUTOMATION_ROOT / "ebsd_br_pair.log"
BR_COMPARISON = BR_OUTPUT_ROOT / "comparison.json"
BR_COMPARISON_TABLE = BR_OUTPUT_ROOT / "comparison.csv"
BR_REPORT = BR_OUTPUT_ROOT / "B_vs_R_EBSD_preliminary_report.md"
BR_RUNNER = ROOT / "model_lab" / "ebsd_mtex" / "run_ebsd_pair_job.py"
HIGHRES_PAIR_ID = "BR_DQ_2000x_step0.15_v0.1"
HIGHRES_OUTPUT_ROOT = OUTPUTS / "ebsd" / HIGHRES_PAIR_ID
HIGHRES_B_OUTPUT = HIGHRES_OUTPUT_ROOT / "B-DQ"
HIGHRES_R_OUTPUT = HIGHRES_OUTPUT_ROOT / "R-DQ"
HIGHRES_B_CONFIG = HIGHRES_B_OUTPUT / "job_config.json"
HIGHRES_R_CONFIG = HIGHRES_R_OUTPUT / "job_config.json"
HIGHRES_STATUS = EBSD_AUTOMATION_ROOT / "ebsd_br_highres_status.json"
HIGHRES_LOG = EBSD_AUTOMATION_ROOT / "ebsd_br_highres.log"
HIGHRES_COMPARISON = HIGHRES_OUTPUT_ROOT / "comparison.json"
HIGHRES_COMPARISON_TABLE = HIGHRES_OUTPUT_ROOT / "comparison.csv"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_ebsd_status(payload: dict[str, Any], path: Path = EBSD_STATUS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_ebsd_status(path: Path = EBSD_STATUS) -> dict[str, Any]:
    status = _read_json(path)
    if not status:
        status = {
            "job_id": PILOT_RUN_ID,
            "status": "ready" if EBSD_SUMMARY.exists() else "idle",
            "message": "Existing pilot results are available." if EBSD_SUMMARY.exists() else "Pilot has not run yet.",
        }
    status["result_available"] = EBSD_SUMMARY.exists()
    status["result_root"] = str(EBSD_OUTPUT_ROOT)
    return status


def read_ebsd_log(max_lines: int = 100) -> str:
    if not EBSD_LOG.exists():
        return ""
    try:
        lines = EBSD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def read_ctf_header(path: Path = PILOT_CTF) -> dict[str, Any]:
    metadata: dict[str, Any] = {"path": str(path), "available": path.exists(), "phases": []}
    if not path.exists():
        return metadata

    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            lines.append(line.rstrip("\r\n"))
            if line.startswith("Phase\tX\tY"):
                break

    scalar_keys = {
        "XCells": ("x_cells", int),
        "YCells": ("y_cells", int),
        "XStep": ("x_step_um", float),
        "YStep": ("y_step_um", float),
        "Phases": ("phase_count", int),
    }
    phase_lines_remaining = 0
    for line in lines:
        parts = line.split("\t")
        key = parts[0] if parts else ""
        if key in scalar_keys and len(parts) > 1:
            output_key, converter = scalar_keys[key]
            try:
                metadata[output_key] = converter(parts[1])
            except ValueError:
                metadata[output_key] = parts[1]
            if key == "Phases":
                phase_lines_remaining = int(parts[1])
            continue
        if line.startswith("Euler angles refer"):
            for label, output_key, converter in (
                ("Mag", "magnification", float),
                ("Coverage", "coverage_percent", float),
                ("KV", "voltage_kv", float),
                ("TiltAngle", "tilt_angle_deg", float),
            ):
                if label in parts:
                    index = parts.index(label)
                    if index + 1 < len(parts):
                        try:
                            metadata[output_key] = converter(parts[index + 1])
                        except ValueError:
                            metadata[output_key] = parts[index + 1]
            continue
        if phase_lines_remaining > 0 and ";" in line and len(parts) >= 3:
            metadata["phases"].append(parts[2])
            phase_lines_remaining -= 1

    metadata["file_size_mb"] = round(path.stat().st_size / 1024**2, 2)
    return metadata


def build_analysis_config(sample_id: str, run_id: str, input_file: Path, output_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "sample_id": sample_id,
        "input_file": str(input_file),
        "output_dir": str(output_dir),
        "mtex_root": str(MTEX_ROOT),
        "mtex_version_expected": "6.1.0",
        "target_phase": "Iron bcc (old)",
        "retained_phase": "Iron fcc",
        "grain_angle_deg": 3.0,
        "min_grain_pixels": 5,
        "grain_smoothing_iterations": 5,
        "lagb_min_deg": 2.0,
        "hagb_min_deg": 15.0,
        "kam_order": 1,
        "kam_threshold_deg": 2.5,
        "analysis_scope": "basic_ebsd_pilot",
        "parent_reconstruction_enabled": False,
        "raw_files_read_only": True,
    }


def build_pilot_config() -> dict[str, Any]:
    return build_analysis_config(PILOT_SAMPLE_ID, PILOT_RUN_ID, PILOT_CTF, EBSD_OUTPUT_ROOT)


def build_matched_pair_configs() -> tuple[dict[str, Any], dict[str, Any]]:
    b_config = build_analysis_config("B-DQ", f"{BR_PAIR_ID}_B", B_MATCHED_CTF, BR_B_OUTPUT)
    r_config = build_analysis_config("R-DQ", f"{BR_PAIR_ID}_R", R_MATCHED_CTF, BR_R_OUTPUT)
    b_config["analysis_scope"] = "matched_br_ebsd_comparison"
    r_config["analysis_scope"] = "matched_br_ebsd_comparison"
    return b_config, r_config


def build_highres_pair_configs() -> tuple[dict[str, Any], dict[str, Any]]:
    b_config = build_analysis_config("B-DQ", f"{HIGHRES_PAIR_ID}_B", PILOT_CTF, HIGHRES_B_OUTPUT)
    r_config = build_analysis_config("R-DQ", f"{HIGHRES_PAIR_ID}_R", R_HIGHRES_CTF, HIGHRES_R_OUTPUT)
    b_config["analysis_scope"] = "matched_br_high_resolution_ebsd_comparison"
    r_config["analysis_scope"] = "matched_br_high_resolution_ebsd_comparison"
    return b_config, r_config


def write_pilot_config() -> Path:
    EBSD_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    EBSD_CONFIG.write_text(json.dumps(build_pilot_config(), ensure_ascii=False, indent=2), encoding="utf-8")
    return EBSD_CONFIG


def write_matched_pair_configs() -> tuple[Path, Path]:
    b_config, r_config = build_matched_pair_configs()
    BR_B_OUTPUT.mkdir(parents=True, exist_ok=True)
    BR_R_OUTPUT.mkdir(parents=True, exist_ok=True)
    BR_B_CONFIG.write_text(json.dumps(b_config, ensure_ascii=False, indent=2), encoding="utf-8")
    BR_R_CONFIG.write_text(json.dumps(r_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return BR_B_CONFIG, BR_R_CONFIG


def write_highres_pair_configs() -> tuple[Path, Path]:
    b_config, r_config = build_highres_pair_configs()
    HIGHRES_B_OUTPUT.mkdir(parents=True, exist_ok=True)
    HIGHRES_R_OUTPUT.mkdir(parents=True, exist_ok=True)
    HIGHRES_B_CONFIG.write_text(json.dumps(b_config, ensure_ascii=False, indent=2), encoding="utf-8")
    HIGHRES_R_CONFIG.write_text(json.dumps(r_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return HIGHRES_B_CONFIG, HIGHRES_R_CONFIG


def environment_status() -> dict[str, bool]:
    return {
        "pilot_ctf": PILOT_CTF.exists(),
        "matlab": MATLAB_EXE.exists(),
        "mtex": (MTEX_ROOT / "startup_mtex.m").exists(),
        "matlab_entrypoint": MATLAB_ENTRYPOINT.exists(),
        "job_runner": EBSD_RUNNER.exists(),
    }


def matched_pair_environment_status() -> dict[str, bool]:
    status = environment_status()
    status.update(
        {
            "matched_b_ctf": B_MATCHED_CTF.exists(),
            "matched_r_ctf": R_MATCHED_CTF.exists(),
            "pair_job_runner": BR_RUNNER.exists(),
        }
    )
    return status


def highres_pair_environment_status() -> dict[str, bool]:
    status = environment_status()
    status.update(
        {
            "highres_b_ctf": PILOT_CTF.exists(),
            "highres_r_ctf": R_HIGHRES_CTF.exists(),
            "pair_job_runner": BR_RUNNER.exists(),
        }
    )
    return status


def launch_ebsd_pilot() -> dict[str, Any]:
    current = read_ebsd_status()
    if current.get("status") == "running":
        return current
    missing = [name for name, available in environment_status().items() if not available]
    if missing:
        raise FileNotFoundError(f"Missing EBSD runtime components: {', '.join(missing)}")

    config_path = write_pilot_config()
    EBSD_AUTOMATION_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(EBSD_RUNNER),
        "--project-root",
        str(ROOT),
        "--config",
        str(config_path),
        "--status-file",
        str(EBSD_STATUS),
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with EBSD_LOG.open("a", encoding="utf-8") as log_handle:
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
        "job_id": PILOT_RUN_ID,
        "status": "running",
        "pid": process.pid,
        "started_at": _now(),
        "message": "B-DQ EBSD pilot is running in MATLAB/MTEX.",
        "result_available": EBSD_SUMMARY.exists(),
        "result_root": str(EBSD_OUTPUT_ROOT),
    }
    write_ebsd_status(status)
    return status


def read_ebsd_summary() -> dict[str, Any]:
    return _read_json(EBSD_SUMMARY)


def read_matched_pair_status() -> dict[str, Any]:
    status = _read_json(BR_STATUS)
    if not status:
        status = {
            "job_id": BR_PAIR_ID,
            "status": "ready" if BR_COMPARISON.exists() else "idle",
            "message": "Existing B/R results are available." if BR_COMPARISON.exists() else "Matched B/R analysis has not run yet.",
        }
    status["result_available"] = BR_COMPARISON.exists()
    status["result_root"] = str(BR_OUTPUT_ROOT)
    return status


def read_matched_pair_log(max_lines: int = 120) -> str:
    if not BR_LOG.exists():
        return ""
    try:
        lines = BR_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def launch_matched_pair() -> dict[str, Any]:
    current = read_matched_pair_status()
    if current.get("status") == "running":
        return current
    missing = [name for name, available in matched_pair_environment_status().items() if not available]
    if missing:
        raise FileNotFoundError(f"Missing matched B/R runtime components: {', '.join(missing)}")

    b_config, r_config = write_matched_pair_configs()
    EBSD_AUTOMATION_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(BR_RUNNER),
        "--project-root",
        str(ROOT),
        "--b-config",
        str(b_config),
        "--r-config",
        str(r_config),
        "--status-file",
        str(BR_STATUS),
        "--pair-id",
        BR_PAIR_ID,
        "--output-root",
        str(BR_OUTPUT_ROOT),
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with BR_LOG.open("a", encoding="utf-8") as log_handle:
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
        "job_id": BR_PAIR_ID,
        "status": "running",
        "pid": process.pid,
        "started_at": _now(),
        "message": "Matched B-DQ and R-DQ EBSD analysis is running in MATLAB/MTEX.",
        "result_available": BR_COMPARISON.exists(),
        "result_root": str(BR_OUTPUT_ROOT),
    }
    write_ebsd_status(status, BR_STATUS)
    return status


def read_matched_comparison() -> dict[str, Any]:
    return _read_json(BR_COMPARISON)


def read_highres_pair_status() -> dict[str, Any]:
    status = _read_json(HIGHRES_STATUS)
    if not status:
        status = {
            "job_id": HIGHRES_PAIR_ID,
            "status": "ready" if HIGHRES_COMPARISON.exists() else "idle",
            "message": "Existing high-resolution B/R results are available." if HIGHRES_COMPARISON.exists() else "High-resolution B/R analysis has not run yet.",
        }
    status["result_available"] = HIGHRES_COMPARISON.exists()
    status["result_root"] = str(HIGHRES_OUTPUT_ROOT)
    return status


def read_highres_pair_log(max_lines: int = 120) -> str:
    if not HIGHRES_LOG.exists():
        return ""
    try:
        lines = HIGHRES_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def launch_highres_pair() -> dict[str, Any]:
    current = read_highres_pair_status()
    if current.get("status") == "running":
        return current
    missing = [name for name, available in highres_pair_environment_status().items() if not available]
    if missing:
        raise FileNotFoundError(f"Missing high-resolution B/R runtime components: {', '.join(missing)}")

    b_config, r_config = write_highres_pair_configs()
    EBSD_AUTOMATION_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(BR_RUNNER),
        "--project-root",
        str(ROOT),
        "--b-config",
        str(b_config),
        "--r-config",
        str(r_config),
        "--status-file",
        str(HIGHRES_STATUS),
        "--pair-id",
        HIGHRES_PAIR_ID,
        "--output-root",
        str(HIGHRES_OUTPUT_ROOT),
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with HIGHRES_LOG.open("a", encoding="utf-8") as log_handle:
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
        "job_id": HIGHRES_PAIR_ID,
        "status": "running",
        "pid": process.pid,
        "started_at": _now(),
        "message": "High-resolution B-DQ and R-DQ EBSD analysis is running in MATLAB/MTEX.",
        "result_available": HIGHRES_COMPARISON.exists(),
        "result_root": str(HIGHRES_OUTPUT_ROOT),
    }
    write_ebsd_status(status, HIGHRES_STATUS)
    return status


def read_highres_comparison() -> dict[str, Any]:
    return _read_json(HIGHRES_COMPARISON)
