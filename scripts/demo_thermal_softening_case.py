"""One-command OFFLINE synthetic demo for the governed double-hit softening case chain.

STEEL-V1-03B. This script is a PUBLIC, reviewable demo entry: it builds a FIXED, fully
synthetic input (no measurement, no literature, no cloud model, no PAOS), publishes it
through the SAME governed pipeline as a real case (`publish_softening_case` with the
explicit default-off `synthetic_demo=True` branch), verifies the sealed package with the
governance core's own `verify_package`, and reports the case id, the verification status
and the demo-root-relative result locations.

Everything the demo prints stays labelled as a synthetic demo and a non-scientific
conclusion. The Manifest is classified `synthetic_demo_data`, its sources are
`synthetic_demo_input` (never `human_approved` real research data), and the package can
never enter the formal evidence library (`outputs/thermal_softening_cases` is refused for
demo publishes).

Exit codes: 0 demo published or reused and verified | 2 governed refusal | 3 usage error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

#: A public CLI must run from the repository root with one command; direct script execution puts
#: scripts/ (not the repo root) on sys.path, so bootstrap it before importing the package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from steelai.governance import digest_value, verify_package
from steelai.paths import OUTPUTS
from steelai.thermal_softening_case import publish_softening_case

DEMO_VERSION = "SteelAI-Thermal-Softening-Demo-v1"
DEFAULT_DEMO_ROOT = OUTPUTS / "synthetic_demo" / "thermal_softening_cases"

#: The FIXED, reviewable synthetic input. Every number in the demo package traces back to
#: exactly these rows; nothing is sampled, randomised or fetched.
_SYNTHETIC_ROWS: tuple[dict[str, Any], ...] = (
    {
        "acquisition_id": "D1", "sample_id": "B-DEMO", "temperature_c": 1000.0,
        "deformation_gap_s": 10.0, "primary_percent": 48.0, "sensitivity_percent": 44.0,
        "qc_status": "passed", "qc_flags": [],
    },
    {
        "acquisition_id": "D2", "sample_id": "R-DEMO", "temperature_c": 1000.5,
        "deformation_gap_s": 9.5, "primary_percent": 61.0, "sensitivity_percent": 58.0,
        "qc_status": "passed", "qc_flags": [],
    },
    {
        "acquisition_id": "D3", "sample_id": "B-DEMO", "temperature_c": 1100.0,
        "deformation_gap_s": 30.0, "primary_percent": 130.0, "sensitivity_percent": 95.0,
        "qc_status": "warning_needs_human_review",
        "qc_flags": ["primary_softening_outside_0_to_1"],
    },
)

_SYNTHETIC_DIGEST_PARTS = (
    "runs_sha256", "points_sha256", "features_sha256",
    "formal_results_sha256", "method_registry_sha256", "literature_pdf_sha256",
)


def build_synthetic_demo_case() -> dict[str, Any]:
    """Derive the demo case (and its stable id) from the fixed synthetic input."""
    canonical_input = {"version": DEMO_VERSION, "rows": list(_SYNTHETIC_ROWS)}
    source_digests = {
        part: digest_value({"input": canonical_input, "part": part})
        for part in _SYNTHETIC_DIGEST_PARTS
    }
    warning_ids = [row["acquisition_id"] for row in _SYNTHETIC_ROWS
                   if row["qc_status"] != "passed"]
    return {
        "schema_version": "1.0",
        "case_version": DEMO_VERSION,
        "case_id": "TSC-" + digest_value(
            {"version": DEMO_VERSION, "sources": source_digests}
        )[:20].upper(),
        "status": "analysis_draft_needs_human_review",
        "source_digests": source_digests,
        "row_count": len(_SYNTHETIC_ROWS),
        "passed_count": len(_SYNTHETIC_ROWS) - len(warning_ids),
        "warning_ids": warning_ids,
        "large_method_difference_passed_ids": [],
        "observations": {},
        "rows": [dict(row) for row in _SYNTHETIC_ROWS],
    }


class _PathFreeArgumentParser(argparse.ArgumentParser):
    """Never echo caller input in an error (same discipline as the export CLI)."""

    def error(self, message: str):  # noqa: D102 - mirrors argparse's signature
        raise SystemExit(3)


def main(argv: list[str] | None = None) -> int:
    parser = _PathFreeArgumentParser(add_help=True, description=__doc__)
    parser.add_argument(
        "--output-root", default=None, type=str,
        help="demo output root (optional); never the formal evidence library",
    )
    args = parser.parse_args(argv)

    demo_root = DEFAULT_DEMO_ROOT
    if args.output_root is not None:
        demo_root = Path(args.output_root)
        if demo_root.resolve() == OUTPUTS.resolve() / "thermal_softening_cases":
            # The formal library check inside publish would also refuse; refuse here too so the
            # message never needs to quote the caller's path.
            print("DEMO_REFUSED: the formal evidence library is not a demo output root", file=sys.stderr)
            return 2

    case = build_synthetic_demo_case()
    destination = demo_root / case["case_id"]
    reused = destination.exists()
    try:
        publish_softening_case(case, output_root=demo_root, synthetic_demo=True)
    except ValueError as exc:
        print(f"DEMO_REFUSED: {exc}", file=sys.stderr)
        return 2

    verification = verify_package(destination)
    if verification.status != "passed":
        print(f"DEMO_REFUSED: published package failed verification ({verification.status})", file=sys.stderr)
        return 2

    print("SteelAI 合成演示（synthetic_demo_data）：以下结果全部来自固定合成输入。")
    print("非真实测量、非科研结论；未调用云模型；未接 PAOS。")
    print(f"case_id: {case['case_id']}")
    print(f"verification: {verification.status}")
    print(f"reused: {'true' if reused else 'false'}")
    print("demo_root 相对结果位置：")
    print("  analysis_draft.md")
    print("  evidence.json")
    print("  manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
