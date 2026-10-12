"""STEEL-V1 (S3) - CLI for the restricted structured case snapshot.

Accepts EXACTLY one argument: a valid case ID. No package root, no file path, no environment
variable root override, no field selection. Every export re-verifies the governed package and
only emits the frozen path-free snapshot JSON on stdout.

Exit codes: 0 snapshot emitted | 2 governed refusal (stable, path-free code on stderr)
| 3 usage error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from steelai.thermal_softening_case_snapshot import build_case_snapshot  # noqa: E402
from steelai.thermal_softening_case_ref import CaseReferenceError  # noqa: E402


class _PathFreeParserError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if len(argv) != 1 or argv[0] in {"-h", "--help"}:
        # Never echo the offending command line (same discipline as the export/ref CLI).
        print("CASE_ARGUMENT_INVALID: the command line is not a single case ID", file=sys.stderr)
        return 3 if len(argv) != 1 else 0
    try:
        snapshot = build_case_snapshot(argv[0])
    except CaseReferenceError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 2
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
