"""WO-31 §4 — 科研薄入口的首页视图。

只做三件事，且都基于真实数据：

1. 显示经校验的项目/任务上下文（来自 ``?project_id=&task_id=``）；
2. 显示薄 API 登记的工具与真实可用性（缺什么就说什么）；
3. 给出与 React 前端的对照说明，便于换 AI/换入口接续。

不读原始科研正文、不写任何正式库、不连接云模型。
"""

from __future__ import annotations

import streamlit as st

API_BASE = "http://127.0.0.1:8760"


def _context_from_query() -> tuple[str, str, str]:
    """Return ``(project_id, task_id, problem)`` after validating against the registry."""
    raw_project = str(st.query_params.get("project_id", "") or "").strip()
    raw_task = str(st.query_params.get("task_id", "") or "").strip()
    if not raw_project and not raw_task:
        return "", "", "未指定项目/任务：地址里没有 project_id/task_id。"
    try:
        from steelai.web_api import registry
    except Exception as exc:  # noqa: BLE001 - the page must not crash on an import problem
        return raw_project, raw_task, f"无法加载项目登记：{exc}"
    try:
        project = registry.find_project(raw_project)
    except Exception as exc:  # noqa: BLE001
        return raw_project, raw_task, f"项目未登记：{raw_project}（{exc}）"
    if not raw_task:
        return project.project_id, "", "已指定项目，但未指定任务：请从 React 入口带着 task_id 打开。"
    tasks = {item.task_id for item in registry.list_tasks(project.project_id)}
    if raw_task not in tasks:
        return project.project_id, raw_task, f"任务未登记于该项目：{raw_task}"
    return project.project_id, raw_task, ""


def render() -> None:
    st.markdown("## SteelAI 科研工作台")
    st.caption("科研专用薄入口 · 只登记已确认的科研页 · 不嵌 PAOS/生活混合首页")

    project_id, task_id, problem = _context_from_query()

    st.markdown("### 当前上下文")
    if problem:
        st.warning(problem)
    if project_id or task_id:
        st.write({"project_id": project_id or "—", "task_id": task_id or "—"})
    else:
        st.info(
            "本项目上下文来自 React 入口的同一 project_id/task_id。"
            f"也可以在地址后加 `?project_id=P01&task_id=T001` 显式指定。"
        )

    st.markdown("### 工具可用性（读自薄 API 的登记）")
    try:
        from steelai.web_api import tools

        rows = [
            {
                "工具": cap["label"],
                "合同": cap["contract"],
                "可用": "是" if cap["available"] else "否",
                "不可用原因": cap["reason"] or "—",
            }
            for cap in tools.capabilities()
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"无法读取工具登记：{exc}")

    st.markdown("### 与 React 入口的关系")
    st.markdown(
        f"""
- React 六页负责选择项目/任务、上传、人审、运行、看表图、下载：<{API_BASE}/>
- 本页只提供科研旧页的**原样**入口，不实现消息协议时不会被当作已接通。
- 两者共享同一 `project_id`/`task_id` 与同一份任务目录，换 AI 读同一 README 即可接续。
- 数据与产物归属：任务目录 `runs/<run_id>/`；正式晋升仍走原 owner 人审。
"""
    )
    st.caption("本页不读原始科研正文、不写正式库、不连接云模型。")


# Streamlit 以脚本方式执行页面文件，因此在模块末尾直接渲染。
render()
