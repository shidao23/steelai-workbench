from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from steelai.automation import AUTODIMPLE_RESULT_ROOT
from steelai.data import numeric, sample_bundle
from steelai.ebsd import read_highres_comparison, read_matched_comparison


EVIDENCE_LEVELS = {
    "L0": "经验公式、模型估算或未经实验校正的计算结果",
    "L1": "单次测量、单视场观察或仅由研究笔记核对的数据",
    "L2": "同条件重复测量或多视场方向一致，但独立性仍有限",
    "L3": "独立试样重复和适当统计分析支持",
    "L4": "独立重复且由多种表征方法相互印证",
    "NA": "当前没有可用证据",
}


@dataclass
class EvidenceItem:
    evidence_id: str
    domain: str
    title: str
    level: str
    status: str
    scope: str
    summary: str
    source_locator: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    def agent_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "domain": self.domain,
            "title": self.title,
            "level": self.level,
            "status": self.status,
            "scope": self.scope,
            "summary": self.summary,
            "limitations": self.limitations,
        }


@dataclass
class ClaimAssessment:
    claim_id: str
    claim: str
    status: str
    evidence_level: str
    evidence_ids: list[str]
    allowed_wording: str
    prohibited_wording: str
    evidence_gap: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _load_json(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _delta_percent(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100


def _metric(comparison: dict[str, Any], name: str) -> dict[str, Any]:
    for row in comparison.get("metrics", []):
        if row.get("metric") == name:
            return row
    return {}


def _interval_crosses_zero(metric: dict[str, Any]) -> bool:
    interval = metric.get("bootstrap_mean_difference", {})
    low = numeric(interval.get("ci95_low"))
    high = numeric(interval.get("ci95_high"))
    return low is not None and high is not None and low <= 0 <= high


def _format_direction(value: float | None) -> str:
    if value is None:
        return "不可计算"
    return f"R相对B为{value:+.1f}%"


def build_evidence_registry(
    low_ebsd: dict[str, Any] | None = None,
    high_ebsd: dict[str, Any] | None = None,
    autodimple: dict[str, Any] | None = None,
) -> list[EvidenceItem]:
    b = sample_bundle("B-DQ")
    r = sample_bundle("R-DQ")
    low = read_matched_comparison() if low_ebsd is None else low_ebsd
    high = read_highres_comparison() if high_ebsd is None else high_ebsd
    if autodimple is None:
        autodimple = _load_json(AUTODIMPLE_RESULT_ROOT / "br_comparison_v0.1.json")

    b_props, r_props = b.get("properties", {}), r.get("properties", {})
    replicates = min(
        int(numeric(b_props.get("replicates")) or 0),
        int(numeric(r_props.get("replicates")) or 0),
    )
    impact_change = _delta_percent(
        numeric(b_props.get("impact_minus40_j")),
        numeric(r_props.get("impact_minus40_j")),
    )
    ys_change = _delta_percent(numeric(b_props.get("ys_mpa")), numeric(r_props.get("ys_mpa")))
    uts_change = _delta_percent(numeric(b_props.get("uts_mpa")), numeric(r_props.get("uts_mpa")))

    items = [
        EvidenceItem(
            "E-CHEM-001",
            "composition",
            "B/R化学成分摘要",
            "L1",
            "available_with_provenance_caveat",
            "B-DQ与R-DQ processed成分表",
            "成分差异已结构化，但当前状态仍为verified_from_source_note。",
            "data/processed/composition.csv",
            ["尚未在本工作台内对照原始直读仪器记录再次核验。"],
        ),
        EvidenceItem(
            "E-MECH-001",
            "mechanical",
            "B/R力学性能摘要",
            "L2" if replicates >= 3 else "L1",
            "available_with_independence_caveat",
            f"报告重复数n={replicates}；独立试样关系尚未登记",
            f"{_format_direction(ys_change)}（YS），{_format_direction(uts_change)}（UTS），{_format_direction(impact_change)}（−40℃冲击功）。",
            "data/processed/properties.csv",
            [
                "均值和样本标准差可用，但重复试样ID、原始记录和独立性未进入数据模型。",
                "不得据此直接写成统计显著或因果结论。",
            ],
        ),
        EvidenceItem(
            "E-PHYS-001",
            "physics",
            "Physics Engine经验估算",
            "L0",
            "available_model_estimate",
            "B-DQ与R-DQ成分驱动的Ms/Ac1/Ac3/Tnr/Ceq/Pcm",
            "结果用于形成可检验预期，不是实验真值。",
            "steelai/physics.py and WearSteel-AI v0.1 adapter",
            ["需用热膨胀、热模拟或文献适用范围复核。"],
        ),
    ]

    for evidence_id, title, group, comparison in (
        ("E-EBSD-LOW-001", "低分辨率B/R EBSD", "约1000×/0.5 μm，每条件1视场", low),
        ("E-EBSD-HIGH-001", "高分辨率B/R EBSD", "约2000×/0.15 μm，每条件1视场", high),
    ):
        available = bool(comparison and comparison.get("status") == "completed")
        items.append(EvidenceItem(
            evidence_id,
            "ebsd",
            title,
            "L1" if available else "NA",
            "available_directional_only" if available else "missing",
            group,
            "采集参数匹配，可做同尺度场级方向性比较。" if available else "尚无完成的标准化比较结果。",
            f"outputs/ebsd/{'low' if 'LOW' in evidence_id else 'high'}_resolution_comparison",
            [
                "每个条件仅1个视场，不能外推为独立试样结论。",
                "3° BCC取向晶粒不等于block、packet或原奥氏体晶粒。",
                "FCC索引比例不等于已验证的残余奥氏体含量。",
            ],
        ))

    image_counts = autodimple.get("n_images", {}) if autodimple else {}
    n_b, n_r = int(image_counts.get("B", 0)), int(image_counts.get("R", 0))
    items.append(EvidenceItem(
        "E-SEM-001",
        "sem",
        "AutoDimple B/R断口摘要",
        "L2" if n_b >= 2 and n_r >= 2 else ("L1" if n_b and n_r else "NA"),
        "available_descriptive_only" if n_b and n_r else "missing",
        f"B={n_b}张、R={n_r}张1000×图像；图像级比较",
        "分割对象为描述性单位，Bootstrap以图像为单位。" if n_b and n_r else "尚无完成的B/R批量结果。",
        "outputs/model_lab/auto_dimple/BR10_1000x_v0.1",
        [
            "图像和分割对象不是独立试样重复。",
            "当前主要指标的图像级Bootstrap 95%区间均跨零。",
        ],
    ))
    items.append(EvidenceItem(
        "E-XRD-001",
        "xrd",
        "XRD相分析",
        "NA",
        "not_integrated",
        "B/R XRD证据",
        "当前工作台尚未接入可追溯XRD结构化结果。",
        "not_integrated",
        ["不能用EBSD FCC索引替代XRD或其他残余奥氏体验证。"],
    ))
    return items


def build_claim_register(
    low_ebsd: dict[str, Any] | None = None,
    high_ebsd: dict[str, Any] | None = None,
    autodimple: dict[str, Any] | None = None,
) -> list[ClaimAssessment]:
    low = read_matched_comparison() if low_ebsd is None else low_ebsd
    high = read_highres_comparison() if high_ebsd is None else high_ebsd
    if autodimple is None:
        autodimple = _load_json(AUTODIMPLE_RESULT_ROOT / "br_comparison_v0.1.json")
    b, r = sample_bundle("B-DQ"), sample_bundle("R-DQ")
    bp, rp = b.get("properties", {}), r.get("properties", {})

    ys_pct = _delta_percent(numeric(bp.get("ys_mpa")), numeric(rp.get("ys_mpa")))
    uts_pct = _delta_percent(numeric(bp.get("uts_mpa")), numeric(rp.get("uts_mpa")))
    impact_pct = _delta_percent(numeric(bp.get("impact_minus40_j")), numeric(rp.get("impact_minus40_j")))

    claims = [
        ClaimAssessment(
            "C-MECH-001",
            "B-DQ与R-DQ的报告强度均值接近",
            "supported_with_caveat",
            "L2",
            ["E-MECH-001"],
            f"processed摘要中R相对B的YS为{ys_pct:+.1f}%、UTS为{uts_pct:+.1f}%，报告重复数为3。",
            "两钢强度无显著差异，或两钢强度完全相同。",
            "缺少重复试样ID、独立性登记和原始记录级统计复核。",
            "登记每个拉伸试样ID并复核原始结果后再做统计检验。",
        ),
        ClaimAssessment(
            "C-MECH-002",
            "R-DQ的报告−40℃冲击功均值低于B-DQ",
            "supported_with_caveat",
            "L2",
            ["E-MECH-001"],
            f"processed摘要中R相对B的−40℃冲击功为{impact_pct:+.1f}%，可描述为报告均值下降。",
            "残余元素导致冲击韧性下降，或差异已经统计显著。",
            "缺少冲击试样ID、独立性、原始值与正式推断统计。",
            "补齐独立冲击试样级数据，并将断口和组织证据与对应试样关联。",
        ),
        ClaimAssessment(
            "C-MECH-003",
            "残余元素导致R-DQ韧性下降",
            "hypothesis_only",
            "L1",
            ["E-CHEM-001", "E-MECH-001"],
            "两钢同时存在成分和冲击均值差异，可提出残余元素作用假设。",
            "现有数据证明了残余元素的因果作用。",
            "只有B/R两状态，成分变化共线，且缺少机制表征与干预对照。",
            "通过偏析、夹杂/析出物、断裂路径及独立重复建立机制证据链。",
        ),
        ClaimAssessment(
            "C-PHYS-001",
            "经验物理公式能够解释B/R韧性机制",
            "not_supported",
            "L0",
            ["E-PHYS-001", "E-MECH-001"],
            "Physics Card只能比较经验估算是否给出明显的相变或淬透性差异。",
            "经验Ms/Tnr/Ceq/Pcm结果证明了韧性差异机制。",
            "模型未由本课题实验值校正，且这些公式不直接描述断裂韧性。",
            "补充Ms/Ac1/Ac3/Tnr实验值并分析模型偏差。",
        ),
    ]

    low_grain = _metric(low, "median_equivalent_diameter_um_interior")
    high_grain = _metric(high, "median_equivalent_diameter_um_interior")
    low_kam = _metric(low, "median_kam_deg")
    high_kam = _metric(high, "median_kam_deg")
    low_hagb = _metric(low, "hagb_length_fraction_percent")
    high_hagb = _metric(high, "hagb_length_fraction_percent")
    both_ebsd = bool(low_grain and high_grain)
    grain_same_direction = both_ebsd and low_grain.get("R_minus_B", 0) * high_grain.get("R_minus_B", 0) > 0
    kam_same_direction = bool(low_kam and high_kam) and low_kam.get("R_minus_B", 0) * high_kam.get("R_minus_B", 0) > 0
    hagb_same_direction = bool(low_hagb and high_hagb) and low_hagb.get("R_minus_B", 0) * high_hagb.get("R_minus_B", 0) > 0

    claims.extend([
        ClaimAssessment(
            "C-EBSD-001",
            "R-DQ的BCC取向晶粒中位等效直径在两个尺度均高于B-DQ",
            "directionally_consistent" if grain_same_direction else "unresolved",
            "L2" if grain_same_direction else "L1",
            ["E-EBSD-LOW-001", "E-EBSD-HIGH-001"],
            "两个独立采集尺度可分别报告方向；不得合并数值。" if grain_same_direction else "当前两个尺度未形成一致方向。",
            "R-DQ马氏体block/packet已经显著粗化。",
            "每尺度每条件仅1个视场，且3°取向晶粒不是马氏体层级单元。",
            "增加匹配视场和独立试样，并开展父相/packet/block重构。",
        ),
        ClaimAssessment(
            "C-EBSD-002",
            "B/R KAM差异具有稳定方向",
            "directionally_consistent" if kam_same_direction else "conflicting_evidence",
            "L2" if kam_same_direction else "L1",
            ["E-EBSD-LOW-001", "E-EBSD-HIGH-001"],
            "分别报告两个尺度的KAM方向，并明确当前是否一致。",
            "R-DQ位错密度确定更高或更低。",
            "两个尺度方向不一致，且KAM不能未经校准直接等同GND。" if not kam_same_direction else "仍缺少独立视场与KAM-GND校准。",
            "在匹配步长、参数和多视场条件下复核KAM，并与GND方法交叉验证。",
        ),
        ClaimAssessment(
            "C-EBSD-003",
            "R-DQ的HAGB长度占比在两个尺度均略高",
            "directionally_consistent" if hagb_same_direction else "unresolved",
            "L2" if hagb_same_direction else "L1",
            ["E-EBSD-LOW-001", "E-EBSD-HIGH-001"],
            "可描述两个尺度的场级方向一致，但效应较小。" if hagb_same_direction else "当前证据不足以给出一致方向。",
            "R-DQ具有显著更多HAGB，因此韧性必然更好或更差。",
            "每条件视场数有限，且尚未建立HAGB与裂纹路径的对应关系。",
            "增加视场并将边界类型与断裂路径或有效晶粒尺寸关联。",
        ),
        ClaimAssessment(
            "C-EBSD-004",
            "EBSD FCC索引比例代表真实残余奥氏体含量",
            "not_supported",
            "L1" if low or high else "NA",
            ["E-EBSD-LOW-001", "E-EBSD-HIGH-001", "E-XRD-001"],
            "只能报告在当前索引设置下的FCC indexed-point fraction。",
            "已通过EBSD证明残余奥氏体含量及其B/R差异。",
            "缺少XRD或其他相验证，且索引比例可能受花样质量和相库影响。",
            "接入XRD定量并检查EBSD相索引置信度。",
        ),
    ])

    auto_metrics = autodimple.get("metrics", {}) if autodimple else {}
    key_auto = [
        auto_metrics.get("estimated_true_candidates", {}),
        auto_metrics.get("candidate_coverage_percent", {}),
        auto_metrics.get("median_equivalent_diameter_um", {}),
    ]
    intervals_available = all(metric.get("bootstrap_mean_difference") for metric in key_auto)
    all_cross_zero = intervals_available and all(_interval_crosses_zero(metric) for metric in key_auto)
    claims.append(ClaimAssessment(
        "C-SEM-001",
        "B/R AutoDimple断口形貌存在稳健差异",
        "not_confirmed" if all_cross_zero else ("unresolved" if auto_metrics else "missing"),
        "L2" if auto_metrics else "NA",
        ["E-SEM-001"],
        "可报告图像级均值方向，并明确主要Bootstrap 95%区间是否跨零。",
        "AutoDimple已经证明B/R真实韧窝尺寸或数量存在显著差异。",
        "当前主要图像级区间跨零；自动候选也不等同于人工确认的全部真实韧窝。",
        "增加独立断口试样、统一取样位置，并用盲法小样本复核自动结果。",
    ))
    return claims


VALIDATION_GATES = [
    {
        "gate": "G1 原始真值边界",
        "rule": "研究笔记或processed摘要不得自动升级为原始仪器真值。",
        "status": "enforced",
    },
    {
        "gate": "G2 重复独立性",
        "rule": "未登记独立试样ID时，不输出统计显著性或样品总体推断。",
        "status": "enforced",
    },
    {
        "gate": "G3 图像伪重复",
        "rule": "视场和分割对象只作描述性单位，不作为独立试样重复。",
        "status": "enforced",
    },
    {
        "gate": "G4 EBSD尺度隔离",
        "rule": "1000×/0.5 μm与2000×/0.15 μm分别报告，不合并数值。",
        "status": "enforced",
    },
    {
        "gate": "G5 模型估算",
        "rule": "Physics结果始终标记为经验估算，不能替代实验值。",
        "status": "enforced",
    },
    {
        "gate": "G6 因果结论",
        "rule": "证据低于L3且缺少干预/机制验证时，只允许提出假设。",
        "status": "enforced",
    },
]


def validation_summary(
    low_ebsd: dict[str, Any] | None = None,
    high_ebsd: dict[str, Any] | None = None,
    autodimple: dict[str, Any] | None = None,
    *,
    statistics_package=None,
) -> dict[str, Any]:
    evidence = build_evidence_registry(low_ebsd, high_ebsd, autodimple)
    claims = build_claim_register(low_ebsd, high_ebsd, autodimple)
    governed_statistics = None
    if statistics_package is not None:
        from steelai.statistics_governance import inspect_governed_statistics

        inspected = inspect_governed_statistics(statistics_package)
        if inspected.get("status") == "passed":
            registry = inspected["registry"]
            policy = inspected["statement_policy"]
            governed_statistics = {
                "governance_id": inspected["governance_id"],
                "analysis_id": inspected["analysis_id"],
                "governance_state": inspected["governance_state"],
                "quality_status": inspected["quality_status"],
                "evidence_class": inspected["evidence_class"],
                "evidence_level": inspected["evidence_level"],
                "statistical_unit_type": registry["statistical_unit_type"],
                "counts": registry["counts"],
                "source": registry["source"],
                "statement_policy": policy,
            }
            mechanical = next(
                (item for item in evidence if item.evidence_id == "E-MECH-001"),
                None,
            )
            if mechanical is not None:
                mechanical.level = policy["evidence_level"]
                mechanical.status = "governed_statistics_complete"
                mechanical.scope = (
                    f"{registry['counts']['statistical_units']}个登记统计单位，"
                    f"{registry['counts']['observations']}条观测，"
                    f"{registry['counts']['groups']}个描述统计组"
                )
                mechanical.summary = (
                    f"治理统计结果 {inspected['governance_id']} 已通过完整性复核；"
                    "允许报告描述统计，不包含显著性检验或因果判断。"
                )
                mechanical.source_locator = "governed_statistics/" + inspected["governance_id"]
                mechanical.limitations = list(policy["cautious_statements"])
    level_counts = Counter(item.level for item in evidence)
    status_counts = Counter(item.status for item in claims)
    return {
        "schema_version": "1.0",
        "case_id": "BR-DQ-evidence-case-v0.1",
        "research_scope": "B-DQ versus R-DQ only; experiments 1-14 excluded by decision",
        "overall_readiness": "directional_evidence_only",
        "causal_inference_ready": False,
        "machine_learning_ready": False,
        "portfolio_case_ready": True,
        "evidence_count": len(evidence),
        "claim_count": len(claims),
        "evidence_level_counts": dict(level_counts),
        "claim_status_counts": dict(status_counts),
        "evidence": [item.to_dict() for item in evidence],
        "claims": [item.to_dict() for item in claims],
        "validation_gates": VALIDATION_GATES,
        "governed_statistics": governed_statistics,
    }


def agent_validation_payload() -> dict[str, Any]:
    summary = validation_summary()
    return {
        "schema_version": summary["schema_version"],
        "case_id": summary["case_id"],
        "research_scope": summary["research_scope"],
        "overall_readiness": summary["overall_readiness"],
        "causal_inference_ready": summary["causal_inference_ready"],
        "machine_learning_ready": summary["machine_learning_ready"],
        "evidence": [
            EvidenceItem(**item).agent_dict()
            for item in summary["evidence"]
        ],
        "claims": summary["claims"],
        "validation_gates": summary["validation_gates"],
        "privacy_boundary": "No raw images, CTF/TIF, file paths, or thesis text are included.",
    }


def validation_report_markdown(summary: dict[str, Any] | None = None) -> str:
    data = summary or validation_summary()
    lines = [
        "# B-DQ / R-DQ Evidence & Validation Report",
        "",
        f"- Case ID: `{data['case_id']}`",
        f"- Overall readiness: `{data['overall_readiness']}`",
        f"- Causal inference ready: `{data['causal_inference_ready']}`",
        f"- Machine learning ready: `{data['machine_learning_ready']}`",
        "- Experiments 1-14: excluded from the current core evidence set by decision",
        "",
        "## Evidence Registry",
        "",
    ]
    for item in data["evidence"]:
        lines.extend([
            f"### {item['evidence_id']} · {item['title']} [{item['level']}]",
            f"- Status: `{item['status']}`",
            f"- Scope: {item['scope']}",
            f"- Summary: {item['summary']}",
            "- Limitations: " + "；".join(item["limitations"]),
            "",
        ])
    governed = data.get("governed_statistics")
    if governed:
        policy = governed["statement_policy"]
        lines.extend([
            "## Governed Statistical Evidence",
            "",
            f"- Governance ID: `{governed['governance_id']}`",
            f"- Analysis ID: `{governed['analysis_id']}`",
            f"- State / QC / level: `{governed['governance_state']}` / `{governed['quality_status']}` / `{governed['evidence_level']}`",
            "- Allowed wording: " + "；".join(policy["allowed_statements"]),
            "- Cautious wording: " + "；".join(policy["cautious_statements"]),
            "- Prohibited wording: " + "；".join(policy["prohibited_statements"]),
            "",
        ])
    lines.extend(["## Claim Validation Matrix", ""])
    for claim in data["claims"]:
        lines.extend([
            f"### {claim['claim_id']} · {claim['claim']}",
            f"- Status / level: `{claim['status']}` / `{claim['evidence_level']}`",
            f"- Evidence: {', '.join(claim['evidence_ids'])}",
            f"- Allowed wording: {claim['allowed_wording']}",
            f"- Prohibited wording: {claim['prohibited_wording']}",
            f"- Evidence gap: {claim['evidence_gap']}",
            f"- Next action: {claim['next_action']}",
            "",
        ])
    lines.extend(["## Validation Gates", ""])
    lines.extend(f"- **{gate['gate']}**: {gate['rule']} (`{gate['status']}`)" for gate in data["validation_gates"])
    return "\n".join(lines) + "\n"
