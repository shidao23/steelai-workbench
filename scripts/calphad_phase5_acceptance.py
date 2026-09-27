"""T86 phase 5 acceptance: the formal independent-single-point-process acceptance run.

Heavy acceptance is executed here, not in the unit tests:

    .\\.venv\\Scripts\\python.exe -X utf8 scripts\\calphad_phase5_acceptance.py \
        --reviewer-id "<named approver>" --approved-at YYYY-MM-DD --approval-reason "<reason>" \
        --json outputs\\calphad_phase5_acceptance.json

It runs the full 54-point scan for B-DQ and R-DQ three times each (324 independent points), strictly
serial, one fresh worker process per point, and then compares the old batch warm-start mode with the
independent mode on R-DQ.  Acceptance only passes if every one of the 324 points succeeds on its
first independent process call, no point aborts natively, times out or fails to converge, the three
runs agree within 1e-7, both heats use the identical profile/phase set/grid/mode, the physical
plausibility guards pass, the export limitation check passes and the two solver modes agree within
1e-7 on commonly converged points.

A diagnostic retry is recorded for failed points but never changes the formal result.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steelai import calphad_adapter as adapter  # noqa: E402

COMPOSITION_CSV = ROOT / "data" / "processed" / "composition.csv"
DEFAULT_INTERPRETER = ROOT / ".venv-pycalphad" / "Scripts" / "python.exe"
ELEMENT_COLUMNS = ["C", "Mn", "Si", "Cr", "Ni", "Mo", "Cu", "Al", "Nb", "Ti", "V"]
EXTRA_COLUMNS = ["As", "Sn", "Sb", "O", "W"]
REPEAT_TOLERANCE = 1e-7
REQUIRED_MARKDOWN_TOKENS = (
    adapter.RESULT_LABEL_MATRIX,
    "steel_matrix_equilibrium_v1",
    "steel_matrix_major_carbides_v1",
    "independent_single_point_process_v1",
    "缩减成分体系",
    "受控元素排除",
    "pending_human_review",
)
REQUIRED_CSV_TOKENS = (
    adapter.RESULT_LABEL_MATRIX,
    "# component_profile: steel_matrix_equilibrium_v1 v1.0",
    "# phase_profile: steel_matrix_major_carbides_v1 v1.0",
    "# solver_mode: independent_single_point_process_v1",
    "# reduced_component_system: true",
    "# excluded_elements_and_reasons:",
    "# model_losses:",
    "# review_status: pending_human_review",
    "# writes_back_formal_experimental_data: false",
)


def load_compositions() -> dict[str, dict[str, float | None]]:
    rows: dict[str, dict[str, float | None]] = {}
    with COMPOSITION_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            composition: dict[str, float | None] = {}
            for key in ELEMENT_COLUMNS + EXTRA_COLUMNS:
                value = row.get(key)
                composition[key] = None if value in ("", None) else float(value)
            rows[row["sample_id"]] = composition
    return rows


def plausibility(record: dict[str, Any]) -> dict[str, Any]:
    """Basic physical sanity: catches the class of error a phase-fraction sum cannot see."""
    problems: list[str] = []
    points = record.get("points", []) or []
    cold_liquid = [point for point in points
                   if point["temperature_C"] <= 1000
                   and point["phase_fractions_mole"].get("LIQUID", 0.0) > 1e-3]
    hot_liquid = [point for point in points
                  if point["temperature_C"] >= 1500
                  and point["phase_fractions_mole"].get("LIQUID", 0.0) > 0]
    if cold_liquid:
        problems.append("液相在 1000 °C 以下出现：" +
                        "、".join(f"{p['temperature_C']:.0f}°C={p['phase_fractions_mole']['LIQUID']:.4f}"
                                  for p in cold_liquid[:5]))
    if not hot_liquid:
        problems.append("1500 °C 以上没有出现液相")
    cold_matrix = [point for point in points if point["temperature_C"] <= 700]
    missing_matrix = [point for point in cold_matrix
                      if (point["phase_fractions_mole"].get("BCC_A2", 0.0)
                          + point["phase_fractions_mole"].get("FCC_A1", 0.0)) <= 1e-3]
    if missing_matrix:
        problems.append("700 °C 以下缺少 BCC_A2/FCC_A1 基体相")
    manifest = record.get("point_manifest", []) or []
    return {
        "status": "ok" if not problems else "failed",
        "problems": problems,
        "vacancy_included": bool(manifest) and all(entry.get("va_present") for entry in manifest),
        "cold_liquid_points": len(cold_liquid),
        "hot_liquid_points": len(hot_liquid),
    }


def scan_summary(record: dict[str, Any], elapsed: float) -> dict[str, Any]:
    manifest = record.get("point_manifest", []) or []
    first_success = sum(1 for entry in manifest if entry.get("first_attempt_success"))
    failures = [entry for entry in manifest if not entry.get("first_attempt_success")]
    diagnostic_recovered = [
        entry for entry in failures
        if any(attempt.get("diagnostic_only") and attempt.get("solve_status") == "ok"
               for attempt in entry.get("attempts", []))
    ]
    points = record.get("points", []) or []
    return {
        "status": record.get("status"),
        "solver_mode": record.get("solver_mode"),
        "point_count": len(manifest),
        "first_attempt_success": first_success,
        "first_attempt_failure": len(failures),
        "diagnostic_recovered_but_still_formally_failed": len(diagnostic_recovered),
        "failed_points": [
            {"temperature_C": entry["temperature_C"],
             "failure_category": entry.get("attempts", [{}])[0].get("failure_category"),
             "problems": entry.get("attempts", [{}])[0].get("problems"),
             "diagnostic_retry_succeeded": entry.get("diagnostic_retry_succeeded")}
            for entry in failures
        ],
        "computed_points": len(points),
        "sum_min": round(min((point["total_moles"] for point in points), default=0.0), 10),
        "sum_max": round(max((point["total_moles"] for point in points), default=0.0), 10),
        "elapsed_s": round(elapsed, 1),
        "error": record.get("error"),
        "plausibility": plausibility(record) if points else None,
    }


def cross_run(sample: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [record for record in records if record.get("status") == "computed"]
    if len(usable) != len(records):
        return {"status": "failed", "reason": f"{sample}: 不是每轮都产出完整曲线"}
    lengths = {len(record["points"]) for record in usable}
    if len(lengths) != 1:
        return {"status": "failed", "reason": f"{sample}: 各轮温度点数不一致 {sorted(lengths)}"}
    assemblages = [tuple(sorted(point["phases_present"])) for point in usable[0]["points"]]
    assemblage_consistent = all(
        [tuple(sorted(point["phases_present"])) for point in record["points"]] == list(assemblages)
        for record in usable
    )
    max_diff = 0.0
    for index in range(len(usable[0]["points"])):
        for left in range(len(usable)):
            for right in range(left + 1, len(usable)):
                names = set(usable[left]["points"][index]["phase_fractions_mole"]) | \
                    set(usable[right]["points"][index]["phase_fractions_mole"])
                for name in names:
                    difference = abs(
                        usable[left]["points"][index]["phase_fractions_mole"].get(name, 0.0)
                        - usable[right]["points"][index]["phase_fractions_mole"].get(name, 0.0)
                    )
                    max_diff = max(max_diff, difference)
    return {
        "status": "ok" if assemblage_consistent and max_diff <= REPEAT_TOLERANCE else "failed",
        "runs": len(usable),
        "points_per_run": len(usable[0]["points"]),
        "assemblage_consistent": assemblage_consistent,
        "max_abs_difference": max_diff,
        "tolerance": REPEAT_TOLERANCE,
    }


def compare_modes(sample: str, independent: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    if independent.get("status") != "computed":
        return {"status": "failed", "reason": f"{sample}: 独立点模式未产出完整曲线"}
    if batch.get("status") != "computed":
        return {"status": "failed", "reason": f"{sample}: 批量模式未产出完整曲线",
                "batch_error": batch.get("error")}
    batch_points = {round(point["temperature_C"], 6): point for point in batch["points"]}
    max_diff = 0.0
    compared = 0
    differences: list[dict[str, Any]] = []
    for point in independent["points"]:
        key = round(point["temperature_C"], 6)
        if key not in batch_points:
            continue
        compared += 1
        names = set(point["phase_fractions_mole"]) | set(batch_points[key]["phase_fractions_mole"])
        point_diff = 0.0
        for name in names:
            point_diff = max(point_diff, abs(
                point["phase_fractions_mole"].get(name, 0.0)
                - batch_points[key]["phase_fractions_mole"].get(name, 0.0)))
        max_diff = max(max_diff, point_diff)
        if point_diff > REPEAT_TOLERANCE:
            differences.append({"temperature_C": key, "max_abs_difference": point_diff,
                                "independent": point["phase_fractions_mole"],
                                "batch": batch_points[key]["phase_fractions_mole"]})
    return {
        "status": "ok" if compared and max_diff <= REPEAT_TOLERANCE else "failed",
        "compared_points": compared,
        "max_abs_difference": max_diff,
        "tolerance": REPEAT_TOLERANCE,
        "differences_over_tolerance": differences[:10],
        "unexplained_difference": bool(max_diff > REPEAT_TOLERANCE),
    }


def export_check(record: dict[str, Any]) -> dict[str, Any]:
    markdown = adapter.phase_fraction_curve_markdown(record)
    csv_text = adapter.phase_fraction_csv(record)
    missing_markdown = [token for token in REQUIRED_MARKDOWN_TOKENS if token not in markdown]
    missing_csv = [token for token in REQUIRED_CSV_TOKENS if token not in csv_text]
    required_keys = [key for key in (
        "result_label", "component_profile", "phase_profile", "solver_mode",
        "reduced_component_system", "included_elements", "excluded_elements_with_reasons",
        "not_computed_in_this_phase", "model_losses", "component_versions_and_hashes",
        "reduced_system_approval", "review_status", "writes_back_formal_experimental_data",
        "point_manifest", "manifest_digest",
    ) if key not in record]
    data_rows = [line for line in csv_text.splitlines() if line and not line.startswith("#")]
    rows_carry = bool(data_rows) and all(
        adapter.RESULT_LABEL_MATRIX in row and "independent_single_point_process_v1" in row
        for row in data_rows[1:]
    )
    return {
        "status": "ok" if not missing_markdown and not missing_csv and not required_keys and rows_carry
        else "failed",
        "missing_markdown_tokens": missing_markdown,
        "missing_csv_tokens": missing_csv,
        "missing_record_keys": required_keys,
        "csv_rows_carry_profile_and_mode": rows_carry,
    }


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="T86 phase-5 acceptance run.")
    parser.add_argument("--reviewer-id", default="")
    parser.add_argument("--approved-at", default="")
    parser.add_argument("--approval-reason", default="")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--samples", default="B-DQ,R-DQ")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--temperature-min-C", type=float, default=400.0)
    parser.add_argument("--temperature-max-C", type=float, default=1725.0)
    parser.add_argument("--step-C", type=float, default=25.0)
    parser.add_argument("--interpreter", type=Path, default=DEFAULT_INTERPRETER)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--skip-mode-comparison", action="store_true")
    args = parser.parse_args(argv[1:])

    if not (args.reviewer_id.strip() and args.approved_at.strip() and args.approval_reason.strip()):
        print("必须显式提供 --reviewer-id / --approved-at / --approval-reason（代码不代填姓名）。")
        return 2

    started = time.perf_counter()
    samples = [name.strip() for name in args.samples.split(",") if name.strip()]
    compositions = load_compositions()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "acceptance_id": "SteelAI-T86-Phase5-Acceptance-v1.0",
        "task": "T86 phase 5",
        "solver_mode": adapter.INDEPENDENT_SOLVER_MODE,
        "diagnostic_batch_mode": adapter.BATCH_SOLVER_MODE,
        "temperature_grid_C": {
            "min": args.temperature_min_C, "max": args.temperature_max_C, "step": args.step_C,
        },
        "runs_per_sample": args.runs,
        "samples": samples,
        "reviewer_id": args.reviewer_id.strip(),
        "approved_at": args.approved_at.strip(),
        "approval_reason": args.approval_reason.strip(),
        "runs": {},
    }

    previews: dict[str, Any] = {}
    all_records: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        preview = adapter.preview_phase_fraction_curve(
            compositions[sample], sample_id=sample,
            temperature_min_C=args.temperature_min_C,
            temperature_max_C=args.temperature_max_C, step_C=args.step_C,
            fe_balance_confirmed_by=args.reviewer_id,
            controlled_exclusions_confirmed_by=args.reviewer_id,
            reduced_system_reviewer_id=args.reviewer_id,
            reduced_system_approved_at=args.approved_at,
            reduced_system_approval_reason=args.approval_reason,
            reduced_system_acknowledged=True,
        )
        previews[sample] = preview
        if preview.state != "ready":
            report["runs"][sample] = {"status": "failed",
                                      "gate_codes": [gate.code for gate in preview.gates]}
            all_records[sample] = []
            continue
        records: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        for run_index in range(1, args.runs + 1):
            run_started = time.perf_counter()
            record = adapter.run_phase_fraction_curve(
                preview, interpreter=str(args.interpreter), timeout_seconds=args.timeout,
            )
            elapsed = time.perf_counter() - run_started
            records.append(record)
            summary = scan_summary(record, elapsed)
            summaries.append(summary)
            print(f"{sample} run {run_index}/{args.runs}: status={summary['status']} "
                  f"first_attempt_success={summary['first_attempt_success']}/{summary['point_count']} "
                  f"failed={summary['first_attempt_failure']} elapsed={summary['elapsed_s']}s", flush=True)
            if summary["failed_points"]:
                print("    failed: " + json.dumps(summary["failed_points"], ensure_ascii=False)[:400],
                      flush=True)
        all_records[sample] = records
        report["runs"][sample] = {
            "status": "ok" if all(summary["status"] == "computed" for summary in summaries) else "failed",
            "runs": summaries,
            "cross_run": cross_run(sample, records),
        }

    total_points = sum(
        summary["point_count"]
        for sample in samples for summary in report["runs"].get(sample, {}).get("runs", [])
    )
    total_first_success = sum(
        summary["first_attempt_success"]
        for sample in samples for summary in report["runs"].get(sample, {}).get("runs", [])
    )
    report["totals"] = {
        "independent_points_attempted": total_points,
        "first_attempt_success": total_first_success,
        "first_attempt_failure": total_points - total_first_success,
        "first_attempt_success_rate": (round(total_first_success / total_points, 6)
                                       if total_points else None),
        "native_abort_points": sum(
            1 for sample in samples
            for summary in report["runs"].get(sample, {}).get("runs", [])
            for failure in summary["failed_points"]
            if failure.get("problems") and "ACCESS_VIOLATION" in str(failure.get("problems"))
        ),
        "total_wall_clock_s": None,
    }

    parity: dict[str, bool] = {}
    fingerprints: dict[str, Any] = {}
    if all(sample in previews and previews[sample].request for sample in samples):
        # Parity is a property of the requests, not of the run outcome, so it is evaluated even when
        # one heat cannot produce a complete curve.
        for sample in samples:
            request = previews[sample].request or {}
            fingerprints[sample] = {
                "components": list(request.get("components", [])),
                "phases": list(request.get("phases", [])),
                "temperature_values_C": list((request.get("temperature") or {}).get("values_C", [])),
                "component_profile": (request.get("component_profile") or {}).get("profile_id"),
                "phase_profile": (request.get("phase_profile") or {}).get("profile_id"),
                "solver_mode": request.get("solver_mode"),
            }
        parity = {
            "same_components": len({tuple(item["components"]) for item in fingerprints.values()}) == 1,
            "same_component_count": all(len(item["components"]) == 12 for item in fingerprints.values()),
            "same_phases": len({tuple(item["phases"]) for item in fingerprints.values()}) == 1,
            "same_temperature_grid": len({tuple(item["temperature_values_C"])
                                          for item in fingerprints.values()}) == 1,
            "same_profiles": len({(item["component_profile"], item["phase_profile"])
                                  for item in fingerprints.values()}) == 1,
            "same_solver_mode": len({item["solver_mode"] for item in fingerprints.values()}) == 1,
        }
    report["b_and_r_parity"] = {"status": "ok" if parity and all(parity.values()) else "failed",
                                "checks": parity,
                                "request_fingerprints": fingerprints}

    guards: dict[str, Any] = {}
    for sample in samples:
        records = [record for record in all_records.get(sample, []) if record.get("status") == "computed"]
        guards[sample] = plausibility(records[0]) if records else {"status": "failed",
                                                                   "problems": ["没有完整曲线"]}
    report["plausibility_guards"] = {
        "status": "ok" if all(item["status"] == "ok" for item in guards.values()) else "failed",
        "per_sample": guards,
    }

    exports: dict[str, Any] = {}
    for sample in samples:
        records = [record for record in all_records.get(sample, []) if record.get("status") == "computed"]
        exports[sample] = export_check(records[0]) if records else {"status": "failed"}
    report["export_checks"] = {
        "status": "ok" if all(item["status"] == "ok" for item in exports.values()) else "failed",
        "per_sample": exports,
    }

    if args.skip_mode_comparison:
        report["batch_vs_independent"] = {"status": "skipped"}
    else:
        sample = "R-DQ" if "R-DQ" in samples else samples[0]
        preview = previews.get(sample)
        if preview is None or preview.state != "ready":
            report["batch_vs_independent"] = {"status": "failed", "reason": "预览未就绪"}
        else:
            batch = adapter.run_phase_fraction_curve(
                preview, interpreter=str(args.interpreter), timeout_seconds=args.timeout,
                solver_mode=adapter.BATCH_SOLVER_MODE,
            )
            independent = all_records.get(sample, [{}])[0] if all_records.get(sample) else {}
            report["batch_vs_independent"] = compare_modes(sample, independent, batch)
            if batch.get("status") != "computed":
                report["batch_vs_independent"]["batch_error"] = batch.get("error")
            print(f"batch-vs-independent ({sample}): "
                  f"{json.dumps(report['batch_vs_independent'], ensure_ascii=False)[:300]}", flush=True)

    blocking: list[str] = []
    if report["totals"]["first_attempt_failure"]:
        blocking.append(f"{report['totals']['first_attempt_failure']} 个独立点首次调用未成功")
    for sample in samples:
        run_block = report["runs"].get(sample, {})
        if run_block.get("status") != "ok":
            blocking.append(f"{sample}: 有轮次未产出完整曲线")
        cross = run_block.get("cross_run", {})
        if cross.get("status") != "ok":
            blocking.append(f"{sample}: 三轮一致性未通过（{cross.get('reason') or cross.get('max_abs_difference')}）")
    if report["b_and_r_parity"]["status"] != "ok":
        blocking.append("B/R 使用的体系不一致")
    if report["plausibility_guards"]["status"] != "ok":
        blocking.append("物理合理性守卫未通过")
    if report["export_checks"]["status"] != "ok":
        blocking.append("导出限制声明验证未通过")
    mode = report.get("batch_vs_independent", {})
    if mode.get("status") not in ("ok", "skipped"):
        blocking.append("批量模式与独立点模式存在超过 1e-7 的差异或无法比较")

    report["blocking"] = blocking
    report["overall_status"] = ("pilot_ready_pending_scientific_review" if not blocking
                                else "blocked")
    report["not_claimed"] = ["validated", "production_ready"]
    report["total_elapsed_s"] = round(time.perf_counter() - started, 1)
    report["totals"]["total_wall_clock_s"] = report["total_elapsed_s"]
    report["result_label"] = adapter.RESULT_LABEL_MATRIX

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                         encoding="utf-8")
    print()
    print(f"independent points: {total_points}, first-attempt success: {total_first_success}")
    print(f"overall: {report['overall_status']}")
    for item in blocking:
        print(f"  blocking: {item}")
    print(f"total elapsed: {report['total_elapsed_s']}s")
    print(f"json: {args.json}")
    return 0 if not blocking else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
