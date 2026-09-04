from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from steelai.ebsd import read_ctf_header


METRICS = {
    "indexed_fraction_percent": ("Indexed fraction", "%"),
    "retained_phase_fraction_of_indexed_percent": ("FCC fraction of indexed points", "%"),
    "median_equivalent_diameter_um_interior": ("Median interior BCC orientation-grain diameter", "um"),
    "median_kam_deg": ("Median KAM", "degree"),
    "hagb_length_fraction_percent": ("HAGB length fraction", "%"),
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_percent(b_value: float, r_value: float) -> float | None:
    if b_value == 0:
        return None
    return 100.0 * (r_value - b_value) / b_value


def _relative_close(first: float | None, second: float | None, tolerance_percent: float = 1.0) -> bool:
    if first is None or second is None:
        return False
    scale = max(abs(float(first)), abs(float(second)))
    if scale == 0:
        return True
    return 100.0 * abs(float(first) - float(second)) / scale <= tolerance_percent


def compare_ctf_headers(b_header: dict[str, Any], r_header: dict[str, Any]) -> dict[str, Any]:
    b_width = max(int(b_header.get("x_cells", 0)) - 1, 0) * float(b_header.get("x_step_um", 0))
    r_width = max(int(r_header.get("x_cells", 0)) - 1, 0) * float(r_header.get("x_step_um", 0))
    b_height = max(int(b_header.get("y_cells", 0)) - 1, 0) * float(b_header.get("y_step_um", 0))
    r_height = max(int(r_header.get("y_cells", 0)) - 1, 0) * float(r_header.get("y_step_um", 0))
    checks = {
        "step_size_within_1_percent": _relative_close(b_header.get("x_step_um"), r_header.get("x_step_um")),
        "magnification_within_1_percent": _relative_close(b_header.get("magnification"), r_header.get("magnification")),
        "field_width_within_1_percent": _relative_close(b_width, r_width),
        "field_height_within_1_percent": _relative_close(b_height, r_height),
        "voltage": b_header.get("voltage_kv") == r_header.get("voltage_kv"),
        "tilt": b_header.get("tilt_angle_deg") == r_header.get("tilt_angle_deg"),
        "phases": b_header.get("phases") == r_header.get("phases"),
    }
    return {
        "compatible": all(checks.values()),
        "checks": checks,
        "b_field_um": {"width": b_width, "height": b_height},
        "r_field_um": {"width": r_width, "height": r_height},
    }


def acquisition_compatibility(b_summary: dict[str, Any], r_summary: dict[str, Any]) -> dict[str, Any]:
    b_header = read_ctf_header(Path(b_summary["input_file"]))
    r_header = read_ctf_header(Path(r_summary["input_file"]))
    compatibility = compare_ctf_headers(b_header, r_header)
    compatibility["b_header"] = b_header
    compatibility["r_header"] = r_header
    return compatibility


def build_comparison(b_summary: dict[str, Any], r_summary: dict[str, Any]) -> dict[str, Any]:
    compatibility = acquisition_compatibility(b_summary, r_summary)
    metric_rows = []
    for key, (label, unit) in METRICS.items():
        b_value = float(b_summary[key])
        r_value = float(r_summary[key])
        metric_rows.append(
            {
                "metric": key,
                "label": label,
                "unit": unit,
                "B_DQ": b_value,
                "R_DQ": r_value,
                "R_minus_B": r_value - b_value,
                "R_vs_B_percent": _relative_percent(b_value, r_value),
            }
        )
    return {
        "schema_version": "1.0",
        "status": "completed",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "comparison_unit": "one EBSD map per condition",
        "acquisition_compatibility": compatibility,
        "metrics": metric_rows,
        "limitations": [
            "This is a directional comparison of one field per condition; it is not an inferential sample-level conclusion.",
            "The 3-degree BCC orientation grains are not martensite blocks, packets, or prior-austenite grains.",
            "The indexed FCC fraction is not accepted as retained-austenite truth without phase validation.",
            "All comparisons depend on the shared MTEX reconstruction and KAM parameters stored in each summary.",
        ],
    }


def write_comparison(b_output: Path, r_output: Path, output_root: Path) -> dict[str, Path]:
    b_summary = _read_json(b_output / "summary.json")
    r_summary = _read_json(r_output / "summary.json")
    comparison = build_comparison(b_summary, r_summary)
    output_root.mkdir(parents=True, exist_ok=True)

    json_path = output_root / "comparison.json"
    csv_path = output_root / "comparison.csv"
    report_path = output_root / "B_vs_R_EBSD_preliminary_report.md"
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison["metrics"][0].keys()))
        writer.writeheader()
        writer.writerows(comparison["metrics"])

    compatibility_text = "matched" if comparison["acquisition_compatibility"]["compatible"] else "not matched"
    rows = [
        "# B-DQ vs R-DQ EBSD preliminary comparison",
        "",
        f"- Acquisition compatibility: **{compatibility_text}**",
        "- Statistical unit: one EBSD map per condition",
        "- Interpretation level: directional exploratory evidence only",
        "",
        "| Metric | B-DQ | R-DQ | R vs B |",
        "|---|---:|---:|---:|",
    ]
    for metric in comparison["metrics"]:
        relative = metric["R_vs_B_percent"]
        relative_text = "n/a" if relative is None else f"{relative:+.2f}%"
        rows.append(
            f"| {metric['label']} ({metric['unit']}) | {metric['B_DQ']:.4f} | "
            f"{metric['R_DQ']:.4f} | {relative_text} |"
        )
    rows.extend(["", "## Evidence boundaries", ""])
    rows.extend(f"- {item}" for item in comparison["limitations"])
    report_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"comparison": json_path, "table": csv_path, "report": report_path}
