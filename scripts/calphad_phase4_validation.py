"""T86 phase 4: the ten-step validation of the fixed reduced component system and phase range.

Runs in the MAIN Workbench interpreter, because it drives the real adapter and the isolated worker
exactly the way the Physics page does:

    .\\.venv\\Scripts\\python.exe -X utf8 scripts\\calphad_phase4_validation.py \
        --reviewer-id "<named approver recorded in the work order>" \
        --approved-at 2026-09-25 \
        --approval-reason "<reason>" \
        --json outputs\\calphad_phase4_validation.json

Steps 1-5 are the isolated-interpreter building blocks (12 components with a single phase, with the
fixed phase set, a temperature scan, per-point phase-fraction sums, and a repeated run).  They come
from ``scripts/calphad_phase_profile_probe.py``, run once for this report.

Steps 6-10 drive the real product path for B-DQ and R-DQ and check that both heats use exactly the
same components and phase set, that the excluded elements never reach the worker, and that the page
and every export carry the full limitation.

The reviewer identity is NEVER defaulted in code: without ``--reviewer-id`` the run must block with
CALPHAD-COMP-011, which the script verifies as step 0.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steelai import calphad_adapter as adapter  # noqa: E402

COMPOSITION_CSV = ROOT / "data" / "processed" / "composition.csv"
PROBE = ROOT / "scripts" / "calphad_phase_profile_probe.py"
DEFAULT_INTERPRETER = ROOT / ".venv-pycalphad" / "Scripts" / "python.exe"
SAMPLES = ("B-DQ", "R-DQ")
#: Two independent runs of the same request must agree to this absolute phase-fraction difference.
#: A numerical solver is not bitwise reproducible; observed run-to-run drift is ~1e-10.
REPEAT_TOLERANCE = 1e-6
#: Every restriction that must appear in the record, the Markdown and the CSV.
REQUIRED_MARKDOWN_TOKENS = (
    adapter.RESULT_LABEL_MATRIX,
    "steel_matrix_equilibrium_v1",
    "steel_matrix_major_carbides_v1",
    "缩减成分体系",
    "具名批准（真实样品运行前置条件）",
    "本阶段明确不计算的内容（禁止据此推断）",
    "受控元素排除",
    "禁止使用的名称",
    "已知模型损失",
    "pending_human_review",
)
REQUIRED_CSV_TOKENS = (
    adapter.RESULT_LABEL_MATRIX,
    "# component_profile: steel_matrix_equilibrium_v1 v1.0",
    "# phase_profile: steel_matrix_major_carbides_v1 v1.0",
    "# reduced_component_system: true",
    "# included_elements:",
    "# excluded_elements_and_reasons:",
    "# not_computed_in_this_phase:",
    "# model_losses:",
    "# reviewer_id:",
    "# approved_at:",
    "# database_sha256:",
    "# pycalphad_version:",
    "# review_status: pending_human_review",
    "# writes_back_formal_experimental_data: false",
)


def plausibility(record: dict[str, Any]) -> dict[str, Any]:
    """Basic physical sanity of a reduced-system curve.

    This is deliberately not a materials-science judgement: it only catches assemblages that are
    impossible for a solid low-alloy steel, which is exactly the class of error that a
    phase-fraction-sum check cannot see (a wrong component list can still sum to 1).
    """
    problems: list[str] = []
    points = record.get("points", []) or []
    hot_liquid = [point for point in points
                  if point["temperature_C"] >= 1500 and
                  point["phase_fractions_mole"].get("LIQUID", 0.0) > 0]
    cold_liquid = [point for point in points
                   if point["temperature_C"] <= 1000 and
                   point["phase_fractions_mole"].get("LIQUID", 0.0) > 1e-3]
    if cold_liquid:
        problems.append(
            "液相在 1000 °C 以下出现：" +
            "、".join(f"{point['temperature_C']:.0f}°C={point['phase_fractions_mole']['LIQUID']:.4f}"
                      for point in cold_liquid[:5])
        )
    if not hot_liquid:
        problems.append("1500 °C 以上没有出现液相，固相线以上的行为不合理")
    solid_matrix = [
        point for point in points
        if point["temperature_C"] <= 700 and
        (point["phase_fractions_mole"].get("BCC_A2", 0.0)
         + point["phase_fractions_mole"].get("FCC_A1", 0.0)) > 1e-3
    ]
    if len(solid_matrix) != len([point for point in points if point["temperature_C"] <= 700]):
        problems.append("700 °C 以下的温度点缺少 BCC_A2/FCC_A1 基体相")
    vacancy = record.get("pycalphad_components", []) or []
    return {
        "status": "ok" if not problems else "failed",
        "problems": problems,
        "cold_liquid_points": len(cold_liquid),
        "hot_liquid_points": len(hot_liquid),
        "pycalphad_components": vacancy,
        "vacancy_included": "VA" in {str(name).upper() for name in vacancy},
    }


def load_compositions() -> dict[str, dict[str, float | None]]:
    rows: dict[str, dict[str, float | None]] = {}
    with COMPOSITION_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            sample_id = row["sample_id"]
            composition: dict[str, float | None] = {}
            for key, value in row.items():
                if key in ("sample_id", "source_status"):
                    continue
                composition[key] = None if value in ("", None) else float(value)
            rows[sample_id] = composition
    return rows


def run_probe(interpreter: Path, json_path: Path, timeout: float) -> dict[str, Any]:
    completed = subprocess.run(
        [str(interpreter), "-X", "utf8", str(PROBE), "--json", str(json_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=timeout, check=False,
    )
    payload: dict[str, Any] | None = None
    if json_path.is_file():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
    return {"returncode": completed.returncode, "payload": payload,
            "stdout_tail": (completed.stdout or "").strip().splitlines()[-6:],
            "stderr_tail": (completed.stderr or "").strip().splitlines()[-6:]}


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="T86 phase-4 ten-step validation.")
    parser.add_argument("--reviewer-id", default="")
    parser.add_argument("--approved-at", default="")
    parser.add_argument("--approval-reason", default="")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--interpreter", type=Path, default=DEFAULT_INTERPRETER)
    parser.add_argument("--temperature-min-C", type=float, default=400.0)
    parser.add_argument("--temperature-max-C", type=float, default=1725.0)
    parser.add_argument("--step-C", type=float, default=25.0)
    parser.add_argument("--probe-timeout", type=float, default=1800.0)
    parser.add_argument("--worker-timeout", type=float, default=1800.0)
    parser.add_argument("--skip-probe", action="store_true")
    args = parser.parse_args(argv[1:])

    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "validation_id": "SteelAI-T86-Phase4-Reduced-System-Validation-v1.0",
        "task": "T86 phase 4",
        "component_profile": {"profile_id": adapter.COMPONENT_PROFILE_ID,
                              "version": adapter.COMPONENT_PROFILE_VERSION,
                              "elements": list(adapter.REQUIRED_MATRIX_ELEMENTS)},
        "phase_profile": {"profile_id": adapter.PHASE_PROFILE_ID,
                          "version": adapter.PHASE_PROFILE_VERSION,
                          "phases": list(adapter.REQUIRED_MATRIX_PHASES)},
        "steps": {},
    }

    # --- step 0: no named approval must block ------------------------------------------------
    compositions = load_compositions()
    missing = [sample for sample in SAMPLES if sample not in compositions]
    if missing:
        report["steps"]["step0_no_named_approval_blocks"] = {
            "status": "failed", "reason": f"composition table is missing {missing}"}
    else:
        unapproved = adapter.preview_phase_fraction_curve(
            compositions[SAMPLES[0]], sample_id=SAMPLES[0],
            temperature_min_C=args.temperature_min_C, temperature_max_C=args.temperature_max_C,
            step_C=args.step_C,
            fe_balance_confirmed_by="t86-phase4-validation",
            controlled_exclusions_confirmed_by="t86-phase4-validation",
        )
        codes = [gate.code for gate in unapproved.gates]
        report["steps"]["step0_no_named_approval_blocks"] = {
            "status": "ok" if "CALPHAD-COMP-011" in codes and unapproved.request is None else "failed",
            "state": unapproved.state,
            "gate_codes": codes,
            "reason": "without reviewer_id the run must stay blocked and produce no request",
        }

    # --- steps 1-5: isolated-interpreter building blocks --------------------------------------
    if args.skip_probe:
        report["steps"]["step1_to_step5"] = {"status": "skipped"}
        probe_payload: dict[str, Any] | None = None
    else:
        probe_json = args.json.parent / "calphad_phase_profile_probe.json"
        probe = run_probe(args.interpreter, probe_json, args.probe_timeout)
        probe_payload = probe["payload"]
        statuses = (probe_payload or {}).get("reduced_system_check_status", {})
        report["steps"]["step1_to_step5"] = {
            "status": "ok" if probe["returncode"] == 0 and probe_payload
            and probe_payload.get("verdict") == "verified" else "failed",
            "probe_returncode": probe["returncode"],
            "probe_json": str(probe_json),
            "probe_stderr_tail": probe["stderr_tail"],
            "verified_phases": (probe_payload or {}).get("verified_phases", []),
            "removed_phases": (probe_payload or {}).get("removed_phases", []),
            "step1_12_components_one_phase_single_point": statuses.get(
                "step1_12_components_one_phase_single_point"),
            "step2_12_components_fixed_phase_set_single_point": statuses.get(
                "step2_12_components_fixed_phase_set_single_point"),
            "step3_temperature_scan": statuses.get("step3_temperature_scan"),
            "step4_phase_fraction_sums": statuses.get("step4_phase_fraction_sums"),
            "step5_repeat_run_identical": statuses.get("step5_repeat_run_identical"),
        }
        if probe_payload:
            report["steps"]["step1_to_step5"]["phase_fraction_sums"] = (
                probe_payload.get("reduced_system_checks", {}).get("phase_fraction_sums"))
            report["steps"]["step1_to_step5"]["single_point_1173K"] = (
                probe_payload.get("reduced_system_checks", {}).get("single_point_1173K"))

    # --- steps 6-10: the real product path ----------------------------------------------------
    required = {
        "reviewer_id": args.reviewer_id.strip(),
        "approved_at": args.approved_at.strip(),
        "approval_reason": args.approval_reason.strip(),
    }
    if not all(required.values()):
        report["steps"]["step6_to_step10"] = {
            "status": "failed",
            "reason": "a named approval is required: pass --reviewer-id, --approved-at and "
                      "--approval-reason. The script never fills in a name by default.",
        }
    else:
        results: dict[str, Any] = {}
        previews: dict[str, Any] = {}
        records: dict[str, Any] = {}
        for sample_id in SAMPLES:
            preview = adapter.preview_phase_fraction_curve(
                compositions[sample_id], sample_id=sample_id,
                temperature_min_C=args.temperature_min_C,
                temperature_max_C=args.temperature_max_C,
                step_C=args.step_C,
                fe_balance_confirmed_by=args.reviewer_id,
                controlled_exclusions_confirmed_by=args.reviewer_id,
                reduced_system_reviewer_id=args.reviewer_id,
                reduced_system_approved_at=args.approved_at,
                reduced_system_approval_reason=args.approval_reason,
                reduced_system_acknowledged=True,
            )
            previews[sample_id] = preview
            entry: dict[str, Any] = {
                "preview_state": preview.state,
                "gate_codes": [gate.code for gate in preview.gates],
            }
            if preview.state != "ready" or preview.request is None:
                entry["status"] = "failed"
                results[sample_id] = entry
                continue
            request = preview.request
            entry["components"] = list(request["components"])
            entry["phases"] = list(request["phases"])
            entry["included_elements"] = list(
                request["component_profile"]["included_elements"])
            entry["excluded_elements"] = sorted(
                item["element"] for item in request["controlled_exclusions"])
            entry["approval"] = dict(request["reduced_system_approval"])
            entry["result_label"] = request["result_label"]

            record = adapter.run_phase_fraction_curve(
                preview,
                interpreter=str(args.interpreter),
                timeout_seconds=args.worker_timeout,
            )
            records[sample_id] = record
            entry["record_status"] = record.get("status")
            entry["record_state"] = record.get("state")
            if record.get("status") != "computed":
                entry["status"] = "failed"
                entry["error"] = record.get("error")
                results[sample_id] = entry
                continue
            # Repeatability: the same request must give the same curve.
            repeat = adapter.run_phase_fraction_curve(
                preview,
                interpreter=str(args.interpreter),
                timeout_seconds=args.worker_timeout,
            )
            entry["repeat_status"] = repeat.get("status")
            repeat_points = repeat.get("points", []) if repeat.get("status") == "computed" else []
            first_points = record.get("points", [])
            repeat_diffs: list[float] = []
            if len(repeat_points) == len(first_points):
                for left, right in zip(first_points, repeat_points):
                    names = set(left["phase_fractions_mole"]) | set(right["phase_fractions_mole"])
                    repeat_diffs.extend(
                        abs(left["phase_fractions_mole"].get(name, 0.0)
                            - right["phase_fractions_mole"].get(name, 0.0))
                        for name in names
                    )
            max_diff = max(repeat_diffs) if repeat_diffs else None
            # A numerical solver is not bitwise reproducible.  The meaningful criterion is that the
            # phase assemblage is identical and every fraction agrees far below any physical
            # significance; the observed maximum difference is recorded either way.
            entry["repeat_max_abs_difference"] = max_diff
            entry["repeat_tolerance"] = REPEAT_TOLERANCE
            entry["repeat_identical"] = (
                repeat.get("status") == "computed"
                and len(repeat_points) == len(first_points)
                and max_diff is not None and max_diff <= REPEAT_TOLERANCE
            )
            entry["repeat_assemblage_identical"] = (
                [sorted(point["phases_present"]) for point in first_points]
                == [sorted(point["phases_present"]) for point in repeat_points]
            )
            entry["retried_temperatures_C"] = record.get("non_converged_retried_temperatures_C", [])
            entry["failed_temperatures_C"] = record.get("non_converged_failed_temperatures_C", [])
            points = record["points"]
            sums = [point["total_moles"] for point in points]
            sanity = plausibility(record)
            if not entry["repeat_identical"]:
                sanity["problems"].append(
                    f"重复运行结果不一致（最大绝对差 {max_diff}，容差 {REPEAT_TOLERANCE}）")
                sanity["status"] = "failed"
            if not entry["repeat_assemblage_identical"]:
                sanity["problems"].append("重复运行的稳定相组合不一致")
                sanity["status"] = "failed"
            if entry["failed_temperatures_C"]:
                sanity["problems"].append(
                    "存在重试后仍未收敛的温度点：" + str(entry["failed_temperatures_C"]))
                sanity["status"] = "failed"
            entry["status"] = "ok" if sanity["status"] == "ok" else "failed"
            entry["plausibility"] = sanity
            entry["point_count"] = len(points)
            entry["sum_min"] = round(min(sums), 10)
            entry["sum_max"] = round(max(sums), 10)
            entry["non_converged_points"] = [
                point["temperature_C"] for point in points
                if abs(point["total_moles"] - 1.0) > 1e-4
            ]
            entry["phase_union"] = sorted({name for point in points
                                           for name in point["phases_present"]})
            entry["elapsed_s"] = record.get("elapsed_s")
            results[sample_id] = entry
            print(f"{sample_id}: status={entry['status']} phases={entry['phase_union']} "
                  f"sum=[{entry['sum_min']}, {entry['sum_max']}] "
                  f"plausibility={sanity['status']} {sanity['problems']}", flush=True)

        step6 = results.get("B-DQ", {})
        step7 = results.get("R-DQ", {})
        report["steps"]["step6_b_dq_reduced_system"] = step6
        report["steps"]["step7_r_dq_reduced_system"] = step7

        parity_checks: dict[str, bool] = {}
        if step6.get("status") == "ok" and step7.get("status") == "ok":
            parity_checks = {
                "same_components": step6["components"] == step7["components"],
                "same_component_count": len(step6["components"]) == len(step7["components"]) == 12,
                "same_phases": step6["phases"] == step7["phases"],
                "same_phase_set_matches_profile":
                    tuple(step6["phases"]) == adapter.REQUIRED_MATRIX_PHASES,
                "same_approved_elements": step6["included_elements"] == step7["included_elements"],
                "same_excluded_elements": step6["excluded_elements"] == step7["excluded_elements"],
                "both_repeatable": bool(step6.get("repeat_identical")) and bool(step7.get("repeat_identical")),
            }
        report["steps"]["step8_b_and_r_use_identical_system"] = {
            "status": "ok" if parity_checks and all(parity_checks.values()) else "failed",
            "checks": parity_checks,
        }

        # step 9: the excluded elements must never reach the worker
        excluded_elements = sorted(set(
            list(step6.get("excluded_elements", [])) + list(step7.get("excluded_elements", []))
        ))
        leak_checks: dict[str, Any] = {}
        for sample_id in SAMPLES:
            preview = previews.get(sample_id)
            if preview is None or preview.request is None:
                leak_checks[sample_id] = {"status": "failed", "reason": "no request"}
                continue
            request = preview.request
            declared = {str(name).upper() for name in request["components"]}
            fractions = {str(name).upper() for name in request["component_mole_fractions"]}
            record = records.get(sample_id, {})
            worker_components = {str(name).upper()
                                 for name in record.get("components", []) or declared}
            intruders = sorted(
                ({element.upper() for element in excluded_elements} & declared)
                | ({element.upper() for element in excluded_elements} & fractions)
                | ({element.upper() for element in excluded_elements} & worker_components)
            )
            leak_checks[sample_id] = {
                "status": "ok" if not intruders else "failed",
                "excluded_elements": excluded_elements,
                "request_components": sorted(declared),
                "request_component_count": len(declared),
                "intruders": intruders,
            }
        report["steps"]["step9_excluded_elements_absent_from_worker"] = {
            "status": "ok" if all(item.get("status") == "ok" for item in leak_checks.values())
            else "failed",
            "per_sample": leak_checks,
        }

        # step 10: the page and every export carry the full limitation
        export_checks: dict[str, Any] = {}
        for sample_id in SAMPLES:
            record = records.get(sample_id)
            if not record or record.get("status") != "computed":
                export_checks[sample_id] = {"status": "failed", "reason": "no computed record"}
                continue
            markdown = adapter.phase_fraction_curve_markdown(record)
            csv_text = adapter.phase_fraction_csv(record)
            record_json = json.dumps(record, ensure_ascii=False)
            missing_markdown = [token for token in REQUIRED_MARKDOWN_TOKENS if token not in markdown]
            missing_csv = [token for token in REQUIRED_CSV_TOKENS if token not in csv_text]
            missing_record = [
                key for key in (
                    "result_label", "component_profile", "phase_profile", "reduced_component_system",
                    "included_elements", "excluded_elements_with_reasons",
                    "not_computed_in_this_phase", "model_losses", "component_versions_and_hashes",
                    "reduced_system_approval", "review_status",
                    "writes_back_formal_experimental_data",
                ) if key not in record
            ]
            data_rows = [line for line in csv_text.splitlines() if line and not line.startswith("#")]
            rows_carry = all(
                adapter.RESULT_LABEL_MATRIX in row and "steel_matrix_equilibrium_v1" in row
                and "steel_matrix_major_carbides_v1" in row
                for row in data_rows[1:]
            ) if len(data_rows) > 1 else False
            export_checks[sample_id] = {
                "status": "ok" if not missing_markdown and not missing_csv
                and not missing_record and rows_carry else "failed",
                "missing_markdown_tokens": missing_markdown,
                "missing_csv_tokens": missing_csv,
                "missing_record_keys": missing_record,
                "csv_rows_carry_profile": rows_carry,
                "record_contains_limitation": "limitation_notice" in record,
                "record_json_bytes": len(record_json),
            }
        report["steps"]["step10_page_and_exports_carry_limitation"] = {
            "status": "ok" if all(item.get("status") == "ok" for item in export_checks.values())
            else "failed",
            "per_sample": export_checks,
        }

    # --- verdict ------------------------------------------------------------------------------
    statuses = {name: step.get("status") for name, step in report["steps"].items()}
    blocking = [name for name, status in statuses.items() if status not in ("ok", "skipped")]
    report["step_statuses"] = statuses
    report["blocking_steps"] = blocking
    report["overall_status"] = (
        "pilot_ready_pending_scientific_review" if not blocking else "blocked"
    )
    report["not_claimed"] = ["validated", "production_ready"]
    report["permanent_limitations"] = {
        "text_zh": adapter.MATRIX_ACKNOWLEDGEMENT_TEXT,
        "not_computed": list(adapter.MATRIX_NOT_COMPUTED),
        "model_losses": dict(
            (adapter.load_reduced_system_policy().get("model_losses") or {})
        ),
        "review_status": adapter.REVIEW_STATUS,
        "writes_back_formal_experimental_data": False,
        "is_complete_phase_diagram": False,
    }
    report["elapsed_s"] = round(time.perf_counter() - started, 1)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                         encoding="utf-8")

    print()
    for name, status in statuses.items():
        print(f"{name}: {status}")
    print(f"overall: {report['overall_status']}")
    print(f"json: {args.json}")
    return 0 if not blocking else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
