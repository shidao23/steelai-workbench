from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from steelai.data import append_row, evidence_path_status, read_rows
from steelai.event_log import record_event
from steelai.ui import next_step_buttons, setup_page

setup_page(st, "证据与微观组织索引", "🗂️")
st.caption("只登记绝对路径与人工提取参数，不复制原始 OM/SEM/EBSD/XRD 文件。")

evidence = read_rows("evidence")
display = []
for row in evidence:
    display.append({**row, "path_status": evidence_path_status(row.get("file_path", ""))})
st.dataframe(pd.DataFrame(display), width="stretch", hide_index=True)

st.subheader("登记一条证据")
samples = read_rows("samples")
with st.form("evidence_form", clear_on_submit=True):
    c1, c2 = st.columns(2)
    evidence_id = c1.text_input("证据 ID", placeholder="B-DQ_EBSD_001")
    sample_id = c2.selectbox("样品", [r["sample_id"] for r in samples])
    modality = c1.selectbox("模态", ["OM", "SEM", "EBSD", "XRD", "Fractography", "Other"])
    file_path = c2.text_input("原始文件绝对路径")
    description = st.text_input("描述")
    extracted = st.text_area("人工提取参数", placeholder="PAG=... μm; HAGB=...%; KAM=...°")
    sensitive = st.checkbox("包含公司/客户/个人或未公开敏感信息")
    submitted = st.form_submit_button("保存索引")

if submitted:
    if not evidence_id or not file_path:
        st.error("证据 ID 和文件路径不能为空。")
    elif not Path(file_path).is_absolute():
        st.error("请填写绝对路径，避免项目移动后失效。")
    elif any(r.get("evidence_id") == evidence_id for r in evidence):
        st.error("证据 ID 已存在。")
    else:
        row = {
            "evidence_id": evidence_id,
            "sample_id": sample_id,
            "modality": modality,
            "file_path": file_path,
            "relative_hint": "",
            "description": description,
            "extracted_parameters": extracted,
            "review_status": "indexed",
            "is_sensitive": str(sensitive).lower(),
        }
        append_row("evidence", row)
        record_event("evidence_indexed", f"登记 {evidence_id}", f"{sample_id} · {modality}", {"evidence_id": evidence_id, "path_status": evidence_path_status(file_path)}, ["microstructure", modality])
        st.success("证据索引已保存。路径只被登记，文件未复制。")
        if sensitive:
            st.warning("该记录已标记敏感。使用 GPT 前请先脱敏，并确认数据权限。")
        st.rerun()

st.info("下一阶段建议：先补齐 sample_id、成像模态、倍率/标尺、取样位置、处理软件、参数提取方法和复核状态，再考虑图像 AI。")

next_step_buttons(
    st,
    [
        {"label": "进入 EBSD 分析", "state": {"evidence_module_selector": "EBSD 分析"}},
        {
            "label": "检查数据质量",
            "url": "/数据与物理?module=quality",
        },
    ],
    key_prefix="evidence_index",
    note="来源、样品和方法信息登记完整后，再进入组织分析或数据质量检查。",
)
