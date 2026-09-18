from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from steelai.data_intake import load_id_policy
from steelai.data_intake_governance import commit_standard_intake_governed, preview_intake_governance
from steelai.event_log import record_event
from steelai.intake_request import register_intake_request, uploaded_file_selection
from steelai.external_data_standardizer import (
    build_standardization_preview,
    canonical_unit_for_field,
    infer_source_unit,
    inspect_external_file,
    suggest_mapping,
    unit_choices,
    xlsx_sheet_names,
)
from steelai.paths import PROCESSED
from steelai.research_data_contract import load_research_contract


TABLE_LABELS = {
    "samples": "样品主数据（新样品先从这里登记）",
    "composition": "成分摘要（每个样品一行）",
    "composition_observations": "成分逐项记录（推荐）",
    "process": "工艺摘要（每个样品一行）",
    "process_steps": "工艺逐步骤记录（推荐）",
    "microstructure": "组织摘要（每个样品一行）",
    "microstructure_observations": "组织逐视场记录（推荐）",
    "properties": "性能摘要（每个样品一行）",
    "property_observations": "性能逐试样记录（推荐）",
    "physics_observations": "物理实测与模型校正记录",
}


def _ordered_fields(spec: dict) -> list[str]:
    fields: list[str] = []
    for group in ("essential_fields", "recommended_fields", "optional_fields", "numeric_fields"):
        for field in spec.get(group, []):
            if field not in fields:
                fields.append(field)
    return fields


def _existing_samples() -> list[str]:
    try:
        frame = pd.read_csv(PROCESSED / "samples.csv", dtype=str, keep_default_na=False)
    except (OSError, ValueError):
        return []
    return sorted(value for value in frame.get("sample_id", pd.Series(dtype=str)).astype(str) if value)


def render_external_standardization() -> None:
    st.subheader("外部文件标准化入库")
    st.caption("选择文件后完成字段映射、单位确认和人工审批。原文件不改动；标准化记录只追加到 SteelAI 标准数据层。")
    st.info("新样品第一次使用时，先导入“样品主数据”；后续成分、工艺、组织和性能记录才能引用该 sample_id。")

    upload = st.file_uploader(
        "1. 选择外部 CSV、TSV 或 XLSX",
        type=["csv", "tsv", "xlsx"],
        max_upload_size=20,
        key="external_standardization_upload",
    )
    if upload is None:
        st.markdown("#### 当前状态")
        st.info("尚未选择文件。系统不会扫描你的文件夹，也不会把文件发送给云端 AI。")
        return

    content = upload.getvalue()
    try:
        intake_request = register_intake_request(
            st.session_state,
            route="external_file",
            selection=uploaded_file_selection([upload]),
        )
    except (OSError, ValueError) as exc:
        st.error("无法登记数据选择；未执行导入：" + str(exc))
        return
    st.caption(
        f"请求已登记：{intake_request.identity.request_id} · "
        f"任务：{intake_request.identity.task_id}（尚未执行）"
    )
    sheet_name = None
    if upload.name.lower().endswith(".xlsx"):
        try:
            sheets = xlsx_sheet_names(content)
        except ValueError as exc:
            st.error(str(exc))
            return
        sheet_name = st.selectbox("工作表", sheets, key="external_standardization_sheet")
    try:
        inspection = inspect_external_file(upload.name, content, sheet_name=sheet_name)
    except ValueError as exc:
        st.error("文件读取失败：" + str(exc))
        return

    st.markdown("#### 文件预览")
    a, b, c = st.columns(3)
    a.metric("来源记录", inspection["row_count"])
    b.metric("来源字段", len(inspection["headers"]))
    c.metric("文件指纹", inspection["source_sha256"][:10].upper())
    st.dataframe(pd.DataFrame(inspection["rows"][:20]), hide_index=True, width="stretch")
    if inspection["warnings"]:
        st.warning("；".join(inspection["warnings"]))

    contract = load_research_contract()
    label = st.selectbox("2. 这些数据要进入哪一层？", list(TABLE_LABELS.values()),
                         index=list(TABLE_LABELS).index("property_observations"),
                         key="external_standardization_table")
    table_name = next(name for name, value in TABLE_LABELS.items() if value == label)
    spec = contract["tables"][table_name]
    suggestions = suggest_mapping(inspection["headers"], table_name)
    policy = load_id_policy()
    source_statuses = [value for value in policy.get("verified_statuses", []) if value != "model_generated"]

    st.markdown("#### 3. 字段对应与单位")
    st.caption("左边是 SteelAI 标准字段，右边选择原文件的列。黄色警告必须在提交前解决；系统不会猜单位或试样身份。")
    mapping: dict[str, str] = {}
    constants: dict[str, str] = {}
    source_units: dict[str, str] = {}
    choices = ["（留空或使用固定值）", *inspection["headers"]]
    essential = set(spec.get("essential_fields", []))
    numeric = set(spec.get("numeric_fields", []))
    fields = _ordered_fields(spec)

    for field in fields:
        if field in {"source_status", "data_status"}:
            continue
        proposed = suggestions.get(field, "")
        index = choices.index(proposed) if proposed in choices else 0
        left, right = st.columns([1, 2])
        left.markdown(f"`{field}`" + (" · 必填" if field in essential else ""))
        selected = right.selectbox(
            f"{field} 的来源列", choices, index=index,
            key=f"external_map_{table_name}_{field}", label_visibility="collapsed",
        )
        source = "" if selected == choices[0] else selected
        mapping[field] = source
        if not source and (field in essential or field in {"sample_id", "property", "unit", "method"}):
            default = ""
            if field == "observation_id":
                default = "OBS-{source8}-{row}"
            elif field == "sample_id" and len(_existing_samples()) == 1:
                default = _existing_samples()[0]
            constants[field] = st.text_input(
                f"{field} 固定值" + ("（可用 {{source8}}、{{row}} 生成记录编号）" if field == "observation_id" else ""),
                value=default, key=f"external_constant_{table_name}_{field}",
            )
        target_unit = canonical_unit_for_field(table_name, field)
        if source and field in numeric and target_unit:
            available_units = unit_choices(target_unit)
            inferred = infer_source_unit(source, target_unit)
            unit_options = ["（请选择来源单位）", *available_units]
            unit_index = unit_options.index(inferred) if inferred in unit_options else 0
            selected_unit = st.selectbox(
                f"{field} 来源单位 → 标准单位 {target_unit}", unit_options, index=unit_index,
                key=f"external_unit_{table_name}_{field}",
            )
            if selected_unit != unit_options[0]:
                source_units[field] = selected_unit

    status_field = "data_status" if table_name == "samples" else "source_status"
    if status_field in fields:
        constants[status_field] = st.selectbox(
            f"{status_field}（本批统一来源状态）", source_statuses,
            index=source_statuses.index("instrument_export") if "instrument_export" in source_statuses else 0,
            key=f"external_status_{table_name}",
        )

    try:
        preview = build_standardization_preview(
            inspection, table_name, mapping, constants=constants, source_units=source_units,
        )
    except (KeyError, ValueError) as exc:
        st.error("映射无效：" + str(exc))
        return

    governance = preview_intake_governance(preview)
    st.markdown("#### 标准化结果")
    x, y, z = st.columns(3)
    x.metric("状态", "可审批" if preview["status"] == "ready" else "需修正")
    y.metric("标准记录", preview["row_count"])
    z.metric("目标数据表", table_name)
    if preview["errors"]:
        st.error("\n\n".join(f"• {item}" for item in preview["errors"]))
    if preview["warnings"]:
        st.warning("\n\n".join(f"• {item}" for item in preview["warnings"]))
    if preview["rows"]:
        st.dataframe(pd.DataFrame(preview["rows"][:50]), hide_index=True, width="stretch")
    transformations = preview["standardization"]["unit_transformations"]
    if transformations:
        st.caption("已确认的单位换算")
        st.dataframe(pd.DataFrame(transformations), hide_index=True, width="stretch")
    st.download_button(
        "下载本次标准化预览 JSON",
        json.dumps({
            "status": preview["status"], "table_name": table_name,
            "standardization": preview["standardization"], "errors": preview["errors"],
            "warnings": preview["warnings"], "rows": preview["rows"],
        }, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"steelai_{table_name}_standardization_preview.json",
        mime="application/json",
    )

    st.markdown("#### 4. 人工批准并入库")
    reviewer = st.text_input("审核人", key=f"external_reviewer_{table_name}")
    rationale = st.text_input("审核说明（说明如何核对字段、单位、样品/试样身份和来源）",
                              key=f"external_rationale_{table_name}")
    confirmed = st.checkbox(
        "我已逐项核对字段映射、单位换算、样品/试样身份和警告，确认只追加写入，不覆盖已有记录。",
        key=f"external_confirm_{table_name}",
    )
    can_commit = (preview["status"] == "ready" and governance["can_request_approval"] and confirmed
                  and reviewer.strip() and rationale.strip())
    if st.button("批准并写入 SteelAI 标准数据层", type="primary", use_container_width=True,
                 disabled=not can_commit, key=f"external_commit_{table_name}"):
        try:
            result = commit_standard_intake_governed(
                preview,
                reviewer_id=reviewer,
                rationale=rationale,
                confirmed=confirmed,
                route="external_file",
                source_id="EXTERNAL-" + inspection["source_sha256"][:20].upper(),
                source_digest=inspection["source_sha256"],
                extra_artifacts={"standardization_record.json": preview["standardization"]},
                workflow_identity=intake_request.identity,
            )
        except (ValueError, OSError) as exc:
            st.error("未写入：" + str(exc))
            return
        record_event(
            "data_intake", f"外部文件标准化：{table_name}",
            f"字段和单位经人工确认后追加 {result['rows_added']} 条标准记录。",
            evidence={
                "intake_id": result["governance_intake_id"], "table": table_name,
                "rows_added": result["rows_added"], "source_sha256": inspection["source_sha256"],
                "standardization_sha256": preview["standardization_sha256"],
                "request_id": result["request_id"], "task_id": result["task_id"],
                "run_id": result["run_id"], "task_revision": result["task_revision"],
            },
            tags=["external-file", "standardization", "append-only"],
        )
        st.success(
            f"已写入 {result['rows_added']} 条标准记录。目标：{result['destination']}；"
            f"审计编号：{result['governance_intake_id']}。"
        )
