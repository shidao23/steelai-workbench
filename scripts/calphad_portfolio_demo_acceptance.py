"""T86 portfolio demo: fast end-to-end acceptance for the public synthetic Fe-C demonstration.

    .\\.venv\\Scripts\\python.exe -X utf8 scripts\\calphad_portfolio_demo_acceptance.py \
        --json outputs\\calphad_portfolio_demo_acceptance.json

Checks (deliberately fast — it never runs the 324-point heavy acceptance):

1. the demo preview passes every gate;
2. the demo runs end to end twice through the formal independent single-point mode;
3. the two runs agree within 1e-7;
4. the curve, the chart frame and all three download formats (Markdown, JSON, CSV) carry the
   required demo flags and provenance;
5. the main application still works when the isolated pycalphad environment is unavailable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steelai import calphad_adapter as adapter  # noqa: E402

DEMO_TOLERANCE = 1e-7
REQUIRED_RECORD_KEYS = (
    "portfolio_demo",
    "public_synthetic_input",
    "not_for_scientific_conclusion",
    "result_type",
    "is_complete_phase_diagram",
    "writes_back_formal_experimental_data",
    "pycalphad_version",
    "database",
    "components",
    "phases",
    "temperature",
    "pressure_Pa",
    "solver_mode",
    "component_profile",
    "phase_profile",
)
REQUIRED_MARKDOWN_TOKENS = (
    "portfolio_demo=true",
    "public_synthetic_input=true",
    "not_for_scientific_conclusion=true",
    "model_prediction_not_experimental_measurement",
    "不得用于论文结论、真实钢种分析或生产决策",
    "独立点清单摘要",
    "不是完整相图",
)
REQUIRED_CSV_TOKENS = (
    "# portfolio_demo: true",
    "# public_synthetic_input: true",
    "# not_for_scientific_conclusion: true",
    "# model_prediction_not_experimental_measurement: true",
    "# solver_mode: independent_single_point_process_v1",
    "# database_sha256:",
    "# pycalphad_version: 0.11.2",
    "# is_complete_phase_diagram: false",
    "# writes_back_formal_experimental_data: false",
)


def curve_difference(left: dict[str, Any], right: dict[str, Any]) -> float:
    if len(left.get("points", [])) != len(right.get("points", [])):
        return float("inf")
    worst = 0.0
    for first, second in zip(left["points"], right["points"]):
        if abs(first["temperature_C"] - second["temperature_C"]) > 1e-9:
            return float("inf")
        names = set(first["phase_fractions_mole"]) | set(second["phase_fractions_mole"])
        for name in names:
            worst = max(worst, abs(first["phase_fractions_mole"].get(name, 0.0)
                                   - second["phase_fractions_mole"].get(name, 0.0)))
    return worst


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="T86 portfolio demo acceptance.")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv[1:])

    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "acceptance_id": "SteelAI-T86-Portfolio-Demo-Acceptance-v1.0",
        "task": "T86 portfolio demo",
        "demo_id": adapter.PORTFOLIO_DEMO_ID,
        "solver_mode": adapter.INDEPENDENT_SOLVER_MODE,
        "tolerance": DEMO_TOLERANCE,
        "checks": {},
    }

    policy_report = adapter.validate_portfolio_demo_policy()
    report["checks"]["demo_policy_valid"] = {
        "status": "ok" if policy_report["status"] == "passed" else "failed",
        "problems": policy_report.get("problems", []),
        "phases": policy_report.get("phases"),
        "composition": policy_report.get("composition"),
        "temperature": policy_report.get("temperature"),
    }

    preview = adapter.preview_portfolio_demo()
    report["checks"]["preview_ready"] = {
        "status": "ok" if preview.state == "ready" else "failed",
        "state": preview.state,
        "gate_codes": [gate.code for gate in preview.gates],
        "messages": [gate.message for gate in preview.gates],
    }
    if preview.state != "ready":
        report["overall_status"] = "failed"
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                             encoding="utf-8")
        print("demo preview blocked:", report["checks"]["preview_ready"]["gate_codes"])
        return 1

    request = preview.request
    report["demo_request"] = {
        "sample_id": request.get("sample_id"),
        "components": request.get("components"),
        "phases": request.get("phases"),
        "component_mole_fractions": request.get("component_mole_fractions"),
        "temperature_points": len(request["temperature"]["values_C"]),
        "temperature_range_C": [request["temperature"]["min_C"], request["temperature"]["max_C"]],
        "step_C": request["temperature"]["step_C"],
        "pressure_Pa": request.get("pressure_Pa"),
        "solver_mode": request.get("solver_mode"),
        "database_id": (request.get("database") or {}).get("database_id"),
        "database_sha256": (request.get("database") or {}).get("sha256"),
    }

    runs: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        run_started = time.perf_counter()
        record = adapter.run_phase_fraction_curve(
            preview, timeout_seconds=args.timeout,
            scratch_root=ROOT / "outputs" / "_t86_demo_runs",
        )
        elapsed = time.perf_counter() - run_started
        runs.append(record)
        print(f"demo run {index}/{args.runs}: status={record.get('status')} "
              f"points={len(record.get('points', []) or [])} "
              f"first_attempt_success={record.get('point_count_first_attempt_success')}"
              f"/{record.get('point_count_expected')} elapsed={elapsed:.1f}s", flush=True)

    all_computed = all(record.get("status") == "computed" for record in runs)
    report["checks"]["runs_computed"] = {
        "status": "ok" if all_computed else "failed",
        "runs": [
            {
                "status": record.get("status"),
                "points": len(record.get("points", []) or []),
                "first_attempt_success": record.get("point_count_first_attempt_success"),
                "first_attempt_expected": record.get("point_count_expected"),
                "failed_temperatures_C": [
                    entry["temperature_C"] for entry in (record.get("failed_points") or [])
                ],
                "manifest_digest": record.get("manifest_digest"),
            }
            for record in runs
        ],
    }
    if not all_computed:
        report["overall_status"] = "failed"
        report["elapsed_s"] = round(time.perf_counter() - started, 1)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                             encoding="utf-8")
        return 1

    worst = 0.0
    for left in range(len(runs)):
        for right in range(left + 1, len(runs)):
            worst = max(worst, curve_difference(runs[left], runs[right]))
    report["repeat"] = {
        "runs": len(runs),
        "max_abs_difference": worst,
        "tolerance": DEMO_TOLERANCE,
        "status": "ok" if worst <= DEMO_TOLERANCE else "failed",
    }
    report["checks"]["repeatable_within_tolerance"] = report["repeat"]

    record = runs[0]
    missing_keys = [key for key in REQUIRED_RECORD_KEYS if key not in record]
    flags_ok = (
        record.get("portfolio_demo") is True
        and record.get("public_synthetic_input") is True
        and record.get("not_for_scientific_conclusion") is True
        and record.get("result_type") == adapter.RESULT_TYPE
        and record.get("is_complete_phase_diagram") is False
        and record.get("writes_back_formal_experimental_data") is False
        and record.get("solver_mode") == adapter.INDEPENDENT_SOLVER_MODE
    )
    report["checks"]["record_contract"] = {
        "status": "ok" if not missing_keys and flags_ok else "failed",
        "missing_keys": missing_keys,
        "flags_ok": flags_ok,
        "result_type": record.get("result_type"),
        "review_status": record.get("review_status"),
        "pycalphad_version": record.get("pycalphad_version"),
        "database_id": (record.get("database") or {}).get("database_id"),
        "database_sha256": (record.get("database") or {}).get("sha256"),
        "components": record.get("components"),
        "phases": record.get("phases"),
        "pressure_Pa": record.get("pressure_Pa"),
        "solver_mode": record.get("solver_mode"),
    }

    markdown = adapter.phase_fraction_curve_markdown(record)
    csv_text = adapter.phase_fraction_csv(record)
    json_text = json.dumps(record, ensure_ascii=False, indent=2)
    rows = adapter.phase_fraction_rows(record)
    csv_rows = [line for line in csv_text.splitlines() if line and not line.startswith("#")]
    phase_columns = [name for name in rows[0] if str(name).endswith("（相摩尔分数）")] if rows else []
    report["checks"]["downloads"] = {
        "status": "ok" if (
            not [token for token in REQUIRED_MARKDOWN_TOKENS if token not in markdown]
            and not [token for token in REQUIRED_CSV_TOKENS if token not in csv_text]
            and len(rows) == len(record["points"])
            and len(csv_rows) == len(record["points"]) + 1
            and phase_columns
            and '"portfolio_demo": true' in json_text
        ) else "failed",
        "markdown_bytes": len(markdown.encode("utf-8")),
        "json_bytes": len(json_text.encode("utf-8")),
        "csv_bytes": len(csv_text.encode("utf-8")),
        "missing_markdown_tokens": [t for t in REQUIRED_MARKDOWN_TOKENS if t not in markdown],
        "missing_csv_tokens": [t for t in REQUIRED_CSV_TOKENS if t not in csv_text],
        "chart_phase_columns": phase_columns,
        "chart_rows": len(rows),
        "csv_data_rows": len(csv_rows) - 1,
    }

    # The main application must keep working when the optional CALPHAD feature is switched off.
    previous = os.environ.get(adapter.FEATURE_ENV)
    os.environ[adapter.FEATURE_ENV] = "0"
    try:
        status_without = adapter.calphad_feature_status()
    finally:
        if previous is None:
            os.environ.pop(adapter.FEATURE_ENV, None)
        else:
            os.environ[adapter.FEATURE_ENV] = previous
    from steelai.physics import calculate_all

    physics_composition = {"C": 0.19, "Mn": 0.9, "Si": 0.25, "Cr": 0.2, "Ni": 0.021,
                           "Mo": 0.151, "V": 0.07, "Nb": 0.03, "Ti": 0.00966,
                           "Al": 0.003, "Cu": 0.0145, "P": 0.012, "S": 0.005}
    physics = calculate_all(physics_composition, set(physics_composition))
    report["checks"]["main_app_without_pycalphad"] = {
        "status": "ok" if status_without.get("state") == "disabled" and physics_ok(physics) else "failed",
        "feature_state_when_disabled": status_without.get("state"),
        "physics_result_count": len(physics) if isinstance(physics, list) else 0,
        "physics_ok": physics_ok(physics),
        "adapter_imports_pycalphad_at_module_level": "import pycalphad" in (
            ROOT / "steelai" / "calphad_adapter.py").read_text(encoding="utf-8"),
    }

    blocking = [name for name, item in report["checks"].items() if item.get("status") != "ok"]
    report["blocking"] = blocking
    report["overall_status"] = "portfolio_exploration_complete" if not blocking else "failed"
    report["elapsed_s"] = round(time.perf_counter() - started, 1)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                         encoding="utf-8")
    print()
    for name, item in report["checks"].items():
        print(f"  {name}: {item.get('status')}")
    print(f"max abs difference between runs: {worst}")
    print(f"overall: {report['overall_status']}  elapsed={report['elapsed_s']}s")
    print(f"json: {args.json}")
    return 0 if not blocking else 1


def physics_ok(results: Any) -> bool:
    """The deterministic physics path must still produce values without the optional adapter."""
    if not isinstance(results, list) or not results:
        return False
    for item in results:
        value = getattr(item, "value", None)
        if isinstance(value, (int, float)) and value == value:
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
