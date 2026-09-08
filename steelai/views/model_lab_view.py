from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from steelai.event_log import record_event
from steelai.model_lab import (
    find_dq_fractography_dir,
    gpu_status,
    micro_sam_status,
    model_statuses,
    save_pilot_manifest,
    scan_sem_directory,
    select_balanced_pilot,
    smoke_test_report,
    tif_preview,
)
from steelai.settings import load_settings
from steelai.ui import next_step_buttons, setup_page


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REVIEW30_VALUE = os.environ.get("STEELAI_REVIEW30_ROOT") or load_settings().get("tools", {}).get("review30_root", "")
REVIEW30_ROOT = Path(_REVIEW30_VALUE).expanduser() if _REVIEW30_VALUE else PROJECT_ROOT / ".not-configured" / "review30_root"
REVIEW30_SEED = REVIEW30_ROOT / "B-DQ-1-06_review30_seed.tif"
REVIEW30_TABLE = REVIEW30_ROOT / "B-DQ-1-06_review30_table.csv"
REVIEW30_MAP = REVIEW30_ROOT / "B-DQ-1-06_review30_map.png"
REVIEW30_REVIEWED = REVIEW30_ROOT / "B-DQ-1-06_review30_reviewed.tif"
AUTO_STANDARD_PATH = PROJECT_ROOT / "config" / "micro_sam_auto_standard_v0.2.json"
BATCH_ROOT = PROJECT_ROOT / "outputs" / "model_lab" / "auto_dimple" / "BR10_1000x_v0.1"
BATCH_COMPARISON = BATCH_ROOT / "br_comparison_v0.1.json"
BATCH_SUMMARY = BATCH_ROOT / "br_image_summary_v0.1.csv"
BATCH_PLOT = BATCH_ROOT / "br_metric_boxplots_v0.1.png"
BATCH_REPORT = BATCH_ROOT / "B_vs_R_AutoDimple_preliminary_report_v0.1.md"


def _render_acceptance_boundary() -> None:
    with st.expander("科研验收边界"):
        st.markdown(
            """
            - 原始 TIF 保持只读；模型输出进入独立试验目录。
            - B/R 使用相同倍率、像素标定、裁剪与提示规则。
            - 先由人定义目标类别，模型不能自行发明类别。
            - 至少抽取 3 张图复核漏分、错分和修正时间，并保留失败案例。
            - 只有通过复核的参数才可写入正式微观组织数据。
            """
        )


def _render_next_steps() -> None:
    next_step_buttons(
        st,
        [
            {"label": "查看任务与结果", "state": {"model_module_selector": "任务与结果"}},
            {
                "label": "进入证据验证",
                "url": "/研究助手?module=validation",
            },
        ],
        key_prefix="model_lab",
        note="模型输出先查看任务记录并完成人工复核；只有接纳后的结果才能进入证据验证。",
    )


setup_page(st, "模型实验室", "🧪")
st.caption("模型结果与正式科研数据保持隔离；先选择当前关注内容，只有人工复核通过后才能接纳结果。")

gpu = gpu_status()
runtime = micro_sam_status()
c1, c2, c3, c4 = st.columns(4)
c1.metric("GPU", gpu["name"] or "未检测到")
c2.metric("显存", gpu["memory"] or "未知")
c3.metric("micro-sam 环境", "就绪" if runtime["environment_ready"] else "未就绪")
c4.metric("SAM 技术测试", "通过" if runtime["smoke_test_ready"] else "待运行")
if runtime.get("conda_environment_ready"):
    st.caption(
        f"当前标注环境：{runtime.get('environment_manager', 'Conda')} · "
        f"z5py {runtime.get('z5py', '已安装')} · CUDA {runtime.get('cuda_runtime', '已启用')}"
    )

focus = st.selectbox(
    "当前查看内容",
    ["B/R 初步结果", "人工复核", "环境与试验集", "全部技术详情"],
    help="一次只展示一类工作，避免把模型状态、复核任务和试验结果混在同一长页面。",
)
with st.expander("查看候选模型登记册与环境说明"):
    registry = pd.DataFrame(model_statuses())
    st.dataframe(
        registry[["model", "task", "license", "readiness", "local_status"]],
        width="stretch",
        hide_index=True,
    )
    st.info("重型模型继续使用独立环境。主工作台只读取状态和结果文件，不会被模型依赖拖慢或破坏。")

if focus in {"人工复核", "全部技术详情"} and REVIEW30_SEED.exists() and REVIEW30_TABLE.exists() and REVIEW30_MAP.exists():
    st.subheader("Review30 人工复核")
    st.success("已从自动候选中抽取 30 个对象：覆盖全图，并平衡小、中、大三档尺寸。")
    st.image(str(REVIEW30_MAP), caption="B-DQ-1-06 · Review30 编号位置图（当前仍是未复核候选）")

    review30 = pd.read_csv(REVIEW30_TABLE)
    a, b, c, d = st.columns(4)
    a.metric("待复核", len(review30))
    b.metric("小尺寸", int((review30["size_bin"] == "small").sum()))
    c.metric("中尺寸", int((review30["size_bin"] == "medium").sum()))
    d.metric("大尺寸", int((review30["size_bin"] == "large").sum()))
    editable_columns = {"review_status", "confidence", "boundary_issue", "notes"}
    edited_review30 = st.data_editor(
        review30,
        width="stretch",
        hide_index=True,
        disabled=[column for column in review30.columns if column not in editable_columns],
        column_config={
            "review_status": st.column_config.SelectboxColumn(
                "review_status",
                options=["pending", "correct", "under", "over", "merged", "false", "uncertain"],
                required=True,
            ),
            "confidence": st.column_config.SelectboxColumn(
                "confidence", options=["", "high", "medium", "low"]
            ),
            "boundary_issue": st.column_config.SelectboxColumn(
                "boundary_issue", options=["", "none", "under", "over", "merged", "fragmented"]
            ),
        },
        key="review30_editor",
    )
    if st.button("保存 Review30 复核表", type="primary"):
        edited_review30.to_csv(REVIEW30_TABLE, index=False, encoding="utf-8-sig")
        completed = int((edited_review30["review_status"] != "pending").sum())
        record_event(
            "manual_review_progress",
            "Review30 人工复核进度已保存",
            f"B-DQ-1-06 已记录 {completed}/30 个候选对象的人工判断。",
            {"review_table": str(REVIEW30_TABLE), "completed": completed, "total": 30},
            ["micro-sam", "SEM", "Review30", "human-validation"],
        )
        st.success(f"已保存：{completed}/30 个对象完成判断。")

    st.markdown(
        "**操作入口：**关闭当前 napari 后，双击项目根目录的 "
        "`Start_microSAM_B_Review30.cmd`。逐个检查 1–30 号对象，最后另存为："
    )
    st.code(str(REVIEW30_REVIEWED), language=None)
    st.warning("不要覆盖 seed 文件；只有人工确认后的 reviewed 文件才能用于韧窝尺寸统计。")

if focus in {"B/R 初步结果", "全部技术详情"} and AUTO_STANDARD_PATH.exists():
    auto_standard = json.loads(AUTO_STANDARD_PATH.read_text(encoding="utf-8"))
    calibration = auto_standard["calibration"]
    policy = auto_standard["automatic_policy"]
    st.subheader("韧窝自动标准 v0.1")
    a, b, c, d = st.columns(4)
    a.metric("候选正确比例", f"{calibration['candidate_acceptance_rate'] * 100:.1f}%")
    b.metric("候选误差比例", f"{calibration['candidate_rejection_rate'] * 100:.1f}%")
    c.metric("465个候选初步校正", "≈ 341")
    d.metric("逐对象人工校核", "关闭")
    st.caption(
        "适用范围：同制样、同探测条件、1000× SEM，像素标定相对 0.27265625 µm/px 偏差不超过 ±5%。"
    )
    st.info(
        "自动规则：面积至少 50 px；去除接触图像边缘的对象；Commit 后再次去除小碎片。"
        "超出覆盖率或中位尺寸范围的图像自动标记 out_of_standard，不进入汇总。"
    )
    st.warning(
        "校准记录存在差异：口头确认22/30正确，但保存掩膜保留25个标签。"
        "系统采用保守的22/30总体比例，不虚构那3个对象的身份。"
    )

if focus in {"B/R 初步结果", "全部技术详情"} and BATCH_COMPARISON.exists() and BATCH_SUMMARY.exists():
    batch_comparison = json.loads(BATCH_COMPARISON.read_text(encoding="utf-8"))
    batch_metrics = batch_comparison["metrics"]
    st.subheader("B/R 十张1000×断口图自动对比")
    a, b, c, d = st.columns(4)
    a.metric("有效图像", "B 5 / R 5")
    b.metric("R候选数量相对B", f"{batch_metrics['estimated_true_candidates']['R_vs_B_percent']:.1f}%")
    c.metric("R中位直径相对B", f"+{batch_metrics['median_equivalent_diameter_um']['R_vs_B_percent']:.1f}%")
    d.metric("R覆盖率相对B", f"+{batch_metrics['candidate_coverage_percent']['R_vs_B_percent']:.1f}%")
    if BATCH_PLOT.exists():
        st.image(str(BATCH_PLOT), caption="以每张SEM图为独立统计单位；散点表示单张图。")
    batch_table = pd.read_csv(BATCH_SUMMARY)
    st.dataframe(batch_table, width="stretch", hide_index=True)
    st.info(
        "探索性方向：R钢自动候选数量密度较低、中位等效直径较高、覆盖率接近。"
        "但当前各指标的bootstrap 95%区间均跨越0，因此尚不能认定为稳定B/R差异。"
    )
    st.warning(
        "这一模式既可能表示R钢韧窝更粗大，也可能表示模型在R钢图上合并了相邻区域。"
        "在不再人工逐对象复核的前提下，系统将其保留为待其他证据验证的假设。"
    )

report = smoke_test_report()
if focus in {"环境与试验集", "全部技术详情"} and report.get("results"):
    st.subheader("首轮 GPU 技术测试")
    a, b, c = st.columns(3)
    a.metric("模型", report.get("model", "SAM"))
    b.metric("峰值显存", f"{report.get('peak_gpu_memory_mb', 0):.0f} MB")
    mean_embedding = sum(float(row.get("embedding_seconds", 0)) for row in report["results"]) / len(report["results"])
    c.metric("平均特征计算", f"{mean_embedding:.2f} s/图")

    st.warning(
        "本轮只证明 GPU、权重、原图预处理和掩膜输出链路已跑通。默认单点提示产生了过大的区域，"
        "不能作为韧窝、解理、夹杂或 B/R 差异结论。"
    )
    result_columns = st.columns(len(report["results"]))
    for column, row in zip(result_columns, report["results"]):
        overlay = Path(row["outputs"]["overlay"])
        if overlay.exists():
            column.image(str(overlay), caption=f"{row['sample_file']} · 未复核技术掩膜")
        column.caption(
            f"模型分数 {float(row['model_score']):.3f}；特征计算 {float(row['embedding_seconds']):.2f}s"
        )

    st.markdown(
        "**下一步操作：** 使用一键 micro-sam 标注器，在同一目标上组合框选、正点和负点；"
        "保存人工确认的掩膜后，才计算面积分数、等效尺寸和数量密度。"
    )
    st.success("一键入口已放在项目根目录：`Start_microSAM_B.cmd` 和 `Start_microSAM_R.cmd`。")
    st.markdown("**Commit 记录目录（每张原图必须独立）：**")
    st.code(
        "B: D:\\SteelAI-Tools\\annotations\\B-DQ-1-06.zarr\n"
        "R: D:\\SteelAI-Tools\\annotations\\R-DQ-1-03.zarr",
        language=None,
    )

if focus not in {"环境与试验集", "全部技术详情"}:
    _render_acceptance_boundary()
    _render_next_steps()
    st.stop()

st.subheader("B/R DQ 冲击断口试验集")
settings = load_settings()
experiment_root = settings.get("sources", {}).get("experiment_root", "")
pilot_dir = find_dq_fractography_dir(experiment_root)

if pilot_dir is None:
    st.warning("没有找到 20260803 SEM-DQ 冲击断口目录，请先检查 experiment_root 配置。")
else:
    all_rows = scan_sem_directory(pilot_dir)
    pilot = select_balanced_pilot(all_rows, magnification=1000, per_steel=5)
    b_count = sum(row["steel"] == "B" for row in pilot)
    r_count = sum(row["steel"] == "R" for row in pilot)

    a, b, c = st.columns(3)
    a.metric("已发现 SEM 图", len(all_rows))
    b.metric("1000× B 试验图", b_count)
    c.metric("1000× R 试验图", r_count)
    st.caption(f"来源目录：{pilot_dir}。只读取 TIF 和同名 HDR，不复制、不修改原文件。")

    if pilot:
        st.dataframe(
            pd.DataFrame(pilot)[
                ["evidence_id", "sample_id", "magnification_x", "pixel_size_um", "filename", "review_status"]
            ],
            width="stretch",
            hide_index=True,
        )

        b_example = next((row for row in pilot if row["steel"] == "B"), None)
        r_example = next((row for row in pilot if row["steel"] == "R"), None)
        if b_example and r_example:
            left, right = st.columns(2)
            left.image(tif_preview(b_example["image_path"]), caption=f"B · {b_example['filename']} · 1000×")
            right.image(tif_preview(r_example["image_path"]), caption=f"R · {r_example['filename']} · 1000×")

        if st.button("保存 10 张配对试验清单", type="primary"):
            if b_count < 5 or r_count < 5:
                st.error("B/R 各不足 5 张同倍率图片，未保存。")
            else:
                manifest_path = save_pilot_manifest(pilot)
                record_event(
                    "model_lab_pilot",
                    "建立 micro-sam DQ 断口试验集",
                    "选择 B/R 各 5 张 1000× SEM 图；只登记路径，模型输出仍需人工复核。",
                    {"manifest": str(manifest_path), "source": str(pilot_dir)},
                    ["micro-sam", "SEM", "fractography", "pilot"],
                )
                st.success(f"试验清单已保存：{manifest_path}")

_render_acceptance_boundary()
_render_next_steps()
