import unittest

import numpy as np

from steelai.review_sampling import build_review_seed, candidate_properties, select_review_candidates


class ReviewSamplingTests(unittest.TestCase):
    def test_spatial_review_seed_has_unique_labels(self):
        labels = np.zeros((60, 50), dtype=np.uint32)
        source_label = 1
        for row in range(6):
            for col in range(5):
                y = row * 10 + 2
                x = col * 10 + 2
                labels[y : y + 6, x : x + 6] = source_label
                source_label += 1

        candidates = candidate_properties(labels, min_area_px=20, grid_rows=6, grid_cols=5)
        selected = select_review_candidates(candidates, count=30, image_shape=labels.shape)
        seed = build_review_seed(labels, selected)

        self.assertEqual(len(selected), 30)
        self.assertEqual(set(np.unique(seed)), set(range(31)))
        self.assertEqual(int(np.count_nonzero(seed)), 30 * 36)


if __name__ == "__main__":
    unittest.main()
