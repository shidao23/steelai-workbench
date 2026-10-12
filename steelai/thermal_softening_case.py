"""Read-only, literature-grounded case for the approved T75 double-hit batch."""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from steelai.governance import (
    EvidenceClass,
    GovernanceState,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    build_manifest,
    create_staging_directory,
    digest_value,
    load_verified_manifest,
    publish_append_only,
    seal_package,
    sha256_file,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS, ROOT
from steelai.thermal_simulation_analysis import load_standardized_thermal_data
from steelai.thermal_softening_analysis import build_softening_result_preview, load_softening_method_registry


CASE_VERSION = "SteelAI-Thermal-Softening-Case-v1.1"
CASE_ROOT = OUTPUTS / "thermal_softening_cases"
SOFTENING_RELATIVE = Path("data/processed/thermal_simulation_softening.csv")
FEATURES_RELATIVE = Path("data/processed/thermal_simulation_features.csv")
REGISTRY_RELATIVE = Path("config/thermal_softening_method_registry_v1.0.json")
LITERATURE_SHA256 = "dbdc31ee31a5754869b8282796af6f75416fc1c349c30f1123fb7e85bc6259d7"
_CASE_ID = re.compile(r"^TSC-[A-F0-9]{20}$")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(row: Mapping[str, str], key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _validate_formal_rows(
    formal: list[dict[str, str]], calculated: list[dict[str, Any]],
    features: list[dict[str, str]], registry_digest: str,
) -> list[dict[str, Any]]:
    if not formal or len(formal) != len(calculated):
        raise ValueError("T75 formal and recalculated result counts differ")
    by_run = {row["experiment_run_id"]: row for row in formal}
    feature_by_run = {row["experiment_run_id"]: row for row in features}
    if len(by_run) != len(formal) or len(feature_by_run) != len(features):
        raise ValueError("T75 or T74 contains duplicate run IDs")
    if set(by_run) != {row["experiment_run_id"] for row in calculated}:
        raise ValueError("T75 formal and recalculated run IDs differ")

    checked: list[dict[str, Any]] = []
    for candidate in calculated:
        run_id = candidate["experiment_run_id"]
        row = by_run[run_id]
        feature = feature_by_run.get(run_id)
        if feature is None or row["source_feature_row_sha256"] != feature["feature_row_sha256"]:
            raise ValueError(f"{run_id}: approved feature link is invalid")
        if (
            row["result_review_status"] != "approved"
            or not row["result_reviewer_id"].strip()
            or not row["result_reviewed_at"].strip()
            or row["source_feature_review_status"] != "approved"
            or row["method_selection_status"] != "approved"
            or row["method_registry_sha256"] != registry_digest
        ):
            raise ValueError(f"{run_id}: approval or method evidence is incomplete")
        for key, value in candidate.items():
            if key in {"result_review_status", "result_reviewer_id", "result_reviewed_at", "softening_row_sha256"}:
                continue  # The formal row adds approval metadata and receives a new digest.
            if key not in row:
                raise ValueError(f"{run_id}: {key} is missing from the formal result")
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                if not math.isclose(_number(row, key), float(value), rel_tol=1e-10, abs_tol=1e-9):
                    raise ValueError(f"{run_id}: {key} differs from recalculation")
            elif row[key] != str(value):
                raise ValueError(f"{run_id}: {key} differs from recalculation")

        primary = _number(row, "primary_softening_percent_raw")
        sensitivity = _number(row, "sensitivity_softening_percent_raw")
        checked.append({
            "acquisition_id": "A" + row["acquisition_id"],
            "sample_id": row["sample_id"],
            "temperature_c": round(_number(row, "effective_temperature_c"), 3),
            "deformation_gap_s": round(_number(row, "effective_deformation_gap_s"), 4),
            "primary_percent": round(primary, 4),
            "sensitivity_percent": round(sensitivity, 4),
            "sensitivity_minus_primary_pp": round(sensitivity - primary, 4),
            "sigma_2_minus_sigma_1_mpa": round(
                _number(row, "primary_sigma_2_mpa") - _number(row, "primary_sigma_1_mpa"), 4
            ),
            "qc_status": row["result_qc_status"],
            "qc_flags": row["qc_flags"].split(";") if row["qc_flags"] else [],
            "approved_row_digest": row["softening_row_sha256"],
        })
    return sorted(checked, key=lambda item: int(item["acquisition_id"][1:]))


def build_softening_case(*, project_root: Path = ROOT, literature_pdf: Path) -> dict[str, Any]:
    """Recalculate the approved batch and bind a fixed paper by its file digest."""
    pdf_digest = sha256_file(literature_pdf)
    if pdf_digest != LITERATURE_SHA256:
        raise ValueError("The literature PDF differs from the reviewed Zhang Ling thesis")
    registry_path = project_root / REGISTRY_RELATIVE
    registry = load_softening_method_registry(registry_path)
    if registry["selection_status"] != "approved":
        raise ValueError("T75 method selection is not approved")
    runs, points = load_standardized_thermal_data(project_root)
    preview = build_softening_result_preview(
        runs, points, project_root=project_root, registry_path=registry_path
    )
    formal = _rows(project_root / SOFTENING_RELATIVE)
    features = _rows(project_root / FEATURES_RELATIVE)
    checked = _validate_formal_rows(formal, preview["rows"], features, sha256_file(registry_path))
    warnings = [row for row in checked if row["qc_status"] != "passed"]
    sensitivity_review = [
        row["acquisition_id"] for row in checked
        if row["qc_status"] == "passed" and abs(row["sensitivity_minus_primary_pp"]) >= 10
    ]
    low_temperature = [
        row for row in checked if 995 <= row["temperature_c"] <= 1005
        and 9 <= row["deformation_gap_s"] <= 11 and row["qc_status"] == "passed"
    ]
    low_b = [row["primary_percent"] for row in low_temperature if row["sample_id"] == "B-DQ"]
    low_r = [row["primary_percent"] for row in low_temperature if row["sample_id"] == "R-DQ"]
    if len(low_b) != 2 or len(low_r) != 2:
        raise ValueError("The 1000 C comparison lacks its two approved runs per sample")
    source_digests = {
        "formal_results_sha256": sha256_file(project_root / SOFTENING_RELATIVE),
        "runs_sha256": sha256_file(project_root / "data/processed/thermal_simulation_runs.csv"),
        "points_sha256": sha256_file(project_root / "data/processed/thermal_simulation_points.csv"),
        "features_sha256": sha256_file(project_root / FEATURES_RELATIVE),
        "method_registry_sha256": sha256_file(registry_path),
        "literature_pdf_sha256": pdf_digest,
    }
    case_id = "TSC-" + digest_value({"version": CASE_VERSION, "sources": source_digests})[:20].upper()
    return {
        "schema_version": "1.0",
        "case_version": CASE_VERSION,
        "case_id": case_id,
        "status": "analysis_draft_needs_human_review",
        "source_digests": source_digests,
        "method": {
            "primary_id": registry["selected_method_id"],
            "sensitivity_id": registry["sensitivity_method_id"],
            "primary_sigma_m": "first_hit_observed_peak",
            "sensitivity_sigma_m": "first_hit_hollomon_projection",
            "same_sigma_m_for_both_methods": False,
        },
        "literature": {
            "title": "TSDR 工艺热加工过程的组织演变与控制",
            "author": "张玲",
            "year": 2007,
            "method_reference": "第4.1.2.1节，图4.4及式(4.1)，印刷页68-69 / PDF页81-82",
            "interpretation_reference": "第4.1.2.1节，图4.5，印刷页69-70 / PDF页82-83",
            "supported_points": [
                "双道次应力软化可按式(4.1)计算；论文采用2% offset应力。",
                "论文的sigma_m定义为第一道次结束时应力；本项目T75主方法使用第一道次峰值应力。",
                "应力软化含回复贡献，不能无条件等同于金相再结晶体积分数。",
                "论文的Nb2/Nb4材料及预应变、应变速率条件与本批B-DQ/R-DQ不能直接等同。",
            ],
        },
        "row_count": len(checked),
        "passed_count": len(checked) - len(warnings),
        "warning_ids": [row["acquisition_id"] for row in warnings],
        "large_method_difference_passed_ids": sensitivity_review,
        "observations": {
            "near_1000_c_9_to_11_s": {
                "b_dq_primary_percent_range": [min(low_b), max(low_b)],
                "r_dq_primary_percent_range": [min(low_r), max(low_r)],
                "r_min_exceeds_b_max": min(low_r) > max(low_b),
                "replicates_per_sample": 2,
            },
            "above_100_primary_count": sum(row["primary_percent"] > 100 for row in checked),
            "above_100_sensitivity_count": sum(row["sensitivity_percent"] > 100 for row in checked),
        },
        "rows": checked,
        "interpretation_limits": [
            "All values above 100 percent remain raw warnings, not recrystallized fractions.",
            "Do not fit kinetic parameters or infer mechanism from the warning rows.",
            "The two methods use different sigma_m definitions; their difference is not solely a strain-point effect.",
            "The thesis uses first-hit end stress for sigma_m; current T75 uses first-hit peak stress.",
            "Sample chemistry, prior strain and strain rate must be checked before mechanistic comparison with the thesis.",
            "This draft is not a human-approved scientific conclusion.",
        ],
    }


def _draft_markdown(case: Mapping[str, Any]) -> str:
    """Render the draft strictly from the case's own rows, QC, warnings and sources.

    Every factual statement below is derived from the case mapping: counts come from
    ``row_count``/``passed_count``, the review list from the actual warning rows, and the
    1000-degree comparison only appears when the case's own passed rows support it. Nothing
    about specific acquisitions (IDs, temperatures, ranges) is hardcoded, so a one-row
    synthetic case can never inherit the approved batch's narrative.
    """
    rows = list(case.get("rows") or [])
    warning_rows = [row for row in rows if str(row.get("qc_status", "")) != "passed"]
    sensitivity_over_100 = [
        str(row["acquisition_id"]) for row in warning_rows
        if float(row.get("sensitivity_percent", 0.0)) > 100.0
    ]
    window_rows = [
        row for row in rows
        if 995.0 <= float(row.get("temperature_c", 0.0)) <= 1005.0
        and 9.0 <= float(row.get("deformation_gap_s", 0.0)) <= 11.0
        and str(row.get("qc_status", "")) == "passed"
    ]
    outside_rows = [row for row in rows if row not in window_rows]
    outside_above_100 = [row for row in outside_rows if float(row.get("primary_percent", 0.0)) > 100.0]
    by_sample: dict[str, list[float]] = {}
    for row in window_rows:
        by_sample.setdefault(str(row.get("sample_id")), []).append(float(row["primary_percent"]))
    synthetic_demo = str(case.get("evidence_class", "")) == "synthetic_demo_data"
    literature = case.get("literature") or {}

    lines = [
        "# 双道次软化实验分析草稿", "",
        f"案例：`{case['case_id']}`；状态：待人工科研复核。",
    ]
    if synthetic_demo:
        lines += [
            "",
            "> **合成演示标记**：本包属于 `synthetic_demo_data`——全部内容由固定合成输入生成，"
            "不含任何真实测量；文献条目（如有）仅作方法依据占位，不代表已核验真实论文 PDF；"
            "本包不进入正式证据库。",
        ]
    lines += ["", "## 方法与证据", ""]
    if synthetic_demo:
        # A synthetic demo must not imply reviewed-data work that never happened: the percentages
        # and QC flags are FIXED SYNTHETIC INPUT, and no T75 recalculation, formal approval or
        # literature verification ran anywhere in this path.
        lines += [
            "本演示的百分比与 QC 标记直接来自固定合成输入。",
            "未运行 T75 曲线重算；没有已批准的正式结果；也没有真实文献 PDF 核验。",
        ]
    elif literature:
        lines += [
            "使用已批准的 T75 正式结果，逐项与标准化曲线重新计算的结果核对。",
            "主方法为 2% 偏移法；5% 定真应变法的参考应力来自 Hollomon 投影。",
            "论文式 (4.1) 的 σm 为第一道次结束应力；当前 T75 主方法取第一道次峰值，"
            "因此属于文献启发的方法实现，不能声称逐项复现论文。",
            f"文献（仅作方法依据）：{literature.get('author', '')}（{literature.get('year', '')}），"
            f"《{literature.get('title', '')}》，{literature.get('method_reference', '')}。",
        ]
    else:
        lines += [
            "使用 T75 冻结方法重新计算：主方法为 2% 偏移法；"
            "5% 定真应变法的参考应力来自 Hollomon 投影。",
            "本案例未绑定文献条目，不作任何文献核验声明。",
        ]
    lines += [
        "", "## 可确认的描述性结果", "",
        f"共 {case['row_count']} 个采集；{case['passed_count']} 个范围 QC 通过；"
        f"{len(case['warning_ids'])} 个仍需复核：{', '.join(case['warning_ids']) or '无'}。",
    ]
    if len(by_sample) >= 2 and len(window_rows) >= len(by_sample):
        parts = [
            f"{sample_id} 主软化率为 {min(values):.2f}–{max(values):.2f}%（n={len(values)}）"
            for sample_id, values in sorted(by_sample.items())
        ]
        lines += [
            f"约 1000 ℃、有效变形间隔 9–11 s 的 {len(window_rows)} 个通过项中，"
            + "，".join(parts) + "；此处只作描述性比较。",
        ]
    elif len(window_rows) == 1:
        only = window_rows[0]
        lines += [
            f"约 1000 ℃、有效变形间隔 9–11 s 仅有 1 个通过项（{only.get('sample_id')} "
            f"主软化率 {float(only['primary_percent']):.2f}%），无法作组间比较。",
        ]
    else:
        lines += ["无法作组间比较：没有同时满足约 1000 ℃、有效变形间隔 9–11 s 且范围 QC 通过的采集。"]
    if outside_rows:
        temps = [float(row.get("temperature_c", 0.0)) for row in outside_rows]
        lines += [
            f"其余 {len(outside_rows)} 个采集（温度 {min(temps):.0f}–{max(temps):.0f} ℃）中 "
            f"{len(outside_above_100)} 个 2% 主结果超过 100%（原始结果不截断），"
            "暂不拟合动力学或排序材料。",
        ]
    lines += [
        "", "## 逐采集结果", "",
        "| 采集 | 样品 | 温度 ℃ | 有效间隔 s | 2% 主结果 % | 5% 对照 % | QC |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['acquisition_id']} | {row['sample_id']} | {row['temperature_c']:.2f} | "
            f"{row['deformation_gap_s']:.4f} | {row['primary_percent']:.2f} | "
            f"{row['sensitivity_percent']:.2f} | {row['qc_status']} |"
        )
    lines += ["", "## 待复核", ""]
    if warning_rows:
        for row in warning_rows:
            flags = [str(flag) for flag in (row.get("qc_flags") or [])]
            flag_note = f"（QC 标记：{'、'.join(flags)}）" if flags else ""
            lines.append(
                f"- {row['acquisition_id']}（{row.get('sample_id')}）：范围 QC 未通过{flag_note}；"
                "核对两道次局部应变零点、2% 交点、温度与应变速率；原始结果不截断。"
            )
        if sensitivity_over_100:
            lines.append(
                "- " + "、".join(sensitivity_over_100)
                + "：5% 对照同样超过 100%，需同时核对 Hollomon 投影与曲线。"
            )
    else:
        lines.append("- 无待复核采集。")
    lines.append(
        "- 范围 QC 已通过但方法差至少 10 个百分点的采集："
        + ("、".join(case["large_method_difference_passed_ids"]) or "无") + "。"
    )
    if literature:
        lines.append(
            "- 用金相组织或其他独立证据验证回复与再结晶的贡献；"
            "论文的约 20% 回复、超过 90% 完全再结晶判据不直接移植到本批。"
        )
    else:
        lines.append(
            "- 用金相组织或其他独立证据验证回复与再结晶的贡献；任何文献判据不直接移植到本批。"
        )
    if synthetic_demo:
        lines += [
            "", "## 结论状态", "",
            "这是由固定合成输入生成的演示草稿：其中没有任何经人工复核的真实数据，"
            "没有已获批准的正式结果，也未运行 T75 曲线重算；"
            "一切内容待具名人工复核，且不构成科研结论，本包不进入正式证据库。", "",
        ]
    else:
        lines += [
            "", "## 结论状态", "",
            "这是由已复核数据生成的分析草稿。机制判断、论文表述及是否纳入正式科研结论仍需具名人工审核。", "",
        ]
    return "\n".join(lines)


def publish_softening_case(
    case: Mapping[str, Any], *, output_root: Path = CASE_ROOT, synthetic_demo: bool = False
) -> Path:
    """Publish a governed case package.

    The formal path (default) is unchanged: real approved inputs, ``real_research_data``
    classification, human-approved source wording. ``synthetic_demo=True`` is an EXPLICIT,
    default-off branch for the public demo (STEEL-V1-03B): it changes ONLY the governance
    classification and source wording - every source becomes ``synthetic_demo_data`` /
    ``synthetic_demo_input``, the Manifest is classified ``synthetic_demo_data``, the case itself
    is stamped ``evidence_class=synthetic_demo_data`` (which also switches the draft's demo
    marker on), and the caller must point ``output_root`` at a demo root (never the formal
    evidence library). Calculation, package format, staging, seal and append-only publication
    are shared with the formal path.

    A case that ALREADY declares ``evidence_class=synthetic_demo_data`` is refused in the
    default branch: when the explicit ``synthetic_demo=True`` opt-in is missing (omitted or
    ``False``), publication is rejected before any directory creation, staging or write -
    the caller must fix the call, the parameter is never silently corrected.
    """
    # Read the case's EXPLICIT classification before any byte is written: a pre-marked
    # synthetic case must never fall into the default real-research branch.
    if not synthetic_demo and str(case.get("evidence_class", "")) == "synthetic_demo_data":
        raise ValueError(
            "a case explicitly classified as synthetic_demo_data requires the explicit "
            "synthetic_demo=True opt-in; publication is refused before any write"
        )
    case_id = str(case["case_id"])
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError("invalid case ID")
    if synthetic_demo:
        case = dict(case)
        case["evidence_class"] = "synthetic_demo_data"
        # Refuse equality AND any location INSIDE the formal library (through "..", symlinks or
        # junctions - resolve() normalises all of them). This runs before any byte is written.
        case_root_resolved = CASE_ROOT.resolve()
        demo_root_resolved = output_root.resolve()
        if demo_root_resolved == case_root_resolved or demo_root_resolved.is_relative_to(case_root_resolved):
            raise ValueError("a synthetic demo package must not enter the formal evidence library")
    destination = output_root / case_id
    if destination.exists():
        if verify_package(destination).status != "passed":
            raise ValueError("existing case package failed verification")
        existing = json.loads((destination / "evidence.json").read_text(encoding="utf-8"))
        if existing != case:
            raise ValueError("existing case ID has different evidence")
        return destination
    stage = create_staging_directory(output_root, case_id)
    write_json_atomic(stage / "evidence.json", dict(case))
    (stage / "analysis_draft.md").write_text(_draft_markdown(case), encoding="utf-8")
    digests = case["source_digests"]
    identity = ResearchObjectIdentity.from_content(
        "thermal_softening_case", case_id, 1, case, "SteelAI thermal_softening_case"
    )
    if synthetic_demo:
        demo_class = EvidenceClass.SYNTHETIC_DEMO_DATA.value
        demo_status = "synthetic_demo_input"
        sources = (
            SourceReference("synthetic-runs", 1, digests["runs_sha256"], demo_class, demo_status),
            SourceReference("synthetic-points", 1, digests["points_sha256"], demo_class, demo_status),
            SourceReference("synthetic-features", 1, digests["features_sha256"], demo_class, demo_status),
            SourceReference("synthetic-formal-results", 1, digests["formal_results_sha256"], demo_class, demo_status),
            SourceReference("synthetic-literature-placeholder", 1, digests["literature_pdf_sha256"], demo_class, demo_status),
            SourceReference("synthetic-method", 1, digests["method_registry_sha256"], demo_class, demo_status),
        )
    else:
        sources = (
            SourceReference("approved-t71-runs", 1, digests["runs_sha256"],
                            EvidenceClass.REAL_RESEARCH_DATA, "human_approved",
                            "data/processed/thermal_simulation_runs.csv"),
            SourceReference("approved-t71-points", 1, digests["points_sha256"],
                            EvidenceClass.REAL_RESEARCH_DATA, "human_approved",
                            "data/processed/thermal_simulation_points.csv"),
            SourceReference("approved-t74-features", 1, digests["features_sha256"],
                            EvidenceClass.REAL_RESEARCH_DATA, "human_approved",
                            FEATURES_RELATIVE.as_posix()),
            SourceReference("approved-t75-results", 1, digests["formal_results_sha256"],
                            EvidenceClass.REAL_RESEARCH_DATA, "human_approved",
                            SOFTENING_RELATIVE.as_posix()),
            SourceReference("zhang-ling-2007-thesis", 1, digests["literature_pdf_sha256"],
                            EvidenceClass.REAL_RESEARCH_DATA, "literature_digest_verified"),
            SourceReference("approved-t75-method", 1, digests["method_registry_sha256"],
                            EvidenceClass.HUMAN_CONCLUSION, "method_approved",
                            REGISTRY_RELATIVE.as_posix()),
        )
    manifest = build_manifest(
        stage, publication_id=case_id, identity=identity,
        state=GovernanceState.NEEDS_HUMAN,
        result_level=ResultLevel.WORKING_CANDIDATE,
        evidence_class=(EvidenceClass.SYNTHETIC_DEMO_DATA if synthetic_demo
                        else EvidenceClass.REAL_RESEARCH_DATA),
        sources=sources, generated_by="SteelAI thermal_softening_case",
        metadata={"case_version": CASE_VERSION, "row_count": case["row_count"]},
    )
    seal_package(stage, manifest)
    publish_append_only(stage, destination)
    return destination


def load_softening_case(case_id: str, *, output_root: Path = CASE_ROOT) -> dict[str, Any]:
    """Return only a verified package's curated evidence; never accept arbitrary paths."""
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError("invalid case ID")
    directory = output_root / case_id
    manifest = load_verified_manifest(directory)
    if manifest.publication_id != case_id or manifest.state != GovernanceState.NEEDS_HUMAN.value:
        raise ValueError("case manifest is not the expected review candidate")
    evidence = json.loads((directory / "evidence.json").read_text(encoding="utf-8"))
    if evidence.get("case_id") != case_id:
        raise ValueError("case evidence identity differs from manifest")
    return evidence
