from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="SteelAI Workbench",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.session_state["_steelai_router_configured"] = True

navigation = st.navigation([
    st.Page("steelai/views/dashboard_view.py", title="科研总览", icon="🧭", default=True),
    st.Page("pages/1_数据与物理.py", title="数据与物理", icon="📊"),
    st.Page("pages/2_研究助手.py", title="研究助手", icon="🧠"),
    st.Page("pages/3_组织与证据.py", title="组织与证据", icon="🔬"),
    st.Page("pages/4_模型与自动化.py", title="模型与自动化", icon="⚙️"),
    st.Page("pages/5_Career_Portfolio.py", title="Career Portfolio", icon="💼"),
])
navigation.run()
