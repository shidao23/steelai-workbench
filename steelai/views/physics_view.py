import json

import pandas as pd
import streamlit as st

from steelai.calphad_adapter import (
    BATCH_SOLVER_MODE,
    INDEPENDENT_SOLVER_MODE,
    PORTFOLIO_DEMO_ID,
    PORTFOLIO_DEMO_LABEL,
    PORTFOLIO_STATUS_PENDING_SIGNATURE,
    SCIENTIFIC_STATUS_BLOCKED,
    calphad_feature_status,
    phase_fraction_csv,
    phase_fraction_curve_markdown,
    phase_fraction_rows,
    preview_phase_fraction_curve,
    preview_portfolio_demo,
    run_phase_fraction_curve,
)
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

calculation_tab, registry_tab, experiment_tab, calphad_tab = st.tabs(
    ["计算与版本对比", "模型注册表与模型卡", "实验值—模型值—残差", "平衡相分数—温度（可选 · T86）"]
)
physics_observations = load_physics_observations()
declared_composition = {
    key: numeric(raw_value)
    for key, raw_value in raw.items()
    if key not in {"sample_id", "source_status"}
}

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

with calphad_tab:
    st.caption(
        "可选功能（T86）：由模型登记册里的 pycalphad 候选提供固定成分下的平衡相分数—温度计算。"
        "输入成分单位 wt.%、温度单位 °C，输出为各相摩尔分数（相内摩尔数占比），压力固定 101325 Pa。"
        "pycalphad 使用独立环境，不是主应用依赖；未配置环境或授权 TDB 时本页签只显示阻断原因。"
    )
    calphad_status = calphad_feature_status()
    calphad_environment = calphad_status.get("environment", {})
    calphad_database = calphad_status.get("database", {})
    calphad_component = calphad_status.get("component", {})
    state_labels = {"ready": "就绪", "blocked": "阻断", "disabled": "已关闭"}
    status_a, status_b, status_c, status_d = st.columns(4)
    status_a.metric("功能状态", state_labels.get(calphad_status["state"], calphad_status["state"]))
    status_b.metric("独立环境", "就绪" if calphad_environment.get("status") == "ready" else "未就绪")
    status_c.metric("pycalphad", str(calphad_component.get("version") or "未登记"))
    registered_count = int(calphad_database.get("registered_count") or 0)
    status_d.metric("已登记 TDB", f"{registered_count} 个" if registered_count else "无")

    # ---------------------------------------------------------------------------------------
    # 区域 1 · 公开合成演示（作品集展示）
    # ---------------------------------------------------------------------------------------
    st.divider()
    st.markdown("### 区域 1 · 公开合成演示（作品集展示）")
    st.caption(
        "公开合成 Fe-C 体系（Fe-0.45 wt.% C）、固定相集合、数据库声明温区内，"
        f"求解模式 `{INDEPENDENT_SOLVER_MODE}`（每个温度点独立进程）。"
        "本演示不读取任何私人实验数据，可运行、可下载，仅用于展示工具链。"
    )
    owner_split = calphad_status.get("status_split", {}) or {}
    if owner_split.get("portfolio_signed"):
        st.success(
            "负责人验收已签署（工程与作品集范围）："
            f"`{owner_split.get('portfolio')}`。"
            f"负责人 `{owner_split.get('responsible_person_id')}`，"
            f"签署时间 `{owner_split.get('signed_at')}`（{owner_split.get('timezone')}），"
            f"范围 `{owner_split.get('decision_scope')}`。"
        )
        st.caption(
            "该签署**只**覆盖公开合成演示的工程与作品集验收，"
            "`scientific_use_approved=false`、`real_sample_curves_published=false`、"
            "`materials_conclusion_approved=false`；记录见 `config/calphad_owner_acceptance_v1.0.json`。"
        )
    else:
        st.warning(
            f"负责人验收尚未签署：工程与作品集状态仍为 `{owner_split.get('portfolio', PORTFOLIO_STATUS_PENDING_SIGNATURE)}`。"
        )
    demo_preview = preview_portfolio_demo()
    if demo_preview.state != "ready":
        st.warning("公开演示当前不可运行（缺失独立环境或授权 TDB）：")
        for gate in demo_preview.gates:
            st.markdown(f"- `{gate.code}` {gate.message}")
    else:
        st.markdown(
            "- 样品：`" + str(PORTFOLIO_DEMO_ID) + "`（" + PORTFOLIO_DEMO_LABEL + "）"
            + "\n- 组元：`" + "、".join(demo_preview.request["components"]) + "`；相集合：`"
            + "、".join(demo_preview.request["phases"]) + "`"
            + "\n- 温度：`"
            + f"{demo_preview.request['temperature']['min_C']:g}–"
            + f"{demo_preview.request['temperature']['max_C']:g} °C`，步长 "
            + f"`{demo_preview.request['temperature']['step_C']:g} °C`，共 "
            + f"`{len(demo_preview.request['temperature']['values_C'])}` 个点"
            + "\n- 数据库：`" + str((demo_preview.request.get("database") or {}).get("database_id"))
            + "`，SHA-256 `" + str((demo_preview.request.get("database") or {}).get("sha256")) + "`"
        )
        st.info(
            "本演示是公开合成输入下的模型预测（`model_prediction_not_experimental_measurement`），"
            "`not_for_scientific_conclusion=true`：不得用于论文结论、真实钢种分析或生产决策。"
        )
        if st.button("运行公开合成演示", type="primary", key="calphad_demo_run"):
            with st.spinner("正在独立进程中逐点求解公开合成演示…"):
                st.session_state["calphad_demo_record"] = run_phase_fraction_curve(demo_preview)
        demo_record = st.session_state.get("calphad_demo_record")
        if isinstance(demo_record, dict):
            if demo_record.get("status") != "computed":
                st.error(
                    "公开演示未产出可信结果："
                    + str((demo_record.get("error") or {}).get("message", "未知原因"))
                )
            else:
                demo_rows = phase_fraction_rows(demo_record)
                if demo_rows:
                    demo_frame = pd.DataFrame(demo_rows)
                    st.dataframe(demo_frame, width="stretch", hide_index=True)
                    demo_phase_columns = [
                        column for column in demo_frame.columns
                        if str(column).endswith("（相摩尔分数）")
                    ]
                    if demo_phase_columns:
                        st.caption("相分数—温度曲线（公开合成演示，不是完整相图）")
                        st.line_chart(
                            demo_frame.set_index("温度 (°C)")[demo_phase_columns]
                        )
                st.caption(
                    f"求解模式 `{demo_record.get('solver_mode')}`；"
                    f"首次成功 `{demo_record.get('point_count_first_attempt_success')}/"
                    f"{demo_record.get('point_count_expected')}` 个点；"
                    f"清单哈希 `{demo_record.get('manifest_digest')}`；"
                    f"pycalphad `{demo_record.get('pycalphad_version')}`；"
                    f"数据库 SHA-256 `{(demo_record.get('database') or {}).get('sha256')}`"
                )
                demo_a, demo_b, demo_c = st.columns(3)
                demo_a.download_button(
                    "下载演示记录 (Markdown)",
                    phase_fraction_curve_markdown(demo_record),
                    file_name=f"{PORTFOLIO_DEMO_ID}_demo.md",
                    mime="text/markdown",
                    key="calphad_demo_md",
                )
                demo_b.download_button(
                    "下载演示记录 (JSON)",
                    json.dumps(demo_record, ensure_ascii=False, indent=2),
                    file_name=f"{PORTFOLIO_DEMO_ID}_demo.json",
                    mime="application/json",
                    key="calphad_demo_json",
                )
                demo_c.download_button(
                    "下载相分数数据 (CSV)",
                    phase_fraction_csv(demo_record),
                    file_name=f"{PORTFOLIO_DEMO_ID}_demo.csv",
                    mime="text/csv",
                    key="calphad_demo_csv",
                )
                with st.expander("演示技术详情", expanded=False):
                    st.write("组元与摩尔分数：", demo_record.get("component_mole_fractions"))
                    st.write("压力 (Pa)：", demo_record.get("pressure_Pa"))
                    st.write("相集合：", demo_record.get("phases"))
                    st.write("允许的结论范围：", (demo_record.get("demo_label"), "不得用于论文/真实钢种/生产决策"))
                    st.json(demo_record.get("point_manifest") or [])

    # ---------------------------------------------------------------------------------------
    # 区域 2 · 真实样品探索（保持 Blocked）
    # ---------------------------------------------------------------------------------------
    st.divider()
    st.markdown("### 区域 2 · 真实样品探索（保持 `Blocked`）")
    st.error(
        f"真实 B-DQ/R-DQ 计算状态：`{SCIENTIFIC_STATUS_BLOCKED}` —— 不发布真实钢种曲线，也不形成材料结论。"
    )
    st.markdown(
        "- 全组元体系（16 个组元条目）超过本机 pycalphad 0.11.2 的实测求解容量（上界 13）。\n"
        "- 缩减体系在 **B-DQ 的 875 °C 与 900 °C** 附近不稳定收敛：全新进程中重复求解同一单点条件，"
        "900 °C 成功 1/8、875 °C 成功 2/4，失败形态为“没有任何相摩尔数”。\n"
        "- 批量模式与独立点模式在 **R-DQ 675 °C** 的相分数差异约 **`1.069×10⁻⁴`**（容差 `1e-7`），"
        "两种模式得到相同三相组合但相分数不同。\n"
        "- 因此两条真实曲线都不发布；此前全部失败证据保留在 "
        "`config/calphad_phase4_evidence_v1.0.json`、`config/calphad_phase5_evidence_v1.0.json` 与 "
        "`docs/T86_PHASE5_INDEPENDENT_POINTS.md`，不删除、不改写。"
    )
    st.caption(
        "本功能定位为求职作品集中的开源计算热力学探索，不承担真实钢种科研分析；"
        "真实科研使用需先解决求解稳定性问题并完成具名科研审批。"
    )

    st.markdown("#### 当前状态")
    if calphad_status["state"] == "ready":
        st.success(calphad_status["headline"])
    elif calphad_status["state"] == "disabled":
        st.info(calphad_status["headline"])
    else:
        st.warning(calphad_status["headline"])
        for blocking in calphad_status.get("blocking", []):
            st.markdown(f"- `{blocking['code']}` {blocking['message']}")
        st.caption(
            "启用条件：(1) 建立独立 Python 环境并安装已登记固定版本的 pycalphad；"
            "(2) 提供有使用授权且适用于该钢种的 TDB，并按 `config/calphad_tdb.example.json` "
            "登记来源、授权依据、覆盖元素与 SHA-256。两项完成前本页签不执行任何计算，其余物理计算不受影响。"
        )
        st.caption(
            f"第三方登记：{calphad_component.get('official_repo')} · 许可证 {calphad_component.get('license_spdx')} · "
            f"固定版本 {calphad_component.get('version')}（{calphad_component.get('version_pin_status')}）· "
            f"源码引用 {calphad_component.get('source_ref')}"
        )

    if calphad_status["state"] == "ready":
        st.markdown("#### 主要操作")
        st.caption("Fe 若按余量计算必须由用户具名确认；任何非零元素不在 TDB 覆盖范围内都会阻断计算。")
        range_a, range_b, range_c = st.columns(3)
        calphad_min_c = range_a.number_input("起始温度 (°C)", value=600.0, step=10.0, key="calphad_min_c")
        calphad_max_c = range_b.number_input("终止温度 (°C)", value=900.0, step=10.0, key="calphad_max_c")
        calphad_step_c = range_c.number_input(
            "温度步长 (°C)", value=10.0, min_value=0.5, step=10.0, key="calphad_step_c"
        )
        database_ids = list(calphad_database.get("database_ids") or [])
        calphad_database_id = ""
        if len(database_ids) > 1:
            calphad_database_id = st.selectbox("使用的 TDB", database_ids, key="calphad_database_id")
        elif database_ids:
            calphad_database_id = database_ids[0]
            st.caption(f"使用的 TDB：`{calphad_database_id}`")

        calphad_kwargs = {
            "sample_id": sid,
            "database_id": calphad_database_id,
            "temperature_min_C": calphad_min_c,
            "temperature_max_C": calphad_max_c,
            "step_C": calphad_step_c,
            "environment": calphad_environment,
        }
        preliminary = preview_phase_fraction_curve(declared_composition, **calphad_kwargs)
        fe_balance_wt_pct = preliminary.composition.get("fe_balance_wt_pct")
        approved_exclusions = list(preliminary.composition.get("approved_exclusion_elements") or [])
        fe_required = bool(preliminary.composition.get("fe_balance_confirmation_required"))

        confirm_a, confirm_b = st.columns(2)
        with confirm_a:
            if fe_required and fe_balance_wt_pct is not None:
                fe_confirmed = st.checkbox(
                    f"我确认 Fe 按余量计算：Fe = 100 - Σ其他元素 = {fe_balance_wt_pct:.4f} wt.%",
                    key="calphad_fe_confirm",
                )
                fe_confirmer = st.text_input("Fe 余量确认人（具名）", key="calphad_fe_confirmer")
            else:
                fe_confirmed = bool(preliminary.composition.get("fe_balance_confirmed"))
                fe_confirmer = str(preliminary.composition.get("fe_balance_confirmed_by") or "")
                st.caption("样品成分已提供 Fe 数值，不需要余量确认。")
        with confirm_b:
            st.caption(
                "受控元素排除（版本化政策 `config/calphad_exclusion_policy_v1.2.json`，"
                "只作用于政策已批准的样品与元素）："
            )
            st.markdown(
                "- 政策已批准元素："
                + ("、".join(approved_exclusions) if approved_exclusions else "无（严格模式：任何未覆盖的非零元素都会阻断）")
            )
            exclusion_confirmer = st.text_input(
                "受控排除确认人（具名；本次运行会记录排除清单、类别、原始值与数据库哈希）",
                key="calphad_exclusion_confirmer",
            )

        st.markdown("##### 12 组元缩减体系具名批准（真实样品运行前置条件）")
        st.caption(
            "固定政策 `steel_matrix_equilibrium_v1` + 固定相集合 `steel_matrix_major_carbides_v1`。"
            "代码不代填姓名，也不提供默认值；缺少任一项即以 `CALPHAD-COMP-011` 阻断。"
        )
        approval_a, approval_b = st.columns(2)
        with approval_a:
            reduced_reviewer = st.text_input("reviewer_id（具名批准人）", key="calphad_reduced_reviewer")
            reduced_approved_at = st.text_input(
                "批准时间（YYYY-MM-DD 或 ISO 8601）", key="calphad_reduced_approved_at"
            )
        with approval_b:
            reduced_reason = st.text_area(
                "批准理由", key="calphad_reduced_reason", height=100
            )
        reduced_acknowledged = st.checkbox(
            "我确认本次计算采用 12 组元缩减体系。B、N、P、S、As、Sn、Sb、O、W 未进入计算；"
            "结果只能用于 Fe 基体相和已验证主要碳化物的平衡趋势探索，"
            "不能用于评价这些被排除元素、夹杂物、碳氮化物、晶界偏聚或实际组织。",
            key="calphad_reduced_ack",
        )

        calphad_preview = preview_phase_fraction_curve(
            declared_composition,
            fe_balance_confirmed_by=fe_confirmer if fe_confirmed else "",
            controlled_exclusions_confirmed_by=exclusion_confirmer,
            reduced_system_reviewer_id=reduced_reviewer,
            reduced_system_approved_at=reduced_approved_at,
            reduced_system_approval_reason=reduced_reason,
            reduced_system_acknowledged=reduced_acknowledged,
            **calphad_kwargs,
        )
        for gate in calphad_preview.gates:
            st.error(f"{gate.code}：{gate.message}")
        for warning in calphad_preview.warnings:
            st.warning(warning)
        notice = calphad_preview.to_dict().get("limitation_notice", {})
        st.warning("限制声明（必须随结果一同引用）：" + str(notice.get("zh", "")))
        if not calphad_preview.gates:
            st.caption(
                "全部前置门禁已通过：授权 TDB 与 SHA-256 校验一致、兼容性门禁为 passed，"
                "成分推导出的组元与固定缩减体系一致，固定相集合均在数据库中，"
                "具名批准字段完整，温度区间有效。计算将在独立解释器中执行。"
            )
        if st.button(
            "计算平衡相分数—温度",
            type="primary",
            disabled=bool(calphad_preview.gates),
            key="calphad_run",
        ):
            with st.spinner("正在独立环境中求解平衡相分数…"):
                calphad_record = run_phase_fraction_curve(calphad_preview)
            st.session_state["calphad_record"] = calphad_record

        st.markdown("#### 结果")
        calphad_record = st.session_state.get("calphad_record")
        if not isinstance(calphad_record, dict):
            st.info("尚未计算。确认上方输入与门禁后点击“计算平衡相分数—温度”。")
        elif calphad_record.get("sample_id") != sid:
            st.info(f"最近一次计算属于样品 `{calphad_record.get('sample_id')}`，请切换样品后重新计算。")
        elif calphad_record.get("status") != "computed":
            st.error("计算未产出可信结果：" + str((calphad_record.get("error") or {}).get("message", "未知原因")))
            st.json(calphad_record.get("error") or {})
        else:
            calphad_rows = phase_fraction_rows(calphad_record)
            st.dataframe(pd.DataFrame(calphad_rows), width="stretch", hide_index=True)
            phase_columns = [column for column in pd.DataFrame(calphad_rows).columns if column.endswith("（相摩尔分数）")]
            if phase_columns:
                chart_frame = pd.DataFrame(calphad_rows).set_index("温度 (°C)")[phase_columns]
                st.caption("相分数—温度曲线（固定成分下的截面，不是完整相图）")
                st.line_chart(chart_frame)
            result_notice = calphad_record.get("limitation_notice", {}) or {}
            st.warning("限制声明（随每个导出文件一同保存）：" + str(result_notice.get("zh", "")))
            st.caption(
                f"结果名称：{calphad_record.get('result_label')}。"
                "输出基准：各相摩尔分数（相内摩尔数占比），不是质量分数。"
                f"结果类型 `{calphad_record.get('result_type')}`，复核状态 `{calphad_record.get('review_status')}`；"
                f"成分体系 `{(calphad_record.get('component_profile') or {}).get('profile_id')}`，"
                f"相集合 `{(calphad_record.get('phase_profile') or {}).get('profile_id')}`；"
                f"求解模式 `{calphad_record.get('solver_mode')}`"
                f"（每个温度点独立进程：`{calphad_record.get('point_count_first_attempt_success')}/"
                f"{calphad_record.get('point_count_expected')}` 个点首次成功，"
                f"清单哈希 `{calphad_record.get('manifest_digest')}`）；"
                f"缩减成分体系 `{calphad_record.get('reduced_component_system')}`，"
                f"被排除元素 `{calphad_record.get('excluded_elements')}`；"
                "未写回正式实验数据，也不得替代实验测量。"
            )
            not_computed = calphad_record.get("not_computed_in_this_phase") or []
            if not_computed:
                st.info("本阶段明确不计算：" + "、".join(str(item) for item in not_computed))
            for warning in calphad_record.get("warnings", []):
                st.warning(warning)
            download_a, download_b, download_c = st.columns(3)
            download_a.download_button(
                "下载计算记录 (Markdown)",
                phase_fraction_curve_markdown(calphad_record),
                file_name=f"{sid}_calphad_phase_fraction.md",
                mime="text/markdown",
            )
            download_b.download_button(
                "下载计算记录 (JSON)",
                json.dumps(calphad_record, ensure_ascii=False, indent=2),
                file_name=f"{sid}_calphad_phase_fraction.json",
                mime="application/json",
            )
            download_c.download_button(
                "下载相分数数据 (CSV)",
                phase_fraction_csv(calphad_record),
                file_name=f"{sid}_calphad_phase_fraction.csv",
                mime="text/csv",
            )
            with st.expander("技术详情 · 输入基准、受控排除、TDB 来源与哈希、模型输入", expanded=False):
                st.write("输入成分（wt.%）：", calphad_preview.to_dict()["composition"]["provided_wt_pct"])
                st.write("Fe 余量确认人：", calphad_record["composition_basis"].get("fe_balance_confirmed_by") or "不适用")
                st.write("受控排除确认人：", calphad_record.get("controlled_exclusions_confirmed_by") or "不适用")
                st.write("缩减体系具名批准：", calphad_record.get("reduced_system_approval") or {})
                st.write("成分体系：", calphad_record.get("component_profile") or {})
                st.write("相集合：", calphad_record.get("phase_profile") or {})
                st.write("已知模型损失：", calphad_record.get("model_losses") or {})
                st.write("求解模式：", calphad_record.get("solver_mode"))
                st.write("独立点清单：", calphad_record.get("point_manifest") or [])
                st.write("清单完整性哈希：", calphad_record.get("manifest_digest"))
                st.write("版本与哈希：", calphad_record.get("component_versions_and_hashes") or {})
                st.write("受控元素排除（逐次运行记录）：", calphad_record.get("controlled_exclusions") or [])
                st.write("排除政策：", calphad_record.get("exclusion_policy") or {})
                st.write("数据库兼容性门禁：", calphad_record.get("database_compatibility") or {})
                st.write("原子量来源：", calphad_record["composition_basis"].get("atomic_weights_source"))
                st.write("原子量状态：", calphad_record["composition_basis"].get("atomic_weights_source_status"))
                st.write("模型输入组元与摩尔分数：", calphad_record.get("component_mole_fractions"))
                st.write("TDB 路径：", calphad_record["database"].get("path"))
                st.write("TDB SHA-256：", calphad_record["database"].get("sha256"))
                st.write("TDB 授权：", calphad_record["database"].get("license_or_authorization"))
                st.write("pycalphad：", calphad_record.get("pycalphad_version"))
                st.write("模型输入摘要：", calphad_record.get("model_input_digest"))
                st.write("结果摘要：", calphad_record.get("result_digest"))
                st.caption("完整请求快照（未执行任何写回）：")
                st.json(calphad_preview.request or {})

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
