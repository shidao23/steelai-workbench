"""Optional Frictionless adapter for the public graduation-v1 data package.

The native SteelAI contract remains authoritative.  This module imports
Frictionless lazily so the core application and quality gate work unchanged
when the optional dependency is not installed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import time
from importlib import metadata
from pathlib import Path
from typing import Any

from steelai.graduation_data_contract import (
    CONTRACT_PATH,
    load_graduation_contract,
    validate_graduation_contract,
)
from steelai.paths import ROOT


ADAPTER_VERSION = "1.0"
EXPECTED_FRICTIONLESS_VERSION = "5.19.0"
EXAMPLE_DIR = ROOT / "data" / "examples" / "graduation_contract_v1"
DESCRIPTOR_PATH = EXAMPLE_DIR / "datapackage.json"
EVALUATION_PATH = ROOT / "config" / "frictionless_adapter_evaluation_v1.0.json"

RESOURCE_ORDER = ("materials", "heats", "samples", "specimens", "reports", "observations")
FOREIGN_KEYS = {
    "heats": [("material_id", "materials", "material_id")],
    "samples": [
        ("material_id", "materials", "material_id"),
        ("heat_id", "heats", "heat_id"),
    ],
    "specimens": [("sample_id", "samples", "sample_id")],
    "observations": [("report_id", "reports", "report_id")],
}


def frictionless_availability() -> dict[str, Any]:
    """Report availability without importing or requiring Frictionless."""
    try:
        version = metadata.version("frictionless")
    except metadata.PackageNotFoundError:
        return {
            "available": False,
            "ready": False,
            "version": None,
            "expected_version": EXPECTED_FRICTIONLESS_VERSION,
            "reason": "optional_dependency_not_installed",
        }
    ready = version == EXPECTED_FRICTIONLESS_VERSION
    return {
        "available": True,
        "ready": ready,
        "version": version,
        "expected_version": EXPECTED_FRICTIONLESS_VERSION,
        "reason": "ready" if ready else "version_mismatch",
    }


def _field_descriptor(table_name: str, field: str, spec: dict[str, Any]) -> dict[str, Any]:
    field_type = "string"
    if field in spec.get("numeric_fields", []):
        field_type = "number"
    elif table_name == "observations" and field == "replicate_count":
        field_type = "integer"
    constraints: dict[str, Any] = {}
    if field in spec.get("required_fields", []) and field not in spec.get("nullable_fields", []):
        constraints["required"] = True
    allowed = spec.get("allowed_values", {}).get(field)
    if allowed:
        constraints["enum"] = allowed
    result: dict[str, Any] = {"name": field, "type": field_type}
    if constraints:
        result["constraints"] = constraints
    return result


def build_data_package_descriptor(
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
    descriptor_dir: Path = EXAMPLE_DIR,
) -> dict[str, Any]:
    """Translate the frozen native contract into a portable tabular package.

    Conditional subject identity and scientific rules cannot be represented by
    ordinary Data Package foreign keys; those deliberately stay in SteelAI's
    native validator and are stated in the package description.
    """
    contract = load_graduation_contract(contract_path)
    root = project_root.resolve()
    destination = descriptor_dir.resolve()
    resources = []
    for table_name in RESOURCE_ORDER:
        spec = contract["tables"][table_name]
        source = (root / spec["path"]).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"{table_name}: source path escapes project root.")
        fields = [
            _field_descriptor(table_name, field, spec)
            for field in spec.get("required_fields", []) + spec.get("optional_fields", [])
        ]
        primary_key = spec["primary_key"]
        schema: dict[str, Any] = {
            "fields": fields,
            "primaryKey": primary_key[0] if len(primary_key) == 1 else primary_key,
        }
        foreign_keys = [
            {
                "fields": field,
                "reference": {"resource": resource, "fields": target_field},
            }
            for field, resource, target_field in FOREIGN_KEYS.get(table_name, [])
        ]
        if foreign_keys:
            schema["foreignKeys"] = foreign_keys
        resources.append({
            "profile": "tabular-data-resource",
            "name": table_name,
            "type": "table",
            "path": Path(os.path.relpath(source, destination)).as_posix(),
            "scheme": "file",
            "format": "csv",
            "mediatype": "text/csv",
            "encoding": "utf-8",
            "schema": schema,
        })
    return {
        "profile": "tabular-data-package",
        "name": "steelai-graduation-core-v1",
        "title": "SteelAI Graduation Core v1 public synthetic package",
        "description": (
            "Portable structural description of the public synthetic tensile example. "
            "SteelAI's frozen native contract remains authoritative for conditional "
            "subject identity, units, statistics, provenance and scientific rules."
        ),
        "version": "1.0.0",
        "resources": resources,
    }


def write_data_package_descriptor(
    output_path: Path = DESCRIPTOR_PATH,
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
) -> Path:
    output = output_path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = build_data_package_descriptor(contract_path, project_root, output.parent)
    output.write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


def _public_boundary_problems(
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
) -> list[str]:
    contract = load_graduation_contract(contract_path)
    root = project_root.resolve()
    problems: list[str] = []
    for table_name in RESOURCE_ORDER:
        spec = contract["tables"][table_name]
        path = (root / spec["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            problems.append(f"{table_name}: public resource is missing or outside the project.")
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        identity_fields = set(spec.get("primary_key", []))
        if table_name == "observations":
            identity_fields.update({"report_id", "subject_id", "source_record_id"})
        for row_number, row in enumerate(rows, 2):
            for field in identity_fields:
                if not str(row.get(field, "")).startswith("SYN-"):
                    problems.append(f"{table_name} row {row_number}: {field} is not a SYN- identity.")
            for field in spec.get("allowed_values", {}):
                if field.endswith("status") and row.get(field) != "synthetic_fixture":
                    problems.append(f"{table_name} row {row_number}: {field} is not synthetic_fixture.")
            if table_name == "observations" and row.get("source_status") != "synthetic_fixture":
                problems.append(f"observations row {row_number}: source_status is not synthetic_fixture.")
    return problems


def _descriptor_boundary_problems(
    descriptor_path: Path,
    contract_path: Path,
    project_root: Path,
) -> list[str]:
    path = descriptor_path.resolve()
    if not path.is_file():
        return ["Data Package descriptor is missing."]
    try:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        expected = build_data_package_descriptor(contract_path, project_root, path.parent)
    except (OSError, ValueError, KeyError) as exc:
        return [f"Data Package descriptor cannot be inspected safely: {exc}"]
    if descriptor != expected:
        return ["Data Package descriptor differs from the local synthetic-only descriptor."]
    return []


def validate_public_data_package(
    descriptor_path: Path = DESCRIPTOR_PATH,
    contract_path: Path = CONTRACT_PATH,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Validate locally, never uploading data or replacing native validation."""
    native = validate_graduation_contract(contract_path, project_root)
    boundary_problems = _public_boundary_problems(contract_path, project_root)
    descriptor_problems = _descriptor_boundary_problems(descriptor_path, contract_path, project_root)
    availability = frictionless_availability()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "adapter_version": ADAPTER_VERSION,
        "required_by_core": False,
        "native_contract_status": native["status"],
        "public_boundary_status": "passed" if not boundary_problems else "failed",
        "public_boundary_problems": boundary_problems,
        "descriptor_boundary_status": "passed" if not descriptor_problems else "failed",
        "descriptor_boundary_problems": descriptor_problems,
        "frictionless": availability,
    }
    if native["status"] != "passed":
        return {**result, "status": "blocked_native_contract", "valid": False}
    if boundary_problems:
        return {**result, "status": "blocked_public_boundary", "valid": False}
    if descriptor_problems:
        return {**result, "status": "blocked_descriptor_boundary", "valid": False}
    if not availability["ready"]:
        status = "unavailable" if not availability["available"] else "version_mismatch"
        return {**result, "status": status, "valid": None}
    path = descriptor_path.resolve()
    started = time.perf_counter()
    try:
        from frictionless import Package  # type: ignore[import-not-found]

        report = Package(str(path)).validate()
        stats = dict(getattr(report, "stats", {}) or {})
        valid = bool(report.valid)
    except Exception as exc:  # Frictionless errors become bounded adapter results.
        return {
            **result,
            "status": "adapter_error",
            "valid": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        **result,
        "status": "passed" if valid else "failed",
        "valid": valid,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "stats": stats,
    }


def benchmark_public_data_package(iterations: int = 30) -> dict[str, Any]:
    """Compare the native gate with the optional end-to-end adapter locally."""
    if iterations < 3 or iterations > 200:
        raise ValueError("Benchmark iterations must be between 3 and 200.")
    availability = frictionless_availability()
    if not availability["ready"]:
        return {
            "status": "unavailable",
            "iterations": iterations,
            "frictionless": availability,
        }

    validate_graduation_contract()
    warm = validate_public_data_package()
    if warm["status"] != "passed":
        return {"status": "failed", "iterations": iterations, "report": warm}

    native_samples = []
    adapter_samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        native = validate_graduation_contract()
        native_samples.append((time.perf_counter() - started) * 1000)
        if native["status"] != "passed":
            return {"status": "failed", "iterations": iterations, "native": native}

        started = time.perf_counter()
        adapter = validate_public_data_package()
        adapter_samples.append((time.perf_counter() - started) * 1000)
        if adapter["status"] != "passed":
            return {"status": "failed", "iterations": iterations, "report": adapter}

    native_median = statistics.median(native_samples)
    adapter_median = statistics.median(adapter_samples)
    return {
        "status": "passed",
        "iterations": iterations,
        "frictionless_version": availability["version"],
        "native_median_ms": round(native_median, 3),
        "native_min_ms": round(min(native_samples), 3),
        "native_max_ms": round(max(native_samples), 3),
        "adapter_end_to_end_median_ms": round(adapter_median, 3),
        "adapter_end_to_end_min_ms": round(min(adapter_samples), 3),
        "adapter_end_to_end_max_ms": round(max(adapter_samples), 3),
        "median_overhead_ms": round(adapter_median - native_median, 3),
        "median_slowdown_ratio": round(adapter_median / native_median, 2),
    }


def validate_frictionless_evaluation(
    evaluation_path: Path = EVALUATION_PATH,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Validate the committed T14 evidence without requiring Frictionless."""
    try:
        record = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"schema_version": "1.0", "status": "failed", "problems": [str(exc)]}
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    if record.get("evaluation_id") != "SteelAI-Frictionless-Adapter-Evaluation-v1.0":
        add("Unexpected T14 evaluation_id.")
    if record.get("schema_version") != "1.0" or record.get("result") != "adopted_optional":
        add("T14 must record an adopted_optional v1.0 result.")
    component = record.get("component", {})
    if component.get("name") != "frictionless" or component.get("version") != EXPECTED_FRICTIONLESS_VERSION:
        add("T14 component must remain pinned to Frictionless 5.19.0.")
    if component.get("license_spdx") != "MIT":
        add("T14 component license must remain MIT.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(component.get("wheel_sha256", ""))):
        add("T14 wheel SHA-256 is missing or invalid.")
    runtime = record.get("runtime", {})
    if runtime.get("python") != "CPython 3.12.14" or runtime.get("os") != "Windows x64":
        add("T14 runtime evidence must match the isolated Windows CPython 3.12.14 run.")
    if runtime.get("network_used_by_adapter") is not False or runtime.get("real_data_used") is not False:
        add("T14 adapter evaluation must remain local and synthetic-only.")

    integration = record.get("integration", {})
    if integration.get("required_by_core") is not False or integration.get("main_requirements_modified") is not False:
        add("Frictionless must stay optional and outside main requirements.")
    if integration.get("synthetic_only") is not True:
        add("T14 adapter must remain synthetic-only.")
    root = project_root.resolve()
    lock_path = (root / str(integration.get("lock_file", ""))).resolve()
    license_path = (root / str(integration.get("license_record", ""))).resolve()
    descriptor_path = (root / str(integration.get("descriptor", ""))).resolve()
    if not all(path.is_relative_to(root) for path in (lock_path, license_path, descriptor_path)):
        add("T14 artifact path escapes the project root.")
    else:
        try:
            lock_lines = [
                line.strip() for line in lock_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            expected_count = record.get("dependency_cost", {}).get("installed_packages_total")
            if expected_count != 40 or len(lock_lines) != expected_count:
                add("Optional lock must contain exactly the 40 measured packages.")
            lock_pattern = re.compile(r"[A-Za-z0-9_.-]+==[^ ]+ --hash=sha256:[0-9a-f]{64}")
            if not all(lock_pattern.fullmatch(line) for line in lock_lines):
                add("Every optional dependency must have an exact version and wheel hash.")
            pinned = f"frictionless=={EXPECTED_FRICTIONLESS_VERSION} --hash=sha256:{component.get('wheel_sha256')}"
            if pinned not in lock_lines:
                add("Pinned Frictionless wheel is absent from the optional lock.")
        except OSError as exc:
            add(f"Cannot read optional lock: {exc}")
        try:
            license_text = license_path.read_text(encoding="utf-8")
            if "Open Knowledge Foundation" not in license_text or "Permission is hereby granted" not in license_text:
                add("Frictionless MIT license copy is incomplete.")
        except OSError as exc:
            add(f"Cannot read license record: {exc}")
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            expected_descriptor = build_data_package_descriptor(
                project_root=root, descriptor_dir=descriptor_path.parent,
            )
            if descriptor != expected_descriptor:
                add("Committed Data Package descriptor is stale or modified.")
        except (OSError, ValueError, KeyError) as exc:
            add(f"Cannot validate committed descriptor: {exc}")

    main_requirements = root / "requirements.txt"
    try:
        if "frictionless" in main_requirements.read_text(encoding="utf-8").lower():
            add("Frictionless must not enter requirements.txt.")
    except OSError as exc:
        add(f"Cannot read main requirements: {exc}")
    cost = record.get("dependency_cost", {})
    if cost.get("transitive_packages") != 39 or cost.get("direct_dependencies") != 19:
        add("T14 dependency counts do not match the isolated installation.")
    performance = record.get("performance", {})
    if performance.get("iterations") != 30:
        add("T14 performance record must contain the 30-iteration comparison.")
    if not all(isinstance(performance.get(key), (int, float)) and performance[key] > 0 for key in (
        "native_median_ms", "adapter_end_to_end_median_ms", "median_overhead_ms",
    )):
        add("T14 performance measurements are incomplete.")
    removal = record.get("removal", {})
    if removal.get("core_data_migration_required") is not False or removal.get("core_configuration_change_required") is not False:
        add("Removing the adapter must not require core migration or configuration changes.")
    return {
        "schema_version": "1.0",
        "evaluation_id": record.get("evaluation_id"),
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "component_version": component.get("version"),
        "required_by_core": integration.get("required_by_core"),
        "locked_package_count": record.get("dependency_cost", {}).get("installed_packages_total"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate the public graduation-v1 Data Package.")
    parser.add_argument("--output", type=Path, default=DESCRIPTOR_PATH)
    args = parser.parse_args()
    output = write_data_package_descriptor(args.output)
    report = validate_public_data_package(output)
    print(json.dumps({"descriptor": str(output), **report}, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"passed", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
