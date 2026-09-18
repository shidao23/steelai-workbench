from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="SteelAI Workbench",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.session_state["_steelai_router_configured"] = True

navigation = st.navigation({
    "日常研究": [
        st.Page("steelai/views/dashboard_view.py", title="首页", icon="🏠", url_path="home", default=True),
        st.Page("pages/1_数据与物理.py", title="项目与样品", icon="🧬", url_path="projects"),
        st.Page("pages/2_研究助手.py", title="数据处理", icon="📥", url_path="intake"),
        st.Page("pages/3_组织与证据.py", title="分析与报告", icon="📊", url_path="analysis"),
        st.Page("pages/4_模型与自动化.py", title="AI 助手", icon="✨", url_path="assistant"),
    ],
    "系统工具": [
        st.Page("pages/5_Career_Portfolio.py", title="作品集与发布", icon="💼", url_path="portfolio"),
        st.Page("pages/6_高级功能.py", title="实验室与高级功能", icon="⚙️", url_path="advanced"),
    ],
})
navigation.run()
