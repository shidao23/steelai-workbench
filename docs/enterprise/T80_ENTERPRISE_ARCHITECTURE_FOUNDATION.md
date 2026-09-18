# T80 Enterprise Lab 企业架构基础

- 状态：`Review`（实现完成并已按 Codex 复核意见修正三项契约问题，等待再次复核）
- 日期：2026-09-17
- 边界决策：`docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md`
- 代码位置：`steelai/enterprise_lab/`
- 测试：`tests/test_t80_enterprise_architecture.py`（74 passed + 71 subtests）

## 1. T80 做了什么

T80 只建立企业架构的边界与可替换接口骨架：一个可选模块、一组 Ports、一个纯 Python 内存适配器，
以及一条最小纵向流程。它**不**安装、不接入、不宣称 PostgreSQL、FastAPI、后台 worker、Kafka
或 OpenTelemetry 已经可用。

对现有系统的承诺：

- Streamlit 页面、科研计算、治理内核与运行中心不导入 `steelai.enterprise_lab`；
- 没有任何企业组件时，该模块仍可导入、可执行、可测试；
- 科研数据、方法注册表、审批规则、状态语义和运行行为均未改变；
- 未新增任何第三方依赖。

## 2. 目录与职责

```
steelai/enterprise_lab/
├── __init__.py               # 可选包入口，只导出稳定对象与接口
├── domain/
│   ├── __init__.py
│   └── models.py             # 领域对象 + 脱敏/路径/哈希校验，无 I/O
├── application/
│   ├── __init__.py
│   └── services.py           # 纵向流程，只使用 Ports
├── ports/
│   ├── __init__.py
│   ├── repositories.py       # RunRepository / AuditRepository / UnitOfWork
│   ├── artifacts.py          # ArtifactStore
│   ├── events.py             # EventPublisher
│   └── jobs.py               # JobQueue
└── adapters/
    ├── __init__.py
    └── memory.py             # 纯 Python 内存适配器（演示与契约测试用）
```

依赖方向由外向内：`domain` 不导入任何外层；`application` 只导入 `ports` 与 `domain`；
`ports` 只导入 `domain`；只有 `adapters` 可以导入 `ports` 与 `domain`。
该规则由测试中的 AST 检查强制执行。

## 3. 领域对象

| 对象 | 关键字段 | 边界 |
| --- | --- | --- |
| `EnterpriseProject` | `project_id`、`name`、`created_at`、`schema_version` | 只有业务元数据，无科研数值 |
| `WorkflowRun` | `run_id`、`project_id`、`task_id`、`state`、`revision`、`content_digest`、`result_level`、`evidence_class`、`idempotency_key`、`request_digest`（必填小写 64 位 SHA-256） | 状态复用 T50 十状态；`model_output` 不能登记为 `accepted_evidence` |
| `ArtifactReference` | `artifact_id`、`relative_path`、`sha256`、`artifact_type`、`artifact_version`、`run_id` | 只登记引用，不承载大文件；拒绝绝对路径、穿越、空哈希、非法哈希 |
| `AuditEvent` | `audit_id`、`sequence`、`action`、`actor_role`、`actor_id`、`summary`、`object_*` | 只追加，没有修改/删除入口 |
| `DomainEvent` | `event_id`、`event_type`、`run_id`、`sequence`、`payload` | 负载只允许 ID、状态、版本、哈希与脱敏摘要 |
| `BackgroundJob` | `job_id`、`job_type`、`state`、`attempts`、`max_attempts`、`idempotency_key` | 状态机明确，T80 不实现 worker |

统一约束：

- 身份稳定：`content_digest` 复用共享治理的规范 JSON + SHA-256 规则，前缀为 `run_` / `art_` / `aud_` / `evt_`；
- 状态复用：`RUN_STATES` 与 `steelai.governance.GovernanceState` 的十个值完全一致，不新建第二套科研状态机；
- 脱敏文本：描述性字段拒绝数字、路径分隔符、绝对路径、UNC 路径、URL 和常见凭据模式，
  因此原始实验值、绝对路径和密钥在类型层面无法进入运行记录、审计记录或领域事件；
- 无 I/O：领域层不打开文件、不访问环境变量、不发起网络请求。

## 4. Ports 与接口语义

| Port | 语义 |
| --- | --- |
| `RunRepository.create_run(run, idempotency_key=)` | 幂等创建；同一幂等键 + 相同 `request_digest` 且 run_id 一致才复用（`reused=True`），同一幂等键绑定不同内容在任何副作用产生前关闭式失败；只接受 `request_digest` 合法的运行 |
| `RunRepository.get_run(run_id)` | 未知运行返回 `None`，不抛异常 |
| `RunRepository.get_run_by_idempotency_key(idempotency_key)` | 只读重放探针：返回该幂等键已绑定的运行，不产生任何写入 |
| `RunRepository.list_runs(filters)` | 按项目、任务、状态集合和结果等级筛选，稳定排序 |
| `RunRepository.update_run_state(run_id, expected_revision=, state=, updated_at=)` | 必须带 `expected_revision`；修订不匹配拒绝写入；成功返回修订号 +1 的新记录 |
| `AuditRepository.append(event)` | 只能追加；重复 `audit_id` 或乱序 `sequence` 关闭式失败；接口没有 update/delete |
| `ArtifactStore.register(reference)` | 只登记相对引用 + SHA-256 + 类型 + 版本；相同引用幂等，路径冲突拒绝 |
| `EventPublisher.publish / next_sequence / replay` | 结构化事件；每个运行内序号连续，可按创建顺序重放 |
| `JobQueue.enqueue / lease / complete / fail / retry / cancel` | 入队通过幂等索引把「幂等键 → job_id + 请求摘要」绑定；同键同请求复用，同键不同 job_id 或不同请求、同 job_id 换用不同键均拒绝 |
| `UnitOfWork.commit / rollback` | 明确事务边界，只有这一个事务接口（读也是读后 rollback）；`committed` 是该 UoW 自己的结果标志；T80 内存实现只保证已提交状态对外唯一可见、回滚不留部分写入，**不宣称数据库事务** |

接口预留的替换点见 ADR-0001 第 2.3–2.6 节。

## 5. 内存适配器的事务与幂等契约

`steelai/enterprise_lab/adapters/memory.py` 是可执行的接口证明，不是生产实现：

**事务边界**

1. `MemoryStore.state` **始终只代表已提交状态**；运行中的 UoW 只修改自己的私有 working state，仓库文件与系统临时目录都不涉及；
2. 仓库（repository）在创建时就绑定到某一个 UoW 与该 UoW 的生命周期，每次调用都重新校验归属；
3. `commit()` 用一次赋值把已提交状态整体替换为 working state，读方永远不会看到半提交结果；
4. `rollback()` 只丢弃 working state，已提交状态逐字节不变；
5. `commit`/`rollback` 之后，即使调用方提前保存了仓库引用，任何读写都返回 `ENT-UOW-001`；
6. T80 不支持重叠 UoW：同一 store 上第二个 UoW 会被明确拒绝（`ENT-UOW-001`），不会被允许读取第一个 UoW 的未提交数据；正常路径由 `commit`/`rollback` 释放单写者守卫，被放弃的 UoW 由弱引用守卫兜底，不会把 store 永久锁死；
7. `committed` 是 UoW 自己的提交结果标志：commit 后永久为 `True`，rollback 后为 `False`，不会被其他 UoW 之后的提交改写。

**幂等与并发**

8. 创建运行：同一幂等键 + 相同 request_digest + 相同 run_id 才复用；`WorkflowRun.request_digest` 为**必填**的小写 64 位 SHA-256，运行记录不可能在没有请求摘要的情况下入库；同一幂等键绑定不同内容、或同一键换用不同 run_id，都在产生任何 artifact/审计/事件之前返回 `ENT-IDEMPOTENCY-001`；
9. 乐观并发：`expected_revision` 不一致 → `ENT-CONCURRENCY-001`，且不写入；
10. 审计仅追加：重复追加 → `ENT-AUDIT-001`，可读计数不变，接口没有修改或删除入口；
11. 事件顺序：每个运行内序号连续，`replay_events` 按创建顺序返回；
12. 任务幂等：幂等索引把键绑定到 job_id 与请求摘要，同键不同 job_id 或不同 payload、同 job_id 换用不同键都被拒绝；非法状态转换 → `ENT-JOB-001`，重试次数上限后拒绝重试；
13. 路径与哈希安全：绝对路径、穿越、空哈希、大写/长度错误哈希全部拒绝。

## 6. 最小纵向流程

`EnterpriseWorkflowService.start_workflow_run` 只使用**一个**显式 `UnitOfWork`，没有独立的只读会话类型：

```
计算 request_digest（覆盖全部影响副作用的字段，无运行时时间戳）
  → 打开一个 UnitOfWork
      幂等检查（同一事务内，且在 artifact/audit/event 之前）
        - 该幂等键已绑定且 request_digest 与 run_id 都一致
            → 只读取已有 run/artifact/audit/event，然后 rollback 返回已存结果
        - 该幂等键已绑定但内容不同
            → 在任何副作用前 ENT-IDEMPOTENCY-001
        - 未绑定
            → create_run（run 上保存 request_digest）
            → 登记 artifact metadata（相对引用 + SHA-256 + 类型 + 版本）
            → 追加 audit event（仅追加）
            → 发布 domain event（ID/状态/版本/哈希/脱敏摘要）
            → commit（一次原子替换）
```

- 读路径（`read_run` / `list_runs`）同样使用显式 UoW，读完后 `rollback`，不做单独接口；
- `create_run` 在事务内重新校验绑定，是运行记录的唯一写入方，因此即使调用顺序改变也不会绕过幂等闸门；
- 输入只使用公开合成元数据：合成项目 ID、合成任务 ID、合成相对路径与合成长度哈希；
- 流程不读取任何真实科研文件，不打开仓库目录，不访问网络，不使用系统临时目录；
- 一个幂等键只绑定一个运行：同一键换用不同 `run_id` 也返回 `ENT-IDEMPOTENCY-001`，需要另一个运行时必须使用自己的幂等键；
- 幂等重放不追加第二条审计记录或第二个事件，返回第一次登记的 ID；
- 任一环节失败都在同一事务内回滚，已提交状态中不留下部分写入；
- 返回值 `WorkflowRunResult` 只含 ID、状态、修订、请求摘要和哈希列表。

用例级最小示例：

```python
from steelai.enterprise_lab.adapters.memory import MemoryUnitOfWorkFactory
from steelai.enterprise_lab import (
    EnterpriseWorkflowService, WorkflowRunRequest, RunArtifactRequest, AuditEntryRequest,
)

service = EnterpriseWorkflowService(MemoryUnitOfWorkFactory())
result = service.start_workflow_run(
    WorkflowRunRequest(
        project_id="PRJ-T80-DEMO",
        task_id="task_t80demo001",
        idempotency_key="idem-t80-demo-001",
        artifacts=(RunArtifactRequest(
            relative_path="enterprise/demo/manifest.json",
            sha256="a" * 64,
            artifact_type="governance_manifest",
            artifact_version="v1",
        ),),
        audit_entries=(AuditEntryRequest(
            action="run-registered",
            summary="named human review of synthetic metadata",
        ),),
    )
)
```

## 7. 验证

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t80_enterprise_architecture.py
.\scripts\test.ps1
```

专项覆盖：模块导入隔离、默认应用不依赖该包、六边形依赖方向（AST 检查）、领域对象校验、
事务与幂等契约（已提交状态在写入期间不变、重叠 UoW 被拒绝、保存的仓库引用在提交与回滚后失效、
提交后下一个 UoW 可见而回滚后不可见、request_digest 覆盖全部字段并在副作用前冲突、任务幂等索引）、
纵向流程、脱敏输出，以及“不写仓库文件、不写临时目录、不读写环境变量”的边界。
结果记录在本任务的完成报告中，并同步到 `project_log/CHANGELOG.md`。

## 8. 非目标与遗留

非目标见 ADR-0001 第 5 节。T80 之后的真实遗留：

- 领域对象尚未与 T51 治理包（Manifest、审批快照、仅追加发布器）建立正式映射，
  当前是元数据模型而不是治理包的替代实现；
- 还没有 outbox 表结构、投递器、重试与死信语义，Kafka 之前必须先完成这些；
- 内存实现没有持久化、跨进程隔离或并发 worker 语义，不能用于多用户场景；
- T80 不提供 HTTP API、后台 worker、消息消费者，也没有页面入口（按任务要求不新增页面）。
