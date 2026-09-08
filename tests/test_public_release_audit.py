from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steelai.public_release_audit import audit_public_candidate


class PublicReleaseAuditTests(unittest.TestCase):
    def _candidate(self) -> tuple[tempfile.TemporaryDirectory, Path, list[str]]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        paths = ["LICENSE", "README.md", "docs/ARCHITECTURE.md", "docs/KNOWN_LIMITATIONS.md"]
        for path in paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("public synthetic candidate\n", encoding="utf-8")
        return temporary, root, paths

    def test_synthetic_candidate_passes(self) -> None:
        temporary, root, paths = self._candidate()
        self.addCleanup(temporary.cleanup)

        result = audit_public_candidate(root, paths)

        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["findings"])

    def test_private_area_and_real_path_fail_closed(self) -> None:
        temporary, root, paths = self._candidate()
        self.addCleanup(temporary.cleanup)
        sensitive = root / "project_log" / "research_sessions" / "session.json"
        sensitive.parent.mkdir(parents=True, exist_ok=True)
        private_path = "C:" + "/Users/" + "researcher/private/report.xlsx"
        sensitive.write_text(f"source={private_path}\n", encoding="utf-8")

        result = audit_public_candidate(root, paths + ["project_log/research_sessions/session.json"])
        codes = {finding["code"] for finding in result["findings"]}

        self.assertEqual("failed", result["status"])
        self.assertIn("forbidden_tracked_area", codes)
        self.assertIn("absolute_windows_user_path", codes)

    def test_secret_and_model_weight_fail_closed(self) -> None:
        temporary, root, paths = self._candidate()
        self.addCleanup(temporary.cleanup)
        secret = root / "notes.txt"
        fake_secret = "sk-" + "exampleSecretValue123456789"
        secret.write_text(f"token={fake_secret}\n", encoding="utf-8")
        weight = root / "model.pt"
        weight.write_bytes(b"not a real weight")

        result = audit_public_candidate(root, paths + ["notes.txt", "model.pt"])
        codes = {finding["code"] for finding in result["findings"]}

        self.assertEqual("failed", result["status"])
        self.assertIn("openai_style_secret", codes)
        self.assertIn("credential_or_model_binary", codes)


if __name__ == "__main__":
    unittest.main()
