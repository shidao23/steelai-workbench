from __future__ import annotations

import configparser
import csv
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from steelai.paths import INDEX, OUTPUTS, ROOT


PILOT_FILE = INDEX / "model_lab_pilot.csv"
MICRO_SAM_DIR = ROOT / "model_lab" / "micro_sam"
MICRO_SAM_STATUS_FILE = MICRO_SAM_DIR / "environment_status.json"
MICRO_SAM_REPORT_FILE = OUTPUTS / "model_lab" / "micro_sam_smoke" / "smoke_test_report.json"


MODEL_REGISTRY = [
    {
        "model": "micro-sam",
        "task": "OM/SEM interactive segmentation",
        "input": "Microscopy image + point/box prompts",
        "output": "Reviewed masks and measurements",
        "license": "MIT",
        "readiness": "pilot_ready",
        "package": "micro_sam",
        "repository": "https://github.com/computational-cell-analytics/micro-sam",
    },
    {
        "model": "pycalphad",
        "task": "CALPHAD equilibrium and phase stability",
        "input": "Composition + TDB + conditions",
        "output": "Phase fractions and thermodynamic properties",
        "license": "MIT (database separate)",
        "readiness": "database_required",
        "package": "pycalphad",
        "repository": "https://github.com/pycalphad/pycalphad",
    },
    {
        "model": "CrabNet",
        "task": "Composition-only property prediction",
        "input": "Formula/composition + labelled target",
        "output": "Prediction + composition attention",
        "license": "MIT",
        "readiness": "more_samples_required",
        "package": "crabnet",
        "repository": "https://github.com/anthony-wang/CrabNet",
    },
    {
        "model": "MODNet",
        "task": "Limited-data materials property learning",
        "input": "Composition/structure + labelled target",
        "output": "Multi-property predictions",
        "license": "MIT",
        "readiness": "more_samples_required",
        "package": "modnet",
        "repository": "https://github.com/ppdebreuck/modnet",
    },
]


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def micro_sam_status() -> dict[str, str | bool | float]:
    status = _read_json(MICRO_SAM_STATUS_FILE)
    configured_environment = status.get("active_environment_path", "")
    conda_python = Path(configured_environment) / "python.exe" if configured_environment else Path()
    legacy_python = MICRO_SAM_DIR / ".venv-micro-sam" / "Scripts" / "python.exe"
    environment_python = conda_python if configured_environment and conda_python.exists() else legacy_python
    checkpoint = MICRO_SAM_DIR / "weights" / "sam_vit_b_01ec64.pth"
    report = _read_json(MICRO_SAM_REPORT_FILE)
    return {
        **status,
        "environment_ready": environment_python.exists(),
        "conda_environment_ready": bool(configured_environment and conda_python.exists()),
        "checkpoint_ready": checkpoint.exists(),
        "smoke_test_ready": bool(report.get("results")),
        "checkpoint_path": str(checkpoint),
        "report_path": str(MICRO_SAM_REPORT_FILE),
    }


def smoke_test_report() -> dict:
    return _read_json(MICRO_SAM_REPORT_FILE)


def calphad_status() -> dict[str, str | bool]:
    """Local status of the optional T86 CALPHAD adapter without importing pycalphad."""
    try:
        from steelai.calphad_adapter import status_row

        return dict(status_row())
    except Exception as exc:  # never let the optional adapter break the registry view
        return {
            "state": "blocked",
            "local_status": "adapter_status_unavailable",
            "headline": f"CALPHAD 适配器状态不可用：{type(exc).__name__}",
            "has_authorized_database": False,
        }


def model_statuses() -> list[dict[str, str]]:
    micro_sam = micro_sam_status()
    calphad = calphad_status()
    rows = []
    for model in MODEL_REGISTRY:
        if model["model"] == "micro-sam":
            if micro_sam["smoke_test_ready"]:
                local_status = "gpu_smoke_test_passed"
            elif micro_sam["environment_ready"] and micro_sam["checkpoint_ready"]:
                local_status = "isolated_gpu_environment_ready"
            else:
                local_status = "isolated_install_pending"
            extra: dict[str, str] = {}
        elif model["model"] == "pycalphad":
            local_status = str(calphad["local_status"])
            extra = {"state": str(calphad["state"]), "headline": str(calphad["headline"])}
        else:
            installed = importlib.util.find_spec(model["package"]) is not None
            local_status = "installed" if installed else "isolated_install_pending"
            extra = {}
        rows.append({**model, "local_status": local_status, **extra})
    return rows


def gpu_status() -> dict[str, str]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=True)
        name, memory, driver = [item.strip() for item in result.stdout.strip().split(",", 2)]
        return {"status": "available", "name": name, "memory": memory, "driver": driver}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"status": "not_detected", "name": "", "memory": "", "driver": ""}


def find_dq_fractography_dir(experiment_root: str | Path) -> Path | None:
    root = Path(experiment_root)
    if not root.exists():
        return None
    matches = sorted(path for path in root.rglob("20260803SEM-DQ-冲击断口") if path.is_dir())
    preferred = [path for path in matches if "OM_SEM_EBSD" in path.parts]
    return (preferred or matches or [None])[0]


def _read_hdr(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return dict(parser["MAIN"]) if parser.has_section("MAIN") else {}


def scan_sem_directory(directory: str | Path) -> list[dict[str, str | float]]:
    directory = Path(directory)
    rows: list[dict[str, str | float]] = []
    for hdr_path in sorted(directory.glob("*-TIF.hdr")):
        tif_path = hdr_path.with_name(hdr_path.name.replace("-TIF.hdr", ".TIF"))
        if not tif_path.exists():
            continue
        metadata = _read_hdr(hdr_path)
        filename = tif_path.stem
        steel = filename.split("-", 1)[0].upper()
        magnification = float(metadata.get("magnification", 0) or 0)
        pixel_size_um = float(metadata.get("pixelsizex", 0) or 0) * 1_000_000
        rows.append(
            {
                "evidence_id": f"SEM_{filename}",
                "sample_id": f"{steel}-DQ",
                "steel": steel,
                "filename": tif_path.name,
                "magnification_x": magnification,
                "pixel_size_um": pixel_size_um,
                "image_path": str(tif_path),
                "metadata_path": str(hdr_path),
                "review_status": "pilot_candidate",
                "is_sensitive": "true",
            }
        )
    return rows


def select_balanced_pilot(
    rows: list[dict[str, str | float]], magnification: float = 1000, per_steel: int = 5
) -> list[dict[str, str | float]]:
    selected: list[dict[str, str | float]] = []
    for steel in ("B", "R"):
        candidates = [
            row
            for row in rows
            if row["steel"] == steel and abs(float(row["magnification_x"]) - magnification) < 1
        ]
        selected.extend(candidates[:per_steel])
    return selected


def save_pilot_manifest(rows: list[dict[str, str | float]], path: Path = PILOT_FILE) -> Path:
    if not rows:
        raise ValueError("Pilot manifest cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def tif_preview(path: str | Path, max_size: tuple[int, int] = (900, 900)) -> Image.Image:
    with Image.open(path) as image:
        array = np.asarray(image, dtype=np.float32)
    low, high = np.percentile(array, (1, 99))
    if high <= low:
        normalized = np.zeros_like(array, dtype=np.uint8)
    else:
        normalized = np.clip((array - low) / (high - low) * 255, 0, 255).astype(np.uint8)
    preview = Image.fromarray(normalized)
    preview.thumbnail(max_size)
    return preview
