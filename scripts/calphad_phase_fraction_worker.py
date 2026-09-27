"""Isolated pycalphad worker for the T86 CALPHAD phase-fraction adapter.

This script is **never** imported by the Workbench application.  It is executed by the
separate interpreter configured in ``STEELAI_CALPHAD_PYTHON`` (or
``settings.toml [tools] calphad_python``) as:

    <isolated-python> -I scripts/calphad_phase_fraction_worker.py <request.json> <result.json>

Contract:

* The request is produced by :mod:`steelai.calphad_adapter` only after every gate in the
  main application passed (registered authorized TDB, matching SHA-256, element coverage,
  named Fe-balance confirmation, declared temperature range, isolated environment ready).
* The worker re-checks the pinned pycalphad version and the TDB SHA-256 and refuses to run
  if either changed after the gates were evaluated.
* Output is one entry per temperature with the mole fraction of each phase, aggregated by
  base phase name.  Nothing is written back to the research data layer.
* Exit code 0 with ``{"status": "ok", ...}`` on success; exit code 2 with
  ``{"status": "error", ...}`` when the calculation cannot produce a trustworthy result.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any


WORKER_SCHEMA_VERSION = "1.1"
#: Cap on single-temperature retries.  Each retry builds another phase record, and building many of
#: them in one interpreter trips the symengine LLVM JIT abort, so the retry count is bounded.
MAX_POINT_RETRIES = 8
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from steelai.calphad_adapter import summarize_phase_amounts  # noqa: E402


class WorkerError(RuntimeError):
    """A bounded, reportable worker failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_request(request: dict[str, Any]) -> None:
    if request.get("request_schema_version") != WORKER_SCHEMA_VERSION:
        raise WorkerError("CALPHAD-WORKER-SCHEMA-001", "请求 schema 版本不受支持。")
    units = request.get("units", {})
    if units.get("temperature_input") != "degC" or units.get("composition_input") != "wt_pct":
        raise WorkerError("CALPHAD-WORKER-UNIT-001", "输入单位声明不是 degC / wt_pct。")
    if units.get("output_phase_fraction") != "mole_fraction_of_phase":
        raise WorkerError("CALPHAD-WORKER-UNIT-002", "输出基准不是各相摩尔分数。")
    claims = request.get("claims", {})
    if claims.get("is_complete_phase_diagram") is not False:
        raise WorkerError("CALPHAD-WORKER-CLAIM-001", "请求不得声明这是完整相图。")
    components = request.get("components") or []
    if len(components) < 2:
        raise WorkerError("CALPHAD-WORKER-COMP-001", "组元少于 2 个，无法做多元平衡计算。")
    if not any(str(name).upper() == "FE" for name in components):
        raise WorkerError("CALPHAD-WORKER-COMP-002", "组元列表缺少 Fe。")
    fractions = request.get("component_mole_fractions") or {}
    if not fractions:
        raise WorkerError("CALPHAD-WORKER-COMP-003", "缺少非 Fe 组元的摩尔分数。")
    total = sum(float(value) for value in fractions.values())
    if total >= 1.0 or total < 0:
        raise WorkerError("CALPHAD-WORKER-COMP-004", f"非 Fe 组元摩尔分数合计 {total:.6f} 不在 [0, 1) 内。")
    temperatures_K = (request.get("temperature") or {}).get("values_K") or []

    # T86 phase 5: the formal mode runs exactly one temperature per process.  A multi-temperature
    # request in this mode would silently reintroduce the warm-start path, so it is rejected.
    solver_mode = str(request.get("solver_mode", "") or "batch_workspace_warm_start")
    if solver_mode == "independent_single_point_process_v1":
        if len(temperatures_K) != 1:
            raise WorkerError(
                "CALPHAD-WORKER-MODE-001",
                "独立单点模式要求每个进程只求解一个温度点，请求包含 "
                f"{len(temperatures_K)} 个温度点。",
            )
        if request.get("single_point_process") is not True:
            raise WorkerError("CALPHAD-WORKER-MODE-002", "独立单点模式必须声明 single_point_process=true。")
        if request.get("no_warm_start") is not True:
            raise WorkerError("CALPHAD-WORKER-MODE-002", "独立单点模式必须声明 no_warm_start=true。")
    elif len(temperatures_K) < 2:
        raise WorkerError("CALPHAD-WORKER-RANGE-001", "温度点少于 2 个。")
    database = request.get("database") or {}
    if not database.get("path"):
        raise WorkerError("CALPHAD-WORKER-TDB-001", "请求缺少 TDB 路径。")
    if not database.get("sha256"):
        raise WorkerError("CALPHAD-WORKER-TDB-002", "请求缺少 TDB SHA-256。")

    # T86 phase 4: the run is a fixed, approved reduced-system run.  The worker re-checks the profile
    # and the named approval so a hand-built request cannot bypass the adapter's gates.
    phases = request.get("phases")
    if not isinstance(phases, list) or not phases:
        raise WorkerError(
            "CALPHAD-WORKER-PHASE-001",
            "请求缺少固定相集合（phases）。本阶段只允许经过验证的固定相集合，不接受空相列表或全库相。",
        )
    component_profile = request.get("component_profile") or {}
    if not str(component_profile.get("profile_id", "")).strip():
        raise WorkerError("CALPHAD-WORKER-PHASE-003", "请求缺少 component_profile。")
    phase_profile = request.get("phase_profile") or {}
    if not str(phase_profile.get("profile_id", "")).strip():
        raise WorkerError("CALPHAD-WORKER-PHASE-003", "请求缺少 phase_profile。")
    approval = request.get("reduced_system_approval") or {}
    # The public synthetic portfolio demo makes no scientific claim, so it carries explicit
    # not-for-science flags instead of a named scientific approval.  A real-sample run still needs
    # the named approval, and the two cannot be combined.
    if request.get("portfolio_demo") is True:
        if request.get("public_synthetic_input") is not True:
            raise WorkerError("CALPHAD-WORKER-DEMO-001", "演示请求必须声明 public_synthetic_input=true。")
        if request.get("not_for_scientific_conclusion") is not True:
            raise WorkerError("CALPHAD-WORKER-DEMO-001",
                              "演示请求必须声明 not_for_scientific_conclusion=true。")
        if not str(request.get("demo_policy_id", "")).strip():
            raise WorkerError("CALPHAD-WORKER-DEMO-001", "演示请求必须声明 demo_policy_id。")
        if approval.get("no_scientific_approval_required") is not True:
            raise WorkerError("CALPHAD-WORKER-DEMO-002",
                              "演示请求必须显式声明不需要具名科研审批。")
    elif not str(approval.get("reviewer_id", "")).strip():
        raise WorkerError("CALPHAD-WORKER-APPROVAL-001", "请求缺少具名批准人 reviewer_id。")
    elif not str(approval.get("approved_at", "")).strip():
        raise WorkerError("CALPHAD-WORKER-APPROVAL-001", "请求缺少批准时间。")
    elif not str(approval.get("approval_reason", "")).strip():
        raise WorkerError("CALPHAD-WORKER-APPROVAL-001", "请求缺少批准理由。")
    elif approval.get("acknowledged") is not True:
        raise WorkerError("CALPHAD-WORKER-APPROVAL-001", "请求未记录确认文本已被勾选。")

    # Excluded elements must not reach the calculation in any form.
    included = {str(profile_component).upper() for profile_component in component_profile.get("included_elements", []) or []}
    declared = {str(name).upper() for name in components}
    request_fractions = {str(name).upper() for name in fractions}
    intruders = sorted((declared | request_fractions) - included - {"VA"})
    if intruders:
        raise WorkerError(
            "CALPHAD-WORKER-COMP-005",
            "请求中出现了缩减体系之外的元素（被排除元素不得进入计算）：" + ", ".join(intruders),
        )


def _check_database_and_version(request: dict[str, Any]) -> tuple[Path, str]:
    database = request["database"]
    database_path = Path(str(database["path"])).expanduser()
    if not database_path.is_file():
        raise WorkerError("CALPHAD-WORKER-TDB-003", "TDB 文件不存在。")
    actual = _sha256_file(database_path)
    if actual != str(database["sha256"]):
        raise WorkerError("CALPHAD-WORKER-TDB-004", "TDB SHA-256 与登记不一致，拒绝计算。")

    installed = metadata.version("pycalphad")
    expected = str(request.get("pycalphad_version") or "")
    if expected and installed != expected:
        raise WorkerError(
            "CALPHAD-WORKER-VERSION-001",
            f"隔离环境 pycalphad {installed} 与登记版本 {expected} 不一致。",
        )
    return database_path, installed


def _load_database(path: Path):
    """Load a TDB from its own bytes instead of letting pycalphad pick the encoding.

    ``Database(path)`` opens the file with the platform locale encoding, which fails on a
    GBK-locale Windows host for a utf-8 or cp1252 database.  The compatibility gate for the
    registered candidate is recorded against an explicit decode, so the product path has to use
    the same rule; otherwise the gate would pass while the feature silently could not run.
    """
    from pycalphad import Database  # type: ignore[import-not-found]

    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return Database.from_string(text, fmt="tdb")


def _run(request: dict[str, Any]) -> dict[str, Any]:
    database_path, installed_version = _check_database_and_version(request)
    solver_mode = str(request.get("solver_mode", "") or "batch_workspace_warm_start")

    from pycalphad import equilibrium, variables as v  # type: ignore[import-not-found]

    temperatures_K = [float(value) for value in request["temperature"]["values_K"]]
    components = [str(name).upper() for name in request["components"]]
    mole_fractions = {str(name).upper(): float(value) for name, value in request["component_mole_fractions"].items()}
    pressure = float(request.get("pressure_Pa", 101325))

    database = _load_database(database_path)
    available = {str(name) for name in database.phases.keys()}
    requested_phases = [str(name) for name in request["phases"]]
    missing_phases = [name for name in requested_phases if name not in available]
    if missing_phases:
        raise WorkerError(
            "CALPHAD-WORKER-PHASE-002",
            "TDB 中不存在以下固定相集合成员，拒绝计算（不得自动替换相名、不得改写 TDB 强行启用）："
            + ", ".join(missing_phases),
        )
    phases = requested_phases
    if not phases:
        raise WorkerError("CALPHAD-WORKER-TDB-005", "TDB 没有解析出任何相。")
    missing_components = sorted(name for name in components if name not in {str(k).upper() for k in database.elements})
    if missing_components:
        raise WorkerError(
            "CALPHAD-WORKER-TDB-006",
            "TDB 未定义以下组元，拒绝计算：" + ", ".join(missing_components),
        )

    conditions: dict[Any, Any] = {v.T: temperatures_K, v.P: pressure}
    for element, fraction in mole_fractions.items():
        conditions[v.X(element)] = fraction
    # pycalphad needs the vacancy species in the component list for the substitutional phases of this
    # database.  Leaving it out does NOT raise: it silently returns a physically wrong assemblage
    # (LIQUID stable at 400 degC for a low-alloy steel) whose phase fractions still sum to 1, so it
    # would pass a sum-only check.  VA is therefore always added when the database declares it.
    pycalphad_components = list(components)
    if "VA" in {str(name).upper() for name in database.elements} \
            and "VA" not in {name.upper() for name in pycalphad_components}:
        pycalphad_components.append("VA")
    result = equilibrium(database, pycalphad_components, phases, conditions, verbose=False)

    temperature_grid = [float(value) for value in list(result.T.values.ravel())]
    phase_grid = result.Phase.values.reshape(-1, result.Phase.values.shape[-1])
    amount_grid = result.NP.values.reshape(-1, result.NP.values.shape[-1])
    if len(temperature_grid) != phase_grid.shape[0] or len(temperature_grid) != amount_grid.shape[0]:
        raise WorkerError(
            "CALPHAD-WORKER-SHAPE-001",
            "平衡结果网格与温度坐标不一致，无法安全对齐。",
        )

    # The multi-temperature batch solver warm-starts each point from the previous one and, near a
    # two-phase boundary, occasionally returns no stable phase at all.  A single-temperature call at
    # the same conditions does converge, so any such point is recomputed on its own and the retry is
    # recorded.  This changes nothing about the physics; it only avoids warm-start contamination.
    retried: list[float] = []
    retry_failures: list[float] = []
    for index, temperature_K in enumerate(temperature_grid):
        summary = summarize_phase_amounts(phase_grid[index], amount_grid[index])
        if summary["phase_fractions_mole"]:
            continue
        if len(retried) >= MAX_POINT_RETRIES:
            retry_failures.append(round(temperature_K - 273.15, 6))
            continue
        point_conditions = dict(conditions)
        point_conditions[v.T] = float(temperature_K)
        point_result = equilibrium(database, pycalphad_components, phases, point_conditions, verbose=False)
        point_phase = point_result.Phase.values.reshape(-1, point_result.Phase.values.shape[-1])
        point_amount = point_result.NP.values.reshape(-1, point_result.NP.values.shape[-1])
        if not summarize_phase_amounts(point_phase[0], point_amount[0])["phase_fractions_mole"]:
            retry_failures.append(round(temperature_K - 273.15, 6))
            continue
        phase_grid[index] = point_phase[0]
        amount_grid[index] = point_amount[0]
        retried.append(round(temperature_K - 273.15, 6))

    points: list[dict[str, Any]] = []
    problems: list[str] = []
    for index, temperature_K in enumerate(temperature_grid):
        if temperature_K != temperature_K:  # NaN
            problems.append(f"第 {index + 1} 个网格点温度缺失。")
            continue
        summary = summarize_phase_amounts(phase_grid[index], amount_grid[index])
        if not summary["phase_fractions_mole"]:
            problems.append(f"{temperature_K:.2f} K 没有任何相摩尔数，平衡求解可能未收敛。")
            continue
        points.append({
            "temperature_C": round(temperature_K - 273.15, 6),
            "temperature_K": round(temperature_K, 6),
            "total_moles": round(float(summary["total_moles"]), 12),
            "phase_fractions_mole": {name: round(value, 10) for name, value in summary["phase_fractions_mole"].items()},
            "raw_phase_amounts_mole": {name: round(value, 12) for name, value in summary["raw_phase_amounts_mole"].items()},
            "phases_present": summary["phases_present"],
        })

    if problems:
        raise WorkerError(
            "CALPHAD-WORKER-SOLVE-001",
            "；".join(problems)
            + f"（多温度批量求解未收敛；已单独重算 {len(retried)} 个温度点"
            + (f"：{retried}" if retried else "")
            + f"，重算后仍未收敛 {len(retry_failures)} 个"
            + (f"：{retry_failures}" if retry_failures else "")
            + "）",
        )

    points.sort(key=lambda item: item["temperature_C"])
    requested = sorted(round(value - 273.15, 6) for value in temperatures_K)
    returned = [point["temperature_C"] for point in points]
    if returned != requested:
        raise WorkerError(
            "CALPHAD-WORKER-TEMPERATURE-001",
            "返回的温度点集合与请求不一致，拒绝给出结果。",
        )
    return {
        "worker_schema_version": WORKER_SCHEMA_VERSION,
        "status": "ok",
        "pycalphad_version": installed_version,
        "python_version": sys.version.split()[0],
        "phase_count": len(phases),
        "phases": phases,
        "components": components,
        "pycalphad_components": pycalphad_components,
        "solver_mode": solver_mode,
        "single_point_process": bool(request.get("single_point_process")),
        "portfolio_demo": bool(request.get("portfolio_demo")),
        "public_synthetic_input": bool(request.get("public_synthetic_input")),
        "not_for_scientific_conclusion": bool(request.get("not_for_scientific_conclusion")),
        "point_index": request.get("point_index"),
        "point_count": request.get("point_count"),
        "temperature_points": len(points),
        "component_profile_id": (request.get("component_profile") or {}).get("profile_id"),
        "phase_profile_id": (request.get("phase_profile") or {}).get("profile_id"),
        "points": points,
        "warnings": [],
        "non_converged_retried_temperatures_C": retried,
        "non_converged_failed_temperatures_C": retry_failures,
        "retry_method": "single_temperature_equilibrium_without_warm_start",
    }


def _memory_message(exc: BaseException, request: dict[str, Any]) -> str:
    """Explain a solver memory exhaustion in terms of the measured capability limit."""
    components = [str(name).upper() for name in (request.get("components") or [])]
    return (
        f"平衡求解所需的初始组成点网格超出可用内存（{exc}）。请求的组元列表长度为 {len(components)}"
        f"（{', '.join(components) or '未知'}）。pycalphad 0.11.2 在本机对组元数较多的体系构造初始点时"
        "规模急剧增长；实测组元列表长度 ≤13（Fe + 11 个合金元素 + VA）可解，≥14 时必定失败"
        "（内存耗尽，或被 pycalphad 的 minimizer 原生扩展中止进程）。该限制在 pycalphad 自带的独立"
        "数据库 COST507 上同样复现，因此属于隔离环境/软件能力限制，不是本数据库的内容问题。"
        "如需减少组元、限制相列表或更换隔离环境，必须由具名负责人批准并同步更新受控元素排除声明；"
        "Worker 不会自行降级成分体系。"
    )


def main(argv: list[str]) -> int:
    # Error text is Chinese; make stderr UTF-8 safe even on a GBK console.
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError, ValueError):
        pass
    if len(argv) != 3:
        print("usage: calphad_phase_fraction_worker.py <request.json> <result.json>", file=sys.stderr)
        return 2
    request_path = Path(argv[1])
    result_path = Path(argv[2])
    started = time.perf_counter()
    request: dict[str, Any] = {}
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise WorkerError("CALPHAD-WORKER-SCHEMA-002", "请求不是 JSON 对象。")
        _validate_request(request)
        payload = _run(request)
        exit_code = 0
    except WorkerError as exc:
        payload = {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "status": "error",
            "error_code": exc.code,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        exit_code = 2
        print(f"{exc.code}: {exc}", file=sys.stderr)
    except MemoryError as exc:
        payload = {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "status": "error",
            "error_code": "CALPHAD-WORKER-MEMORY-001",
            "error_type": type(exc).__name__,
            "error_message": _memory_message(exc, request),
            "component_count": len(request.get("components") or []),
        }
        exit_code = 2
        print(f"CALPHAD-WORKER-MEMORY-001: {exc}", file=sys.stderr)
    except Exception as exc:  # any pycalphad or numeric failure becomes a bounded record
        payload = {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "status": "error",
            "error_code": "CALPHAD-WORKER-UNEXPECTED-001",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        exit_code = 2
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)

    payload["elapsed_s"] = round(time.perf_counter() - started, 3)
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
