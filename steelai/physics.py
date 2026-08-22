from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from typing import Callable


NumberMap = dict[str, float]


@dataclass(frozen=True)
class PhysicsResult:
    key: str
    label: str
    value: float | None
    unit: str
    formula: str
    source: str
    review_status: str
    warnings: tuple[str, ...]
    note: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["warnings"] = list(self.warnings)
        return result


@dataclass(frozen=True)
class FormulaSpec:
    key: str
    label: str
    unit: str
    equation: str
    source: str
    required: tuple[str, ...]
    guardrails: dict[str, tuple[float, float]]
    calculator: Callable[[NumberMap], float]
    note: str
    review_status: str = "provisional_review_required"


def _v(c: NumberMap, key: str) -> float:
    return float(c.get(key, 0.0))


SPECS = (
    FormulaSpec(
        "Ms", "Ms（马氏体开始温度）", "°C",
        "539 − 423C − 30.4Mn − 17.7Ni − 12.1Cr − 7.5Mo",
        "K. W. Andrews, Journal of the Iron and Steel Institute 203 (1965) 721–727",
        ("C", "Mn", "Ni", "Cr", "Mo"),
        {"C": (0.0, 0.6), "Mn": (0.0, 2.0), "Ni": (0.0, 4.0), "Cr": (0.0, 3.0), "Mo": (0.0, 1.0)},
        lambda c: 539 - 423*_v(c,"C") - 30.4*_v(c,"Mn") - 17.7*_v(c,"Ni") - 12.1*_v(c,"Cr") - 7.5*_v(c,"Mo"),
        "Andrews 线性经验式；需与原 WearSteel-AI v0.1 及原文版本核对。",
    ),
    FormulaSpec(
        "Ac1", "Ac1（加热时奥氏体化开始温度）", "°C",
        "723 − 10.7Mn − 16.9Ni + 29.1Si + 16.9Cr + 290As + 6.38W",
        "K. W. Andrews, Journal of the Iron and Steel Institute 203 (1965) 721–727",
        ("Mn", "Ni", "Si", "Cr", "As", "W"),
        {"Mn": (0.0, 2.0), "Ni": (0.0, 4.0), "Si": (0.0, 1.5), "Cr": (0.0, 3.0), "As": (0.0, 0.2), "W": (0.0, 1.0)},
        lambda c: 723 - 10.7*_v(c,"Mn") - 16.9*_v(c,"Ni") + 29.1*_v(c,"Si") + 16.9*_v(c,"Cr") + 290*_v(c,"As") + 6.38*_v(c,"W"),
        "经验估算；残余元素项与热膨胀实测值应分开保存。",
    ),
    FormulaSpec(
        "Ac3", "Ac3（加热时奥氏体化完成温度）", "°C",
        "910 − 203√C − 15.2Ni + 44.7Si + 104V + 31.5Mo + 13.1W",
        "K. W. Andrews, Journal of the Iron and Steel Institute 203 (1965) 721–727",
        ("C", "Ni", "Si", "V", "Mo", "W"),
        {"C": (0.0, 0.6), "Ni": (0.0, 4.0), "Si": (0.0, 1.5), "V": (0.0, 0.5), "Mo": (0.0, 1.0), "W": (0.0, 1.0)},
        lambda c: 910 - 203*sqrt(max(_v(c,"C"), 0)) - 15.2*_v(c,"Ni") + 44.7*_v(c,"Si") + 104*_v(c,"V") + 31.5*_v(c,"Mo") + 13.1*_v(c,"W"),
        "经验估算；请核对原项目是否采用同一 Andrews 版本。",
    ),
    FormulaSpec(
        "Tnr", "Tnr（再结晶停止温度）", "°C",
        "887 + 464C + (6445Nb − 644√Nb) + (732V − 230√V) + 890Ti + 363Al − 357Si",
        "Boratto et al., THERMEC-88 conference proceedings (1988), commonly cited empirical relation",
        ("C", "Nb", "V", "Ti", "Al", "Si"),
        {"C": (0.02, 0.25), "Nb": (0.0, 0.12), "V": (0.0, 0.15), "Ti": (0.0, 0.06), "Al": (0.0, 0.10), "Si": (0.0, 0.6)},
        lambda c: 887 + 464*_v(c,"C") + 6445*_v(c,"Nb") - 644*sqrt(max(_v(c,"Nb"),0)) + 732*_v(c,"V") - 230*sqrt(max(_v(c,"V"),0)) + 890*_v(c,"Ti") + 363*_v(c,"Al") - 357*_v(c,"Si"),
        "对成分与工艺历史敏感，仅作筛查；护栏范围为项目审查范围。",
    ),
    FormulaSpec(
        "Ceq", "Ceq（IIW 碳当量）", "wt.%",
        "C + Mn/6 + (Cr + Mo + V)/5 + (Ni + Cu)/15",
        "International Institute of Welding (IIW) carbon-equivalent relation",
        ("C", "Mn", "Cr", "Mo", "V", "Ni", "Cu"),
        {"C": (0.0, 0.6), "Mn": (0.0, 2.0)},
        lambda c: _v(c,"C") + _v(c,"Mn")/6 + (_v(c,"Cr")+_v(c,"Mo")+_v(c,"V"))/5 + (_v(c,"Ni")+_v(c,"Cu"))/15,
        "用于焊接性/淬硬倾向筛查，不直接等于组织或韧性。",
    ),
    FormulaSpec(
        "Pcm", "Pcm（冷裂纹敏感性组成指标）", "wt.%",
        "C + Si/30 + (Mn + Cu + Cr)/20 + Ni/60 + Mo/15 + V/10 + 5B",
        "Ito–Bessyo cold-cracking susceptibility composition parameter",
        ("C", "Si", "Mn", "Cu", "Cr", "Ni", "Mo", "V", "B"),
        {"C": (0.0, 0.25), "B": (0.0, 0.01)},
        lambda c: _v(c,"C") + _v(c,"Si")/30 + (_v(c,"Mn")+_v(c,"Cu")+_v(c,"Cr"))/20 + _v(c,"Ni")/60 + _v(c,"Mo")/15 + _v(c,"V")/10 + 5*_v(c,"B"),
        "更常用于低碳钢焊接冷裂纹敏感性筛查。",
    ),
)


def calculate_all(composition: NumberMap, provided_fields: set[str] | None = None) -> list[PhysicsResult]:
    provided = provided_fields if provided_fields is not None else set(composition)
    results: list[PhysicsResult] = []
    for spec in SPECS:
        warnings: list[str] = []
        missing = [key for key in spec.required if key not in provided]
        if missing:
            warnings.append("缺少成分字段，当前按 0 计算: " + ", ".join(missing))
        for key, (low, high) in spec.guardrails.items():
            if key in provided:
                value = _v(composition, key)
                if value < low or value > high:
                    warnings.append(f"{key}={value:g} 超出工作台审查范围 [{low:g}, {high:g}]")
        value = spec.calculator(composition)
        results.append(PhysicsResult(
            spec.key, spec.label, round(value, 3), spec.unit, spec.equation,
            spec.source, spec.review_status, tuple(warnings), spec.note,
        ))
    return results


def specs_as_rows() -> list[dict]:
    return [{
        "key": s.key,
        "label": s.label,
        "formula": s.equation,
        "unit": s.unit,
        "source": s.source,
        "review_status": s.review_status,
        "note": s.note,
    } for s in SPECS]
