from __future__ import annotations

from typing import Any


def verified_portfolio_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Defense-in-depth filter: only complete, verified, human-accepted results."""
    return [
        dict(item)
        for item in results
        if item.get("portfolio_eligible") is True
        and item.get("state") == "complete"
        and item.get("integrity_status") == "passed"
        and str(item.get("reviewer_id", "")).strip()
    ]


def portfolio_markdown(results: list[dict[str, Any]]) -> str:
    accepted = verified_portfolio_results(results)
    modules = sorted({str(item.get("module", "未分类")) for item in accepted})
    lines = [
        "# SteelAI Workbench 求职展示摘要",
        "",
        "## 项目定位",
        "构建面向耐磨钢课题的本地科研 AI 工作台，将成分—工艺—组织—性能数据、经验物理公式、微观证据索引和结构化科研报告串成可追溯流程。",
        "",
        "## 已验收成果",
        f"- 当前纳入 {len(accepted)} 项完整性通过且已人工验收的成果。",
    ]
    if modules:
        lines.append(f"- 覆盖模块：{'、'.join(modules)}。")
    for item in accepted:
        scope = str(item.get("portfolio_reason", "已通过运行与成果中心过滤"))
        lines.append(f"- {item.get('title', item.get('task_id', '已验收成果'))}：{scope}。")
    if not accepted:
        lines.append("- 暂无符合条件的成果；中间结果不会用于作品集表述。")
    lines.extend([
        "",
        "## 简历要点（草稿）",
        "- 使用 Python + Streamlit 搭建多页材料科研工作台，统一管理样品、成分、工艺、组织、性能与证据路径。",
        "- 将 Ms、Ac1、Ac3、Tnr、Ceq、Pcm 经验公式封装为带来源、适用范围审查和 warning 的可测试 Physics Engine。",
        "- 设计“确定性计算 + GPT 报告层”架构，强制区分事实、判断、假设、决定和下一步，降低科研表述中的证据越界。",
        "- 建立统一运行与成果中心，让作品集只消费 complete、完整性通过且具名人工验收的结果。",
        "",
        "## STAR 素材",
        "- Situation：实验资料分散在表格、显微图片和既有脚本中，科研分析与求职展示之间缺少持续沉淀。",
        "- Task：在不迁移原始数据的前提下，构建轻量、可运行、可扩展的本地 AI 工作台。",
        "- Action：设计路径索引和 processed 数据层；封装经验公式与警告；实现结构化对比、报告与事件日志；保留离线降级能力。",
        "- Result：MVP 已形成从数据、治理、统计到受限解释和成果筛选的闭环；真实科研结论仍以人工复核为准。",
        "",
        "## 面试演示（3 分钟）",
        "1. Dashboard 展示课题数据完整度与最近里程碑。",
        "2. 选择 B/R 样品，演示成分—组织—性能对比与 Physics Engine warning。",
        "3. 打开统一运行与成果中心，证明待确认、阻断、失效与已验收结果不会混在一起。",
        "",
        "> 注意：以上为项目能力描述。涉及实验结论和量化效果时，只使用已核验的真实数据。",
    ])
    return "\n".join(lines) + "\n"
