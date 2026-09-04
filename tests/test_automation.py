from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steelai.automation import read_job_status, read_log_tail, write_status


class AutomationTests(unittest.TestCase):
    def test_status_round_trip_and_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_path = root / "status.json"
            log_path = root / "job.log"
            write_status({"status": "running", "pid": 123}, status_path)
            status = read_job_status(status_path)
            self.assertEqual(status["status"], "running")
            log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")
            self.assertEqual(read_log_tail(log_path, max_lines=2), "two\nthree")


if __name__ == "__main__":
    unittest.main()
