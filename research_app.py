"""WO-31 §4 — 科研专用 Streamlit 薄入口。

与默认 `app.py` 分开：这里**只登记已确认的科研页**，不嵌原 PAOS/生活混合首页，
也不读取生活私有 owner。

上下文约定（对应工单 §4「不能猜 query 参数或默默输出错项目」）：

* 项目/任务来自 ``?project_id=…&task_id=…``；
* 两个值都会经 :mod:`steelai.web_api.registry` **校验**后才显示；
* 缺失或不匹配时明确显示"未指定/未登记"，绝不回落到某个别的项目。

启动（固定可信端口，占用时明确报错，不扫端口）：

```powershell
.\.venv\Scripts\python.exe -m streamlit run research_app.py --server.port 8761 --server.address 127.0.0.1
```

保留 Streamlit 自带的 XSRF/CORS 保护，不用 ``server.enableCORS=false`` 之类的方式强行嵌入。
"""

from __future__ import annotations

import streamlit as st

RESEARCH_PAGES = [
    ("steelai/views/research_home_view.py", "科研首页", "🏠", "home", True),
    ("pages/1_数据与物理.py", "项目与样品", "🧬", "projects", False),
    ("pages/2_研究助手.py", "数据处理", "📥", "intake", False),
    ("pages/3_组织与证据.py", "分析与报告", "📊", "analysis", False),
    ("pages/4_模型与自动化.py", "AI 助手", "✨", "assistant", False),
]

st.set_page_config(
    page_title="SteelAI 科研工作台",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.session_state["_steelai_router_configured"] = True
# 与 React 前端同源的薄 API 地址（只用于展示与跳转，不在这里做写操作）。
st.session_state.setdefault("_research_api_base", "http://127.0.0.1:8760")

navigation = st.navigation({
    "科研工作台": [
        st.Page(path, title=title, icon=icon, url_path=slug, default=is_default)
        for path, title, icon, slug, is_default in RESEARCH_PAGES
    ],
})
navigation.run()
