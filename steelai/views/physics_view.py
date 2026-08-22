import pandas as pd
import streamlit as st

from steelai.data import numeric, read_rows
from steelai.physics import calculate_all, specs_as_rows
from steelai.ui import demo_warning, setup_page
from steelai.v01_adapter import evaluate as evaluate_v01
from steelai.v01_adapter import is_available as v01_available

setup_page(st, "Physics Engine", "⚙️")
samples = read_rows("samples")
compositions = read_rows("composition")
demo_warning(st, samples)
ids = [row["sample_id"] for row in samples]

if not ids:
    st.warning("没有可计算样品。")
    st.stop()

sid = st.selectbox("选择样品", ids)
sample = next(row for row in samples if row.get("sample_id") == sid)
steel_id = sample.get("steel", "")

using_v01 = v01_available() and steel_id in {"B", "R"}
if using_v01:
    model_rows, composition, source_metadata = evaluate_v01(steel_id)
    st.success("已连接现有 WearSteel-AI v0.1 Physics Engine（13 个模型）。")
    st.caption(f"成分来源：{source_metadata.get('source_file', '')} · {source_metadata.get('source_location', '')} · {source_metadata.get('verification_status', '')}")
else:
    raw = next((row for row in compositions if row.get("sample_id") == sid), {})
    composition = {k: v for k, value in raw.items() if k not in {"sample_id", "source_status"} and (v := numeric(value)) is not None}

st.markdown("**输入成分（wt.%）**")
st.dataframe(pd.DataFrame([{"sample_id": sid, **composition}]), width="stretch", hide_index=True)

if using_v01:
    displayable = [row for row in model_rows if row["value"] is not None]
    cols = st.columns(3)
    for i, row in enumerate(displayable):
        cols[i % 3].metric(row["name"], f"{row['value']:.3f} {row['unit']}")
    for row in model_rows:
        value_text = "SKIPPED" if row["value"] is None else f"{row['value']:.3f} {row['unit']}"
        with st.expander(f"{row['name']} · {row['status']} · {value_text}"):
            st.code(row["formula"])
            st.write("适用对象：", row["applicability"])
            st.write("范围依据：", row["range_basis"])
            st.markdown(f"来源：[{row['source']}]({row['source_url']})")
            for warning in row["warnings"]:
                st.warning(warning)
            for limitation in row["limitations"]:
                st.caption("局限：" + limitation)
            if not row["warnings"]:
                st.success("未触发 v0.1 范围或缺失输入警告。")
else:
    results = calculate_all(composition, set(composition))
    cols = st.columns(3)
    for i, result in enumerate(results):
        cols[i % 3].metric(result.key, f"{result.value:g} {result.unit}")
    for result in results:
        with st.expander(f"{result.label} · {result.review_status}"):
            st.code(result.formula)
            st.write("来源：", result.source)
            st.write(result.note)
            for warning in result.warnings:
                st.warning(warning)

st.divider()
st.subheader("公式注册表")
if using_v01:
    st.dataframe(pd.DataFrame(model_rows)[["model_id", "family", "name", "output_name", "formula", "source", "status"]], width="stretch", hide_index=True)
    st.caption("注册表直接来自现有 WearSteel-AI v0.1。SKIPPED 表示输入不足，WARNING 表示范围或证据边界被触发。")
else:
    st.dataframe(pd.DataFrame(specs_as_rows()), width="stretch", hide_index=True)
    st.caption("当前使用内置备用公式。配置并连接 WearSteel-AI v0.1 后会切换到完整 13 模型引擎。")
