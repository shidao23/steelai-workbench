# T84 Background Job Worker、心跳与过期租约恢复基线

- 状态：`Done`（真实 PostgreSQL 18.6 验收、两轮契约修正与 Codex 最终技术复核均已完成；2026-09-18 由 `Review` 转为 `Done`，ADR-0005 同步转为 `accepted`）
- 决策日期：2026-09-18；完成日期：2026-09-18
- 验收证据：离线 **72 passed + 65 subtests**、真实 PostgreSQL 18.6 集成 **25 passed + 6 subtests（0 skipped，连续复跑稳定）**、全量 **705 passed / 8 skipped / 358 subtests / 0 failed**、`git diff --check` exit 0、14 项冻结哈希 mismatches = 0
- 边界决策：`docs/enterprise/ADR-0005_BACKGROUND_JOB_WORKER.md`（accepted）
- 前置任务：T80（Ports/领域模型，Done）、T81（Schema/迁移，Done）、T82（PostgreSQL Repository/UoW 与数据库内任务租约，Done）、T83（Outbox Dispatcher，Done）
- 范围：后台任务**执行侧**——有限调用式 Worker、独立租约标识与 `attempts` fencing、心跳续租、失败重试、过期租约恢复、显式 Handler Registry 与离线 Recording Handler
- **不属于本任务**：常驻 worker/daemon/定时器/调度器、Kafka/Redis/Celery/RabbitMQ/FastAPI、真实科研计算、payload/对象存储、监控告警、管理页面、exactly-once
- 两轮契约修正均已完成：第一轮为 outcome 与安全边界收口（五种 outcome 由 status 唯一推导、Handler 只见安全元数据、Registry 显式注册、失败重试与租约恢复复用两次合法转换）；第二轮为 Handler 异常边界收紧（任何 Handler `Exception`，**包括 `DomainError`**，都脱敏并隔离，不再中断批次、不再泄漏原始信息、不再让任务残留 `leased`）与 `JobOutcome` 完整不变量冻结（status 与 `state`/`attempts`/`error_code` 必须一致）
- 本文档**不得**表述为生产级后台任务平台、exactly-once、已接入 Kafka、已有常驻 worker/调度器，或已接入默认 Streamlit 应用

## 0. 验收完成情况（2026-09-18）

- **真实 PostgreSQL 18.6 验收完成**：官方镜像 `postgres:18.6-alpine3.23` 一次性 loopback 容器、空库执行 T81 `upgrade head` 后，25 项场景全部通过（0 skipped，连续复跑稳定），**未新增表、列、索引或迁移**；
- **两轮契约修正完成**：第一轮（五种 outcome 与安全元数据边界、显式 Registry、失败重试与租约恢复复用两次合法转换）；第二轮（Handler 异常边界统一脱敏并隔离、`JobOutcome` 完整不变量冻结）；
- **Codex 最终技术复核通过**：T84 由 `Review` 转为 `Done`，ADR-0005 由 `proposed` 转为 `accepted`；
- 回归与全量证据见 §11；本任务**不构成**生产可用声明（见 §1 与 §11 遗留），也不得表述为已接入 Kafka、已有常驻 worker/调度器或已接入默认应用。

## 1. 交付语义与边界（必须先读）

- Worker 是**有限调用**，不是常驻服务：只有 `run_once()` / `run_batch(limit)` / `reclaim_expired(limit)`，没有 `run_forever`、没有无限循环、没有定时器、没有后台线程；
- `leased` 状态的 `updated_at` 表示**最后一次成功领取或心跳的数据库时间**；没有 `lease_expires_at` 列；
- `lease_timeout_seconds` 是**进程配置**，没有逐任务持久化（见 §11 遗留）；
- T84 使用 **at-least-once** 执行语义，**不是** exactly-once；
- Handler 若产生外部副作用，**必须以稳定的 `job_id` 作为幂等键**（`success_unrecorded` 或租约恢复都会导致同一 `job_id` 再次执行）；
- `payload_digest` 是**请求摘要，不是任务 payload**；T84 **没有实现** payload/对象存储；
- `RecordingJobHandler` 只在内存记录调用，**不代表**真实科研任务已接入；
- **没有**调度器、监控、告警、取消运行中任务或管理页面。

## 2. 文件与模块

```
steelai/enterprise_lab/
    ports/workers.py                    # JobLease / JobExecutionState / JobExecutionRepository / JobHandler / JobHandlerRegistry / JobExecutionContext / JobHandlerError + 安全校验
    application/job_worker.py           # JobWorker（run_once / run_batch / reclaim_expired）、JobWorkerConfig、JobOutcome、OUTCOME_PROPERTIES
    adapters/worker_memory.py           # MemoryJobExecutionRepository + RecordingJobHandler（离线/测试专用，无任何 I/O）
    adapters/postgresql/worker.py       # PostgreSQLJobExecutionRepository（复用既有 background_jobs 表，短事务）
tests/
    test_t84_job_worker.py              # 离线契约测试（59 项）
    test_t84_job_worker_integration.py  # 真实 PostgreSQL 场景（22 项）
```

**公共导入路径**（推荐）：

```python
from steelai.enterprise_lab.ports import JobLease, JobExecutionRepository, JobHandler, JobHandlerRegistry
from steelai.enterprise_lab.application import JobWorker, JobWorkerConfig, JobOutcome
from steelai.enterprise_lab.adapters import MemoryJobExecutionRepository, RecordingJobHandler
from steelai.enterprise_lab.adapters.postgresql import PostgreSQLJobExecutionRepository   # 需要可选依赖
```

顶层 `steelai.enterprise_lab` 也导出上述 T84 公共类型（除 PostgreSQL 适配器）：导入它**不会**加载 SQLAlchemy/Alembic/Psycopg；`import app` 后依旧不加载 `enterprise_lab`、数据库包或 Worker。`application` 包同时导出 T83 的 `OUTBOX_OUTCOME_PROPERTIES` 与 T84 的 `OUTCOME_PROPERTIES`（同名冲突已用不同前缀区分）。

被修改的既有文件：`steelai/enterprise_lab/domain/models.py`（**唯一**领域层改动：`BackgroundJob.transition` 新增 `clear_lease: bool = False`，默认行为不变、不新增状态、不改转换表）、五个包 `__init__.py`（新增导出与更新 docstring）、`TASKS.md`、`docs/ARCHITECTURE.md`、`project_log/CHANGELOG.md`。
**未修改**：T81 `schema.py`/`constraints.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements 文件、`app.py`、`pages/`、科研数据与方法注册表；**未新增表、列、索引、迁移或第三方依赖**。

## 3. 领取语义

PostgreSQL 领取在**一个短事务**内完成：

```sql
SELECT job_id
FROM steelai_enterprise.background_jobs
WHERE state IN ('queued','retrying')
ORDER BY created_at, job_id
LIMIT 1
FOR UPDATE SKIP LOCKED;

UPDATE steelai_enterprise.background_jobs
SET state = 'leased', lease_id = :lease_id, updated_at = now()
WHERE job_id = :job_id AND state IN ('queued','retrying')
RETURNING *;
```

- `queued`/`retrying` → `leased`，写入**全新** `lease_id`，`updated_at` 使用 PostgreSQL 时间；
- **第一次领取不增加** `attempts`（新建任务已是 `attempts = 1`，第一次执行的 `attempt` 为 1）；
- 两个并发 Worker：有两个任务时各领取一个不同任务；只有一个任务时一个领取、另一个**立即得到 `None`**（`SKIP LOCKED`，不等待）；**不使用**任何全局 advisory lock 串行化 Worker。

## 4. 租约、心跳与 fencing

| 写入 | SQL 条件 | 失败码 |
| --- | --- | --- |
| `heartbeat` | `state='leased' AND job_id AND lease_id AND attempts=:attempt` | `ENT-WORKER-CLAIM-001` |
| `mark_succeeded` | 同上 | `ENT-WORKER-CLAIM-001` |
| `mark_failed` | 同上 | `ENT-WORKER-CLAIM-001` |

- 心跳成功后 `updated_at = now()`（数据库时间）；心跳是有限调用，不创建线程；
- 过期判断：`state='leased' AND updated_at <= now() - make_interval(secs => :lease_timeout_seconds)`；
- 每次写入前都在同一事务内 `SELECT ... FOR UPDATE` 复读并校验三方一致，再以同一条件 `UPDATE ... RETURNING`，因此旧 Worker 的三种写入全部关闭式失败，且**不能**覆盖新 Worker 的 `state`/`lease_id`/`attempts`/`updated_at`/`error_code`；同一次租约的重复确认同样失败。

## 5. 状态转换（复用冻结状态机，零新增状态）

| 情形 | 转换 | 结果 |
| --- | --- | --- |
| 执行成功 | `leased → succeeded` | 清除 `lease_id` 与 `error_code`，`updated_at = now()` |
| 不可重试失败 | `leased → failed` | 清除 `lease_id`，保存安全错误码 |
| 可重试失败且 `attempts < max_attempts` | 同一事务内 `leased → failed`，再 `failed → retrying`（`count_attempt=True`） | 只持久化 `retrying`：`attempts + 1`、清除 `lease_id`、保存安全错误码 |
| 已达 `max_attempts` | `leased → failed` | 清除 `lease_id`，不再进入 `retrying` |
| 过期租约且 `attempts < max_attempts` | 同上两步 | `retrying`，`attempts + 1`，`error_code = ENT-WORKER-LEASE-EXPIRED` |
| 过期租约且 `attempts == max_attempts` | `leased → failed` | `error_code = ENT-WORKER-LEASE-EXPIRED`，清除 `lease_id` |

重试判定使用**锁定行的持久化 `max_attempts`**（不是调用方参数）；`attempts` 永不超过 `max_attempts`。
`BackgroundJob.transition(..., clear_lease=True)` 是本任务唯一的领域层契约扩展：`clear_lease` 与 `lease_id` 互斥，默认（保留当前租约）行为不变。

## 6. 执行流程与 Handler

`run_once(job_type=None)`：

1. 生成新的安全 `lease_id`（`lease_<uuid4 hex>`）；
2. **短事务**领取任务并 commit，连接归还连接池；
3. 在任何数据库事务**之外**调用 Handler；
4. Handler 可显式调用 `context.heartbeat()` 续租（失败会以 `ENT-WORKER-CLAIM-001` 关闭式失败并归类为可重试）；
5. 成功后用**独立短事务** `mark_succeeded`；失败后用**独立短事务** `mark_failed`；
6. 输出五种 `JobOutcome` 之一；一个任务的失败不影响同批其他任务。

`JobExecutionContext` 只提供 `job_id`、`job_type`、`run_id`、`attempt`、`max_attempts`、`payload_digest`、`idempotency_key` 与 `heartbeat()`——没有 payload、路径、连接或凭据。
`JobHandlerRegistry` 只支持显式 `register`/`resolve`；重复注册关闭式失败（`ENT-WORKER-CONFIG-001`）；未注册类型以 `ENT-WORKER-HANDLER-NOT-FOUND` 作为不可重试失败写入 `failed`；**不允许**动态 import、entry point 扫描或按字符串加载模块。

### 6.1 Handler 异常边界（第二轮修正）

`handler.execute(context)` 的异常处理是**完全**的：

| 抛出 | 处理 |
| --- | --- |
| `JobHandlerError` | 保留其安全 `error_code` 与 `retryable` |
| **其他一切 `Exception`（含 `DomainError`）** | 一律视为**未分类** Handler 异常 → `JobHandlerError(ENT-WORKER-EXECUTION-001, retryable=True)` |
| `KeyboardInterrupt` / `SystemExit` 等 `BaseException` | **不吞掉**，直接向上传播（操作员信号必须到达调用方） |

因此：

- Handler 抛出的 `DomainError` **不会**再传播出 `run_once`/`run_batch`，**不会**中断同批后续任务，也**不会**让任务残留 `leased`——它会被正常记入 `retrying`（或达上限时记入 `failed`）；
- 原始 `code`、`message`、`details`、URL、host、凭据、路径与异常类型都**不会**进入 outcome、数据库或调用方；持久化的只有 `ENT-WORKER-EXECUTION-001`；
- 修复点位于 **Handler 执行边界**：`run_batch` 外层**没有**笼统吞异常，Repository 错误与配置错误（例如领取失败或非法 `limit`）仍然照常向上抛出，不会被掩盖。

### 6.2 幂等边界（反复强调）

Handler 若产生外部副作用，**必须以稳定的 `job_id` 作为幂等键**：`success_unrecorded` 或租约恢复都会导致同一 `job_id` 再次执行。
**enqueue 时使用的 `idempotency_key` 不能替代这一要求**：它只保证入队不重复，无法阻止同一任务在确认失败后被再次执行，也无法为外部系统提供去重依据。

## 7. Worker Outcome（五种，属性与持久化字段都被强约束）

| status | handler_succeeded | persistence_state_known | reexecution_possible |
| --- | --- | --- | --- |
| `succeeded` | true | true | false |
| `retry_scheduled` | false | true | true |
| `failed_terminal` | false | true | false |
| `success_unrecorded` | true | false | true |
| `failure_unrecorded` | false | false | true |

- `success_unrecorded`：Handler 已执行成功但成功状态未提交 → 租约过期后**可能再次执行**（at-least-once 副作用风险，不得写成最终成功）；
- `failure_unrecorded`：Handler 失败且失败状态也未提交；
- 未知 status 一律拒绝（`ENT-WORKER-CONFIG-001`）。

### 7.1 不变量（第二轮修正）

`JobOutcome` 只能表达自洽的结果；任何违反下表组合的构造都以 `ENT-WORKER-CONFIG-001` 关闭式失败：

| status | `state` | `attempts` | `error_code` |
| --- | --- | --- | --- |
| `succeeded` | `succeeded` | == `attempt` | 必须为 `None` |
| `retry_scheduled` | `retrying` | == `attempt + 1` | 必填（安全码） |
| `failed_terminal` | `failed` | == `attempt` | 必填（安全码） |
| `success_unrecorded` | `None` | `None` | 必填（安全码） |
| `failure_unrecorded` | `None` | `None` | 必填（安全码） |

因此一个 outcome **不可能**：声称 `succeeded` 却报告 `state=failed`、已知失败却缺少错误码、未知状态却携带持久化 `state`/`attempts`、或把 `attempts` 写成 `bool`/负数/字符串。五种真实输出路径（成功、可重试失败、终止失败、确认未提交、失败未记录）都有测试证明其产出满足该不变量。

## 8. 错误码边界

| 情形 | 码 |
| --- | --- |
| 领取失效 / `attempts` 不匹配 / 租约过期后的旧写入 | `ENT-WORKER-CLAIM-001` |
| 未知 Handler 异常（含不安全自定义码回退） | `ENT-WORKER-EXECUTION-001` |
| 未注册 Handler（写入 `failed`，不可重试） | `ENT-WORKER-HANDLER-NOT-FOUND` |
| 租约恢复写入的固定码 | `ENT-WORKER-LEASE-EXPIRED` |
| 非法配置 / `limit` / `timeout` / 不安全错误码 | `ENT-WORKER-CONFIG-001` |
| 数据库异常 | 沿用 T82 SQLSTATE/约束名映射（`ENT-DB-001`…`ENT-DB-005`） |

**禁止**持久化 traceback、异常消息、URL、主机名、用户名/密码、payload 内容或文件路径；`error_code` 只接受安全 token（`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，且不超过列宽 64）。

## 9. 离线契约测试（72 passed + 65 subtests）

`tests/test_t84_job_worker.py` 覆盖：`queued → leased → succeeded`；第一次领取 `attempt=1` 且不增加 `attempts`；Handler 在领取边界关闭后执行（断言 `in_short_transaction == False`）；Handler 只拿到安全元数据；`heartbeat` 使用当前租约并延长租约；Handler 内显式心跳；过期前不回收、过期后恢复为 `retrying` 且 `attempts+1`、达上限进入 `failed`；每次领取 `lease_id` 不同；旧租约无法心跳/成功确认/记录失败；重复确认不静默成功；可重试 `HandlerError → retrying`；不可重试 `→ failed`；达上限 `→ failed`；未注册 Handler `→ failed`；未知异常只保存 `ENT-WORKER-EXECUTION-001`；原始异常、URL、host、凭据、路径均不泄漏；`success_unrecorded` 与 `failure_unrecorded` 语义；一个任务失败不阻断批次；重复注册关闭式失败；非法配置/`limit`/`timeout` 关闭式失败；Registry 不使用动态加载；Recording Handler 无文件/网络/子进程 I/O；无无限循环/定时器/后台线程；`import app` 不加载 `enterprise_lab`、数据库包或 Worker；公共导入路径可用且不加载可选依赖；`BackgroundJob.transition` 可显式清空租约且既有行为不变。

第二轮契约修正新增的用例（`HandlerExceptionBoundaryTests` 与 `JobOutcomeInvariantTests`）：

| 用例 | 断言要点 |
| --- | --- |
| `test_a_handler_domain_error_does_not_break_the_batch_or_leak` | Handler 抛出带伪连接串、密码、host、Windows 路径与 `details` 的 `DomainError` 后：该任务依次得到 `retry_scheduled`（attempt 1）与 `failed_terminal`（attempt 2，达上限），同批第二、三个任务**仍正常成功**；失败行**不再残留 `leased`**（`state=failed`、`lease_id=None`）、`error_code` 仅为 `ENT-WORKER-EXECUTION-001`；返回值、序列化结果与任务行都不含 7 类敏感片段 |
| `test_a_handler_domain_error_at_the_attempt_limit_is_terminal` | 同一 `DomainError` 在 `max_attempts=1` 时形成 `failed_terminal`（`state=failed`、清租约、安全码） |
| `test_run_once_never_raises_a_handler_domain_error` | `run_once` 直接返回 outcome，不向外抛出 Handler 的 `DomainError` |
| `test_a_handler_domain_error_is_recorded_like_any_unknown_failure` | 持久化码长度 ≤ 64 且不等于原始码 |
| `test_base_exceptions_are_not_swallowed` | `KeyboardInterrupt`/`SystemExit` 照常传播；随后租约过期可被回收 |
| `test_a_repository_claim_failure_is_not_swallowed` | Repository 领取错误仍向上抛出（`run_batch` 与 `run_once` 都不掩盖） |
| `test_a_configuration_error_is_not_swallowed` | 非法 `limit` 关闭式失败且未执行任何 Handler |
| `test_the_call_order_is_claim_handler_then_confirm` | 调用顺序严格为 `claim → handler → mark_succeeded` |
| `test_contradictory_outcomes_are_refused`（表驱动，19 个子用例） | 拒绝：`succeeded`+`state=failed`、`succeeded`+错误码、`succeeded`+`attempts=0/None/错误值`、`retry_scheduled`+`attempts==attempt`、`retry_scheduled`+`state=failed`、已知失败缺错误码、`failed_terminal`+`state=retrying`、未知状态携带 `state`/`attempts`、`attempts` 为 `bool`/负数/字符串 |
| `test_a_boolean_attempt_counter_is_refused_for_retry_outcomes_too` / `test_an_unsafe_error_code_is_refused` | 布尔计数与不安全错误码都被拒绝 |
| `test_the_five_real_worker_paths_satisfy_the_invariants` | 五条真实输出路径的 `state`/`attempts`/`error_code` 与不变量表逐条一致 |

## 10. 真实 PostgreSQL 验收

| 项目 | 值 |
| --- | --- |
| 镜像 | `postgres:18.6-alpine3.23`（`sha256:697c180dbf244d3ce4a8f4cbc0156cde840af055c1bf8b76aebe422a4822086f`，`amd64/linux`） |
| 容器 | `steelai-t84-postgres-test`，标签 `com.steelai.task=T84`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，`RestartPolicy=no`，无 volume |
| 端口 | `127.0.0.1:55468 → 5432`（loopback-only） |
| 数据库/用户 | `steelai_enterprise_test` / `steelai_t84_test`（密码运行时随机生成，验收后销毁） |
| 前置 | 空库执行 T81 `alembic upgrade head` 后再运行 T84 验收；T84 **未新增表、列、索引或迁移** |
| 结果 | **25 passed + 6 subtests**（0 skipped，连续复跑稳定） |

| # | 场景 | 结果 |
| --- | --- | --- |
| 1 | T82 `enqueue` 的 `queued` job 可被 T84 Worker 执行 | 通过 |
| 2 | 两个并发 Worker 不领取同一个 job | 通过 |
| 3 | 两个任务可以重叠执行（Barrier 证明 Handler 同时运行） | 通过 |
| 4 | 只有一个任务时第二个 Worker 立即得到 `None`（< 5 s 且第一个仍持租约） | 通过 |
| 5 | Handler 执行时 `pool.checkedout() == 0`（单 Worker 严格 0；并发时不超过他方一个短事务连接） | 通过 |
| 6 | 成功后 `state=succeeded`、`lease_id=NULL`、`error_code=NULL`、`attempts` 保留 | 通过 |
| 7 | 可重试失败原子进入 `retrying` 且 `attempts + 1` | 通过 |
| 8 | 下一次领取获得全新 `lease_id` | 通过 |
| 9 | 达 `max_attempts` 后 `failed` 且不再领取 | 通过 |
| 10 | `heartbeat` 用数据库时间更新 `updated_at`（落在数据库时钟区间内） | 通过 |
| 11 | 心跳后在 timeout 内不被回收 | 通过 |
| 12 | timeout 后被回收（`retrying`，`attempts + 1`，`ENT-WORKER-LEASE-EXPIRED`） | 通过 |
| 13 | 旧 Worker 的 heartbeat / `mark_succeeded` / `mark_failed` 三种写入全部 `ENT-WORKER-CLAIM-001` | 通过 |
| 14 | 新 Worker 的 `state`/`lease_id`/`attempts`/`updated_at`/`error_code` 未被旧 Worker 覆盖 | 通过 |
| 15 | Handler 成功但确认事务被真实约束拒绝 → `success_unrecorded`，租约恢复后以 attempt 2 重新执行 | 通过 |
| 16 | Handler 失败且失败事务未提交 → `failure_unrecorded`，行保持 `leased` 且 `error_code` 为空 | 通过 |
| 17 | 未注册 Handler 安全失败（`failed` + `ENT-WORKER-HANDLER-NOT-FOUND`） | 通过 |
| 18 | 无原始异常文本进入 `error_code`（行内不含 URL/host/密码/路径/异常名） | 通过 |
| 19 | 所有短事务后 `pool.checkedout() == 0` | 通过 |
| 20 | `pg_stat_activity` 无 `idle in transaction` | 通过 |
| 21 | 既有 T82 `complete`-vs-`fail` 并发测试语义仍成立（一个成功、另一个 `ENT-JOB-001`） | 通过 |
| 22 | T83 Dispatcher 回归不受影响（同一数据库上 outbox 仍可投递，且 job 租约不受影响） | 通过 |
| 23 | **真实库上的 Handler `DomainError`**：`ENT-WORKER-EXECUTION-001`（attempt 1 `retry_scheduled`、attempt 2 达上限 `failed_terminal`），行不残留 `leased`，同批第二个任务成功，行内与 outcome 内无 7 类敏感片段 | 通过 |
| 24 | **真实库上的 outcome 不变量**：三条持久化路径的 `state`/`attempts`/`error_code` 与数据库行逐项一致（`attempts == attempt + offset`） | 通过 |
| 25 | 真实 Repository + Handler 组合执行成功（集成套件不使用假 Repository） | 通过 |

并发测试使用有界线程池与 starting barrier（只在并发段开始前设置），失败不会无限等待。

## 11. 复现命令、回归与遗留

```powershell
$env:STEELAI_TEST_DATABASE_URL = "postgresql+psycopg://<user>:<pw>@127.0.0.1:55468/steelai_enterprise_test"
$env:STEELAI_ENTERPRISE_DATABASE_URL = $env:STEELAI_TEST_DATABASE_URL
$env:STEELAI_ENTERPRISE_TEST_DATABASE_ONLY = '1'

.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t84_job_worker.py
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t84_job_worker_integration.py
```

未设置 `STEELAI_TEST_DATABASE_URL` 时集成测试明确 skip；离线测试不需要数据库。

**回归证据**（同一轮验收，第二轮修正后复跑）：T80 **74 passed**；T81 schema **28 passed**、migrations **26 passed + 0 skipped**；T82 离线 **57 passed**、集成 **22 passed**；T83 离线 **67 passed + 74 subtests**、集成 **17 passed**；Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **705 passed、8 skipped、358 subtests、0 failed**；`git diff --check` exit 0。

**冻结哈希证据**：T81 `schema.py`/`constraints.py`/`config.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements、两份热模拟数据、方法注册表、科研数据契约与全局治理配置共 **14 项复测，mismatches = 0**。

**遗留问题（真实存在，不得隐藏，也不得写成已解决）：**

1. **`lease_timeout_seconds` 是进程配置，没有逐任务持久化**：同一部署中的所有 worker 与 reaper 必须使用一致值；不同值会让租约过早或过晚被回收；
2. 心跳频率由 Handler 决定：长时间不调用 `context.heartbeat()` 的 Handler 会被判定过期并**重复执行**；
3. 无取消运行中任务的机制（`cancelled` 只在领取前生效）；
4. 无调度、优先级、限流与公平性；吞吐取决于调用方调用 Worker 的频率；
5. 无监控、告警、指标与死信队列；`failed` 需要人工处置；
6. 重试无抖动，也没有按任务类型的差异化重试策略；
7. 没有 payload/对象存储：Handler 只拿得到 `payload_digest`；
8. `RecordingJobHandler` 不代表真实科研任务；T84 不执行任何真实模型或数据管线；
9. 只在 PostgreSQL 18.6 单实例验证，未覆盖复制、PgBouncer 或托管服务下的租约语义。

以上 1–9 均为能力边界说明：它们**不会**造成状态丢失或 fencing 失效（未确认的执行结果仍由租约恢复接管，`attempts` 单调递增并继续作为 fencing token，旧 Worker 无法覆盖新租约），但本任务**不声称**已解决它们。
