from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from segment_anything import SamPredictor, sam_model_registry


def normalize_sem_tif(path: Path, strip_height: int = 223) -> tuple[np.ndarray, dict[str, int]]:
    """Read a SEM TIF without modifying it and remove the instrument information strip."""
    with Image.open(path) as image:
        raw = np.asarray(image, dtype=np.float32)
    if raw.ndim == 3:
        raw = raw[..., 0]
    source_height, source_width = raw.shape
    crop_height = source_height - strip_height if source_height > strip_height else source_height
    micrograph = raw[:crop_height, :]
    low, high = np.percentile(micrograph, (1, 99))
    if high <= low:
        gray = np.zeros_like(micrograph, dtype=np.uint8)
    else:
        gray = np.clip((micrograph - low) / (high - low) * 255, 0, 255).astype(np.uint8)
    rgb = np.repeat(gray[..., None], 3, axis=2)
    return rgb, {
        "source_width_px": source_width,
        "source_height_px": source_height,
        "analysis_width_px": int(rgb.shape[1]),
        "analysis_height_px": int(rgb.shape[0]),
        "removed_strip_px": source_height - crop_height,
    }


def save_outputs(
    image: np.ndarray,
    mask: np.ndarray,
    point: tuple[int, int],
    output_dir: Path,
    stem: str,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / f"{stem}_input.png"
    mask_path = output_dir / f"{stem}_mask.png"
    overlay_path = output_dir / f"{stem}_overlay.png"

    Image.fromarray(image).save(input_path)
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(mask_path)

    overlay = image.astype(np.float32).copy()
    red = np.zeros_like(overlay)
    red[..., 0] = 255
    alpha = 0.42
    overlay[mask] = (1 - alpha) * overlay[mask] + alpha * red[mask]
    overlay_image = Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(overlay_image)
    radius = 8
    draw.ellipse(
        (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
        fill=(0, 255, 80),
        outline=(255, 255, 255),
        width=2,
    )
    overlay_image.save(overlay_path)
    return {"input": str(input_path), "mask": str(mask_path), "overlay": str(overlay_path)}


def run_one(
    predictor: SamPredictor,
    image_path: Path,
    output_dir: Path,
    pixel_size_um: float | None,
) -> dict[str, object]:
    image, dimensions = normalize_sem_tif(image_path)
    point = (image.shape[1] // 2, image.shape[0] // 2)

    started = time.perf_counter()
    predictor.set_image(image)
    embedding_seconds = time.perf_counter() - started

    masks, scores, _ = predictor.predict(
        point_coords=np.asarray([point], dtype=np.float32),
        point_labels=np.asarray([1], dtype=np.int32),
        multimask_output=True,
    )
    selected = int(np.argmax(scores))
    mask = masks[selected]
    mask_pixels = int(mask.sum())
    paths = save_outputs(image, mask, point, output_dir, image_path.stem)

    result: dict[str, object] = {
        "sample_file": image_path.name,
        "source_path": str(image_path),
        "source_policy": "read_only",
        "review_status": "technical_smoke_test_not_scientifically_validated",
        "prompt_type": "single_positive_point",
        "prompt_xy_px": list(point),
        "selected_mask_index": selected,
        "model_score": float(scores[selected]),
        "all_model_scores": [float(value) for value in scores],
        "mask_area_px": mask_pixels,
        "embedding_seconds": round(embedding_seconds, 3),
        "dimensions": dimensions,
        "outputs": paths,
    }
    if pixel_size_um is not None:
        result["pixel_size_um"] = pixel_size_um
        result["mask_area_um2_unreviewed"] = round(mask_pixels * pixel_size_um**2, 3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a non-scientific SAM smoke test on paired SEM images.")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image", action="append", type=Path, required=True)
    parser.add_argument("--pixel-size-um", action="append", type=float, default=[])
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this SteelAI smoke test.")
    if not args.checkpoint.exists():
        raise FileNotFoundError(args.checkpoint)
    for path in args.image:
        if not path.exists():
            raise FileNotFoundError(path)

    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint))
    model.to(device="cuda")
    predictor = SamPredictor(model)
    load_seconds = time.perf_counter() - load_started

    results = []
    for index, image_path in enumerate(args.image):
        pixel_size = args.pixel_size_um[index] if index < len(args.pixel_size_um) else None
        results.append(run_one(predictor, image_path, args.output_dir, pixel_size))

    report = {
        "schema_version": "1.0",
        "status": "technical_smoke_test_not_scientifically_validated",
        "model": "Segment Anything ViT-B",
        "checkpoint": str(args.checkpoint),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "model_load_seconds": round(load_seconds, 3),
        "peak_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
        "interpretation_boundary": (
            "Masks only verify the software pipeline. They are not accepted dimples, inclusions, "
            "cleavage facets, or quantitative B/R evidence until a human defines and reviews the target."
        ),
        "results": results,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "smoke_test_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
