from __future__ import annotations

import pandas as pd
import streamlit as st

from steelai.run_center import (
    FILTER_LABELS,
    accepted_portfolio_results,
    collect_run_records,
    filter_run_records,
)
from steelai.ui import next_step_buttons, setup_page


setup_page(st, "待办与成果", "🧭")
st.caption("先处理待确认、阻断和失效记录，再查看已完成或已验收成果。这里不会自动改变任务状态。")

records = collect_run_records()
counts = {
    "running": sum(item.state_group == "running" for item in records),
    "needs_human": sum(item.state_group == "needs_human" for item in records),
    "blocked": sum(item.state_group == "blocked" for item in records),
    "invalidated": sum(item.state_group == "invalidated" for item in records),
    "accepted": sum(item.portfolio_eligible for item in records),
}

st.subheader("当前状态")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("进行中", counts["running"])
c2.metric("待人工确认", counts["needs_human"])
c3.metric("被阻断", counts["blocked"])
c4.metric("完整性失效", counts["invalidated"])
c5.metric("已验收成果", counts["accepted"])

if counts["needs_human"]:
    st.warning(f"有 {counts['needs_human']} 项需要人工确认。它们不会进入作品集。")
if counts["blocked"]:
    st.warning(f"有 {counts['blocked']} 项被阻断。请按来源模块提示补齐前置条件。")
if counts["invalidated"]:
    st.error(f"有 {counts['invalidated']} 项完整性失效。请回到来源模块检查，不能复用或覆盖原包。")

st.subheader("选择查看范围")
selected_filter = st.selectbox("查看范围", FILTER_LABELS)
filtered = filter_run_records(records, selected_filter)
st.caption(f"当前显示 {len(filtered)} 项；筛选不会改变任务状态。")

st.subheader("任务列表")
if not filtered:
    st.info("当前筛选条件下没有记录。")
else:
    state_labels = {
        "running": "进行中",
        "needs_human": "待人工确认",
        "blocked": "被阻止",
        "invalidated": "完整性失效",
        "completed": "已完成",
    }
    table = pd.DataFrame([{
        "任务": item.title,
        "任务编号": item.task_id,
        "来源": item.module,
        "状态": state_labels.get(item.state_group, item.state),
        "更新时间": item.updated_at or "—",
    } for item in filtered])
    st.dataframe(table, hide_index=True, width="stretch")

    options = {f"{item.module}｜{item.task_id}": item for item in filtered}
    selected_name = st.selectbox("选择一项继续处理", list(options))
    selected = options[selected_name]
    if selected.state_group == "invalidated":
        st.error("该记录完整性失效。请回到来源模块检查，不能作为证据或作品集成果。")
    elif selected.state_group == "blocked":
        st.error("该记录已被阻断或拒绝。请按来源模块提示解除条件，不要绕过门禁。")
    elif selected.state_group == "needs_human":
        st.warning("该记录等待人工确认。确认前不能升级为正式结果或作品集成果。")
    elif selected.portfolio_eligible:
        st.success("该成果完整性通过且已有人工验收，可以进入作品集候选。")
    else:
        st.info("该记录可查看，但尚不满足作品集的 complete 加人工验收条件。")

    with st.expander("技术详情"):
        st.json(selected.to_dict())

    next_step_buttons(
        st,
        [
            {"label": selected.next_label, "url": selected.next_url},
            {"label": "返回首页", "url": "/"},
        ],
        key_prefix="run_center_selected",
        note=selected.portfolio_reason,
    )

st.subheader("已验收成果")
accepted = accepted_portfolio_results(records)
if accepted:
    st.dataframe(
        pd.DataFrame([{
            "成果": item["title"],
            "模块": item["module"],
            "结果等级": item["result_level"],
            "证据类别": item["evidence_class"],
            "审核身份": item["reviewer_id"],
            "范围": item["portfolio_reason"],
        } for item in accepted]),
        hide_index=True,
        width="stretch",
    )
else:
    st.info("当前没有同时满足完整性、complete 状态、结果等级和人工验收的成果。")

st.caption("作品集过滤器不会读取 draft、needs_human、blocked、invalidated 或未经人工验收的中间结果。")
