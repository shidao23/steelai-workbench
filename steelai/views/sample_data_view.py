import pandas as pd
import streamlit as st

from steelai.data import read_rows, sample_bundle
from steelai.ui import demo_warning, setup_page

setup_page(st, "样品数据与 B/R 对比", "🔬")
samples = read_rows("samples")
demo_warning(st, samples)
ids = [row["sample_id"] for row in samples]

if not ids:
    st.warning("请先添加样品数据。")
    st.stop()

col1, col2 = st.columns(2)
a_id = col1.selectbox("对照样品", ids, index=0)
b_id = col2.selectbox("比较样品", ids, index=min(1, len(ids)-1))
a, b = sample_bundle(a_id), sample_bundle(b_id)

tabs = st.tabs(["样品卡", "成分", "工艺", "组织", "性能", "字段差异"])
table_map = {
    "样品卡": "samples", "成分": "composition", "工艺": "process",
    "组织": "microstructure", "性能": "properties",
}
for tab, (label, key) in zip(tabs[:5], table_map.items()):
    with tab:
        frame = pd.DataFrame([a[key], b[key]])
        st.dataframe(frame, width="stretch", hide_index=True)

with tabs[5]:
    rows = []
    for table in ("composition", "process", "microstructure", "properties"):
        keys = sorted(set(a[table]) | set(b[table]))
        for key in keys:
            if key == "sample_id":
                continue
            av, bv = a[table].get(key, ""), b[table].get(key, "")
            if av != bv:
                rows.append({"table": table, "field": key, a_id: av, b_id: bv})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

st.caption("空白表示未测/未录入，不等于 0。字段名称和单位应在接入真实数据时统一。")
