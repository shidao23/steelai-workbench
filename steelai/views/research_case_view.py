from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.data import read_rows
from steelai.event_log import record_event
from steelai.research_agent import agent_status
from steelai.research_case import DEFAULT_QUESTION, ResearchCaseRequest, run_research_case
from steelai.research_session import attach_run, load_session
from steelai.ui import setup_page


setup_page(st, "研究任务", "🧭")
st.caption("把数据检查、Physics、SEM、双尺度EBSD、证据门控和可选Agent综合串成一次可复现研究运行。")

status = agent_status()
samples = [row["sample_id"] for row in read_rows("samples")]
active_session_id = st.session_state.get("active_research_session_id", "")
active_session = None
if active_session_id:
    try:
        active_session = load_session(active_session_id)
    except (FileNotFoundError, ValueError):
        st.session_state.pop("active_research_session_id", None)
if active_session:
    st.info(f"本次运行将关联当前科研会话：{active_session['title']} · {active_session['session_id']}")
a, b, c, d = st.columns(4)
a.metric("核心样品", len(samples))
b.metric("确定性阶段", 7)
c.metric("科学门控", 6)
d.metric("外部Agent", "可用" if status.ready else "离线可运行")

with st.expander("本流程会做什么", expanded=False):
    st.markdown(
        "1. 固化processed数据哈希与代码哈希。\n"
        "2. 运行B/R结构化对比和Physics Card。\n"
        "3. 读取既有AutoDimple与两个采集尺度的EBSD结果。\n"
        "4. 应用证据等级、允许/禁止表述和六项科学门控。\n"
        "5. 生成Markdown报告、证据快照和`run_manifest.json`。"
    )

question = st.text_area("研究问题", value=DEFAULT_QUESTION, height=90)
left, right = st.columns(2)
control_id = left.selectbox("对照样品", samples, index=samples.index("B-DQ") if "B-DQ" in samples else 0)
comparison_id = right.selectbox(
    "比较样品",
    samples,
    index=samples.index("R-DQ") if "R-DQ" in samples else min(1, len(samples) - 1),
)
use_agent = st.toggle(
    "最后使用DeepSeek进行证据综合",
    value=False,
    disabled=not status.ready,
    help="关闭时仍会完成全部确定性计算与报告。开启后只允许发送脱敏processed结构化数据和分析摘要。",
)
if not status.ready:
    st.info("DeepSeek当前不可用或未随本次进程加载；端到端确定性流程仍可完整运行。")

if st.button("运行完整研究任务", type="primary", use_container_width=True):
    try:
        request = ResearchCaseRequest(question, control_id, comparison_id, use_agent)
        with st.status("正在执行研究任务……", expanded=True) as run_status:
            st.write("检查数据版本与核心样品范围")
            result = run_research_case(request)
            st.write("完成Physics、SEM、EBSD和证据门控")
            st.write("生成研究报告、证据快照和运行清单")
            run_status.update(label="研究任务已完成", state="complete", expanded=False)
        linked_session_id = ""
        if active_session:
            attach_run(
                active_session["session_id"],
                result.run_id,
                result.manifest["pipeline"]["version"],
                result.status,
                f"outputs/research_cases/{result.run_id}/research_report.md",
            )
            linked_session_id = active_session["session_id"]
        event = record_event(
            "research_case_run",
            "SteelAI端到端B/R研究任务完成",
            question.strip(),
            evidence={
                "run_id": result.run_id,
                "pipeline_version": result.manifest["pipeline"]["version"],
                "status": result.status,
                "agent_status": result.manifest["agent"].get("status"),
                "scientific_readiness": result.manifest["scientific_readiness"],
                "artifact": f"outputs/research_cases/{result.run_id}/research_report.md",
                "research_session_id": linked_session_id,
            },
            tags=["research-pipeline", "reproducibility", "scientific-guardrail", "career-evidence"],
        )
        payload = result.to_dict()
        payload["event_id"] = event["event_id"]
        payload["research_session_id"] = linked_session_id
        st.session_state["research_case_last_result"] = payload
    except Exception as exc:
        st.error(f"研究任务未完成：{exc}")

saved = st.session_state.get("research_case_last_result")
if saved:
    manifest = saved["manifest"]
    st.success(f"运行完成：{saved['run_id']} · 项目事件：{saved['event_id']}")
    if saved.get("research_session_id"):
        st.caption(f"已关联科研会话：{saved['research_session_id']}")
    readiness = manifest["scientific_readiness"]
    r1, r2, r3 = st.columns(3)
    r1.metric("总体就绪度", readiness.get("overall", "unknown"))
    r2.metric("因果推断", "就绪" if readiness.get("causal_inference_ready") else "未就绪")
    r3.metric("机器学习", "就绪" if readiness.get("machine_learning_ready") else "未就绪")

    st.subheader("任务轨迹")
    stage_table = pd.DataFrame(manifest["stages"])
    st.dataframe(
        stage_table[["stage_id", "label", "status", "duration_ms"]],
        hide_index=True,
        width="stretch",
    )

    st.subheader("结果文件")
    st.caption("完整报告默认收起，主界面只保留结论状态、任务轨迹和下载入口。")
    with st.expander("展开完整研究报告", expanded=False):
        st.markdown(saved["report"])
    download_left, download_right = st.columns(2)
    download_left.download_button(
        "下载研究报告",
        saved["report"].encode("utf-8"),
        file_name=f"{saved['run_id']}_research_report.md",
        mime="text/markdown",
        use_container_width=True,
    )
    download_right.download_button(
        "下载Run Manifest",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{saved['run_id']}_run_manifest.json",
        mime="application/json",
        use_container_width=True,
    )

st.divider()
st.caption("隐私边界：禁止发送原始图片、CTF/TIF、本地文件路径和论文原文；1–14号实验不进入本流程。")
