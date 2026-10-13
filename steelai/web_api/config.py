"""WO-31 §3 — 可信根与工具解释器的服务端解析。

客户端永远不会提交路径、解释器或 URL；它们全部在这里解析：

1. 环境变量（部署/测试覆盖用）；
2. ``config/settings.toml`` 的 ``[tools]`` / ``[sources]`` / ``[research_web]`` 表（被 Git 忽略）；
3. 由仓库自身位置推导出的相对位置。

**本文件不写任何本机盘符**（对应工单 §2「公开样例无本机盘符/秘密，工具路径仅忽略可信配置」）：
可推导的根一律由 ``steelai.paths.ROOT`` 相对计算，机器专用解释器只在被忽略的
``config/settings.toml`` 里登记；没登记就如实报"未配置"，不猜、不硬编码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from steelai.paths import ROOT

# --------------------------------------------------------------------------- #
# 仓库相对锚点（无盘符、无用户名）
# --------------------------------------------------------------------------- #
# ROOT = <workbench>/   →   _ENGINEERING = <workbench>/..   →   _WORKSPACE = ../..
_ENGINEERING = ROOT.parent
_WORKSPACE = ROOT.parent.parent
# 共享工具应用/模型/数据库容器（与工程区同级）。
_TOOLS = _WORKSPACE / "06_Tools"


def _settings() -> dict:
    try:
        from steelai.settings import load_settings

        return load_settings()
    except Exception:  # pragma: no cover - a missing/malformed config must not crash the API
        return {}


def _text(section: dict, key: str, env: str) -> str:
    """Environment first, then the ignored settings file. Never a literal path."""
    value = str(os.environ.get(env, "") or "").strip()
    if not value:
        value = str(section.get(key, "") or "").strip()
    return value


def _path(section: dict, key: str, env: str, default: Path) -> Path:
    """A required path: settings/env wins, otherwise the derived repository default."""
    raw = _text(section, key, env)
    return Path(raw).expanduser() if raw else default


def _optional_path(section: dict, key: str, env: str) -> Path | None:
    """A machine-specific path that has no derivable default (``None`` = 未配置)."""
    raw = _text(section, key, env)
    return Path(raw).expanduser() if raw else None


@dataclass(frozen=True)
class ToolPaths:
    """Resolved interpreter + script for one registered tool.

    ``interpreter``/``script`` are ``None`` when the machine-specific location has
    not been registered in the ignored config; callers must report that as
    "unavailable" instead of substituting a guess.
    """

    tool_id: str
    interpreter: Path | None
    script: Path | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def interpreter_ok(self) -> bool:
        return bool(self.interpreter and self.interpreter.is_file())


@dataclass(frozen=True)
class ResearchConfig:
    workspace_root: Path
    master_workbook: Path
    work_root: Path
    output_root: Path
    run_root: Path
    synthetic_root: Path
    research_root: Path | None
    experiment_root: Path | None
    allowed_origins: tuple[str, ...]
    streamlit_url: str
    tools: dict[str, ToolPaths]
    trusted_tool_roots: tuple[Path, ...]

    def tool(self, tool_id: str) -> ToolPaths | None:
        return self.tools.get(tool_id)


def _build() -> ResearchConfig:
    settings = _settings()
    tools = settings.get("tools", {}) or {}
    web = settings.get("research_web", {}) or {}
    sources = settings.get("sources", {}) or {}

    # ---- 科研工作空间（可推导：<workspace>/01_Research/11_Research_Workspace）----
    workspace_root = _path(
        web, "workspace_root", "RESEARCH_WEB_WORKSPACE_ROOT",
        _WORKSPACE / "01_Research" / "11_Research_Workspace",
    )
    master_workbook = _path(
        sources, "master_workbook", "RESEARCH_WEB_MASTER_WORKBOOK",
        workspace_root / "02_科研主数据" / "样品-工艺-性能主表_v0.1.xlsx",
    )
    work_root = _path(web, "work_root", "RESEARCH_WEB_WORK_ROOT", workspace_root / "03_工作区")
    output_root = _path(web, "output_root", "RESEARCH_WEB_OUTPUT_ROOT", workspace_root / "04_输出区")
    run_root = _path(web, "run_root", "RESEARCH_WEB_RUN_ROOT", ROOT / "outputs" / "research_web")
    synthetic_root = _path(
        web, "synthetic_root", "RESEARCH_WEB_SYNTHETIC_ROOT",
        workspace_root / "03_工作区" / "PSYN_合成演示",
    )

    # ---- 真实科研正文（机器专用，只在忽略配置里登记；没登记就是 None）----
    research_root = _optional_path(sources, "research_root", "RESEARCH_ROOT")
    experiment_root = _optional_path(sources, "experiment_root", "RESEARCH_EXPERIMENT_ROOT")
    if experiment_root is None and research_root is not None:
        experiment_root = research_root / "02_实验数据"

    # ---- 独立工具项目根（可推导：<engineering>/0N_<name>）----
    steeldata_project = _path(
        tools, "steeldata_project", "STEELDATA_PROJECT", _ENGINEERING / "02_SteelData")
    steelstats_project = _path(
        tools, "steelstats_project", "STEELSTATS_PROJECT", _ENGINEERING / "03_SteelStats")
    mra_root = _path(
        tools, "materials_agent_project", "MATERIALS_AGENT_PROJECT",
        _ENGINEERING / "04_Materials_Research_Agent")

    # ---- 共享工具脚本/模型/数据库（可推导：<workspace>/06_Tools/...）----
    microsam_script = _path(
        tools, "microsam_script", "MICROSAM_SCRIPT",
        _TOOLS / "01_Applications" / "01_Micro_SAM" / "microsam_predict.py")
    calphad_script = _path(
        tools, "calphad_script", "CALPHAD_SCRIPT",
        _TOOLS / "01_Applications" / "02_CALPHAD" / "calphad_equilibrium.py")
    microsam_checkpoint = _path(
        tools, "microsam_checkpoint", "MICROSAM_CHECKPOINT",
        _TOOLS / "03_Models" / "01_Micro_SAM" / "sam_vit_b_01ec64.pth")
    calphad_tdb = _path(
        tools, "calphad_tdb", "CALPHAD_TDB",
        _TOOLS / "04_Databases" / "01_CALPHAD" / "mc_fe_v2062_clean_19b1164.tdb")

    resolved: dict[str, ToolPaths] = {
        # SteelData/SteelStats 的解释器可推导为项目内 .venv（源码迁入工程区，
        # 环境按 WO-28/WO-31 原位保护，因此实际位置由忽略配置指回）。
        "steeldata": ToolPaths(
            tool_id="steeldata",
            interpreter=_path(tools, "steeldata_python", "STEELDATA_PYTHON",
                              steeldata_project / ".venv" / "Scripts" / "python.exe"),
            script=None,
            extra={"project": str(steeldata_project)},
        ),
        "steelstats": ToolPaths(
            tool_id="steelstats",
            interpreter=_path(tools, "steelstats_python", "STEELSTATS_PYTHON",
                              steelstats_project / ".venv" / "Scripts" / "python.exe"),
            script=None,
            extra={"project": str(steelstats_project)},
        ),
        # Micro-SAM / CALPHAD 的解释器是机器专用隔离环境，没有可推导默认值。
        "microsam": ToolPaths(
            tool_id="microsam",
            interpreter=_optional_path(tools, "microsam_python", "MICROSAM_PYTHON"),
            script=microsam_script,
            extra={"checkpoint": str(microsam_checkpoint)},
        ),
        "calphad": ToolPaths(
            tool_id="calphad",
            interpreter=_optional_path(tools, "calphad_python", "STEELAI_CALPHAD_PYTHON"),
            script=calphad_script,
            extra={"tdb": str(calphad_tdb)},
        ),
        # MRA 的运行环境原位保留在旧根，新根不含 venv，因此只能由忽略配置登记。
        "materials_agent": ToolPaths(
            tool_id="materials_agent",
            interpreter=_optional_path(tools, "materials_agent_python", "MATERIALS_AGENT_PYTHON"),
            script=None,
            extra={"project": str(mra_root)},
        ),
    }

    # 可信根 = 服务器自己推导/登记的工具根（可推导项目根 + 忽略配置里显式登记的工具环境根）。
    declared_env_roots = web.get("tool_env_roots", []) or []
    trusted_roots = tuple(
        dict.fromkeys(
            [steeldata_project, steelstats_project, mra_root]
            + [Path(str(item)).expanduser() for item in declared_env_roots if str(item).strip()]
        )
    )

    origins_raw = _text(web, "allowed_origins", "RESEARCH_WEB_ALLOWED_ORIGINS")
    if origins_raw:
        allowed = tuple(item.strip() for item in origins_raw.split(",") if item.strip())
    else:
        from steelai.web_api.security import default_allowed_origins

        allowed = default_allowed_origins("127.0.0.1", (8760, 8761, 5173))

    # 科研 Streamlit 薄入口固定在可信回环端口（不是路径，所以不走 Path 解析）。
    streamlit_url = _text(web, "streamlit_url", "RESEARCH_WEB_STREAMLIT_URL")
    if not streamlit_url.startswith("http"):
        streamlit_url = "http://127.0.0.1:8761/"

    return ResearchConfig(
        workspace_root=workspace_root,
        master_workbook=master_workbook,
        work_root=work_root,
        output_root=output_root,
        run_root=run_root,
        synthetic_root=synthetic_root,
        research_root=research_root,
        experiment_root=experiment_root,
        allowed_origins=allowed,
        streamlit_url=streamlit_url,
        tools=resolved,
        trusted_tool_roots=trusted_roots,
    )


_CACHE: ResearchConfig | None = None


def config(refresh: bool = False) -> ResearchConfig:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = _build()
    return _CACHE
