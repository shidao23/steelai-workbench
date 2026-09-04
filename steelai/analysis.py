from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from steelai.data import numeric


@dataclass
class ResearchReport:
    title: str
    confirmed_facts: list[str] = field(default_factory=list)
    judgments: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    narrative: str = ""
    provider: str = "offline_rules"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    def to_markdown(self) -> str:
        sections = [f"# {self.title}", f"生成方式：{self.provider}"]
        mapping = [
            ("已确认事实", self.confirmed_facts),
            ("当前判断", self.judgments),
            ("待验证假设", self.hypotheses),
            ("已作决定", self.decisions),
            ("下一步行动", self.next_actions),
            ("局限与提醒", self.limitations),
        ]
        for heading, items in mapping:
            sections.append(f"## {heading}\n" + ("\n".join(f"- {x}" for x in items) if items else "- 暂无"))
        if self.narrative:
            sections.append("## 综合结论\n" + self.narrative)
        return "\n\n".join(sections) + "\n"


def _fmt_delta(label: str, a: dict, b: dict, key: str, unit: str) -> str | None:
    av, bv = numeric(a.get(key)), numeric(b.get(key))
    if av is None or bv is None:
        return None
    delta = bv - av
    pct = (delta / av * 100) if av else None
    pct_text = f"（{pct:+.1f}%）" if pct is not None else ""
    return f"{label}：对照样品 {av:g}{unit}，比较样品 {bv:g}{unit}，差值 {delta:+.3g}{unit}{pct_text}。"


def build_rule_report(a: dict[str, dict[str, str]], b: dict[str, dict[str, str]]) -> ResearchReport:
    aid = a["samples"].get("sample_id", "A")
    bid = b["samples"].get("sample_id", "B")
    report = ResearchReport(title=f"{aid} vs {bid} 结构化研究分析")
    if a["samples"].get("is_demo", "").lower() == "true" or b["samples"].get("is_demo", "").lower() == "true":
        report.limitations.append("包含 DEMO 数据；本报告仅用于验证工作流，不得作为论文或实验结论。")

    for label, table, key, unit in (
        ("屈服强度", "properties", "ys_mpa", " MPa"),
        ("抗拉强度", "properties", "uts_mpa", " MPa"),
        ("断后伸长率", "properties", "elongation_pct", "%"),
        ("−40 ℃冲击吸收功", "properties", "impact_minus40_j", " J"),
        ("PAG 尺寸", "microstructure", "pag_size_um", " μm"),
        ("HAGB 比例", "microstructure", "hagb_pct", "%"),
        ("KAM 均值", "microstructure", "kam_mean_deg", "°"),
    ):
        fact = _fmt_delta(label, a[table], b[table], key, unit)
        if fact:
            report.confirmed_facts.append(fact)

    impact_a = numeric(a["properties"].get("impact_minus40_j"))
    impact_b = numeric(b["properties"].get("impact_minus40_j"))
    ys_a = numeric(a["properties"].get("ys_mpa"))
    ys_b = numeric(b["properties"].get("ys_mpa"))
    if None not in (impact_a, impact_b, ys_a, ys_b) and impact_a:
        impact_drop = (impact_b - impact_a) / impact_a * 100
        ys_change = abs((ys_b - ys_a) / ys_a * 100) if ys_a else 0
        if impact_drop <= -10 and ys_change <= 5:
            report.judgments.append("强度接近而低温冲击明显下降，当前差异不能仅用宏观强度变化解释。")
            report.hypotheses.extend([
                "残余元素晶界偏析提高了脆性断裂倾向。",
                "夹杂/析出物数量、尺寸或界面特征发生变化。",
                "马氏体 packet/block 层级或大角度晶界分布影响裂纹扩展。",
            ])
            report.next_actions.extend([
                "核对两样品冲击试验重复数、离散性与断口取样位置。",
                "补充冲击断口 SEM，并登记解理、韧窝、二次裂纹和夹杂证据。",
                "补齐 EBSD 的 PAG/packet/block、HAGB、KAM/GND 参数后再判断组织机制。",
            ])
    if not report.judgments:
        report.judgments.append("现有字段只支持差异描述，尚不足以建立稳健机制链。")
    report.decisions.append("MVP 阶段保持机理驱动分析，不训练 XGBoost/DeepXDE。")
    report.limitations.append("经验公式输出应标记为 model estimate，并与热膨胀/热模拟实验值分列。")
    report.narrative = "；".join(report.judgments + report.hypotheses[:1])
    return report


def enrich_with_gpt(report: ResearchReport, evidence_payload: dict[str, Any]) -> ResearchReport:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return report
    try:
        from openai import OpenAI
    except ImportError:
        report.limitations.append("已检测到 API key，但未安装 openai 包；继续使用离线报告。")
        return report

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    prompt = {
        "task": "在不新增事实的前提下，将离线研究报告润色成中文科研分析。严格区分事实、判断、假设、决定和下一步。不得把相关性写成因果。",
        "offline_report": report.to_dict(),
        "selected_structured_evidence": evidence_payload,
        "output": "Markdown，保留六个同名小节，最后给出不超过120字的综合结论。",
    }
    try:
        response = client.responses.create(
            model=model,
            instructions="你是材料科研报告编辑。只能重组提供的证据，禁止虚构数值、文献或观察。",
            input=json.dumps(prompt, ensure_ascii=False),
        )
        text = response.output_text.strip()
        if text:
            report.narrative = text
            report.provider = f"openai_responses:{model}"
    except Exception as exc:  # App must remain usable offline.
        report.limitations.append(f"GPT 调用失败，已保留离线报告：{type(exc).__name__}")
    return report
