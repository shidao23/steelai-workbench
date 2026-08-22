from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import z5py


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the preliminary automatic dimple standard to a candidate zarr.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--candidate-zarr", type=Path, required=True)
    parser.add_argument("--standard", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--magnification-x", type=int, required=True)
    parser.add_argument("--pixel-size-um", type=float, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.project_root))
    from steelai.dimple_standard import assess_run, estimate_true_candidates
    from steelai.review_sampling import candidate_properties

    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    labels = z5py.ZarrFile(args.candidate_zarr.as_posix(), "r")["committed_objects"][:]
    minimum_area = int(standard["postprocessing"]["minimum_area_px"])
    candidates = candidate_properties(labels, min_area_px=minimum_area, exclude_edges=True)
    foreground_px = sum(item.area_px for item in candidates)
    coverage_percent = foreground_px / labels.size * 100
    diameters = [2 * np.sqrt(item.area_px * args.pixel_size_um**2 / np.pi) for item in candidates]
    median_deq_um = float(np.median(diameters)) if diameters else 0.0
    assessment = assess_run(
        args.magnification_x,
        args.pixel_size_um,
        coverage_percent,
        median_deq_um,
        standard,
    )
    estimate = estimate_true_candidates(len(candidates), standard)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    object_table = args.output_dir / f"{args.sample_id}_auto_objects_v0.1.csv"
    result_path = args.output_dir / f"{args.sample_id}_auto_result_v0.1.json"
    with object_table.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["object_id", "source_label_id", "area_px", "area_um2", "deq_um", "size_bin"],
        )
        writer.writeheader()
        for object_id, item in enumerate(candidates, start=1):
            area_um2 = item.area_px * args.pixel_size_um**2
            writer.writerow(
                {
                    "object_id": object_id,
                    "source_label_id": item.source_label_id,
                    "area_px": item.area_px,
                    "area_um2": round(area_um2, 6),
                    "deq_um": round(2 * np.sqrt(area_um2 / np.pi), 6),
                    "size_bin": item.size_bin,
                }
            )

    result = {
        "schema_version": "1.0",
        "result_id": f"{args.sample_id}_auto_result_v0.1",
        "status": assessment["status"],
        "standard_id": standard["standard_id"],
        "sample_id": args.sample_id,
        "source_candidate": str(args.candidate_zarr),
        "magnification_x": args.magnification_x,
        "pixel_size_um": args.pixel_size_um,
        "candidate_count_postfilter": len(candidates),
        "candidate_coverage_percent": round(coverage_percent, 6),
        "median_equivalent_diameter_um": round(median_deq_um, 6),
        "estimated_true_candidates": estimate,
        "triggered_rules": assessment["triggered_rules"],
        "routine_manual_review": False,
        "object_table": str(object_table),
        "interpretation_boundary": standard["interpretation_boundary"],
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
