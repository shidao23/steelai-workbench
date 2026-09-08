from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steelai.public_workspace import prepare_public_workspace


class PublicWorkspaceTests(unittest.TestCase):
    def _root(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        processed = root / "data" / "examples" / "processed"
        index = root / "data" / "examples" / "index"
        processed.mkdir(parents=True)
        index.mkdir(parents=True)
        (processed / "samples.csv").write_text("sample_id\nSYN-B\n", encoding="utf-8")
        (index / "evidence_index.csv").write_text("sample_id\nSYN-B\n", encoding="utf-8")
        return temporary, root

    def test_creates_and_reuses_public_synthetic_workspace(self) -> None:
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)

        created = prepare_public_workspace(root)
        reused = prepare_public_workspace(root)

        self.assertEqual("public_synthetic_only", created["data_classification"])
        self.assertEqual({"created"}, {item["status"] for item in created["files"]})
        self.assertEqual({"reused"}, {item["status"] for item in reused["files"]})

    def test_refuses_to_overwrite_local_data(self) -> None:
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        target = root / "data" / "processed" / "samples.csv"
        target.parent.mkdir(parents=True)
        target.write_text("local research data\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            prepare_public_workspace(root)


if __name__ == "__main__":
    unittest.main()
