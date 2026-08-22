from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tifffile
import torch
from PIL import Image
from micro_sam.instance_segmentation import AutomaticMaskGenerator
from segment_anything import SamPredictor, sam_model_registry


def normalize_sem_tif(path: Path, strip_height: int = 223) -> np.ndarray:
    with Image.open(path) as image:
        raw = np.asarray(image, dtype=np.float32)
    if raw.ndim == 3:
        raw = raw[..., 0]
    crop_height = raw.shape[0] - strip_height if raw.shape[0] > strip_height else raw.shape[0]
    micrograph = raw[:crop_height, :]
    low, high = np.percentile(micrograph, (1, 99))
    if high <= low:
        gray = np.zeros_like(micrograph, dtype=np.uint8)
    else:
        gray = np.clip((micrograph - low) / (high - low) * 255, 0, 255).astype(np.uint8)
    return gray


def relabel_candidates(labels: np.ndarray, candidates) -> np.ndarray:
    lookup = np.zeros(int(labels.max()) + 1, dtype=np.uint32)
    for new_id, item in enumerate(candidates, start=1):
        lookup[item.source_label_id] = new_id
    return lookup[labels]


def save_overlay(image: np.ndarray, labels: np.ndarray, path: Path) -> None:
    boundary = np.zeros(labels.shape, dtype=bool)
    boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
    boundary[:-1, :] |= labels[:-1, :] != labels[1:, :]
    boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    boundary[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    boundary &= labels > 0
    overlay = np.repeat(image[..., None], 3, axis=2) if image.ndim == 2 else image.copy()
    overlay[boundary] = (255, 230, 0)
    Image.fromarray(overlay).save(path)


def write_object_table(path: Path, candidates, pixel_size_um: float) -> list[float]:
    diameters: list[float] = []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["object_id", "source_label_id", "area_px", "area_um2", "deq_um", "size_bin"],
        )
        writer.writeheader()
        for object_id, item in enumerate(candidates, start=1):
            area_um2 = item.area_px * pixel_size_um**2
            deq_um = float(2 * np.sqrt(area_um2 / np.pi))
            diameters.append(deq_um)
            writer.writerow(
                {
                    "object_id": object_id,
                    "source_label_id": item.source_label_id,
                    "area_px": item.area_px,
                    "area_um2": round(area_um2, 6),
                    "deq_um": round(deq_um, 6),
                    "size_bin": item.size_bin,
                }
            )
    return diameters


def process_image(predictor, manifest_row, standard, output_root: Path, project_root: Path) -> dict:
    from steelai.dimple_standard import assess_run, estimate_true_candidates
    from steelai.review_sampling import candidate_properties

    image_path = Path(manifest_row["image_path"])
    stem = image_path.stem
    steel = manifest_row["steel"]
    pixel_size_um = float(manifest_row["pixel_size_um"])
    magnification_x = int(float(manifest_row["magnification_x"]))
    sample_dir = output_root / stem
    sample_dir.mkdir(parents=True, exist_ok=True)
    result_path = sample_dir / f"{stem}_auto_result_v0.1.json"
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assessment = assess_run(
            magnification_x,
            pixel_size_um,
            float(result["candidate_coverage_percent"]),
            float(result["median_equivalent_diameter_um"]),
            standard,
        )
        result["standard_id"] = standard["standard_id"]
        result["status"] = assessment["status"]
        result["triggered_rules"] = assessment["triggered_rules"]
        result["warnings"] = assessment.get("warnings", [])
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"RESUME {stem}: {result.get('status')}", flush=True)
        return result

    print(f"START {stem}", flush=True)
    started = time.perf_counter()
    image = normalize_sem_tif(image_path)
    Image.fromarray(image).save(sample_dir / f"{stem}_input.png")
    amg = AutomaticMaskGenerator(predictor, points_per_side=32, points_per_batch=64)
    amg.initialize(image)
    params = standard["segmentation"]
    raw_labels = amg.generate(
        pred_iou_thresh=float(params["pred_iou_thresh"]),
        stability_score_thresh=float(params["stability_score_thresh"]),
        box_nms_thresh=float(params["box_nms_thresh"]),
        output_mode="instance_segmentation",
        with_background=True,
    )
    minimum_area = int(standard["postprocessing"]["minimum_area_px"])
    candidates = candidate_properties(raw_labels, min_area_px=minimum_area, exclude_edges=True)
    labels = relabel_candidates(raw_labels, candidates)
    tifffile.imwrite(sample_dir / f"{stem}_auto_labels_v0.1.tif", labels, compression="zlib")
    save_overlay(image, labels, sample_dir / f"{stem}_auto_overlay_v0.1.png")
    diameters = write_object_table(sample_dir / f"{stem}_auto_objects_v0.1.csv", candidates, pixel_size_um)

    foreground_px = int((labels > 0).sum())
    coverage_percent = foreground_px / labels.size * 100
    median_deq_um = float(np.median(diameters)) if diameters else 0.0
    quantiles = np.quantile(diameters, [0.1, 0.5, 0.9]) if diameters else np.zeros(3)
    assessment = assess_run(magnification_x, pixel_size_um, coverage_percent, median_deq_um, standard)
    estimate = estimate_true_candidates(len(candidates), standard)
    analysis_area_um2 = labels.size * pixel_size_um**2
    result = {
        "schema_version": "1.0",
        "result_id": f"{stem}_auto_result_v0.1",
        "status": assessment["status"],
        "sample_id": stem,
        "steel": steel,
        "source_path": str(image_path),
        "source_policy": "read_only",
        "standard_id": standard["standard_id"],
        "magnification_x": magnification_x,
        "pixel_size_um": pixel_size_um,
        "image_shape_px": list(labels.shape),
        "analysis_area_um2": round(analysis_area_um2, 6),
        "candidate_count_postfilter": len(candidates),
        "estimated_true_candidates": estimate["estimated_true_candidates"],
        "exploratory_lower": estimate["exploratory_lower"],
        "exploratory_upper": estimate["exploratory_upper"],
        "candidate_coverage_percent": round(coverage_percent, 6),
        "median_equivalent_diameter_um": round(median_deq_um, 6),
        "D10_um": round(float(quantiles[0]), 6),
        "D50_um": round(float(quantiles[1]), 6),
        "D90_um": round(float(quantiles[2]), 6),
        "adjusted_density_per_1000_um2": round(
            estimate["estimated_true_candidates"] / analysis_area_um2 * 1000, 6
        ),
        "triggered_rules": assessment["triggered_rules"],
        "warnings": assessment.get("warnings", []),
        "routine_manual_review": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "outputs": {
            "labels": str(sample_dir / f"{stem}_auto_labels_v0.1.tif"),
            "objects": str(sample_dir / f"{stem}_auto_objects_v0.1.csv"),
            "overlay": str(sample_dir / f"{stem}_auto_overlay_v0.1.png"),
        },
        "interpretation_boundary": standard["interpretation_boundary"],
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE {stem}: status={result['status']} candidates={len(candidates)} "
        f"estimated={result['estimated_true_candidates']} median={median_deq_um:.3f}um",
        flush=True,
    )
    del amg, raw_labels, labels
    predictor.reset_image()
    torch.cuda.empty_cache()
    return result


def write_summary_csv(rows: list[dict], output_root: Path) -> Path:
    path = output_root / "br_image_summary_v0.1.csv"
    fields = [
        "sample_id", "steel", "status", "candidate_count_postfilter", "estimated_true_candidates",
        "exploratory_lower", "exploratory_upper", "candidate_coverage_percent",
        "median_equivalent_diameter_um", "D10_um", "D50_um", "D90_um",
        "adjusted_density_per_1000_um2", "elapsed_seconds",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)
    return path


def write_plots(rows: list[dict], output_root: Path) -> list[str]:
    valid = [row for row in rows if str(row["status"]).startswith("in_standard")]
    metrics = [
        ("estimated_true_candidates", "Estimated dimple candidates / image"),
        ("candidate_coverage_percent", "Candidate coverage (%)"),
        ("median_equivalent_diameter_um", "Median equivalent diameter (µm)"),
        ("adjusted_density_per_1000_um2", "Adjusted density (/1000 µm²)"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    for axis, (metric, title) in zip(axes.ravel(), metrics):
        data = [[row[metric] for row in valid if row["steel"] == steel] for steel in ("B", "R")]
        axis.boxplot(data, tick_labels=["B", "R"], patch_artist=True)
        for index, values in enumerate(data, start=1):
            axis.scatter(np.full(len(values), index), values, color="#16324f", zorder=3)
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle("B/R 1000x SEM AutoDimple preliminary comparison")
    fig.tight_layout()
    plot_path = output_root / "br_metric_boxplots_v0.1.png"
    fig.savefig(plot_path, dpi=180)
    plt.close(fig)
    return [str(plot_path)]


def write_report(rows: list[dict], comparison: dict, output_root: Path, standard_id: str) -> Path:
    path = output_root / "B_vs_R_AutoDimple_preliminary_report_v0.1.md"
    m = comparison["metrics"]
    count = m["estimated_true_candidates"]
    coverage = m["candidate_coverage_percent"]
    diameter = m["median_equivalent_diameter_um"]
    density = m["adjusted_density_per_1000_um2"]
    d10 = m["D10_um"]
    d90 = m["D90_um"]
    warning_count = sum(bool(row.get("warnings")) for row in rows)
    lines = [
        "# B/R 1000× SEM AutoDimple初步对比报告",
        "",
        "## 数据与方法",
        "",
        f"- 有效图像：B钢 {comparison['n_images']['B']} 张，R钢 {comparison['n_images']['R']} 张。",
        "- 图像为独立统计单位；单个韧窝仅用于描述尺寸分布，不作为独立实验重复。",
        f"- 使用 {standard_id}；逐对象人工复核关闭。",
        f"- {warning_count}张图出现尺寸或覆盖率分布偏移警告，但因倍率与标定合格，仍纳入探索性比较。",
        "- 该标准由单张B-DQ图的Review30校准，跨钢种结果属于探索性证据。",
        "",
        "## B/R图像级结果",
        "",
        "| 指标 | B均值 | R均值 | R相对B | R-B bootstrap 95%区间 |",
        "|---|---:|---:|---:|---:|",
        f"| 校正候选数/图 | {count['B_mean']:.2f} | {count['R_mean']:.2f} | {count['R_vs_B_percent']:.1f}% | {count['bootstrap_mean_difference']['ci95_low']:.2f}–{count['bootstrap_mean_difference']['ci95_high']:.2f} |",
        f"| 候选覆盖率/% | {coverage['B_mean']:.3f} | {coverage['R_mean']:.3f} | {coverage['R_vs_B_percent']:.1f}% | {coverage['bootstrap_mean_difference']['ci95_low']:.3f}–{coverage['bootstrap_mean_difference']['ci95_high']:.3f} |",
        f"| 中位等效直径/µm | {diameter['B_mean']:.3f} | {diameter['R_mean']:.3f} | {diameter['R_vs_B_percent']:.1f}% | {diameter['bootstrap_mean_difference']['ci95_low']:.3f}–{diameter['bootstrap_mean_difference']['ci95_high']:.3f} |",
        f"| 校正数量密度/(1000 µm²) | {density['B_mean']:.3f} | {density['R_mean']:.3f} | {density['R_vs_B_percent']:.1f}% | {density['bootstrap_mean_difference']['ci95_low']:.3f}–{density['bootstrap_mean_difference']['ci95_high']:.3f} |",
        f"| 图像D10/µm | {d10['B_mean']:.3f} | {d10['R_mean']:.3f} | {d10['R_vs_B_percent']:.1f}% | {d10['bootstrap_mean_difference']['ci95_low']:.3f}–{d10['bootstrap_mean_difference']['ci95_high']:.3f} |",
        f"| 图像D90/µm | {d90['B_mean']:.3f} | {d90['R_mean']:.3f} | {d90['R_vs_B_percent']:.1f}% | {d90['bootstrap_mean_difference']['ci95_low']:.3f}–{d90['bootstrap_mean_difference']['ci95_high']:.3f} |",
        "",
        "## 解释边界",
        "",
        "- bootstrap区间跨越0时，当前5张/组不足以支持稳定方向性差异。",
        "- 73.3%校正系数来自尺寸平衡的B钢Review30，不能视为R钢独立验证精度。",
        "- 本报告用于筛选研究假设，不能单独证明冲击韧性变化机制。",
        "",
        "## 下一步建议",
        "",
        "将图像级结果与冲击功、夹杂/裂纹证据和EBSD层级结构联合分析；保持倍率和标定分层。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SteelAI B/R 1000x AutoDimple batch.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--standard", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project_root))
    from steelai.batch_dimple import summarize_groups

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the batch AutoDimple workflow.")
    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    if len(manifest) != 10:
        raise ValueError(f"Expected 10 pilot images, found {len(manifest)}")
    for row in manifest:
        if not Path(row["image_path"]).exists():
            raise FileNotFoundError(row["image_path"])

    args.output_root.mkdir(parents=True, exist_ok=True)
    print(f"Loading SAM on {torch.cuda.get_device_name(0)}", flush=True)
    model = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint))
    model.to(device="cuda")
    predictor = SamPredictor(model)
    rows = [process_image(predictor, row, standard, args.output_root, args.project_root) for row in manifest]
    comparison = summarize_groups(rows)
    summary_path = write_summary_csv(rows, args.output_root)
    comparison_path = args.output_root / "br_comparison_v0.1.json"
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    plots = write_plots(rows, args.output_root)
    report_path = write_report(rows, comparison, args.output_root, standard["standard_id"])
    batch_manifest = {
        "schema_version": "1.0",
        "status": (
            "complete"
            if all(row["status"] == "in_standard" for row in rows)
            else "complete_with_warnings"
            if all(str(row["status"]).startswith("in_standard") for row in rows)
            else "completed_with_exclusions"
        ),
        "standard_id": standard["standard_id"],
        "image_count": len(rows),
        "routine_manual_review": False,
        "outputs": {
            "image_summary": str(summary_path),
            "comparison": str(comparison_path),
            "plots": plots,
            "report": str(report_path),
        },
    }
    manifest_path = args.output_root / "batch_manifest_v0.1.json"
    manifest_path.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(batch_manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
