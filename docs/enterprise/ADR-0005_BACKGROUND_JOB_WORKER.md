# ADR-0005 Background Job Worker、心跳与过期租约恢复

- 状态：`accepted`
- 决策日期：2026-09-18
- 接受日期：2026-09-18
- 决策范围：Enterprise Lab 后台任务的**执行侧**（有限调用式 Worker、独立租约标识与 fencing、心跳续租、失败重试、过期租约恢复、显式 Handler Registry）
- 相关任务：T80（Ports 与领域模型，Done）；T81（Schema 与迁移基线，Done）；T82（PostgreSQL Repository/UoW 与数据库内任务租约，Done）；T83（Outbox Dispatcher，Done）；T84（本 ADR 的引入者，Done）；T85 及以后（常驻 worker 服务、调度器、Kafka、API、监控）
- 相关文档：`docs/enterprise/ADR-0002_POSTGRESQL_PERSISTENCE.md`、`docs/enterprise/ADR-0003_POSTGRESQL_UNIT_OF_WORK.md`、`docs/enterprise/ADR-0004_OUTBOX_DISPATCHER.md`、`docs/enterprise/T84_BACKGROUND_JOB_WORKER.md`
- 边界前置：本 ADR **不修改** T80 领域模型与既有 `JobQueue`/`EventPublisher` 契约，**不修改** T81 冻结迁移 `0001_enterprise_baseline`、Schema、约束与既有 DDL，**不新增表、列、索引、迁移或第三方依赖**，也不接 Kafka/Redis/Celery/RabbitMQ/FastAPI
- 验收结论（2026-09-18）：PostgreSQL 18.6 **真实集成验收通过**（25 项场景、0 skipped）；**两轮契约修正完成**（第一轮：五种 outcome 与安全元数据边界、显式 Registry、两次合法转换的重试与租约恢复；第二轮：Handler 异常边界统一脱敏并隔离、`JobOutcome` 完整不变量冻结）；**Codex 最终技术复核通过**；T84 由 `Review` 转为 `Done`，本 ADR 由 `proposed` 转为 `accepted`。
- `accepted` 的适用范围：它只表示**本 ADR 第 2 节所限定的架构决策与其实现**通过验收，**不构成生产可用声明**，也不代表超出该范围的任何能力已经具备（见第 4 节）。

## 1. 背景

T82 建立了 `background_jobs` 表与数据库内租约：`enqueue`、`lease`（`FOR UPDATE SKIP LOCKED`）、`complete`/`fail`/`retry`/`cancel` 与乐观的状态机校验。**但 T82 没有执行者**：没有任何组件把 `leased` 任务真正跑起来、续租、或者在 worker 崩溃后把过期租约回收。

T83 为 outbox 建立了"领取 → 事务外发送 → 确认/重试 → 租约恢复"的派发闭环，并证明了这个形状可行。T84 把同一形状用于**后台任务执行**，但执行语义与它有两处本质差别：

1. 执行会产生**外部副作用**，因此"已执行但确认失败"必须如实报告，不能当作完成；
2. 任务执行可能很长，因此租约需要**心跳续租**，需要一个独立的租约标识来 fencing。

## 2. 决策

### 2.1 独立的执行 Port，不扩展既有 JobQueue

- 新增 `steelai/enterprise_lab/ports/workers.py`：不可变 `JobLease`（`BackgroundJob` + `lease_id` + `attempt` + `leased_at`/`heartbeat_at` + `worker_id`）、`JobExecutionRepository`（`claim_next` / `heartbeat` / `mark_succeeded` / `mark_failed` / `reclaim_expired`）、`JobHandler`、`JobHandlerRegistry`、`JobExecutionContext`、`JobHandlerError`。
- T80 `JobQueue` 与 T82 `PostgreSQLJobQueue` **保持原语义**：`enqueue`、基础状态查询与状态机演练继续由它们负责。分布式 worker 的租约语义不塞回旧接口。
- T84 Worker **不调用** T82 无 fencing 参数的 `complete`/`fail` 作为执行确认入口：所有执行确认都走 `JobExecutionRepository`，并带完整 fencing 三元组。
- 投递状态与执行状态都不进入领域对象：`BackgroundJob` 不新增字段。

### 2.2 独立租约标识 + attempts 共同 fencing

- 每次领取写入**全新** `lease_id`（`lease_<uuid4 hex>`，安全 token，不含主机、路径或凭据）；
- `job_id + lease_id + attempt` 是唯一的写入条件；`attempt` 等于 `BackgroundJob.attempts`；
- 所有 Worker 写操作的 SQL 都要求 `state = 'leased'` **且** `job_id`、`lease_id`、`attempts` 同时匹配；0 行受影响即 `ENT-WORKER-CLAIM-001`；
- 因此租约过期、任务被重新领取后，旧 Worker 的 heartbeat / 成功确认 / 失败记录**全部**关闭式失败，且**不可能**覆盖新 Worker 的 `state`、`error_code` 或 `updated_at`；同一次租约的重复确认也不会静默成功。

### 2.3 attempts 的既有契约（不新增状态）

- 新建任务已是 `attempts = 1`，表示当前执行尝试编号；
- **第一次领取不增加** `attempts`，因此第一次执行的 `attempt` 为 1；
- 只有"失败后安排下一次尝试"或"过期租约恢复"时才 `attempts + 1`；
- `attempts` 永不超过 `max_attempts`（复用 T80 的 `ck_background_jobs_attempts_within_limit` 与领域校验）。

### 2.4 租约与心跳只使用数据库时间

- 不新增 `lease_expires_at` 列：`leased` 状态的 `updated_at` 表示**最后一次成功领取或心跳的数据库时间**；
- `heartbeat(job_id, lease_id, attempt)` 成功后 `updated_at = now()`（PostgreSQL 时间）；旧租约、错误 `attempt`、非 `leased` 状态一律返回 `ENT-WORKER-CLAIM-001`；
- 心跳是**有限调用**：不创建后台线程、不注册定时器；
- 过期判断：`state = 'leased' AND updated_at <= now() - lease_timeout_seconds`；
- `lease_timeout_seconds` 是**进程配置**，没有逐任务持久化：同一部署中的所有 worker 与 reaper 必须使用一致值（列入遗留问题）。

### 2.5 失败、重试与租约恢复复用冻结状态机

不新增 `JobState`，不改 `ALLOWED_JOB_TRANSITIONS`，不写第二套状态机；所有状态变化都由 `BackgroundJob.transition` 完成：

- 成功：`leased → succeeded`，清除 `lease_id` 与 `error_code`，`updated_at` 用数据库时间；
- 不可重试失败或已达上限：`leased → failed`，清除 `lease_id`，保存安全错误码；
- 可重试失败且 `attempts < max_attempts`：**同一事务内两次合法转换**（`leased → failed`，再 `failed → retrying` 且 `count_attempt=True`），最终只持久化 `retrying`：`attempts + 1`、清除 `lease_id`、保存安全错误码、`updated_at` 用数据库时间；
- 过期租约与上述一致：`attempts < max_attempts → retrying`（`attempts + 1`），否则 `failed`，`error_code` 固定为 `ENT-WORKER-LEASE-EXPIRED`，并清除 `lease_id`。

**契约最小扩展**：`BackgroundJob.transition` 新增 `clear_lease: bool = False`，用于显式清空租约；`clear_lease` 与 `lease_id` 互斥，默认行为（保留当前租约）完全不变。这是本 ADR 允许的唯一领域层改动，不新增状态、不改变转换表。

### 2.6 Handler 只拿到安全元数据，Registry 显式注册

- `JobExecutionContext` 只提供 `job_id`、`job_type`、`run_id`、`attempt`、`max_attempts`、`payload_digest`、`idempotency_key` 与 `heartbeat()`：不提供任务 payload、文件路径、数据库连接或凭据；
- `payload_digest` 是**请求摘要，不是 payload**；T84 没有实现 payload/对象存储；
- `JobHandlerRegistry` 只做显式 `register`/`resolve`：**不允许**动态 import、entry point 扫描或按字符串加载模块；重复注册同一 `job_type` 关闭式失败，未注册类型以 `ENT-WORKER-HANDLER-NOT-FOUND` 作为**不可重试**失败写入 `failed`；
- `RecordingJobHandler` 只在内存记录调用，供离线演练与测试，**不代表真实科研任务已接入**。

### 2.6.1 Handler 异常边界是完全的（第二轮修正）

`handler.execute(context)` 的异常处理必须覆盖整个 `Exception` 谱系：

- `JobHandlerError` 按其安全 `error_code`/`retryable` 处理；
- **其他所有 `Exception`，包括 `DomainError`**，一律视为**未分类** Handler 异常，统一转换为 `JobHandlerError(ENT-WORKER-EXECUTION-001, retryable=True)`；
- 因此 Handler 的 `DomainError` **不得**传播出 `run_once`/`run_batch`、**不得**中断同批后续任务、**不得**让任务残留 `leased`，也**不得**把原始 `code`/`message`/`details`/URL/host/凭据/路径/异常类型暴露给 outcome、数据库或调用方；
- `KeyboardInterrupt`、`SystemExit` 等 `BaseException` **不吞掉**：操作员信号必须到达调用方，租约留给过期恢复；
- 修复点位于 **Handler 执行边界**：不得在 `run_batch` 外层笼统吞异常，Repository 错误与配置错误仍照常向上抛出。

### 2.6.2 幂等边界

Handler 产生外部副作用时**必须以稳定的 `job_id` 作为幂等键**；enqueue 使用的 `idempotency_key` **不能**替代这一要求：它只保证入队不重复，无法阻止同一任务在确认失败或租约恢复后被再次执行。

### 2.7 错误只带安全字段

- `JobHandlerError(error_code, retryable)` 只携带安全错误码与重试提示；不允许不安全码（含 URL、路径、host、凭据或自由文本）；
- 未知 Handler 异常统一映射为 `ENT-WORKER-EXECUTION-001`（可重试，直到用尽尝试预算）；
- 未找到 Handler → `ENT-WORKER-HANDLER-NOT-FOUND`（不可重试）；
- 领取失效/`attempts` 不匹配/租约过期 → `ENT-WORKER-CLAIM-001`；租约恢复写入固定码 `ENT-WORKER-LEASE-EXPIRED`；非法配置 → `ENT-WORKER-CONFIG-001`；
- **禁止**持久化 traceback、异常消息、URL、主机名、用户名/密码、payload 内容或文件路径；数据库异常继续沿用 T82 的 SQLSTATE 脱敏映射。

### 2.8 执行结果是五种状态，属性与持久化字段都被强约束

| status | handler_succeeded | persistence_state_known | reexecution_possible |
| --- | --- | --- | --- |
| `succeeded` | true | true | false |
| `retry_scheduled` | false | true | true |
| `failed_terminal` | false | true | false |
| `success_unrecorded` | true | false | true |
| `failure_unrecorded` | false | false | true |

- `success_unrecorded`：Handler 已执行成功，但成功状态未提交，租约过期后任务**可能再次执行**——这正是 at-least-once 的副作用风险，必须显式暴露，不得写成最终成功；
- `failure_unrecorded`：Handler 执行失败，且失败状态也未提交；
- 两种未知状态都允许后续 worker 通过租约恢复接管，因此都不能当作完成；
- 未知 status 一律拒绝（`ENT-WORKER-CONFIG-001`）。

**完整不变量（第二轮修正）**：一个 outcome 还必须与其声称的持久化字段一致，否则以 `ENT-WORKER-CONFIG-001` 关闭式失败：

| status | `state` | `attempts` | `error_code` |
| --- | --- | --- | --- |
| `succeeded` | `succeeded` | `attempt` | 必须为 `None` |
| `retry_scheduled` | `retrying` | `attempt + 1` | 必填 |
| `failed_terminal` | `failed` | `attempt` | 必填 |
| `success_unrecorded` | `None` | `None` | 必填 |
| `failure_unrecorded` | `None` | `None` | 必填 |

`attempts` 为 `bool`、负数或字符串一律拒绝。这样 outcome 既不能声称已持久化的状态却没写对，也不能为"状态未知"编造持久化字段。

### 2.9 有限调用，事务外执行

- `JobWorker` 只提供 `run_once` / `run_batch(limit)` / `reclaim_expired(limit)`：没有 `run_forever`、没有无限循环、没有定时器、没有后台线程；
- 领取是**一次短事务**并先 commit；Handler **在任何数据库事务之外**执行；成功/失败确认各自是新的短事务；
- 一个任务的失败（含未知状态）不中断同批其他任务；
- **不实现** Windows 服务、daemon、自动启动、调度器。

## 3. 后果与代价

**执行语义（必须随任何 T84 结论一起引用）：**

- T84 提供 **at-least-once** 执行，**不是** exactly-once，也不声称 exactly-once；
- Handler 若产生外部副作用，**必须以稳定的 `job_id` 作为幂等键**：确认失败（`success_unrecorded`）或租约过期恢复都会导致同一 `job_id` 再次执行；
- `RecordingJobHandler` 只能证明接口与流程，**不代表**真实科研任务、模型执行或数据管线已接入。

**代价与风险：**

- `lease_timeout_seconds` 没有逐任务持久化，是进程配置：配置不一致会让租约过早或过晚被回收（列入遗留问题）；
- 心跳频率由 Handler 自行调用 `context.heartbeat()`：长时间不心跳的 Handler 会被回收并重复执行；
- 没有取消运行中任务的机制（`cancelled` 只在领取前生效）；
- 没有调度、优先级、限流与公平性；吞吐取决于调用方调用 worker 的频率；
- 没有监控、告警、指标与死信队列；`failed` 需要人工处置；
- 失败重试没有抖动，也没有按任务类型的差异化策略；
- 只在 PostgreSQL 18.6 单实例验证。

## 4. 明确不属于本 ADR / T84 的范围

- 常驻 worker 服务、Windows 服务、daemon、自动启动、定时器与调度器：**未实现**；
- Kafka、RabbitMQ、Redis、Celery、FastAPI：**未接入**；
- 真实科研计算、模型执行、数据管线或文件读写：**未实现**；Handler 只接收安全元数据；
- payload/object store：**未实现**（`payload_digest` 只是请求摘要）；
- 监控、告警、指标、分布式追踪、管理页面与人工重放控制台：**未实现**；
- 取消运行中任务、跳过失败任务、按 run/任务的人工解锁：**未实现**；
- exactly-once 执行：**未实现，也未声称**；
- 默认 SteelAI 应用接入 worker 或数据库：**未接入**；`app.py`、`pages/`、Streamlit 默认入口与 T76 启动器都不导入 T84 代码；
- 修改 T80 领域模型/既有 Port 契约（`transition` 的 `clear_lease` 除外）、T81 Schema/迁移、新增表/列/索引/迁移或第三方依赖：**禁止**（本 ADR 的前置边界）。

本 ADR 与 T84 都**不得**表述为生产可用或 exactly-once 已实现；也不得表述为已接入 Kafka、已有常驻 worker 服务或调度器、或已接入默认 Streamlit 应用。

本 ADR 由 `proposed` 转为 `accepted` 只表示**第 2 节所限定的决策**通过验收。第 2 节的全部技术决策在验收后**保持不变**：

- `job_id + lease_id + attempt` 三元 fencing，所有 Worker 写入都必须同时匹配 `state='leased'`；
- Handler 在**任何数据库事务之外**执行，领取与确认各自是短事务；
- 心跳与租约过期判断使用**数据库时钟**（`leased` 行的 `updated_at` 即最后心跳时间）；
- 过期租约恢复：`attempts` 未达上限 → `retrying`（`attempts+1`），已达上限 → `failed`，固定码 `ENT-WORKER-LEASE-EXPIRED`；
- 五种 outcome（`succeeded`/`retry_scheduled`/`failed_terminal`/`success_unrecorded`/`failure_unrecorded`）及其完整不变量；
- **at-least-once** 执行语义，Handler 外部副作用以稳定 `job_id` 为幂等键；
- `JobState` 与既有转换集合（`ALLOWED_JOB_TRANSITIONS`）不变。
