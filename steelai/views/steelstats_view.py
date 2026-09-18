from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from steelai.steeldata_bridge import inspect_run, mapping_rows
from steelai.steelstats_bridge import SteelStatsClient
from steelai.statistics_governance import run_governed_statistics_from_steeldata
from steelai.ui import next_step_buttons, setup_page


setup_page(st, "可追溯统计", "📈")
st.caption("选择已完成的 SteelData 结果包，经人工确认试样对应和统计方法后，调用独立 SteelStats 环境生成描述统计报告。")
st.caption("T53 共享治理：统计单位与纳入决定 → SteelStats 描述统计 → 完整性复核 → 证据等级与表述边界 → Governance Manifest。")

client = SteelStatsClient()
availability = client.availability()
st.markdown("#### 当前状态")
if availability["ready"]:
    st.success("SteelStats 独立模块已就绪；Workbench 只调用公开 CLI，不导入其内部代码。")
else:
    st.error("未找到同级 SteelStats 项目、steelstats.module.json 或独立 .venv。仍可填写路径，但不能生成报告。")

st.markdown("#### 主要操作")
run_path = st.text_input("SteelData 结果包目录", key="ss_run_path", placeholder=r"<SteelData结果包目录>\run-...")
if st.button("校验并读取统计来源", key="ss_load", disabled=not run_path.strip()):
    try:
        st.session_state["ss_inspection"] = inspect_run(run_path)
        st.session_state.pop("ss_result", None)
    except (OSError, ValueError) as exc:
        st.session_state.pop("ss_inspection", None)
        st.error("无法读取 SteelData 结果包：" + str(exc))

inspection = st.session_state.get("ss_inspection")
if inspection is not None:
    a, b, c = st.columns(3)
    a.metric("SteelData QC", inspection.manifest.get("qc_status", "unknown"))
    b.metric("逐试样记录", sum(len(dataset["records"]) for dataset in inspection.datasets))
    c.metric("来源完整性", "通过")
    st.caption(f"Run ID：{inspection.manifest.get('run_id')}　Manifest SHA-256：{inspection.manifest_sha256}")
    if inspection.warnings:
        st.warning("\n\n".join(inspection.warnings))
    if inspection.blockers:
        st.error("当前结果包不能进入统计：\n\n" + "\n\n".join(f"• {item}" for item in inspection.blockers))
    else:
        st.subheader("人工确认统计身份")
        st.write("每个来源试样必须明确对应研究样品；Workbench 不根据试样名称自动猜测。")
        bindings: dict[str, str] = {}
        rows = mapping_rows(inspection)
        for item in rows:
            columns = st.columns([2, 2, 3])
            columns[0].text_input("来源文件", value=item["source_file"], disabled=True, key=f"ss_source_{item['mapping_key']}")
            columns[1].text_input("物理试样", value=item["specimen_id"], disabled=True, key=f"ss_specimen_{item['mapping_key']}")
            bindings[item["mapping_key"]] = columns[2].text_input(
                "研究样品 sample_id", key=f"ss_sample_{item['mapping_key']}", placeholder="例如 B-DQ",
            ).strip()

        method_version = st.text_input(
            "拉伸方法版本",
            key="ss_method_version",
            placeholder="例如 tensile-iso6892-1@1.0.0",
            help="必须来自实验方法或报告记录，Workbench 不会自行推断。",
        )
        reviewer = st.text_input("统计纳入审核人", key="ss_reviewer")
        rationale = st.text_input(
            "审核说明（统计单位、纳入决定、方法版本和证据边界）",
            key="ss_rationale",
        )
        confirmed = st.checkbox(
            "我已核对试样对应、方法版本和来源 QC，并批准这些逐试样 YS、UTS、EL 观测进入本次描述统计。",
            key="ss_confirm",
        )
        accept_warnings = st.checkbox(
            "若结果保留 warning，我同意完整保留警告并仅作描述性解释，不摘取为显著性或因果结论。",
            key="ss_accept_warnings",
        )
        ready = (
            availability["ready"]
            and all(bindings.values())
            and bool(method_version.strip())
            and bool(reviewer.strip())
            and bool(rationale.strip())
            and confirmed
            and accept_warnings
        )
        if st.button("生成并复核统计报告", type="primary", key="ss_generate", disabled=not ready):
            st.session_state.pop("ss_result", None)
            try:
                reviewed_at = datetime.now().astimezone().isoformat(timespec="seconds")
                result = run_governed_statistics_from_steeldata(
                    inspection.root,
                    bindings,
                    method_version,
                    reviewer,
                    reviewed_at,
                    rationale=rationale,
                    accept_warnings=accept_warnings,
                    client=client,
                )
                st.session_state["ss_result"] = result
            except (OSError, ValueError) as exc:
                st.error("统计报告未生成；SteelData 源包未修改：" + str(exc))

result = st.session_state.get("ss_result")
if result is not None:
    st.markdown("#### 结果")
    a, b, c, d = st.columns(4)
    a.metric("综合质量状态", result["quality_status"])
    b.metric("SteelStats 状态", result["statistics"]["status"])
    c.metric("完整性复核", result["statistics"]["verification"])
    d.metric("证据等级", result["evidence_level"])
    st.caption(
        f"治理编号：{result['governance_id']}　分析编号：{result['analysis_id']}　"
        "SteelData 源包 modified=false"
    )
    if result["quality_status"] == "warning":
        st.warning("报告已生成，但 SteelData 或 SteelStats 存在 warning；请阅读报告中的缺失、排除和 QC 说明。")
    else:
        st.success("报告已生成并通过独立完整性复核。")
    report_text = Path(result["governance_report"]).read_text(encoding="utf-8")
    with st.expander("查看统计报告", expanded=True):
        st.markdown(report_text)
    st.download_button(
        "下载统计报告 Markdown",
        report_text.encode("utf-8"),
        file_name=f"{result['analysis_id']}_statistics_report.md",
        mime="text/markdown",
    )
    policy = result["statement_policy"]
    with st.expander("技术详情 · 表述边界与治理记录", expanded=False):
        st.markdown("**允许表述**")
        for item in policy["allowed_statements"]:
            st.write("- " + item)
        st.markdown("**谨慎表述**")
        for item in policy["cautious_statements"]:
            st.write("- " + item)
        st.markdown("**禁止表述**")
        for item in policy["prohibited_statements"]:
            st.write("- " + item)
        st.json(result)

st.info("边界：只做描述统计，不做显著性检验；不自动删异常值或补缺失值；不把统计结果写回 SteelData 或原始观测列。")

next_step_buttons(
    st,
    [
        {
            "label": "进入证据验证",
            "url": "/analysis?module=validation",
        },
        {"label": "返回数据处理", "url": "/intake"},
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
    ],
    key_prefix="steelstats",
    note="统计报告生成后，继续检查证据等级、限制和允许表述的结论。",
)
