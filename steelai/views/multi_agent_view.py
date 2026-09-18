from __future__ import annotations

import pandas as pd
import streamlit as st

from steelai.multi_agent_orchestrator import run_t60_demo, validate_multi_agent_contract
from steelai.agent_workflow_benchmark import latest_evaluation, publish_benchmark_package, validate_benchmark
from steelai.research_protocol import protocol_status, run_t61_handoff_demo
from steelai.ui import next_step_buttons, setup_page


setup_page(st, "材料科研多智能体协作", "🧩")
st.caption("五个职责受限的角色按固定顺序协作；角色不是五个自由聊天机器人，不能审批、正式写入或运行任意命令。")

contract = validate_multi_agent_contract()
c1, c2, c3, c4 = st.columns(4)
c1.metric("角色契约", "通过" if contract.get("status") == "passed" else "失败")
c2.metric("职责角色", contract.get("role_count", 0))
c3.metric("人工关口", contract.get("checkpoint_count", 0))
c4.metric("工具失败重试", "1 次")

st.subheader("协作流程")
st.markdown("规划 → 人工批准计划 → 数据证据 → 统计与物理 → 材料解释 → 机器审查 → 人工接纳结果")
st.info("机器审查角色可以阻止无证据结论，但没有人工审批权。云模型不可用时，确定性数据处理、统计和物理卡仍可运行。")

scenario_labels = {
    "成功链路": "success",
    "证据不足失败": "insufficient_evidence",
    "工具执行失败": "tool_failure",
    "云端不可用降级": "offline_success",
}
selected = st.selectbox("冻结演示", list(scenario_labels))
st.caption("全部演示只使用公开合成证据和明确标记的人工决定夹具，不代表真实实验审批。")
if st.button("运行或复用 T60 演示", type="primary", use_container_width=True):
    with st.spinner("正在执行受控交接并生成审计轨迹……"):
        st.session_state["t60_last_demo"] = run_t60_demo(scenario_labels[selected]).to_dict()

result = st.session_state.get("t60_last_demo")
if result:
    st.subheader("运行结果")
    a, b, c, d = st.columns(4)
    a.metric("状态", result.get("status", ""))
    b.metric("交接", len(result.get("handoffs", [])))
    c.metric("工具调用", len(result.get("tool_calls", [])))
    d.metric("确定性结果", "已就绪" if result.get("deterministic_outputs_ready") else "未生成")
    if result.get("status") == "complete":
        st.success(result.get("message", ""))
    else:
        st.error(f"{result.get('error_code', '')} · {result.get('message', '')}")
    if result.get("cloud_status") == "unavailable":
        st.warning("云端模型不可用：已切换为确定性降级说明，数据、统计和物理步骤不受影响。")
    handoffs = result.get("handoffs", [])
    if handoffs:
        st.dataframe(pd.DataFrame([{
            "任务": item.get("task_id"),
            "交出角色": item.get("from_role"),
            "负责角色": item.get("responsibility_role"),
            "状态": item.get("output_status"),
            "证据数": len(item.get("evidence_refs", [])),
        } for item in handoffs]), hide_index=True, width="stretch")
    with st.expander("技术轨迹"):
        st.json(result)

st.divider()
st.subheader("MCP 工具与 A2A 交接")
protocol = protocol_status()
p1, p2, p3, p4 = st.columns(4)
p1.metric("协议契约", "通过" if protocol.get("status") == "passed" else "失败")
p2.metric("MCP 工具", protocol.get("tool_count", 0))
p3.metric("传输", protocol.get("transport", ""))
p4.metric("正式结果权限", "关闭")
st.caption("当前只实现本地 stdio MCP 与项目内轻量 A2A 任务信封，不宣称完整网络协议兼容。")
if st.button("运行或复用 T61 协议演示", use_container_width=True):
    with st.spinner("正在执行结构化任务交接与幂等工具调用……"):
        st.session_state["t61_last_demo"] = run_t61_handoff_demo()

protocol_demo = st.session_state.get("t61_last_demo")
if protocol_demo:
    if protocol_demo.get("status") == "passed":
        st.success("T61 结构化交接通过；所有输出仍是待人工复核的候选结果。")
    else:
        st.error("T61 协议演示未通过。")
    calls = protocol_demo.get("tool_calls", [])
    if calls:
        st.dataframe(pd.DataFrame([{
            "调用 ID": item.get("tool_call_id"),
            "工具": item.get("tool_name"),
            "角色": item.get("caller_role"),
            "输入版本": item.get("input_version"),
            "状态": item.get("status"),
            "复用": item.get("reused"),
            "正式结果": item.get("formal_result"),
        } for item in calls]), hide_index=True, width="stretch")
    with st.expander("查看 A2A 任务修订与协议收据"):
        st.json(protocol_demo)

st.divider()
st.subheader("人工 单智能体与多智能体评估")
t63_contract = validate_benchmark()
t1, t2, t3, t4 = st.columns(4)
t1.metric("评测契约", "通过" if t63_contract.get("status") == "passed" else "失败")
t2.metric("固定任务", t63_contract.get("task_count", 0))
t3.metric("对照流程", t63_contract.get("workflow_count", 0))
t4.metric("需实测记录", t63_contract.get("required_measurement_count", 0))
st.caption("数据检查、统计解释、Physics 判断和报告整理各一题；三种流程各重复两次。指标和优势判定已在实测前冻结。")
if st.button("准备或复用 T63 评测包", use_container_width=True):
    st.session_state["t63_preparation"] = publish_benchmark_package()

t63_latest = latest_evaluation()
if t63_latest:
    evaluation = t63_latest["evaluation"]
    if evaluation["conclusion"] == "insufficient_evidence":
        st.warning(
            f"真实记录 {evaluation['measured_record_count']}/{evaluation['required_record_count']}。"
            "校准记录不参与优势判断；需要研究者完成同一任务集的真实计时。"
        )
    else:
        st.success(f"固定判定结果：{evaluation['conclusion']}")
    st.dataframe(pd.DataFrame(evaluation["workflow_results"]), hide_index=True, width="stretch")
    st.caption(f"填写模板：{t63_latest['measurement_template']}")
    st.caption(f"评估报告：{t63_latest['report']}")
    with st.expander("查看 T63 覆盖与判定详情"):
        st.json(evaluation)

st.subheader("当前边界")
st.markdown(
    "- 只编排已登记、已核验、已授权的证据引用，不直接读取或修改原始资料。\n"
    "- 只调用角色契约中的固定工具；失败重试一次后关闭式阻断。\n"
    "- 不保存问题原文和工具原始参数，只保存摘要、状态、责任角色和证据引用。\n"
    "- 成功演示仍是 synthetic_demo_only，不自动进入真实科研成果或作品集。"
    "\n- MCP 与 A2A 当前是本地受控子集，不包含远程发现、流式协议或网络身份联盟。"
    "\n- T63 校准记录不等于真实效率证据；人工、单智能体和多智能体的24条同题实测未齐前不判断优势。"
)

next_step_buttons(
    st,
    [
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
        {"label": "进入证据验证", "url": "/analysis?module=validation"},
    ],
    key_prefix="t60_multi_agent",
    note="先看交接与失败原因，再决定是否由人工接管、补证据或结束流程。",
)
