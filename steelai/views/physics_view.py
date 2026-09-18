import pandas as pd
import streamlit as st

from steelai.data import numeric, read_rows
from steelai.physics import (
    MODEL_FAMILIES,
    calculate_all,
    compare_versions,
    compare_with_experimental_observations,
    default_model_ids,
    load_physics_observations,
    model_by_id,
    model_card_markdown,
    models_for_family,
    specs_as_rows,
    validate_model_registry,
    version_comparison_markdown,
)
from steelai.physics_governance import preview_physics_governance, run_governed_physics
from steelai.ui import demo_warning, next_step_buttons, setup_page


setup_page(st, "物理计算", "⚙️")
samples = read_rows("samples")
compositions = read_rows("composition")
demo_warning(st, samples)
ids = [row["sample_id"] for row in samples]

if not ids:
    st.warning("没有可计算样品。")
    st.stop()

registry_status = validate_model_registry()
if registry_status["status"] != "passed":
    st.error("Physics Model Registry 未通过结构校验：" + "；".join(registry_status["problems"]))
    st.stop()

sid = st.selectbox("选择样品", ids)
raw = next((row for row in compositions if row.get("sample_id") == sid), {})
composition = {
    key: value
    for key, raw_value in raw.items()
    if key not in {"sample_id", "source_status"} and (value := numeric(raw_value)) is not None
}

st.caption(
    f"{registry_status['registry_id']} · {registry_status['model_count']}个公式版本 · "
    "所有输出均为经验模型估算，不是实验真值。缺失成分不会按0代填。"
)
st.caption("T52 共享治理：输入快照 → 公式版本与范围复核 → 具名审批 → 模型结果包 → 完整性验证。")
st.markdown("**输入成分（wt.%）**")
st.dataframe(pd.DataFrame([{"sample_id": sid, **composition}]), width="stretch", hide_index=True)

calculation_tab, registry_tab, experiment_tab = st.tabs(["计算与版本对比", "模型注册表与模型卡", "实验值—模型值—残差"])
physics_observations = load_physics_observations()

with calculation_tab:
    st.markdown("#### 主要操作")
    defaults = default_model_ids()
    selected_models: dict[str, str] = {}
    selectors = st.columns(3)
    for index, family in enumerate(MODEL_FAMILIES):
        models = models_for_family(family)
        options = [item["model_id"] for item in models]
        selected_models[family] = selectors[index % 3].selectbox(
            f"{family}公式版本",
            options,
            index=options.index(defaults[family]),
            format_func=lambda model_id: f"{model_by_id(model_id)['display_name']} · {model_by_id(model_id)['model_version']}",
            key=f"physics_model_{family}",
        )

    results = calculate_all(composition, set(composition), selected_models)
    governed_preview = preview_physics_governance(
        sid,
        composition,
        provided_fields=set(composition),
        selected_models=selected_models,
        observations=physics_observations,
        source_status=str(raw.get("source_status", "registered_composition_snapshot")),
    )
    st.markdown("#### 当前状态")
    status_a, status_b, status_c = st.columns(3)
    status_a.metric("治理状态", governed_preview.state)
    status_b.metric("公式数量", len(governed_preview.results))
    status_c.metric("范围/输入事项", len(governed_preview.warnings) + len(governed_preview.error_codes))
    st.markdown("#### 结果")
    metrics = st.columns(3)
    for index, result in enumerate(results):
        display_value = "SKIPPED" if result.value is None else f"{result.value:g} {result.unit}"
        metrics[index % 3].metric(result.key, display_value, help=f"{result.model_id} · {result.status}")

    with st.expander("技术详情 · 公式、来源、适用范围与警告", expanded=False):
        for result in results:
            st.markdown(f"**{result.key} · {result.model_version} · {result.status}**")
            st.code(result.formula)
            st.write("模型ID：", result.model_id)
            st.write("来源：", result.source)
            st.write("审核 / 校正状态：", result.review_status, "/", result.calibration_status)
            for warning in result.warnings:
                st.warning(warning)
            if not result.warnings:
                st.success("未触发缺失输入或适用范围警告。")
            st.caption("局限：" + result.note)

    st.markdown("#### 保存可追溯模型结果")
    st.caption("上方数值是即时预览；只有完成人工复核，才发布带输入快照、模型卡和 Governance Manifest 的结果包。")
    physics_reviewer = st.text_input("Physics 运行审核人", key="physics_governance_reviewer")
    physics_rationale = st.text_input(
        "审核说明（公式适用范围、输入来源与使用边界）",
        key="physics_governance_rationale",
    )
    accept_scope_warnings = st.checkbox(
        "我已阅读并接受当前适用范围警告；结果只作为经验公式估算值。",
        disabled=not governed_preview.warnings,
        value=not governed_preview.warnings,
        key="physics_governance_warning_acceptance",
    )
    if st.button(
        "批准并保存治理结果包",
        type="primary",
        disabled=(governed_preview.state == "blocked" or not physics_reviewer.strip()
                  or not physics_rationale.strip()
                  or (bool(governed_preview.warnings) and not accept_scope_warnings)),
        key="physics_governance_publish",
    ):
        try:
            governed_result = run_governed_physics(
                sid,
                composition,
                reviewer_id=physics_reviewer,
                rationale=physics_rationale,
                accept_warnings=accept_scope_warnings,
                provided_fields=set(composition),
                selected_models=selected_models,
                observations=physics_observations,
                source_status=str(raw.get("source_status", "registered_composition_snapshot")),
            )
        except (ValueError, OSError) as exc:
            st.error("Physics 结果未发布：" + str(exc))
        else:
            st.success(
                f"治理结果已保存：{governed_result['run_id']}"
                + ("（复用既有完整结果）" if governed_result["reused"] else "")
            )
            st.code(governed_result["package"], language=None)

    st.divider()
    st.subheader("公式版本对比")
    comparison_family = st.selectbox("选择要比较的物理量", MODEL_FAMILIES, key="physics_comparison_family")
    version_results = compare_versions(comparison_family, composition, set(composition))
    comparison_rows = [{
        "model_id": item.model_id,
        "model_version": item.model_version,
        "value": item.value,
        "unit": item.unit,
        "status": item.status,
        "warnings": "；".join(item.warnings),
    } for item in version_results]
    st.dataframe(pd.DataFrame(comparison_rows), width="stretch", hide_index=True)
    comparison_report = version_comparison_markdown(sid, comparison_family, version_results)
    st.download_button(
        "下载版本对比报告",
        comparison_report,
        file_name=f"{sid}_{comparison_family}_model_version_comparison.md",
        mime="text/markdown",
    )
    st.caption("版本间接近不代表准确；正式校正需要具有来源记录的匹配实验值。")

with registry_tab:
    st.dataframe(pd.DataFrame(specs_as_rows()), width="stretch", hide_index=True)
    card_model_id = st.selectbox(
        "选择模型卡",
        [row["model_id"] for row in specs_as_rows()],
        format_func=lambda model_id: f"{model_by_id(model_id)['model_family']} · {model_by_id(model_id)['display_name']}",
        key="physics_model_card",
    )
    card = model_card_markdown(card_model_id)
    st.markdown(card)
    st.download_button(
        "下载模型卡",
        card,
        file_name=f"{card_model_id}_model_card.md",
        mime="text/markdown",
    )

with experiment_tab:
    selected_results = calculate_all(composition, set(composition), selected_models)
    comparisons = compare_with_experimental_observations(sid, selected_results, physics_observations)
    if not physics_observations:
        st.info(
            "尚无 physics_observations.csv。请通过“数据质量与扩展准备 → 导入与校验”追加热膨胀/热模拟实验记录；"
            "不要直接修改 processed 数据。"
        )
    elif not comparisons:
        st.info(f"当前没有与 {sid} 及所选物理量匹配的 experimental 记录。")
    else:
        display = []
        for row in comparisons:
            display.append({**row, "warnings": "；".join(row["warnings"])})
        st.dataframe(pd.DataFrame(display), width="stretch", hide_index=True)
    st.caption(
        "残差约定：模型值 − 实验值。实验值、模型值和残差保持独立字段；当前界面只读，不写回、不拟合，"
        "也不会用校正结果覆盖原始公式。"
    )

next_step_buttons(
    st,
    [
        {"label": "进入数据处理", "url": "/intake"},
        {"label": "返回样品总览", "url": "/projects"},
        {"label": "查看运行与成果", "url": "/analysis?module=runs"},
    ],
    key_prefix="physics",
    note="物理计算完成后，先核对实验观测与数据门禁，再决定是否进入正式统计。",
)
