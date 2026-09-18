from __future__ import annotations

import argparse
import json
from pathlib import Path

from steelai.event_log import record_event
from steelai.paths import OUTPUTS
from steelai.thermal_simulation_intake import (
    build_thermal_standardization_preview,
    commit_thermal_preview_governed,
    inspect_thermal_simulation_batch,
    read_plan_csv,
    read_thermal_simulation_folder,
    save_thermal_preview_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and optionally commit a governed thermal-simulation intake.")
    parser.add_argument("source_folder", type=Path)
    parser.add_argument("--plan-csv", type=Path)
    parser.add_argument("--output-root", type=Path, default=OUTPUTS / "thermal_simulation_intake")
    parser.add_argument("--confirm-time-seconds", action="store_true")
    parser.add_argument("--force-unit", choices=["instrument_kg_force", "kgf"])
    parser.add_argument("--confirm-specimen-mapping", action="store_true")
    parser.add_argument("--accept-instrument-over-plan", action="store_true")
    parser.add_argument("--commit", action="store_true", help="Append both normalized tables after human approval.")
    parser.add_argument("--reviewer-id")
    parser.add_argument("--rationale")
    args = parser.parse_args()

    files = read_thermal_simulation_folder(args.source_folder)
    batch = inspect_thermal_simulation_batch(files)
    plan_rows = read_plan_csv(args.plan_csv.read_bytes()) if args.plan_csv else []
    preview = build_thermal_standardization_preview(
        batch,
        plan_rows,
        time_unit_confirmed=args.confirm_time_seconds,
        force_unit_interpretation=args.force_unit or "",
        specimen_mapping_confirmed=args.confirm_specimen_mapping,
        accept_instrument_over_plan=args.accept_instrument_over_plan,
    )
    paths = save_thermal_preview_package(preview, args.output_root)
    summary = {
        "status": preview["status"],
        "file_count": preview["file_count"],
        "point_count": preview["point_count"],
        "errors": preview["errors"],
        "warnings": preview["warnings"],
        "decisions_needed": preview["decisions_needed"],
        "package": str(paths["package"]),
    }
    if args.commit:
        if not args.reviewer_id or not args.reviewer_id.strip():
            parser.error("--commit requires --reviewer-id")
        if not args.rationale or not args.rationale.strip():
            parser.error("--commit requires --rationale")
        result = commit_thermal_preview_governed(
            preview,
            reviewer_id=args.reviewer_id,
            rationale=args.rationale,
            confirmed=True,
        )
        record_event(
            "data_intake",
            "热模拟曲线正式接入",
            f"{preview['file_count']} 个采集、{preview['point_count']} 个曲线点完成治理入库",
            {
                "transaction_id": result["transaction_id"],
                "governance_intake_id": result["governance_intake_id"],
                "tables": result["tables"],
            },
            ["thermal_simulation", "data_standardization", "governed_intake"],
        )
        summary["commit"] = result
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if preview["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
