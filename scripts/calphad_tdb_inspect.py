"""Read-only inspector for a local CALPHAD TDB file (T86 phase-2 provenance and gates).

This tool never edits, rewrites, normalises or "fixes" a database.  It only reports what the
file actually contains, so that a compatibility decision can be recorded against the exact
file hash.  It runs in the main Workbench interpreter and does not import pycalphad.

TDB statements are terminated by ``!``; the first token of a statement is its command keyword.
Reporting the keywords that fall outside pycalphad 0.11.2's recognised set is the evidence
needed for the second compatibility gate; nothing is removed or rewritten here.

Usage:
    .\\.venv\\Scripts\\python.exe -B scripts\\calphad_tdb_inspect.py <tdb> [--json <out.json>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


#: Thermo-Calc TDB keywords recognised by pycalphad 0.11.2
#: (from pycalphad/io/tdb_keywords.py at tag 0.11.2, which cites the Thermo-Calc Database
#: Manager's Guide).  Used only to *report* which commands fall outside that set.
PYCALPHAD_TDB_KEYWORDS = {
    "ELEMENT", "SPECIES", "PHASE", "CONSTITUENT", "ADD_CONSTITUENT", "COMPOUND_PHASE",
    "ALLOTROPIC_PHASE", "TEMPERATURE_LIMITS", "DEFINE_SYSTEM_DEFAULT", "DEFAULT_COMMAND",
    "DATABASE_INFORMATION", "TYPE_DEFINITION", "FTP_FILE", "FUNCTION", "PARAMETER",
    "OPTIONS", "TABLE", "ASSESSED_SYSTEMS", "REFERENCE_FILE", "LIST_OF_REFERENCES",
    "ADD_REFERENCE", "CASE", "ENDCASE", "VERSION_DATA", "VERSION_DATE", "DIFFUSION",
    "ZEROVOLUME_SPECIES", "AMEND_PHASE_DESCRIPTION", "DEFINE_ELEMENTS", "TEMP-LIM",
}

#: MatCalc extensions that matter for the second gate.  Reported with counts and examples
#: so the effect of each one can be examined; never stripped.
MATCALC_EXTENSIONS = (
    "REFERENCE_ELEMENT",
    "ADD_COMPOSITION_SET",
    "ATTACH_CONTRIBUTION",
    "CREATE_NEW_PHASE",
    "ALTER_PHASE",
    "ADD_PHASE",
)

COMMAND = re.compile(r"^([A-Za-z][A-Za-z0-9_\-]*)")
#: Reference records inside LIST_OF_REFERENCES appear as bare keys on their own "statement".
REFERENCE_RECORD = re.compile(r"^[A-Z]\d")


def command_keyword(statement: str) -> str:
    match = COMMAND.match(statement)
    if not match:
        return ""
    return match.group(1).upper()


def is_recognised(keyword: str) -> bool:
    """True for exact pycalphad keywords and for Thermo-Calc abbreviations of them.

    Thermo-Calc (and pycalphad's ``expand_keyword``) accept abbreviated commands such as
    ``CONST`` for CONSTITUENT or ``PARAM`` for PARAMETER, so a prefix match is treated as
    recognised.  Anything else is reported as a non-pycalphad command.
    """
    if keyword in PYCALPHAD_TDB_KEYWORDS:
        return True
    return any(candidate.startswith(keyword) for candidate in PYCALPHAD_TDB_KEYWORDS)


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", raw, 0, 1, "undecodable")


def statements(lines: list[str]) -> list[tuple[int, str]]:
    """Return (start_line, statement_text) for every ``!``-terminated TDB statement."""
    result: list[tuple[int, str]] = []
    pending = ""
    start = 0
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("$"):
            continue
        if not pending:
            start = number
            pending = stripped
        else:
            pending += " " + stripped
        while "!" in pending:
            head, _, rest = pending.partition("!")
            text = head.strip()
            if text:
                result.append((start, text))
            pending = rest.strip()
            start = number
    if pending.strip():
        result.append((start, pending.strip()))
    return result


def inspect(path: Path) -> dict[str, Any]:
    text, encoding = read_text(path)
    raw = path.read_bytes()
    lines = text.splitlines()
    parsed = statements(lines)

    elements: list[str] = []
    phases: list[dict[str, Any]] = []
    temperature_limits: list[str] = []
    version_lines: list[str] = []
    type_definitions: list[dict[str, Any]] = []
    unknown: dict[str, dict[str, Any]] = {}
    extensions: dict[str, dict[str, Any]] = {}
    comment_temperature_lines: list[str] = []

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("$") and ("TEMPERATURE:" in stripped.upper() or "T-LIMIT" in stripped.upper()):
            comment_temperature_lines.append(f"{number}: {stripped[:160]}")

    for start, statement in parsed:
        keyword = command_keyword(statement)
        if not keyword:
            continue
        head = statement.split()[1] if len(statement.split()) > 1 else ""

        if keyword == "ELEMENT":
            elements.append(head.upper())
        elif keyword == "PHASE":
            parts = statement.split()
            phases.append({
                "line": start,
                "name": parts[1].upper() if len(parts) > 1 else "",
                "options": parts[2] if len(parts) > 2 and not parts[2].isdigit() else "",
            })
        elif keyword == "TEMPERATURE_LIMITS":
            temperature_limits.append(f"{start}: {statement[:120]}")
        elif keyword in {"VERSION_DATE", "VERSION_DATA", "DATABASE_INFORMATION"}:
            version_lines.append(f"{start}: {statement[:160]}")
        elif keyword == "TYPE_DEFINITION":
            type_definitions.append({
                "line": start,
                "has_if_then": bool(re.search(r"\bIF\b", statement.upper()) and re.search(r"\bTHEN\b", statement.upper())),
                "text": statement[:200],
            })

        if not is_recognised(keyword) and not REFERENCE_RECORD.match(keyword):
            bucket = unknown.setdefault(keyword, {"count": 0, "first_line": start, "examples": []})
            bucket["count"] += 1
            if len(bucket["examples"]) < 3:
                bucket["examples"].append(f"{start}: {statement[:180]}")
        if keyword in MATCALC_EXTENSIONS:
            bucket = extensions.setdefault(keyword, {"count": 0, "first_line": start, "examples": []})
            bucket["count"] += 1
            if len(bucket["examples"]) < 5:
                bucket["examples"].append(f"{start}: {statement[:180]}")

    alloy_elements = sorted(element for element in set(elements) if element not in {"VA", "/-"})
    phase_names = [item["name"] for item in phases]
    base_phases = sorted({name.split("#")[0] for name in phase_names if name})
    return {
        "schema_version": "1.0",
        "path": str(path),
        "filename": path.name,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding_detected": encoding,
        "line_count": len(lines),
        "statement_count": len(parsed),
        "elements": sorted(set(elements)),
        "alloy_elements": alloy_elements,
        "alloy_element_count": len(alloy_elements),
        "phase_line_count": len(phases),
        "base_phases": base_phases,
        "base_phase_count": len(base_phases),
        "phases": phases,
        "temperature_limits": temperature_limits,
        "comment_temperature_lines": comment_temperature_lines,
        "version_lines": version_lines[:10],
        "type_definition_count": len(type_definitions),
        "type_definitions_with_if_then": [item for item in type_definitions if item["has_if_then"]],
        "type_definitions": type_definitions,
        "matcalc_extensions": {key: extensions[key] for key in sorted(extensions)},
        "non_pycalphad_keywords": {key: unknown[key] for key in sorted(unknown)},
        "non_pycalphad_keyword_total": sum(item["count"] for item in unknown.values()),
        "pycalphad_keyword_source": "pycalphad/io/tdb_keywords.py @ tag 0.11.2",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read-only inspector for a CALPHAD TDB file.")
    parser.add_argument("tdb", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    if not args.tdb.is_file():
        print(f"not a file: {args.tdb}", file=sys.stderr)
        return 2

    report = inspect(args.tdb)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"file        : {report['filename']}")
    print(f"size        : {report['size_bytes']} bytes")
    print(f"sha256      : {report['sha256']}")
    print(f"encoding    : {report['encoding_detected']}  lines: {report['line_count']}  statements: {report['statement_count']}")
    print(f"elements({report['alloy_element_count']} alloy): {', '.join(report['alloy_elements'])}")
    print(f"phases      : {report['base_phase_count']} base, {report['phase_line_count']} PHASE statements")
    print(f"temperature : {report['temperature_limits'] or 'no TEMPERATURE_LIMITS command'}")
    for line in report["comment_temperature_lines"]:
        print(f"  comment   : {line}")
    print(f"type_defs   : {report['type_definition_count']} (IF/THEN: {len(report['type_definitions_with_if_then'])})")
    print(f"MatCalc extensions: {report['matcalc_extensions'] or 'none found'}")
    print(f"non-pycalphad commands: {report['non_pycalphad_keyword_total']} occurrences "
          f"across {len(report['non_pycalphad_keywords'])} keywords")
    for keyword, info in report["non_pycalphad_keywords"].items():
        print(f"  {keyword:<24} x{info['count']:<5} first line {info['first_line']}")
        for example in info["examples"][:1]:
            print(f"      {example}")
    if args.json:
        print(f"json        : {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
