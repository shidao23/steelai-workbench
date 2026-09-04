import pandas as pd
import streamlit as st

from steelai.event_log import read_events, record_event, safe_output_filename, write_text_artifact
from steelai.paths import PORTFOLIO
from steelai.portfolio import portfolio_markdown
from steelai.ui import setup_page

setup_page(st, "Career Portfolio", "💼")
events = read_events()

c1, c2, c3 = st.columns(3)
c1.metric("可追溯事件", len(events))
c2.metric("分析报告", sum(e.get("event_type") == "analysis" for e in events))
c3.metric("证据登记", sum(e.get("event_type") == "evidence_indexed" for e in events))

if events:
    st.dataframe(pd.DataFrame(events)[["created_at", "event_type", "title", "summary"]].iloc[::-1], width="stretch", hide_index=True)
else:
    st.info("尚无事件。先在分析助手生成报告或登记一条证据。")

preview = portfolio_markdown(events)
st.markdown(preview)

if st.button("生成并沉淀作品集摘要", type="primary"):
    filename = safe_output_filename("career_portfolio")
    path = write_text_artifact(PORTFOLIO, filename, preview)
    record_event("portfolio", "生成求职展示摘要", f"基于 {len(events)} 条既有事件生成", {"artifact": str(path)}, ["career"])
    st.success(f"已保存：{path}")

st.download_button("下载作品集摘要", preview, file_name="steelai_career_portfolio.md", mime="text/markdown")
st.caption("简历量化成果必须来自已核验真实数据。DEMO 数据只展示产品与工程能力。")
