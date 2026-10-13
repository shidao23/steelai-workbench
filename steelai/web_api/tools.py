"""WO-31 §3 — 已登记工具的能力描述与**固定 argv 构造**。

规则（对应工单 §3）：

* 后端可信解析 ``project``/``task``/``fileId``/``output``；客户端**不能**提交任意
  文件路径、URL、解释器、shell 或 Python 入口。
* 参数是固定 schema：每个工具自己声明字段，构造 argv 时不拼接字符串、
  不经过 shell（``subprocess`` 始终收到列表，``shell=False``）。
* 缺一个工具只让对应能力卡不可用，并在 ``reason`` 里说清缺什么。
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from steelai.web_api.config import config
from steelai.web_api.security import GuardError

ELEMENT_RE = re.compile(r"^[A-Z][A-Z]?$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
PHASE_RE = re.compile(r"^[A-Za-z0-9_+\-()]{1,32}$")
MAX_TEMPERATURES = 12
MAX_POINTS = 8


@dataclass
class Field:
    name: str
    kind: str                      # file | text | number | select | points | box | list
    label: str
    required: bool = False
    help: str = ""
    default: str | float | None = None
    options: list[str] = field(default_factory=list)
    suffix: str = ""


@dataclass
class Capability:
    tool_id: str
    page: str
    label: str
    description: str
    contract: str
    fields: list[Field]
    outputs: list[str]
    available: bool = True
    reason: str = ""

    def as_dict(self) -> dict:
        data = asdict(self)
        data["fields"] = [asdict(item) for item in self.fields]
        return data


# --------------------------------------------------------------------------- #
# 参数校验
# --------------------------------------------------------------------------- #

def _number(value, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GuardError(f"{name} 不是数字") from exc
    if not math.isfinite(result):
        raise GuardError(f"{name} 必须是有限数")
    return result


def _element(value: str) -> str:
    """CALPHAD 组元用大写元素符号（``FE``/``C``/``CR``）。"""
    text = str(value or "").strip().upper()
    if not ELEMENT_RE.match(text):
        raise GuardError(f"非法元素符号：{text!r}（应为大写元素符号，如 FE、C、CR）")
    if text == "VA":
        raise GuardError("不要把 VA 写进组元：TDB 声明时脚本会自动加入，手写会静默改变相组合")
    return text


def _phase(value: str) -> str:
    text = str(value or "").strip()
    if not PHASE_RE.match(text):
        raise GuardError(f"非法相名：{text!r}")
    return text


def _temps(raw, unit: str) -> tuple[list[str], list[str]]:
    """Return ``--temp-list``/``--temp-unit`` argv fragments for an explicit list."""
    if not isinstance(raw, list) or not raw:
        raise GuardError("必须给出显式温度列表")
    if len(raw) > MAX_TEMPERATURES:
        raise GuardError(f"温度点数不能超过 {MAX_TEMPERATURES}")
    values = [str(_number(item, "温度")) for item in raw]
    return values, ["--temp-unit", unit]


def _missing(tool, label: str, setting_key: str) -> str:
    """Say exactly what is missing: an unregistered interpreter or a bad path.

    A machine-specific interpreter that has no derivable default is only ever
    registered in the ignored ``config/settings.toml``; when it is absent the
    honest answer is "未登记", not a guessed path.
    """
    if tool is None or tool.interpreter is None:
        return (f"缺少 {label}：未在忽略的 config/settings.toml 的 [tools] 中登记 "
                f"{setting_key}")
    return f"缺少 {label}：{tool.interpreter}"


def _interpreter(tool, tool_id: str):
    """Return the interpreter or refuse; never let ``None`` reach ``subprocess``."""
    if tool is None or tool.interpreter is None:
        raise GuardError(f"{tool_id} 未登记可信解释器")
    return tool.interpreter


def _script(tool, tool_id: str) -> str:
    """Return the registered tool script path, or refuse."""
    if tool is None or tool.script is None or not tool.script.is_file():
        raise GuardError(f"{tool_id} 未登记可信脚本")
    return str(tool.script)


# --------------------------------------------------------------------------- #
# 能力清单
# --------------------------------------------------------------------------- #

def _capabilities() -> list[Capability]:
    cfg = config()
    caps: list[Capability] = []

    steeldata = cfg.tool("steeldata")
    sd_ok = bool(steeldata and steeldata.interpreter_ok())
    sd_reason = "" if sd_ok else _missing(steeldata, "SteelData 独立解释器",
                                          "steeldata_python")

    caps.append(Capability(
        tool_id="steeldata.preview", page="data_processing",
        label="SteelData · 预览（不改数据）",
        description="对选定输入与 profile 做本地预览，只读，不写审批或输出。",
        contract="SteelData-CLI-preview",
        fields=[
            Field("input_file", "file", "输入数据文件", True, "任务输入目录中的单个文件", suffix=".csv"),
            Field("profile_file", "file", "映射 profile（JSON）", True,
                  "网页映射保存的候选 profile（本任务 profiles/），或输入目录中导入的 profile", suffix=".json"),
        ],
        outputs=["预览 JSON（字段/单位/摘要）"],
        available=sd_ok, reason=sd_reason,
    ))
    caps.append(Capability(
        tool_id="steeldata.run", page="data_processing",
        label="SteelData · 按人审审批运行",
        description="使用显式人工审批文件运行；缺审批、缺摘要、输入或映射变化即拒绝，不自动改绿。",
        contract="SteelData-CLI-run",
        fields=[
            Field("input_file", "file", "输入数据文件", True, suffix=".csv"),
            Field("approval_file", "file", "人审审批文件（approval JSON）", True,
                  "本任务 approvals/ 下由网页具名人审生成的，或 inputs/ 下导入的既有审批", suffix=".json"),
        ],
        outputs=["processed 表", "manifest.json", "QC 报告"],
        available=sd_ok, reason=sd_reason,
    ))
    caps.append(Capability(
        tool_id="steeldata.demo", page="data_processing",
        label="SteelData · 合成演示（隔离输出）",
        description="只跑仓库自带合成 fixture，输出到本任务独立目录；坏值按原合同 QCfailed，不伪改全绿。",
        contract="SteelData-CLI-demo",
        fields=[],
        outputs=["report.html", "manifest.json", "qc.json"],
        available=sd_ok, reason=sd_reason,
    ))
    caps.append(Capability(
        tool_id="steeldata.verify", page="data_processing",
        label="SteelData · 校验运行目录",
        description="校验某次运行目录的完成标记与产物校验和。"
                    "SteelData 的运行会落在本次 web run 输出目录下的 run-<hash>/ 子目录，"
                    "此处留空即自动定位唯一含 COMPLETE 的结果目录。",
        contract="SteelData-CLI-verify",
        fields=[
            Field("run_dir", "select", "要校验的 web 运行", True, "本任务已完成的运行"),
            Field("target", "text", "结果子目录（可留空自动定位）", False,
                  help="相对该 web 运行输出目录的子目录，例如 run-5e991e741496446b"),
        ],
        outputs=["integrity/processing_status/qc_status"],
        available=sd_ok, reason=sd_reason,
    ))

    steelstats = cfg.tool("steelstats")
    ss_ok = bool(steelstats and steelstats.interpreter_ok())
    ss_reason = "" if ss_ok else _missing(steelstats, "SteelStats 独立解释器",
                                          "steelstats_python")
    caps.append(Capability(
        tool_id="steelstats.report", page="tools",
        label="SteelStats · 描述统计报告",
        description="固定合同：输入必须是已标准化、带质量状态的观测包（T30 的 4 个固定文件）。"
                    "只出描述统计与组级 QC，不做显著性检验，n 按独立物理试样。",
        contract="SteelStats-Statistical-Input-v1.0",
        fields=[
            Field("analysis_plan", "file", "analysis_plan.json", True, suffix=".json"),
            Field("units", "file", "units.csv", True, suffix=".csv"),
            Field("observations", "file", "observations.csv", True, suffix=".csv"),
            Field("decisions", "file", "decisions.csv", True, suffix=".csv"),
        ],
        outputs=["statistical report 包", "verify-report 校验结果"],
        available=ss_ok, reason=ss_reason,
    ))
    caps.append(Capability(
        tool_id="steelstats.verify", page="tools",
        label="SteelStats · 校验报告包",
        description="对已发布的 T32 报告包做完整性校验；被篡改必须拒绝。",
        contract="SteelStats-T32-report-package",
        fields=[Field("run_dir", "select", "要校验的 web 运行", True, "本任务已完成且产出报告包的运行")],
        outputs=["status=complete/失败原因"],
        available=ss_ok, reason=ss_reason,
    ))

    microsam = cfg.tool("microsam")
    ms_missing: list[str] = []
    if microsam:
        if microsam.interpreter is None:
            ms_missing.append("解释器未登记（tools.microsam_python）")
        elif not microsam.interpreter.is_file():
            ms_missing.append(f"解释器 {microsam.interpreter}")
        if not microsam.script or not microsam.script.is_file():
            ms_missing.append(f"脚本 {microsam.script}")
        ckpt = Path(microsam.extra.get("checkpoint", ""))
        if not ckpt.is_file():
            ms_missing.append(f"权重 {ckpt}")
    ms_ok = microsam is not None and not ms_missing
    ms_reason = "" if ms_ok else "缺少：" + "；".join(ms_missing or ["未配置"])
    caps.append(Capability(
        tool_id="microsam.predict", page="tools",
        label="Micro-SAM · 单图点/框分割",
        description="单张图像的提示式分割；点/框是**原像素坐标**，输出真 mask/overlay 与 run.json。",
        contract="MicroSAM-single-image-v1",
        fields=[
            Field("image", "file", "单张图像", True, suffix=".png"),
            Field("prompt_mode", "select", "提示方式", True, options=["point", "box"]),
            Field("point_x", "number", "点 X（原像素）", False, default=128),
            Field("point_y", "number", "点 Y（原像素）", False, default=128),
            Field("box", "box", "框 X0 Y0 X1 Y1（原像素）", False, default="64 64 192 192"),
            Field("label", "select", "标签", False, options=["1", "0"], default="1"),
            Field("save_overlay", "select", "同时保存 overlay", False, options=["true", "false"], default="true"),
        ],
        outputs=["mask_*.png", "mask_*.npy", "run.json"],
        available=ms_ok and not ms_missing, reason=ms_reason,
    ))

    calphad = cfg.tool("calphad")
    cp_missing: list[str] = []
    if calphad:
        if calphad.interpreter is None:
            cp_missing.append("解释器未登记（tools.calphad_python）")
        elif not calphad.interpreter.is_file():
            cp_missing.append(f"解释器 {calphad.interpreter}")
        if not calphad.script or not calphad.script.is_file():
            cp_missing.append(f"脚本 {calphad.script}")
        if not Path(calphad.extra.get("tdb", "")).is_file():
            cp_missing.append(f"TDB {calphad.extra.get('tdb')}")
    cp_ok = calphad is not None and not cp_missing
    cp_reason = "" if cp_ok else "缺少：" + "；".join(cp_missing or ["未配置"])
    caps.append(Capability(
        tool_id="calphad.equilibrium", page="tools",
        label="CALPHAD · 缩减体系平衡相分数",
        description="显式组元/相/温度与单位；余额元素不被覆盖、显式零不丢。首版复用已验证 Fe–C 小例。",
        contract="CALPHAD-reduced-system-v1",
        fields=[
            Field("components", "text", "组元（大写空格分隔；**不要写 VA**）", True, default="FE C"),
            Field("phases", "text", "相（空格分隔）", True, default="LIQUID BCC_A2"),
            Field("composition", "text", "非余额组元成分（如 C=0.02，空格分隔）", True, default="C=0.02"),
            Field("temps", "list", "温度列表（空格分隔）", True, default="900 1000 1100"),
            Field("temp_unit", "select", "温度单位", True, options=["K", "C"], default="K"),
        ],
        outputs=["phase_fractions.csv", "run.json"],
        available=cp_ok and not cp_missing, reason=cp_reason,
    ))
    return caps


def capabilities() -> list[dict]:
    return [cap.as_dict() for cap in _capabilities()]


def capability(tool_id: str) -> dict:
    for cap in _capabilities():
        if cap.tool_id == tool_id:
            return cap.as_dict()
    raise GuardError(f"未登记的工具：{tool_id}")


# --------------------------------------------------------------------------- #
# argv 构造：只在这里把可信值变成命令行
# --------------------------------------------------------------------------- #

def _resolve_input(task_inputs: Path, name: str) -> Path:
    from steelai.web_api.security import resolve_under, safe_filename

    return resolve_under(task_inputs, safe_filename(name))


def _stage_run_input(source: Path, task_dir: Path, run_id: str) -> Path:
    """SteelData ``run --input`` 收的是**目录**（一个批次），不是一个文件。

    这里为本次运行把选中的那一个输入复制进 `<task>/.stage/<run_id>/inputs/`：
    * 复制字节，不改内容——原件仍然只读，且后续处理用的就是这同一批字节；
    * 目录里放这一个文件，不放 `inputs/` 下的其他文件（否则 SteelData 会把
      它们也当输入并报 unsupported，QC 会被无谓污染）；
    * 输出目录在 `<task>/runs/<run_id>/`，与 `.stage/` 不重叠，符合 SteelData
      "input/output 不得互相包含" 的约束。
    """
    stage = task_dir / ".stage" / run_id / "inputs"
    stage.mkdir(parents=True, exist_ok=True)
    staged = stage / source.name
    if not staged.is_file():
        staged.write_bytes(source.read_bytes())
    return stage


def build_argv(tool_id: str, params: dict, *, task_inputs: Path, out_dir: Path,
               run_id: str, existing_runs: list[str],
               project_id: str | None = None, task_id: str | None = None,
               provenance: dict | None = None) -> tuple[Path, list[str], Path]:
    """Return ``(interpreter, argv, cwd)`` for one run. Raises ``GuardError`` on bad input.

    当 ``provenance`` 是 dict 时，会把「这次运行依据的确认从哪来」写进去，供运行记录
    如实留痕（web 人审生成 / 导入的既有审批），而不是让一个 actor 字符串自己声明。
    """
    cfg = config()

    if tool_id == "steeldata.demo":
        tool = cfg.tool("steeldata")
        return _interpreter(tool, tool_id), ["-B", "-m", "steeldata", "demo", "--output", str(out_dir)], Path(tool.extra["project"])

    if tool_id == "steeldata.preview":
        tool = cfg.tool("steeldata")
        source = _resolve_input(task_inputs, params.get("input_file", ""))
        if project_id and task_id:
            from steelai.web_api import mapping
            profile = mapping.resolve_profile_file(project_id, task_id, params.get("profile_file", ""))
        else:
            profile = _resolve_input(task_inputs, params.get("profile_file", ""))
        return _interpreter(tool, tool_id), [
            "-B", "-m", "steeldata", "preview",
            "--input-file", str(source), "--profile", str(profile),
        ], Path(tool.extra["project"])

    if tool_id == "steeldata.profile":
        tool = cfg.tool("steeldata")
        source = _resolve_input(task_inputs, params.get("input_file", ""))
        return _interpreter(tool, tool_id), ["-B", "-m", "steeldata", "profile", str(source)], Path(tool.extra["project"])

    if tool_id == "steeldata.run":
        tool = cfg.tool("steeldata")
        source = _resolve_input(task_inputs, params.get("input_file", ""))
        if not project_id or not task_id:
            raise GuardError("steeldata.run 需要任务上下文来复核人工确认")
        from steelai.web_api import mapping
        # 确认必须来自本任务 approvals/（网页人审生成）或 inputs/（导入的既有审批），
        # 并且输入 SHA / profile 摘要任一变化都让旧确认失效。
        info = mapping.approval_for_run(project_id, task_id, params.get("approval_file", ""))
        if not info.get("ok"):
            raise GuardError(str(info.get("message") or "该确认已失效，请重新保存映射并重新人工确认"))
        approval = Path(info["path"])
        if provenance is not None:
            provenance.update({
                "approval_origin": info.get("origin", ""),
                "approval_file": info.get("file", ""),
                "approval_profile_id": info.get("profile_id", ""),
                "approval_profile_sha256": info.get("profile_sha256", ""),
                "approval_input_sha256": info.get("input_sha256", ""),
                "approval_reviewer": info.get("reviewer", ""),
                "approval_synthetic": bool(info.get("synthetic", False)),
            })
        # SteelData run 的 --input 是目录：只把本次选中的输入暂存进去（见 _stage_run_input）
        stage = _stage_run_input(source, out_dir.parent.parent, run_id)
        return _interpreter(tool, tool_id), [
            "-B", "-m", "steeldata", "run",
            "--input", str(stage), "--approval", str(approval), "--output", str(out_dir),
        ], Path(tool.extra["project"])

    if tool_id == "steeldata.verify":
        tool = cfg.tool("steeldata")
        chosen = str(params.get("run_dir", "")).strip()
        if chosen not in existing_runs:
            raise GuardError("只能校验本任务已登记的运行")
        web_out = out_dir.parent / chosen
        target = str(params.get("target", "")).strip()
        if target:
            from steelai.web_api.security import resolve_under

            result_dir = resolve_under(web_out, target)
        else:
            result_dir = discover_result_dir(web_out)
        if result_dir is None or not result_dir.is_dir():
            raise GuardError(f"该运行下没有可校验的结果目录：{web_out}")
        return _interpreter(tool, tool_id), ["-B", "-m", "steeldata", "verify", str(result_dir)], Path(tool.extra["project"])

    if tool_id == "steelstats.report":
        tool = cfg.tool("steelstats")
        bundle = out_dir / "input_bundle"
        bundle.mkdir(parents=True, exist_ok=True)
        required = {
            "analysis_plan": "analysis_plan.json",
            "units": "units.csv",
            "observations": "observations.csv",
            "decisions": "decisions.csv",
        }
        for key, target_name in required.items():
            source = _resolve_input(task_inputs, params.get(key, ""))
            (bundle / target_name).write_bytes(source.read_bytes())
        return _interpreter(tool, tool_id), [
            "-B", "-m", "steelstats", "report", str(bundle),
            "--output", str(out_dir / "reports"),
        ], Path(tool.extra["project"])

    if tool_id == "steelstats.verify":
        tool = cfg.tool("steelstats")
        chosen = str(params.get("run_dir", "")).strip()
        if chosen not in existing_runs:
            raise GuardError("只能校验本任务已登记的运行")
        reports = out_dir.parent / chosen / "reports"
        if not reports.is_dir():
            raise GuardError(f"该运行没有 reports 目录：{reports}")
        packages = sorted(item for item in reports.iterdir() if item.is_dir())
        if len(packages) != 1:
            raise GuardError(f"reports 下需要唯一报告包，实际 {len(packages)} 个")
        return _interpreter(tool, tool_id), [
            "-B", "-m", "steelstats", "verify-report", str(packages[0]),
        ], Path(tool.extra["project"])

    if tool_id == "microsam.predict":
        tool = cfg.tool("microsam")
        image = _resolve_input(task_inputs, params.get("image", ""))
        mode = str(params.get("prompt_mode", "point"))
        argv = [
            "-B", _script(tool, tool_id),
            "--input", str(image),
            "--output-dir", str(out_dir),
            "--run-id", run_id,
            "--checkpoint", str(tool.extra["checkpoint"]),
        ]
        if mode == "point":
            argv += ["--point", str(_number(params.get("point_x"), "点 X")), str(_number(params.get("point_y"), "点 Y"))]
            argv += ["--label", str(int(_number(params.get("label", 1), "标签")))]
        elif mode == "box":
            raw = params.get("box", "")
            if isinstance(raw, str):
                parts = raw.split()
            elif isinstance(raw, (list, tuple)):
                parts = list(raw)
            else:
                parts = []
            if len(parts) != 4:
                raise GuardError("框需要 4 个坐标 X0 Y0 X1 Y1")
            argv += ["--box", *[str(_number(item, "框坐标")) for item in parts]]
        else:
            raise GuardError(f"不支持的提示方式：{mode}")
        if str(params.get("save_overlay", "true")).lower() == "true":
            argv.append("--save-overlay")
        return _interpreter(tool, tool_id), argv, Path(tool.extra.get("project", Path.cwd()))

    if tool_id == "calphad.equilibrium":
        tool = cfg.tool("calphad")
        components = [_element(item) for item in str(params.get("components", "")).split()]
        if not components:
            raise GuardError("组元不能为空")
        phases = [_phase(item) for item in str(params.get("phases", "")).split()]
        if not phases:
            raise GuardError("相不能为空")
        pairs: list[str] = []
        for item in str(params.get("composition", "")).split():
            if "=" not in item:
                raise GuardError(f"成分需要 EL=VALUE 形式：{item!r}")
            element, _, value = item.partition("=")
            pairs.append(f"{_element(element)}={_number(value, '成分')}")
        if not pairs:
            raise GuardError("成分不能为空")
        unit = str(params.get("temp_unit", "K"))
        if unit not in {"K", "C"}:
            raise GuardError("温度单位只能是 K 或 C")
        raw_temps = params.get("temps", [])
        if isinstance(raw_temps, str):
            raw_temps = raw_temps.split()
        temps, unit_argv = _temps(raw_temps, unit)
        argv = [
            "-B", _script(tool, tool_id),
            "--tdb", str(tool.extra["tdb"]),
            "--components", *components,
            "--phases", *phases,
            "--x", *pairs,
            "--temp-list", *temps,
            *unit_argv,
            "--output-dir", str(out_dir),
            "--run-id", run_id,
        ]
        return _interpreter(tool, tool_id), argv, Path(tool.extra.get("project", Path.cwd()))

    raise GuardError(f"未登记的工具：{tool_id}")


def missing_asset_reason(tool_id: str) -> str:
    """Return a non-empty reason when the tool cannot run at all."""
    for cap in _capabilities():
        if cap.tool_id == tool_id:
            return cap.reason
    return f"未登记的工具：{tool_id}"


def discover_result_dir(web_out: Path) -> Path | None:
    """Locate the SteelData result directory created inside one web run output.

    ``steeldata demo/run --output X`` writes ``X/run-<hash>/``; a caller that
    names the web run instead of that nested directory is resolved here, and
    only when the choice is unambiguous (exactly one ``COMPLETE`` marker).
    """
    if not web_out.is_dir():
        return None
    if (web_out / "COMPLETE").is_file():
        return web_out
    candidates = [item for item in sorted(web_out.iterdir())
                  if item.is_dir() and (item / "COMPLETE").is_file()]
    if len(candidates) == 1:
        return candidates[0]
    return None


def discover_result_dirs(web_out: Path) -> list[str]:
    """All nested SteelData result directories inside one web run output."""
    if not web_out.is_dir():
        return []
    if (web_out / "COMPLETE").is_file():
        return ["."]
    return sorted(item.name for item in web_out.iterdir()
                  if item.is_dir() and (item / "COMPLETE").is_file())
