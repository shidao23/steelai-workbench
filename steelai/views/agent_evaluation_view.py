from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.agent_evaluation import (
    benchmark_contract,
    load_benchmark,
    read_latest_evaluation,
    run_agent_evaluation,
)
from steelai.agent_observability import (
    build_trace_records,
    compare_evaluation_runs,
    load_evaluation_run,
    read_evaluation_history,
)
from steelai.event_log import record_event
from steelai.research_agent import agent_status
from steelai.ui import setup_page


setup_page(st, "SteelAI Workbench · Agent质量评测", "📐")
st.caption("用固定问题、固定工具期望和透明评分规则，检查Research Agent的可靠性，而不是让另一个大模型主观打分。")

contract = benchmark_contract()
benchmark, cases = load_benchmark()
status = agent_status()
category_labels = {
    "data_grounding": "数据事实",
    "physics": "Physics",
    "ebsd": "EBSD",
    "sem": "SEM",
    "scientific_guardrail": "科学边界",
    "privacy_and_permission": "隐私与权限",
}

a, b, c, d = st.columns(4)
a.metric("标准问题", contract["case_count"])
b.metric("能力类别", contract["category_count"])
c.metric("隐私案例", contract["privacy_case_count"])
d.metric("评测契约", "通过" if contract["status"] == "passed" else "需修复")

if contract["status"] == "passed":
    st.success("问题ID、工具白名单、案例数量和隐私覆盖检查均通过。")
else:
    st.error("；".join(contract["problems"]))

with st.expander("查看标准问题集", expanded=False):
    case_table = pd.DataFrame([
        {
            "case_id": case.case_id,
            "category": category_labels.get(case.category, case.category),
            "title": case.title,
            "expected_tools": ", ".join(call.get("tool", "") for call in case.expected_calls) or "本地拒绝/无需工具",
        }
        for case in cases
    ])
    st.dataframe(case_table, hide_index=True, width="stretch")
    st.caption(f"Benchmark SHA-256：{contract['benchmark_sha256']}")

st.subheader("运行小批量实时评测")
st.warning(f"实时评测会调用DeepSeek。建议每轮选择1–5个案例；先修复失败案例，再扩大到完整{contract['case_count']}题。")
case_options = [case.case_id for case in cases]
default_cases = [case_id for case_id in ("DATA-001", "PHYS-004", "PRIV-001") if case_id in case_options]
selected_ids = st.multiselect(
    "选择评测案例",
    case_options,
    default=default_cases,
    format_func=lambda case_id: next(
        f"{case_id} · {case.title}" for case in cases if case.case_id == case_id
    ),
)
if len(selected_ids) > 5:
    st.error("单轮最多选择5个案例，以控制费用并便于逐项分析。")

run_disabled = not status.ready or not selected_ids or len(selected_ids) > 5
if not status.ready:
    st.info(f"实时评测暂不可用：{status.message} 标准问题集与离线评分框架仍已就绪。")

if st.button("运行选中案例", type="primary", disabled=run_disabled, use_container_width=True):
    try:
        with st.status("正在运行Agent评测……", expanded=True) as evaluation_status:
            st.write("逐题调用只读Research Agent并保存工具轨迹")
            result = run_agent_evaluation(selected_ids)
            st.write("应用工具、证据、科学边界和隐私评分")
            evaluation_status.update(label="Agent评测完成", state="complete", expanded=False)
        event = record_event(
            "agent_evaluation",
            "Research Agent完成一轮标准化评测",
            f"运行{result.summary['case_count']}个案例；通过率{result.summary['pass_rate'] * 100:.1f}%。",
            evidence={
                "evaluation_id": result.evaluation_id,
                "benchmark_id": result.summary["benchmark_id"],
                "model": result.summary["model"],
                "case_count": result.summary["case_count"],
                "pass_rate": result.summary["pass_rate"],
                "mean_score": result.summary["mean_overall_score"],
                "privacy_score": result.summary["mean_privacy_score"],
                "artifact": f"outputs/agent_evaluations/{result.evaluation_id}/evaluation_report.md",
            },
            tags=["agent-evaluation", "benchmark", "privacy", "career-evidence"],
        )
        saved = result.to_dict()
        saved["event_id"] = event["event_id"]
        saved["manifest"] = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        st.session_state["agent_evaluation_last_result"] = saved
    except Exception as exc:
        st.error(f"评测未完成：{exc}")

saved = st.session_state.get("agent_evaluation_last_result")
if not saved:
    latest = read_latest_evaluation()
    if latest:
        saved = {
            "evaluation_id": latest.get("evaluation_id"),
            "summary": latest.get("summary", {}),
            "rows": latest.get("rows", []),
            "report": latest.get("report", ""),
            "manifest": latest,
        }

if saved and saved.get("summary"):
    summary = saved["summary"]
    st.subheader("最近一次评测")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("通过率", f"{summary['pass_rate'] * 100:.1f}%")
    m2.metric("综合得分", f"{summary['mean_overall_score'] * 100:.1f}")
    m3.metric("科学边界", f"{summary['mean_guardrail_score'] * 100:.1f}")
    m4.metric("隐私得分", f"{summary['mean_privacy_score'] * 100:.1f}")

    detail_tab, history_tab, trace_tab = st.tabs(["本轮结果", "历史与版本对比", "安全调用轨迹"])
    with detail_tab:
        k1, k2, k3 = st.columns(3)
        k1.metric("案例数", summary.get("case_count", 0))
        k2.metric("平均延迟", f"{summary.get('mean_latency_ms', 0) / 1000:.1f} s")
        k3.metric("记录Token", f"{summary.get('total_tokens', 0):,}")
        category_frame = pd.DataFrame([
            {
                "类别": category_labels.get(category, category),
                "得分": score * 100,
            }
            for category, score in summary.get("category_scores", {}).items()
        ]).set_index("类别")
        if not category_frame.empty:
            st.bar_chart(category_frame, horizontal=True)

        rows = pd.DataFrame(saved.get("rows", []))
        if not rows.empty:
            display = rows[[
                "case_id", "category", "title", "passed", "overall_score",
                "tool_score", "evidence_score", "guardrail_score", "privacy_score", "latency_ms",
            ]].copy()
            display["category"] = display["category"].map(lambda value: category_labels.get(value, value))
            display["overall_score"] = (display["overall_score"] * 100).round(1)
            display = display.rename(columns={
                "case_id": "案例", "category": "类别", "title": "标题", "passed": "通过",
                "overall_score": "综合分", "tool_score": "工具", "evidence_score": "证据",
                "guardrail_score": "科学边界", "privacy_score": "隐私", "latency_ms": "延迟(ms)",
            })
            st.dataframe(display, hide_index=True, width="stretch")

            failed = [row for row in saved["rows"] if not row.get("passed")]
            with st.expander(f"失败案例诊断（{len(failed)}）", expanded=False):
                if not failed:
                    st.success("本轮没有失败案例。")
                for row in failed:
                    st.markdown(f"**{row['case_id']} · {row['title']}**")
                    st.write("缺少工具：", row.get("missing_expected_calls") or "无")
                    st.write("缺少概念：", row.get("missing_required_groups") or "无")
                    st.write("禁止表述命中：", row.get("forbidden_hits") or "无")

        left, right = st.columns(2)
        left.download_button(
            "下载评测报告",
            saved.get("report", "").encode("utf-8"),
            file_name=f"{saved['evaluation_id']}_agent_evaluation.md",
            mime="text/markdown",
            use_container_width=True,
        )
        right.download_button(
            "下载评测Manifest",
            json.dumps(saved.get("manifest", {}), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"{saved['evaluation_id']}_evaluation_manifest.json",
            mime="application/json",
            use_container_width=True,
        )

    with history_tab:
        history = read_evaluation_history()
        if not history:
            st.info("完成至少一轮评测后显示历史趋势。")
        else:
            history_frame = pd.DataFrame(history)
            history_display = history_frame[[
                "created_at", "evaluation_id", "model", "case_count", "pass_rate",
                "mean_overall_score", "mean_latency_ms", "total_tokens",
            ]].copy()
            history_display["pass_rate"] = (history_display["pass_rate"] * 100).round(1)
            history_display["mean_overall_score"] = (history_display["mean_overall_score"] * 100).round(1)
            history_display = history_display.rename(columns={
                "created_at": "时间", "evaluation_id": "评测ID", "model": "模型",
                "case_count": "案例数", "pass_rate": "通过率(%)",
                "mean_overall_score": "综合分", "mean_latency_ms": "平均延迟(ms)",
                "total_tokens": "Token",
            })
            st.dataframe(history_display, hide_index=True, width="stretch")
            trend = history_frame.sort_values("created_at").set_index("created_at")
            st.line_chart(trend[["pass_rate", "mean_overall_score"]] * 100)
            if len(history) < 2:
                st.caption("当前只有一个真实基线；下一轮评测后即可自动进行版本退化检查。")
            else:
                run_ids = [row["evaluation_id"] for row in history]
                left_col, right_col = st.columns(2)
                baseline_id = left_col.selectbox("基线运行", run_ids, index=min(1, len(run_ids) - 1))
                candidate_id = right_col.selectbox("候选运行", run_ids, index=0)
                if baseline_id == candidate_id:
                    st.info("请选择两次不同的运行。")
                else:
                    comparison = compare_evaluation_runs(baseline_id, candidate_id)
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("共同案例", comparison["common_case_count"])
                    c2.metric("退化", comparison["regression_count"])
                    c3.metric("得分变化", f"{comparison['score_delta'] * 100:+.1f}")
                    c4.metric("延迟变化", f"{comparison['latency_delta_ms']:+.0f} ms")
                    if comparison["rows"]:
                        st.dataframe(pd.DataFrame(comparison["rows"]), hide_index=True, width="stretch")
                    else:
                        st.warning("两轮评测没有共同案例，不能直接判断能力退化。")

    with trace_tab:
        trace_records = build_trace_records(saved.get("manifest", {}), saved.get("rows", []))
        st.caption("仅保存案例ID、模型、评分、耗时、Token和工具名称；不含问题、回答、工具参数、本地路径或原始文件。")
        trace_frame = pd.DataFrame([
            {
                "trace_id": row["trace_id"][:10],
                "span": row["name"],
                "kind": row["kind"],
                "status": row["status"],
                "duration_ms": row["duration_ms"],
                "case_id": row["attributes"].get("case_id"),
            }
            for row in trace_records
        ])
        if not trace_frame.empty:
            st.dataframe(trace_frame, hide_index=True, width="stretch")
        trace_jsonl = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in trace_records)
        st.download_button(
            "下载脱敏Trace JSONL",
            trace_jsonl.encode("utf-8"),
            file_name=f"{saved['evaluation_id']}_trace_spans.jsonl",
            mime="application/x-ndjson",
            use_container_width=True,
        )

st.divider()
st.caption("评测分数用于定位失败模式，不代表通用智能水平；重要科研结论仍需专家复核和独立实验支持。")
