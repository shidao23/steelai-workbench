"""Build and verify a read-only double-hit analysis case from approved data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from steelai.governance import verify_package
from steelai.thermal_softening_case import build_softening_case, publish_softening_case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--literature-pdf", required=True, type=Path)
    args = parser.parse_args()
    case = build_softening_case(literature_pdf=args.literature_pdf)
    destination = publish_softening_case(case)
    verification = verify_package(destination)
    print(json.dumps({
        "case_id": case["case_id"],
        "status": case["status"],
        "row_count": case["row_count"],
        "warning_ids": case["warning_ids"],
        "package_verification": verification.status,
        "package": str(destination),
        "draft": str(destination / "analysis_draft.md"),
    }, ensure_ascii=False, indent=2))
    return 0 if verification.status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
