from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


METRICS = (
    "estimated_true_candidates",
    "candidate_coverage_percent",
    "median_equivalent_diameter_um",
    "adjusted_density_per_1000_um2",
    "D10_um",
    "D90_um",
)


def bootstrap_mean_difference(
    values_b: list[float],
    values_r: list[float],
    iterations: int = 10_000,
    seed: int = 20260811,
) -> dict[str, float]:
    if not values_b or not values_r:
        return {"r_minus_b": float("nan"), "ci95_low": float("nan"), "ci95_high": float("nan")}
    b = np.asarray(values_b, dtype=float)
    r = np.asarray(values_r, dtype=float)
    rng = np.random.default_rng(seed)
    b_means = rng.choice(b, size=(iterations, len(b)), replace=True).mean(axis=1)
    r_means = rng.choice(r, size=(iterations, len(r)), replace=True).mean(axis=1)
    differences = r_means - b_means
    return {
        "r_minus_b": round(float(r.mean() - b.mean()), 6),
        "ci95_low": round(float(np.quantile(differences, 0.025)), 6),
        "ci95_high": round(float(np.quantile(differences, 0.975)), 6),
    }


def summarize_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("status", "")).startswith("in_standard"):
            groups[str(row["steel"])].append(row)

    summary: dict[str, Any] = {"n_images": {steel: len(groups.get(steel, [])) for steel in ("B", "R")}}
    metric_summary: dict[str, Any] = {}
    for metric in METRICS:
        b_values = [float(row[metric]) for row in groups.get("B", [])]
        r_values = [float(row[metric]) for row in groups.get("R", [])]
        b_mean = float(np.mean(b_values)) if b_values else float("nan")
        r_mean = float(np.mean(r_values)) if r_values else float("nan")
        percent = (r_mean - b_mean) / b_mean * 100 if b_values and b_mean != 0 else float("nan")
        metric_summary[metric] = {
            "B_mean": round(b_mean, 6),
            "B_median": round(float(np.median(b_values)), 6) if b_values else float("nan"),
            "R_mean": round(r_mean, 6),
            "R_median": round(float(np.median(r_values)), 6) if r_values else float("nan"),
            "R_vs_B_percent": round(float(percent), 3),
            "bootstrap_mean_difference": bootstrap_mean_difference(b_values, r_values),
        }
    summary["metrics"] = metric_summary
    summary["interpretation_boundary"] = (
        "Bootstrap intervals use images as independent units. Object-level rows are descriptive only and are not "
        "treated as independent experimental replicates."
    )
    return summary
