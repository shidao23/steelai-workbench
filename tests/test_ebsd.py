from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steelai.ebsd import build_pilot_config, read_ctf_header, read_ebsd_status, write_ebsd_status


class EbsdTests(unittest.TestCase):
    def test_ctf_header_parser(self) -> None:
        content = """Channel Text File
XCells\t800
YCells\t599
XStep\t0.15
YStep\t0.15
Euler angles refer to Sample Coordinate system (CS0)!\tMag\t2005\tCoverage\t84.81\tKV\t20\tTiltAngle\t70
Phases\t2
3.6;3.6;3.6\t90;90;90\tIron fcc\t11\t225
2.86;2.86;2.86\t90;90;90\tIron bcc (old)\t11\t229
Phase\tX\tY\tBands\tError\tEuler1\tEuler2\tEuler3\tMAD\tBC\tBS
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.ctf"
            path.write_text(content, encoding="utf-8")
            metadata = read_ctf_header(path)
        self.assertEqual(metadata["x_cells"], 800)
        self.assertEqual(metadata["phases"], ["Iron fcc", "Iron bcc (old)"])
        self.assertAlmostEqual(metadata["coverage_percent"], 84.81)

    def test_status_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            write_ebsd_status({"status": "running", "pid": 42}, path)
            self.assertEqual(read_ebsd_status(path)["status"], "running")

    def test_pilot_config_has_scientific_guardrails(self) -> None:
        config = build_pilot_config()
        self.assertTrue(config["raw_files_read_only"])
        self.assertFalse(config["parent_reconstruction_enabled"])
        self.assertEqual(config["analysis_scope"], "basic_ebsd_pilot")


if __name__ == "__main__":
    unittest.main()
