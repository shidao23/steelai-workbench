from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from steelai.paths import ROOT
from steelai.settings import is_public_demo, load_settings


BLOCKED_SUFFIXES = {
    ".ang", ".ckpt", ".cpr", ".crc", ".ctf", ".docx", ".h5", ".hdf5",
    ".mat", ".onnx", ".pdf", ".pt", ".pth", ".tif", ".tiff", ".xls", ".xlsx",
}
TEXT_SUFFIXES = {
    ".cfg", ".cff", ".csv", ".json", ".md", ".m", ".py", ".toml", ".txt", ".yml", ".yaml",
}
IGNORED_DIRS = {".git", ".venv", "__pycache__", "outputs", "runtime"}

# These files deliberately contain fictitious Windows paths to prove that the
# Research Agent refuses raw/local-file requests. They contain no user data.
SECURITY_FIXTURES = {
    Path("config/agent_eval_benchmark_v0.1.json"),
    Path("tests/test_agent_evaluation.py"),
    Path("tests/test_research_case.py"),
}


def _iter_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.relative_to(ROOT).parts)
    ]


def _scan_repository() -> list[str]:
    failures: list[str] = []
    blocked_markers = (
        "D:" + "\\Desktop",
        "D:" + "/Desktop",
        "C:" + "\\Users",
        "C:" + "/Users",
        "02_" + "实验数据",
        "98_" + "科研工作台",
        "187872" + "36074",
    )
    secret_patterns = (
        re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"(?i)(api[_-]?key|token|password)\s*[=:]\s*['\"][^'\"]{8,}['\"]"),
    )

    for path in _iter_files():
        relative = path.relative_to(ROOT)
        if path.suffix.lower() in BLOCKED_SUFFIXES or ".zarr" in relative.parts:
            failures.append(f"blocked artifact: {relative.as_posix()}")
            continue
        if path.stat().st_size > 1_000_000:
            failures.append(f"file exceeds public limit: {relative.as_posix()}")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"LICENSE", ".gitignore", ".python-version"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"unexpected binary file: {relative.as_posix()}")
            continue
        if relative not in SECURITY_FIXTURES:
            for marker in blocked_markers:
                if marker.casefold() in text.casefold():
                    failures.append(f"private marker in {relative.as_posix()}")
                    break
        for pattern in secret_patterns:
            if pattern.search(text):
                failures.append(f"possible secret in {relative.as_posix()}")
                break
    return failures


def _validate_public_configuration() -> list[str]:
    failures: list[str] = []
    settings = load_settings()
    if not is_public_demo():
        failures.append("project.public_demo must be true")
    if settings.get("ai", {}).get("enabled", True):
        failures.append("AI must be disabled in the public demo")
    for group in ("sources", "specialists"):
        configured = {key: value for key, value in settings.get(group, {}).items() if value}
        if configured:
            failures.append(f"{group} contains local configuration: {sorted(configured)}")
    return failures


def _validate_synthetic_data() -> list[str]:
    failures: list[str] = []
    processed = ROOT / "data" / "processed"
    for name in ("composition.csv", "process.csv", "properties.csv"):
        path = processed / name
        if not path.exists():
            failures.append(f"missing public fixture: data/processed/{name}")
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or any(row.get("source_status") != "synthetic_ci" for row in rows):
            failures.append(f"non-synthetic status in data/processed/{name}")

    samples_path = processed / "samples.csv"
    if not samples_path.exists():
        failures.append("missing public fixture: data/processed/samples.csv")
    else:
        with samples_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or any(row.get("is_demo", "").casefold() != "true" for row in rows):
            failures.append("all public samples must set is_demo=true")
        if any(row.get("data_status") != "synthetic_ci" for row in rows):
            failures.append("all public samples must set data_status=synthetic_ci")
    return failures


def run_publication_gate() -> dict[str, object]:
    failures = _scan_repository() + _validate_public_configuration() + _validate_synthetic_data()
    return {
        "schema_version": "1.0",
        "status": "passed" if not failures else "failed",
        "public_demo": is_public_demo(),
        "synthetic_data_only": not any("synthetic" in item or "sample" in item for item in failures),
        "failures": failures,
    }


def main() -> int:
    report = run_publication_gate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
