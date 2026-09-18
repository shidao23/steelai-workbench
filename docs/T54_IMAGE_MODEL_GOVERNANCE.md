# T54 EBSD SEM 与模型任务治理适配

状态：`Done`
依赖：T51 共享科研治理包
实施日期：2026-09-09

## 1 目标

T54 为 EBSD、SEM 和独立模型运行建立同一条可验证身份链：先登记只读来源、样品、物理试样、图像视场和参数，再由隔离工具执行，随后登记运行状态和输出摘要，最后由具名人员决定是否把结果登记为受限模型证据。它不改变 MATLAB/MTEX、micro-sam 或既有图像算法。

## 2 三段式工作流

第一段是运行前任务登记。用户确认来源编号、样品编号、物理试样编号、视场编号、模态、软件版本、模型或流程版本、参数集和独立环境版本。审批与当前配置摘要绑定，参数变化必须形成新的任务身份。

第二段是独立环境运行登记。Workbench 不启动任意命令，也不加载重型模型；外部工具完成后，用户登记 `completed`、`partial`、`failed` 或 `canceled`。每个输出只保存输出编号、SHA-256、大小、媒体类型和私有定位摘要。重跑保存尝试次数和前序运行编号。

第三段是人工复核。完成或部分结果一律先进入 `needs_human`。完整结果可批准或拒绝；部分结果只能显式接纳警告或拒绝。批准记录必须包含审核人、时间、范围和依据。系统据此生成独立、仅追加的复核包。

## 3 治理包

任务包位于 `outputs/image_model_tasks/<task_id>/`，包含：

- `image_task_manifest.json`：任务、来源身份、版本、参数和运行环境；
- `governance_record.json`：配置审批和状态记录；
- `governance_manifest.json` 与 `COMPLETE`：文件摘要和完整性绑定。

运行包位于 `outputs/image_model_runs/<run_id>/`，包含：

- `model_run_record.json`：技术状态、尝试次数、模型、参数、环境、错误和输出摘要；
- `result_traceability.json`：运行到任务、来源和输出的反查索引；
- Governance Manifest 与完整性标记。

复核包位于 `outputs/image_model_reviews/<review_id>/`，包含：

- `human_review.json`：具名决定、适用范围、依据、局限和接纳输出；
- `result_index_record.json`：供证据模块消费的结果索引；
- `governance_record.json`、Governance Manifest 与完整性标记。

三个目录都遵守仅追加发布。相同身份和内容可复用，内容冲突或完整性失效时拒绝覆盖。

## 4 状态与证据边界

| 技术状态 | 治理状态 | 是否可登记模型证据 | 人工要求 |
| --- | --- | --- | --- |
| completed | needs_human | 否 | 批准或拒绝 |
| partial | needs_human | 否 | 接纳警告或拒绝 |
| failed | blocked | 否 | 保存错误码后重新配置或重跑 |
| canceled | blocked | 否 | 保存取消状态，需要时发起新运行 |
| reviewed completed | complete | 是，等级为 model_result | 具名审核及范围 |
| reviewed partial | complete | 是，等级为 model_result | 具名审核、局限和 warning_accepted |

即使复核通过，证据类别仍为 `model_output`，结果等级仍为 `model_result`。它可以作为受限模型证据被引用，但不能改称直接实验测量，不能自动成为组织、断口或材料机理结论。

## 5 文件与运行边界

- 原始 TIF、CTF、HDR、模型权重和重型结果不复制进治理包或公开仓库。
- 本地绝对路径和原始文件名不写入治理 Manifest；包内仅保存稳定来源编号、文件摘要及私有定位摘要。
- MATLAB/MTEX、micro-sam、GPU 和未来重型模型继续使用独立环境。
- Workbench 不要求安装或运行本地大语言模型。
- T54 不覆盖 seed、reviewed、原始图像或既有 EBSD 输出。
- 失败、取消和未经复核的结果不会进入可引用结果索引。

## 6 页面操作

在“组织与证据 → EBSD 分析”或“模型与自动化 → 模型实验室”展开“可信任务与人工复核”：

1. 填写稳定来源、样品、试样和视场编号以及版本，批准并登记任务配置。
2. 在独立工具完成后，选择任务并登记技术状态与输出文件。
3. 对 `needs_human` 结果填写审核人、允许范围、依据和局限，提交批准、警告接纳或拒绝。
4. 页面只统计通过 Manifest 完整性验证的任务、运行和结果索引。

## 7 验收覆盖

`tests/test_t54_image_model_governance.py` 使用完全合成的临时文件验证：

- EBSD 与 SEM 使用同一契约，且原始文件逐字节不变；
- 包中不存在原始路径、原始文件名或原始图像副本；
- 软件、模型、参数、环境、来源和输出摘要均可反查；
- 完成和部分结果在复核前不能成为正式模型证据；
- 部分结果不能用普通批准绕过警告接纳；
- 失败、取消和重跑状态稳定；
- 篡改后的包无法通过完整性复核或人工接纳；
- 未隔离运行环境和缺失来源关闭式失败。
