"""Export the restricted read-only reference for one governed double-hit softening case.

PAOS-004B1 / PAOS-004B1R / PAOS-004B1R2. The command line accepts a case ID only - never a filesystem
path. The reference states that the package's governance integrity was verified; it is not a research
conclusion and not a human approval, so the review gate stays open for the caller.

Exit codes: 0 reference produced, 2 refused (argument refusal, unknown or invalid case ID, package
failed verification, identity mismatch, evidence unavailable, or a review state other than
needs_human), 3 unexpected internal failure. Every refusal writes one stable machine-readable code to
stderr and nothing to stdout; it never prints a traceback, the offending argument, or a local path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Run directly from the repository root without any PYTHONPATH setup: this file lives in scripts/, so
# the import root is its parent directory.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from steelai.thermal_softening_case_ref import (  # noqa: E402  (import follows the path bootstrap)
    PARSER_REFUSAL_CODES,
    REFUSAL_CODES,
    CaseReferenceError,
    build_case_reference,
)


class PathFreeArgumentParser(argparse.ArgumentParser):
    """An argument parser that never echoes what the user typed.

    argparse's default error path prints "unrecognized arguments: <raw>" and its default help path
    prints usage. Both would put caller-supplied text - possibly an absolute path - on stderr, so this
    parser suppresses its own messages and raises a path-free refusal instead.
    """

    def error(self, message: str):  # noqa: D102 - mirrors argparse's signature
        raise _ArgumentRefusal(
            "CASE_ARGUMENT_UNKNOWN" if "unrecognized" in message else "CASE_ARGUMENT_INVALID"
        )

    def exit(self, status: int = 0, message: str | None = None):  # noqa: D102
        if status == 0:
            raise _HelpRequested()
        raise _ArgumentRefusal("CASE_ARGUMENT_INVALID")

    def _print_message(self, message, file=None):  # noqa: D102
        # Suppress argparse's usage/message output entirely; main() owns everything written to stderr.
        return


class _HelpRequested(Exception):
    """The caller asked for --help."""


class _ArgumentRefusal(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_HELP_TEXT = (
    "usage: export_thermal_softening_case_ref.py <case_id>\n"
    "\n"
    "Export the restricted read-only reference for one governed double-hit softening case.\n"
    "The command takes a case ID only and never a filesystem path. Exit codes: 0 reference\n"
    "produced, 2 refused, 3 internal failure.\n"
)


def _write_refusal(code: str) -> None:
    catalog = PARSER_REFUSAL_CODES if code in PARSER_REFUSAL_CODES else REFUSAL_CODES
    sys.stderr.write(f"refused: {code} - {catalog[code]}\n")


def main(argv: list[str] | None = None, *, package_root: Path | None = None) -> int:
    """Produce the reference for one case ID.

    ``package_root`` is an internal injection point for tests only; it is never a command-line option.
    """
    parser = PathFreeArgumentParser(prog="export_thermal_softening_case_ref.py", add_help=False)
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("-h", "--help", action="store_true")
    arguments = list(sys.argv[1:] if argv is None else argv)

    try:
        parsed = parser.parse_args(arguments)
    except _HelpRequested:
        sys.stdout.write(_HELP_TEXT)
        return 0
    except _ArgumentRefusal as refusal:
        sys.stdout.write("")
        _write_refusal(refusal.code)
        return 2

    if parsed.help:
        sys.stdout.write(_HELP_TEXT)
        return 0

    if not isinstance(parsed.case_id, str) or not parsed.case_id:
        sys.stdout.write("")
        _write_refusal("CASE_ARGUMENT_INVALID")
        return 2

    try:
        reference = build_case_reference(parsed.case_id, package_root=package_root)
    except CaseReferenceError as exc:
        # Only the stable code is emitted: the governance layer's own problem text may quote a local
        # filesystem location, so it is deliberately not forwarded.
        sys.stdout.write("")
        _write_refusal(exc.code)
        return 2
    except Exception:
        # No traceback and no exception text: a failure must not leak a path by accident.
        sys.stdout.write("")
        _write_refusal("CASE_REFERENCE_INTERNAL_ERROR")
        return 3

    sys.stdout.write(json.dumps(reference, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
