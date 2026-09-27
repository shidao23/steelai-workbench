"""T86 phase 3: probe how pycalphad reads the malformed original statements that the community
"clean" database repaired.

Some statements in the TU Wien original are malformed (a stray duplicated number and a doubled
`; <T> N` tail on exactly two PDMN_B2 end-member parameters, an invalid `6000.00.00` literal, a
`;` used where the constituent delimiter must be `,`, and one missing `!` terminator).  This
script feeds the original and the repaired form of the *same* parameter to pycalphad in an
isolated, synthetic database and reports whether each parses and what symbolic expression
pycalphad ends up with.  It answers one question: is a community change a pure syntax repair of
an unparseable statement, or a real change to a Gibbs-energy coefficient?

Run in the isolated interpreter:
    .\\.venv-pycalphad\\Scripts\\python.exe -I scripts\\calphad_malformed_statement_probe.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PREAMBLE = """ELEMENT VA VACUUM 0 0 0 !
ELEMENT MN CBCC_A12 54.938 4996 32.22 !
ELEMENT PD FCC_A1 106.42 0 37.82 !
ELEMENT CR BCC_A2 51.996 4050 23.5429 !
ELEMENT FE BCC_A2 55.847 4489 27.2797 !
ELEMENT C GRAPHITE 12.011 1054 5.7423 !
ELEMENT CU FCC_A1 63.546 5004 33.15 !
ELEMENT SI DIAMOND_A4 28.085 3217 18.82 !
PHASE PDMN_B2 % 2 0.5 0.5 !
CONSTITUENT PDMN_B2 :MN,PD:MN,PD: !
PHASE SIGMA % 3 0.3 0.5 0.2 !
CONSTITUENT SIGMA :FE:CR:FE: !
PHASE G_PHASE % 3 1 1 1 !
CONSTITUENT G_PHASE :FE:CU:SI: !
FUNCTION GHSERMN 298.15 -8115.28+130.67*T-23.4582*T*LN(T); 6000 N !
FUNCTION GHSERPD 298.15 -7950.8+128.6*T-22.4*T*LN(T); 6000 N !
FUNCTION GFEFCC 298.15 -236.7+132.416*T-24.6643*T*LN(T); 6000 N !
FUNCTION GHSERCR 298.15 -8856.94+157.48*T-26.908*T*LN(T); 6000 N !
FUNCTION GHSERFE 298.15 +1225.7+124.134*T-23.5143*T*LN(T); 6000 N !
FUNCTION GHSERCU 298.15 -7770.46+130.485*T-24.1124*T*LN(T); 6000 N !
FUNCTION GHSERSI 298.15 -8162.61+137.236*T-22.8318*T*LN(T); 6000 N !
"""

CASES: list[dict[str, str]] = [
    {
        "case": "pdmn_b2_MN_PD",
        "phase": "PDMN_B2",
        "constituents": "MN:PD",
        "original": "PARAMETER G(PDMN_B2,MN:PD;0) 273.00 273 +46000-23*T +0.05*T**(+2)-1E-05*T**(+3)+1000000*T**(-1)+0.5*GHSERMN# -5*T*LN(T)+0.5*GHSERPD#; 6000.00  N ; 6000.00  N !",
        "community": "PARAMETER G(PDMN_B2,MN:PD;0) 273.00 +46000-23*T +0.05*T**(+2)-1E-05*T**(+3)+1000000*T**(-1)+0.5*GHSERMN# -5*T*LN(T)+0.5*GHSERPD#; 6000.00  N !",
    },
    {
        "case": "sigma_FE_CR_FE",
        "phase": "SIGMA",
        "constituents": "FE:CR:FE",
        "original": "PARAMETER G(SIGMA,FE:CR:FE;0) 273.00 +117300-95.96*T+8*GFEFCC# +4*GHSERCR#+18*GHSERFE#; 6000.00.00  N !",
        "community": "PARAMETER G(SIGMA,FE:CR:FE;0) 273.00 +117300-95.96*T+8*GFEFCC# +4*GHSERCR#+18*GHSERFE#; 6000.00  N !",
    },
    {
        "case": "g_phase_semicolon_delimiter",
        "phase": "G_PHASE",
        "constituents": "FE:CU:SI",
        "original": "PARAMETER G(G_PHASE;FE:CU:SI;0) 273.00 +16*GHSERFE#+6*GHSERCU# +7*GHSERSI-435000; 6000.00  N !",
        "community": "PARAMETER G(G_PHASE,FE:CU:SI;0) 273.00 +16*GHSERFE#+6*GHSERCU# +7*GHSERSI-435000; 6000.00  N !",
    },
]


def probe(case: dict[str, str]) -> dict[str, Any]:
    from pycalphad import Database

    result: dict[str, Any] = {"case": case["case"], "phase": case["phase"], "constituents": case["constituents"]}
    for label in ("original", "community"):
        text = PREAMBLE + case[label] + "\n"
        entry: dict[str, Any] = {"status": "unknown"}
        try:
            dbf = Database.from_string(text, fmt="tdb")
        except Exception as exc:  # noqa: BLE001
            entry.update({
                "status": "failed",
                "exception_type": type(exc).__name__,
                "message": str(exc).replace("\n", " | ")[:300],
            })
        else:
            from tinydb import where
            from pycalphad.variables import Species

            wanted = tuple(
                (Species(part),) for part in case["constituents"].split(":")
            )
            rows = dbf._parameters.search(where("constituent_array") == wanted)
            if not rows:
                rows = [row for row in dbf._parameters.all()
                        if row["phase_name"] == case["phase"].upper()]
            if rows:
                entry.update({
                    "status": "parsed",
                    "parameter_expression": str(rows[0]["parameter"]),
                    "parameter_count_for_phase": len(rows),
                })
            else:
                entry.update({"status": "parsed_but_parameter_missing"})
        result[label] = entry
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Probe malformed TDB statements with pycalphad.")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv[1:])

    from importlib import metadata

    report = {
        "schema_version": "1.0",
        "pycalphad_version": metadata.version("pycalphad"),
        "python_version": sys.version.split()[0],
        "note": "Synthetic in-memory database used only to read the same parameter in its original and repaired form; no vendor file is modified and no equilibrium is calculated.",
        "cases": [probe(case) for case in CASES],
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"pycalphad {report['pycalphad_version']} on Python {report['python_version']}")
    for case in report["cases"]:
        print(f"\ncase {case['case']} ({case['phase']} {case['constituents']})")
        for label in ("original", "community"):
            entry = case[label]
            print(f"  {label:9}: {entry['status']}")
            if entry["status"] == "failed":
                print(f"             {entry['exception_type']}: {entry['message']}")
            elif "parameter_expression" in entry:
                print(f"             expr = {entry['parameter_expression'][:220]}")
    if args.json:
        print(f"\njson: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
