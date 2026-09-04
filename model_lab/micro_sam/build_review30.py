from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import tifffile
import z5py
from PIL import Image, ImageDraw


def _load_sampling_module(project_root: Path):
    sys.path.insert(0, str(project_root))
    from steelai.review_sampling import build_review_seed, candidate_properties, select_review_candidates

    return build_review_seed, candidate_properties, select_review_candidates


def _outline_overlay(image_path: Path, seed: np.ndarray, selected, output_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    array = np.asarray(image).copy()
    boundary = np.zeros(seed.shape, dtype=bool)
    boundary[1:, :] |= seed[1:, :] != seed[:-1, :]
    boundary[:-1, :] |= seed[:-1, :] != seed[1:, :]
    boundary[:, 1:] |= seed[:, 1:] != seed[:, :-1]
    boundary[:, :-1] |= seed[:, :-1] != seed[:, 1:]
    boundary &= seed > 0
    array[boundary] = (255, 230, 0)
    overlay = Image.fromarray(array)
    draw = ImageDraw.Draw(overlay)
    for review_id, item in enumerate(selected, start=1):
        x, y = int(round(item.centroid_x_px)), int(round(item.centroid_y_px))
        text = str(review_id)
        box = draw.textbbox((x, y), text, anchor="mm")
        draw.rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1), fill=(0, 0, 0))
        draw.text((x, y), text, fill=(255, 255, 0), anchor="mm")
    overlay.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a spatially and size-stratified Review30 seed.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--candidate-zarr", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pixel-size-um", type=float, required=True)
    parser.add_argument("--min-area-px", type=int, default=50)
    args = parser.parse_args()

    build_review_seed, candidate_properties, select_review_candidates = _load_sampling_module(args.project_root)
    candidate_path = args.candidate_zarr.as_posix()
    labels = z5py.ZarrFile(candidate_path, "r")["committed_objects"][:]
    candidates = candidate_properties(labels, min_area_px=args.min_area_px)
    selected = select_review_candidates(candidates, count=30, image_shape=labels.shape)
    if len(selected) != 30:
        raise RuntimeError(f"Expected 30 review candidates, found {len(selected)}")
    seed = build_review_seed(labels, selected)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    seed_path = args.output_dir / "B-DQ-1-06_review30_seed.tif"
    table_path = args.output_dir / "B-DQ-1-06_review30_table.csv"
    overlay_path = args.output_dir / "B-DQ-1-06_review30_map.png"
    manifest_path = args.output_dir / "B-DQ-1-06_review30_manifest.json"
    tifffile.imwrite(seed_path, seed, photometric="minisblack")

    with table_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "review_id", "source_label_id", "grid_cell", "size_bin", "area_px_auto",
            "area_um2_auto", "deq_um_auto", "centroid_x_px", "centroid_y_px",
            "review_status", "confidence", "boundary_issue", "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for review_id, item in enumerate(selected, start=1):
            area_um2 = item.area_px * args.pixel_size_um**2
            writer.writerow(
                {
                    "review_id": review_id,
                    "source_label_id": item.source_label_id,
                    "grid_cell": f"R{item.grid_row}C{item.grid_col}",
                    "size_bin": item.size_bin,
                    "area_px_auto": item.area_px,
                    "area_um2_auto": round(area_um2, 4),
                    "deq_um_auto": round(2 * np.sqrt(area_um2 / np.pi), 4),
                    "centroid_x_px": round(item.centroid_x_px, 2),
                    "centroid_y_px": round(item.centroid_y_px, 2),
                    "review_status": "pending",
                    "confidence": "",
                    "boundary_issue": "",
                    "notes": "",
                }
            )

    _outline_overlay(args.image, seed, selected, overlay_path)
    manifest = {
        "schema_version": "1.0",
        "status": "review_seed_unreviewed",
        "source_candidate": str(args.candidate_zarr),
        "source_image": str(args.image),
        "selection": "one candidate per 5x6 spatial grid cell with rotating small/medium/large size preference",
        "minimum_area_px": args.min_area_px,
        "excluded_edge_objects": True,
        "review_count": len(selected),
        "outputs": {
            "seed_tif": str(seed_path),
            "review_table": str(table_path),
            "numbered_map": str(overlay_path),
        },
        "interpretation_boundary": "The 30 objects are unreviewed automatic candidates, not accepted dimples.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
