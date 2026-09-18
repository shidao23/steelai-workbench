# T51 共享科研治理包

状态：`implemented`
依赖：T50 全局科研治理规范 v1.0
Python 包：`steelai.governance`

## 1. 完成结果

T51 把 T50 的治理规范实现为一个不依赖 Streamlit、云模型或外部数据库的 Python 公共包。后续工作区不再各自发明审批摘要、状态跳转、SHA-256、Manifest 和发布规则，而是调用同一组稳定接口。

公共包提供：

- 稳定数据类：研究对象身份、来源引用、人工审批快照、产物记录、治理 Manifest、转换记录和验证结果；
- 规范序列化：UTF-8、键排序、禁止 NaN/Infinity 的标准 JSON，以及流式 SHA-256；
- 状态保护：只允许 T50 冻结的转换，`running` 只能从 `approved` 进入；
- 执行保护：批准记录必须由人作出，并绑定对象类型、ID、修订和内容摘要；
- QC 与正式写入门禁：统一验证身份、来源、schema、审批、QC、溯源、完整性、类别、仅追加和状态；
- 产物保护：Manifest 绑定文件集合、大小和 SHA-256，`COMPLETE` 再绑定 Manifest；
- 发布保护：同一文件系统临时目录原子切换、相同内容幂等复用、不同内容冲突拒绝、已篡改目标拒绝覆盖。

## 2. 包结构

| 文件 | 职责 |
| --- | --- |
| `contract.py` | 读取并验证 T50 机器契约 |
| `models.py` | 统一数据类、枚举和 JSON 往返 |
| `state_machine.py` | 状态转换与受控执行授权 |
| `gates.py` | QC 和正式写入十条件门禁 |
| `manifest.py` | Manifest 构建、封口、完整性复核 |
| `publishing.py` | 仅追加原子发布、重放复用和冲突拒绝 |
| `serialization.py` | 标准 JSON、SHA-256 和原子 JSON 写入 |
| `errors.py` | 带稳定错误码和目标状态的关闭式错误 |

## 3. 最小调用流程

```python
from steelai.governance import (
    ApprovalSnapshot,
    EvidenceClass,
    GovernanceState,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    authorize_execution,
    build_manifest,
    create_staging_directory,
    publish_append_only,
    seal_package,
)

identity = ResearchObjectIdentity.from_content(
    "result", "RESULT-001", 1, result_payload, "pipeline-name"
)
approval = ApprovalSnapshot.create(
    identity, "approved", reviewer_id, scope, rationale
)
authorize_execution(identity, GovernanceState.APPROVED, approval)

stage = create_staging_directory(output_root, identity.object_id)
# 确定性代码只向 stage 写产物
manifest = build_manifest(
    stage,
    publication_id=identity.object_id,
    identity=identity,
    state="complete",
    result_level=ResultLevel.ACCEPTED_EVIDENCE,
    evidence_class=EvidenceClass.REAL_RESEARCH_DATA,
    sources=(source_reference,),
    approvals=(approval,),
    generated_by="pipeline-name",
)
seal_package(stage, manifest)
publish_append_only(stage, output_root / identity.object_id)
```

审批发生在执行之前；Manifest 在所有产物写完后构建；封口之后不能再改文件；正式目录只通过临时目录的原子切换出现。

## 4. 稳定错误行为

| 场景 | 错误码 | 结果状态 |
| --- | --- | --- |
| 无审批、审批过期或摘要不匹配 | `GOV-APPROVAL-001` | `blocked` |
| 非法状态跳转 | `GOV-STATE-001` | `blocked` |
| Manifest、完成标记或文件摘要不一致 | `GOV-INTEGRITY-001` | `blocked` 或验证结果 `invalidated` |
| 同一发布身份对应不同内容 | `GOV-DUPLICATE-001` | `blocked` |
| 合成数据请求进入正式证据库 | `GOV-RESULT-001` | `blocked` |
| 越界、非仅追加或符号链接写入 | `GOV-WRITE-001` | `blocked` |
| AI/Agent 尝试成为审批人 | `GOV-AI-AUTH-001` | `blocked` |

验证函数不删除篡改产物，也不尝试自动修复。它返回 `invalidated` 和具体问题；发布函数看到无效目标后拒绝覆盖。

## 5. 迁移适配说明

T51 不一次性改写九个工作区。后续任务按以下方式迁移：

| 现有模块 | 现有语义 | 目标适配 |
| --- | --- | --- |
| SteelData Bridge | `candidate / approved / execution_not_approved / completed` | 映射为 `draft / approved / blocked / complete`，保留原模块状态作为扩展字段 |
| SteelStats Bridge | `ready / passed / failed / warning` | 使用统计结果身份和来源引用，失败统一关闭为 `blocked` |
| Physics Engine | `ready / warning / blocked` | 公式版本、输入摘要和适用范围进入来源及审批快照 |
| EBSD/SEM | `pending / running / completed / needs_review` | 参数审批后运行，模型结果默认进入 `needs_human` |
| Research Agent | `candidate / verified / unsupported` | 只读取 `verified_output` 或 `accepted_evidence`，不得创建审批 |
| Model Lab | `draft / ready / running / completed / accepted` | 数据、模型和参数共同形成对象摘要，人工验收形成审批快照 |
| Automation | `pending / approved / running / completed / failed` | 所有执行通过 `authorize_execution`，产物通过公共发布器 |
| Research Session | `open / in_progress / blocked / complete` | 结论作为独立人工结论对象引用证据 |
| Portfolio | `candidate / accepted / hidden` | 只投影完整性通过且已做公开决定的成果 |

迁移时必须“映射旧状态并保留原文”，不能直接重写既有历史。T52 起每次只迁移一个业务链路，并同时补充回归测试。

## 6. T51 验收证据

`tests/test_governance_core.py` 覆盖：稳定 JSON 往返、AI 审批拒绝、未批准执行拒绝、非法捷径拒绝、警告人工接纳、正式写入十道门槛、成功发布、相同内容重放、不同内容冲突、文件篡改和完成标记缺失。

治理契约也进入 `steelai.quality_gate`。T51 不读取真实数据，测试产物全部在系统临时目录中生成；T40 旗舰演示继续运行其冻结公开合成链路。
