from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ReviewCandidate:
    source_label_id: int
    area_px: int
    centroid_x_px: float
    centroid_y_px: float
    grid_row: int
    grid_col: int
    size_bin: str


def candidate_properties(
    label_image: np.ndarray,
    min_area_px: int = 50,
    grid_rows: int = 6,
    grid_cols: int = 5,
    exclude_edges: bool = True,
) -> list[ReviewCandidate]:
    if label_image.ndim != 2:
        raise ValueError("label_image must be two-dimensional")
    height, width = label_image.shape
    flat = label_image.astype(np.int64, copy=False).ravel()
    max_label = int(flat.max(initial=0))
    counts = np.bincount(flat, minlength=max_label + 1)
    flat_indices = np.arange(flat.size, dtype=np.int64)
    x_sums = np.bincount(flat, weights=flat_indices % width, minlength=max_label + 1)
    y_sums = np.bincount(flat, weights=flat_indices // width, minlength=max_label + 1)

    edge_labels: set[int] = set()
    if exclude_edges:
        edge_labels.update(int(value) for value in np.unique(label_image[0, :]))
        edge_labels.update(int(value) for value in np.unique(label_image[-1, :]))
        edge_labels.update(int(value) for value in np.unique(label_image[:, 0]))
        edge_labels.update(int(value) for value in np.unique(label_image[:, -1]))
        edge_labels.discard(0)

    valid_labels = [
        label
        for label in range(1, max_label + 1)
        if counts[label] >= min_area_px and label not in edge_labels
    ]
    if not valid_labels:
        return []

    valid_areas = np.asarray([counts[label] for label in valid_labels], dtype=np.float64)
    lower_cut, upper_cut = np.quantile(valid_areas, [1 / 3, 2 / 3])

    rows: list[ReviewCandidate] = []
    for label in valid_labels:
        area = int(counts[label])
        centroid_x = float(x_sums[label] / area)
        centroid_y = float(y_sums[label] / area)
        grid_row = min(int(centroid_y / height * grid_rows), grid_rows - 1) + 1
        grid_col = min(int(centroid_x / width * grid_cols), grid_cols - 1) + 1
        if area <= lower_cut:
            size_bin = "small"
        elif area <= upper_cut:
            size_bin = "medium"
        else:
            size_bin = "large"
        rows.append(
            ReviewCandidate(
                source_label_id=label,
                area_px=area,
                centroid_x_px=centroid_x,
                centroid_y_px=centroid_y,
                grid_row=grid_row,
                grid_col=grid_col,
                size_bin=size_bin,
            )
        )
    return rows


def select_review_candidates(
    candidates: list[ReviewCandidate],
    count: int = 30,
    grid_rows: int = 6,
    grid_cols: int = 5,
    image_shape: tuple[int, int] = (960, 1280),
) -> list[ReviewCandidate]:
    if count <= 0:
        return []
    height, width = image_shape
    selected: list[ReviewCandidate] = []
    used: set[int] = set()
    size_cycle = ("small", "medium", "large")

    for row in range(1, grid_rows + 1):
        for col in range(1, grid_cols + 1):
            target_size = size_cycle[(len(selected)) % len(size_cycle)]
            cell_candidates = [
                item
                for item in candidates
                if item.grid_row == row and item.grid_col == col and item.source_label_id not in used
            ]
            preferred = [item for item in cell_candidates if item.size_bin == target_size]
            pool = preferred or cell_candidates
            if not pool:
                continue
            center_x = (col - 0.5) * width / grid_cols
            center_y = (row - 0.5) * height / grid_rows
            chosen = min(
                pool,
                key=lambda item: (item.centroid_x_px - center_x) ** 2 + (item.centroid_y_px - center_y) ** 2,
            )
            selected.append(chosen)
            used.add(chosen.source_label_id)
            if len(selected) == count:
                return selected

    if len(selected) < count:
        remaining = [item for item in candidates if item.source_label_id not in used]
        remaining.sort(key=lambda item: (-item.area_px, item.source_label_id))
        selected.extend(remaining[: count - len(selected)])
    return selected


def build_review_seed(label_image: np.ndarray, selected: list[ReviewCandidate]) -> np.ndarray:
    seed = np.zeros(label_image.shape, dtype=np.uint16)
    for review_id, item in enumerate(selected, start=1):
        seed[label_image == item.source_label_id] = review_id
    return seed
