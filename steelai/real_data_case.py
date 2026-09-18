"""T62 reproducible real-data case for the UCI Steel Plates Faults dataset.

The raw public dataset is downloaded or read from a user-provided ZIP, verified,
used in memory and never copied into the repository or governed result package.
The implementation intentionally uses NumPy/Pandas already brought in by the
Workbench requirements; it does not require scikit-learn, a GPU or a local LLM.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import platform
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from steelai.governance import (
    EvidenceClass,
    GovernanceError,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    build_manifest,
    create_staging_directory,
    digest_value,
    load_verified_manifest,
    publish_append_only,
    seal_package,
    utc_now,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS, ROOT


CASE_CONTRACT_PATH = ROOT / "config" / "real_data_case_v1.0.json"
REAL_DATA_CASE_OUTPUTS = OUTPUTS / "real_data_cases"
LABEL_COLUMNS = (
    "Pastry", "Z_Scratch", "K_Scatch", "Stains", "Dirtiness", "Bumps", "Other_Faults",
)


def _sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _read_contract(path: Path = CASE_CONTRACT_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "T62 case contract is unreadable") from exc
    if not isinstance(value, dict):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "T62 case contract must be a JSON object")
    return value


def validate_real_data_case_contract(path: Path = CASE_CONTRACT_PATH) -> dict[str, Any]:
    problems: list[str] = []
    contract = _read_contract(path)
    dataset = contract.get("dataset", {})
    split = contract.get("split", {})
    models = contract.get("models", {})
    if contract.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    if contract.get("case_id") != "SteelAI-T62-UCI-Steel-Plates-Faults-v1.0":
        problems.append("case_id is not frozen")
    if dataset.get("license_id") != "CC-BY-4.0" or not dataset.get("attribution"):
        problems.append("dataset license and attribution must be explicit")
    for key in ("zip_sha256", "data_sha256", "variables_sha256"):
        value = str(dataset.get(key, ""))
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            problems.append(f"{key} must be a lowercase SHA-256")
    if dataset.get("raw_data_in_repository") is not False:
        problems.append("raw public data must remain outside the repository")
    if split.get("algorithm") != "class-stratified-sha256-order-v1":
        problems.append("split algorithm is not frozen")
    if split.get("test_used_for_tuning") is not False:
        problems.append("test data must not be used for tuning")
    fractions = [split.get("train_fraction"), split.get("validation_fraction"), split.get("test_fraction")]
    if not all(isinstance(item, (int, float)) for item in fractions) or not math.isclose(sum(fractions), 1.0):
        problems.append("split fractions must sum to 1")
    if models.get("baseline", {}).get("model_id") != "majority-class-v1":
        problems.append("baseline model is not frozen")
    candidates = models.get("improved", {}).get("candidate_k")
    if candidates != [3, 5, 7, 11]:
        problems.append("improved-model candidate_k is not frozen")
    runtime = contract.get("runtime", {})
    if runtime.get("local_ai_required") is not False or runtime.get("gpu_required") is not False:
        problems.append("T62 must remain CPU-only and require no local AI")
    return {
        "status": "passed" if not problems else "failed",
        "case_id": contract.get("case_id"),
        "contract_sha256": digest_value(contract),
        "dataset_id": dataset.get("dataset_id"),
        "license_id": dataset.get("license_id"),
        "problems": problems,
    }


def _download_archive(contract: Mapping[str, Any], timeout_seconds: int = 45) -> bytes:
    request = urllib.request.Request(
        str(contract["dataset"]["download_url"]),
        headers={"User-Agent": "SteelAI-Workbench-T62/1.0 (reproducible research case)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise GovernanceError(
            "GOV-SOURCE-001",
            "blocked",
            "official UCI archive could not be downloaded; use --zip with the official file",
        ) from exc
    return payload


def _load_archive_bytes(zip_path: Path | None, contract: Mapping[str, Any]) -> bytes:
    if zip_path is None:
        payload = _download_archive(contract)
    else:
        candidate = zip_path.expanduser()
        if not candidate.is_file() or candidate.is_symlink():
            raise GovernanceError("GOV-SOURCE-001", "blocked", "dataset ZIP is unavailable or is a symbolic link")
        payload = candidate.read_bytes()
    expected = str(contract["dataset"]["zip_sha256"])
    observed = _sha256_bytes(payload)
    if observed != expected:
        raise GovernanceError(
            "GOV-INTEGRITY-001", "blocked", "dataset ZIP digest does not match the frozen UCI artifact",
            details={"expected": expected, "observed": observed},
        )
    return payload


def _member_bytes(archive: zipfile.ZipFile, name: str, expected_digest: str) -> bytes:
    try:
        payload = archive.read(name)
    except KeyError as exc:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", f"dataset member is missing: {name}") from exc
    observed = _sha256_bytes(payload)
    if observed != expected_digest:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", f"dataset member digest mismatch: {name}")
    return payload


def load_verified_dataset(
    zip_path: Path | None = None,
    *,
    contract_path: Path = CASE_CONTRACT_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    contract = _read_contract(contract_path)
    payload = _load_archive_bytes(zip_path, contract)
    dataset = contract["dataset"]
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            data_bytes = _member_bytes(archive, dataset["data_member"], dataset["data_sha256"])
            variables_bytes = _member_bytes(
                archive, dataset["variables_member"], dataset["variables_sha256"],
            )
    except zipfile.BadZipFile as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "dataset archive is not a valid ZIP") from exc

    names = [line.strip() for line in variables_bytes.decode("utf-8").splitlines() if line.strip()]
    if len(names) != dataset["expected_features"] + dataset["expected_classes"]:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "unexpected number of UCI variables")
    if tuple(names[-dataset["expected_classes"]:]) != LABEL_COLUMNS:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "UCI target columns differ from the frozen contract")
    frame = pd.read_csv(io.BytesIO(data_bytes), sep=r"\s+", header=None, names=names)
    if frame.shape != (dataset["expected_instances"], len(names)):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "UCI dataset dimensions differ from the frozen contract")
    if int(frame.isna().sum().sum()) != dataset["missing_values_expected"]:
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "unexpected missing values in UCI dataset")
    if not all(pd.api.types.is_numeric_dtype(frame[column]) for column in frame.columns):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "all UCI columns must be numeric")
    target_sum = frame[list(LABEL_COLUMNS)].sum(axis=1)
    if not bool((target_sum == 1).all()):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "each row must contain exactly one fault label")
    feature_columns = names[: dataset["expected_features"]]
    frame = frame.copy()
    frame["target_label"] = frame[list(LABEL_COLUMNS)].idxmax(axis=1)
    frame["row_id"] = [
        "UCI198-" + digest_value([float(value) for value in row])[:20].upper()
        for row in frame[feature_columns].itertuples(index=False, name=None)
    ]
    if frame["row_id"].duplicated().any():
        raise GovernanceError("GOV-DUPLICATE-001", "blocked", "duplicate feature rows would cross split boundaries")
    receipt = {
        "dataset_id": dataset["dataset_id"],
        "archive_sha256": _sha256_bytes(payload),
        "data_sha256": dataset["data_sha256"],
        "variables_sha256": dataset["variables_sha256"],
        "instance_count": len(frame),
        "feature_count": len(feature_columns),
        "class_count": len(LABEL_COLUMNS),
        "missing_value_count": int(frame.isna().sum().sum()),
        "raw_data_copied_to_result": False,
        "source_locator_recorded": False,
    }
    return frame, receipt


def frozen_split(frame: pd.DataFrame, contract: Mapping[str, Any]) -> tuple[dict[str, list[int]], dict[str, Any]]:
    split = contract["split"]
    fractions = (float(split["train_fraction"]), float(split["validation_fraction"]))
    indices: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
    class_counts: dict[str, dict[str, int]] = {}
    for label in LABEL_COLUMNS:
        members = [int(index) for index in frame.index[frame["target_label"] == label]]
        ordered = sorted(
            members,
            key=lambda index: digest_value({
                "algorithm": split["algorithm"], "salt": split["salt"], "row_id": frame.at[index, "row_id"],
            }),
        )
        train_end = int(len(ordered) * fractions[0])
        validation_end = train_end + int(len(ordered) * fractions[1])
        if train_end < 1 or validation_end <= train_end or validation_end >= len(ordered):
            raise GovernanceError("GOV-SCHEMA-001", "blocked", f"class {label} is too small for the frozen split")
        partitions = {
            "train": ordered[:train_end],
            "validation": ordered[train_end:validation_end],
            "test": ordered[validation_end:],
        }
        for name, values in partitions.items():
            indices[name].extend(values)
        class_counts[label] = {name: len(values) for name, values in partitions.items()}
    for name in indices:
        indices[name] = sorted(indices[name], key=lambda index: frame.at[index, "row_id"])
    all_indices = [index for values in indices.values() for index in values]
    if len(all_indices) != len(frame) or len(set(all_indices)) != len(frame):
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "frozen splits overlap or omit rows")
    manifest = {
        "schema_version": "1.0",
        "algorithm": split["algorithm"],
        "salt_sha256": digest_value(split["salt"]),
        "fractions": {
            "train": split["train_fraction"],
            "validation": split["validation_fraction"],
            "test": split["test_fraction"],
        },
        "test_used_for_tuning": False,
        "counts": {name: len(values) for name, values in indices.items()},
        "class_counts": class_counts,
        "row_ids": {name: [frame.at[index, "row_id"] for index in values] for name, values in indices.items()},
    }
    manifest["split_sha256"] = digest_value(manifest)
    return indices, manifest


def _classification_metrics(
    truth: Sequence[str], prediction: Sequence[str], labels: Sequence[str] = LABEL_COLUMNS,
) -> dict[str, Any]:
    if len(truth) != len(prediction) or not truth:
        raise ValueError("truth and prediction must have the same non-zero length")
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    for actual, predicted in zip(truth, prediction):
        matrix[actual][predicted] += 1
    per_class: dict[str, dict[str, Any]] = {}
    for label in labels:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted_count = sum(matrix[actual][label] for actual in labels)
        recall = tp / support if support else 0.0
        precision = tp / predicted_count if predicted_count else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "support": support, "precision": precision, "recall": recall, "f1": f1,
        }
    accuracy = sum(actual == predicted for actual, predicted in zip(truth, prediction)) / len(truth)
    return {
        "sample_count": len(truth),
        "accuracy": accuracy,
        "balanced_accuracy": sum(item["recall"] for item in per_class.values()) / len(labels),
        "macro_f1": sum(item["f1"] for item in per_class.values()) / len(labels),
        "per_class": per_class,
        "confusion_matrix": {actual: matrix[actual] for actual in labels},
    }


def _scale_from_training(train: np.ndarray, *others: np.ndarray) -> tuple[np.ndarray, ...]:
    mean = train.mean(axis=0)
    standard_deviation = train.std(axis=0)
    standard_deviation[standard_deviation == 0.0] = 1.0
    return tuple((array - mean) / standard_deviation for array in (train, *others))


def _weighted_knn_predict(
    train_x: np.ndarray,
    train_y: Sequence[str],
    query_x: np.ndarray,
    k: int,
    *,
    batch_size: int = 128,
) -> list[str]:
    labels = list(LABEL_COLUMNS)
    label_index = {label: index for index, label in enumerate(labels)}
    encoded = np.asarray([label_index[label] for label in train_y], dtype=np.int64)
    train_norm = np.sum(train_x * train_x, axis=1)
    predictions: list[str] = []
    for start in range(0, len(query_x), batch_size):
        query = query_x[start:start + batch_size]
        distance_squared = np.maximum(
            np.sum(query * query, axis=1)[:, None] + train_norm[None, :] - 2.0 * query @ train_x.T,
            0.0,
        )
        nearest = np.argpartition(distance_squared, kth=k - 1, axis=1)[:, :k]
        for row_number, neighbor_indices in enumerate(nearest):
            neighbor_distances = np.sqrt(distance_squared[row_number, neighbor_indices])
            weights = 1.0 / np.maximum(neighbor_distances, 1e-12)
            scores = np.zeros(len(labels), dtype=float)
            for neighbor, weight in zip(neighbor_indices, weights):
                scores[encoded[neighbor]] += float(weight)
            predictions.append(labels[int(np.argmax(scores))])
    return predictions


def _experiment(frame: pd.DataFrame, contract: Mapping[str, Any]) -> dict[str, Any]:
    dataset = contract["dataset"]
    feature_columns = list(frame.columns[: dataset["expected_features"]])
    indices, split_manifest = frozen_split(frame, contract)
    train = frame.loc[indices["train"]]
    validation = frame.loc[indices["validation"]]
    test = frame.loc[indices["test"]]
    majority_label = Counter(train["target_label"]).most_common(1)[0][0]
    baseline_validation = [majority_label] * len(validation)
    baseline_test = [majority_label] * len(test)

    train_x, validation_x, test_x = _scale_from_training(
        train[feature_columns].to_numpy(dtype=float),
        validation[feature_columns].to_numpy(dtype=float),
        test[feature_columns].to_numpy(dtype=float),
    )
    candidates: list[dict[str, Any]] = []
    predictions_by_k: dict[int, list[str]] = {}
    for k in contract["models"]["improved"]["candidate_k"]:
        prediction = _weighted_knn_predict(train_x, train["target_label"].tolist(), validation_x, int(k))
        predictions_by_k[int(k)] = prediction
        candidates.append({"k": int(k), **_classification_metrics(validation["target_label"].tolist(), prediction)})
    selected = max(candidates, key=lambda item: (item["macro_f1"], item["balanced_accuracy"], -item["k"]))
    selected_k = int(selected["k"])
    improved_test = _weighted_knn_predict(train_x, train["target_label"].tolist(), test_x, selected_k)

    metrics = {
        "schema_version": "1.0",
        "selection": {
            "dataset_partition": "validation",
            "metric": "macro_f1",
            "selected_k": selected_k,
            "candidates": candidates,
            "test_examined_during_selection": False,
        },
        "validation": {
            "baseline": _classification_metrics(validation["target_label"].tolist(), baseline_validation),
            "improved_selected": _classification_metrics(
                validation["target_label"].tolist(), predictions_by_k[selected_k],
            ),
        },
        "test": {
            "baseline": _classification_metrics(test["target_label"].tolist(), baseline_test),
            "improved": _classification_metrics(test["target_label"].tolist(), improved_test),
        },
    }
    prediction_rows = []
    for split_name, partition, baseline, improved in (
        ("validation", validation, baseline_validation, predictions_by_k[selected_k]),
        ("test", test, baseline_test, improved_test),
    ):
        for row_id, actual, baseline_value, improved_value in zip(
            partition["row_id"], partition["target_label"], baseline, improved,
        ):
            prediction_rows.append({
                "row_id": row_id,
                "split": split_name,
                "actual": actual,
                "baseline_prediction": baseline_value,
                "improved_prediction": improved_value,
                "improved_correct": actual == improved_value,
            })
    errors = [row for row in prediction_rows if row["split"] == "test" and not row["improved_correct"]]
    pair_counts = Counter((row["actual"], row["improved_prediction"]) for row in errors)
    error_analysis = {
        "schema_version": "1.0",
        "test_error_count": len(errors),
        "test_error_rate": len(errors) / len(test),
        "largest_confusion_pairs": [
            {"actual": pair[0], "predicted": pair[1], "count": count}
            for pair, count in sorted(pair_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        "example_error_row_ids": [row["row_id"] for row in errors[:20]],
        "risks": [
            "The source provides no plate/batch grouping key, so hidden acquisition-group leakage cannot be ruled out.",
            "Coordinate and conveyor-related features may encode collection conditions rather than transferable defect physics.",
            "Class imbalance makes accuracy alone misleading; macro F1 and balanced accuracy are reported.",
            "Several logarithmic fields are derived from size fields, creating redundant rather than independent evidence.",
            "The dataset has no microstructure, chemistry or processing history, so model behavior cannot establish mechanism.",
        ],
        "failed_or_weak_features": [
            "No feature-ablation claim is made in v1.0; correlated and acquisition-specific predictors require later study.",
            "A correct label does not prove scientifically meaningful reasoning by the classifier.",
        ],
    }
    return {
        "feature_columns": feature_columns,
        "split_manifest": split_manifest,
        "majority_label": majority_label,
        "metrics": metrics,
        "prediction_rows": prediction_rows,
        "error_analysis": error_analysis,
    }


def _round_metric(value: float) -> str:
    return f"{value:.4f}"


def _report_markdown(contract: Mapping[str, Any], experiment: Mapping[str, Any]) -> str:
    test = experiment["metrics"]["test"]
    validation = experiment["metrics"]["selection"]
    counts = experiment["split_manifest"]["counts"]
    return f"""# T62 真实钢板缺陷数据案例

## 研究问题

{contract['research_question']['question']}

## 数据与许可

- 数据：UCI Machine Learning Repository, Steel Plates Faults (ID 198)
- 许可：CC BY 4.0
- 引用：{contract['dataset']['attribution']}
- 数据规模：{contract['dataset']['expected_instances']} 行，{contract['dataset']['expected_features']} 个特征，{contract['dataset']['expected_classes']} 类
- 原始数据未复制进仓库或结果包；运行时按固定 SHA-256 验证。

## 冻结实验设计

- 划分：训练 {counts['train']} / 验证 {counts['validation']} / 测试 {counts['test']}
- 基线：训练集多数类 `{experiment['majority_label']}`
- 改进方法：训练集标准化后的距离加权 kNN
- 仅用验证集选择 k：候选 {contract['models']['improved']['candidate_k']}，选中 k={validation['selected_k']}
- 测试集不参与选型或调参。

## 测试集结果

| 模型 | Accuracy | Balanced accuracy | Macro F1 |
| --- | ---: | ---: | ---: |
| 多数类基线 | {_round_metric(test['baseline']['accuracy'])} | {_round_metric(test['baseline']['balanced_accuracy'])} | {_round_metric(test['baseline']['macro_f1'])} |
| 标准化距离加权 kNN | {_round_metric(test['improved']['accuracy'])} | {_round_metric(test['improved']['balanced_accuracy'])} | {_round_metric(test['improved']['macro_f1'])} |

## 可以说与不能说

本案例证明：在冻结划分上，轻量传统机器学习方法可以与多数类基线进行可复现比较。它不证明模型已经适合生产部署，也不证明任何钢铁冶金机理、工艺因果或跨企业泛化能力。

## 失败分析

- 测试集误分 {experiment['error_analysis']['test_error_count']} 条，错误率 {_round_metric(experiment['error_analysis']['test_error_rate'])}。
- 数据没有板号或批次分组键，无法排除隐藏采集组泄漏。
- 类别不平衡，因此同时报告 Macro F1 与 balanced accuracy。
- 坐标、输送线和派生对数字段可能携带采集条件信息，不能直接解释成材料机制。
- 无成分、工艺和组织信息，禁止据此提出钢种或工艺推荐。

## 当前治理状态

结果包完整性通过，但结果等级仍为 `working_candidate`。在项目负责人单独完成人工验收与披露审查前，不进入正式证据或作品集。
"""


def run_real_data_case(
    *,
    zip_path: Path | None = None,
    output_root: Path = REAL_DATA_CASE_OUTPUTS,
    contract_path: Path = CASE_CONTRACT_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validation = validate_real_data_case_contract(contract_path)
    if validation["status"] != "passed":
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "T62 case contract failed validation")
    contract = _read_contract(contract_path)
    frame, receipt = load_verified_dataset(zip_path, contract_path=contract_path)
    experiment = _experiment(frame, contract)
    identity_seed = {
        "case_id": contract["case_id"],
        "contract_sha256": validation["contract_sha256"],
        "data_sha256": receipt["data_sha256"],
        "split_sha256": experiment["split_manifest"]["split_sha256"],
        "models": contract["models"],
        "metrics_sha256": digest_value(experiment["metrics"]),
    }
    identity_digest = digest_value(identity_seed)
    publication_id = "T62-UCI198-" + identity_digest[:20].upper()
    destination = output_root.resolve() / publication_id
    if destination.exists():
        verification = verify_package(destination)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing T62 package is invalidated")
        manifest = load_verified_manifest(destination)
        if manifest.identity.content_digest != identity_digest:
            raise GovernanceError("GOV-DUPLICATE-001", "blocked", "existing T62 identity conflicts with this run")
        return {
            "status": "passed", "case_id": contract["case_id"], "publication_id": publication_id,
            "package": str(destination), "reused": True, "manifest_sha256": verification.manifest_digest,
            "selected_k": experiment["metrics"]["selection"]["selected_k"],
            "test_metrics": experiment["metrics"]["test"], "human_review_required": True,
            "portfolio_eligible": False,
        }

    timestamp = generated_at or utc_now()
    identity = ResearchObjectIdentity(
        object_type="real_data_model_case",
        object_id=publication_id,
        revision=1,
        content_digest=identity_digest,
        created_at=timestamp,
        created_by="steelai.real_data_case",
    )
    source = SourceReference(
        source_id=contract["dataset"]["dataset_id"],
        source_revision=1,
        source_digest=receipt["data_sha256"],
        evidence_class=EvidenceClass.REAL_RESEARCH_DATA.value,
        source_status="official_public_cc_by_4_0_verified",
    )
    dataset_card = {
        "schema_version": "1.0",
        **contract["dataset"],
        "research_use": contract["research_question"],
        "observed": receipt,
        "limitations": [
            "No source plate or batch grouping identifier is supplied.",
            "Feature units/descriptions are incomplete on the source page.",
            "The case is not a steel chemistry-to-property model.",
        ],
    }
    model_card = {
        "schema_version": "1.0",
        "case_id": contract["case_id"],
        "dataset_id": contract["dataset"]["dataset_id"],
        "research_question": contract["research_question"],
        "split_sha256": experiment["split_manifest"]["split_sha256"],
        "baseline": contract["models"]["baseline"],
        "improved": {**contract["models"]["improved"], "selected_k": experiment["metrics"]["selection"]["selected_k"]},
        "metrics": experiment["metrics"],
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "gpu_used": False,
            "local_ai_used": False,
            "cloud_ai_used": False,
        },
        "result_level": "working_candidate",
        "human_review_required": True,
        "formal_scientific_conclusion": False,
    }
    stage = create_staging_directory(output_root, publication_id)
    try:
        write_json_atomic(stage / "dataset_card.json", dataset_card)
        write_json_atomic(stage / "acquisition_receipt.json", receipt)
        write_json_atomic(stage / "split_manifest.json", experiment["split_manifest"])
        write_json_atomic(stage / "metrics.json", experiment["metrics"])
        write_json_atomic(stage / "model_card.json", model_card)
        write_json_atomic(stage / "error_analysis.json", experiment["error_analysis"])
        pd.DataFrame(experiment["prediction_rows"]).to_csv(
            stage / "predictions.csv", index=False, encoding="utf-8", lineterminator="\n",
        )
        (stage / "case_report.md").write_text(_report_markdown(contract, experiment), encoding="utf-8")
        manifest = build_manifest(
            stage,
            publication_id=publication_id,
            identity=identity,
            state="passed",
            result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
            sources=(source,),
            generated_by="steelai.real_data_case",
            generated_at=timestamp,
            metadata={
                "feature": "T62", "dataset_license": "CC-BY-4.0", "raw_data_copied": False,
                "test_used_for_tuning": False, "human_review_required": True,
                "portfolio_eligible": False,
            },
        )
        seal_package(stage, manifest)
        publication = publish_append_only(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "status": "passed",
        "case_id": contract["case_id"],
        "publication_id": publication_id,
        "package": publication.destination,
        "reused": publication.reused,
        "manifest_sha256": publication.manifest_digest,
        "selected_k": experiment["metrics"]["selection"]["selected_k"],
        "test_metrics": experiment["metrics"]["test"],
        "human_review_required": True,
        "portfolio_eligible": False,
    }


def latest_real_data_case(output_root: Path = REAL_DATA_CASE_OUTPUTS) -> dict[str, Any] | None:
    """Return a small, path-safe summary of the latest valid T62 package."""
    if not output_root.is_dir():
        return None
    candidates = sorted(
        (path for path in output_root.glob("T62-UCI198-*") if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for package in candidates:
        verification = verify_package(package)
        if verification.status != "passed":
            continue
        try:
            model_card = json.loads((package / "model_card.json").read_text(encoding="utf-8"))
            error_analysis = json.loads((package / "error_analysis.json").read_text(encoding="utf-8"))
            manifest = load_verified_manifest(package)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        return {
            "publication_id": package.name,
            "state": manifest.state,
            "result_level": manifest.result_level,
            "integrity_status": verification.status,
            "selected_k": model_card["improved"]["selected_k"],
            "test_metrics": model_card["metrics"]["test"],
            "test_error_count": error_analysis["test_error_count"],
            "report_relative_path": f"outputs/real_data_cases/{package.name}/case_report.md",
            "human_review_required": True,
            "portfolio_eligible": False,
        }
    return None


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the governed T62 UCI steel-plate fault case")
    parser.add_argument("--zip", type=Path, help="optional official UCI ZIP for offline reproduction")
    parser.add_argument("--output-root", type=Path, default=REAL_DATA_CASE_OUTPUTS)
    parser.add_argument("--validate-contract", action="store_true")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = (
            validate_real_data_case_contract()
            if arguments.validate_contract
            else run_real_data_case(zip_path=arguments.zip, output_root=arguments.output_root)
        )
    except GovernanceError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
