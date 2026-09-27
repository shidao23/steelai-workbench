"""T86 phase-2 compatibility gates for a MatCalc TDB under pycalphad 0.11.2.

Runs in the **isolated** interpreter (`.venv-pycalphad`) as:

    .\\.venv-pycalphad\\Scripts\\python.exe -I scripts\\calphad_compatibility_gate.py <tdb> [--json out.json]

Gate 1: can ``pycalphad.Database`` parse the raw vendor file, and if not, what is the exact
        exception, line and keyword?  The file is never modified.
Gate 2: what do the MatCalc-only commands (``REFERENCE_ELEMENT``, ``ADD_COMPOSITION_SET``,
        ``ATTACH_CONTRIBUTION``) do to the parsed model — phase list, composition sets,
        order/disorder linkage and the carbide/nitride phases — given that pycalphad does not
        implement them?

The output is evidence for a decision; a successful parse is **not** evidence of numerical
validity, which is why the structural checks are reported separately.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
import warnings
from pathlib import Path
from typing import Any


#: Phase names whose presence matters for a low-alloy steel carbide/nitride discussion.
CARBIDE_NITRIDE_HINTS = (
    "CEMENTITE", "M7C3", "M23C6", "M6C", "M3C2", "V3C2", "WC", "MC", "M2P", "M3P",
    "ALN", "BN", "ZET", "FCC_A1", "HCP_A3", "M2B", "TIB2", "SIGMA", "LAVES", "MU_PHASE",
)


def _error_location(exc: BaseException) -> dict[str, Any]:
    location: dict[str, Any] = {}
    for attr, key in (("lineno", "line"), ("col", "column"), ("line", "line"), ("column", "column")):
        value = getattr(exc, attr, None)
        if value is not None and key not in location:
            location[key] = value
    return location


#: Minimal, syntactically valid TDB used to isolate the effect of one extension command at a
#: time.  This is an in-memory parser probe only: it is never written to disk, it contains no
#: vendor database content, and no equilibrium calculation is run with it.
_PROBE_BASELINE = """ELEMENT VA VACUUM 0 0 0 !
ELEMENT FE BCC_A2 55.845 4489 27.28 !
ELEMENT C GRAPHITE 12.011 1054 5.74 !
PHASE BCC_A2 % 2 1 3 !
CONSTITUENT BCC_A2 :FE:C: !
PARAMETER G(BCC_A2,FE:C;0) 298.15 0; 6000 N !
"""

_PROBE_COMMANDS = {
    "REFERENCE_ELEMENT": "REFERENCE_ELEMENT FE !",
    "ADD_COMPOSITION_SET": "ADD_COMPOSITION_SET BCC_A2 :FE:C: !",
    "ATTACH_CONTRIBUTION": "ATTACH_CONTRIBUTION BCC_B2 BCC_A2 ORDER_DISORDER !",
    "CREATE_NEW_PHASE": "CREATE_NEW_PHASE BCC_B2 3 0.5 0.5 3 !",
    "HMVA_parameter_type": "PARAMETER HMVA(BCC_A2,FE:C;0) 298.15 0; 6000 N !",
}


def keyword_probe() -> dict[str, Any]:
    """Feed each MatCalc-only command to pycalphad in isolation (synthetic, in-memory only)."""
    from pycalphad import Database

    results: dict[str, Any] = {}
    try:
        Database.from_string(_PROBE_BASELINE, fmt="tdb")
        results["_baseline"] = {"status": "passed", "detail": "minimal probe database parses"}
    except Exception as exc:  # noqa: BLE001
        results["_baseline"] = {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
        return {"probe_note": "baseline probe failed; per-keyword results are not interpretable", "results": results}

    for name, command in _PROBE_COMMANDS.items():
        text = _PROBE_BASELINE + command + "\n"
        try:
            Database.from_string(text, fmt="tdb")
            results[name] = {"status": "passed", "command": command}
        except Exception as exc:  # noqa: BLE001
            results[name] = {
                "status": "failed",
                "command": command,
                "exception_type": type(exc).__name__,
                "exception_module": type(exc).__module__,
                "message": str(exc).replace("\n", " | ")[:400],
                "location": _error_location(exc),
            }
    return {
        "probe_note": (
            "Synthetic in-memory probe of pycalphad's TDB grammar. No vendor database content, "
            "no file write, no equilibrium calculation."
        ),
        "results": results,
    }


def _non_ascii_report(tdb: Path) -> dict[str, Any]:
    """Locate the bytes that break locale-default decoding, without changing the file."""
    raw = tdb.read_bytes()
    bad_offsets = [index for index, byte in enumerate(raw) if byte > 0x7F]
    text = raw.decode("cp1252", errors="replace")
    line_starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            line_starts.append(index + 1)
    first = None
    if bad_offsets:
        offset = bad_offsets[0]
        line_number = 1
        for candidate, start in enumerate(line_starts, 1):
            if start <= offset:
                line_number = candidate
            else:
                break
        line = text.splitlines()[line_number - 1] if line_number <= len(text.splitlines()) else ""
        first = {
            "first_non_ascii_offset": offset,
            "first_non_ascii_byte": f"0x{raw[offset]:02x}",
            "cp1252_character": raw[offset:offset + 1].decode("cp1252", errors="replace"),
            "line_number": line_number,
            "line_text": line.strip()[:160],
        }
    return {
        "non_ascii_byte_count": len(bad_offsets),
        "decodes_as_utf8": _try_utf8(raw),
        "decodes_as_cp1252": True,
        "first_non_ascii": first,
    }


def _try_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def gate1_parse(tdb: Path) -> dict[str, Any]:
    """Try the raw, unmodified file through each documented pycalphad load path."""
    from pycalphad import Database

    raw = tdb.read_bytes()
    detected = "utf-8"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        detected = "cp1252"

    attempts: list[dict[str, Any]] = []
    databases: dict[str, Any] = {}

    def attempt(label: str, loader) -> None:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                dbf = loader()
                record = {
                    "method": label,
                    "status": "passed",
                    "warnings": [f"{item.category.__name__}: {item.message}" for item in caught],
                }
            databases[label] = dbf
        except Exception as exc:  # noqa: BLE001 - the exact failure is the deliverable
            record = {
                "method": label,
                "status": "failed",
                "exception_type": type(exc).__name__,
                "exception_module": type(exc).__module__,
                "message": str(exc),
                "location": _error_location(exc),
                "traceback_tail": traceback.format_exc().splitlines()[-6:],
            }
        attempts.append(record)

    # 1. The vendor file exactly as published, through pycalphad's normal path.
    attempt("Database(path) - platform default encoding", lambda: Database(str(tdb)))
    # 2. Same bytes, decoded with the encoding the file actually uses (pycalphad's documented
    #    file-like entry point).  No byte of the database is changed.
    attempt(
        f"Database.from_file(open(path, encoding='{detected}'), fmt='tdb')",
        lambda: Database.from_file(open(tdb, encoding=detected), fmt="tdb"),
    )
    # 3. Same bytes as text (what a caller with an explicit encoding would pass).
    attempt(
        f"Database.from_string({detected} text, fmt='tdb')",
        lambda: Database.from_string(raw.decode(detected), fmt="tdb"),
    )

    raw_status = attempts[0]["status"]
    return {
        "raw_file_status": raw_status,
        "detected_encoding": detected,
        "attempts": attempts,
        "databases": databases,
        "encoding_diagnostics": _non_ascii_report(tdb),
    }


def select_database(parsed: dict[str, Any]) -> tuple[str, Any] | tuple[None, None]:
    for attempt in parsed["attempts"]:
        if attempt["status"] == "passed":
            return attempt["method"], parsed["databases"][attempt["method"]]
    return None, None


def gate2_structure(dbf: Any, tdbfacts: dict[str, Any] | None = None) -> dict[str, Any]:
    phase_names = sorted(str(name) for name in dbf.phases.keys())
    upper = {name.upper(): name for name in phase_names}
    hints: dict[str, dict[str, Any]] = {}
    ordered_links: list[dict[str, str]] = []
    for name in phase_names:
        phase = dbf.phases[name]
        model_hints = dict(getattr(phase, "model_hints", {}) or {})
        if model_hints:
            hints[name] = {key: (value if isinstance(value, (str, int, float, bool)) else str(value))
                           for key, value in model_hints.items()}
        if "ordered_phase" in model_hints or "disordered_phase" in model_hints:
            ordered_links.append({
                "phase": name,
                "ordered_phase": str(model_hints.get("ordered_phase", "")),
                "disordered_phase": str(model_hints.get("disordered_phase", "")),
            })

    interest = {name: name in upper for name in CARBIDE_NITRIDE_HINTS}
    present_interest = sorted(name for name, found in interest.items() if found)
    missing_interest = sorted(name for name, found in interest.items() if not found)

    reference_states = {}
    for element, ref in (getattr(dbf, "refstates", {}) or {}).items():
        try:
            reference_states[str(element)] = {"phase": str(ref.get("phase", "")), "mass": float(ref.get("mass", 0.0))}
        except (TypeError, ValueError):
            reference_states[str(element)] = {"phase": str(ref.get("phase", ""))}

    temperature_limits = getattr(dbf, "temperature_limits", None)

    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    # BCC_B2 / BCC_A2 order-disorder linkage.  MatCalc expresses this with
    # ATTACH_CONTRIBUTION; pycalphad only creates these hints from TYPE_DEFINITION ... DIS_PART.
    bcc_b2_hint = hints.get("BCC_B2", {})
    bcc_a2_hint = hints.get("BCC_A2", {})
    if "ordered_phase" in bcc_b2_hint or "disordered_phase" in bcc_b2_hint:
        add("bcc_b2_order_disorder_link", "passed", f"BCC_B2 hints: {bcc_b2_hint}")
    else:
        add(
            "bcc_b2_order_disorder_link",
            "failed",
            "pycalphad did not link BCC_B2 to a disordered part. MatCalc's "
            "ATTACH_CONTRIBUTION ... ORDER_DISORDER is not implemented by pycalphad, so any "
            "ordered-B2 contribution is not applied as the database intends.",
        )
    if bcc_a2_hint:
        add("bcc_a2_hints", "passed", f"BCC_A2 hints: {bcc_a2_hint}")
    else:
        add("bcc_a2_hints", "warning", "BCC_A2 carries no model hints after parsing.")

    # Composition sets: MatCalc's ADD_COMPOSITION_SET creates phases such as fcc_A1#01.
    composition_set_phases = [name for name in phase_names if "#" in name]
    declared_sets = (tdbfacts or {}).get("matcalc_extensions", {}).get("ADD_COMPOSITION_SET", {}).get("count", 0)
    if composition_set_phases:
        add("matcalc_composition_sets", "passed", f"parsed composition-set phases: {composition_set_phases}")
    else:
        add(
            "matcalc_composition_sets",
            "failed",
            f"{declared_sets} ADD_COMPOSITION_SET commands in the file produced no separate phase in "
            "pycalphad. Carbides/nitrides that MatCalc models as composition sets (for example the MC "
            "carbo-nitride as fcc_A1#01) are therefore not reachable as separate phases.",
        )

    # Carbide / nitride availability.
    if present_interest:
        add("carbide_nitride_phases", "passed", f"present: {present_interest}")
    add("carbide_nitride_absent", "warning", f"not defined as standalone phases: {missing_interest}")

    if temperature_limits:
        add("temperature_limits", "passed", f"pycalphad temperature_limits: {temperature_limits}")
    else:
        add(
            "temperature_limits",
            "warning",
            "the database has no TEMPERATURE_LIMITS command, so pycalphad enforces no range; the "
            "vendor's assessed range lives only in header comments and must be registered by the caller.",
        )

    if reference_states:
        add("reference_states", "passed", f"{len(reference_states)} element reference states parsed")
    else:
        add("reference_states", "warning", "no element reference states parsed")

    return {
        "gate": 2,
        "status": "passed" if all(item["status"] == "passed" for item in checks[:3]) else "failed",
        "phase_count": len(phase_names),
        "phases": phase_names,
        "model_hints": hints,
        "order_disorder_links": ordered_links,
        "matcalc_composition_set_phases": composition_set_phases,
        "carbide_nitride_present": present_interest,
        "carbide_nitride_absent": missing_interest,
        "elements": sorted(str(element) for element in dbf.elements),
        "species_count": len(getattr(dbf, "species", []) or []),
        "parameter_count": len(getattr(dbf, "_parameters", []) or []),
        "reference_states": reference_states,
        "checks": checks,
    }


def main(argv: list[str]) -> int:
    # Console output may be a GBK terminal while the database contains UTF-8 characters.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="T86 phase-2 pycalphad compatibility gates.")
    parser.add_argument("tdb", type=Path)
    parser.add_argument("--tdb-facts", type=Path, default=None, help="JSON from calphad_tdb_inspect.py")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    if not args.tdb.is_file():
        print(f"not a file: {args.tdb}", file=sys.stderr)
        return 2

    facts = None
    if args.tdb_facts and args.tdb_facts.is_file():
        facts = json.loads(args.tdb_facts.read_text(encoding="utf-8"))

    from importlib import metadata

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "tdb": str(args.tdb),
        "pycalphad_version": metadata.version("pycalphad"),
        "python_version": sys.version.split()[0],
    }
    parsed = gate1_parse(args.tdb)
    loaded_via, database = select_database(parsed)
    report["gate1"] = {
        "raw_file_status": parsed["raw_file_status"],
        "attempts": parsed["attempts"],
        "encoding_diagnostics": parsed["encoding_diagnostics"],
        "loaded_via": loaded_via,
    }
    report["keyword_probe"] = keyword_probe()
    if database is None:
        report["overall"] = "blocked_gate1_parse_failed"
    else:
        gate2 = gate2_structure(database, facts)
        report["gate2"] = gate2
        report["overall"] = (
            "raw_file_parsed_but_gate2_failed"
            if parsed["raw_file_status"] != "passed" or gate2["status"] != "passed"
            else "both_gates_passed"
        )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    g1 = report["gate1"]
    print(f"pycalphad : {report['pycalphad_version']} on Python {report['python_version']}")
    print(f"gate 1    : raw file -> {g1['raw_file_status']}")
    for attempt in g1["attempts"]:
        print(f"  [{attempt['status']:>7}] {attempt['method']}")
        if attempt["status"] == "failed":
            print(f"            {attempt['exception_module']}.{attempt['exception_type']}: {attempt['message']}")
            print(f"            location: {attempt.get('location')}")
            for line in attempt.get("traceback_tail", []):
                print(f"            | {line}")
        for warning in attempt.get("warnings", []):
            print(f"            warning: {warning}")
    diag = g1["encoding_diagnostics"]
    print(f"  encoding : non-ASCII bytes={diag['non_ascii_byte_count']} valid-utf8={diag['decodes_as_utf8']} "
          f"valid-cp1252={diag['decodes_as_cp1252']}")
    if diag["first_non_ascii"]:
        first = diag["first_non_ascii"]
        print(f"  first    : offset {first['first_non_ascii_offset']} byte {first['first_non_ascii_byte']} "
              f"{ascii(first['cp1252_character'])} on line {first['line_number']}: {first['line_text']}")
    print(f"  loaded_via: {g1['loaded_via']}")
    print("keyword probe (synthetic, in-memory only):")
    for name, result in report["keyword_probe"]["results"].items():
        if result["status"] == "passed":
            print(f"  [{result['status']:>7}] {name}")
        else:
            print(f"  [{result['status']:>7}] {name}: {result.get('exception_module','')}."
                  f"{result.get('exception_type','')} line={result.get('location',{}).get('line')} "
                  f"{str(result.get('message',''))[:120]}")
    if "gate2" in report:
        g2 = report["gate2"]
        print(f"gate 2    : {g2['status']}")
        print(f"  elements({len(g2['elements'])}): {', '.join(g2['elements'])}")
        print(f"  phases  : {g2['phase_count']}  parameters: {g2['parameter_count']}  species: {g2['species_count']}")
        print(f"  MatCalc composition-set phases: {g2['matcalc_composition_set_phases'] or 'none'}")
        print(f"  order/disorder links: {g2['order_disorder_links'] or 'none'}")
        for item in g2["checks"]:
            print(f"  [{item['status']:>7}] {item['check']}: {item['detail']}")
    print(f"overall   : {report['overall']}")
    if args.json:
        print(f"json      : {args.json}")
    return 0 if report["overall"] == "both_gates_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
