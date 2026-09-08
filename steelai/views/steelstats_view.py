from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from steelai.steeldata_bridge import inspect_run, mapping_rows
from steelai.steelstats_bridge import SteelStatsClient, run_statistics_from_steeldata
from steelai.ui import setup_page


setup_page(st, "SteelStats 可追溯统计", "📈")
st.caption("选择已完成的 SteelData 结果包，经人工确认试样对应和统计方法后，调用独立 SteelStats 环境生成描述统计报告。")

client = SteelStatsClient()
availability = client.availability()
if availability["ready"]:
    st.success("SteelStats 独立模块已就绪；Workbench 只调用公开 CLI，不导入其内部代码。")
else:
    st.error("未找到同级 SteelStats 项目、steelstats.module.json 或独立 .venv。仍可填写路径，但不能生成报告。")

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
        confirmed = st.checkbox(
            "我已核对试样对应、方法版本和来源 QC，并批准这些逐试样 YS、UTS、EL 观测进入本次描述统计。",
            key="ss_confirm",
        )
        ready = availability["ready"] and all(bindings.values()) and bool(method_version.strip()) and bool(reviewer.strip()) and confirmed
        if st.button("生成并复核统计报告", type="primary", key="ss_generate", disabled=not ready):
            st.session_state.pop("ss_result", None)
            try:
                result = run_statistics_from_steeldata(
                    inspection.root,
                    bindings,
                    method_version,
                    reviewer,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    client=client,
                )
                st.session_state["ss_result"] = result
            except (OSError, ValueError) as exc:
                st.error("统计报告未生成；SteelData 源包未修改：" + str(exc))

result = st.session_state.get("ss_result")
if result is not None:
    st.subheader("统计结果状态")
    a, b, c = st.columns(3)
    a.metric("综合质量状态", result["quality_status"])
    b.metric("SteelStats 状态", result["statistics"]["status"])
    c.metric("完整性复核", result["statistics"]["verification"])
    st.caption(f"分析编号：{result['analysis_id']}　SteelData 源包 modified=false")
    if result["quality_status"] == "warning":
        st.warning("报告已生成，但 SteelData 或 SteelStats 存在 warning；请阅读报告中的缺失、排除和 QC 说明。")
    else:
        st.success("报告已生成并通过独立完整性复核。")
    report_text = Path(result["report"]).read_text(encoding="utf-8")
    with st.expander("查看统计报告", expanded=True):
        st.markdown(report_text)
    st.download_button(
        "下载统计报告 Markdown",
        report_text.encode("utf-8"),
        file_name=f"{result['analysis_id']}_statistics_report.md",
        mime="text/markdown",
    )
    with st.expander("查看模块边界记录", expanded=False):
        st.json(result)

st.info("边界：只做描述统计，不做显著性检验；不自动删异常值或补缺失值；不把统计结果写回 SteelData 或原始观测列。")
