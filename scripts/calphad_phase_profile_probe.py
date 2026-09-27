"""T86 phase 4: independent verification of the fixed phase profile and reduced component system.

Runs in the ISOLATED interpreter (it needs pycalphad):

    .\\.venv-pycalphad\\Scripts\\python.exe -X utf8 scripts\\calphad_phase_profile_probe.py \
        --json outputs\\calphad_phase_profile_probe.json

It answers three questions and writes machine-readable evidence:

1. Does every phase named in ``steel_matrix_major_carbides_v1`` exist in the registered database,
   carry thermodynamic parameters, and construct a solvable phase record for the 12-component
   reduced system?
2. Is every one of those phases actually reachable inside the declared component system, so that
   "verified" is not merely "the name exists"?
3. Do the reduced-system building blocks behave: 12 components with a single phase, with the full
   fixed phase set, across a temperature scan, with phase-fraction sums of 1, and identically on a
   repeated run?

A phase that fails any of these checks must be removed from the first version of the phase set and
the reason recorded; it must never be forced on by editing the TDB.

Crash isolation: pycalphad 0.11.2 in this environment can abort the process natively, and building
many *distinct* phase records in one interpreter reliably triggers an LLVM JIT relocation abort
(``LLVM ERROR: IMAGE_REL_AMD64_ADDR32NB relocation requires an ordered section layout``) inside
symengine.  Each unit of work therefore runs in its own subprocess with a wall-clock timeout, and
the single-phase check runs one phase per process.

The reference composition below is a SYNTHETIC low-alloy reference, not a measured sample.  Measured
B-DQ/R-DQ compositions are only ever used through the adapter in the git-ignored outputs area.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "model_lab" / "calphad" / "databases" / "community" / "mc_fe_v2062_clean_19b1164.tdb"
COMPONENT_PROFILE_ID = "steel_matrix_equilibrium_v1"
PHASE_PROFILE_ID = "steel_matrix_major_carbides_v1"
ELEMENTS = ["C", "MN", "SI", "CR", "NI", "MO", "CU", "AL", "NB", "TI", "V"]
CANDIDATE_PHASES = ["LIQUID", "FCC_A1", "BCC_A2", "CEMENTITE", "M23C6", "M7C3", "M6C"]
FRACTION_EPSILON = 1e-6

#: Synthetic reference composition in mole fractions.  NOT a measured sample.
REFERENCE_MOLE_FRACTIONS = {
    "C": 0.0090, "MN": 0.0120, "SI": 0.0060, "CR": 0.0080, "NI": 0.0030,
    "MO": 0.0012, "CU": 0.0010, "AL": 0.0010, "NB": 0.0002, "TI": 0.0003, "V": 0.0005,
}
#: Composition envelope used for the reachability question only.  Mo and Cr are pushed well above
#: the reference values so that Mo-driven carbides (M6C) get a fair chance to appear.
REACHABILITY_ENVELOPE = {
    "C": [0.003, 0.010, 0.030, 0.060],
    "CR": [0.008, 0.030, 0.100, 0.200],
    "MO": [0.0012, 0.005, 0.015, 0.030],
}
REACHABILITY_TEMPERATURES_K = [873.15, 1073.15, 1273.15, 1473.15, 1673.15]
SCAN_TEMPERATURES_K = [673.15, 773.15, 873.15, 973.15, 1073.15, 1173.15, 1273.15,
                       1373.15, 1473.15, 1573.15, 1673.15, 1773.15, 1873.15, 1998.15]


def _components() -> list[str]:
    return ["FE"] + sorted(ELEMENTS) + ["VA"]


def _conditions(mole_fractions: dict[str, float], temperatures):
    from pycalphad import variables as v

    conditions: dict[Any, Any] = {v.T: temperatures, v.P: 101325.0, v.N: 1}
    for element, value in mole_fractions.items():
        conditions[v.X(element)] = float(value)
    return conditions


def _load_database(path: Path):
    from pycalphad import Database

    return Database.from_string(path.read_bytes().decode("utf-8"), fmt="tdb")


def _observed(np_values, phase_values) -> dict[str, float]:
    """Aggregate phase amounts.  The last axis is the number of *components*, not phases."""
    vertex = phase_values.shape[-1]
    pairs: dict[str, float] = {}
    for row_phase, row_np in zip(phase_values.reshape(-1, vertex), np_values.reshape(-1, vertex)):
        for name, amount in zip(row_phase, row_np):
            label = str(name).strip()
            if not label:
                continue
            value = float(amount)
            if value != value:
                continue
            pairs[label] = pairs.get(label, 0.0) + value
    return {name: value for name, value in pairs.items() if abs(value) > 1e-12}


def _parameter_counts(db) -> dict[str, int]:
    raw = getattr(db, "_parameters", None)
    entries = raw.all() if hasattr(raw, "all") else list(raw or [])
    counter: dict[str, int] = {}
    for entry in entries:
        name = getattr(entry, "phase_name", None)
        if name is None and isinstance(entry, dict):
            name = entry.get("phase_name")
        if name is not None:
            counter[str(name)] = counter.get(str(name), 0) + 1
    return counter


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        return
    try:
        os.killpg(os.getpgid(pid), 9)
    except (OSError, AttributeError):
        pass


def _spawn(tag: str, extra: list[str], scratch: Path, timeout_seconds: float) -> dict[str, Any]:
    scratch.mkdir(parents=True, exist_ok=True)
    payload_path = scratch / f"{tag}.json"
    if payload_path.is_file():
        payload_path.unlink()
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), *extra, "--json", str(payload_path)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", cwd=str(ROOT), env=environment,
                               creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = "", ""
    payload = None
    if payload_path.is_file():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
    return {
        "returncode": process.returncode,
        "timed_out": timed_out,
        "aborted": process.returncode != 0 or timed_out,
        "payload": payload,
        "stdout_tail": (stdout or "").strip().splitlines()[-4:],
        "stderr_tail": (stderr or "").strip().splitlines()[-4:],
    }


# ---------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------

def section_metadata(db_path: Path) -> dict[str, Any]:
    import importlib.metadata as metadata

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db = _load_database(db_path)
        warning_names = sorted({item.category.__name__ for item in caught})
    phase_names = {str(name) for name in db.phases.keys()}
    counters = _parameter_counts(db)
    return {
        "pycalphad_version": metadata.version("pycalphad"),
        "python_version": sys.version.split()[0],
        "database_path": str(db_path),
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "database_phase_count": len(phase_names),
        "database_parameter_count": sum(counters.values()),
        "load_warning_categories": warning_names,
        "candidate_phases": [
            {
                "phase": name,
                "in_database": name in phase_names,
                "parameter_count": int(counters.get(name, 0)),
                "constituent_count": (
                    len({str(c) for subl in db.phases[name].constituents for c in subl})
                    if name in phase_names else 0
                ),
            }
            for name in CANDIDATE_PHASES
        ],
    }


def section_one_phase(db_path: Path, phase: str) -> dict[str, Any]:
    """Validation step 1: 12 components, a single phase, single point at 1173.15 K."""
    from pycalphad import Workspace, equilibrium

    db = _load_database(db_path)
    components = _components()
    conditions = _conditions(REFERENCE_MOLE_FRACTIONS, 1173.15)
    entry: dict[str, Any] = {"phase": phase, "status": "ok"}
    try:
        Workspace(db, components, [phase], conditions)
        entry["workspace_constructed"] = True
    except Exception as exc:  # noqa: BLE001
        entry.update({"status": "failed", "workspace_constructed": False,
                      "error": f"{type(exc).__name__}: {exc}"[:300]})
        return entry
    result = equilibrium(db, components, [phase], conditions, output="GM")
    observed = _observed(np.asarray(result.NP.values), np.asarray(result.Phase.values))
    entry["observed"] = {name: round(value, 10) for name, value in sorted(observed.items())}
    entry["total_moles"] = round(sum(observed.values()), 10)
    return entry


def section_reachability(db_path: Path) -> dict[str, Any]:
    """Is each candidate phase stable *anywhere* in the declared component system?

    Done as ONE equilibrium call with composition and temperature as grid axes.  Building a fresh
    Workspace per point accumulates symengine modules and eventually trips the LLVM JIT relocation
    abort, so the grid is evaluated in a single workspace instead.
    """
    from pycalphad import equilibrium
    from pycalphad import variables as v

    db = _load_database(db_path)
    components = _components()
    conditions: dict[Any, Any] = {
        v.T: list(REACHABILITY_TEMPERATURES_K),
        v.X("C"): list(REACHABILITY_ENVELOPE["C"]),
        v.X("CR"): list(REACHABILITY_ENVELOPE["CR"]),
        v.X("MO"): list(REACHABILITY_ENVELOPE["MO"]),
        v.P: 101325.0,
        v.N: 1,
    }
    fixed = {element: value for element, value in REFERENCE_MOLE_FRACTIONS.items()
             if element not in {"C", "CR", "MO"}}
    for element, value in fixed.items():
        conditions[v.X(element)] = float(value)

    result = equilibrium(db, components, CANDIDATE_PHASES, conditions, output="GM")
    np_values = np.asarray(result.NP.values)
    phase_values = np.asarray(result.Phase.values)
    vertex = phase_values.shape[-1]
    flat_np = np_values.reshape(-1, vertex)
    flat_phase = phase_values.reshape(-1, vertex)
    occurrences: dict[str, int] = {}
    for row_phase, row_np in zip(flat_phase, flat_np):
        for name, amount in zip(row_phase, row_np):
            label = str(name).strip()
            if not label:
                continue
            value = float(amount)
            if value == value and value > FRACTION_EPSILON:
                occurrences[label] = occurrences.get(label, 0) + 1
    grid_points = int(flat_np.shape[0])
    return {
        "grid_points": grid_points,
        "envelope": REACHABILITY_ENVELOPE,
        "temperatures_K": REACHABILITY_TEMPERATURES_K,
        "fixed_elements": fixed,
        "occurrences": dict(sorted(occurrences.items())),
        "workspace_builds": 1,
    }


def section_reduced(db_path: Path, phases: list[str]) -> dict[str, Any]:
    """Validation steps 2-5: fixed phase set single point, temperature scan, sums, repeat."""
    from pycalphad import equilibrium

    db = _load_database(db_path)
    components = _components()

    single = equilibrium(db, components, phases,
                         _conditions(REFERENCE_MOLE_FRACTIONS, 1173.15), output="GM")
    observed = _observed(np.asarray(single.NP.values), np.asarray(single.Phase.values))

    def scan(temperatures):
        started = time.perf_counter()
        result = equilibrium(db, components, phases, _conditions(REFERENCE_MOLE_FRACTIONS, temperatures),
                             output="GM")
        elapsed = time.perf_counter() - started
        np_values = np.asarray(result.NP.values)
        phase_values = np.asarray(result.Phase.values)
        vertex = phase_values.shape[-1]
        flat_np = np_values.reshape(-1, vertex)
        flat_phase = phase_values.reshape(-1, vertex)
        points = []
        for index, temperature in enumerate(np.asarray(result.T.values).ravel()):
            pairs: dict[str, float] = {}
            for pname, amount in zip(flat_phase[index], flat_np[index]):
                label = str(pname).strip()
                value = float(amount)
                if label and value == value and value > 0:
                    pairs[label] = pairs.get(label, 0.0) + value
            points.append({
                "temperature_K": round(float(temperature), 6),
                "temperature_C": round(float(temperature) - 273.15, 6),
                "total_moles": round(sum(pairs.values()), 10),
                "phase_fractions_mole": {name: round(value, 10) for name, value in sorted(pairs.items())},
            })
        return {"elapsed_s": round(elapsed, 3), "points": points}

    first = scan(SCAN_TEMPERATURES_K)
    second = scan(SCAN_TEMPERATURES_K)
    sums = [point["total_moles"] for point in first["points"]]
    return {
        "requested_phases": phases,
        "single_point_1173K": {
            "observed": {name: round(value, 10) for name, value in sorted(observed.items())},
            "total_moles": round(sum(observed.values()), 10),
        },
        "temperature_scan": {
            "point_count": len(first["points"]),
            "expected_count": len(SCAN_TEMPERATURES_K),
            "elapsed_s": first["elapsed_s"],
            "points": first["points"],
        },
        "phase_fraction_sums": {
            "sum_min": round(min(sums), 10) if sums else None,
            "sum_max": round(max(sums), 10) if sums else None,
            "tolerance": 1e-4,
        },
        "repeat_run_identical": first["points"] == second["points"],
    }


def run_all(args: argparse.Namespace) -> int:
    scratch = args.json.parent / "_t86_phase_profile"
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "probe_id": "SteelAI-T86-Phase4-Phase-Profile-Evidence-v1.0",
        "component_profile": {
            "profile_id": COMPONENT_PROFILE_ID,
            "elements": ["Fe"] + [element.capitalize() for element in sorted(ELEMENTS)],
            "component_list_length_sent_to_pycalphad": len(_components()),
        },
        "phase_profile_candidate": {"profile_id": PHASE_PROFILE_ID, "phases": list(CANDIDATE_PHASES)},
        "reference_composition": {
            "kind": "synthetic_reference_not_a_measured_sample",
            "basis": "mole_fraction",
            "values": dict(REFERENCE_MOLE_FRACTIONS),
        },
        "crash_isolation": "each unit of work runs in its own subprocess with a wall-clock timeout",
    }

    metadata_outcome = _spawn("metadata", ["--section", "metadata", "--db", str(args.db)],
                              scratch, args.timeout)
    if metadata_outcome["payload"] is None:
        report["status"] = "failed"
        report["failure"] = {"stage": "metadata", **{k: v for k, v in metadata_outcome.items() if k != "payload"}}
        _write(args.json, report)
        return 1
    report.update(metadata_outcome["payload"])

    one_phase: list[dict[str, Any]] = []
    for name in CANDIDATE_PHASES:
        outcome = _spawn(f"phase_{name}", ["--section", "one-phase", "--phase", name, "--db", str(args.db)],
                         scratch, args.timeout)
        payload = outcome["payload"] or {"phase": name, "status": "aborted"}
        payload["process_aborted"] = outcome["aborted"]
        payload["returncode"] = outcome["returncode"]
        payload["timed_out"] = outcome["timed_out"]
        payload["stderr_tail"] = outcome["stderr_tail"]
        if outcome["payload"] is None:
            payload["status"] = "failed"
        one_phase.append(payload)
        print(f"one-phase {name:10} status={payload['status']} rc={outcome['returncode']}", flush=True)
    report["one_phase_single_point"] = one_phase

    reach_outcome = _spawn("reachability", ["--section", "reachability", "--db", str(args.db)],
                           scratch, args.timeout)
    reachability = reach_outcome["payload"] or {"occurrences": {}, "grid_points": 0}
    reachability["process_aborted"] = reach_outcome["aborted"]
    report["reachability"] = reachability
    print(f"reachability: rc={reach_outcome['returncode']} occurrences={reachability.get('occurrences')}", flush=True)

    # --- verdict per phase -------------------------------------------------------------------
    by_phase = {item["phase"]: item for item in one_phase}
    metadata_by_phase = {item["phase"]: item for item in report["candidate_phases"]}
    occurrences = reachability.get("occurrences", {}) or {}
    phases: list[dict[str, Any]] = []
    for name in CANDIDATE_PHASES:
        info = metadata_by_phase.get(name, {})
        single = by_phase.get(name, {})
        entry = {
            "phase": name,
            "in_database": bool(info.get("in_database")),
            "parameter_count": int(info.get("parameter_count", 0)),
            "constituent_count": int(info.get("constituent_count", 0)),
            "workspace_constructed": bool(single.get("workspace_constructed")),
            "single_phase_solved": single.get("status") == "ok",
            "single_phase_total_moles": single.get("total_moles"),
            "reachability_occurrences": int(occurrences.get(name, 0)),
        }
        entry["has_parameters"] = entry["parameter_count"] > 0
        entry["reachable"] = entry["reachability_occurrences"] > 0
        failures = []
        if not entry["in_database"]:
            failures.append("phase name absent from the registered database")
        if not entry["has_parameters"]:
            failures.append("no thermodynamic parameters")
        if not entry["workspace_constructed"]:
            failures.append("phase record not constructible for the reduced system")
        if not entry["single_phase_solved"]:
            failures.append("single-phase equilibrium did not solve")
        if not entry["reachable"]:
            failures.append("never stable anywhere in the declared component system")
        entry["verdict"] = "removed" if failures else "verified"
        entry["reason"] = "; ".join(failures)
        phases.append(entry)
    report["phases"] = phases
    verified = [entry["phase"] for entry in phases if entry["verdict"] == "verified"]
    report["verified_phases"] = verified
    report["removed_phases"] = [{"phase": entry["phase"], "reason": entry["reason"]}
                                for entry in phases if entry["verdict"] == "removed"]
    report["active_phase_set"] = verified

    reduced_outcome = _spawn("reduced", ["--section", "reduced", "--db", str(args.db),
                                         "--phases", ",".join(verified)],
                             scratch, args.timeout) if verified else {"payload": None, "aborted": True,
                                                                      "returncode": None,
                                                                      "timed_out": False,
                                                                      "stderr_tail": []}
    reduced = reduced_outcome["payload"]
    report["reduced_system_checks"] = reduced
    print(f"reduced checks: rc={reduced_outcome['returncode']} payload={'yes' if reduced else 'no'}", flush=True)

    checks_status: dict[str, str] = {}
    checks_status["step1_12_components_one_phase_single_point"] = (
        "ok" if verified and all(entry["single_phase_solved"] and entry["workspace_constructed"]
                                 for entry in phases if entry["verdict"] == "verified") else "failed")
    if reduced:
        checks_status["step2_12_components_fixed_phase_set_single_point"] = (
            "ok" if reduced["single_point_1173K"]["observed"] else "failed")
        checks_status["step3_temperature_scan"] = (
            "ok" if reduced["temperature_scan"]["point_count"] == reduced["temperature_scan"]["expected_count"]
            else "failed")
        sums = reduced["phase_fraction_sums"]
        checks_status["step4_phase_fraction_sums"] = (
            "ok" if sums["sum_min"] is not None and abs(sums["sum_min"] - 1.0) < sums["tolerance"]
            and abs(sums["sum_max"] - 1.0) < sums["tolerance"] else "failed")
        checks_status["step5_repeat_run_identical"] = "ok" if reduced["repeat_run_identical"] else "failed"
    else:
        for key in ("step2_12_components_fixed_phase_set_single_point", "step3_temperature_scan",
                    "step4_phase_fraction_sums", "step5_repeat_run_identical"):
            checks_status[key] = "failed"
    report["reduced_system_check_status"] = checks_status
    report["all_phases_verified"] = bool(verified) and len(verified) == len(CANDIDATE_PHASES)
    report["verdict"] = "verified" if all(value == "ok" for value in checks_status.values()) else "failed"
    report["elapsed_s"] = round(time.perf_counter() - started, 1)
    _write(args.json, report)

    print(f"verified phases: {verified}")
    print(f"removed phases: {report['removed_phases']}")
    for key, value in checks_status.items():
        print(f"{key}: {value}")
    print(f"verdict: {report['verdict']}")
    print(f"json: {args.json}")
    return 0


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Verify the fixed phase profile for the reduced system.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--section",
                        choices=("all", "metadata", "one-phase", "reachability", "reduced"),
                        default="all")
    parser.add_argument("--phase", default=None)
    parser.add_argument("--phases", default="")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv[1:])

    if args.section == "all":
        return run_all(args)
    if args.section == "metadata":
        _write(args.json, section_metadata(args.db))
        return 0
    if args.section == "one-phase":
        _write(args.json, section_one_phase(args.db, args.phase))
        return 0
    if args.section == "reachability":
        _write(args.json, section_reachability(args.db))
        return 0
    if args.section == "reduced":
        phases = [name for name in args.phases.split(",") if name]
        _write(args.json, section_reduced(args.db, phases))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
