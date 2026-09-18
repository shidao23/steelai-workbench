"""Reusable T54 task, run and human-review panel for EBSD and SEM."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from steelai.governance import GovernanceError, load_verified_manifest, verify_package
from steelai.image_model_governance import (
    IMAGE_MODEL_REVIEW_OUTPUTS,
    IMAGE_MODEL_RUN_OUTPUTS,
    IMAGE_MODEL_TASK_OUTPUTS,
    list_image_model_result_index,
    record_image_model_run,
    register_image_model_task,
    review_image_model_run,
)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _packages(root: Path, artifact: str, modality: str) -> list[dict]:
    rows: list[dict] = []
    if not root.is_dir():
        return rows
    for package in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        verification = verify_package(package)
        if verification.status != "passed":
            continue
        payload = _read_json(package / artifact)
        if str(payload.get("modality", "")).upper() != modality:
            continue
        manifest = load_verified_manifest(package)
        rows.append({
            "id": manifest.publication_id,
            "state": manifest.state,
            "result_level": manifest.result_level,
            "package": str(package),
            "payload": payload,
        })
    return rows


def render_image_model_governance_panel(st, modality: str, *, key_prefix: str) -> None:
    modality = modality.upper()
    defaults = {
        "EBSD": {
            "task_type": "orientation_map_analysis",
            "software_id": "mtex",
            "model_id": "basic-ebsd-pipeline",
            "environment_id": "isolated-matlab-mtex",
            "runtime": "MATLAB-MTEX",
        },
        "SEM": {
            "task_type": "fracture_segmentation",
            "software_id": "micro-sam",
            "model_id": "sam-vit-b",
            "environment_id": "isolated-micro-sam",
            "runtime": "Python-CUDA",
        },
    }[modality]
    tasks = _packages(IMAGE_MODEL_TASK_OUTPUTS, "image_task_manifest.json", modality)
    runs = _packages(IMAGE_MODEL_RUN_OUTPUTS, "model_run_record.json", modality)
    reviews = [row for row in list_image_model_result_index(IMAGE_MODEL_REVIEW_OUTPUTS) if row.get("modality") == modality]
    pending = [row for row in runs if row["state"] == "needs_human"]

    with st.expander(f"{modality} 可信任务与人工复核", expanded=False):
        a, b, c = st.columns(3)
        a.metric("已批准任务", len(tasks))
        b.metric("待人工复核运行", len(pending))
        c.metric("已登记模型结果", sum(bool(row.get("evidence_eligible")) for row in reviews))
        st.caption("这里只保存身份、参数、版本、摘要和审核记录；原始图像、CTF、模型权重和重型输出均不复制。")

        st.markdown("**一 登记运行前任务**")
        source_path = st.text_input("只读源文件路径", key=f"{key_prefix}_source_path")
        x1, x2, x3, x4 = st.columns(4)
        source_id = x1.text_input("来源编号", key=f"{key_prefix}_source_id")
        sample_id = x2.text_input("样品编号", key=f"{key_prefix}_sample_id")
        specimen_id = x3.text_input("试样编号", key=f"{key_prefix}_specimen_id")
        field_id = x4.text_input("视场编号", key=f"{key_prefix}_field_id")
        y1, y2, y3 = st.columns(3)
        task_key = y1.text_input("任务名称", value=f"{modality}-analysis", key=f"{key_prefix}_task_key")
        software_version = y2.text_input("软件版本", key=f"{key_prefix}_software_version")
        model_version = y3.text_input("模型或流程版本", key=f"{key_prefix}_model_version")
        z1, z2 = st.columns(2)
        runtime_version = z1.text_input("独立环境版本", key=f"{key_prefix}_runtime_version")
        task_reviewer = z2.text_input("参数审核人", key=f"{key_prefix}_task_reviewer")
        parameter_rationale = st.text_input("参数选择依据", key=f"{key_prefix}_parameter_rationale")
        can_register = all(value.strip() for value in (
            source_path, source_id, sample_id, specimen_id, field_id, task_key,
            software_version, model_version, runtime_version, task_reviewer, parameter_rationale,
        ))
        if st.button("批准并登记任务配置", key=f"{key_prefix}_register_task", disabled=not can_register):
            try:
                result = register_image_model_task(
                    task_key,
                    modality=modality,
                    task_type=defaults["task_type"],
                    sources=[{
                        "source_id": source_id,
                        "source_path": source_path,
                        "source_status": "read_only_verified",
                        "modality": modality,
                        "sample_id": sample_id,
                        "specimen_id": specimen_id,
                        "image_field_id": field_id,
                    }],
                    software_id=defaults["software_id"],
                    software_version=software_version,
                    model_id=defaults["model_id"],
                    model_version=model_version,
                    parameters={"raw_files_read_only": True, "parameter_set": "human_confirmed_v1"},
                    environment={
                        "environment_id": defaults["environment_id"],
                        "runtime": defaults["runtime"],
                        "runtime_version": runtime_version,
                        "isolated_from_workbench": True,
                    },
                    reviewer_id=task_reviewer,
                    rationale=parameter_rationale,
                )
            except (GovernanceError, OSError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success(f"任务已登记：{result['task_id']}")
                st.rerun()

        st.markdown("**二 登记独立环境运行结果**")
        if not tasks:
            st.info("先登记并批准任务配置，才能登记外部运行结果。")
        else:
            selected_task = st.selectbox(
                "已批准任务",
                [row["id"] for row in tasks],
                key=f"{key_prefix}_run_task",
            )
            outcome = st.selectbox(
                "技术运行状态",
                ["completed", "partial", "failed", "canceled"],
                key=f"{key_prefix}_run_outcome",
            )
            output_path = st.text_input(
                "输出文件路径（完成或部分结果时必填）",
                key=f"{key_prefix}_output_path",
            )
            output_id = st.text_input("输出编号", value="RESULT-01", key=f"{key_prefix}_output_id")
            error_code = st.text_input("失败错误码", key=f"{key_prefix}_error_code")
            chosen_task = next(row for row in tasks if row["id"] == selected_task)
            output_required = outcome in {"completed", "partial"}
            can_record = bool(output_path.strip() and output_id.strip()) if output_required else outcome == "canceled" or bool(error_code.strip())
            if st.button("登记运行状态", key=f"{key_prefix}_record_run", disabled=not can_record):
                outputs = [{"output_id": output_id, "path": output_path}] if output_required else []
                try:
                    result = record_image_model_run(
                        chosen_task["package"],
                        outcome=outcome,
                        outputs=outputs,
                        error_code=error_code or None,
                        error_summary="External runtime reported failure." if outcome == "failed" else None,
                    )
                except (GovernanceError, OSError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.success(f"运行已登记：{result['run_id']}，当前状态 {result['status']}。")
                    st.rerun()

        st.markdown("**三 人工复核模型结果**")
        if not pending:
            st.info("当前没有待人工复核的运行结果。")
        else:
            selected_run = st.selectbox(
                "待复核运行",
                [row["id"] for row in pending],
                key=f"{key_prefix}_pending_run",
            )
            chosen_run = next(row for row in pending if row["id"] == selected_run)
            technical_outcome = chosen_run["payload"].get("technical_outcome")
            decisions = ["warning_accepted", "rejected"] if technical_outcome == "partial" else ["approved", "rejected"]
            decision = st.selectbox("复核决定", decisions, key=f"{key_prefix}_review_decision")
            r1, r2 = st.columns(2)
            reviewer = r1.text_input("结果审核人", key=f"{key_prefix}_result_reviewer")
            scope = r2.text_input("允许使用范围", key=f"{key_prefix}_review_scope")
            rationale = st.text_input("结果复核依据与局限", key=f"{key_prefix}_review_rationale")
            if st.button(
                "提交人工复核",
                key=f"{key_prefix}_submit_review",
                disabled=not all(value.strip() for value in (reviewer, scope, rationale)),
            ):
                try:
                    result = review_image_model_run(
                        chosen_run["package"],
                        reviewer_id=reviewer,
                        decision=decision,
                        rationale=rationale,
                        scope=scope,
                    )
                except (GovernanceError, OSError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.success(f"复核已登记：{result['review_id']}。模型结果仍明确标记为非实验测量。")
                    st.rerun()

        if runs:
            st.markdown("**最近运行状态**")
            st.dataframe(
                pd.DataFrame([{
                    "run_id": row["id"],
                    "state": row["state"],
                    "technical_outcome": row["payload"].get("technical_outcome"),
                    "attempt": row["payload"].get("attempt"),
                    "model_version": row["payload"].get("model", {}).get("model_version"),
                } for row in runs]),
                hide_index=True,
                width="stretch",
            )
