from pathlib import Path

import pandas as pd
import streamlit as st

from steelai.event_log import read_events, record_event, safe_output_filename, write_text_artifact
from steelai.paths import PORTFOLIO
from steelai.portfolio import portfolio_markdown
from steelai.portfolio_release import prepare_release_package, validate_release_config
from steelai.run_center import accepted_portfolio_results, collect_run_records
from steelai.ui import setup_page

setup_page(st, "Career Portfolio", "💼")
st.subheader("SteelAI · 材料科研系统框架")
st.caption("当前系统框架｜科研输入、确定性分析、AI 证据协作与可追溯成果；可选扩展单独标注。")
architecture_path = Path(__file__).resolve().parents[1] / "docs" / "assets" / "steelai_system_architecture.png"
st.image(str(architecture_path), width="stretch")
st.download_button(
    "下载架构图（PNG）",
    architecture_path.read_bytes(),
    file_name="SteelAI_系统框架.png",
    mime="image/png",
)
st.divider()
st.subheader("T64 · 岗位作品集与公开发布包")
release_contract = validate_release_config()
r1, r2, r3 = st.columns(3)
r1.metric("发布契约", "通过" if release_contract["status"] == "passed" else "失败")
r2.metric("公开资产", release_contract["required_asset_count"])
r3.metric("能力证据映射", release_contract["claim_count"])
st.info("代码与公开材料已就绪；T63 实测、全新环境复现、视频、技术报告和最终公开审查仍需人工完成。")
if st.button("准备或复用 T64 发布检查包", use_container_width=True):
    try:
        st.session_state["t64_release"] = prepare_release_package()
    except (OSError, ValueError) as exc:
        st.error(str(exc))
if st.session_state.get("t64_release"):
    result = st.session_state["t64_release"]
    st.warning(f"当前状态：{result['status']}。检查包：{Path(result['package']).name}")
st.caption("发布准备包不会执行 Git 提交、GitHub Release、视频录制或人工验收。")
st.divider()
st.subheader("项目实践与成果记录")
events = read_events()
run_records = collect_run_records()
accepted_results = accepted_portfolio_results(run_records)

c1, c2, c3 = st.columns(3)
c1.metric("项目活动记录", len(events))
c2.metric("已验收成果", len(accepted_results))
c3.metric("覆盖模块", len({item.get("module") for item in accepted_results}))

if events:
    st.caption("以下是项目活动日志，用于追溯过程；它们不会直接进入作品集摘要。")
    st.dataframe(pd.DataFrame(events)[["created_at", "event_type", "title", "summary"]].iloc[::-1], width="stretch", hide_index=True)
else:
    st.info("尚无事件。先在分析助手生成报告或登记一条证据。")

if accepted_results:
    st.success("作品集过滤器只纳入 complete、完整性通过且已有具名人工验收的成果。")
else:
    st.warning("当前没有满足作品集门禁的成果；draft、needs_human、blocked 和 invalidated 记录均已排除。")

preview = portfolio_markdown(accepted_results)
st.markdown(preview)

if st.button("生成并沉淀作品集摘要", type="primary"):
    filename = safe_output_filename("career_portfolio")
    path = write_text_artifact(PORTFOLIO, filename, preview)
    record_event(
        "portfolio",
        "生成求职展示摘要",
        f"基于 {len(accepted_results)} 项已验收成果生成",
        {
            "artifact": str(path),
            "accepted_result_ids": [item.get("task_id") for item in accepted_results],
        },
        ["career", "accepted-results-only"],
    )
    st.success(f"已保存：{path}")

st.download_button("下载作品集摘要", preview, file_name="steelai_career_portfolio.md", mime="text/markdown")
st.caption("简历量化成果必须来自已核验真实数据。DEMO 数据只展示产品与工程能力。")
