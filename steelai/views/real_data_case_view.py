from __future__ import annotations

import pandas as pd
import streamlit as st

from steelai.governance import GovernanceError
from steelai.real_data_case import (
    latest_real_data_case,
    run_real_data_case,
    validate_real_data_case_contract,
)
from steelai.ui import next_step_buttons, setup_page


setup_page(st, "真实钢板数据案例", "🧱")
st.caption("UCI 公开真实工业数据 · CC BY 4.0 · CPU 轻量运行 · 不需要本地或云端 AI")

contract = validate_real_data_case_contract()
c1, c2, c3, c4 = st.columns(4)
c1.metric("案例契约", "通过" if contract["status"] == "passed" else "失败")
c2.metric("数据规模", "1941 行")
c3.metric("输入特征", "27")
c4.metric("缺陷类别", "7")

st.subheader("主要操作")
st.write("运行会从 UCI 官方地址下载约 99 KB 的数据，校验固定 SHA-256，再执行冻结划分、基线和轻量 kNN。原始数据不会写入仓库或结果包。")
if st.button("运行或复用 T62 真实数据案例", type="primary", width="stretch"):
    try:
        result = run_real_data_case()
    except GovernanceError as exc:
        st.error(f"运行被治理门禁阻止：{exc.code} · {exc.message}")
    except Exception as exc:
        st.error(f"运行失败：{type(exc).__name__}。可按 T62 文档下载官方 ZIP 后离线运行。")
    else:
        st.session_state["t62_last_result"] = result
        st.success("T62 技术链路通过；当前仍是待人工复核的 working_candidate。")

st.subheader("最近结果")
latest = latest_real_data_case()
if latest is None:
    st.info("尚无本机 T62 结果。运行按钮只生成候选，不会自动加入正式证据或作品集。")
else:
    baseline = latest["test_metrics"]["baseline"]
    improved = latest["test_metrics"]["improved"]
    a, b, c, d = st.columns(4)
    a.metric("选中 k", latest["selected_k"])
    b.metric("测试 Accuracy", f"{improved['accuracy']:.3f}", delta=f"{improved['accuracy'] - baseline['accuracy']:+.3f}")
    c.metric("测试 Macro F1", f"{improved['macro_f1']:.3f}", delta=f"{improved['macro_f1'] - baseline['macro_f1']:+.3f}")
    d.metric("测试误分", latest["test_error_count"])
    st.dataframe(
        pd.DataFrame([
            {
                "模型": "多数类基线",
                "Accuracy": baseline["accuracy"],
                "Balanced accuracy": baseline["balanced_accuracy"],
                "Macro F1": baseline["macro_f1"],
            },
            {
                "模型": "标准化距离加权 kNN",
                "Accuracy": improved["accuracy"],
                "Balanced accuracy": improved["balanced_accuracy"],
                "Macro F1": improved["macro_f1"],
            },
        ]),
        hide_index=True,
        width="stretch",
    )
    st.success(f"完整性：{latest['integrity_status']} · 结果：{latest['result_level']}")
    st.caption(f"报告位置：{latest['report_relative_path']}")

with st.expander("数据、模型与科研边界"):
    st.markdown(
        """
        - 官方来源：UCI Machine Learning Repository，数据集 ID 198，DOI `10.24432/C5J88N`。
        - 数据许可：CC BY 4.0；公开使用必须保留署名。
        - 划分：逐类别稳定 SHA-256 排序，60% 训练、20% 验证、20% 测试；测试集不调参。
        - 模型：多数类基线与 CPU 距离加权 kNN；不依赖 GPU、scikit-learn 或大模型。
        - 局限：没有板号/批次键、成分、工艺和组织，不能推出冶金机理、生产部署能力或工艺建议。
        - 人工验收与披露审查前，结果不能进入正式科研证据或作品集。
        """
    )

next_step_buttons(
    st,
    [
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
        {"label": "进入证据验证", "url": "/analysis?module=validation"},
        {"label": "返回首页", "url": "/"},
    ],
    key_prefix="t62_real_data",
    note="先查看模型卡和失败分析；若要进入作品集，需要另行完成具名人工验收与公开披露审查。",
)
