import tempfile
import unittest
from pathlib import Path

from steelai.model_lab import micro_sam_status, scan_sem_directory, select_balanced_pilot


class ModelLabTests(unittest.TestCase):
    def test_scan_and_balanced_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for steel in ("B", "R"):
                for number in range(1, 7):
                    stem = f"{steel}-DQ-1-{number:02d}"
                    (root / f"{stem}.TIF").write_bytes(b"test")
                    (root / f"{stem}-TIF.hdr").write_text(
                        "[MAIN]\nMagnification=1000\nPixelSizeX=0.00000025\n",
                        encoding="utf-8",
                    )

            rows = scan_sem_directory(root)
            selected = select_balanced_pilot(rows)

            self.assertEqual(len(rows), 12)
            self.assertEqual(len(selected), 10)
            self.assertEqual(sum(row["steel"] == "B" for row in selected), 5)
            self.assertEqual(sum(row["steel"] == "R" for row in selected), 5)
            self.assertAlmostEqual(float(selected[0]["pixel_size_um"]), 0.25)

    def test_micro_sam_status_contract(self):
        status = micro_sam_status()
        self.assertIn("environment_ready", status)
        self.assertIn("checkpoint_ready", status)
        self.assertIn("smoke_test_ready", status)
        self.assertIn("conda_environment_ready", status)
        self.assertIn("report_path", status)


if __name__ == "__main__":
    unittest.main()
