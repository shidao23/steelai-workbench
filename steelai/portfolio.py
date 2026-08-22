from __future__ import annotations

from collections import Counter
from typing import Any


def portfolio_markdown(events: list[dict[str, Any]]) -> str:
    counts = Counter(event.get("event_type", "unknown") for event in events)
    lines = [
        "# SteelAI Workbench 求职展示摘要",
        "",
        "## 项目定位",
        "构建面向耐磨钢课题的本地科研 AI 工作台，将成分—工艺—组织—性能数据、经验物理公式、微观证据索引和结构化科研报告串成可追溯流程。",
        "",
        "## 可量化进展",
        f"- 已沉淀 {len(events)} 条可追溯事件。",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## 简历要点（草稿）",
        "- 使用 Python + Streamlit 搭建多页材料科研工作台，统一管理样品、成分、工艺、组织、性能与证据路径。",
        "- 将 Ms、Ac1、Ac3、Tnr、Ceq、Pcm 经验公式封装为带来源、适用范围审查和 warning 的可测试 Physics Engine。",
        "- 设计“确定性计算 + GPT 报告层”架构，强制区分事实、判断、假设、决定和下一步，降低科研表述中的证据越界。",
        "- 建立 project log 与自动作品集管线，将每次数据接入、分析和模型迭代转化为可追溯求职素材。",
        "",
        "## STAR 素材",
        "- Situation：实验资料分散在表格、显微图片和既有脚本中，科研分析与求职展示之间缺少持续沉淀。",
        "- Task：在不迁移原始数据的前提下，构建轻量、可运行、可扩展的本地 AI 工作台。",
        "- Action：设计路径索引和 processed 数据层；封装经验公式与警告；实现结构化对比、报告与事件日志；保留离线降级能力。",
        "- Result：MVP 已形成从数据/证据到科研结论和求职材料的闭环；真实结果需在接入实验资料后更新。",
        "",
        "## 面试演示（3 分钟）",
        "1. Dashboard 展示课题数据完整度与最近里程碑。",
        "2. 选择 B/R 样品，演示成分—组织—性能对比与 Physics Engine warning。",
        "3. 生成结构化研究报告，同时在 Career Portfolio 中看到事件转化为简历与 STAR 素材。",
        "",
        "> 注意：以上为项目能力描述。涉及实验结论和量化效果时，只使用已核验的真实数据。",
    ])
    return "\n".join(lines) + "\n"
