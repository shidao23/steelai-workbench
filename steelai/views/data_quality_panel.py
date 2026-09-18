from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.research_data_contract import (
    contract_report_markdown,
    load_research_contract,
    validate_research_data_contract,
)
from steelai.data_intake import (
    load_id_policy,
    template_csv_bytes,
    validate_intake_csv,
)
from steelai.data_intake_governance import (
    commit_standard_intake_governed,
    preview_intake_governance,
)
from steelai.event_log import record_event
from steelai.intake_request import register_intake_request, uploaded_file_selection
from steelai.ui import next_step_buttons, setup_page
from steelai.views.external_standardization_view import render_external_standardization
from steelai.views.steeldata_panel import render_steeldata_panel
from steelai.views.thermal_simulation_view import render_thermal_simulation_intake


setup_page(st, "导入与检查数据", "🧱")
st.caption("选择与你手头文件相符的入口。系统先预览和检查；身份或单位不明确时停止，不会把未知值当作 0。")

with st.expander("为什么需要人工确认？", expanded=False):
    st.write(
        "文件识别和字段映射可以自动完成，但样品身份、物理试样关系、单位和来源必须由人确认。"
        "确认后仍只追加新记录，不覆盖原始文件或既有观测。"
    )
    st.caption("治理流程：输入登记 → 人工审批 → 受控执行 → 质量检查 → 仅追加提交 → 完整性记录。")

report = validate_research_data_contract()
contract = load_research_contract()
policy = load_id_policy()

external_tab, thermal_tab, status_tab, advanced_tab = st.tabs(
    ["导入实验表格", "导入热模拟", "查看数据状态", "高级工具"]
)

with advanced_tab:
    intake_tab, steeldata_tab, template_tab = st.tabs(
        ["标准表导入", "SteelData 接入", "字段与模板"]
    )

with external_tab:
    render_external_standardization()

with thermal_tab:
    render_thermal_simulation_intake()

with status_tab:
    a, b, c, d = st.columns(4)
    a.metric("数据契约", "通过" if report["contract_status"] == "passed" else "需修复")
    b.metric("核心样品", report["sample_count"])
    c.metric("因果推断", "未就绪" if not report["scientific_readiness"]["causal_inference_ready"] else "就绪")
    d.metric("机器学习", "未就绪" if not report["scientific_readiness"]["machine_learning_ready"] else "就绪")

    if report["contract_status"] == "passed":
        st.success("当前文件满足v1.1结构契约；这不等于所有实验字段已经测量完整。")
    else:
        st.error("；".join(report["problems"]))

    st.subheader("五层数据与物理实测准备度")
    layer_labels = {
        "samples": "样品主数据", "composition": "成分摘要", "composition_observations": "成分逐项记录",
        "process": "工艺摘要", "microstructure": "组织摘要", "properties": "性能摘要",
        "physics_observations": "物理实测/校正", "process_steps": "逐工序记录",
        "microstructure_observations": "组织逐视场记录", "property_observations": "性能逐试样记录",
        "thermal_simulation_runs": "热模拟运行", "thermal_simulation_points": "热模拟曲线点",
    }
    table = pd.DataFrame(report["tables"])
    table["layer"] = table["layer"].map(lambda value: layer_labels.get(value, value))
    table["essential_completeness"] = (table["essential_completeness"] * 100).round(1)
    table["recommended_completeness"] = (table["recommended_completeness"] * 100).round(1)
    st.dataframe(
        table[["layer", "status", "row_count", "essential_completeness", "recommended_completeness"]].rename(columns={
            "layer": "数据层", "status": "状态", "row_count": "记录数",
            "essential_completeness": "必要字段(%)", "recommended_completeness": "建议字段(%)",
        }),
        hide_index=True,
        width="stretch",
    )

    with st.expander("查看每个样品的缺失字段", expanded=False):
        matrix = pd.DataFrame(report["sample_matrix"])
        matrix["layer"] = matrix["layer"].map(lambda value: layer_labels.get(value, value))
        st.dataframe(
            matrix[["sample_id", "layer", "status", "essential", "recommended", "missing_essential", "missing_recommended"]],
            hide_index=True,
            width="stretch",
        )

    st.subheader("建议补齐顺序")
    for index, action in enumerate(report["next_actions"], start=1):
        st.write(f"{index}. {action}")

    st.info("当前结论仍是 directional_evidence_only：可以做B/R方向性比较，不能据此宣称统计显著、因果机制或训练可靠机器学习模型。")

    with st.expander("未来模型接口", expanded=False):
        st.write("允许逐步加入的模型家族：")
        st.write("、".join(report["future_model_families"]))
        st.write("每个模型必须登记：")
        st.write("、".join(report["physics_model_requirements"]))
        st.json(contract.get("tables", {}).get("physics_observations", {}))

    left, right = st.columns(2)
    left.download_button(
        "下载数据契约报告",
        contract_report_markdown(report).encode("utf-8"),
        file_name="steelai_research_data_contract_report.md",
        mime="text/markdown",
        use_container_width=True,
    )
    right.download_button(
        "下载机器可读检查结果",
        json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="steelai_research_data_contract_result.json",
        mime="application/json",
        use_container_width=True,
    )

with template_tab:
    st.subheader("先确定层级，再填写数值")
    id_table = pd.DataFrame(policy["levels"])[["field", "meaning", "example"]].rename(columns={
        "field": "编号字段", "meaning": "真实含义", "example": "示例",
    })
    st.dataframe(id_table, hide_index=True, width="stretch")
    st.warning("field_id只是同一试样中的视场，不是独立试样；无法确认真实specimen_id时应留空或标记待核验，不能为了统计而编造编号。")

    template_labels = {
        "composition_observations": "成分逐元素记录",
        "process_steps": "工艺逐步骤记录",
        "microstructure_observations": "组织逐视场记录",
        "property_observations": "性能逐试样记录",
        "physics_observations": "物理实测与模型校正记录",
        "thermal_simulation_runs": "热模拟运行记录",
        "thermal_simulation_points": "热模拟曲线点",
    }
    st.write("下载空白模板（只含表头）：")
    columns = st.columns(len(template_labels))
    for slot, (table_name, label) in zip(columns, template_labels.items()):
        slot.download_button(
            label,
            template_csv_bytes(table_name),
            file_name=f"{table_name}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    st.caption("冻结旗舰案例仍是B-DQ与R-DQ；其他真实样品必须先经人工审核登记到samples，再接入后续数据。原始实验文件不复制到项目中。")

with intake_tab:
    st.subheader("标准表导入 · 统一治理入口")
    st.caption("已按 SteelAI 模板整理好的 CSV 走这里；仪器导出或不同格式的数据请使用“SteelData 标准化接入”。")
    st.caption("流程：选择数据层 → 上传 CSV → 本地预检 → 具名审批 → 受控执行 → 仅追加写入。默认不会修改 processed。")
    st.markdown("#### 主要操作")
    intake_labels = {
        "composition_observations": "成分逐元素记录",
        "process_steps": "工艺逐步骤记录",
        "microstructure_observations": "组织逐视场记录",
        "property_observations": "性能逐试样记录",
        "physics_observations": "物理实测与模型校正记录",
        "thermal_simulation_runs": "热模拟运行记录",
        "thermal_simulation_points": "热模拟曲线点",
    }
    selected_label = st.selectbox("要新增哪类数据？", list(intake_labels.values()))
    selected_table = next(key for key, value in intake_labels.items() if value == selected_label)
    st.download_button(
        "下载对应空白模板",
        template_csv_bytes(selected_table),
        file_name=f"{selected_table}.csv",
        mime="text/csv",
    )
    upload = st.file_uploader("上传填写后的CSV", type=["csv"], key=f"intake_{selected_table}")
    if upload is None:
        st.markdown("#### 当前状态")
        st.info("尚未上传。模板可在Excel/WPS中填写后另存为UTF-8 CSV。")
    else:
        try:
            intake_request = register_intake_request(
                st.session_state,
                route="standard_csv",
                selection=uploaded_file_selection([upload]),
                target_table=selected_table,
            )
        except (OSError, ValueError) as exc:
            st.error("无法登记数据选择；未执行导入：" + str(exc))
            st.stop()
        st.caption(
            f"请求已登记：{intake_request.identity.request_id} · "
            f"任务：{intake_request.identity.task_id}（尚未执行）"
        )
        intake_report = validate_intake_csv(selected_table, upload.getvalue())
        governance_preview = preview_intake_governance(intake_report)
        st.markdown("#### 当前状态")
        x, y, z = st.columns(3)
        x.metric("治理状态", governance_preview["state"])
        y.metric("新增记录", intake_report["row_count"])
        z.metric("现有记录", intake_report.get("existing_row_count", 0))
        if governance_preview["issue_codes"]:
            st.caption("治理代码：" + "、".join(governance_preview["issue_codes"]))
        st.markdown("#### 结果")
        if intake_report["errors"]:
            st.error("\n\n".join(f"• {item}" for item in intake_report["errors"]))
        if intake_report["warnings"]:
            st.warning("\n\n".join(f"• {item}" for item in intake_report["warnings"]))
        with st.expander("技术详情 · 规范化数据预览", expanded=False):
            if intake_report["rows"]:
                st.dataframe(pd.DataFrame(intake_report["rows"]), hide_index=True, width="stretch")
            st.caption("系统只保存规范化后的结构化暂存表、审批快照和治理 Manifest，不复制上传的原始文件，也不调用 DeepSeek。")

        st.markdown("#### 人工审批")
        reviewer = st.text_input("本次标准表接入审核人", key=f"intake_reviewer_{selected_table}")
        rationale = st.text_input(
            "审核说明（如何核对身份、单位、来源和警告）",
            key=f"intake_rationale_{selected_table}",
        )
        confirm = st.checkbox(
            "我已核对样品/试样层级、单位、来源状态及全部警告，并确认仅追加写入 processed。",
            key=f"intake_confirm_{selected_table}",
        )
        if st.button(
            "确认追加到 processed",
            type="primary",
            disabled=(intake_report["status"] != "ready" or not confirm
                      or not reviewer.strip() or not rationale.strip()),
            use_container_width=True,
        ):
            # Revalidate immediately before commit; the shared gate checks again under its lock.
            intake_report = validate_intake_csv(selected_table, upload.getvalue())
            if intake_report["status"] != "ready":
                st.error("数据状态发生变化，请重新预检：" + "；".join(intake_report["errors"]))
                st.stop()
            try:
                commit_result = commit_standard_intake_governed(
                    intake_report,
                    reviewer_id=reviewer,
                    rationale=rationale,
                    confirmed=confirm,
                    workflow_identity=intake_request.identity,
                )
            except (ValueError, OSError) as exc:
                st.error("未写入，请重新预检：" + str(exc))
                st.stop()
            record_event(
                "data_intake",
                f"新增{selected_label}",
                f"通过v1.1数据闸门，向{selected_table}追加{commit_result['rows_added']}条记录。",
                evidence={
                    "intake_id": commit_result["governance_intake_id"],
                    "table": selected_table,
                    "rows_added": commit_result["rows_added"],
                    "content_sha256": commit_result["content_sha256"],
                    "request_id": commit_result["request_id"],
                    "task_id": commit_result["task_id"],
                    "run_id": commit_result["run_id"],
                    "task_revision": commit_result["task_revision"],
                },
                tags=["data-contract", "append-only", "portfolio-evidence"],
            )
            st.success(
                f"已追加{commit_result['rows_added']}条记录；治理审计编号："
                f"{commit_result['governance_intake_id']}。刷新页面可查看新的数据状态。"
            )

with steeldata_tab:
    render_steeldata_panel(contract)

next_step_buttons(
    st,
    [
        {"label": "生成可追溯统计", "url": "/analysis?module=statistics"},
        {"label": "返回样品总览", "url": "/projects"},
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
    ],
    key_prefix="data_quality",
    note="只有通过人工审核和质量门禁的数据，才应进入组级描述统计。",
)
