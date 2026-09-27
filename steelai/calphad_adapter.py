"""Optional CALPHAD phase-fraction adapter (T86) for the registered pycalphad candidate.

Phase 1 scope: for one fixed sample composition, compute and show the equilibrium
phase mole fractions on a temperature sweep at fixed pressure.

Boundaries enforced here (all of them fail closed):

* The Workbench core never imports pycalphad.  Thermodynamics only runs in a separate
  interpreter configured through ``STEELAI_CALPHAD_PYTHON``, and only after every gate
  below passes.  Without an isolated environment the existing Physics formulas keep
  working unchanged, and no requirement file is touched.
* A TDB must be registered locally with its source, authorization basis, covered
  elements and a matching SHA-256 before anything is computed.
* An element that is non-zero in the composition but missing from the TDB blocks the
  calculation.  There is no override, no silent omission and no zero fill.
* A declared element with no value is never treated as zero.  It either needs a value
  or a named human declaration that it is excluded from the component set.
* Fe may only be used as the balance after a named user explicitly confirms it.
* The temperature input is ``degC``, the composition input is ``wt_pct`` and the output
  is the **mole fraction of each phase**, not a mass fraction.  The result is a model
  prediction awaiting human review and is never written back to the processed research
  data layer.  The curve is not a complete phase diagram.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from steelai.governance.serialization import digest_value, sha256_file
from steelai.paths import OUTPUTS, ROOT


ADAPTER_VERSION = "1.0"
CONFIG_PATH = ROOT / "config" / "calphad_adapter_v1.0.json"
TDB_TEMPLATE_PATH = ROOT / "config" / "calphad_tdb.example.json"
DEFAULT_TDB_REGISTRY_PATH = ROOT / "config" / "calphad_tdb.local.json"
WORKER_PATH = ROOT / "scripts" / "calphad_phase_fraction_worker.py"
RUN_SCRATCH_ROOT = OUTPUTS / "calphad_runs"

FEATURE_ENV = "STEELAI_CALPHAD_ENABLED"
INTERPRETER_ENV = "STEELAI_CALPHAD_PYTHON"
TDB_REGISTRY_ENV = "STEELAI_CALPHAD_TDB_REGISTRY"
DEFAULT_INTERPRETER_RELATIVE = Path(".venv-pycalphad") / "Scripts" / "python.exe"

DISABLE_VALUES = {"0", "false", "no", "off"}

#: Composition columns that are not chemical elements.
NON_ELEMENT_COLUMNS = {"sample_id", "source_status", "specimen_id", "notes"}
ELEMENT_SYMBOL = re.compile(r"^[A-Z][a-z]?$")
#: pycalphad phase names may carry a composition-set suffix such as ``FCC_A1#2``.
PHASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+(#\d+)?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
#: A named approval must carry an explicit date (or ISO 8601 date-time) supplied by the reviewer.
ISO_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")

REQUIRED_TDB_FIELDS = {
    "database_id",
    "path",
    "sha256",
    "format",
    "provider",
    "version_or_date",
    "license_or_authorization",
    "authorization_status",
    "authorized_by",
    "authorized_at",
    "applicable_steel_grades",
    "covered_elements",
    "covered_phases",
    "declared_temperature_range_C",
    "citation",
    "pycalphad_compatibility",
}
ALLOWED_TDB_FORMAT = "thermo-calc_tdb"
REQUIRED_TDB_AUTHORIZATION = "user_confirmed_authorized_for_this_steel_grade"
COMPATIBILITY_PASSED = "passed"

RESULT_TYPE = "model_prediction_not_experimental_measurement"
REVIEW_STATUS = "pending_human_review"
CURVE_LABEL = "固定成分下的相分数—温度截面曲线"

#: The limitation text that every export must carry (T86 phase 2, item 4).  It is recorded in
#: the exclusion policy as well, so a change of wording is a versioned change.
DEFAULT_LIMITATION_NOTICE_ZH = (
    "本结果是基于 pycalphad 0.11.2 与 mc_fe v2.062 的缩减成分体系平衡热力学预测。"
    "R-DQ 中 As、Sn、Sb 未被数据库建模；O、W 因缺少测量值未进入计算。"
    "结果不能用于判断这些元素对偏聚、夹杂、晶界脆化、相稳定性或性能的影响。"
)
DEFAULT_LIMITATION_NOTICE_EN = (
    "This result is an equilibrium thermodynamic prediction for a REDUCED component system, "
    "computed with pycalphad 0.11.2 and mc_fe v2.062. As, Sn and Sb are not modelled by the "
    "database for R-DQ, and O and W are not part of the calculation because no measured values "
    "exist. The result must not be used to judge the effect of these elements on segregation, "
    "inclusions, grain-boundary embrittlement, phase stability or properties."
)

#: Outcome categories for a controlled element exclusion.  A bare "ignore element" switch is
#: deliberately not implemented: only (sample, element, category) triples listed in the versioned
#: exclusion policy may be excluded, and every exclusion is recorded per run.
#:
#: ``capacity_reduction`` is the T86 phase-4 category: the element HAS a measured non-zero value and
#: IS covered by the database, but is excluded because the fixed reduced-system profile keeps the
#: component list within the measured pycalphad solver capacity limit.
ALLOWED_EXCLUSION_CATEGORIES = ("database_not_covered", "measured_zero", "input_unknown",
                                "capacity_reduction")
CAPACITY_REDUCTION_CATEGORY = "capacity_reduction"
CAPACITY_REDUCTION_ELEMENTS = ("B", "N", "P", "S")

EXCLUSION_POLICY_PATH = ROOT / "config" / "calphad_exclusion_policy_v1.2.json"
EXCLUSION_TEMPLATE_PATH = ROOT / "config" / "calphad_exclusions.example.json"

#: T86 phase 4: the fixed, versioned reduced component system and fixed phase range.
REDUCED_SYSTEM_POLICY_PATH = ROOT / "config" / "calphad_reduced_system_v1.0.json"
REDUCED_SYSTEM_POLICY_ID = "SteelAI-CALPHAD-Reduced-System-Policy-v1.0"
COMPONENT_PROFILE_ID = "steel_matrix_equilibrium_v1"
COMPONENT_PROFILE_VERSION = "1.0"
PHASE_PROFILE_ID = "steel_matrix_major_carbides_v1"
PHASE_PROFILE_VERSION = "1.0"
#: The profile is validated against these module constants, so silently editing the policy file to a
#: different element or phase set fails closed instead of widening the calculation.
REQUIRED_MATRIX_ELEMENTS = ("Al", "C", "Cr", "Cu", "Fe", "Mn", "Mo", "Nb", "Ni", "Si", "Ti", "V")
REQUIRED_MATRIX_PHASES = ("LIQUID", "FCC_A1", "BCC_A2", "CEMENTITE", "M23C6", "M7C3", "M6C")
REQUIRED_EXCLUDED_ELEMENTS = ("As", "B", "N", "O", "P", "S", "Sb", "Sn", "W")
MATRIX_ACKNOWLEDGEMENT_TEXT = (
    "我确认本次计算采用 12 组元缩减体系。B、N、P、S、As、Sn、Sb、O、W 未进入计算；"
    "结果只能用于 Fe 基体相和已验证主要碳化物的平衡趋势探索，"
    "不能用于评价这些被排除元素、夹杂物、碳氮化物、晶界偏聚或实际组织。"
)
RESULT_LABEL_MATRIX = "12-component reduced-system matrix equilibrium prediction"
PROHIBITED_RESULT_LABELS = (
    "完整钢种热力学计算", "完整相图", "全成分平衡", "实际组织预测", "析出动力学结果",
)
#: Everything the phase-4 profile deliberately does not compute.  Carried into every result.
MATRIX_NOT_COMPUTED = (
    "BCC_B2 有序-无序相",
    "MC/MX 组合碳氮化物",
    "氮化物",
    "硼化物",
    "硫化物",
    "磷化物",
    "氧化物与夹杂物",
    "As/Sn/Sb 相关相",
    "析出动力学、偏聚、晶界脆化与实际组织含量",
)
MATRIX_PHASE_PROFILE_EVIDENCE = "config/calphad_phase_profile_evidence_v1.0.json"
MATRIX_PHASE_PROFILE_SCRIPT = "scripts/calphad_phase_profile_probe.py"

#: T86 phase 5: the formal solver mode.  Every temperature point runs in its own worker process and
#: the multi-temperature batch path is kept only as diagnostic evidence.
INDEPENDENT_SOLVER_MODE = "independent_single_point_process_v1"
BATCH_SOLVER_MODE = "batch_workspace_warm_start"
FORMAL_SOLVER_MODE = INDEPENDENT_SOLVER_MODE
#: A single point may be retried once for diagnosis, but a retry never becomes part of the formal
#: curve and never turns a failed formal point into a pass.
DIAGNOSTIC_RETRY_LIMIT = 1
#: Maximum difference between three independent runs of the same curve.
REPEAT_MAX_ABS_DIFFERENCE = 1e-7

#: T86 portfolio demo: a fast, public, reproducible synthetic demonstration built only from the
#: phases verified in phase 4.  It never reads the private sample composition table.
PORTFOLIO_DEMO_POLICY_PATH = ROOT / "config" / "calphad_portfolio_demo_v1.0.json"
PORTFOLIO_DEMO_POLICY_ID = "SteelAI-CALPHAD-Portfolio-Demo-Policy-v1.0"
PORTFOLIO_DEMO_ID = "fec_public_synthetic_v1"
PORTFOLIO_DEMO_COMPONENT_PROFILE_ID = "portfolio_demo_fec_v1"
PORTFOLIO_DEMO_PHASE_PROFILE_ID = "portfolio_demo_fec_verified_phases_v1"
PORTFOLIO_DEMO_REQUIRED_PHASES = ("LIQUID", "FCC_A1", "BCC_A2", "CEMENTITE")
PORTFOLIO_DEMO_COMPOSITION_WT_PCT = {"C": 0.45}
PORTFOLIO_DEMO_TEMPERATURE_RANGE_C = (400.0, 1600.0)
PORTFOLIO_DEMO_STEP_C = 50.0
PORTFOLIO_DEMO_LABEL = "Fe-C public synthetic portfolio demo"
PORTFOLIO_DEMO_FLAGS = {
    "portfolio_demo": True,
    "public_synthetic_input": True,
    "not_for_scientific_conclusion": True,
    "model_prediction_not_experimental_measurement": True,
    "is_complete_phase_diagram": False,
    "writes_back_formal_experimental_data": False,
}
#: T86 final status split: the portfolio exploration can complete even though scientific use stays
#: blocked by solver stability.
PORTFOLIO_STATUS_COMPLETE = "portfolio_exploration_complete"
PORTFOLIO_STATUS_PENDING_SIGNATURE = "portfolio_exploration_complete_pending_owner_signature"
SCIENTIFIC_STATUS_BLOCKED = "scientific_use_blocked_by_solver_stability"

#: T86 owner sign-off: a versioned, append-only acceptance record using the same governance shape as
#: config/portfolio_acceptance_v1.0.json.  It covers portfolio/engineering acceptance only and must
#: never be read as a real steel-grade scientific approval.
OWNER_ACCEPTANCE_PATH = ROOT / "config" / "calphad_owner_acceptance_v1.0.json"
OWNER_ACCEPTANCE_REGISTRY_ID = "SteelAI-CALPHAD-Owner-Acceptance-v1.0"
OWNER_ACCEPTANCE_RECORD_ID = "T86-PORTFOLIO-OWNER-SIGN-OFF-20260925"
OWNER_ACCEPTANCE_SCOPE = "portfolio_engineering_acceptance_only"
PORTFOLIO_DEMO_EVIDENCE_VERSION = "SteelAI-T86-Portfolio-Demo-Evidence-v1.0"
PORTFOLIO_ACCEPTANCE_INDEX_PATH = ROOT / "config" / "portfolio_acceptance_v1.0.json"

#: Runner contract: ``runner(request, interpreter=..., workdir=..., timeout_seconds=...)``
#: returns ``{"returncode": int, "payload": dict | None, "stdout_tail": str, "stderr_tail": str}``.
Runner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class CalphadGate:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CalphadPhaseFractionPreview:
    state: str
    sample_id: str
    gates: tuple[CalphadGate, ...]
    warnings: tuple[str, ...]
    environment: dict[str, Any]
    database: dict[str, Any]
    temperature: dict[str, Any]
    composition: dict[str, Any]
    request: dict[str, Any] | None
    exclusion_policy: dict[str, Any] | None = None
    limitation_notice: dict[str, Any] | None = None
    reduced_system: dict[str, Any] | None = None

    @property
    def blocked(self) -> bool:
        return self.state in {"disabled", "blocked"}

    def notice(self) -> dict[str, str]:
        notice = self.limitation_notice or {}
        return {
            "zh": str(notice.get("zh") or DEFAULT_LIMITATION_NOTICE_ZH),
            "en": str(notice.get("en") or DEFAULT_LIMITATION_NOTICE_EN),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "adapter_version": ADAPTER_VERSION,
            "feature": "calphad_phase_fraction",
            "state": self.state,
            "sample_id": self.sample_id,
            "gates": [gate.to_dict() for gate in self.gates],
            "warnings": list(self.warnings),
            "environment": self.environment,
            "database": self.database,
            "temperature": self.temperature,
            "composition": self.composition,
            "request": self.request,
            "exclusion_policy": self.exclusion_policy,
            "reduced_system": self.reduced_system,
            "limitation_notice": self.notice(),
            "result_label": RESULT_LABEL_MATRIX,
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
            "is_complete_phase_diagram": False,
            "writes_back_formal_experimental_data": False,
        }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON top level must be an object: {path}")
    return value


def load_adapter_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return _read_json(path)


def validate_adapter_registry(
    path: Path = CONFIG_PATH,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Structurally check the committed T86 third-party adapter registration."""
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    try:
        registry = load_adapter_config(path)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "problems": [f"无法读取 CALPHAD 登记：{exc}"], "problems_count": 1}

    if registry.get("registry_id") != "SteelAI-CALPHAD-Adapter-v1.0":
        add("registry_id 不是 SteelAI-CALPHAD-Adapter-v1.0。")
    if registry.get("schema_version") != "1.0":
        add("schema_version 必须为 1.0。")

    feature = registry.get("feature", {})
    if feature.get("key") != "calphad_phase_fraction":
        add("feature.key 必须为 calphad_phase_fraction。")
    if feature.get("core_dependency") is not False:
        add("CALPHAD 适配器不得成为核心依赖。")
    if feature.get("physics_core_runs_without_it") is not True:
        add("缺少隔离环境时既有物理计算必须照常运行。")
    if feature.get("disable_environment_variable") != FEATURE_ENV:
        add(f"关闭开关必须使用 {FEATURE_ENV}。")

    component = registry.get("component", {})
    version = str(component.get("version", ""))
    if not SEMVER_PATTERN.fullmatch(version):
        add("component.version 必须是精确版本号。")
    if component.get("license_spdx") != "MIT" or component.get("license_status") != "verified_osi":
        add("pycalphad 许可证必须是已核对的 MIT。")
    for field in ("official_repo", "release_url", "license_url", "pypi_release_url"):
        if not str(component.get(field, "")).startswith("https://"):
            add(f"component.{field} 必须是官方 HTTPS 地址。")
    if version and version not in str(component.get("release_url", "")):
        add("release_url 未包含所固定的版本。")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(component.get("source_ref", ""))):
        add("component.source_ref 必须是固定的 Git 提交前缀或 SHA。")
    wheel = component.get("artifacts", {}).get("cp312_win_amd64", {})
    if not SHA256_PATTERN.fullmatch(str(wheel.get("sha256", ""))):
        add("cp312 win_amd64 wheel 的 SHA-256 缺失或格式不正确。")
    if str(component.get("requires_python", "")) != ">=3.11":
        add("pycalphad 的 requires_python 记录必须为 >=3.11。")
    if component.get("code_imported") is not False:
        add("第三方代码不得复制入仓库。")

    isolated = registry.get("isolated_environment", {})
    if isolated.get("main_requirements_modified") is not False:
        add("主 requirements 不得被修改。")
    if isolated.get("install_requires_explicit_user_approval") is not True:
        add("安装必须要求显式用户批准。")
    for requirement_file in isolated.get("requirement_files_must_not_contain_pycalphad", []):
        target = Path(project_root) / str(requirement_file)
        try:
            text = target.read_text(encoding="utf-8").lower()
        except OSError as exc:
            add(f"无法读取 {requirement_file}：{exc}")
            continue
        if "pycalphad" in text:
            add(f"{requirement_file} 不允许出现 pycalphad。")

    database = registry.get("database", {})
    if database.get("registered_databases"):
        add("提交的登记不得内含已登记的 TDB；TDB 只能登记在本地未跟踪文件。")
    if database.get("contains_database_content") is not False:
        add("提交的登记必须声明不含数据库内容。")
    if database.get("database_not_redistributed") is not True:
        add("登记必须声明数据库不随仓库分发。")
    if not isinstance(database.get("authorized_database_present"), bool):
        add("authorized_database_present 必须是布尔值（本地是否已登记授权 TDB）。")
    if database.get("required_authorization_status") != REQUIRED_TDB_AUTHORIZATION:
        add("TDB 授权状态要求与适配器不一致。")
    if not str(database.get("local_registration_file", "")).strip():
        add("登记必须说明本地 TDB 登记文件的位置。")
    if not str(database.get("get_it_from", "")).strip():
        add("登记必须说明如何取得数据库（不得由仓库分发）。")

    method = registry.get("method", {})
    if method.get("temperature_input_unit") != "degC":
        add("温度输入单位必须标注为 degC。")
    if method.get("composition_input_unit") != "wt_pct":
        add("成分输入单位必须标注为 wt_pct。")
    if "mole_fraction_of_phase" not in str(method.get("output_phase_fraction_basis", "")):
        add("输出相分数基准必须标注为各相摩尔分数。")
    weights = method.get("atomic_weights", {}).get("elements", {})
    if not {"Fe", "C", "Mn"} <= set(weights):
        add("原子量表缺少基础元素。")
    if len(weights) < 20:
        add("原子量表覆盖元素过少。")
    fe_rule = method.get("fe_balance", {})
    if fe_rule.get("requires_named_user_confirmation") is not True:
        add("Fe 按余量计算必须要求具名用户确认。")

    claims = registry.get("claims", {})
    for field, expected in (
        ("result_type", RESULT_TYPE),
        ("review_status", REVIEW_STATUS),
        ("is_complete_phase_diagram", False),
        ("writes_back_formal_experimental_data", False),
        ("writes_to_processed_data_layer", False),
        ("silent_zero_fill", False),
        ("silent_element_omission", False),
    ):
        if claims.get(field) != expected:
            add(f"claims.{field} 必须为 {expected!r}。")

    return {
        "schema_version": "1.0",
        "registry_id": registry.get("registry_id"),
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "component_version": version or None,
        "pin_status": component.get("version_pin_status"),
        "authorized_database_present": bool(database.get("authorized_database_present")),
    }


def validate_tdb_template(path: Path = TDB_TEMPLATE_PATH) -> dict[str, Any]:
    """Check that the committed local-TDB template carries every required field."""
    problems: list[str] = []
    try:
        template = _read_json(path)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "problems": [f"无法读取 TDB 模板：{exc}"]}
    if template.get("registry_id") != "SteelAI-CALPHAD-TDB-Local-v1.0":
        problems.append("TDB 模板的 registry_id 不正确。")
    entries = template.get("databases")
    if not isinstance(entries, list) or len(entries) != 1:
        problems.append("TDB 模板必须只有一个示例条目。")
    else:
        missing = sorted(REQUIRED_TDB_FIELDS - set(entries[0]))
        if missing:
            problems.append("TDB 模板缺少字段：" + ", ".join(missing))
    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "required_fields": sorted(REQUIRED_TDB_FIELDS),
    }


def feature_disabled_reason(config: Mapping[str, Any] | None = None) -> str:
    """Return a non-empty reason when the feature is switched off, else ``''``."""
    value = str(os.environ.get(FEATURE_ENV, "")).strip().lower()
    if value in DISABLE_VALUES:
        return f"{FEATURE_ENV}={value}"
    return ""


def feature_enabled(config: Mapping[str, Any] | None = None) -> bool:
    if feature_disabled_reason(config):
        return False
    resolved = config if config is not None else _safe_config()
    return bool(resolved.get("feature", {}).get("default_enabled", True))


def _safe_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config is not None:
        return dict(config)
    try:
        return load_adapter_config()
    except (OSError, ValueError):
        return {}


def _pinned_pycalphad_version(config: Mapping[str, Any] | None = None) -> str:
    return str(_safe_config(config).get("component", {}).get("version", "") or "")


def interpreter_configuration(
    config: Mapping[str, Any] | None = None,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Resolve the isolated interpreter from the environment, settings.toml or the default path."""
    resolved = _safe_config(config)
    isolated = resolved.get("isolated_environment", {})
    default_relative = isolated.get("default_interpreter") or str(DEFAULT_INTERPRETER_RELATIVE)

    environment_value = str(os.environ.get(INTERPRETER_ENV, "")).strip()
    if environment_value:
        path = Path(environment_value).expanduser()
        return {"source": "environment_variable", "path": str(path), "exists": path.is_file()}

    settings_value = ""
    try:
        from steelai.settings import load_settings

        settings_value = str(load_settings().get("tools", {}).get("calphad_python", "")).strip()
    except (OSError, ValueError):
        settings_value = ""
    if settings_value:
        path = Path(settings_value).expanduser()
        return {"source": "settings_toml", "path": str(path), "exists": path.is_file()}

    path = Path(project_root) / str(default_relative)
    if path.is_file():
        return {"source": "default_path", "path": str(path), "exists": True}
    return {"source": None, "path": None, "exists": False, "default_path": str(path)}


_PROBE_SOURCE = (
    "import json\n"
    "payload = {}\n"
    "try:\n"
    "    from importlib import metadata\n"
    "    payload['installed'] = True\n"
    "    payload['version'] = metadata.version('pycalphad')\n"
    "except Exception as exc:\n"
    "    payload['installed'] = False\n"
    "    payload['error'] = type(exc).__name__\n"
    "print(json.dumps(payload))\n"
)


def probe_isolated_environment(
    configuration: Mapping[str, Any],
    expected_version: str,
    config: Mapping[str, Any] | None = None,
    *,
    process_runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Report the isolated environment state without importing pycalphad into this process."""
    resolved = _safe_config(config)
    isolated = resolved.get("isolated_environment", {})
    timeout = int(isolated.get("probe_timeout_seconds", 30) or 30)
    base: dict[str, Any] = {
        "interpreter_source": configuration.get("source"),
        "interpreter": configuration.get("path"),
        "expected_version": expected_version,
        "installed": False,
        "pycalphad_version": None,
    }
    if not configuration.get("path"):
        return {**base, "status": "not_configured", "detail": f"未配置隔离解释器（{INTERPRETER_ENV} 或 settings.toml tools.calphad_python）。"}
    if not configuration.get("exists"):
        return {**base, "status": "interpreter_missing", "detail": "配置的隔离解释器不存在。"}

    runner = process_runner or subprocess.run
    try:
        completed = runner(
            [str(configuration["path"]), "-I", "-c", _PROBE_SOURCE],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {**base, "status": "probe_failed", "detail": f"{type(exc).__name__}: {exc}"}

    if completed.returncode != 0:
        return {
            **base,
            "status": "probe_failed",
            "detail": f"探测进程返回 {completed.returncode}",
            "stderr_tail": str(getattr(completed, "stderr", "") or "")[-400:],
        }
    try:
        payload = json.loads(str(completed.stdout).strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {**base, "status": "probe_failed", "detail": "探测输出不是合法 JSON。"}

    if not payload.get("installed"):
        return {
            **base,
            "status": "dependency_missing",
            "detail": f"隔离环境中未安装 pycalphad（{payload.get('error', 'unknown')}）。",
        }
    version = str(payload.get("version", ""))
    if version != expected_version:
        return {
            **base,
            "status": "version_mismatch",
            "installed": True,
            "pycalphad_version": version,
            "detail": f"隔离环境中的 pycalphad {version} 与登记的固定版本 {expected_version} 不一致。",
        }
    return {
        **base,
        "status": "ready",
        "installed": True,
        "pycalphad_version": version,
        "detail": f"隔离环境就绪：pycalphad {version}。",
    }


def tdb_registry_path(config: Mapping[str, Any] | None = None, project_root: Path = ROOT) -> Path:
    resolved = _safe_config(config)
    database = resolved.get("database", {})
    environment_value = str(os.environ.get(TDB_REGISTRY_ENV, "")).strip()
    if environment_value:
        return Path(environment_value).expanduser()
    relative = database.get("default_registry_path") or str(DEFAULT_TDB_REGISTRY_PATH.relative_to(ROOT))
    return Path(project_root) / str(relative)


def load_tdb_registry(
    path: Path | None = None,
    config: Mapping[str, Any] | None = None,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    target = Path(path) if path is not None else tdb_registry_path(config, project_root)
    if not target.is_file():
        return {"status": "not_registered", "path": str(target), "databases": [], "detail": f"未找到本地 TDB 登记文件：{target}"}
    try:
        registry = _read_json(target)
    except (OSError, ValueError) as exc:
        return {"status": "invalid", "path": str(target), "databases": [], "detail": f"TDB 登记文件无法解析：{exc}"}
    return {"status": "loaded", "path": str(target), "registry": registry, "databases": list(registry.get("databases", []) or [])}


def validate_tdb_registration(
    entry: Mapping[str, Any],
    *,
    project_root: Path = ROOT,
    pinned_version: str = "",
) -> dict[str, Any]:
    """Validate one local TDB registration entry, including the file hash."""
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    missing = sorted(REQUIRED_TDB_FIELDS - set(entry))
    if missing:
        add("登记缺少字段：" + ", ".join(missing))
    if entry.get("format") != ALLOWED_TDB_FORMAT:
        add(f"format 必须为 {ALLOWED_TDB_FORMAT}。")
    if entry.get("authorization_status") != REQUIRED_TDB_AUTHORIZATION:
        add("授权状态必须是用户明确确认的 user_confirmed_authorized_for_this_steel_grade。")
    if not str(entry.get("authorized_by", "")).strip():
        add("缺少具名授权人 authorized_by。")
    if not str(entry.get("license_or_authorization", "")).strip():
        add("缺少许可或书面授权依据。")
    if not str(entry.get("citation", "")).strip():
        add("缺少数据库引用 citation。")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("authorized_at", ""))):
        add("authorized_at 必须是 YYYY-MM-DD。")
    if not isinstance(entry.get("applicable_steel_grades"), list) or not entry.get("applicable_steel_grades"):
        add("applicable_steel_grades 必须是非空列表。")
    covered = entry.get("covered_elements")
    if not isinstance(covered, list) or not covered:
        add("covered_elements 必须是非空列表。")
    elif any(not ELEMENT_SYMBOL.fullmatch(str(element)) for element in covered):
        add("covered_elements 必须是元素符号列表。")
    # The fixed phase profile is checked against this declared list before the worker starts, so a
    # registration that does not declare its phases fails closed.
    covered_phases = entry.get("covered_phases")
    if not isinstance(covered_phases, list) or not covered_phases:
        add("covered_phases 必须是非空列表（登记数据库解析出的相名）。")
    elif any(not PHASE_NAME_PATTERN.fullmatch(str(name)) for name in covered_phases):
        add("covered_phases 必须是相名字符串列表。")
    declared_range = entry.get("declared_temperature_range_C")
    if (
        not isinstance(declared_range, list)
        or len(declared_range) != 2
        or not all(isinstance(item, (int, float)) for item in declared_range)
        or declared_range[0] >= declared_range[1]
    ):
        add("declared_temperature_range_C 必须是递增的 [min, max] 数值对。")

    recorded_hash = str(entry.get("sha256", ""))
    if not SHA256_PATTERN.fullmatch(recorded_hash):
        add("sha256 必须是 64 位小写十六进制。")

    file_status = "not_checked"
    actual_hash: str | None = None
    path_text = str(entry.get("path", ""))
    if path_text:
        candidate = Path(path_text).expanduser()
        if not candidate.is_absolute():
            candidate = Path(project_root) / candidate
        if not candidate.is_file():
            add(f"TDB 文件不存在：{candidate}")
            file_status = "missing"
        else:
            try:
                actual_hash = sha256_file(candidate)
            except OSError as exc:
                add(f"无法读取 TDB 文件：{exc}")
                file_status = "unreadable"
            else:
                file_status = "hashed"
                if SHA256_PATTERN.fullmatch(recorded_hash) and actual_hash != recorded_hash:
                    add("TDB 文件 SHA-256 与登记不一致。")
    else:
        add("缺少 TDB 文件路径。")

    # The compatibility verdict is part of the registration, but a recorded "failed" verdict is a
    # *separate* gate (CALPHAD-TDB-007); a malformed or stale verdict is a registration problem.
    compatibility = _compatibility_summary(entry, pinned_version or _pinned_pycalphad_version())
    if compatibility["status"] == "missing":
        add("登记缺少 pycalphad_compatibility 判定块。")
    for problem in compatibility["problems"]:
        add(problem)

    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "database_id": entry.get("database_id"),
        "sha256": recorded_hash or None,
        "actual_sha256": actual_hash,
        "file_status": file_status,
        "covered_elements": list(covered) if isinstance(covered, list) else [],
        "covered_phases": list(covered_phases) if isinstance(covered_phases, list) else [],
        "declared_temperature_range_C": declared_range if isinstance(declared_range, list) else None,
        "compatibility": compatibility,
    }


def _compatibility_summary(entry: Mapping[str, Any], pinned_version: str) -> dict[str, Any]:
    """Extract the recorded pycalphad-compatibility verdict for one database registration."""
    raw = entry.get("pycalphad_compatibility")
    if not isinstance(raw, Mapping):
        return {
            "status": "missing",
            "pinned_version_match": False,
            "detail": "登记缺少 pycalphad_compatibility 判定块。",
        }
    status = str(raw.get("status", "")).strip().lower()
    recorded_version = str(raw.get("pinned_pycalphad_version", "")).strip()
    version_match = bool(recorded_version) and recorded_version == str(pinned_version)
    problems: list[str] = []
    if status not in {COMPATIBILITY_PASSED, "failed"}:
        problems.append("pycalphad_compatibility.status 必须是 passed 或 failed。")
    if not version_match:
        problems.append(
            f"兼容性判定记录的是 pycalphad {recorded_version or '未记录'}，与当前固定版本 {pinned_version} 不一致；需重新核对。"
        )
    if not str(raw.get("checked_at", "")).strip():
        problems.append("pycalphad_compatibility.checked_at 缺失。")
    return {
        "status": status or "invalid",
        "pinned_pycalphad_version": recorded_version,
        "pinned_version_match": version_match,
        "checked_at": raw.get("checked_at"),
        "checked_with": raw.get("checked_with"),
        "evidence": raw.get("evidence"),
        "raw_file_status": raw.get("raw_file_status"),
        "raw_file_error": raw.get("raw_file_error"),
        "explicit_encoding_status": raw.get("explicit_encoding_status"),
        "explicit_encoding_error": raw.get("explicit_encoding_error"),
        "unsupported_commands": list(raw.get("unsupported_commands", []) or []),
        "blocked_reason": raw.get("blocked_reason", ""),
        "problems": problems,
    }


def select_database(databases: list[Mapping[str, Any]], database_id: str = "") -> Mapping[str, Any] | None:
    if database_id:
        return next((item for item in databases if str(item.get("database_id")) == database_id), None)
    return databases[0] if databases else None


def load_exclusion_policy(path: Path = EXCLUSION_POLICY_PATH) -> dict[str, Any]:
    return _read_json(path)


def approved_exclusions_for(
    policy: Mapping[str, Any] | None,
    sample_id: str,
    database: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return element -> category for the approved (sample, element) pairs only.

    An empty mapping means "nothing may be excluded", which keeps the strict phase-1 behaviour.
    Only triples enumerated in the versioned policy can ever appear here; there is no pattern or
    wildcard matching, so this cannot become a generic ignore-anything switch.
    """
    if not isinstance(policy, Mapping):
        return {}
    entries = policy.get("approved_exclusions")
    if not isinstance(entries, list):
        return {}
    scoped_database = str((policy.get("database_scope") or {}).get("database_id", ""))
    if database is not None and scoped_database and scoped_database != str(database.get("database_id", "")):
        # The approval is bound to one database identity; a different database needs its own decision.
        return {}
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("sample_id", "")) != str(sample_id):
            continue
        category = str(entry.get("category", ""))
        if category not in ALLOWED_EXCLUSION_CATEGORIES:
            continue
        for element in entry.get("elements", []) or []:
            result[str(element)] = category
    return result


def validate_exclusion_policy(path: Path = EXCLUSION_POLICY_PATH) -> dict[str, Any]:
    """Structurally check the approved exclusion policy (versioned, enumerated, no wildcards)."""
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    try:
        policy = load_exclusion_policy(path)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "problems": [f"无法读取排除政策：{exc}"], "approved_exclusion_count": 0}

    if not re.fullmatch(r"SteelAI-CALPHAD-Exclusion-Policy-v1\.\d+", str(policy.get("policy_id", ""))):
        add("policy_id 必须是 SteelAI-CALPHAD-Exclusion-Policy-v1.x。")
    if policy.get("policy_id") != "SteelAI-CALPHAD-Exclusion-Policy-v1.0" and not str(policy.get("supersedes", "")).strip():
        add("非 v1.0 的排除政策必须声明 supersedes（被取代的版本）。")
    if not str(policy.get("approved_by", "")).strip() or not str(policy.get("approved_at", "")).strip():
        add("排除政策必须有具名批准人与批准日期。")
    if policy.get("generic_element_ignore_switch") is not False:
        add("排除政策必须显式声明不存在通用元素忽略开关。")
    if policy.get("requires_named_confirmer") is not True:
        add("每次运行都必须要求具名确认人。")
    notice = policy.get("limitation_notice", {})
    if not str(notice.get("zh", "")).strip() or not str(notice.get("en", "")).strip():
        add("限制声明必须同时提供中文与英文。")
    if "缩减成分体系" not in str(notice.get("zh", "")):
        add("限制声明必须写明结果基于缩减成分体系。")

    entries = policy.get("approved_exclusions")
    if not isinstance(entries, list) or not entries:
        add("approved_exclusions 必须是非空列表。")
        entries = []
    total = 0
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            add("approved_exclusions 的条目必须是对象。")
            continue
        sample = str(entry.get("sample_id", "")).strip()
        if not sample:
            add("排除条目缺少 sample_id。")
        if entry.get("category") not in ALLOWED_EXCLUSION_CATEGORIES:
            add(f"{sample or '<missing>'}: 不支持的排除类别 {entry.get('category')!r}。")
        elements = entry.get("elements")
        if not isinstance(elements, list) or not elements:
            add(f"{sample or '<missing>'}: elements 必须是非空列表。")
            continue
        for element in elements:
            name = str(element)
            if not ELEMENT_SYMBOL.fullmatch(name):
                add(f"{sample}: {name!r} 不是元素符号。")
                continue
            key = (sample, name)
            if key in seen:
                add(f"{sample}/{name}: 重复的排除条目。")
            seen.add(key)
            total += 1
        if "*" in elements or "ALL" in {str(item).upper() for item in elements}:
            add(f"{sample}: 不允许通配符或 ALL 形式的排除。")
    if any(pattern in str(policy) for pattern in ('"elements": "*"', '"wildcard"')):
        add("排除政策不得包含通配符。")
    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "policy_id": policy.get("policy_id"),
        "approved_by": policy.get("approved_by"),
        "approved_at": policy.get("approved_at"),
        "database_scope": policy.get("database_scope"),
        "approved_exclusion_count": total,
        "limitation_notice": notice,
    }


def load_reduced_system_policy(path: Path = REDUCED_SYSTEM_POLICY_PATH) -> dict[str, Any]:
    return _read_json(path)


def validate_reduced_system_policy(path: Path = REDUCED_SYSTEM_POLICY_PATH) -> dict[str, Any]:
    """Structurally check the fixed reduced-system policy.

    The check is deliberately anchored on module constants rather than on the file's own content, so
    quietly editing the policy to a different element or phase set fails closed instead of widening
    the calculation.  There is no generic selector: the policy may only describe the approved 12
    components and the approved carbide phase range.
    """
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    try:
        policy = load_reduced_system_policy(path)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "problems": [f"无法读取缩减体系政策：{exc}"],
                "component_profile": {}, "phase_profile": {}}

    if str(policy.get("policy_id", "")) != REDUCED_SYSTEM_POLICY_ID:
        add(f"policy_id 必须是 {REDUCED_SYSTEM_POLICY_ID}。")
    if not str(policy.get("approved_by", "")).strip() or not str(policy.get("approved_at", "")).strip():
        add("缩减体系政策必须有具名批准人与批准日期。")

    component = dict(policy.get("component_profile") or {})
    if str(component.get("profile_id", "")) != COMPONENT_PROFILE_ID:
        add(f"component_profile.profile_id 必须是 {COMPONENT_PROFILE_ID}。")
    if str(component.get("version", "")) != COMPONENT_PROFILE_VERSION:
        add(f"component_profile.version 必须是 {COMPONENT_PROFILE_VERSION}。")
    included = [str(element) for element in component.get("included_elements", []) or []]
    if tuple(sorted(included)) != tuple(sorted(REQUIRED_MATRIX_ELEMENTS)):
        add("component_profile.included_elements 必须与批准的 12 组元完全一致："
            + "、".join(REQUIRED_MATRIX_ELEMENTS) + "。")
    if int(component.get("included_element_count", 0) or 0) != len(REQUIRED_MATRIX_ELEMENTS):
        add(f"component_profile.included_element_count 必须是 {len(REQUIRED_MATRIX_ELEMENTS)}。")
    if component.get("generic_element_selection_switch") is not False:
        add("缩减体系政策必须显式声明不存在通用元素选择开关。")
    if component.get("zero_fill_forbidden") is not True:
        add("缩减体系政策必须显式声明禁止补零。")

    excluded_groups = component.get("excluded_elements")
    if not isinstance(excluded_groups, list) or not excluded_groups:
        add("component_profile.excluded_elements 必须是非空列表。")
        excluded_groups = []
    excluded_union: set[str] = set()
    for group in excluded_groups:
        if not isinstance(group, Mapping):
            add("excluded_elements 的条目必须是对象。")
            continue
        category = str(group.get("category", ""))
        if category not in ALLOWED_EXCLUSION_CATEGORIES:
            add(f"excluded_elements: 不支持的类别 {category!r}。")
        for element in group.get("elements", []) or []:
            excluded_union.add(str(element))
    if excluded_union != set(REQUIRED_EXCLUDED_ELEMENTS):
        missing = sorted(set(REQUIRED_EXCLUDED_ELEMENTS) - excluded_union)
        extra = sorted(excluded_union - set(REQUIRED_EXCLUDED_ELEMENTS))
        add("excluded_elements 必须恰好覆盖 " + "、".join(REQUIRED_EXCLUDED_ELEMENTS)
            + (f"（缺少：{'、'.join(missing)}）" if missing else "")
            + (f"（多出：{'、'.join(extra)}）" if extra else "") + "。")

    phase = dict(policy.get("phase_profile") or {})
    if str(phase.get("profile_id", "")) != PHASE_PROFILE_ID:
        add(f"phase_profile.profile_id 必须是 {PHASE_PROFILE_ID}。")
    if str(phase.get("version", "")) != PHASE_PROFILE_VERSION:
        add(f"phase_profile.version 必须是 {PHASE_PROFILE_VERSION}。")
    phases = [str(name) for name in phase.get("phases", []) or []]
    if tuple(phases) != tuple(REQUIRED_MATRIX_PHASES):
        add("phase_profile.phases 必须与批准的顺序和内容完全一致（第一版固定相集合，不自动替换）："
            + "、".join(REQUIRED_MATRIX_PHASES) + "。")
    if phase.get("generic_phase_selection_switch") is not False:
        add("相集合政策必须显式声明不存在通用相选择开关。")
    if not str(phase.get("verification_evidence", "")).strip():
        add("相集合政策必须声明独立探针证据文件。")

    if str(policy.get("acknowledgement_text", "")) != MATRIX_ACKNOWLEDGEMENT_TEXT:
        add("确认文本必须与批准的文本逐字一致。")

    # T86 phase 5: the formal solver mode must be the independent single-point process mode, and the
    # batch warm-start path must be marked diagnostic-only.
    modes = policy.get("solver_modes")
    if not isinstance(modes, Mapping):
        add("solver_modes 必须是对象。")
        modes = {}
    formal_mode = str(policy.get("formal_solver_mode", ""))
    if formal_mode != INDEPENDENT_SOLVER_MODE:
        add(f"formal_solver_mode 必须是 {INDEPENDENT_SOLVER_MODE}。")
    independent = modes.get(INDEPENDENT_SOLVER_MODE)
    if not isinstance(independent, Mapping):
        add(f"solver_modes 必须定义 {INDEPENDENT_SOLVER_MODE}。")
        independent = {}
    elif independent.get("formal_pilot") is not True or str(independent.get("status")) != "formal_pilot":
        add(f"{INDEPENDENT_SOLVER_MODE} 必须标记为 formal_pilot。")
    rules = independent.get("rules") if isinstance(independent.get("rules"), Mapping) else {}
    for rule in ("one_temperature_per_process", "fresh_process_per_point",
                 "recreate_database_model_workspace_each_process", "serial_only_no_parallel",
                 "no_warm_start_from_previous_point", "same_normalised_composition_for_every_point",
                 "same_components_plus_va_for_every_point", "same_fixed_phase_set_for_every_point",
                 "same_pressure_database_version_for_every_point"):
        if rules.get(rule) is not True:
            add(f"{INDEPENDENT_SOLVER_MODE}.rules.{rule} 必须为 true。")
    batch = modes.get(BATCH_SOLVER_MODE)
    if not isinstance(batch, Mapping):
        add(f"solver_modes 必须保留 {BATCH_SOLVER_MODE} 作为诊断路径。")
    elif batch.get("formal_pilot") is not False or str(batch.get("status")) != "diagnostic_only":
        add(f"{BATCH_SOLVER_MODE} 必须标记为 diagnostic_only 且不得作为正式路径。")
    retry = independent.get("retry_policy") if isinstance(independent.get("retry_policy"), Mapping) else {}
    if retry.get("formal_acceptance_requires_first_attempt_success") is not True:
        add("正式验收必须要求每个温度点首次独立进程调用即成功。")
    if retry.get("diagnostic_retry_may_not_be_spliced_into_the_formal_curve") is not True:
        add("诊断重试结果不得拼接到正式曲线。")
    if "solver_mode" not in (policy.get("required_result_fields") or []):
        add("required_result_fields 必须包含 solver_mode。")

    naming = dict(policy.get("result_naming") or {})
    if str(naming.get("label", "")) != RESULT_LABEL_MATRIX:
        add(f"结果名称必须是 {RESULT_LABEL_MATRIX}。")
    for prohibited in PROHIBITED_RESULT_LABELS:
        if prohibited not in (naming.get("prohibited_labels") or []):
            add(f"禁止使用的名称列表必须包含 {prohibited}。")

    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "policy_id": policy.get("policy_id"),
        "approved_by": policy.get("approved_by"),
        "approved_at": policy.get("approved_at"),
        "component_profile": component,
        "phase_profile": phase,
        "acknowledgement_text": policy.get("acknowledgement_text"),
        "result_naming": naming,
        "formal_solver_mode": policy.get("formal_solver_mode"),
        "solver_modes": dict(modes),
        "not_computed": list(phase.get("not_computed_in_this_phase", []) or []),
        "model_losses": dict(policy.get("model_losses") or {}),
    }


def matrix_phase_profile(policy: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return the fixed phase list, or an empty tuple when the policy is missing."""
    if not isinstance(policy, Mapping):
        return ()
    phases = (policy.get("phase_profile") or {}).get("phases")
    if not isinstance(phases, list):
        return ()
    return tuple(str(name) for name in phases)


def capacity_reduction_elements(policy: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return the elements the profile excludes for solver-capacity reasons."""
    if not isinstance(policy, Mapping):
        return ()
    groups = (policy.get("component_profile") or {}).get("excluded_elements")
    if not isinstance(groups, list):
        return ()
    result: list[str] = []
    for group in groups:
        if isinstance(group, Mapping) and str(group.get("category")) == CAPACITY_REDUCTION_CATEGORY:
            result.extend(str(element) for element in group.get("elements", []) or [])
    return tuple(sorted(set(result)))


def load_owner_acceptance(path: Path = OWNER_ACCEPTANCE_PATH) -> dict[str, Any]:
    return _read_json(path)


def validate_owner_acceptance(path: Path = OWNER_ACCEPTANCE_PATH) -> dict[str, Any]:
    """Check the owner sign-off record for the portfolio demo.

    The record may only authorise the **portfolio/engineering** acceptance of the public synthetic
    demo.  It must keep ``scientific_use_approved``, ``real_sample_curves_published`` and
    ``materials_conclusion_approved`` false, and its demo configuration must match the committed demo
    policy and the registered database hash; otherwise the record is rejected.
    """
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    try:
        registry = load_owner_acceptance(path)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "problems": [f"无法读取负责人验收记录：{exc}"],
                "signed": False, "entry": {}}

    if str(registry.get("registry_id", "")) != OWNER_ACCEPTANCE_REGISTRY_ID:
        add(f"registry_id 必须是 {OWNER_ACCEPTANCE_REGISTRY_ID}。")
    if str(registry.get("schema_version", "")) != "1.0":
        add("schema_version 必须是 1.0。")
    entries = registry.get("entries")
    if not isinstance(entries, list) or not entries:
        add("entries 必须是非空列表。")
        entries = []
    entry = next((item for item in entries if isinstance(item, Mapping)
                  and str(item.get("record_id")) == OWNER_ACCEPTANCE_RECORD_ID), None)
    if entry is None:
        add(f"记录中必须包含 record_id={OWNER_ACCEPTANCE_RECORD_ID} 的条目。")
        entry = {}

    if str(entry.get("decision", "")) not in {"approved", "warning_accepted"}:
        add("decision 必须是 approved 或 warning_accepted。")
    if not str(entry.get("responsible_person_id", "")).strip():
        add("responsible_person_id 不能为空（不得由 Agent 代填）。")
    if str(entry.get("reviewer_id", "")) != str(entry.get("responsible_person_id", "")):
        add("reviewer_id 必须与 responsible_person_id 一致。")
    signed_at = str(entry.get("signed_at", ""))
    if not ISO_TIMESTAMP_PATTERN.fullmatch(signed_at) or len(signed_at) < 10:
        add("signed_at 必须是 YYYY-MM-DD 或 ISO 8601 日期时间。")
    if str(entry.get("timezone", "")) != "Asia/Shanghai":
        add("timezone 必须是 Asia/Shanghai。")
    if str(entry.get("decision_scope", "")) != OWNER_ACCEPTANCE_SCOPE:
        add(f"decision_scope 必须是 {OWNER_ACCEPTANCE_SCOPE}。")
    if not str(entry.get("scope", "")).strip():
        add("scope 不能为空。")
    if str(entry.get("portfolio_demo_evidence_version", "")) != PORTFOLIO_DEMO_EVIDENCE_VERSION:
        add(f"portfolio_demo_evidence_version 必须是 {PORTFOLIO_DEMO_EVIDENCE_VERSION}。")

    # A portfolio-only signature must never authorise scientific use.
    for key in ("scientific_use_approved", "real_sample_curves_published",
                "materials_conclusion_approved"):
        if entry.get(key) is not False:
            add(f"{key} 必须是 false：本次签署只覆盖公开演示的工程验收。")
    if str(entry.get("engineering_status_after_signature", "")) != PORTFOLIO_STATUS_COMPLETE:
        add(f"engineering_status_after_signature 必须是 {PORTFOLIO_STATUS_COMPLETE}。")
    if str(entry.get("scientific_status_after_signature", "")) != SCIENTIFIC_STATUS_BLOCKED:
        add(f"scientific_status_after_signature 必须是 {SCIENTIFIC_STATUS_BLOCKED}。")

    try:
        demo_policy = load_portfolio_demo_policy()
    except (OSError, ValueError):
        demo_policy = {}
    demo = dict(entry.get("demo_configuration") or {})
    if str(demo.get("demo_id", "")) != str(demo_policy.get("demo_id", "")):
        add("demo_configuration.demo_id 必须与已提交的公开演示政策一致。")
    if [str(name) for name in demo.get("phases", []) or []] != \
            [str(name) for name in PORTFOLIO_DEMO_REQUIRED_PHASES]:
        add("demo_configuration.phases 必须与已验证相集合一致。")
    if str(demo.get("solver_mode", "")) != INDEPENDENT_SOLVER_MODE:
        add(f"demo_configuration.solver_mode 必须是 {INDEPENDENT_SOLVER_MODE}。")
    database = dict(entry.get("database") or {})
    if str(database.get("sha256", "")) != str((demo_policy.get("database") or {}).get("sha256", "")):
        add("database.sha256 必须与公开演示政策记录的数据库哈希一致。")

    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "signed": not problems,
        "record_id": entry.get("record_id"),
        "responsible_person_id": entry.get("responsible_person_id"),
        "signed_at": entry.get("signed_at"),
        "accepted_on": entry.get("accepted_on"),
        "timezone": entry.get("timezone"),
        "decision": entry.get("decision"),
        "decision_scope": entry.get("decision_scope"),
        "scope": entry.get("scope"),
        "accepted_conclusion": entry.get("accepted_conclusion"),
        "portfolio_demo_evidence_version": entry.get("portfolio_demo_evidence_version"),
        "portfolio_demo_evidence_file": entry.get("portfolio_demo_evidence_file"),
        "demo_configuration": demo,
        "database": database,
        "acceptance_evidence": dict(entry.get("acceptance_evidence") or {}),
        "scientific_use_approved": entry.get("scientific_use_approved"),
        "real_sample_curves_published": entry.get("real_sample_curves_published"),
        "materials_conclusion_approved": entry.get("materials_conclusion_approved"),
        "engineering_status": entry.get("engineering_status_after_signature"),
        "scientific_status": entry.get("scientific_status_after_signature"),
        "explicitly_not_approved_for": list(entry.get("explicitly_not_approved_for", []) or []),
        "entry": dict(entry),
    }


def owner_acceptance_status(path: Path = OWNER_ACCEPTANCE_PATH) -> dict[str, Any]:
    """The single status pair T86 reports: portfolio/engineering and scientific."""
    report = validate_owner_acceptance(path)
    signed = bool(report.get("signed"))
    return {
        "portfolio": PORTFOLIO_STATUS_COMPLETE if signed else PORTFOLIO_STATUS_PENDING_SIGNATURE,
        "scientific": SCIENTIFIC_STATUS_BLOCKED,
        "portfolio_signed": signed,
        "signature_record": str(path),
        "record_id": report.get("record_id"),
        "responsible_person_id": report.get("responsible_person_id") if signed else "",
        "signed_at": report.get("signed_at") if signed else "",
        "timezone": report.get("timezone") if signed else "",
        "decision_scope": report.get("decision_scope") if signed else "",
        "scientific_use_approved": False,
        "real_sample_curves_published": False,
        "materials_conclusion_approved": False,
        "problems": report.get("problems", []),
    }


def load_portfolio_demo_policy(path: Path = PORTFOLIO_DEMO_POLICY_PATH) -> dict[str, Any]:
    return _read_json(path)


def validate_portfolio_demo_policy(path: Path = PORTFOLIO_DEMO_POLICY_PATH) -> dict[str, Any]:
    """Structurally check the public synthetic demo policy against module constants."""
    problems: list[str] = []

    def add(message: str) -> None:
        if message not in problems:
            problems.append(message)

    try:
        policy = load_portfolio_demo_policy(path)
    except (OSError, ValueError) as exc:
        return {"status": "failed", "problems": [f"无法读取公开演示政策：{exc}"],
                "phases": [], "temperature": {}, "composition": {}}

    if str(policy.get("policy_id", "")) != PORTFOLIO_DEMO_POLICY_ID:
        add(f"policy_id 必须是 {PORTFOLIO_DEMO_POLICY_ID}。")
    if str(policy.get("demo_id", "")) != PORTFOLIO_DEMO_ID:
        add(f"demo_id 必须是 {PORTFOLIO_DEMO_ID}。")
    if policy.get("public_synthetic_input") is not True:
        add("公开演示必须声明 public_synthetic_input=true。")

    composition = dict(policy.get("composition_wt_pct") or {})
    numeric = {key: value for key, value in composition.items() if key != "Fe"}
    if numeric != PORTFOLIO_DEMO_COMPOSITION_WT_PCT:
        add("composition_wt_pct 必须与公开合成成分一致：" + json.dumps(
            PORTFOLIO_DEMO_COMPOSITION_WT_PCT, ensure_ascii=False) + "。")

    component = dict(policy.get("component_profile") or {})
    if str(component.get("profile_id", "")) != PORTFOLIO_DEMO_COMPONENT_PROFILE_ID:
        add(f"component_profile.profile_id 必须是 {PORTFOLIO_DEMO_COMPONENT_PROFILE_ID}。")
    if [str(element) for element in component.get("included_elements", []) or []] != ["Fe", "C"]:
        add("公开演示只允许 Fe 与 C 两个组元。")

    phase = dict(policy.get("phase_profile") or {})
    if str(phase.get("profile_id", "")) != PORTFOLIO_DEMO_PHASE_PROFILE_ID:
        add(f"phase_profile.profile_id 必须是 {PORTFOLIO_DEMO_PHASE_PROFILE_ID}。")
    phases = [str(name) for name in phase.get("phases", []) or []]
    if tuple(phases) != PORTFOLIO_DEMO_REQUIRED_PHASES:
        add("演示相集合必须是已验证相：" + "、".join(PORTFOLIO_DEMO_REQUIRED_PHASES) + "。")
    unverified = [name for name in phases if name not in REQUIRED_MATRIX_PHASES]
    if unverified:
        add("演示相集合含未验证相：" + "、".join(unverified) + "。")
    if phase.get("generic_phase_selection_switch") is not False:
        add("演示政策必须显式声明不存在通用相选择开关。")

    temperature = dict(policy.get("temperature") or {})
    low, high = PORTFOLIO_DEMO_TEMPERATURE_RANGE_C
    if [float(value) for value in temperature.get("range_C", [])] != [low, high]:
        add(f"演示温度区间必须是 {low:g}-{high:g} degC。")
    if float(temperature.get("step_C", 0) or 0) != PORTFOLIO_DEMO_STEP_C:
        add(f"演示温度步长必须是 {PORTFOLIO_DEMO_STEP_C:g} degC。")

    if str(policy.get("solver_mode", "")) != INDEPENDENT_SOLVER_MODE:
        add(f"演示必须使用正式求解模式 {INDEPENDENT_SOLVER_MODE}。")
    flags = dict(policy.get("required_result_flags") or {})
    for key, value in PORTFOLIO_DEMO_FLAGS.items():
        if flags.get(key) != value:
            add(f"required_result_flags.{key} 必须是 {value!r}。")
    if policy.get("no_write_back") and "data/processed" not in str(policy.get("no_write_back")):
        add("演示政策必须声明不写入 data/processed/。")

    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "policy_id": policy.get("policy_id"),
        "demo_id": policy.get("demo_id"),
        "phases": phases,
        "composition": composition,
        "temperature": temperature,
        "solver_mode": policy.get("solver_mode"),
        "database": dict(policy.get("database") or {}),
        "component_profile": component,
        "phase_profile": phase,
        "flags": flags,
        "not_for": list(policy.get("not_for", []) or []),
        "purpose": policy.get("purpose"),
    }


def _demo_temperature_points(policy: Mapping[str, Any]) -> tuple[list[float], list[float]]:
    low, high = PORTFOLIO_DEMO_TEMPERATURE_RANGE_C
    step = PORTFOLIO_DEMO_STEP_C
    count = int(round((high - low) / step)) + 1
    values_C = [round(low + index * step, 6) for index in range(count)]
    return values_C, [round(value + 273.15, 6) for value in values_C]


def preview_portfolio_demo(
    *,
    registry_path: Path | None = None,
    demo_policy_path: Path | None = None,
    config: Mapping[str, Any] | None = None,
    config_path: Path = CONFIG_PATH,
    project_root: Path = ROOT,
    environment: Mapping[str, Any] | None = None,
) -> CalphadPhaseFractionPreview:
    """Resolve the gates for the public synthetic portfolio demo.

    The demo is deliberately separate from the real-sample path: it uses only the public synthetic
    Fe-C composition declared in the demo policy, only phases verified in phase 4, the same
    registered community database and SHA-256, and the formal solver mode.  It requires no scientific
    approval because it produces no scientific claim — and every result carries
    ``not_for_scientific_conclusion``.
    """
    try:
        resolved = dict(config) if config is not None else load_adapter_config(config_path)
    except (OSError, ValueError) as exc:
        resolved = {}
        config_error = f"无法读取 CALPHAD 登记 {config_path}：{exc}"
    else:
        config_error = ""

    gates: list[CalphadGate] = []
    warnings: list[str] = []
    if config_error:
        gates.append(CalphadGate("CALPHAD-CONFIG-001", config_error))

    component = resolved.get("component", {})
    expected_version = str(component.get("version", ""))
    if environment is None:
        environment = probe_isolated_environment(
            interpreter_configuration(resolved, project_root), expected_version, resolved
        )
    else:
        environment = dict(environment)
    environment_gate_codes = {
        "not_configured": "CALPHAD-ENV-001", "interpreter_missing": "CALPHAD-ENV-001",
        "probe_failed": "CALPHAD-ENV-002", "dependency_missing": "CALPHAD-ENV-002",
        "version_mismatch": "CALPHAD-ENV-003",
    }
    if environment.get("status") != "ready":
        gates.append(CalphadGate(
            environment_gate_codes.get(str(environment.get("status")), "CALPHAD-ENV-002"),
            f"隔离环境未就绪（{environment.get('status')}）：{environment.get('detail', '')}",
        ))

    resolved_demo_path = demo_policy_path or PORTFOLIO_DEMO_POLICY_PATH
    demo_report = validate_portfolio_demo_policy(resolved_demo_path)
    demo_policy: dict[str, Any] | None = None
    try:
        demo_policy = load_portfolio_demo_policy(resolved_demo_path)
    except (OSError, ValueError):
        demo_policy = None
    if demo_report["status"] != "passed":
        gates.append(CalphadGate(
            "CALPHAD-DEMO-001",
            "公开演示政策未通过校验：" + "；".join(demo_report.get("problems", [])),
        ))

    registry = load_tdb_registry(registry_path, resolved, project_root)
    database: dict[str, Any] = {"status": registry.get("status"), "detail": registry.get("detail", "")}
    database_entry: Mapping[str, Any] | None = None
    database_validation: dict[str, Any] | None = None
    if registry.get("status") != "loaded":
        gates.append(CalphadGate("CALPHAD-TDB-000",
                                 "公开演示需要已登记的授权数据库（" + str(registry.get("detail", "")) + "）。"))
    else:
        databases = list(registry.get("databases", []))
        database_entry = select_database(databases)
        if database_entry is None:
            gates.append(CalphadGate("CALPHAD-TDB-000", "TDB 登记文件中没有任何数据库条目。"))
        else:
            database_validation = validate_tdb_registration(
                database_entry, project_root=project_root, pinned_version=expected_version
            )
            database = {
                "status": database_validation["status"],
                "database_id": database_validation["database_id"],
                "sha256": database_validation["sha256"],
                "covered_elements": database_validation["covered_elements"],
                "covered_phases": database_validation.get("covered_phases", []),
                "compatibility": database_validation.get("compatibility", {}),
                "registry_path": registry.get("path"),
            }
            if database_validation["status"] != "passed":
                gates.append(CalphadGate("CALPHAD-TDB-001", "TDB 登记未通过校验："
                                         + "；".join(database_validation.get("problems", []))))
            else:
                declared_demo = dict((demo_policy or {}).get("database") or {})
                if str(declared_demo.get("sha256", "")) != str(database_validation["sha256"]):
                    gates.append(CalphadGate(
                        "CALPHAD-DEMO-002",
                        "公开演示政策记录的数据库 SHA-256 与登记不一致；演示被阻断。",
                    ))
                compatibility = dict(database_validation.get("compatibility", {}) or {})
                if compatibility.get("status") != COMPATIBILITY_PASSED:
                    gates.append(CalphadGate(
                        "CALPHAD-TDB-007",
                        "TDB 未通过与 pycalphad 固定版本的兼容性门禁（记录状态："
                        f"{compatibility.get('status', 'missing')}）。",
                    ))
                covered_phases = {str(name) for name in database_validation.get("covered_phases", []) or []}
                missing = [name for name in PORTFOLIO_DEMO_REQUIRED_PHASES if name not in covered_phases]
                if covered_phases and missing:
                    gates.append(CalphadGate(
                        "CALPHAD-DEMO-003",
                        "演示相集合中的以下相不在已登记数据库中："
                        + "、".join(missing) + "。不得自动替换相名或改写 TDB。",
                    ))
                declared_range = (database_entry or {}).get("declared_temperature_range_C")
                if isinstance(declared_range, list) and len(declared_range) == 2:
                    low, high = PORTFOLIO_DEMO_TEMPERATURE_RANGE_C
                    if low < float(declared_range[0]) or high > float(declared_range[1]):
                        gates.append(CalphadGate(
                            "CALPHAD-DEMO-004",
                            f"演示温度区间 {low:g}-{high:g} degC 超出数据库声明区间 "
                            f"{float(declared_range[0]):g}-{float(declared_range[1]):g} degC。",
                        ))

    request: dict[str, Any] | None = None
    if not gates and database_entry is not None and demo_policy is not None:
        values_C, values_K = _demo_temperature_points(demo_policy)
        regime = _element_mole_fractions(
            dict(demo_policy.get("composition_wt_pct") or {}),
            dict((resolved.get("method", {}) or {}).get("atomic_weights", {}).get("elements", {}) or {}),
        )
        if not regime:
            gates.append(CalphadGate("CALPHAD-DEMO-005", "公开合成成分无法换算为摩尔分数。"))
        else:
            request = {
                "request_schema_version": "1.1",
                "adapter_version": ADAPTER_VERSION,
                "feature": "calphad_phase_fraction",
                "phase": "portfolio_demo_public_synthetic_fec",
                "sample_id": PORTFOLIO_DEMO_ID,
                "pycalphad_version": expected_version,
                "portfolio_demo": True,
                "public_synthetic_input": True,
                "not_for_scientific_conclusion": True,
                "demo_policy_id": (demo_policy or {}).get("policy_id"),
                "demo_id": (demo_policy or {}).get("demo_id"),
                "demo_label": PORTFOLIO_DEMO_LABEL,
                "database": {
                    "database_id": database_entry.get("database_id"),
                    "path": database_entry.get("path"),
                    "sha256": database_entry.get("sha256"),
                    "provider": database_entry.get("provider"),
                    "version_or_date": database_entry.get("version_or_date"),
                    "license_or_authorization": database_entry.get("license_or_authorization"),
                    "citation": database_entry.get("citation"),
                    "declared_temperature_range_C": database_entry.get("declared_temperature_range_C"),
                },
                "units": {
                    "composition_input": "wt_pct",
                    "composition_internal": "mole_fraction",
                    "temperature_input": "degC",
                    "temperature_internal": "K",
                    "pressure": "Pa",
                    "output_phase_fraction": "mole_fraction_of_phase",
                },
                "temperature": {
                    "min_C": PORTFOLIO_DEMO_TEMPERATURE_RANGE_C[0],
                    "max_C": PORTFOLIO_DEMO_TEMPERATURE_RANGE_C[1],
                    "step_C": PORTFOLIO_DEMO_STEP_C,
                    "values_C": values_C,
                    "values_K": values_K,
                    "count": len(values_C),
                },
                "pressure_Pa": float(demo_policy.get("pressure_Pa", 101325)),
                "components": ["FE", "C"],
                "component_mole_fractions": {"C": round(regime["C"], 10)},
                "phases": list(PORTFOLIO_DEMO_REQUIRED_PHASES),
                "component_profile": {
                    "profile_id": PORTFOLIO_DEMO_COMPONENT_PROFILE_ID,
                    "version": "1.0",
                    "included_elements": ["Fe", "C"],
                    "included_element_count": 2,
                    "component_list_length": 3,
                    "matches_profile": True,
                    "derived_from_composition": ["Fe", "C"],
                },
                "phase_profile": {
                    "profile_id": PORTFOLIO_DEMO_PHASE_PROFILE_ID,
                    "version": "1.0",
                    "phases": list(PORTFOLIO_DEMO_REQUIRED_PHASES),
                    "phase_count": len(PORTFOLIO_DEMO_REQUIRED_PHASES),
                    "verification_evidence": MATRIX_PHASE_PROFILE_EVIDENCE,
                    "not_computed": list(MATRIX_NOT_COMPUTED),
                },
                "reduced_system_approval": {
                    "reviewer_id": "",
                    "approved_at": "",
                    "approval_reason": "",
                    "acknowledged": False,
                    "no_scientific_approval_required": True,
                    "reason": "公开合成演示，不形成科研结论，因此不要求具名科研审批。",
                    "component_profile_id": PORTFOLIO_DEMO_COMPONENT_PROFILE_ID,
                    "phase_profile_id": PORTFOLIO_DEMO_PHASE_PROFILE_ID,
                    "database_id": database_entry.get("database_id"),
                    "database_sha256": database_entry.get("sha256"),
                },
                "composition_basis": {
                    "composition_input_unit": "wt_pct",
                    "provided_wt_pct": dict(demo_policy.get("composition_wt_pct") or {}),
                    "public_synthetic_input": True,
                    "synthetic_note": demo_policy.get("synthetic_note"),
                    "silent_element_omission": False,
                    "missing_values_are_zero": False,
                },
                "claims": {
                    "result_type": RESULT_TYPE,
                    "review_status": REVIEW_STATUS,
                    "is_complete_phase_diagram": False,
                    "result_label": RESULT_LABEL_MATRIX,
                    "portfolio_demo": True,
                    "not_for_scientific_conclusion": True,
                    "writes_back_formal_experimental_data": False,
                    "reduced_component_system": False,
                },
                "reduced_component_system": False,
                "controlled_exclusions": [],
                "controlled_exclusions_confirmed_by": "",
                "exclusion_policy": {},
                "limitation_notice": {
                    "zh": "本结果是公开合成 Fe-C 演示，用于展示开源计算热力学工具链；"
                          "不是实验测量值，也不能用于任何科研结论、真实钢种分析或生产决策。",
                    "en": "This is a public synthetic Fe-C demonstration of an open-source "
                          "computational-thermodynamics toolchain. It is not an experimental "
                          "measurement and must not be used for scientific conclusions, real "
                          "steel-grade analysis or production decisions.",
                },
                "database_compatibility": {
                    "status": dict(database_validation.get("compatibility", {}) or {}).get("status"),
                    "pinned_pycalphad_version": expected_version,
                    "evidence": MATRIX_PHASE_PROFILE_EVIDENCE,
                },
                "model_losses": dict(reduced_policy_model_losses()),
                "component_versions_and_hashes": {
                    "pycalphad": expected_version,
                    "database_id": database_entry.get("database_id"),
                    "database_version_or_date": database_entry.get("version_or_date"),
                    "database_sha256": database_entry.get("sha256"),
                },
                "solver_mode": INDEPENDENT_SOLVER_MODE,
                "result_label": RESULT_LABEL_MATRIX,
                "prohibited_result_labels": list(PROHIBITED_RESULT_LABELS) + ["真实钢种计算结果"],
                "output_phase_fraction_basis": (resolved.get("method", {}) or {}).get(
                    "output_phase_fraction_basis"),
                "output_phase_fraction_basis_note": (resolved.get("method", {}) or {}).get(
                    "output_phase_fraction_basis_note"),
            }
            request["request_digest"] = digest_value(
                {key: value for key, value in request.items() if key != "request_digest"}
            )

    state = "blocked" if gates else "ready"
    return CalphadPhaseFractionPreview(
        state=state,
        sample_id=PORTFOLIO_DEMO_ID,
        gates=tuple(gates),
        warnings=tuple(warnings),
        environment=environment,
        database=database,
        temperature={"values_C": _demo_temperature_points(demo_policy or {})[0]} if request else {},
        composition={"public_synthetic_input": True,
                     "composition_wt_pct": dict((demo_policy or {}).get("composition_wt_pct") or {})},
        request=request if not gates else None,
        limitation_notice=(request or {}).get("limitation_notice") or {
            "zh": "公开合成演示，不构成科研结论。",
            "en": "Public synthetic demo; not a scientific conclusion.",
        },
        reduced_system={
            "portfolio_demo": True,
            "demo_policy_id": (demo_policy or {}).get("policy_id"),
            "demo_id": (demo_policy or {}).get("demo_id"),
            "status": demo_report.get("status"),
            "phases": list(PORTFOLIO_DEMO_REQUIRED_PHASES),
            "solver_mode": INDEPENDENT_SOLVER_MODE,
            "flags": dict(PORTFOLIO_DEMO_FLAGS),
            "not_for": list(demo_report.get("not_for", []) or []),
        },
    )


def reduced_policy_model_losses() -> dict[str, Any]:
    """The permanent model losses, read from the fixed reduced-system policy."""
    try:
        return dict((load_reduced_system_policy().get("model_losses") or {}))
    except (OSError, ValueError):
        return {}


def _element_mole_fractions(
    composition_wt_pct: Mapping[str, Any],
    atomic_weights: Mapping[str, Any],
) -> dict[str, float]:
    """Convert a small public synthetic composition to mole fractions (Fe as balance)."""
    provided = {key: float(value) for key, value in composition_wt_pct.items()
                if key != "Fe" and isinstance(value, (int, float))}
    if not provided:
        return {}
    missing = [element for element in provided if element not in atomic_weights]
    if missing:
        return {}
    moles = {element: value / float(atomic_weights[element]) for element, value in provided.items()}
    if "Fe" not in atomic_weights:
        return {}
    iron_wt = 100.0 - sum(provided.values())
    moles["Fe"] = iron_wt / float(atomic_weights["Fe"])
    total = sum(moles.values())
    if total <= 0:
        return {}
    return {element: value / total for element, value in moles.items()}


def assess_composition(
    composition: Mapping[str, float | None],
    *,
    covered_elements: set[str] | None = None,
    fe_balance_confirmed_by: str = "",
    unprovided_elements_declared_by: str = "",
    atomic_weights: Mapping[str, float] | None = None,
    approved_exclusions: Mapping[str, str] | None = None,
    sample_id: str = "",
) -> dict[str, Any]:
    """Classify the declared composition and decide what may enter the model.

    ``None`` means "declared in the sample record but no value" and is never treated as
    zero.  A non-zero element outside the TDB always blocks unless the versioned exclusion
    policy explicitly approves that (sample, element) pair; there is no generic override.
    """
    covered = {str(element) for element in (covered_elements or set())}
    weights = dict(atomic_weights or {})

    declared: list[str] = []
    provided: dict[str, float] = {}
    invalid: list[str] = []
    unprovided: list[str] = []
    for key, value in composition.items():
        name = str(key)
        if name in NON_ELEMENT_COLUMNS or not ELEMENT_SYMBOL.fullmatch(name):
            continue
        declared.append(name)
        if value is None:
            unprovided.append(name)
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            invalid.append(name)
            continue
        if numeric < 0:
            invalid.append(name)
            continue
        provided[name] = numeric

    zero_valued = sorted(element for element, value in provided.items() if value == 0)
    sum_other = round(sum(provided.values()), 6)

    fe_balance_wt_pct: float | None = None
    if "Fe" in provided:
        fe_source = "provided"
    elif "Fe" in unprovided:
        fe_source = "declared_without_value"
    else:
        fe_source = "balance"
        fe_balance_wt_pct = round(100.0 - sum_other, 6)

    effective = dict(provided)
    if fe_source == "balance" and fe_balance_wt_pct is not None and 0 < fe_balance_wt_pct <= 100:
        effective["Fe"] = fe_balance_wt_pct

    # Coverage is judged on the composition that would actually enter the model, so a
    # balance-computed Fe is checked against the TDB exactly like a provided element.
    nonzero = sorted(element for element, value in effective.items() if value > 0)
    uncovered_nonzero = sorted(element for element in nonzero if element not in covered)
    uncovered_zero = sorted(element for element in zero_valued if element not in covered)

    excluded: dict[str, str] = {}
    for element in sorted(set(effective) - covered):
        if effective[element] > 0:
            excluded[element] = "nonzero_element_not_covered_by_registered_database"
        else:
            excluded[element] = "declared_zero_wt_pct_and_not_in_database"
    for element in unprovided:
        excluded[element] = "declared_without_value_and_excluded_by_named_user_declaration"

    # Controlled, policy-bound exclusions.  Only (sample, element, category) triples enumerated in
    # the versioned exclusion policy may be excluded; everything else keeps the strict phase-1
    # behaviour (hard block, no silent omission, no zero fill).
    approvals = dict(approved_exclusions or {})
    controlled: list[dict[str, Any]] = []

    def record(element: str, category: str) -> None:
        if element in provided:
            status, value = "measured", provided[element]
        else:
            status, value = "missing", None
        controlled.append({
            "sample_id": sample_id,
            "element": element,
            "category": category,
            "value_status": status,
            "value_wt_pct": value,
            "excluded_from_component_system": True,
        })

    blocked_nonzero: list[str] = []
    for element in uncovered_nonzero:
        category = approvals.get(element)
        if category == "database_not_covered":
            record(element, category)
        else:
            blocked_nonzero.append(element)

    blocked_unprovided: list[str] = []
    for element in sorted(unprovided):
        category = approvals.get(element)
        if category == "input_unknown":
            record(element, category)
        else:
            blocked_unprovided.append(element)

    for element in uncovered_zero:
        category = approvals.get(element) or "measured_zero"
        record(element, category)

    # T86 phase-4 category: the element is covered by the database and carries a measured value, but
    # the fixed reduced-system profile excludes it to stay inside the measured solver capacity limit.
    capacity_reduced: list[str] = []
    for element in sorted(effective):
        if element in covered and approvals.get(element) == CAPACITY_REDUCTION_CATEGORY:
            record(element, CAPACITY_REDUCTION_CATEGORY)
            capacity_reduced.append(element)

    excluded_from_model = {str(item["element"]) for item in controlled}
    included = sorted(element for element in effective
                      if element in covered and element not in excluded_from_model)

    mole_full: dict[str, float] = {}
    mole_model: dict[str, float] = {}
    weight_problems: list[str] = []
    if effective:
        missing_weights = sorted(element for element in effective if element not in weights)
        if missing_weights:
            weight_problems = [f"缺少原子量：{', '.join(missing_weights)}"]
        else:
            moles = {element: effective[element] / float(weights[element]) for element in effective}
            total = sum(moles.values())
            if total <= 0:
                weight_problems = ["总摩尔数为 0，无法换算摩尔分数。"]
            else:
                mole_full = {element: moles[element] / total for element in sorted(moles)}
                included_total = sum(moles[element] for element in included)
                if included_total > 0:
                    mole_model = {element: moles[element] / included_total for element in included}

    fe_confirmation_required = fe_source == "balance"
    fe_confirmed = bool(fe_balance_confirmed_by.strip())
    unprovided_declared = bool(unprovided_elements_declared_by.strip())

    return {
        "declared_elements": sorted(declared),
        "provided_wt_pct": {element: provided[element] for element in sorted(provided)},
        "unprovided_elements": sorted(unprovided),
        "invalid_elements": sorted(invalid),
        "zero_wt_pct_elements": zero_valued,
        "nonzero_elements": nonzero,
        "provided_nonzero_elements": sorted(element for element, value in provided.items() if value > 0),
        "sum_other_provided_wt_pct": sum_other,
        "fe_source": fe_source,
        "fe_balance_wt_pct": fe_balance_wt_pct,
        "fe_balance_confirmation_required": fe_confirmation_required,
        "fe_balance_confirmed_by": fe_balance_confirmed_by.strip(),
        "fe_balance_confirmed": fe_confirmed,
        "unprovided_elements_exclusion_declared_by": unprovided_elements_declared_by.strip(),
        "unprovided_elements_exclusion_declared": unprovided_declared,
        "effective_wt_pct": {element: effective[element] for element in sorted(effective)},
        "mole_fraction_full": mole_full,
        "mole_fraction_model_input": mole_model,
        "included_elements": included,
        "uncovered_nonzero_elements": uncovered_nonzero,
        "uncovered_zero_elements": uncovered_zero,
        "excluded_elements": {element: excluded[element] for element in sorted(excluded)},
        "controlled_exclusions": controlled,
        "capacity_reduction_elements": sorted(capacity_reduced),
        "approved_exclusion_elements": sorted(approvals),
        "blocked_nonzero_uncovered_elements": sorted(blocked_nonzero),
        "blocked_unprovided_elements": sorted(blocked_unprovided),
        "weight_problems": weight_problems,
        "atomic_weights_used": {element: float(weights[element]) for element in sorted(effective) if element in weights},
    }


def _temperature_points(
    minimum: Any,
    maximum: Any,
    step: Any,
    method: Mapping[str, Any],
) -> dict[str, Any]:
    limits = method.get("temperature_range_limits_C", [200, 1600])
    max_points = int(method.get("max_points", 401) or 401)
    problems: list[str] = []
    try:
        low = float(minimum)
        high = float(maximum)
        increment = float(step)
    except (TypeError, ValueError):
        return {"problems": ["温度区间或步长不是数值。"], "values_C": []}
    if increment <= 0:
        problems.append("温度步长必须大于 0。")
    if low >= high:
        problems.append("起始温度必须小于终止温度。")
    if low < float(limits[0]) or high > float(limits[1]):
        problems.append(f"温度区间必须落在 {limits[0]:g}–{limits[1]:g} °C 以内。")
    if not problems:
        count = int(round((high - low) / increment)) + 1
        if count < 2:
            problems.append("温度点少于 2 个。")
        elif count > max_points:
            problems.append(f"温度点 {count} 超过上限 {max_points}，请增大步长。")
        else:
            values = [round(low + index * increment, 6) for index in range(count)]
            return {
                "problems": [],
                "values_C": values,
                "values_K": [round(value + 273.15, 6) for value in values],
                "min_C": low,
                "max_C": high,
                "step_C": increment,
                "count": count,
            }
    return {
        "problems": problems,
        "values_C": [],
        "values_K": [],
        "min_C": None,
        "max_C": None,
        "step_C": None,
        "count": 0,
    }


def assess_phase_fraction_request(
    composition_wt_pct: Mapping[str, float | None],
    *,
    sample_id: str = "",
    database: Mapping[str, Any] | None = None,
    database_validation: Mapping[str, Any] | None = None,
    temperature_min_C: Any = None,
    temperature_max_C: Any = None,
    step_C: Any = None,
    fe_balance_confirmed_by: str = "",
    unprovided_elements_declared_by: str = "",
    controlled_exclusions_confirmed_by: str = "",
    reduced_system_reviewer_id: str = "",
    reduced_system_approved_at: str = "",
    reduced_system_approval_reason: str = "",
    reduced_system_acknowledged: bool = False,
    exclusion_policy: Mapping[str, Any] | None = None,
    reduced_system_policy: Mapping[str, Any] | None = None,
    reduced_system_report: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every composition/temperature gate and build the isolated-worker request."""
    resolved = _safe_config(config)
    method = resolved.get("method", {})
    claims = resolved.get("claims", {})
    component = resolved.get("component", {})
    defaults = method.get("default_temperature_range_C", [600, 900])
    covered = {str(element) for element in (database or {}).get("covered_elements", []) or []}
    # Coverage blocks are only meaningful once a database has been registered and its
    # hash, authorization and element list have all been validated.
    database_usable = database is not None and (
        database_validation is None or database_validation.get("status") == "passed"
    )
    compatibility = dict((database_validation or {}).get("compatibility", {}) or {})
    approves = approved_exclusions_for(exclusion_policy, sample_id, database)
    limitation_notice = dict((exclusion_policy or {}).get("limitation_notice", {}) or {})
    reduced_report = dict(reduced_system_report or {}) if isinstance(reduced_system_report, Mapping) else {}
    reduced_ok = reduced_report.get("status") == "passed" if reduced_report else bool(reduced_system_policy)
    profile_phases = matrix_phase_profile(reduced_system_policy)
    profile_elements = tuple(
        str(element) for element in ((reduced_system_policy or {}).get("component_profile") or {}).get(
            "included_elements", []) or []
    )
    approved_capacity_elements = capacity_reduction_elements(reduced_system_policy)

    if temperature_min_C is None:
        temperature_min_C = defaults[0] if defaults else 600
    if temperature_max_C is None:
        temperature_max_C = defaults[1] if len(defaults) > 1 else 900
    if step_C is None:
        step_C = method.get("default_step_C", 10)

    gates: list[CalphadGate] = []
    warnings: list[str] = []

    assessment = assess_composition(
        composition_wt_pct,
        covered_elements=covered,
        fe_balance_confirmed_by=fe_balance_confirmed_by,
        unprovided_elements_declared_by=unprovided_elements_declared_by,
        atomic_weights=method.get("atomic_weights", {}).get("elements", {}),
        approved_exclusions=approves,
        sample_id=sample_id,
    )
    controlled = list(assessment["controlled_exclusions"])
    exclusion_confirmed = bool(controlled_exclusions_confirmed_by.strip())

    if assessment["invalid_elements"]:
        gates.append(CalphadGate(
            "CALPHAD-COMP-004",
            "成分值无效（负数或非数值）：" + "、".join(assessment["invalid_elements"]) + "。",
        ))
    if assessment["blocked_unprovided_elements"]:
        gates.append(CalphadGate(
            "CALPHAD-COMP-001",
            "以下元素已在样品成分中声明但没有数值，未按 0 处理："
            + "、".join(assessment["blocked_unprovided_elements"])
            + "。请补充数值，或（仅限排除政策已批准的样品与元素）由具名用户确认按未检出处理并排除出计算体系。",
        ))
    if database_usable and assessment["blocked_nonzero_uncovered_elements"]:
        gates.append(CalphadGate(
            "CALPHAD-COMP-002",
            "以下元素在成分中非零，但登记的 TDB 未覆盖、且不在批准排除政策内，因此阻断计算（没有通用忽略开关，不省略、不补零）："
            + "、".join(assessment["blocked_nonzero_uncovered_elements"])
            + "。请更换覆盖这些元素的授权 TDB，或按流程为该样品单独登记排除决定。",
        ))
    if assessment["fe_balance_confirmation_required"] and not assessment["fe_balance_confirmed"]:
        gates.append(CalphadGate(
            "CALPHAD-COMP-003",
            "样品成分没有 Fe 值。按余量计算 Fe = 100 - Σ其他元素 = "
            f"{assessment['fe_balance_wt_pct']:.4f} wt.% 需要用户具名确认后才能使用。",
        ))
    if assessment["fe_source"] == "balance" and assessment["fe_balance_wt_pct"] is not None:
        if not 0 < assessment["fe_balance_wt_pct"] <= 100:
            gates.append(CalphadGate(
                "CALPHAD-COMP-005",
                f"Fe 余量计算得到 {assessment['fe_balance_wt_pct']:.4f} wt.%，超出 (0, 100] 有效范围。",
            ))
        elif assessment["fe_balance_wt_pct"] < 50:
            warnings.append(
                f"Fe 余量为 {assessment['fe_balance_wt_pct']:.4f} wt.%，低于 50 wt.%，请确认成分表确实适用于该钢种。"
            )
    if assessment["fe_source"] == "declared_without_value":
        gates.append(CalphadGate(
            "CALPHAD-COMP-006",
            "样品成分中声明了 Fe 但没有数值；不得按余量替代已声明的 Fe 列。",
        ))
    if database_usable and assessment["uncovered_zero_elements"]:
        warnings.append(
            "以下元素在成分中为 0 wt.% 且不在 TDB 内，已记录为排除项（0 wt.% 不参与模型体系）："
            + "、".join(assessment["uncovered_zero_elements"])
        )
    if assessment["weight_problems"]:
        gates.append(CalphadGate(
            "CALPHAD-COMP-007",
            "wt.% → 摩尔分数换算不完整：" + "；".join(assessment["weight_problems"]),
        ))

    # --- T86 phase 4: fixed reduced-system profile -------------------------------------------------
    if not reduced_ok:
        gates.append(CalphadGate(
            "CALPHAD-POLICY-002",
            "缩减体系政策无效或不可读（config/calphad_reduced_system_v1.0.json）："
            + "；".join(reduced_report.get("problems", []) or ["未提供政策"])
            + "。本阶段只允许固定的 12 组元体系与固定相集合，没有通用选择开关。",
        ))
    used_capacity_reduction = sorted(
        item["element"] for item in controlled if item["category"] == CAPACITY_REDUCTION_CATEGORY
    )
    if used_capacity_reduction and not reduced_ok:
        gates.append(CalphadGate(
            "CALPHAD-COMP-013",
            "本次运行使用了容量型排除（" + "、".join(used_capacity_reduction)
            + "），但缩减体系政策无效或未提供；容量型排除只能与固定的缩减体系政策一起使用。",
        ))
    if used_capacity_reduction:
        unauthorised = sorted(set(used_capacity_reduction) - set(approved_capacity_elements))
        if unauthorised:
            gates.append(CalphadGate(
                "CALPHAD-COMP-013",
                "以下元素的容量型排除不在缩减体系政策批准的范围内：" + "、".join(unauthorised) + "。",
            ))

    # --- named approval for a real-sample run -----------------------------------------------------
    approval_missing: list[str] = []
    if not str(reduced_system_reviewer_id).strip():
        approval_missing.append("reviewer_id（具名批准人）")
    approved_at_text = str(reduced_system_approved_at).strip()
    if not approved_at_text:
        approval_missing.append("批准时间")
    elif not ISO_TIMESTAMP_PATTERN.fullmatch(approved_at_text):
        approval_missing.append("批准时间（需为 YYYY-MM-DD 或 ISO 8601 日期时间）")
    if not str(reduced_system_approval_reason).strip():
        approval_missing.append("批准理由")
    if not reduced_system_acknowledged:
        approval_missing.append("确认文本勾选")
    if approval_missing and reduced_ok:
        gates.append(CalphadGate(
            "CALPHAD-COMP-011",
            "真实样品运行前必须完成具名批准，当前缺少：" + "、".join(approval_missing)
            + "。批准字段、排除元素列表、缩减体系版本、相集合版本、数据库版本与 SHA-256 都会写入结果记录；代码不代填姓名。",
        ))
    if controlled and not exclusion_confirmed:
        gates.append(CalphadGate(
            "CALPHAD-COMP-011",
            "本次运行使用了受控元素排除（" + "、".join(item["element"] for item in controlled) + "），"
            "必须填写具名确认人；每次运行的排除清单、原因、确认人与数据库版本/哈希都会写入结果记录。",
        ))

    temperature = _temperature_points(temperature_min_C, temperature_max_C, step_C, method)
    if temperature["problems"]:
        gates.append(CalphadGate("CALPHAD-RANGE-001", "温度区间无效：" + "；".join(temperature["problems"])))

    if database is None:
        gates.append(CalphadGate("CALPHAD-TDB-000", "尚未选择已登记的 TDB。"))
    elif database_validation is not None and database_validation.get("status") != "passed":
        gates.append(CalphadGate(
            "CALPHAD-TDB-001",
            "TDB 登记未通过校验：" + "；".join(database_validation.get("problems", [])),
        ))
    elif not covered:
        gates.append(CalphadGate("CALPHAD-TDB-005", "TDB 登记没有声明任何覆盖元素。"))
    elif compatibility.get("status") != COMPATIBILITY_PASSED:
        gates.append(CalphadGate(
            "CALPHAD-TDB-007",
            "TDB 未通过与 pycalphad 固定版本的兼容性门禁（记录状态："
            f"{compatibility.get('status', 'missing')}）：{compatibility.get('blocked_reason') or '未记录原因'}。"
            "禁止删除关键字、改写数据库或制作未经验证的兼容版 TDB。",
        ))
    else:
        # The fixed phase profile must be a subset of the phases the registration declares.  The
        # worker re-checks this against the parsed database, so a wrong registration cannot silently
        # drop or rename a phase.
        covered_phases = {str(name) for name in (database or {}).get("covered_phases", []) or []}
        if profile_phases and covered_phases:
            missing_phases = [name for name in profile_phases if name not in covered_phases]
            if missing_phases:
                gates.append(CalphadGate(
                    "CALPHAD-PHASE-001",
                    "固定相集合中的以下相在已登记数据库中不存在：" + "、".join(missing_phases)
                    + "。不得自动替换相名、不得改写 TDB 强行启用；请从第一版相集合中移除并记录原因。",
                ))

    declared_range = (database or {}).get("declared_temperature_range_C")
    if (
        isinstance(declared_range, list)
        and len(declared_range) == 2
        and temperature.get("min_C") is not None
        and temperature.get("max_C") is not None
    ):
        if temperature["min_C"] < float(declared_range[0]) or temperature["max_C"] > float(declared_range[1]):
            warnings.append(
                f"所请求的温度区间超出 TDB 声明的适用区间 "
                f"{float(declared_range[0]):g}–{float(declared_range[1]):g} °C；超出部分属于模型外推。"
            )

    components: list[str] = []
    component_mole_fractions: dict[str, float] = {}
    profile_elements_upper = tuple(sorted(str(element).upper() for element in profile_elements))
    computed_profile_match = False
    if database_usable and not assessment["included_elements"]:
        gates.append(CalphadGate(
            "CALPHAD-COMP-010",
            "登记的 TDB 与当前成分没有共同覆盖的组元，无法构成计算体系。",
        ))
    if not gates and database_usable and assessment["included_elements"]:
        included = assessment["included_elements"]
        if "Fe" not in included:
            gates.append(CalphadGate("CALPHAD-COMP-008", "计算体系缺少 Fe（TDB 未覆盖 Fe 或成分中没有 Fe）。"))
        elif len(included) < 2:
            gates.append(CalphadGate("CALPHAD-COMP-009", "计算体系只有 Fe 一个组元，无法形成多元平衡计算。"))
        else:
            computed = tuple(sorted(str(element).upper() for element in included))
            if profile_elements_upper and computed != profile_elements_upper:
                display = {str(element).upper(): str(element) for element in profile_elements}
                missing = [display.get(name, name)
                           for name in sorted(set(profile_elements_upper) - set(computed))]
                extra = sorted(set(computed) - set(profile_elements_upper))
                gates.append(CalphadGate(
                    "CALPHAD-COMP-012",
                    f"成分与批准排除推导出的计算体系有 {len(computed)} 个组元，与固定缩减体系 "
                    f"{COMPONENT_PROFILE_ID} 的 {len(profile_elements_upper)} 个组元不一致"
                    + (f"（缺少：{'、'.join(missing)}）" if missing else "")
                    + (f"（多出：{'、'.join(extra)}）" if extra else "")
                    + "。这是固定、版本化的政策，没有通用选择开关；任何其他元素缺失、数据库不覆盖、"
                    "被临时删除或额外出现都必须阻断，不得自动替换、静默省略或补零。",
                ))
            else:
                components = [element.upper() for element in included]
                component_mole_fractions = {
                    element.upper(): round(assessment["mole_fraction_model_input"].get(element, 0.0), 10)
                    for element in included
                    if element != "Fe"
                }
                computed_profile_match = True

    request: dict[str, Any] | None = None
    if not gates and database_usable and components:
        request = {
            "request_schema_version": "1.1",
            "adapter_version": ADAPTER_VERSION,
            "feature": "calphad_phase_fraction",
            "phase": "phase_4_reduced_system_matrix_and_major_carbides",
            "sample_id": sample_id,
            "pycalphad_version": component.get("version"),
            "database": {
                "database_id": database.get("database_id"),
                "path": database.get("path"),
                "sha256": database.get("sha256"),
                "format": database.get("format"),
                "provider": database.get("provider"),
                "version_or_date": database.get("version_or_date"),
                "license_or_authorization": database.get("license_or_authorization"),
                "authorization_status": database.get("authorization_status"),
                "authorized_by": database.get("authorized_by"),
                "citation": database.get("citation"),
                "declared_temperature_range_C": database.get("declared_temperature_range_C"),
            },
            "units": {
                "composition_input": "wt_pct",
                "composition_internal": "mole_fraction",
                "temperature_input": "degC",
                "temperature_internal": "K",
                "pressure": "Pa",
                "output_phase_fraction": "mole_fraction_of_phase",
            },
            "temperature": {
                "min_C": temperature["min_C"],
                "max_C": temperature["max_C"],
                "step_C": temperature["step_C"],
                "values_C": temperature["values_C"],
                "values_K": temperature["values_K"],
            },
            "pressure_Pa": float(method.get("pressure_Pa", 101325)),
            "components": components,
            "component_mole_fractions": component_mole_fractions,
            "phases": list(profile_phases),
            "component_profile": {
                "profile_id": COMPONENT_PROFILE_ID,
                "version": COMPONENT_PROFILE_VERSION,
                "included_elements": list(profile_elements),
                "included_element_count": len(profile_elements),
                "component_list_length": len(components) + 1,
                "excluded_elements": [
                    {"elements": list(group.get("elements", []) or []),
                     "category": str(group.get("category", "")),
                     "reason": str(group.get("reason", ""))}
                    for group in ((reduced_system_policy or {}).get("component_profile") or {}).get(
                        "excluded_elements", []) or []
                    if isinstance(group, Mapping)
                ],
                "derived_from_composition": list(assessment["included_elements"]),
                "matches_profile": computed_profile_match,
            },
            "phase_profile": {
                "profile_id": PHASE_PROFILE_ID,
                "version": PHASE_PROFILE_VERSION,
                "phases": list(profile_phases),
                "phase_count": len(profile_phases),
                "verification_evidence": MATRIX_PHASE_PROFILE_EVIDENCE,
                "verification_script": MATRIX_PHASE_PROFILE_SCRIPT,
                "not_computed": list(MATRIX_NOT_COMPUTED),
            },
            "reduced_system_approval": {
                "reviewer_id": str(reduced_system_reviewer_id).strip(),
                "approved_at": approved_at_text,
                "approval_reason": str(reduced_system_approval_reason).strip(),
                "acknowledged": bool(reduced_system_acknowledged),
                "acknowledgement_text": MATRIX_ACKNOWLEDGEMENT_TEXT,
                "component_profile_id": COMPONENT_PROFILE_ID,
                "component_profile_version": COMPONENT_PROFILE_VERSION,
                "phase_profile_id": PHASE_PROFILE_ID,
                "phase_profile_version": PHASE_PROFILE_VERSION,
                "excluded_elements": sorted(str(item["element"]) for item in controlled),
                "database_id": database.get("database_id"),
                "database_version_or_date": database.get("version_or_date"),
                "database_sha256": database.get("sha256"),
                "reduced_system_policy_id": (reduced_system_policy or {}).get("policy_id"),
                "no_default_reviewer_in_code": True,
            },
            "result_label": RESULT_LABEL_MATRIX,
            "prohibited_result_labels": list(PROHIBITED_RESULT_LABELS),
            "model_losses": dict(((reduced_system_policy or {}).get("model_losses") or {})),
            "component_versions_and_hashes": {
                "pycalphad": component.get("version"),
                "pycalphad_wheel_sha256": (component.get("artifacts", {}) or {}).get(
                    "cp312_win_amd64", {}).get("sha256"),
                "database_id": database.get("database_id"),
                "database_version_or_date": database.get("version_or_date"),
                "database_sha256": database.get("sha256"),
                "community_derivative_commit": database.get("source_commit"),
                "community_derivative_repository": database.get("source_repository"),
            },
            "composition_basis": {
                "composition_input_unit": "wt_pct",
                "provided_wt_pct": assessment["provided_wt_pct"],
                "effective_wt_pct": assessment["effective_wt_pct"],
                "unprovided_elements": assessment["unprovided_elements"],
                "unprovided_elements_excluded": sorted(assessment["unprovided_elements"])
                if assessment["unprovided_elements_exclusion_declared"]
                else [],
                "unprovided_elements_exclusion_declared_by": assessment["unprovided_elements_exclusion_declared_by"],
                "zero_wt_pct_elements": assessment["zero_wt_pct_elements"],
                "uncovered_zero_elements": assessment["uncovered_zero_elements"],
                "nonzero_elements": assessment["nonzero_elements"],
                "sum_other_provided_wt_pct": assessment["sum_other_provided_wt_pct"],
                "fe_source": assessment["fe_source"],
                "fe_balance_wt_pct": assessment["fe_balance_wt_pct"],
                "fe_balance_confirmed_by": assessment["fe_balance_confirmed_by"],
                "mole_fraction_full": assessment["mole_fraction_full"],
                "mole_fraction_model_input": assessment["mole_fraction_model_input"],
                "atomic_weights_used": assessment["atomic_weights_used"],
                "atomic_weights_source": method.get("atomic_weights", {}).get("source"),
                "atomic_weights_source_status": method.get("atomic_weights", {}).get("source_status"),
                "excluded_elements": assessment["excluded_elements"],
                "missing_values_are_zero": False,
                "silent_element_omission": False,
            },
            "claims": {
                "result_type": claims.get("result_type", RESULT_TYPE),
                "review_status": claims.get("review_status", REVIEW_STATUS),
                "is_complete_phase_diagram": False,
                "curve_label": claims.get("curve_label", CURVE_LABEL),
                "result_label": RESULT_LABEL_MATRIX,
                "writes_back_formal_experimental_data": False,
                "reduced_component_system": True,
            },
            "reduced_component_system": True,
            "controlled_exclusions": controlled,
            "controlled_exclusions_confirmed_by": controlled_exclusions_confirmed_by.strip(),
            "exclusion_policy": {
                "policy_id": (exclusion_policy or {}).get("policy_id"),
                "approved_by": (exclusion_policy or {}).get("approved_by"),
                "approved_at": (exclusion_policy or {}).get("approved_at"),
                "database_scope": (exclusion_policy or {}).get("database_scope"),
            },
            "limitation_notice": {
                "zh": limitation_notice.get("zh", DEFAULT_LIMITATION_NOTICE_ZH),
                "en": limitation_notice.get("en", DEFAULT_LIMITATION_NOTICE_EN),
            },
            "database_compatibility": {
                "status": compatibility.get("status"),
                "pinned_pycalphad_version": compatibility.get("pinned_pycalphad_version"),
                "checked_at": compatibility.get("checked_at"),
                "evidence": compatibility.get("evidence"),
            },
            "output_phase_fraction_basis": method.get("output_phase_fraction_basis"),
            "output_phase_fraction_basis_note": method.get("output_phase_fraction_basis_note"),
        }
        request["request_digest"] = digest_value({key: value for key, value in request.items() if key != "request_digest"})

    return {
        "gates": gates,
        "warnings": warnings,
        "request": request,
        "composition": assessment,
        "temperature": temperature,
        "components": components,
        "component_mole_fractions": component_mole_fractions,
        "component_profile": {
            "profile_id": COMPONENT_PROFILE_ID,
            "version": COMPONENT_PROFILE_VERSION,
            "included_elements": list(profile_elements),
            "matches_profile": computed_profile_match,
        },
        "phase_profile": {
            "profile_id": PHASE_PROFILE_ID,
            "version": PHASE_PROFILE_VERSION,
            "phases": list(profile_phases),
        },
        "reduced_system_report": reduced_report,
    }


def preview_phase_fraction_curve(
    composition_wt_pct: Mapping[str, float | None],
    *,
    sample_id: str = "",
    database_id: str = "",
    temperature_min_C: Any = None,
    temperature_max_C: Any = None,
    step_C: Any = None,
    fe_balance_confirmed_by: str = "",
    unprovided_elements_declared_by: str = "",
    controlled_exclusions_confirmed_by: str = "",
    reduced_system_reviewer_id: str = "",
    reduced_system_approved_at: str = "",
    reduced_system_approval_reason: str = "",
    reduced_system_acknowledged: bool = False,
    registry_path: Path | None = None,
    exclusion_policy_path: Path | None = None,
    reduced_system_policy_path: Path | None = None,
    config: Mapping[str, Any] | None = None,
    config_path: Path = CONFIG_PATH,
    project_root: Path = ROOT,
    environment: Mapping[str, Any] | None = None,
) -> CalphadPhaseFractionPreview:
    """Resolve every gate that must pass before the isolated worker may run."""
    try:
        resolved = dict(config) if config is not None else load_adapter_config(config_path)
    except (OSError, ValueError) as exc:
        resolved = {}
        config_error = f"无法读取 CALPHAD 登记 {config_path}：{exc}"
    else:
        config_error = ""

    gates: list[CalphadGate] = []
    warnings: list[str] = []
    if config_error:
        gates.append(CalphadGate("CALPHAD-CONFIG-001", config_error))

    disabled_reason = feature_disabled_reason(resolved)
    if disabled_reason:
        return CalphadPhaseFractionPreview(
            state="disabled",
            sample_id=sample_id,
            gates=(CalphadGate("CALPHAD-DISABLED-001", f"本功能已关闭（{disabled_reason}）。既有物理计算不受影响。"),),
            warnings=(),
            environment={"status": "disabled", "detail": disabled_reason},
            database={"status": "not_checked"},
            temperature={},
            composition={},
            request=None,
        )

    component = resolved.get("component", {})
    expected_version = str(component.get("version", ""))
    if environment is None:
        environment = probe_isolated_environment(
            interpreter_configuration(resolved, project_root),
            expected_version,
            resolved,
        )
    else:
        environment = dict(environment)

    environment_gate_codes = {
        "not_configured": "CALPHAD-ENV-001",
        "interpreter_missing": "CALPHAD-ENV-001",
        "probe_failed": "CALPHAD-ENV-002",
        "dependency_missing": "CALPHAD-ENV-002",
        "version_mismatch": "CALPHAD-ENV-003",
    }
    if environment.get("status") != "ready":
        code = environment_gate_codes.get(str(environment.get("status")), "CALPHAD-ENV-002")
        gates.append(CalphadGate(
            code,
            f"隔离环境未就绪（{environment.get('status')}）：{environment.get('detail', '')}",
        ))

    registry = load_tdb_registry(registry_path, resolved, project_root)
    database: dict[str, Any] = {"status": registry.get("status"), "detail": registry.get("detail", "")}
    database_entry: Mapping[str, Any] | None = None
    database_validation: dict[str, Any] | None = None
    if registry.get("status") == "not_registered":
        gates.append(CalphadGate(
            "CALPHAD-TDB-000",
            "尚未登记任何授权 TDB。请按 config/calphad_tdb.example.json 建立本地登记文件 "
            f"（{registry.get('path')}），登记来源、授权依据、覆盖元素与 SHA-256。",
        ))
    elif registry.get("status") == "invalid":
        gates.append(CalphadGate("CALPHAD-TDB-001", str(registry.get("detail", "TDB 登记无效"))))
    else:
        databases = list(registry.get("databases", []))
        if not databases:
            gates.append(CalphadGate("CALPHAD-TDB-000", "TDB 登记文件中没有任何数据库条目。"))
        else:
            database_entry = select_database(databases, database_id)
            if database_entry is None:
                gates.append(CalphadGate("CALPHAD-TDB-006", f"登记文件中没有 database_id={database_id} 的条目。"))
            else:
                database_validation = validate_tdb_registration(
                    database_entry, project_root=project_root, pinned_version=expected_version
                )
                database = {
                    "status": database_validation["status"],
                    "database_id": database_validation["database_id"],
                    "sha256": database_validation["sha256"],
                    "actual_sha256": database_validation["actual_sha256"],
                    "file_status": database_validation["file_status"],
                    "problems": database_validation["problems"],
                    "registry_path": registry.get("path"),
                    "covered_elements": database_validation["covered_elements"],
                    "covered_phases": database_validation.get("covered_phases", []),
                    "compatibility": database_validation.get("compatibility", {}),
                }

    policy_path = exclusion_policy_path or EXCLUSION_POLICY_PATH
    policy_status = validate_exclusion_policy(policy_path)
    exclusion_policy: dict[str, Any] | None = None
    try:
        exclusion_policy = load_exclusion_policy(policy_path)
    except (OSError, ValueError):
        exclusion_policy = None
    if policy_status["status"] != "passed":
        gates.append(CalphadGate(
            "CALPHAD-POLICY-001",
            "受控元素排除政策未通过校验：" + "；".join(policy_status.get("problems", [])),
        ))

    # T86 phase 4: the fixed reduced-system policy is validated against module constants, so a policy
    # file edited to a different element or phase set fails closed instead of widening the run.
    resolved_reduced_path = reduced_system_policy_path or REDUCED_SYSTEM_POLICY_PATH
    reduced_status = validate_reduced_system_policy(resolved_reduced_path)
    reduced_policy: dict[str, Any] | None = None
    try:
        reduced_policy = load_reduced_system_policy(resolved_reduced_path)
    except (OSError, ValueError):
        reduced_policy = None
    if reduced_status["status"] != "passed":
        gates.append(CalphadGate(
            "CALPHAD-POLICY-002",
            "缩减体系政策未通过校验：" + "；".join(reduced_status.get("problems", [])),
        ))

    assessment_result = assess_phase_fraction_request(
        composition_wt_pct,
        sample_id=sample_id,
        database=database_entry,
        database_validation=database_validation,
        temperature_min_C=temperature_min_C,
        temperature_max_C=temperature_max_C,
        step_C=step_C,
        fe_balance_confirmed_by=fe_balance_confirmed_by,
        unprovided_elements_declared_by=unprovided_elements_declared_by,
        controlled_exclusions_confirmed_by=controlled_exclusions_confirmed_by,
        reduced_system_reviewer_id=reduced_system_reviewer_id,
        reduced_system_approved_at=reduced_system_approved_at,
        reduced_system_approval_reason=reduced_system_approval_reason,
        reduced_system_acknowledged=reduced_system_acknowledged,
        exclusion_policy=exclusion_policy,
        reduced_system_policy=reduced_policy,
        reduced_system_report=reduced_status,
        config=resolved,
    )
    gates.extend(assessment_result["gates"])
    warnings.extend(assessment_result["warnings"])

    deduped: list[CalphadGate] = []
    seen_codes: set[str] = set()
    for gate in gates:
        if gate.code in seen_codes:
            continue
        seen_codes.add(gate.code)
        deduped.append(gate)
    gates = deduped
    warnings = list(dict.fromkeys(warnings))

    if not gates and assessment_result["request"] is None:
        gates = [CalphadGate("CALPHAD-CONFIG-002", "计算请求未生成，但没有记录到具体阻断原因；按关闭式失败处理。")]

    state = "blocked" if gates else "ready"
    return CalphadPhaseFractionPreview(
        state=state,
        sample_id=sample_id,
        gates=tuple(gates),
        warnings=tuple(warnings),
        environment=environment,
        database=database,
        temperature=assessment_result["temperature"],
        composition=assessment_result["composition"],
        request=assessment_result["request"] if not gates else None,
        exclusion_policy={
            "policy_id": (exclusion_policy or {}).get("policy_id"),
            "approved_by": (exclusion_policy or {}).get("approved_by"),
            "approved_at": (exclusion_policy or {}).get("approved_at"),
            "database_scope": (exclusion_policy or {}).get("database_scope"),
            "status": policy_status.get("status"),
            "approved_exclusion_count": policy_status.get("approved_exclusion_count"),
        },
        limitation_notice=(exclusion_policy or {}).get("limitation_notice") or {
            "zh": DEFAULT_LIMITATION_NOTICE_ZH,
            "en": DEFAULT_LIMITATION_NOTICE_EN,
        },
        reduced_system={
            "policy_id": (reduced_policy or {}).get("policy_id"),
            "policy_path": str(resolved_reduced_path),
            "status": reduced_status.get("status"),
            "approved_by": reduced_status.get("approved_by"),
            "approved_at": reduced_status.get("approved_at"),
            "component_profile": reduced_status.get("component_profile", {}),
            "phase_profile": reduced_status.get("phase_profile", {}),
            "acknowledgement_text": reduced_status.get("acknowledgement_text"),
            "result_label": RESULT_LABEL_MATRIX,
            "prohibited_result_labels": list(PROHIBITED_RESULT_LABELS),
            "not_computed": list(MATRIX_NOT_COMPUTED),
            "model_losses": reduced_status.get("model_losses", {}),
            "approval": {
                "reviewer_id": str(reduced_system_reviewer_id).strip(),
                "approved_at": str(reduced_system_approved_at).strip(),
                "approval_reason": str(reduced_system_approval_reason).strip(),
                "acknowledged": bool(reduced_system_acknowledged),
                "no_default_reviewer_in_code": True,
            },
        },
    )


def summarize_phase_amounts(
    phase_names: Any,
    phase_amounts: Any,
    *,
    tolerance: float = 1e-12,
) -> dict[str, Any]:
    """Aggregate pycalphad ``Phase``/``NP`` values into mole fractions of base phases.

    pycalphad reports one entry per phase composition set (for example ``FCC_A1`` and
    ``FCC_A1#2``).  Amounts are summed per base phase name; the denominator is the total
    number of moles over all reported phases at that point.
    """
    raw: dict[str, float] = {}
    for name, amount in zip(list(phase_names), list(phase_amounts)):
        if name is None or not isinstance(name, str):
            continue
        label = name.strip()
        if not label:
            continue
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        if value != value or value <= tolerance:  # NaN or non-positive phase amount
            continue
        raw[label] = raw.get(label, 0.0) + value

    total = sum(raw.values())
    aggregated: dict[str, float] = {}
    for label, value in raw.items():
        base = label.split("#", 1)[0]
        aggregated[base] = aggregated.get(base, 0.0) + value
    fractions = {base: value / total for base, value in sorted(aggregated.items())} if total > 0 else {}
    return {
        "total_moles": total,
        "raw_phase_amounts_mole": {label: raw[label] for label in sorted(raw)},
        "aggregated_phase_amounts_mole": {base: aggregated[base] for base in sorted(aggregated)},
        "phase_fractions_mole": fractions,
        "phases_present": sorted(fractions),
    }


def _kill_process_tree(pid: int) -> None:
    """Kill a worker and its descendants; a hung solver can hold several gigabytes."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        return
    try:
        os.killpg(os.getpgid(pid), 9)
    except (OSError, AttributeError):
        pass


def _default_worker_runner(
    request: Mapping[str, Any],
    *,
    interpreter: str,
    workdir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run the isolated worker with file-based stdio (no pipes, no shell).

    A Popen-based implementation is used so the worker PID can be recorded per point and so a
    timed-out worker is killed together with its process tree.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    request_path = workdir / "request.json"
    result_path = workdir / "result.json"
    stdout_path = workdir / "worker.stdout.log"
    stderr_path = workdir / "worker.stderr.log"
    request_path.write_text(
        json.dumps(dict(request), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    command = [str(interpreter), "-I", str(WORKER_PATH), str(request_path), str(result_path)]
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    process = None
    returncode: int | None = None
    timeout_error = ""
    timed_out = False
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, \
            stderr_path.open("w", encoding="utf-8") as stderr_handle:
        try:
            process = subprocess.Popen(
                command, stdout=stdout_handle, stderr=stderr_handle, cwd=str(ROOT),
                env=environment, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
            timeout_error = f"隔离计算超过 {timeout_seconds:g}s 未结束，已终止进程树。"
            if process is not None:
                _kill_process_tree(process.pid)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    process.kill()
        except OSError as exc:
            returncode = None
            timeout_error = f"{type(exc).__name__}: {exc}"

    payload: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            payload = _read_json(result_path)
        except (OSError, ValueError):
            payload = None
    return {
        "returncode": returncode,
        "pid": process.pid if process is not None else None,
        "timed_out": timed_out,
        "payload": payload,
        "error": timeout_error,
        "stdout_tail": _tail(stdout_path),
        "stderr_tail": _tail(stderr_path),
    }


def _tail(path: Path, limit: int = 1200) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


#: Windows NTSTATUS values seen as a process exit code, mapped to a readable cause.  The isolated
#: interpreter can be aborted by native code in the solver instead of raising a Python exception,
#: and that must be reported as an environment-level failure rather than as a missing result file.
NATIVE_EXIT_CODES: dict[int, str] = {
    0xC0000005: "ACCESS_VIOLATION（内存访问冲突）",
    0xC0000006: "IN_PAGE_ERROR（分页错误）",
    0xC00000FD: "STACK_OVERFLOW（栈溢出）",
    0xC0000374: "HEAP_CORRUPTION（堆损坏）",
    0xC0000409: "STACK_BUFFER_OVERRUN（栈缓冲区溢出）",
    0x80000003: "BREAKPOINT（断点异常）",
}


def _describe_worker_exit(returncode: Any) -> str | None:
    """Translate an abnormal worker exit code into an explicit, actionable explanation."""
    try:
        code = int(returncode)
    except (TypeError, ValueError):
        return None
    if code == 0:
        return None
    unsigned = code & 0xFFFFFFFF
    cause = NATIVE_EXIT_CODES.get(unsigned)
    if cause is None:
        if code < 0:
            return f"隔离计算进程被中止（exit code {code}，0x{unsigned:08X}）。"
        return None
    return (
        f"隔离计算进程被原生代码中止（exit code {code}，0x{unsigned:08X}，{cause}）。"
        "这与 pycalphad 0.11.2 在本机对组元数较多的体系求解时的实测行为一致："
        "在 pycalphad/core 的 minimizer 原生扩展中直接终止进程，而不是抛出 Python 异常。"
        "任何减少组元或更换数据库的处理都必须先经过人工批准并更新受控元素排除声明，"
        "不得由本页自动完成。"
    )


def _blocked_record(
    preview: CalphadPhaseFractionPreview,
    *,
    code: str,
    message: str,
    warnings: list[str] | None = None,
    extra: Mapping[str, Any] | None = None,
    status: str = "failed",
    extra_error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request = preview.request or {}
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(dict(extra_error or {}))
    record: dict[str, Any] = {
        "status": status,
        "state": "blocked",
        "error": error,
        "warnings": list(warnings or preview.warnings),
        "points": [],
        "curve": [],
        "phases": [],
        "request": preview.request,
        "result_type": RESULT_TYPE,
        "review_status": REVIEW_STATUS,
        "result_label": RESULT_LABEL_MATRIX,
        "prohibited_result_labels": list(PROHIBITED_RESULT_LABELS),
        "writes_back_formal_experimental_data": False,
        "is_complete_phase_diagram": False,
        "limitation_notice": preview.notice(),
        "reduced_component_system": True,
        "excluded_elements": sorted(
            {item["element"] for item in request.get("controlled_exclusions", [])}
        ),
        "controlled_exclusions": list(request.get("controlled_exclusions", [])),
        "component_profile": dict(request.get("component_profile", {})),
        "phase_profile": dict(request.get("phase_profile", {})),
        "included_elements": list(request.get("components", [])),
        "not_computed_in_this_phase": list(request.get("phase_profile", {}).get("not_computed", [])),
        "prohibited_interpretations": list(request.get("phase_profile", {}).get("not_computed", [])),
        "model_losses": dict(request.get("model_losses", {})),
        "component_versions_and_hashes": dict(request.get("component_versions_and_hashes", {})),
        "reduced_system_approval": dict(request.get("reduced_system_approval", {})),
    }
    record.update(dict(extra or {}))
    return record


def _sanitize_stderr(text: Any, limit: int = 400) -> str:
    """Collapse and truncate a worker stderr tail, and strip local absolute paths."""
    cleaned = " ".join(str(text or "").split())
    cleaned = cleaned.replace(str(ROOT), "<repo>")
    cleaned = cleaned.replace(str(ROOT).replace("\\", "/"), "<repo>")
    return cleaned[-limit:]


def _point_request(
    base: Mapping[str, Any],
    *,
    temperature_C: float,
    temperature_K: float,
    index: int,
    count: int,
) -> dict[str, Any]:
    """One fully independent, identical-rules request for a single temperature point.

    Everything except the temperature is copied unchanged from the curve request, so every point
    uses the same normalised composition, the same components plus VA, the same fixed phase set, the
    same pressure, the same database SHA-256 and the same pycalphad version.
    """
    request = {key: value for key, value in base.items() if key != "request_digest"}
    temperature = {key: value for key, value in (base.get("temperature") or {}).items()
                   if key not in {"values_C", "values_K"}}
    temperature["values_C"] = [round(float(temperature_C), 6)]
    temperature["values_K"] = [round(float(temperature_K), 6)]
    temperature["count"] = 1
    request["temperature"] = temperature
    request["solver_mode"] = INDEPENDENT_SOLVER_MODE
    request["point_index"] = int(index)
    request["point_count"] = int(count)
    request["single_point_process"] = True
    request["no_warm_start"] = True
    request["request_digest"] = digest_value(request)
    return request


def _validate_point_payload(
    payload: Any,
    *,
    point_request: Mapping[str, Any],
    execution: Mapping[str, Any],
    expected_version: str,
) -> tuple[dict[str, Any] | None, list[str], str, dict[str, Any]]:
    """Validate one single-point worker result against the phase-5 contract.

    Returns ``(clean_point, problems, category, error_detail)``.  ``category`` is one of
    ``ok``, ``worker_error`` (the worker reported a bounded error), ``no_payload`` (the process
    produced nothing, timed out or was aborted natively) or ``contract`` (the payload is present but
    violates the single-point contract).
    """
    problems: list[str] = []
    if not isinstance(payload, Mapping) or payload.get("status") != "ok":
        if isinstance(payload, Mapping):
            message = str(payload.get("error_message") or payload.get("error_code")
                          or "隔离计算未返回可用结果。")
            return None, [message], "worker_error", {
                "worker_error": dict(payload),
                "worker_returncode": execution.get("returncode"),
                "native_abort": False,
                "stderr_tail": _sanitize_stderr(execution.get("stderr_tail"), 1200),
            }
        native = _describe_worker_exit(execution.get("returncode"))
        message = str(execution.get("error") or "") or native or (
            f"隔离计算未产出结果文件（returncode={execution.get('returncode')}）。"
        )
        return None, [message], "no_payload", {
            "worker_error": None,
            "worker_returncode": execution.get("returncode"),
            "native_abort": bool(native),
            "stderr_tail": _sanitize_stderr(execution.get("stderr_tail"), 1200),
            "timed_out": bool(execution.get("timed_out")),
        }

    if str(payload.get("pycalphad_version", "")) != expected_version:
        problems.append(
            f"隔离环境报告的 pycalphad 版本 {payload.get('pycalphad_version') or '未知'} "
            f"与登记版本 {expected_version} 不一致。"
        )
    if payload.get("component_profile_id") != (point_request.get("component_profile") or {}).get("profile_id"):
        problems.append("component_profile 与请求不一致。")
    if payload.get("phase_profile_id") != (point_request.get("phase_profile") or {}).get("profile_id"):
        problems.append("phase_profile 与请求不一致。")
    expected_phases = [str(name) for name in point_request.get("phases", []) or []]
    if [str(name) for name in payload.get("phases", []) or []] != expected_phases:
        problems.append("返回的相集合与固定相集合不一致。")
    expected_components = {str(name).upper() for name in point_request.get("components", []) or []}
    reported_components = {str(name).upper() for name in payload.get("components", []) or []}
    if reported_components != expected_components:
        problems.append("返回的组元集合与固定缩减体系不一致。")
    pycalphad_components = {str(name).upper() for name in payload.get("pycalphad_components", []) or []}
    if "VA" not in pycalphad_components:
        problems.append("pycalphad 组元列表缺少空位 VA。")

    points = payload.get("points")
    if not isinstance(points, list) or len(points) != 1:
        problems.append("单点请求必须且只能返回 1 个温度点。")
        return None, problems, "contract", _point_error_detail(execution)
    raw_point = points[0]
    if not isinstance(raw_point, Mapping):
        problems.append("温度点不是对象。")
        return None, problems, "contract", _point_error_detail(execution)
    try:
        temperature_C = float(raw_point["temperature_C"])
    except (KeyError, TypeError, ValueError):
        problems.append("温度点缺少温度。")
        return None, problems, "contract", _point_error_detail(execution)
    expected_C = float((point_request.get("temperature") or {}).get("values_C", [None])[0])
    if abs(temperature_C - expected_C) > 1e-6:
        problems.append(f"返回温度 {temperature_C:g} °C 与请求 {expected_C:g} °C 不一致。")
    fractions = raw_point.get("phase_fractions_mole")
    if not isinstance(fractions, Mapping):
        problems.append("温度点缺少相摩尔分数。")
        return None, problems, "contract", _point_error_detail(execution)
    cleaned = {str(name): float(value) for name, value in fractions.items()}
    composition_sets = sorted(name for name in cleaned if "#" in name)
    if composition_sets:
        problems.append("返回了未聚合的相成分集：" + "、".join(composition_sets) + "。")
    total = sum(cleaned.values())
    if abs(total - 1.0) > 1e-4:
        problems.append(f"相摩尔分数合计为 {total:.8f}，超出容差 1e-4。")
    if problems:
        return None, problems, "contract", _point_error_detail(execution)
    clean = {
        "temperature_C": temperature_C,
        "temperature_K": round(temperature_C + 273.15, 6),
        "phase_fractions_mole": {name: round(value, 10) for name, value in sorted(cleaned.items())},
        "phases_present": sorted(name for name, value in cleaned.items() if value > 0),
        "total_moles": float(raw_point.get("total_moles", total) or total),
        "raw_phase_amounts_mole": dict(raw_point.get("raw_phase_amounts_mole", {}) or {}),
    }
    return clean, [], "ok", {}


def _point_error_detail(execution: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "worker_error": None,
        "worker_returncode": execution.get("returncode"),
        "native_abort": False,
        "stderr_tail": _sanitize_stderr(execution.get("stderr_tail"), 1200),
    }


def run_independent_single_point_curve(
    preview: CalphadPhaseFractionPreview,
    *,
    interpreter: str | None = None,
    runner: Runner | None = None,
    timeout_seconds: float | None = None,
    scratch_root: Path = RUN_SCRATCH_ROOT,
    diagnostic_retry: bool = True,
) -> dict[str, Any]:
    """T86 phase-5 formal path: one fresh worker process per temperature point, strictly serial.

    Every point is a fully independent deterministic request that differs only in temperature.  The
    parent merges only points that succeeded on their **first** attempt and passed the contract
    check; if any point is missing it returns a blocked record with **no partial curve**.  A single
    diagnostic retry may be executed to characterise a failure, but its result is never spliced into
    the formal curve and never turns a failed formal point into a pass.
    """
    if preview.state != "ready" or preview.request is None:
        return _blocked_record(
            preview, code="CALPHAD-DISABLED-001",
            message="预览未就绪，未启动任何独立点进程。",
            status="blocked",
            extra={"state": preview.state, "gates": [gate.to_dict() for gate in preview.gates]},
        )
    resolved_interpreter = interpreter or preview.environment.get("interpreter")
    if not resolved_interpreter:
        return _blocked_record(preview, code="CALPHAD-ENV-001",
                               message="没有可用的隔离解释器路径。")
    if timeout_seconds is None:
        timeout_seconds = 300.0
    worker = runner or _default_worker_runner
    expected_version = str(preview.request.get("pycalphad_version", ""))
    temperatures_C = [float(value) for value in preview.request["temperature"]["values_C"]]
    temperatures_K = [float(value) for value in preview.request["temperature"]["values_K"]]
    digest = str(preview.request.get("request_digest", ""))[:20] or digest_value(preview.request)[:20]
    base_workdir = Path(scratch_root) / f"points-{digest}"
    if base_workdir.exists():
        shutil.rmtree(base_workdir, ignore_errors=True)

    manifest: list[dict[str, Any]] = []
    clean_points: list[dict[str, Any]] = []
    warnings: list[str] = list(preview.warnings)
    failed: list[dict[str, Any]] = []
    reported_version = expected_version
    total_runtime = 0.0

    try:
        for index, (temperature_C, temperature_K) in enumerate(zip(temperatures_C, temperatures_K), start=1):
            point_request = _point_request(preview.request, temperature_C=temperature_C,
                                           temperature_K=temperature_K, index=index,
                                           count=len(temperatures_C))
            attempt_records: list[dict[str, Any]] = []
            first_success = False
            diagnostic_success = False
            first_failure: dict[str, Any] = {}
            clean_point: dict[str, Any] | None = None
            for attempt in range(1 + (DIAGNOSTIC_RETRY_LIMIT if diagnostic_retry else 0)):
                workdir = base_workdir / f"point-{index:03d}" / f"attempt-{attempt + 1}"
                started = time.perf_counter()
                try:
                    execution = worker(point_request, interpreter=str(resolved_interpreter),
                                       workdir=workdir, timeout_seconds=float(timeout_seconds))
                except Exception as exc:  # a broken runner must not take the page down
                    execution = {"returncode": None, "payload": None,
                                 "error": f"{type(exc).__name__}: {exc}"}
                runtime = round(time.perf_counter() - started, 3)
                total_runtime += runtime
                shutil.rmtree(workdir, ignore_errors=True)
                payload = execution.get("payload") if isinstance(execution, Mapping) else None
                clean, problems, category, error_detail = _validate_point_payload(
                    payload, point_request=point_request, execution=execution,
                    expected_version=expected_version,
                )
                reported_version = str((payload or {}).get("pycalphad_version", reported_version)) \
                    if isinstance(payload, Mapping) else reported_version
                pycalphad_components = [
                    str(name) for name in ((payload or {}).get("pycalphad_components", []) or [])
                ] if isinstance(payload, Mapping) else []
                attempt_record = {
                    "attempt": attempt + 1,
                    "diagnostic_only": attempt > 0,
                    "solve_status": "ok" if clean is not None else "failed",
                    "failure_category": category,
                    "problems": problems,
                    "worker_pid": execution.get("pid") if isinstance(execution, Mapping) else None,
                    "worker_returncode": execution.get("returncode") if isinstance(execution, Mapping) else None,
                    "timed_out": bool(execution.get("timed_out")) if isinstance(execution, Mapping) else False,
                    "runtime_s": runtime,
                    "pycalphad_components": pycalphad_components,
                    "stderr_summary": _sanitize_stderr(
                        execution.get("stderr_tail") if isinstance(execution, Mapping) else ""
                    ),
                }
                attempt_records.append(attempt_record)
                if clean is None and not first_failure:
                    # The formal failure is always the FIRST attempt, never a later diagnostic one.
                    first_failure = {"failure_category": category, "problems": problems,
                                     **dict(error_detail)}
                if clean is not None and attempt == 0:
                    first_success = True
                    clean_point = clean
                    break
                if clean is not None and attempt > 0:
                    # A diagnostic retry that succeeds is recorded as evidence only: ``clean_point``
                    # is deliberately left unset so it can never enter the formal curve.
                    diagnostic_success = True
                    break
            base_record = {
                "point_index": index,
                "request_hash": point_request["request_digest"],
                "temperature_C": round(temperature_C, 6),
                "temperature_K": round(temperature_K, 6),
                "components": list(point_request.get("components", [])),
                "phases": list(point_request.get("phases", [])),
                "va_present": "VA" in {
                    str(name).upper() for name in attempt_records[-1].get("pycalphad_components", [])
                },
                "database_sha256": (point_request.get("database") or {}).get("sha256"),
                "solver_mode": INDEPENDENT_SOLVER_MODE,
                "pycalphad_version": expected_version,
                "pressure_Pa": point_request.get("pressure_Pa"),
                "attempts": attempt_records,
                "first_attempt_success": first_success,
                "diagnostic_retry_used": len(attempt_records) > 1,
                "diagnostic_retry_succeeded": diagnostic_success,
            }
            if first_success and clean_point is not None:
                base_record.update({
                    "solve_status": "ok",
                    "worker_pid": attempt_records[0]["worker_pid"],
                    "worker_returncode": attempt_records[0]["worker_returncode"],
                    "runtime_s": attempt_records[0]["runtime_s"],
                    "active_phases": clean_point["phases_present"],
                    "phase_fractions_mole": clean_point["phase_fractions_mole"],
                    "phase_fraction_sum": round(sum(clean_point["phase_fractions_mole"].values()), 10),
                    "stderr_summary": attempt_records[0]["stderr_summary"],
                })
                clean_points.append(clean_point)
            else:
                base_record.update({
                    "solve_status": "failed",
                    "worker_pid": attempt_records[-1]["worker_pid"],
                    "worker_returncode": attempt_records[-1]["worker_returncode"],
                    "runtime_s": attempt_records[-1]["runtime_s"],
                    "active_phases": [],
                    "phase_fractions_mole": {},
                    "phase_fraction_sum": None,
                    "stderr_summary": attempt_records[-1]["stderr_summary"],
                })
                failed.append({
                    "point_index": index,
                    "temperature_C": round(temperature_C, 6),
                    "temperature_K": round(temperature_K, 6),
                    "failure_category": first_failure.get("failure_category"),
                    "problems": first_failure.get("problems") or attempt_records[0]["problems"],
                    "worker_returncode": first_failure.get("worker_returncode",
                                                           attempt_records[0]["worker_returncode"]),
                    "timed_out": bool(first_failure.get("timed_out",
                                                        attempt_records[0]["timed_out"])),
                    "native_abort": bool(first_failure.get("native_abort")),
                    "worker_error": first_failure.get("worker_error"),
                    "stderr_tail": first_failure.get("stderr_tail"),
                    "diagnostic_retry_used": len(attempt_records) > 1,
                    "diagnostic_retry_succeeded": diagnostic_success,
                })
            manifest.append(base_record)
    finally:
        shutil.rmtree(base_workdir, ignore_errors=True)

    manifest_digest = digest_value(manifest)
    phases = sorted({name for point in clean_points for name in point["phase_fractions_mole"]})
    request = preview.request or {}
    extra = {
        "solver_mode": INDEPENDENT_SOLVER_MODE,
        "formal_solver_mode": True,
        "single_point_process": True,
        "no_warm_start": True,
        # T86 portfolio demo flags: carried only for the public synthetic demonstration.
        "portfolio_demo": bool(request.get("portfolio_demo")),
        "public_synthetic_input": bool(request.get("public_synthetic_input")),
        "not_for_scientific_conclusion": bool(request.get("not_for_scientific_conclusion")),
        "demo_policy_id": request.get("demo_policy_id"),
        "demo_id": request.get("demo_id"),
        "demo_label": request.get("demo_label"),
        "point_count_expected": len(temperatures_C),
        "point_count_first_attempt_success": len(clean_points),
        "point_manifest": manifest,
        "manifest_digest": manifest_digest,
        "total_worker_runtime_s": round(total_runtime, 3),
        "pycalphad_components": sorted({
            str(name) for entry in manifest for name in entry.get("components", [])
        } | {"VA"}),
        "elapsed_s": round(total_runtime, 3),
        "worker_environment": {"pycalphad_version": reported_version},
        "diagnostic_retries_enabled": bool(diagnostic_retry),
        "partial_curve_returned": False,
    }
    if failed:
        first = failed[0]
        if first["failure_category"] == "contract":
            code = "CALPHAD-RUN-002"
            message = "；".join(first["problems"])
        else:
            code = "CALPHAD-RUN-001"
            message = "；".join(first["problems"])
        return _blocked_record(
            preview,
            code=code,
            message=(
                f"独立单点模式：{len(failed)}/{len(temperatures_C)} 个温度点未能在首次独立进程调用中成功，"
                f"按规则不输出任何部分正式曲线（首个失败点 {first['temperature_C']:g} °C）：{message}"
            ),
            warnings=warnings,
            extra={**extra, "failed_points": failed},
            extra_error={
                "worker_returncode": first.get("worker_returncode"),
                "native_abort": bool(first.get("native_abort")),
                "timed_out": bool(first.get("timed_out")),
                "stderr_tail": first.get("stderr_tail"),
                "worker_error": first.get("worker_error"),
                "failed_point_count": len(failed),
                "first_failed_temperature_C": first["temperature_C"],
            },
        )
    return _assemble_curve_record(preview, clean_points=clean_points, phases=phases,
                                 warnings=warnings, reported_version=reported_version, extra=extra)


def run_phase_fraction_curve(
    preview: CalphadPhaseFractionPreview,
    *,
    interpreter: str | None = None,
    runner: Runner | None = None,
    timeout_seconds: float | None = None,
    scratch_root: Path = RUN_SCRATCH_ROOT,
    solver_mode: str | None = None,
) -> dict[str, Any]:
    """Dispatch to the formal or the diagnostic solver mode.

    ``solver_mode=None`` uses the formal mode recorded in the fixed reduced-system policy
    (``independent_single_point_process_v1``).  ``batch_workspace_warm_start`` selects the
    diagnostic multi-temperature path and never returns a formal pilot result.
    """
    resolved = solver_mode or FORMAL_SOLVER_MODE
    if resolved == BATCH_SOLVER_MODE:
        return _run_batch_workspace_curve(
            preview, interpreter=interpreter, runner=runner,
            timeout_seconds=timeout_seconds, scratch_root=scratch_root,
        )
    if resolved != INDEPENDENT_SOLVER_MODE:
        return _blocked_record(
            preview, code="CALPHAD-CONFIG-003",
            message=f"未知的 solver_mode：{resolved!r}。只允许 {INDEPENDENT_SOLVER_MODE}"
                    f"（正式）或 {BATCH_SOLVER_MODE}（仅诊断）。",
        )
    return run_independent_single_point_curve(
        preview, interpreter=interpreter, runner=runner,
        timeout_seconds=timeout_seconds, scratch_root=scratch_root,
    )


def _run_batch_workspace_curve(
    preview: CalphadPhaseFractionPreview,
    *,
    interpreter: str | None = None,
    runner: Runner | None = None,
    timeout_seconds: float | None = None,
    scratch_root: Path = RUN_SCRATCH_ROOT,
) -> dict[str, Any]:
    """DIAGNOSTIC-ONLY multi-temperature batch path with pycalphad warm-starting.

    This is the T86 phase-4 path.  It is kept for diagnosis and for the batch-versus-independent
    comparison; it is no longer the formal pilot calculation path.  Nothing is written back to the
    processed research data layer and the scratch directory is removed afterwards.
    """
    if preview.state != "ready" or preview.request is None:
        return {
            "status": "blocked",
            "state": preview.state,
            "gates": [gate.to_dict() for gate in preview.gates],
            "warnings": list(preview.warnings),
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
            "points": [],
            "curve": [],
            "phases": [],
            "writes_back_formal_experimental_data": False,
            "is_complete_phase_diagram": False,
            "reduced_component_system": bool(preview.composition.get("controlled_exclusions")),
            "excluded_elements": sorted(
                {item["element"] for item in preview.composition.get("controlled_exclusions", [])}
            ),
            "controlled_exclusions": list(preview.composition.get("controlled_exclusions", [])),
            "limitation_notice": preview.notice(),
        }

    resolved_interpreter = interpreter or preview.environment.get("interpreter")
    if not resolved_interpreter:
        return {
            "status": "failed",
            "state": "blocked",
            "error": {"code": "CALPHAD-ENV-001", "message": "没有可用的隔离解释器路径。"},
            "warnings": list(preview.warnings),
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
            "points": [],
            "curve": [],
            "phases": [],
            "writes_back_formal_experimental_data": False,
            "is_complete_phase_diagram": False,
            "limitation_notice": preview.notice(),
            "reduced_component_system": bool(preview.request.get("reduced_component_system")),
            "excluded_elements": sorted(
                {item["element"] for item in preview.request.get("controlled_exclusions", [])}
            ),
            "controlled_exclusions": list(preview.request.get("controlled_exclusions", [])),
        }

    if timeout_seconds is None:
        timeout_seconds = 900.0
    worker = runner or _default_worker_runner
    digest = str(preview.request.get("request_digest", ""))[:20] or digest_value(preview.request)[:20]
    workdir = Path(scratch_root) / f"run-{digest}"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)

    try:
        execution = worker(
            preview.request,
            interpreter=str(resolved_interpreter),
            workdir=workdir,
            timeout_seconds=float(timeout_seconds),
        )
    except Exception as exc:  # a broken runner must not take the page down
        execution = {"returncode": None, "payload": None, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    payload = execution.get("payload") if isinstance(execution, Mapping) else None
    execution_error = str(execution.get("error", "") or "") if isinstance(execution, Mapping) else ""

    if not isinstance(payload, Mapping) or payload.get("status") != "ok":
        message = execution_error
        if not message and isinstance(payload, Mapping):
            message = str(payload.get("error_message") or payload.get("error_code") or "隔离计算未返回可用结果。")
        native_explanation = None
        if not message and isinstance(execution, Mapping):
            native_explanation = _describe_worker_exit(execution.get("returncode"))
        if not message and native_explanation:
            message = native_explanation
        if not message:
            message = f"隔离计算未产出结果文件（returncode={execution.get('returncode') if isinstance(execution, Mapping) else 'n/a'}）。"
        return {
            "status": "failed",
            "state": "blocked",
            "error": {
                "code": "CALPHAD-RUN-001",
                "message": message,
                "worker_returncode": execution.get("returncode") if isinstance(execution, Mapping) else None,
                "native_abort": bool(native_explanation),
                "stderr_tail": str(execution.get("stderr_tail", ""))[:1200] if isinstance(execution, Mapping) else "",
                "worker_error": dict(payload) if isinstance(payload, Mapping) and payload.get("status") != "ok" else None,
            },
            "warnings": list(preview.warnings),
            "points": [],
            "curve": [],
            "phases": [],
            "request": preview.request,
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
            "writes_back_formal_experimental_data": False,
            "is_complete_phase_diagram": False,
            "limitation_notice": preview.notice(),
            "reduced_component_system": bool(preview.request.get("reduced_component_system")),
            "excluded_elements": sorted(
                {item["element"] for item in preview.request.get("controlled_exclusions", [])}
            ),
            "controlled_exclusions": list(preview.request.get("controlled_exclusions", [])),
        }

    expected_version = str(preview.request.get("pycalphad_version", ""))
    reported_version = str(payload.get("pycalphad_version", ""))
    validation_problems: list[str] = []
    if reported_version != expected_version:
        validation_problems.append(
            f"隔离环境报告的 pycalphad 版本 {reported_version or '未知'} 与登记版本 {expected_version} 不一致。"
        )

    expected_phases = [str(name) for name in preview.request.get("phases", []) or []]
    reported_phases = [str(name) for name in payload.get("phases", []) or []]
    if expected_phases and reported_phases != expected_phases:
        validation_problems.append(
            "隔离计算使用的相集合与固定相集合不一致：请求 " + "、".join(expected_phases)
            + "；返回 " + ("、".join(reported_phases) or "（空）") + "。"
        )
    expected_component_profile = (preview.request.get("component_profile") or {}).get("profile_id")
    if payload.get("component_profile_id") != expected_component_profile:
        validation_problems.append("隔离计算报告的 component_profile 与请求不一致。")
    expected_phase_profile = (preview.request.get("phase_profile") or {}).get("profile_id")
    if payload.get("phase_profile_id") != expected_phase_profile:
        validation_problems.append("隔离计算报告的 phase_profile 与请求不一致。")
    reported_components = {str(name).upper() for name in payload.get("components", []) or []}
    expected_components = {str(name).upper() for name in preview.request.get("components", []) or []}
    if reported_components and reported_components != expected_components:
        validation_problems.append("隔离计算报告的组元集合与固定缩减体系不一致。")

    if isinstance(payload, Mapping) and bool(payload.get("portfolio_demo")) \
            != bool(preview.request.get("portfolio_demo")):
        validation_problems.append("隔离计算返回的演示标记与请求不一致。")

    expected_temperatures = [float(value) for value in preview.request["temperature"]["values_C"]]
    points = payload.get("points")
    if not isinstance(points, list) or len(points) != len(expected_temperatures):
        validation_problems.append("隔离计算返回的温度点数与请求不一致。")
        points = []
    warnings = list(preview.warnings) + [str(item) for item in payload.get("warnings", []) or []]

    clean_points: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            validation_problems.append(f"第 {index + 1} 个温度点不是对象。")
            continue
        try:
            temperature_C = float(point["temperature_C"])
        except (KeyError, TypeError, ValueError):
            validation_problems.append(f"第 {index + 1} 个温度点缺少温度。")
            continue
        if abs(temperature_C - expected_temperatures[index]) > 1e-6:
            validation_problems.append(f"第 {index + 1} 个温度点温度与请求不一致。")
            continue
        fractions = point.get("phase_fractions_mole")
        if not isinstance(fractions, Mapping):
            validation_problems.append(f"{temperature_C:g} °C 缺少相摩尔分数。")
            continue
        cleaned = {str(name): float(value) for name, value in fractions.items()}
        composition_sets = sorted(name for name in cleaned if "#" in name)
        if composition_sets:
            validation_problems.append(
                f"{temperature_C:g} °C 返回了未聚合的相成分集：{'、'.join(composition_sets)}。"
            )
            continue
        total = sum(cleaned.values())
        if cleaned and abs(total - 1.0) > 1e-6:
            validation_problems.append(f"{temperature_C:g} °C 的相摩尔分数合计为 {total:.6f}，不等于 1。")
            warnings.append(f"{temperature_C:g} °C 的相摩尔分数合计为 {total:.6f}（未归一化）。")
        clean_points.append({
            "temperature_C": temperature_C,
            "temperature_K": round(temperature_C + 273.15, 6),
            "phase_fractions_mole": {name: round(value, 10) for name, value in sorted(cleaned.items())},
            "phases_present": sorted(name for name, value in cleaned.items() if value > 0),
            "total_moles": float(point.get("total_moles", 1.0) or 0.0),
            "raw_phase_amounts_mole": dict(point.get("raw_phase_amounts_mole", {}) or {}),
        })

    if validation_problems:
        return {
            "status": "failed",
            "state": "blocked",
            "error": {"code": "CALPHAD-RUN-002", "message": "；".join(validation_problems)},
            "warnings": warnings,
            "points": [],
            "curve": [],
            "phases": [],
            "request": preview.request,
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
            "writes_back_formal_experimental_data": False,
            "is_complete_phase_diagram": False,
            "limitation_notice": preview.notice(),
            "reduced_component_system": bool(preview.request.get("reduced_component_system")),
            "excluded_elements": sorted(
                {item["element"] for item in preview.request.get("controlled_exclusions", [])}
            ),
            "controlled_exclusions": list(preview.request.get("controlled_exclusions", [])),
        }

    phases = sorted({name for point in clean_points for name in point["phase_fractions_mole"]})
    extra = {
        "solver_mode": BATCH_SOLVER_MODE,
        "formal_solver_mode": False,
        "batch_warm_start_diagnostic_only": True,
        "pycalphad_components": list(payload.get("pycalphad_components", []) or []),
        "non_converged_retried_temperatures_C": list(
            payload.get("non_converged_retried_temperatures_C", []) or []
        ),
        "non_converged_failed_temperatures_C": list(
            payload.get("non_converged_failed_temperatures_C", []) or []
        ),
        "retry_method": payload.get("retry_method"),
        "elapsed_s": float(payload.get("elapsed_s", 0.0) or 0.0),
        "worker_environment": {
            "python_version": payload.get("python_version"),
            "pycalphad_version": reported_version,
        },
    }
    return _assemble_curve_record(preview, clean_points=clean_points, phases=phases,
                                 warnings=warnings, reported_version=reported_version, extra=extra)


def _assemble_curve_record(
    preview: CalphadPhaseFractionPreview,
    *,
    clean_points: list[dict[str, Any]],
    phases: list[str],
    warnings: list[str],
    reported_version: str,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the labelled result record shared by the formal and the diagnostic solver modes."""
    request = preview.request or {}
    curve = [
        {"temperature_C": point["temperature_C"], "phase": name,
         "mole_fraction": point["phase_fractions_mole"].get(name, 0.0)}
        for point in clean_points
        for name in phases
    ]
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "adapter_version": ADAPTER_VERSION,
        "status": "computed",
        "state": "needs_human_review",
        "feature": "calphad_phase_fraction",
        "sample_id": preview.sample_id,
        "pycalphad_version": reported_version,
        "database": dict(request.get("database", {})),
        "units": dict(request.get("units", {})),
        "output_phase_fraction_basis": request.get("output_phase_fraction_basis"),
        "output_phase_fraction_basis_note": request.get("output_phase_fraction_basis_note"),
        "composition_basis": dict(request.get("composition_basis", {})),
        "components": list(request.get("components", [])),
        "component_mole_fractions": dict(request.get("component_mole_fractions", {})),
        "temperature": dict(request.get("temperature", {})),
        "pressure_Pa": request.get("pressure_Pa"),
        "model_input_digest": request.get("request_digest"),
        "points": clean_points,
        "curve": curve,
        "phases": phases,
        "warnings": warnings,
        "gates": [],
        "result_type": RESULT_TYPE,
        "review_status": REVIEW_STATUS,
        "is_complete_phase_diagram": False,
        "curve_label": CURVE_LABEL,
        # T86 phase-4 item 4: the required result naming and every restriction travel with the record.
        "result_label": RESULT_LABEL_MATRIX,
        "prohibited_result_labels": list(PROHIBITED_RESULT_LABELS),
        "writes_back_formal_experimental_data": False,
        "formal_data_write": False,
        # T86 phase-2 item 4: the limitation travels with every export.
        "reduced_component_system": True,
        "component_profile": dict(request.get("component_profile", {})),
        "phase_profile": dict(request.get("phase_profile", {})),
        "included_elements": list(request.get("components", [])),
        "not_computed_in_this_phase": list(request.get("phase_profile", {}).get("not_computed", [])),
        "prohibited_interpretations": list(request.get("phase_profile", {}).get("not_computed", [])),
        "model_losses": dict(request.get("model_losses", {})),
        "component_versions_and_hashes": dict(request.get("component_versions_and_hashes", {})),
        "reduced_system_approval": dict(request.get("reduced_system_approval", {})),
        "excluded_elements": sorted(
            {item["element"] for item in request.get("controlled_exclusions", [])}
        ),
        "excluded_elements_with_reasons": [
            {"element": item["element"], "category": item["category"],
             "value_status": item.get("value_status"), "value_wt_pct": item.get("value_wt_pct")}
            for item in request.get("controlled_exclusions", [])
        ],
        "controlled_exclusions": list(request.get("controlled_exclusions", [])),
        "controlled_exclusions_confirmed_by": request.get("controlled_exclusions_confirmed_by"),
        "exclusion_policy": dict(request.get("exclusion_policy", {})),
        "limitation_notice": dict(request.get("limitation_notice", {})),
        "database_compatibility": dict(request.get("database_compatibility", {})),
    }
    record.update(dict(extra))
    record["result_digest"] = digest_value(
        {key: value for key, value in record.items() if key != "result_digest"}
    )
    return record


def phase_fraction_csv(record: Mapping[str, Any]) -> str:
    """CSV export that carries the limitation in a preamble *and* on every data row."""
    import csv
    import io

    notice = record.get("limitation_notice", {}) or {}
    database = record.get("database", {}) or {}
    rows = phase_fraction_rows(record)
    phases = list(record.get("phases", []) or [])
    notice_zh = str(notice.get("zh") or DEFAULT_LIMITATION_NOTICE_ZH)
    notice_en = str(notice.get("en") or DEFAULT_LIMITATION_NOTICE_EN)
    excluded = ";".join(str(item) for item in record.get("excluded_elements", []) or [])
    component_profile = record.get("component_profile", {}) or {}
    phase_profile = record.get("phase_profile", {}) or {}
    approval = record.get("reduced_system_approval", {}) or {}
    versions = record.get("component_versions_and_hashes", {}) or {}
    excluded_with_reasons = ";".join(
        f"{item.get('element')}={item.get('category')}"
        for item in record.get("excluded_elements_with_reasons", []) or []
    )

    preamble = [
        "# " + RESULT_LABEL_MATRIX,
        "# CALPHAD 相分数—温度模型预测（12 组元缩减体系；不是完整相图）",
        f"# limitation_notice_zh: {notice_zh}",
        f"# limitation_notice_en: {notice_en}",
        f"# result_label: {record.get('result_label', RESULT_LABEL_MATRIX)}",
        f"# component_profile: {component_profile.get('profile_id', '')} v{component_profile.get('version', '')}",
        f"# phase_profile: {phase_profile.get('profile_id', '')} v{phase_profile.get('version', '')}",
        f"# solver_mode: {record.get('solver_mode', '')}",
        f"# formal_solver_mode: {str(bool(record.get('formal_solver_mode'))).lower()}",
        f"# phase_profile_phases: {';'.join(phase_profile.get('phases', []) or [])}",
        f"# result_type: {record.get('result_type', RESULT_TYPE)}",
        f"# review_status: {record.get('review_status', REVIEW_STATUS)}",
        f"# reduced_component_system: {str(bool(record.get('reduced_component_system'))).lower()}",
        f"# included_elements: {';'.join(str(item) for item in record.get('included_elements', []) or [])}",
        f"# excluded_elements: {excluded}",
        f"# excluded_elements_and_reasons: {excluded_with_reasons}",
        f"# not_computed_in_this_phase: {';'.join(record.get('not_computed_in_this_phase', []) or [])}",
        f"# model_losses: {json.dumps(record.get('model_losses', {}), ensure_ascii=False)}",
        f"# reviewer_id: {approval.get('reviewer_id', '')}",
        f"# approved_at: {approval.get('approved_at', '')}",
        f"# approval_reason: {approval.get('approval_reason', '')}",
        f"# is_complete_phase_diagram: false",
        f"# writes_back_formal_experimental_data: false",
        f"# database_id: {database.get('database_id', '')}",
        f"# database_sha256: {database.get('sha256', '')}",
        f"# community_derivative_commit: {versions.get('community_derivative_commit', '')}",
        f"# pycalphad_version: {record.get('pycalphad_version', '')}",
        f"# sample_id: {record.get('sample_id', '')}",
        f"# result_digest: {record.get('result_digest', '')}",
    ]
    if record.get("portfolio_demo"):
        preamble.extend([
            "# portfolio_demo: true",
            "# public_synthetic_input: true",
            f"# demo_id: {record.get('demo_id', '')}",
            f"# demo_policy_id: {record.get('demo_policy_id', '')}",
            "# not_for_scientific_conclusion: true",
            "# model_prediction_not_experimental_measurement: true",
            "# not_for: 论文结论;真实钢种分析;生产决策;材料结论",
        ])
    buffer = io.StringIO()
    fieldnames = ["温度 (°C)"] + [f"{phase}（相摩尔分数）" for phase in phases] + [
        "出现的相",
        "limitation_notice_zh",
        "result_label",
        "component_profile",
        "phase_profile",
        "solver_mode",
        "reduced_component_system",
        "included_elements",
        "excluded_elements",
        "excluded_elements_and_reasons",
        "not_computed_in_this_phase",
        "review_status",
        "writes_back_formal_experimental_data",
        "database_sha256",
    ]
    if record.get("portfolio_demo"):
        fieldnames.extend(["portfolio_demo", "public_synthetic_input",
                           "not_for_scientific_conclusion", "demo_id"])
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        values = {
            **row,
            "limitation_notice_zh": notice_zh,
            "result_label": record.get("result_label", RESULT_LABEL_MATRIX),
            "component_profile": f"{component_profile.get('profile_id', '')} v{component_profile.get('version', '')}",
            "phase_profile": f"{phase_profile.get('profile_id', '')} v{phase_profile.get('version', '')}",
            "solver_mode": record.get("solver_mode", ""),
            "reduced_component_system": str(bool(record.get("reduced_component_system"))).lower(),
            "included_elements": ";".join(str(item) for item in record.get("included_elements", []) or []),
            "excluded_elements": excluded,
            "excluded_elements_and_reasons": excluded_with_reasons,
            "not_computed_in_this_phase": ";".join(record.get("not_computed_in_this_phase", []) or []),
            "review_status": record.get("review_status", REVIEW_STATUS),
            "writes_back_formal_experimental_data": str(
                bool(record.get("writes_back_formal_experimental_data"))).lower(),
            "database_sha256": str(database.get("sha256", "")),
        }
        if record.get("portfolio_demo"):
            values.update({
                "portfolio_demo": "true",
                "public_synthetic_input": "true",
                "not_for_scientific_conclusion": "true",
                "demo_id": str(record.get("demo_id", "")),
            })
        writer.writerow(values)
    return "\n".join(preamble) + "\n" + buffer.getvalue()


def phase_fraction_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a computed record into one row per temperature for display."""
    rows: list[dict[str, Any]] = []
    phases = list(record.get("phases", []) or [])
    for point in record.get("points", []) or []:
        fractions = point.get("phase_fractions_mole", {}) or {}
        row: dict[str, Any] = {"温度 (°C)": point.get("temperature_C")}
        for phase in phases:
            row[f"{phase}（相摩尔分数）"] = fractions.get(phase, 0.0)
        row["出现的相"] = "、".join(point.get("phases_present", []) or [])
        rows.append(row)
    return rows


def phase_fraction_curve_markdown(record: Mapping[str, Any]) -> str:
    """Render a traceable model record for download. Never claims a phase diagram."""
    if record.get("status") != "computed":
        return (
            f"# CALPHAD 相分数计算未完成\n\n状态：`{record.get('status')}`\n\n"
            + "\n".join(f"- {item}" for item in record.get("warnings", []) or [])
            + "\n"
        )
    database = record.get("database", {}) or {}
    composition = record.get("composition_basis", {}) or {}
    notice = record.get("limitation_notice", {}) or {}
    component_profile = record.get("component_profile", {}) or {}
    phase_profile = record.get("phase_profile", {}) or {}
    approval = record.get("reduced_system_approval", {}) or {}
    lines = [
        "# " + RESULT_LABEL_MATRIX,
        "",
        "# CALPHAD 平衡相分数—温度计算记录（模型预测）",
        "",
    ]
    if record.get("portfolio_demo"):
        lines.extend([
            "> **公开合成演示（作品集用）**",
            ">",
            "> `portfolio_demo=true`、`public_synthetic_input=true`、"
            "`not_for_scientific_conclusion=true`、"
            "`model_prediction_not_experimental_measurement`",
            ">",
            "> 本演示使用公开合成成分，不读取任何私人实验数据；"
            "**不得用于论文结论、真实钢种分析或生产决策**。",
            f"> demo_id：`{record.get('demo_id')}`；政策：`{record.get('demo_policy_id')}`",
            "",
        ])
    lines.extend([
        "> **限制声明（必须随结果一同引用）**",
        ">",
        "> " + str(notice.get("zh") or DEFAULT_LIMITATION_NOTICE_ZH),
        ">",
        "> " + str(notice.get("en") or DEFAULT_LIMITATION_NOTICE_EN),
        "",
        f"- 样品：`{record.get('sample_id') or '未指定'}`",
        f"- 结果类型：`{record.get('result_type')}`",
        f"- 复核状态：`{record.get('review_status')}`",
        f"- 成分体系：`{component_profile.get('profile_id')} v{component_profile.get('version')}`"
        f"（纳入元素 {component_profile.get('included_element_count')} 个，组元条目 {component_profile.get('component_list_length')} 个）",
        f"- 相集合：`{phase_profile.get('profile_id')} v{phase_profile.get('version')}`"
        f"（{'、'.join(phase_profile.get('phases', []) or [])}）",
        f"- 求解模式：`{record.get('solver_mode')}`"
        f"（正式路径 `{INDEPENDENT_SOLVER_MODE}`；`{BATCH_SOLVER_MODE}` 仅用于诊断）",
        f"- 独立点清单摘要：`{record.get('manifest_digest') or '不适用'}`"
        f"（{record.get('point_count_first_attempt_success')}/{record.get('point_count_expected')} 个点首次成功）",
        f"- 缩减成分体系：`{record.get('reduced_component_system')}`；被排除元素：`{record.get('excluded_elements')}`",
        f"- 受控排除确认人：`{record.get('controlled_exclusions_confirmed_by') or '不适用'}`",
        f"- 曲线性质：`{record.get('curve_label')}`；**不是完整相图**",
        "- 输入成分单位：`wt.%`；温度单位：`°C`；压力：`" + f"{record.get('pressure_Pa')}" + " Pa`",
        f"- 输出基准：各相摩尔分数（`mole_fraction_of_phase`）——{record.get('output_phase_fraction_basis_note')}",
        f"- 模型输入摘要：`{record.get('model_input_digest')}`",
        f"- 结果摘要：`{record.get('result_digest')}`",
        f"- 未写回正式实验数据：`{record.get('writes_back_formal_experimental_data')}`",
        "",
        "## 具名批准（真实样品运行前置条件）",
        "",
        f"- 批准人 `reviewer_id`：`{approval.get('reviewer_id') or '未填写'}`",
        f"- 批准时间：`{approval.get('approved_at') or '未填写'}`",
        f"- 批准理由：{approval.get('approval_reason') or '未填写'}",
        f"- 缩减体系版本：`{approval.get('component_profile_id')} v{approval.get('component_profile_version')}`",
        f"- 相集合版本：`{approval.get('phase_profile_id')} v{approval.get('phase_profile_version')}`",
        f"- 排除元素列表：`{'、'.join(approval.get('excluded_elements', []) or [])}`",
        f"- 数据库：`{approval.get('database_id')}`（{approval.get('database_version_or_date')}，SHA-256 `{approval.get('database_sha256')}`）",
        f"- 确认文本已勾选：`{approval.get('acknowledged')}`",
        "",
        "## 本阶段明确不计算的内容（禁止据此推断）",
        "",
    ])
    for item in record.get("not_computed_in_this_phase", []) or []:
        lines.append(f"- {item}")
    lines.extend([
        "",
        f"- 禁止使用的名称：`{'、'.join(record.get('prohibited_result_labels', []) or [])}`",
        f"- 已知模型损失：`{json.dumps(record.get('model_losses', {}), ensure_ascii=False)}`",
        "",
        "## 受控元素排除（政策版本化、逐次运行记录）",
        "",
        "| 元素 | 类别 | 原始状态 | 原始值 (wt.%) | 数据库 | 数据库 SHA-256 |",
        "| --- | --- | --- | ---: | --- | --- |",
    ])
    for item in record.get("controlled_exclusions", []) or []:
        value = item.get("value_wt_pct")
        lines.append(
            f"| {item.get('element')} | `{item.get('category')}` | {item.get('value_status')} | "
            f"{'' if value is None else f'{float(value):.5f}'} | `{database.get('database_id')}` | "
            f"`{str(database.get('sha256', ''))[:16]}…` |"
        )
    if not record.get("controlled_exclusions"):
        lines.append("| — | — | — | — | — | — |")
    lines.extend([
        "",
        f"- 排除政策：`{json.dumps(record.get('exclusion_policy', {}), ensure_ascii=False)}`",
        "- 排除类别含义：`database_not_covered`（数据库未建模）、`measured_zero`（实测为 0）、"
        "`input_unknown`（仅有字段声明、无测量值，未按 0 处理）、"
        "`capacity_reduction`（有实测非零值且数据库覆盖，但为满足求解器容量上限由固定缩减体系政策排除）。",
        "- 对结果适用性的影响：结果只能描述上述被排除元素之外、且被数据库覆盖的组元体系；"
        "禁止用本结果判断被排除元素对偏聚、夹杂、晶界脆化、相稳定性或性能的影响。",
        "",
        "## 计算组件（由 wt.% 换算为摩尔分数后输入模型）",
        "",
        "| 元素 | 模型输入摩尔分数 |",
        "| --- | ---: |",
    ])
    for element, value in (record.get("component_mole_fractions", {}) or {}).items():
        lines.append(f"| {element} | {float(value):.8f} |")
    if "Fe" not in (record.get("component_mole_fractions", {}) or {}):
        lines.append("| Fe | 余量（依赖组元） |")
    lines.extend([
        "",
        "## 成分基准",
        "",
        f"- 已提供 wt.%：`{json.dumps(composition.get('provided_wt_pct', {}), ensure_ascii=False)}`",
        f"- Fe 来源：`{composition.get('fe_source')}`；Fe 余量：`{composition.get('fe_balance_wt_pct')}` wt.%",
        f"- Fe 余量确认人：`{composition.get('fe_balance_confirmed_by') or '不适用'}`",
        f"- 无值元素：`{composition.get('unprovided_elements')}`",
        f"- 无值元素排除声明人：`{composition.get('unprovided_elements_exclusion_declared_by') or '不适用'}`",
        f"- 排除项（含原因）：`{json.dumps(composition.get('excluded_elements', {}), ensure_ascii=False)}`",
        f"- 原子量来源：{composition.get('atomic_weights_source')}；状态：`{composition.get('atomic_weights_source_status')}`",
        "",
        "## 数据库来源与哈希",
        "",
        f"- database_id：`{database.get('database_id')}`",
        f"- 路径：`{database.get('path')}`",
        f"- SHA-256：`{database.get('sha256')}`",
        f"- 提供方/版本：{database.get('provider')} / {database.get('version_or_date')}",
        f"- 授权依据：{database.get('license_or_authorization')}（{database.get('authorization_status')}，{database.get('authorized_by')}）",
        f"- 引用：{database.get('citation')}",
        f"- pycalphad：`{record.get('pycalphad_version')}`",
        "",
        "## 相分数—温度数据",
        "",
        "| 温度 (°C) | " + " | ".join(record.get("phases", []) or []) + " |",
        "| ---: | " + " | ".join("---:" for _ in record.get("phases", []) or []) + " |",
    ])
    for point in record.get("points", []) or []:
        fractions = point.get("phase_fractions_mole", {}) or {}
        cells = " | ".join(f"{float(fractions.get(phase, 0.0)):.6f}" for phase in record.get("phases", []) or [])
        lines.append(f"| {float(point.get('temperature_C', 0.0)):.1f} | {cells} |")
    lines.extend([
        "",
        "## 边界声明",
        "",
        "- 本结果是热力学模型的预测值，不是实验测量值，也不是实验真值。",
        "- 当前状态为待人工复核（`pending_human_review`），未经具名人工复核不得当作结论。",
        "- 这是固定成分、固定压力下的相分数—温度截面曲线，不是完整相图。",
        "- 相分数基准为各相摩尔分数；未做质量分数换算。",
        "- 结果不得写回 `data/processed` 正式实验数据层；须经具名人工复核后才能用于进一步分析。",
        "- TDB 的适用范围、覆盖元素与外推区间以登记记录为准。",
    ])
    if record.get("warnings"):
        lines.extend(["", "## 警告", ""])
        lines.extend(f"- {item}" for item in record["warnings"])
    return "\n".join(lines).strip() + "\n"


def calphad_feature_status(
    *,
    config: Mapping[str, Any] | None = None,
    config_path: Path = CONFIG_PATH,
    registry_path: Path | None = None,
    project_root: Path = ROOT,
    environment: Mapping[str, Any] | None = None,
    tier: str = "physics",
) -> dict[str, Any]:
    """Compact, never-raising status used by the Physics tab and the model registry."""
    try:
        return _build_calphad_feature_status(
            config=config,
            config_path=config_path,
            registry_path=registry_path,
            project_root=project_root,
            environment=environment,
            tier=tier,
        )
    except Exception as exc:  # the optional feature must never break a page render
        return {
            "feature": "calphad_phase_fraction",
            "state": "blocked",
            "enabled": False,
            "headline": f"CALPHAD 状态不可用：{type(exc).__name__}",
            "blocking": [{"code": "CALPHAD-STATUS-001", "message": f"{type(exc).__name__}: {exc}"}],
            "component": {},
            "database": {"status": "unknown"},
            "environment": {"status": "unknown"},
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
        }


def _build_calphad_feature_status(
    *,
    config: Mapping[str, Any] | None = None,
    config_path: Path = CONFIG_PATH,
    registry_path: Path | None = None,
    project_root: Path = ROOT,
    environment: Mapping[str, Any] | None = None,
    tier: str = "physics",
) -> dict[str, Any]:
    try:
        resolved = dict(config) if config is not None else load_adapter_config(config_path)
    except (OSError, ValueError) as exc:
        return {
            "feature": "calphad_phase_fraction",
            "state": "blocked",
            "enabled": False,
            "headline": f"CALPHAD 登记无法读取：{exc}",
            "blocking": [{"code": "CALPHAD-CONFIG-001", "message": str(exc)}],
            "component": {},
            "database": {"status": "unknown"},
            "environment": {"status": "unknown"},
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
        }

    component = resolved.get("component", {})
    disabled_reason = feature_disabled_reason(resolved)
    if disabled_reason:
        return {
            "feature": "calphad_phase_fraction",
            "state": "disabled",
            "enabled": False,
            "headline": f"本功能已关闭（{disabled_reason}）；经验公式物理计算照常可用。",
            "blocking": [{"code": "CALPHAD-DISABLED-001", "message": disabled_reason}],
            "component": _component_summary(component),
            "database": {"status": "not_checked"},
            "environment": {"status": "disabled"},
            "result_type": RESULT_TYPE,
            "review_status": REVIEW_STATUS,
        }

    if environment is None:
        environment = probe_isolated_environment(
            interpreter_configuration(resolved, project_root),
            str(component.get("version", "")),
            resolved,
        )
    else:
        environment = dict(environment)

    registry = load_tdb_registry(registry_path, resolved, project_root)
    databases = list(registry.get("databases", []))
    blocking: list[dict[str, str]] = []
    database_summary: dict[str, Any] = {
        "status": registry.get("status"),
        "registry_path": registry.get("path"),
        "registered_count": len(databases),
        "database_ids": [str(item.get("database_id")) for item in databases if item.get("database_id")],
        "detail": registry.get("detail", ""),
    }
    if environment.get("status") != "ready":
        blocking.append({
            "code": "CALPHAD-ENV",
            "message": f"隔离环境：{environment.get('detail', environment.get('status'))}",
        })
    if registry.get("status") != "loaded" or not databases:
        blocking.append({
            "code": "CALPHAD-TDB-000",
            "message": "尚未登记授权 TDB。",
        })
    else:
        validated = validate_tdb_registration(
            select_database(databases) or {},
            project_root=project_root,
            pinned_version=str(component.get("version", "")),
        )
        database_summary.update({
            "status": "passed" if validated["status"] == "passed" else "failed",
            "database_id": validated["database_id"],
            "sha256": validated["sha256"],
            "covered_elements": validated["covered_elements"],
            "problems": validated["problems"],
            "compatibility": validated.get("compatibility", {}),
        })
        if validated["status"] != "passed":
            blocking.append({
                "code": "CALPHAD-TDB-001",
                "message": "TDB 登记未通过校验：" + "；".join(validated["problems"]),
            })
        compatibility = validated.get("compatibility", {}) or {}
        if compatibility.get("status") != COMPATIBILITY_PASSED:
            blocking.append({
                "code": "CALPHAD-TDB-007",
                "message": "TDB 未通过与 pycalphad 固定版本的兼容性门禁（记录状态："
                           f"{compatibility.get('status', 'missing')}）："
                           + str(compatibility.get("blocked_reason") or "未记录原因"),
            })

    state = "ready" if not blocking else "blocked"
    if state == "ready":
        headline = (
            f"隔离环境与授权 TDB 已就绪（pycalphad {environment.get('pycalphad_version')}，"
            f"database_id={database_summary.get('database_id')}）；计算结果仍为待人工复核的模型预测。"
        )
    else:
        headline = "本功能当前不可用（不影响既有物理计算）：" + "；".join(item["message"] for item in blocking)
    acceptance = owner_acceptance_status()
    return {
        "feature": "calphad_phase_fraction",
        "state": state,
        "enabled": True,
        "headline": headline,
        "blocking": blocking,
        "component": _component_summary(component),
        "database": database_summary,
        "environment": environment,
        "result_type": RESULT_TYPE,
        "review_status": REVIEW_STATUS,
        "tier": tier,
        "status_split": {
            "portfolio": acceptance["portfolio"],
            "scientific": acceptance["scientific"],
            "portfolio_signed": acceptance["portfolio_signed"],
            "responsible_person_id": acceptance["responsible_person_id"],
            "signed_at": acceptance["signed_at"],
            "timezone": acceptance["timezone"],
            "decision_scope": acceptance["decision_scope"],
            "scientific_use_approved": False,
            "real_sample_curves_published": False,
            "materials_conclusion_approved": False,
        },
        "portfolio_demo_available": True,
    }


def _component_summary(component: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": component.get("name"),
        "version": component.get("version"),
        "version_pin_status": component.get("version_pin_status"),
        "license_spdx": component.get("license_spdx"),
        "official_repo": component.get("official_repo"),
        "release_url": component.get("release_url"),
        "source_ref": component.get("source_ref"),
        "wheel_sha256_cp312_win_amd64": (component.get("artifacts", {}) or {}).get("cp312_win_amd64", {}).get("sha256"),
        "required_by_core": False,
    }


def status_row() -> dict[str, Any]:
    """One-line status for the model registry table."""
    status = calphad_feature_status()
    environment = status.get("environment", {})
    blocking = list(status.get("blocking", []) or [])
    key = str(environment.get("status", "unknown"))
    environment_labels = {
        "not_configured": "isolated_install_pending",
        "interpreter_missing": "isolated_environment_missing",
        "probe_failed": "isolated_environment_probe_failed",
        "dependency_missing": "isolated_install_pending",
        "version_mismatch": "isolated_version_mismatch",
        "ready": "isolated_environment_ready",
    }
    if status["state"] == "disabled":
        local_status = "feature_disabled"
    elif status["state"] == "ready":
        local_status = "isolated_environment_and_database_ready_pending_human_review"
    elif blocking:
        # Report the first blocking reason so a compatibility block is not masked by a ready environment.
        local_status = "blocked_" + re.sub(r"[^A-Za-z0-9]+", "_", str(blocking[0].get("code", "unknown"))).strip("_")
    else:
        local_status = environment_labels.get(key, f"blocked_{key}")
    return {
        "state": status["state"],
        "local_status": local_status,
        "headline": status["headline"],
        "blocking_codes": [str(item.get("code")) for item in blocking],
        "has_authorized_database": bool(status.get("database", {}).get("registered_count")),
    }
