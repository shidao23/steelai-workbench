from __future__ import annotations

from math import sqrt
from typing import Any


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("total must be positive")
    if not 0 <= successes <= total:
        raise ValueError("successes must be between zero and total")
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = z * sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2)) / denominator
    return center - margin, center + margin


def build_preliminary_standard(
    correct: int = 22,
    total: int = 30,
    pixel_size_um: float = 0.27265625,
) -> dict[str, Any]:
    rate = correct / total
    lower, upper = wilson_interval(correct, total)
    minimum_area_px = 50
    minimum_area_um2 = minimum_area_px * pixel_size_um**2
    minimum_deq_um = 2 * sqrt(minimum_area_um2 / 3.141592653589793)
    return {
        "schema_version": "1.0",
        "standard_id": "AutoDimple-BDQ-1000x-v0.1",
        "status": "preliminary_automatic_operational_standard",
        "scope": "Matched 1000x SEM fracture images acquired and exported under the B-DQ-1-06 conditions",
        "calibration": {
            "sample": "B-DQ-1-06",
            "human_reported_correct": correct,
            "review_total": total,
            "candidate_acceptance_rate": round(rate, 6),
            "candidate_rejection_rate": round(1 - rate, 6),
            "wilson_95_interval": [round(lower, 6), round(upper, 6)],
            "saved_mask_retained": 25,
            "saved_mask_discrepancy": (
                "The reviewed TIFF retains 25 labels, while the human aggregate reports 22 correct. "
                "The aggregate 22/30 rate is used; no per-object identity is fabricated for the unresolved three."
            ),
        },
        "input_requirements": {
            "magnification_x": 1000,
            "pixel_size_um": pixel_size_um,
            "pixel_size_relative_tolerance": 0.05,
            "same_preparation_detector_contrast_required": True,
        },
        "segmentation": {
            "model": "Segment Anything ViT-B via micro-sam 1.8.8",
            "pred_iou_thresh": 0.78,
            "stability_score_thresh": 0.87,
            "box_nms_thresh": 0.60,
            "min_object_size_px": minimum_area_px,
            "preservation_threshold": 0.78,
        },
        "postprocessing": {
            "minimum_area_px": minimum_area_px,
            "minimum_area_um2": round(minimum_area_um2, 6),
            "minimum_equivalent_diameter_um": round(minimum_deq_um, 6),
            "exclude_edge_touching_objects": True,
            "remove_post_commit_fragments_below_minimum": True,
        },
        "automatic_policy": {
            "routine_object_by_object_review": False,
            "candidate_count_correction_factor": round(rate, 6),
            "correction_is_exploratory": True,
            "baseline_coverage_percent": 28.01766,
            "allowed_coverage_percent": [18.01766, 38.01766],
            "baseline_median_deq_um": 7.586165,
            "allowed_median_deq_um": [5.310316, 9.862015],
            "out_of_standard_action": "Exclude the image from pooled statistics and report the triggered rule.",
        },
        "interpretation_boundary": (
            "This standard produces preliminary automated dimple-candidate estimates. It is calibrated on one "
            "B-DQ image and is not yet a publication-grade universal dimple measurement standard."
        ),
    }


def estimate_true_candidates(candidate_count: int, standard: dict[str, Any]) -> dict[str, int | float]:
    calibration = standard["calibration"]
    rate = float(calibration["candidate_acceptance_rate"])
    lower, upper = (float(value) for value in calibration["wilson_95_interval"])
    return {
        "candidate_count": candidate_count,
        "acceptance_factor": rate,
        "estimated_true_candidates": round(candidate_count * rate),
        "exploratory_lower": round(candidate_count * lower),
        "exploratory_upper": round(candidate_count * upper),
    }


def assess_run(
    magnification_x: int,
    pixel_size_um: float,
    coverage_percent: float,
    median_deq_um: float,
    standard: dict[str, Any],
) -> dict[str, Any]:
    requirements = standard["input_requirements"]
    policy = standard["automatic_policy"]
    failures: list[str] = []
    warnings: list[str] = []
    if magnification_x != int(requirements["magnification_x"]):
        failures.append("magnification_mismatch")
    expected_pixel = float(requirements["pixel_size_um"])
    tolerance = float(requirements["pixel_size_relative_tolerance"])
    if abs(pixel_size_um - expected_pixel) / expected_pixel > tolerance:
        failures.append("pixel_size_mismatch")
    hard_coverage_low, hard_coverage_high = policy.get(
        "hard_allowed_coverage_percent", policy["allowed_coverage_percent"]
    )
    if not hard_coverage_low <= coverage_percent <= hard_coverage_high:
        failures.append("coverage_outlier")
    warning_coverage_low, warning_coverage_high = policy.get(
        "warning_coverage_percent", policy["allowed_coverage_percent"]
    )
    if not warning_coverage_low <= coverage_percent <= warning_coverage_high:
        warnings.append("coverage_shift")
    hard_diameter_low, hard_diameter_high = policy.get(
        "hard_allowed_median_deq_um", policy["allowed_median_deq_um"]
    )
    if not hard_diameter_low <= median_deq_um <= hard_diameter_high:
        failures.append("median_diameter_outlier")
    warning_diameter_low, warning_diameter_high = policy.get(
        "warning_median_deq_um", policy["allowed_median_deq_um"]
    )
    if not warning_diameter_low <= median_deq_um <= warning_diameter_high:
        warnings.append("median_diameter_shift")
    if failures:
        status = "out_of_standard"
    elif warnings:
        status = "in_standard_with_warnings"
    else:
        status = "in_standard"
    return {"status": status, "triggered_rules": failures, "warnings": warnings}
