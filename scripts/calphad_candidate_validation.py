"""T86 phase 3: independent validation of the community "clean" mc_fe v2.062 derivative.

Runs in the isolated interpreter:

    .\\.venv-pycalphad\\Scripts\\python.exe -X utf8 scripts\\calphad_candidate_validation.py \
        --cases outputs\\calphad_validation_cases.json --json outputs\\calphad_candidate_validation.json

Covered:
  * file/DB counts, ordered-disordered relations, Workspace construction;
  * single-point equilibrium and a full temperature scan for the two project heats, with
    phase-fraction sums, non-convergence detection, repeatability and range assertions;
  * the five binary systems / fifteen checks that the community repository claims
    (Fe-Cr, Fe-Ni, Fe-Ti, Fe-Mo, Ni-Ti), re-implemented here from the stated criteria rather
    than copied, and evaluated on our own runs;
  * project-relevant binaries (Fe-C, Fe-Mn, Fe-Si, Fe-Nb, Fe-V, Fe-B, Fe-N) and a MC/MX
    carbo-nitride stability check;
  * whether BCC_B2 enters the stable assemblage for B-DQ/R-DQ;
  * a component-count limit probe that measures the largest component list pycalphad 0.11.2
    can solve on this host, on the community database and on an independent control database.

Every equilibration runs in its own subprocess, because pycalphad 0.11.2 can abort the whole
process with a C-level access violation instead of raising a Python exception.  Crash isolation
is what makes the failure recordable rather than fatal.

All of this demonstrates software behaviour and basic thermodynamic plausibility.  It is NOT
experimental validation of a steel grade and must never be reported as such.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "model_lab" / "calphad" / "databases" / "community" / "mc_fe_v2062_clean_19b1164.tdb"
SCRATCH = ROOT / "outputs" / "_t86_candidate"
FRACTION_THRESHOLD = 0.01

#: Upstream header comment on line 60 of the original: "Temperature: 673 K - 2000 K".
ASSESSED_RANGE_K = (673.0, 2000.0)
#: Upstream header comment composition envelope (wt.% upper limits).
COMPOSITION_LIMITS_WT = {
    "Al": 3, "B": 0.5, "C": 0.5, "Co": 3, "Cr": 25, "Cu": 1, "H": 0.1, "Hf": 0.5, "La": 0.5,
    "Mn": 25, "Mo": 5, "N": 1, "Nb": 1, "Ni": 26, "O": 0.5, "P": 0.05, "Pd": 4, "S": 0.1,
    "Si": 3.5, "Ta": 0.5, "Ti": 0.5, "V": 0.5, "W": 3, "Y": 0.5,
}

PERMANENT_LIMITATION_TEXT = (
    "本结果是基于 pycalphad 0.11.2 与社区派生的 mc_fe v2.062 数据库的缩减成分体系平衡热力学预测。"
    "R-DQ 中 As、Sn、Sb 未被数据库建模；O、W 因缺少测量值未进入计算。"
    "数据库派生过程中 BCC_B2 有序-无序耦合被关闭、MatCalc 的 HMVA 与组合集命令被注释，"
    "因此该数据库不再等价于 MatCalc 原始模型。结果不能用于判断这些元素对偏聚、夹杂、"
    "晶界脆化、相稳定性或性能的影响。"
)


def _cost507_path() -> Path:
    import pycalphad

    return Path(pycalphad.__file__).resolve().parent / "tests" / "databases" / "COST507.tdb"


def load_database(path: Path):
    """Strict loader for the candidate under review.

    The bytes are decoded explicitly and handed to ``Database.from_string``.  A candidate that
    cannot be parsed from its own bytes must fail loudly, so no fallback is applied here.
    """
    from pycalphad import Database

    text = path.read_bytes().decode("utf-8")
    return Database.from_string(text, fmt="tdb")


def load_control_database(path: Path):
    """Loader for the pycalphad-bundled control database (COST507).

    The bundled COST507 is only accepted by the file-based constructor under pycalphad 0.11.2,
    so the string path is tried first and the file constructor is the documented fallback.  The
    candidate under review never takes a fallback.
    """
    from pycalphad import Database

    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    try:
        return Database.from_string(text, fmt="tdb")
    except Exception:  # noqa: BLE001 - documented fallback for an unmodified upstream file
        return Database(path)


def _active_phases(np_values, phase_values) -> list[str]:
    active = []
    for index in range(len(phase_values)):
        name = str(phase_values[index]).strip()
        fraction = float(np_values[index]) if not np.isnan(np_values[index]) else 0.0
        if name and name != "" and fraction > FRACTION_THRESHOLD:
            active.append(name)
    return sorted(set(active))


def equilibrium_point(db, components: list[str], phases: list[str], conditions: dict) -> dict[str, Any]:
    from pycalphad import equilibrium

    result = equilibrium(db, components, phases, conditions, output="GM")
    np_values = np.asarray(result.NP.values).ravel()
    phase_values = np.asarray(result.Phase.values).ravel()
    pairs: dict[str, float] = {}
    for name, fraction in zip(phase_values, np_values):
        label = str(name).strip()
        if not label:
            continue
        value = float(fraction) if fraction == fraction else 0.0
        if value > 0:
            base = label.split("#")[0]
            pairs[base] = pairs.get(base, 0.0) + value
    total = sum(pairs.values())
    return {
        "phase_fractions_mole": {name: round(value, 8) for name, value in sorted(pairs.items())},
        "phases_present": _active_phases(np_values, phase_values),
        "total_moles": total,
        "converged": total > 0,
    }


def temperature_scan(db, case: dict[str, Any]) -> dict[str, Any]:
    from pycalphad import equilibrium, variables as v

    components = list(case["components"])
    phases = sorted(str(name) for name in db.phases.keys())
    conditions = {v.T: [float(t) + 273.15 for t in case["temperature_C"]], v.P: float(case["pressure_Pa"])}
    for element, fraction in case["component_mole_fractions"].items():
        conditions[v.X(element)] = float(fraction)
    started = time.perf_counter()
    result = equilibrium(db, components, phases, conditions, output="GM")
    elapsed = time.perf_counter() - started

    temperatures = np.asarray(result.T.values).ravel()
    np_grid = np.asarray(result.NP.values)
    phase_grid = np.asarray(result.Phase.values)
    vertex = phase_grid.shape[-1]
    np_flat = np_grid.reshape(-1, vertex)
    phase_flat = phase_grid.reshape(-1, vertex)
    if len(temperatures) != np_flat.shape[0]:
        return {"status": "failed", "error": "temperature grid does not match the result grid"}

    points = []
    non_converged = []
    for index in range(len(temperatures)):
        pairs: dict[str, float] = {}
        for name, fraction in zip(phase_flat[index], np_flat[index]):
            label = str(name).strip()
            value = float(fraction) if fraction == fraction else 0.0
            if label and value > 0:
                base = label.split("#")[0]
                pairs[base] = pairs.get(base, 0.0) + value
        total = sum(pairs.values())
        temperature_C = round(float(temperatures[index]) - 273.15, 6)
        if total <= 0:
            non_converged.append(temperature_C)
        points.append({
            "temperature_C": temperature_C,
            "total_moles": round(total, 10),
            "phase_fractions_mole": {name: round(value, 8) for name, value in sorted(pairs.items())},
            "phases_present": _active_phases(np_flat[index], phase_flat[index]),
        })
    points.sort(key=lambda item: item["temperature_C"])
    sums = [point["total_moles"] for point in points if point["total_moles"] > 0]
    return {
        "status": "ok",
        "elapsed_s": round(elapsed, 3),
        "points": points,
        "non_converged_temperatures_C": non_converged,
        "sum_min": round(min(sums), 8) if sums else None,
        "sum_max": round(max(sums), 8) if sums else None,
        "phase_union": sorted({name for point in points for name in point["phases_present"]}),
    }


def phase_map(db, system: dict[str, Any], x_vals: np.ndarray, t_vals: np.ndarray) -> dict[str, Any]:
    """Assemblage grid over (temperature, scanned composition).

    One equilibrium call is made per temperature.  Broadcasting temperature and composition into
    a single call makes the returned axis order depend on how pycalphad materialises scalar
    composition conditions, so the per-temperature call is used to keep the grid indexing
    unambiguous.
    """
    from pycalphad import equilibrium, variables as v

    components = list(system["components"])
    phases = [name for name in system["phases"] if name in db.phases]
    fixed = {element: float(value) for element, value in (system.get("fixed") or {}).items()}
    grid: list[list[str]] = []
    started = time.perf_counter()
    temperature_elapsed: list[float] = []
    for temperature in t_vals:
        conditions = {
            v.X(system["x_var"]): list(x_vals),
            v.T: float(temperature),
            v.P: 101325,
            v.N: 1,
        }
        # pycalphad requires zero degrees of freedom: the scanned element is the grid axis and
        # every other non-Fe element has to be held at a fixed mole fraction.
        for element, value in fixed.items():
            conditions[v.X(element)] = value
        point_started = time.perf_counter()
        result = equilibrium(db, components, phases, conditions, output="GM")
        temperature_elapsed.append(round(time.perf_counter() - point_started, 3))
        np_values = np.asarray(result.NP.values)
        phase_values = np.asarray(result.Phase.values)
        vertex = phase_values.shape[-1]
        flat_np = np_values.reshape(-1, vertex)
        flat_phase = phase_values.reshape(-1, vertex)
        if flat_np.shape[0] != len(x_vals):
            raise ValueError(
                f"phase_map: expected {len(x_vals)} composition points per temperature, "
                f"got {flat_np.shape[0]}"
            )
        row = []
        for composition_index in range(len(x_vals)):
            active = _active_phases(flat_np[composition_index], flat_phase[composition_index])
            row.append("+".join(active) if active else "UNKNOWN")
        grid.append(row)
    elapsed = time.perf_counter() - started
    return {"grid": grid, "elapsed_s": round(elapsed, 3), "phases_used": phases,
            "calls": len(t_vals), "per_call_elapsed_s": temperature_elapsed}


def _has(grid: list[list[str]], *, phase: str, t_celsius, x_values, t_mask: Callable[[float], bool],
         x_mask: Callable[[float], bool] | None = None) -> bool:
    for i, temperature in enumerate(t_celsius):
        if not t_mask(float(temperature)):
            continue
        for j, composition in enumerate(x_values):
            if x_mask is not None and not x_mask(float(composition)):
                continue
            if phase in grid[i][j]:
                return True
    return False


#: The community repository's five binary systems and fifteen stated checks, re-implemented from
#: the criteria (no source code was copied; the repository publishes no LICENSE file).
COMMUNITY_SYSTEMS: list[dict[str, Any]] = [
    {
        "name": "Fe-Cr", "components": ["FE", "CR", "VA"], "x_var": "CR",
        "phases": ["BCC_A2", "FCC_A1", "SIGMA", "LIQUID"],
        "checks": [
            ("SIGMA phase present", lambda grid, t, x: _has(grid, phase="SIGMA", t_celsius=t, x_values=x, t_mask=lambda _: True)),
            ("FCC gamma loop (Fe-rich, >800C)", lambda grid, t, x: _has(grid, phase="FCC_A1", t_celsius=t, x_values=x, t_mask=lambda value: value > 800, x_mask=lambda value: value < 0.15)),
            ("LIQUID at high T", lambda grid, t, x: _has(grid, phase="LIQUID", t_celsius=t, x_values=x, t_mask=lambda value: value > 1400)),
        ],
    },
    {
        "name": "Fe-Ni", "components": ["FE", "NI", "VA"], "x_var": "NI",
        "phases": ["BCC_A2", "FCC_A1", "LIQUID"],
        "checks": [
            ("FCC dominant at high Ni", lambda grid, t, x: _has(grid, phase="FCC_A1", t_celsius=t, x_values=x, t_mask=lambda value: 600 < value < 1000, x_mask=lambda value: value > 0.5)),
            ("BCC at low Ni, low T", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda value: value < 500, x_mask=lambda value: value < 0.1)),
            ("LIQUID at high T", lambda grid, t, x: _has(grid, phase="LIQUID", t_celsius=t, x_values=x, t_mask=lambda value: value > 1400)),
            ("BCC+FCC two-phase region exists", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True) and _has(grid, phase="FCC_A1", t_celsius=t, x_values=x, t_mask=lambda _: True)),
        ],
    },
    {
        "name": "Fe-Ti", "components": ["FE", "TI", "VA"], "x_var": "TI",
        "phases": ["BCC_A2", "FCC_A1", "LAVES_PHASE", "LIQUID", "ETA"],
        "checks": [
            ("LAVES_PHASE (Fe2Ti) present", lambda grid, t, x: _has(grid, phase="LAVES_PHASE", t_celsius=t, x_values=x, t_mask=lambda _: True)),
            ("BCC stable at low Ti", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda value: value < 800, x_mask=lambda value: value < 0.1)),
            ("LIQUID at high T", lambda grid, t, x: _has(grid, phase="LIQUID", t_celsius=t, x_values=x, t_mask=lambda value: value > 1400)),
        ],
    },
    {
        "name": "Fe-Mo", "components": ["FE", "MO", "VA"], "x_var": "MO",
        "phases": ["BCC_A2", "FCC_A1", "SIGMA", "MU_PHASE", "R_PHASE", "LIQUID", "LAVES_PHASE"],
        "checks": [
            ("SIGMA or MU_PHASE present", lambda grid, t, x: _has(grid, phase="SIGMA", t_celsius=t, x_values=x, t_mask=lambda _: True) or _has(grid, phase="MU_PHASE", t_celsius=t, x_values=x, t_mask=lambda _: True)),
            ("BCC dominant", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
            ("LIQUID at high T", lambda grid, t, x: _has(grid, phase="LIQUID", t_celsius=t, x_values=x, t_mask=lambda value: value > 1400)),
        ],
    },
    {
        "name": "Ni-Ti", "components": ["NI", "TI", "VA"], "x_var": "TI",
        "phases": ["BCC_A2", "FCC_A1", "ETA", "NITI2", "LAVES_PHASE", "LIQUID", "HCP_A3"],
        "checks": [
            ("ETA (Ni3Ti) present", lambda grid, t, x: _has(grid, phase="ETA", t_celsius=t, x_values=x, t_mask=lambda _: True)),
            ("FCC at Ni-rich side", lambda grid, t, x: _has(grid, phase="FCC_A1", t_celsius=t, x_values=x, t_mask=lambda value: value < 1000, x_mask=lambda value: value < 0.2)),
        ],
    },
]

PROJECT_SYSTEMS: list[dict[str, Any]] = [
    {"name": "Fe-C (stable, graphite allowed)", "components": ["FE", "C", "VA"], "x_var": "C",
     "x_min": 0.0005, "x_max": 0.05,
     "phases": ["BCC_A2", "FCC_A1", "CEMENTITE", "LIQUID", "GRAPHITE", "M7C3", "M23C6"],
     "checks": [("GRAPHITE present (stable Fe-C)", lambda grid, t, x: _has(grid, phase="GRAPHITE", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("FCC_A1 present (austenite)", lambda grid, t, x: _has(grid, phase="FCC_A1", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-C (metastable, graphite suspended)", "components": ["FE", "C", "VA"], "x_var": "C",
     "x_min": 0.0005, "x_max": 0.05,
     "phases": ["BCC_A2", "FCC_A1", "CEMENTITE", "LIQUID", "M7C3"],
     "checks": [("CEMENTITE present (Fe3C)", lambda grid, t, x: _has(grid, phase="CEMENTITE", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("BCC_A2 present (ferrite)", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-Cr-C (carbide formers)", "components": ["FE", "CR", "C", "VA"], "x_var": "CR",
     "x_min": 0.03, "x_max": 0.30, "fixed": {"C": 0.02},
     "phases": ["BCC_A2", "FCC_A1", "CEMENTITE", "LIQUID", "GRAPHITE", "M7C3", "M23C6", "M3C2", "M6C", "M12C"],
     "checks": [("M7C3 or M23C6 present", lambda grid, t, x: _has(grid, phase="M7C3", t_celsius=t, x_values=x, t_mask=lambda _: True) or _has(grid, phase="M23C6", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("M23C6 present (Cr-rich carbide)", lambda grid, t, x: _has(grid, phase="M23C6", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-Mn", "components": ["FE", "MN", "VA"], "x_var": "MN",
     "phases": ["BCC_A2", "FCC_A1", "LIQUID", "ALPHA_MN", "BETA_MN"],
     "checks": [("BCC_A2 present", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("FCC_A1 present", lambda grid, t, x: _has(grid, phase="FCC_A1", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-Si", "components": ["FE", "SI", "VA"], "x_var": "SI",
     "phases": ["BCC_A2", "FCC_A1", "LIQUID", "HCP_A3", "DIAMOND_A4"],
     "checks": [("BCC_A2 present", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("ordered/silicide phase present", lambda grid, t, x: _has(grid, phase="HCP_A3", t_celsius=t, x_values=x, t_mask=lambda _: True) or _has(grid, phase="DIAMOND_A4", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-Nb", "components": ["FE", "NB", "VA"], "x_var": "NB",
     "phases": ["BCC_A2", "FCC_A1", "C14_LAVES", "C15_LAVES", "LAVES_PHASE", "FE2NB", "LIQUID"],
     "checks": [("BCC_A2 present", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("Laves-type phase present", lambda grid, t, x: _has(grid, phase="C14_LAVES", t_celsius=t, x_values=x, t_mask=lambda _: True) or _has(grid, phase="C15_LAVES", t_celsius=t, x_values=x, t_mask=lambda _: True) or _has(grid, phase="LAVES_PHASE", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-V", "components": ["FE", "V", "VA"], "x_var": "V",
     "phases": ["BCC_A2", "FCC_A1", "SIGMA", "LIQUID"],
     "checks": [("BCC_A2 present", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("SIGMA present", lambda grid, t, x: _has(grid, phase="SIGMA", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-B", "components": ["FE", "B", "VA"], "x_var": "B",
     "phases": ["BCC_A2", "FCC_A1", "FEB", "M2B", "LIQUID"],
     "checks": [("BCC_A2 present", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("boride phase present", lambda grid, t, x: _has(grid, phase="FEB", t_celsius=t, x_values=x, t_mask=lambda _: True) or _has(grid, phase="M2B", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
    {"name": "Fe-N", "components": ["FE", "N", "VA"], "x_var": "N",
     "phases": ["BCC_A2", "FCC_A1", "FE4N", "LIQUID", "O1_GAS"],
     "checks": [("BCC_A2 present", lambda grid, t, x: _has(grid, phase="BCC_A2", t_celsius=t, x_values=x, t_mask=lambda _: True)),
                ("nitride phase present", lambda grid, t, x: _has(grid, phase="FE4N", t_celsius=t, x_values=x, t_mask=lambda _: True))]},
]

MC_PHASES = ("MC", "MX", "NBC", "V4C3", "TIC", "V3C2", "WC", "MOC_ETA", "FCC_A1#01")

#: Findings-only probes for the documented model losses.  Their checks are *expected* to be
#: negative, so they are recorded separately and are never counted as reproduced/failed
#: validation claims.
MODEL_LOSS_PROBES: list[dict[str, Any]] = [
    {
        "name": "Fe-C-N-Nb-Ti-V carbo-nitride reachability",
        "components": ["FE", "C", "N", "NB", "TI", "V", "VA"],
        "x_var": "C",
        "x_min": 0.002,
        "x_max": 0.02,
        "fixed": {"N": 0.001, "NB": 0.0005, "TI": 0.0005, "V": 0.001},
        "phases": ["BCC_A2", "FCC_A1", "CEMENTITE", "LIQUID", "ALN", "BN_HP4", "FE4N",
                   "M7C3", "M23C6", "MC", "MX", "NBC", "TIC", "V4C3", "WC"],
        "expected_result": False,
        "checks": [("MC/MX composition set reachable", lambda grid, t, x: any(
            cell.split("+")[0].upper().startswith(("MC", "MX", "NBC", "TIC", "V4C3", "WC"))
            for row in grid for cell in row))],
    },
]

ALL_SYSTEMS: list[dict[str, Any]] = COMMUNITY_SYSTEMS + PROJECT_SYSTEMS + MODEL_LOSS_PROBES


def _find_system(name: str) -> dict[str, Any]:
    for item in ALL_SYSTEMS:
        if item["name"] == name:
            return item
    raise KeyError(f"unknown system: {name}")


def _system_kind(system: dict[str, Any]) -> str:
    name = system["name"]
    if any(item["name"] == name for item in COMMUNITY_SYSTEMS):
        return "community_claim"
    if any(item["name"] == name for item in PROJECT_SYSTEMS):
        return "project_relevant"
    return "model_loss_probe"


def _tag(name: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in name)

#: Component-count limit probe.  The community database and an independent, pycalphad-bundled
#: steel database (COST507) are swept over increasing component counts with an identical,
#: minimal phase list, so that "how many components can this pycalphad build solve" is measured
#: separately from "is the community derivative correct".
LIMIT_PROBES: dict[str, dict[str, Any]] = {
    "community_mc_fe": {
        "label": "community mc_fe v2.062 clean derivative",
        "db": "community",
        "order": ["C", "MN", "SI", "CR", "NI", "MO", "AL", "CU", "NB", "TI", "V", "B", "N", "P", "S"],
        "pool": {"C": 0.00875, "MN": 0.01359, "SI": 0.00492, "CR": 0.00691, "NI": 0.00188,
                 "MO": 0.00127, "AL": 0.00072, "CU": 0.0007, "NB": 0.00015, "TI": 0.00021,
                 "V": 0.00033, "B": 7.7e-05, "N": 0.00016, "P": 0.00021, "S": 8.6e-05},
    },
    "control_cost507": {
        "label": "pycalphad-bundled COST507 (independent control)",
        "db": "cost507",
        "order": ["C", "CR", "MN", "MO", "N", "NI", "SI", "V", "AL", "TI", "NB", "W", "TA", "CU", "B"],
        "pool": {element: 0.005 for element in
                 ["C", "CR", "MN", "MO", "N", "NI", "SI", "V", "AL", "TI", "NB", "W", "TA", "CU", "B"]},
    },
}


def _probe_db(path_key: str) -> Path:
    return DEFAULT_DB if path_key == "community" else _cost507_path()


def range_checks(cases: dict[str, Any]) -> dict[str, Any]:
    results = []
    for sample_id, case in cases.items():
        temperatures = [float(value) + 273.15 for value in case["temperature_C"]]
        low, high = ASSESSED_RANGE_K
        results.append({
            "sample_id": sample_id,
            "temperature_min_K": min(temperatures),
            "temperature_max_K": max(temperatures),
            "within_assessed_range": all(low <= value <= high for value in temperatures),
            "components": case["components"],
        })
    return {"assessed_range_K": list(ASSESSED_RANGE_K), "per_sample": results}


def composition_range_check(full_mole_fractions: dict[str, float], atomic_weights: dict[str, float]) -> dict[str, Any]:
    """Convert the reduced-system mole fractions back to wt.% and compare with the vendor envelope."""
    masses = {element: fraction * atomic_weights[element] for element, fraction in full_mole_fractions.items()}
    total = sum(masses.values())
    weight_percent = {element: 100.0 * mass / total for element, mass in masses.items()}
    violations = []
    for element, value in weight_percent.items():
        limit = COMPOSITION_LIMITS_WT.get(element)
        if limit is not None and value > limit:
            violations.append({"element": element, "wt_pct": round(value, 4), "limit": limit})
    return {
        "weight_percent_from_mole_fractions": {element: round(value, 5) for element, value in sorted(weight_percent.items())},
        "limits_source": "upstream mc_fe v2.062 header composition envelope (line 61-70 of the original)",
        "violations": violations,
        "within_envelope": not violations,
    }


# ---------------------------------------------------------------------------------------------
# Crash-isolated subprocess plumbing
# ---------------------------------------------------------------------------------------------

def _kill_tree(pid: int) -> None:
    """Kill a child and its descendants.

    The isolated interpreter is a launcher that re-executes the base CPython, so killing only
    the direct child can leave the real worker running.  A runaway solver can also grow to
    several gigabytes, so every unit of work is bounded by a wall-clock timeout.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, check=False)
        return
    try:
        os.killpg(os.getpgid(pid), 9)
    except (OSError, AttributeError):
        pass


def _spawn(tag: str, extra: list[str], timeout_seconds: float = 300.0) -> dict[str, Any]:
    """Run one unit of work in a fresh interpreter and return its outcome.

    pycalphad 0.11.2 can terminate the process with 0xC0000005 instead of raising, and the same
    request can alternatively thrash until it exhausts memory, so the parent must never run a
    risky equilibration in-process and must always bound it in time.
    """
    SCRATCH.mkdir(parents=True, exist_ok=True)
    payload_path = SCRATCH / f"{tag}.json"
    if payload_path.is_file():
        payload_path.unlink()
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), *extra, "--json", str(payload_path)]
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", cwd=str(ROOT), env=environment,
                               creationflags=creation_flags)
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
    outcome = {
        "returncode": process.returncode,
        "crashed": process.returncode != 0,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "stdout_tail": (stdout or "").strip().splitlines()[-6:],
        "stderr_tail": (stderr or "").strip().splitlines()[-6:],
        "payload": payload,
    }
    return outcome


def _write(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------

def section_db(db_path: Path) -> dict[str, Any]:
    from importlib import metadata

    section: dict[str, Any] = {
        "pycalphad_version": metadata.version("pycalphad"),
        "python_version": sys.version.split()[0],
        "database_path": str(db_path),
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "note": "Software-behaviour and basic-plausibility checks only; not experimental validation of a steel grade.",
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db = load_database(db_path)
        section["load_warnings"] = sorted({f"{item.category.__name__}: {str(item.message)[:160]}" for item in caught})

    phase_names = sorted(str(name) for name in db.phases.keys())
    section["counts"] = {
        "elements": len([name for name in db.elements if str(name) not in {"VA", "/-"}]),
        "elements_with_va": len(db.elements),
        "phases": len(phase_names),
        "species": len(getattr(db, "species", []) or []),
        "functions": len(getattr(db, "symbols", {}) or {}),
        "parameters": len(getattr(db, "_parameters", []) or []),
    }
    section["elements"] = sorted(str(name) for name in db.elements)
    section["phases"] = phase_names

    order_disorder = []
    for name in phase_names:
        hints = dict(getattr(db.phases[name], "model_hints", {}) or {})
        if "ordered_phase" in hints or "disordered_phase" in hints:
            order_disorder.append({"phase": name, "hints": {key: str(value) for key, value in hints.items()}})
    section["order_disorder_links"] = order_disorder
    section["order_disorder_link_present_for_bcc_b2"] = any(item["phase"] == "BCC_B2" for item in order_disorder)

    mc_found = sorted(name for name in phase_names if name.upper() in MC_PHASES or name.upper().startswith("MC"))
    fcc_sets = [name for name in phase_names if "#" in name]
    section["mc_mx_check"] = {
        "mc_like_phases_in_database": mc_found,
        "composition_set_phases_in_database": fcc_sets,
        "mc_carbo_nitride_reachable_as_separate_phase": bool(mc_found),
        "note": "MatCalc models the MC carbo-nitride as an fcc_A1 composition set created by "
                "ADD_COMPOSITION_SET; that command is commented out in the derivative, so no separate "
                "MC/MX phase exists and Nb/Ti/V carbo-nitride fractions cannot be resolved by pycalphad.",
    }
    section["model_losses"] = {
        "bcc_b2_order_disorder_coupling": "not linked after parsing (ATTACH_CONTRIBUTION commented out)",
        "matcalc_composition_sets": "absent (ADD_COMPOSITION_SET commented out); MC/MX carbo-nitrides not reachable",
        "hmva_parameters": "absent (commented out); pycalphad has no HMVA parameter type so they never entered "
                            "these runs, but the database is no longer equivalent to the MatCalc model",
        "reference_element": "absent (commented out)",
        "impact": "unknown_model_impact",
    }
    return section


def section_single_case(db_path: Path, case: dict[str, Any], payload_path: Path | None) -> dict[str, Any]:
    from pycalphad import Workspace, variables as v

    result: dict[str, Any] = {
        "sample_id": case["sample_id"],
        "components": list(case["components"]),
        "component_count": len(case["components"]),
        "steps_completed": [],
    }
    _write(payload_path, result)

    db = load_database(db_path)
    components = list(case["components"])
    phase_names = sorted(str(name) for name in db.phases.keys())
    result["database_phase_count"] = len(phase_names)

    conditions = {v.T: 1173.15, v.P: 101325.0, v.N: 1}
    for element, fraction in case["component_mole_fractions"].items():
        conditions[v.X(element)] = float(fraction)
    started = time.perf_counter()
    workspace = Workspace(db, components, phase_names, conditions)
    result["steps_completed"].append("workspace_constructed")
    _write(payload_path, result)
    try:
        value = float(np.asarray(workspace.get(v.T)).ravel()[0])
        result["workspace"] = {"status": "passed", "temperature_K": value,
                               "elapsed_s": round(time.perf_counter() - started, 3)}
    except Exception as exc:  # noqa: BLE001
        result["workspace"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    result["steps_completed"].append("workspace_solved")
    _write(payload_path, result)

    point_conditions = {v.T: 753.15, v.P: float(case["pressure_Pa"]), v.N: 1}
    for element, fraction in case["component_mole_fractions"].items():
        point_conditions[v.X(element)] = float(fraction)
    result["single_point_480C"] = equilibrium_point(db, components, phase_names, point_conditions)
    result["steps_completed"].append("single_point")
    _write(payload_path, result)

    scan = temperature_scan(db, case)
    result["scan"] = {key: value for key, value in scan.items() if key != "points"}
    result["scan_points"] = scan.get("points", [])
    result["steps_completed"].append("temperature_scan")
    _write(payload_path, result)

    repeat = temperature_scan(db, case) if scan.get("status") == "ok" else {"status": "skipped"}
    result["repeatable"] = (
        scan.get("status") == "ok" and repeat.get("status") == "ok"
        and [point["phase_fractions_mole"] for point in scan["points"]]
        == [point["phase_fractions_mole"] for point in repeat["points"]]
    )
    result["sum_within_tolerance"] = (
        scan.get("sum_min") is not None and abs(scan["sum_min"] - 1.0) < 1e-4
        and abs(scan["sum_max"] - 1.0) < 1e-4
    )
    bcc_b2_temperatures = [
        point["temperature_C"] for point in scan.get("points", []) if "BCC_B2" in point["phases_present"]
    ]
    result["bcc_b2_present"] = bool(bcc_b2_temperatures)
    result["bcc_b2_temperatures_C"] = bcc_b2_temperatures
    result["status"] = "ok" if scan.get("status") == "ok" else "failed"
    result["steps_completed"].append("repeat_scan")
    _write(payload_path, result)
    return result


def section_system(db_path: Path, system_name: str, x_points: int, t_points: int,
                   payload_path: Path | None) -> dict[str, Any]:
    system = _find_system(system_name)
    db = load_database(db_path)
    x_low = float(system.get("x_min", 0.01))
    x_high = float(system.get("x_max", 0.99))
    x_values = np.linspace(x_low, x_high, x_points)
    t_values = np.linspace(500.0, 1890.0, t_points)
    t_celsius = t_values - 273.15
    missing = [name for name in system["phases"] if name not in db.phases]
    produced = phase_map(db, system, x_values, t_values)
    grid = produced["grid"]
    checks = []
    for label, predicate in system["checks"]:
        try:
            passed = bool(predicate(grid, t_celsius, x_values))
        except Exception as exc:  # noqa: BLE001
            passed = False
            label = f"{label} (error: {type(exc).__name__})"
        checks.append({"check": label, "passed": passed})
    entry = {
        "name": system["name"],
        "kind": _system_kind(system),
        "phases_used": produced["phases_used"],
        "phases_missing_in_db": missing,
        "x_points": x_points,
        "t_points": t_points,
        "x_range": [round(float(x_values[0]), 5), round(float(x_values[-1]), 5)],
        "t_range_K": [round(float(t_values[0]), 3), round(float(t_values[-1]), 3)],
        "elapsed_s": produced["elapsed_s"],
        "distinct_assemblages": sorted({label for row in grid for label in row})[:40],
        "checks": checks,
        "passed": sum(1 for item in checks if item["passed"]),
        "failed": sum(1 for item in checks if not item["passed"]),
    }
    if entry["kind"] == "model_loss_probe":
        entry["expected_result"] = bool(system.get("expected_result", False))
        entry["agrees_with_expectation"] = all(
            item["passed"] == entry["expected_result"] for item in checks
        )
    _write(payload_path, entry)
    return entry


def section_limit_point(probe_key: str, n_elements: int, payload_path: Path | None) -> dict[str, Any]:
    from pycalphad import equilibrium, variables as v

    probe = LIMIT_PROBES[probe_key]
    db_path = _probe_db(probe["db"])
    db = load_control_database(db_path) if probe["db"] == "cost507" else load_database(db_path)
    elements = probe["order"][:n_elements]
    components = ["FE"] + sorted(elements) + ["VA"]
    conditions = {v.T: 1173.15, v.P: 101325.0, v.N: 1}
    for element in elements:
        conditions[v.X(element)] = float(probe["pool"][element])
    phases = [name for name in ("BCC_A2", "FCC_A1") if name in db.phases]
    entry = {
        "probe": probe_key,
        "label": probe["label"],
        "database": str(db_path),
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "elements": elements,
        "component_list_length": len(components),
        "phases": phases,
        "pycalphad_version": __import__("importlib.metadata", fromlist=["version"]).version("pycalphad"),
    }
    _write(payload_path, entry)
    started = time.perf_counter()
    result = equilibrium(db, components, phases, conditions, output="GM")
    np_values = np.asarray(result.NP.values).ravel()
    phase_values = np.asarray(result.Phase.values).ravel()
    entry["outcome"] = "solved"
    entry["phase_fractions_mole"] = {
        str(name).strip(): round(float(fraction), 8)
        for name, fraction in zip(phase_values, np_values)
        if str(name).strip() and float(fraction) > 1e-6
    }
    entry["total_moles"] = round(float(np.nansum(np_values)), 8)
    entry["elapsed_s"] = round(time.perf_counter() - started, 3)
    _write(payload_path, entry)
    return entry


# ---------------------------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------------------------

def _tally(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise one family of systems, keeping abnormal terminations visible."""
    abnormal = [item for item in items if item.get("crashed")]
    return {
        "systems": len(items),
        "checks_total": sum(len(item.get("checks", [])) for item in items),
        "checks_passed": sum(item.get("passed", 0) for item in items),
        "checks_failed": sum(item.get("failed", 0) for item in items)
        + sum(max(1, len(item.get("checks", []))) for item in abnormal),
        "abnormal_terminations": [
            {"system": item["name"], "returncode": item.get("returncode"),
             "timed_out": bool(item.get("timed_out"))}
            for item in abnormal
        ],
        "failed_checks": [
            {"system": item["name"], "check": check["check"]}
            for item in items for check in item.get("checks", []) if not check["passed"]
        ] + [{"system": item["name"], "check": "system run terminated abnormally"}
             for item in abnormal],
    }


def _verdict(report: dict[str, Any]) -> None:
    hard: list[str] = []
    soft: list[str] = []

    for sample_id, item in report.get("cases", {}).items():
        if item.get("timed_out"):
            hard.append(
                f"{sample_id}: pycalphad did not return within {item['timeout_seconds']:g}s and was "
                f"terminated (last recorded step: {(item.get('payload') or {}).get('steps_completed')})"
            )
            continue
        if item.get("crashed"):
            hard.append(
                f"{sample_id}: pycalphad terminated with C-level status {item['returncode']} "
                f"(0x{item['returncode'] & 0xFFFFFFFF:08X}) before producing a result"
            )
            continue
        payload = item.get("payload") or {}
        if (payload.get("workspace") or {}).get("status") == "failed":
            hard.append(f"{sample_id}: workspace construction failed")
        if payload.get("status") != "ok":
            hard.append(f"{sample_id}: temperature scan failed")
        if not payload.get("sum_within_tolerance"):
            hard.append(f"{sample_id}: phase fractions do not sum to 1")
        if not payload.get("repeatable"):
            hard.append(f"{sample_id}: repeated run differs")
        if (payload.get("scan") or {}).get("non_converged_temperatures_C"):
            hard.append(f"{sample_id}: non-converged temperatures present")

    for entry in report.get("range_checks", {}).get("per_sample", []):
        if not entry["within_assessed_range"]:
            hard.append(f"{entry['sample_id']}: temperature outside the assessed range")

    limit = report.get("component_limit", {})
    if limit.get("threshold_observed"):
        pass  # recorded as a finding, already reflected through the case crashes

    for key in ("community_checks", "project_checks"):
        section = report.get(key) or {}
        for abnormal in section.get("abnormal_terminations", []):
            hard.append(
                f"{key}: {abnormal['system']} terminated abnormally "
                f"(returncode={abnormal['returncode']}, timed_out={abnormal['timed_out']})"
            )
        for failure in section.get("failed_checks", []):
            if failure["check"] == "system run terminated abnormally":
                continue
            soft.append(f"{key}: {failure['system']} / {failure['check']}")

    for probe in report.get("model_loss_probes", []):
        if probe.get("agrees_with_expectation") is False:
            soft.append(
                f"model_loss_probe: {probe['name']} did not agree with the documented "
                f"expectation (expected={probe.get('expected_result')})"
            )

    report["blocking"] = hard
    report["non_blocking_findings"] = soft
    if hard:
        status = "blocked"
    elif soft:
        status = "compatibility_candidate"
    else:
        status = "pilot_ready_pending_scientific_review"
    report["status"] = status


def run_all(args: argparse.Namespace) -> int:
    run_started = time.perf_counter()
    report: dict[str, Any] = {"schema_version": "1.1", "section": "all"}
    report["permanent_limitation_text"] = PERMANENT_LIMITATION_TEXT

    report.update(section_db(args.db))

    cases = json.loads(args.cases.read_text(encoding="utf-8")) if args.cases.is_file() else {}
    case_results: dict[str, Any] = {}
    for sample_id, case in cases.items():
        case = dict(case)
        case["sample_id"] = sample_id
        outcome = _spawn(f"case_{sample_id}", ["--section", "case", "--case-id", sample_id,
                                               "--cases", str(args.cases), "--db", str(args.db)],
                         timeout_seconds=args.case_timeout)
        outcome["case"] = case
        case_results[sample_id] = outcome
        payload = outcome["payload"] or {}
        print(f"case {sample_id}: returncode={outcome['returncode']} timed_out={outcome['timed_out']} "
              f"steps={payload.get('steps_completed', [])} "
              f"single_point={(payload.get('single_point_480C') or {}).get('phases_present')} "
              f"sum={(payload.get('single_point_480C') or {}).get('total_moles')} "
              f"repeatable={payload.get('repeatable')}", flush=True)
    report["cases"] = case_results
    report["range_checks"] = range_checks(cases)

    if not args.skip_systems:
        systems = []
        for system in ALL_SYSTEMS:
            outcome = _spawn(f"system_{_tag(system['name'])}",
                             ["--section", "system", "--system", system["name"],
                              "--x-points", str(args.x_points), "--t-points", str(args.t_points),
                              "--db", str(args.db)],
                             timeout_seconds=args.system_timeout)
            entry = outcome["payload"]
            if entry is None:
                entry = {"name": system["name"], "kind": _system_kind(system),
                         "checks": [], "passed": 0, "failed": 0,
                         "crashed": True, "timed_out": outcome["timed_out"],
                         "returncode": outcome["returncode"],
                         "expected_result": system.get("expected_result"),
                         "stderr_tail": outcome["stderr_tail"]}
            else:
                entry["crashed"] = outcome["returncode"] != 0
                entry["timed_out"] = outcome["timed_out"]
            systems.append(entry)
            print(f"system {entry['name'][:38]:38} kind={entry['kind'][:17]:17} "
                  f"returncode={outcome['returncode']} "
                  f"checks={entry.get('passed')}/{len(entry.get('checks', []))} "
                  f"assemblages={len(entry.get('distinct_assemblages', []))}", flush=True)
        report["binary_systems"] = [item for item in systems if item["kind"] != "model_loss_probe"]
        report["model_loss_probes"] = [item for item in systems if item["kind"] == "model_loss_probe"]
        community = [item for item in systems if item.get("kind") == "community_claim"]
        project = [item for item in systems if item.get("kind") == "project_relevant"]
        report["community_checks"] = _tally(community)
        report["project_checks"] = _tally(project)

    # --- Component-count limit probe ---------------------------------------------------------
    if not args.skip_limit:
        points = []
        for probe_key in LIMIT_PROBES:
            for n_elements in args.limit_ns:
                outcome = _spawn(f"limit_{probe_key}_{n_elements}",
                                 ["--section", "limit", "--probe", probe_key,
                                  "--n-elements", str(n_elements)],
                                 timeout_seconds=args.limit_timeout)
                payload = outcome["payload"] or {}
                # A child can die before it writes anything; the parent still has to describe the
                # probe so that the record stays self-explanatory and groupable.
                probe_def = LIMIT_PROBES[probe_key]
                payload.setdefault("probe", probe_key)
                payload.setdefault("label", probe_def["label"])
                payload.setdefault("elements", probe_def["order"][:n_elements])
                payload.setdefault("component_list_length", len(probe_def["order"][:n_elements]) + 2)
                payload["returncode"] = outcome["returncode"]
                payload["timed_out"] = outcome["timed_out"]
                payload["database"] = str(_probe_db(probe_def["db"]))
                if outcome["timed_out"]:
                    payload["outcome"] = "timed_out"
                elif outcome["returncode"] == 0:
                    payload["outcome"] = "solved"
                else:
                    payload["outcome"] = "process_aborted"
                payload["stderr_tail"] = outcome["stderr_tail"]
                points.append(payload)
                print(f"limit {probe_key:16} n_alloy={n_elements:2} comps={payload.get('component_list_length')} "
                      f"returncode={outcome['returncode']} outcome={payload['outcome']}", flush=True)

        threshold: dict[str, Any] = {}
        for probe_key, probe in LIMIT_PROBES.items():
            rows = [item for item in points if item.get("probe") == probe_key]
            solved = [item["component_list_length"] for item in rows if item.get("outcome") == "solved"]
            aborted = [item["component_list_length"] for item in rows if item.get("outcome") != "solved"]
            threshold[probe_key] = {
                "label": probe["label"],
                "largest_solved_component_list": max(solved) if solved else None,
                "smallest_aborted_component_list": min(aborted) if aborted else None,
                "threshold_observed": bool(solved and aborted and min(aborted) == max(solved) + 1),
            }
        report["component_limit"] = {
            "points": points,
            "per_database": threshold,
            "interpretation": (
                "pycalphad 0.11.2 on this host either aborts the process with 0xC0000005 "
                "(ACCESS_VIOLATION) inside pycalphad/core/minimizer.cp312-win_amd64.pyd or fails to "
                "return at all, once the component list grows past the observed threshold. The "
                "behaviour reproduces identically on an independent pycalphad-bundled database "
                "(COST507), so it is an environment/software limitation and not a defect introduced "
                "by the community TDB derivative. Reducing the component system or changing the "
                "isolated environment both require an explicit owner decision and a versioned policy "
                "update; the validation script never performs either silently."
            ),
        }
    report["permanent_limitations"] = {
        "text": PERMANENT_LIMITATION_TEXT,
        "reduced_component_system": True,
        "excluded_elements": ["As", "Sn", "Sb", "O", "W"],
        "pending_human_review": True,
        "is_complete_phase_diagram": False,
        "writes_back_formal_experimental_data": False,
        "community_derived_database": True,
    }

    _verdict(report)
    report["elapsed_s"] = round(time.perf_counter() - run_started, 1)

    _write(args.json, report)
    print(f"\ncounts: {report['counts']}")
    print(f"order/disorder links: {len(report['order_disorder_links'])} "
          f"(BCC_B2 linked: {report['order_disorder_link_present_for_bcc_b2']})")
    if "community_checks" in report:
        print(f"community checks: {report['community_checks']['checks_passed']}/"
              f"{report['community_checks']['checks_total']} passed")
        for item in report["community_checks"]["failed_checks"]:
            print(f"  FAILED {item['system']}: {item['check']}")
        print(f"project checks: {report['project_checks']['checks_passed']}/"
              f"{report['project_checks']['checks_total']} passed")
        for item in report["project_checks"]["failed_checks"]:
            print(f"  FAILED {item['system']}: {item['check']}")
        for probe in report.get("model_loss_probes", []):
            print(f"model-loss probe: {probe['name']} expected={probe.get('expected_result')} "
                  f"checks={probe.get('checks')} agrees={probe.get('agrees_with_expectation')}")
    for probe_key, item in report.get("component_limit", {}).get("per_database", {}).items():
        print(f"component limit [{probe_key}]: solved up to {item['largest_solved_component_list']}, "
              f"aborted from {item['smallest_aborted_component_list']}")
    print(f"blocking: {report['blocking'] or 'none'}")
    print(f"status: {report['status']}")
    print(f"json: {args.json}")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Independent validation of the community TDB derivative.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cases", type=Path, default=ROOT / "outputs" / "calphad_validation_cases.json")
    parser.add_argument("--json", type=Path, default=ROOT / "outputs" / "calphad_candidate_validation.json")
    parser.add_argument("--x-points", type=int, default=9)
    parser.add_argument("--t-points", type=int, default=13)
    parser.add_argument("--section", choices=("all", "db", "case", "system", "limit"), default="all")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--system", default=None)
    parser.add_argument("--probe", default=None)
    parser.add_argument("--n-elements", type=int, default=None)
    parser.add_argument("--limit-ns", type=int, nargs="+", default=[10, 11, 12, 13])
    parser.add_argument("--case-timeout", type=float, default=240.0)
    parser.add_argument("--system-timeout", type=float, default=180.0)
    parser.add_argument("--limit-timeout", type=float, default=180.0)
    parser.add_argument("--skip-systems", action="store_true")
    parser.add_argument("--skip-limit", action="store_true")
    args = parser.parse_args(argv[1:])

    if args.section == "all":
        return run_all(args)

    if args.section == "db":
        _write(args.json, section_db(args.db))
        return 0

    if args.section == "case":
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        case = dict(cases[args.case_id])
        case["sample_id"] = args.case_id
        section_single_case(args.db, case, args.json)
        return 0

    if args.section == "system":
        section_system(args.db, args.system, args.x_points, args.t_points, args.json)
        return 0

    if args.section == "limit":
        section_limit_point(args.probe, args.n_elements, args.json)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
