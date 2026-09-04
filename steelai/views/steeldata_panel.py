"""SteelData UI, embedded in the existing data-quality page (no new sidebar)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from steelai.event_log import record_event
from steelai.steeldata_bridge import (
    SOURCE_STATUSES, SteelDataClient, commit_run, inspect_run, mapping_rows, prepare_intake,
    validate_selected_files,
)


def _reset_selection_review() -> None:
    st.session_state["sd_snapshot_agree"] = False
    st.session_state.pop("sd_inspection", None)


def render_steeldata_panel(contract: dict) -> None:
    st.subheader("SteelData · 原始表标准化接入")
    st.caption("原始表 → SteelData 独立运行 → 完整性与 QC 检查 → 人工对应样品 → 原有入库闸门。")
    st.info("已经填好的 SteelAI 标准 CSV，继续使用旁边的“标准表导入”；两条路线共用校验和仅追加写入，不需要重复导入。")
    client = SteelDataClient()
    availability = client.availability()
    with st.expander("模块连接与边界", expanded=False):
        st.write("连接：" + ("找到 SteelData 独立环境" if availability["ready"] else "未找到独立运行环境"))
        st.code(availability["project"], language=None)
        st.write("本地运行，不调用 DeepSeek，不更改 DSH；原始文件快照保存在 SteelData 结果包，SteelAI 只接收结构化观测和来源索引。")
        if st.button("检查 SteelData 环境", key="sd_doctor", disabled=not availability["ready"]):
            try:
                with st.spinner("检查模块环境…"):
                    st.json(client.doctor())
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    mode = st.radio("输入方式", ["读取已有结果包", "运行原始数据批次", "合成演示（禁止入库）"],
                    horizontal=True, key="sd_mode")
    selected_run = None
    if mode == "读取已有结果包":
        run_path = st.text_input("SteelData 运行目录（包含 manifest.json 和 COMPLETE）", key="sd_run_path",
                                 placeholder=r"<SteelData结果包目录>\run-...")
        if st.button("校验并读取结果包", key="sd_load", disabled=not run_path.strip()):
            selected_run = run_path.strip().strip('"')
    elif mode == "运行原始数据批次":
        selection = st.radio("如何选取实验数据？", ["选择文件（可多选/拖拽）", "填写文件夹路径"],
                             horizontal=True, key="sd_selection_mode", on_change=_reset_selection_review)
        input_dir, approval_text = "", ""
        data_files, approval_files = [], []
        ready = False
        if selection == "选择文件（可多选/拖拽）":
            uploads = st.file_uploader("选取实验数据文件", type=["xlsx", "csv", "tsv"], accept_multiple_files=True,
                max_upload_size=20, key="sd_data_files", on_change=_reset_selection_review)
            approvals = st.file_uploader("选取已人工批准的映射 JSON", type=["json"], accept_multiple_files=True,
                max_upload_size=2, key="sd_approval_files", on_change=_reset_selection_review)
            st.caption("可点击 Browse files（浏览文件）或拖拽。实验文件单个 ≤20 MiB、合计 ≤100 MiB；旧 .xls 请先另存为 .xlsx。选取不会自动运行。")
            if uploads:
                st.dataframe(pd.DataFrame([{"文件名": f.name, "大小（KiB）": round(f.size / 1024, 1)} for f in uploads]),
                             hide_index=True, width="stretch")
            if uploads and approvals:
                data_files = [(f.name, f.getvalue()) for f in uploads]
                approval_files = [(f.name, f.getvalue()) for f in approvals]
                try:
                    validate_selected_files(data_files, approval_files)
                    ready = True
                except ValueError as exc:
                    st.error(str(exc))
            st.caption("文件内容只传给本机 SteelAI 服务。运行时临时暂存，正常结束或报错后清理；SteelData 结果包仍保留原始快照，不发送给 AI。")
        else:
            input_dir = st.text_input("本批原始数据文件夹", key="sd_input", on_change=_reset_selection_review)
            approval_text = st.text_area("已人工批准的映射 JSON 路径（每行一个）", key="sd_approvals", on_change=_reset_selection_review)
            ready = bool(input_dir.strip() and approval_text.strip())
        st.caption("这里接收 SteelData v0.2 的 human 批准记录，不是旧版 mapping JSON，也不是未经批准的 profile。")
        agree = st.checkbox("我确认只处理该批次，并允许 SteelData 在自己的 output 中保存原始文件快照。", key="sd_snapshot_agree")
        if st.button("运行 SteelData 并读取结果", key="sd_run", disabled=not (agree and availability["ready"] and ready)):
            st.session_state.pop("sd_inspection", None)
            try:
                with st.spinner("SteelData 正在独立环境中处理，最多等待 180 秒…"):
                    if selection == "选择文件（可多选/拖拽）":
                        result = client.run_selected(data_files, approval_files)
                    else:
                        result = client.run(input_dir.strip().strip('"'),
                                            [p.strip().strip('"') for p in approval_text.splitlines() if p.strip()])
                selected_run = result["run_dir"]
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    else:
        st.warning("仅运行内置合成数据，含故意设置的错误。它用于演示拦截流程，不会修改真实 processed。")
        if st.button("运行合成演示", key="sd_demo", disabled=not availability["ready"]):
            st.session_state.pop("sd_inspection", None)
            try:
                with st.spinner("生成合成结果包…"):
                    result = client.demo()
                selected_run = result["run_dir"]
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    if selected_run:
        st.session_state.pop("sd_inspection", None)
        try:
            with st.spinner("校验全部结果文件和批准摘要…"):
                st.session_state["sd_inspection"] = inspect_run(selected_run)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            st.error("无法接收结果包：" + str(exc))
    inspection = st.session_state.get("sd_inspection")
    if inspection is None:
        st.caption("尚未读取结果。首次可选择“合成演示”，确认模块调用和拦截流程。")
        return
    manifest = inspection.manifest
    st.divider()
    st.write("当前已校验的结果：", manifest["run_id"])
    st.code(str(inspection.root), language=None)
    a, b, c = st.columns(3)
    a.metric("处理状态", manifest["processing_status"])
    b.metric("QC 状态", manifest["qc_status"])
    c.metric("标准记录", manifest["counts"]["records"])
    st.caption("COMPLETE 只代表结果写齐，不代表科研质量合格。预览固定在上次读取时；点击提交会重新校验。")
    st.dataframe(pd.DataFrame(manifest["files"])[["source_file", "status", "records"]], hide_index=True, width="stretch")
    with st.expander("QC 事项与标准数据预览", expanded=False):
        if inspection.qc.get("issues"):
            st.dataframe(pd.DataFrame(inspection.qc["issues"]), hide_index=True, width="stretch")
        for data in inspection.datasets:
            st.write(f"{data['source_file']} · {data['domain']}（前 12 条）")
            st.dataframe(pd.DataFrame(data["records"][:12]), hide_index=True, width="stretch")
        st.caption("完整 HTML 报告位于上述运行目录的 report.html；这里不执行导入结果中的 HTML/脚本。")
    if inspection.blockers:
        for reason in inspection.blockers:
            st.warning(reason)
        st.button("确认接入性能长表", disabled=True, key="sd_blocked_commit")
        return
    for warning in inspection.warnings:
        st.warning(warning)
    st.subheader("确认试样与研究样品的对应关系")
    st.caption("specimen_id 保持原样，不把独立试样改成材料组名；sample_id 只从现有研究范围中选，不根据名字猜测。")
    edit = st.data_editor(pd.DataFrame(mapping_rows(inspection)), key="sd_mapping_" + inspection.manifest_sha256,
        hide_index=True, width="stretch", num_rows="fixed", disabled=["mapping_key", "source_file", "specimen_id"],
        column_config={"mapping_key": None, "sample_id": st.column_config.SelectboxColumn(
            "SteelAI sample_id", options=["", *contract["scope"]["included_samples"]], required=True)})
    source_status = st.selectbox("这批数据的真实来源状态（不会因标准化而自动升级）", list(SOURCE_STATUSES),
                                 index=None, key="sd_source_" + inspection.manifest_sha256)
    bindings = {row["mapping_key"]: row["sample_id"] for row in edit.to_dict("records")}
    if source_status is None or any(not value for value in bindings.values()):
        st.info("请填全 sample_id 并选择来源状态，随后生成入库预览。")
        return
    try:
        candidate = prepare_intake(inspection, bindings, source_status)
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return
    report = candidate["report"]
    st.write(f"将 {manifest['counts']['records']} 条试样记录展开为 {report['row_count']} 条性能观测：YS / UTS / EL。")
    st.dataframe(pd.DataFrame(report["rows"]).head(60), hide_index=True, width="stretch")
    st.caption("最多展示 60 行；不生成均值或独立性结论，不覆盖 properties.csv，也不会立刻改变旧 B/R 摘要分析。")
    for message in report["errors"]:
        st.error(message)
    for message in report["warnings"]:
        st.warning(message)
    reviewer = st.text_input("本次接入审核人", key="sd_reviewer")
    note = st.text_input("审核说明（如何核对样品、单位与来源）", key="sd_review_note")
    confirm = st.checkbox("我已核对对应关系、全部数值、来源状态及警告，确认追加到真实性能长表。",
                          key="sd_confirm_" + candidate["preview_sha256"])
    if st.button("确认接入性能长表", type="primary", key="sd_commit",
                  disabled=report["status"] != "ready" or not (confirm and reviewer.strip() and note.strip())):
        try:
            result = commit_run(inspection.root, bindings, source_status, candidate["preview_sha256"],
                                reviewer=reviewer, note=note, confirmed=confirm)
        except (ValueError, OSError) as exc:
            st.error("未能完成接入，请重新预检：" + str(exc))
        else:
            st.success(f"已追加 {result['rows_added']} 条性能观测；审计编号：{result['intake_id']}。")
            try:
                record_event("data_intake", "SteelData 接入性能长表",
                    f"人工确认后追加 {result['rows_added']} 条记录；未修改旧摘要。",
                    evidence={key: result[key] for key in ("intake_id", "run_id", "rows_added", "manifest_sha256")},
                    tags=["steeldata", "append-only", "portfolio-evidence"])
            except OSError:
                st.warning("数据和接入审计包已保存，但事件日志未写入；请勿重复导入。")
            st.session_state.pop("sd_inspection", None)
