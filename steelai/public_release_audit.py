from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


FORBIDDEN_TRACKED_PREFIXES = (
    "approved_mappings/",
    "approved_v2/",
    "data/index/",
    "data/processed/",
    "inbox/",
    "inbox_v2/",
    "outputs/",
    "project_log/research_sessions/",
    "raw_data/",
)
FORBIDDEN_TRACKED_NAMES = {
    ".env",
    ".streamlit/secrets.toml",
    "config/settings.toml",
    "project_log/events.jsonl",
}
FORBIDDEN_SUFFIXES = {
    ".ckpt",
    ".key",
    ".onnx",
    ".pem",
    ".pfx",
    ".pt",
    ".pth",
    ".safetensors",
    ".token",
}
TEXT_FINDINGS = (
    (
        "absolute_windows_user_path",
        re.compile(r"[A-Za-z]:[\\/](?:Users|Desktop)[\\/][^\s\"'<>]+", re.IGNORECASE),
    ),
    (
        "absolute_unix_user_path",
        re.compile(r"/(?:Users|home)/[^/\s\"'<>]+/[^\s\"'<>]+"),
    ),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("openai_style_secret", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b")),
    ("china_mobile_number", re.compile(r"(?<![0-9A-Za-z])1[3-9]\d{9}(?![0-9A-Za-z])")),
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int | None = None


def _git_tracked_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return sorted(item for item in completed.stdout.decode("utf-8").split("\0") if item)


def _path_findings(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        lowered = path.lower()
        if lowered in FORBIDDEN_TRACKED_NAMES:
            findings.append(Finding("forbidden_tracked_file", path))
        if lowered.startswith(FORBIDDEN_TRACKED_PREFIXES):
            findings.append(Finding("forbidden_tracked_area", path))
        if Path(lowered).suffix in FORBIDDEN_SUFFIXES:
            findings.append(Finding("credential_or_model_binary", path))
    return findings


def _content_findings(root: Path, paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        candidate = root / path
        try:
            content = candidate.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for code, pattern in TEXT_FINDINGS:
                if pattern.search(line):
                    findings.append(Finding(code, path.replace("\\", "/"), line_number))
    return findings


def audit_public_candidate(root: Path | None = None, paths: list[str] | None = None) -> dict:
    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    tracked = paths if paths is not None else _git_tracked_files(repository)
    findings = _path_findings(tracked) + _content_findings(repository, tracked)
    required_files = ["LICENSE", "README.md", "docs/ARCHITECTURE.md", "docs/KNOWN_LIMITATIONS.md"]
    missing = [path for path in required_files if path not in tracked and not (repository / path).is_file()]
    findings.extend(Finding("missing_public_document", path) for path in missing)
    return {
        "schema_version": "1.0",
        "status": "passed" if not findings else "failed",
        "scope": "git_tracked_candidate_only",
        "tracked_file_count": len(tracked),
        "findings": [asdict(item) for item in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the Git-tracked public repository candidate.")
    parser.add_argument("--root", type=Path, default=None, help="Repository root; defaults to this package root.")
    args = parser.parse_args(argv)
    result = audit_public_candidate(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
