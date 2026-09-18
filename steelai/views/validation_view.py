from __future__ import annotations

import pandas as pd
import streamlit as st

from steelai.event_log import record_event, safe_output_filename, write_text_artifact
from steelai.evidence_validation import (
    EVIDENCE_LEVELS,
    validation_report_markdown,
    validation_summary,
)
from steelai.paths import REPORTS
from steelai.statistics_governance import latest_governed_statistics_status
from steelai.ui import next_step_buttons, setup_page


setup_page(st, "SteelAI Workbench · 证据与验证中心", "🧩")
st.caption("围绕B-DQ/R-DQ建立证据等级、结论门控与缺口清单；1–14号实验不进入当前核心证据集。")

statistics_status = latest_governed_statistics_status()
statistics_package = (
    statistics_status["package"]
    if statistics_status is not None and statistics_status["status"] == "passed"
    else None
)
summary = validation_summary(statistics_package=statistics_package)
evidence = pd.DataFrame(summary["evidence"])
claims = pd.DataFrame(summary["claims"])

a, b, c, d = st.columns(4)
a.metric("证据项", summary["evidence_count"])
b.metric("待审查结论", summary["claim_count"])
c.metric("总体就绪度", "方向性证据")
d.metric("因果推断", "未就绪")

st.warning(
    "当前B/R案例可以用于方向性研究分析和可审计求职案例；不支持因果结论，也不具备机器学习训练条件。"
)

st.subheader("可追溯统计证据")
if statistics_status is None:
    st.info("尚无 T53 治理统计包。请先在“分析与报告 → 可追溯统计”完成人工审核和报告生成。")
elif statistics_status["status"] != "passed":
    st.error("最新统计包完整性复核失败，已标记为 invalidated，不会进入证据表述。")
    for problem in statistics_status["problems"]:
        st.write("- " + problem)
else:
    policy = statistics_status["statement_policy"]
    s1, s2, s3 = st.columns(3)
    s1.metric("治理状态", statistics_status["governance_state"])
    s2.metric("证据等级", statistics_status["evidence_level"])
    s3.metric("统计 QC", statistics_status["quality_status"])
    with st.expander("查看统计表述规则", expanded=False):
        st.markdown("**允许表述**")
        for item in policy["allowed_statements"]:
            st.write("- " + item)
        st.markdown("**谨慎表述**")
        for item in policy["cautious_statements"]:
            st.write("- " + item)
        st.markdown("**禁止表述**")
        for item in policy["prohibited_statements"]:
            st.write("- " + item)

st.subheader("证据等级标准")
level_rows = [{"level": level, "definition": definition} for level, definition in EVIDENCE_LEVELS.items()]
st.dataframe(pd.DataFrame(level_rows), hide_index=True, width="stretch")

st.subheader("B/R证据注册表")
display_evidence = evidence[[
    "evidence_id", "domain", "title", "level", "status", "scope", "summary"
]].copy()
st.dataframe(display_evidence, hide_index=True, width="stretch")

selected_evidence = st.selectbox(
    "查看证据边界",
    evidence["evidence_id"].tolist(),
    format_func=lambda value: f"{value} · {evidence.loc[evidence['evidence_id'] == value, 'title'].iloc[0]}",
)
selected_row = evidence.loc[evidence["evidence_id"] == selected_evidence].iloc[0]
left, right = st.columns(2)
left.markdown(f"**本地来源登记**：`{selected_row['source_locator']}`")
left.markdown(f"**适用范围**：{selected_row['scope']}")
right.markdown("**限制**")
for item in selected_row["limitations"]:
    right.markdown(f"- {item}")

st.subheader("结论验证矩阵")
status_labels = {
    "supported_with_caveat": "有条件支持",
    "directionally_consistent": "方向一致",
    "hypothesis_only": "仅假设",
    "not_supported": "不支持",
    "not_confirmed": "尚未确认",
    "conflicting_evidence": "证据冲突",
    "unresolved": "未解决",
    "missing": "缺失",
}
claim_table = claims.copy()
claim_table["status_cn"] = claim_table["status"].map(status_labels).fillna(claim_table["status"])
claim_table["evidence_ids"] = claim_table["evidence_ids"].apply(lambda values: ", ".join(values))
st.dataframe(
    claim_table[["claim_id", "claim", "status_cn", "evidence_level", "evidence_ids"]],
    hide_index=True,
    width="stretch",
)

selected_claim = st.selectbox(
    "审查具体结论",
    claims["claim_id"].tolist(),
    format_func=lambda value: f"{value} · {claims.loc[claims['claim_id'] == value, 'claim'].iloc[0]}",
)
claim = claims.loc[claims["claim_id"] == selected_claim].iloc[0]
ok_col, stop_col = st.columns(2)
with ok_col:
    st.success("允许表述")
    st.write(claim["allowed_wording"])
    st.info(f"下一步：{claim['next_action']}")
with stop_col:
    st.error("禁止表述")
    st.write(claim["prohibited_wording"])
    st.warning(f"证据缺口：{claim['evidence_gap']}")

st.subheader("自动结论门控")
gate_rows = pd.DataFrame(summary["validation_gates"])
st.dataframe(gate_rows, hide_index=True, width="stretch")

st.subheader("当前就绪度")
ready_rows = [
    {"target": "方向性科研分析", "ready": True, "reason": "可明确区分事实、方向、冲突和缺口"},
    {"target": "因果机制结论", "ready": summary["causal_inference_ready"], "reason": "缺少L3独立重复与机制干预证据"},
    {"target": "机器学习训练", "ready": summary["machine_learning_ready"], "reason": "只有B/R两个核心状态"},
    {"target": "求职案例展示", "ready": summary["portfolio_case_ready"], "reason": "可展示数据治理、模型适配、证据门控和审计"},
]
st.dataframe(pd.DataFrame(ready_rows), hide_index=True, width="stretch")

report = validation_report_markdown(summary)
st.download_button(
    "下载B/R证据验证报告",
    data=report.encode("utf-8"),
    file_name="BR_DQ_evidence_validation_v0.1.md",
    mime="text/markdown",
    use_container_width=True,
)

if st.button("保存报告并登记为项目证据", use_container_width=True):
    artifact = write_text_artifact(
        REPORTS,
        safe_output_filename("BR_DQ_evidence_validation_v0_1"),
        report,
    )
    event = record_event(
        "evidence_validation",
        "B/R证据与验证矩阵已生成",
        "围绕B-DQ/R-DQ生成证据等级、结论状态、禁止表述和验证门控；1–14号数据保持排除。",
        evidence={
            "case_id": summary["case_id"],
            "evidence_count": summary["evidence_count"],
            "claim_count": summary["claim_count"],
            "artifact": str(artifact.relative_to(artifact.parents[2])),
        },
        tags=["evidence", "validation", "scientific-guardrail", "career-evidence"],
    )
    st.success(f"已保存：{artifact.name}；事件ID：{event['event_id']}")

next_step_buttons(
    st,
    [
        {"label": "进入作品集与发布", "url": "/portfolio"},
        {"label": "返回科研会话", "url": "/projects?module=session"},
    ],
    key_prefix="validation",
    note="证据边界确认后，可以沉淀答辩与求职材料，或回到科研会话补充缺口。",
)
