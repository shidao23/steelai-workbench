# T83 事务型 Outbox Dispatcher、租约恢复与至少一次投递基线

- 状态：`Done`（真实 PostgreSQL 18.6 验收、第一轮契约修正与 Codex 最终技术复核均已完成；2026-09-18 由 `Review` 转为 `Done`，ADR-0004 同步转为 `accepted`）
- 决策日期：2026-09-18；完成日期：2026-09-18
- 验收证据：离线 **67 passed + 74 subtests**、真实 PostgreSQL 18.6 集成 **17 passed（0 skipped，连续复跑稳定）**、全量 **608 passed / 8 skipped / 287 subtests / 0 failed**、`git diff --check` exit 0
- 边界决策：`docs/enterprise/ADR-0004_OUTBOX_DISPATCHER.md`
- 前置任务：T80（Ports/领域模型，Done）、T81（Schema/迁移，Done）、T82（Outbox 写入侧/UnitOfWork，Done）
- 范围：outbox 派发侧——有限调用式 Dispatcher、租约与 `attempts` fencing、失败重试、终止失败、过期租约恢复、离线 Recording Transport
- **不属于本任务**：Kafka/RabbitMQ/Redis/Celery、常驻 worker/daemon/定时器、HTTP API、RBAC、多租户、监控告警、人工重放控制台、exactly-once

## 0. 验收完成情况（2026-09-18）

- **真实 PostgreSQL 验收完成**：官方镜像 `postgres:18.6-alpine3.23` 一次性容器、空库执行 T81 `upgrade head` 后，17 项场景全部通过（0 skipped，连续复跑稳定），**未新增列或迁移**；
- **第一轮契约修正完成**：派发结果由三种（含含义混淆的 `unacknowledged`）拆分为五种并改为由 status 唯一推导三个属性；`failure_unrecorded` 不再错误报告为 delivered；`OutboxClaim`/`OutboxReclaim` DTO 契约收紧；T83 公共包出口收口；
- **Codex 最终技术复核通过**：T83 由 `Review` 转为 `Done`，ADR-0004 由 `proposed` 转为 `accepted`；
- 回归与全量证据见 §11；本任务**不构成**生产可用声明（见 §1 与 §11 遗留）。

## 1. 交付语义（必须先读）

- T83 提供 **at-least-once**，**不是** exactly-once，也不声称 exactly-once；
- **transport 发送成功但数据库确认失败**时（确认事务失败、进程崩溃、租约被其他 worker 接管），事件会在**租约恢复后再次发送**；
- 因此**下游必须以 `event_id` 作为幂等键**去重；
- `RecordingEventTransport` 只在内存中记录将要发送的内容，用于离线演练与测试：它只能证明接口与流程，**不能**代表 Kafka 已接入；
- T83 **不提供**常驻 worker、监控、告警或人工重放控制台。

### 1.1 五种派发结果（status 唯一决定三个属性）

| status | delivered | persistence_state_known | redelivery_possible | 含义 |
| --- | --- | --- | --- | --- |
| `published` | true | true | false | 发送成功，`published` 已提交 |
| `retry_scheduled` | false | true | true | 发送失败，已持久化 `pending` + 退避 |
| `failed_terminal` | false | true | false | 发送失败且不可重试或已达上限，已持久化 `failed` |
| `sent_unacknowledged` | true | false | true | **确实发送过**，但确认未提交，最终状态未知 |
| `failure_unrecorded` | false | false | true | **没有发送成功**，且失败状态也未记录，最终状态未知 |

- `sent_unacknowledged`：transport 真实返回成功；确认写入失败（或租约已被接管）。事件**已经**外发，下游可能已收到，因此 `delivered=true`，但数据库最终状态未知。
- `failure_unrecorded`：transport 失败，且 `mark_failed` 也未能提交。事件**没有**被送出，`delivered=false`——把这种情况报告为已送达是错误的。
- 两者都可能被后续 worker 通过租约恢复接管（`redelivery_possible=true`），因此都不能作为"完成"。
- 三个属性与 status 的映射由 `OUTCOME_PROPERTIES` 固定，调用方不能传入互相矛盾的布尔组合；未知 status 会被 `OutboxDispatchOutcome` 以 `ENT-OUTBOX-CONFIG-001` 拒绝。
- 旧属性 `needs_redelivery` 已删除（它把"以后可能重发"与"已送达"混在一起）。

## 2. 未实现项（不得声称）

- Kafka、RabbitMQ、Redis、Celery 与任何真实 broker；
- daemon、Windows 服务、定时器、调度器与常驻进程；
- HTTP API、RBAC、多租户、投递查询接口、人工重放控制台；
- 跳过失败事件、按 run 的人工解锁；
- 监控、告警、指标、分布式追踪与结构化投递日志；
- exactly-once 投递；
- 默认应用接入（`app.py`、`pages/`、Streamlit 入口与 T76 启动器都不导入 T83 代码）。

## 3. 文件与模块

```
steelai/enterprise_lab/
    ports/outbox.py                     # OutboxClaim / OutboxReclaim / OutboxDeliveryState / OutboxDeliveryRepository / EventTransport / TransportError + DTO 契约校验
    application/outbox_dispatcher.py    # OutboxDispatcher（dispatch_batch / reclaim_expired）、OutboxDispatcherConfig、OutboxDispatchOutcome、OUTCOME_PROPERTIES
    adapters/outbox_memory.py           # MemoryOutboxDeliveryRepository + RecordingEventTransport（离线/测试专用，无网络与文件 I/O）
    adapters/postgresql/outbox.py       # PostgreSQLOutboxDeliveryRepository（复用既有 outbox_events 五列，短事务）
tests/
    test_t83_outbox_dispatcher.py       # 离线契约测试（67 项）
    test_t83_outbox_integration.py      # 真实 PostgreSQL 场景（17 项）
```

**公共导入路径**（推荐）：

```python
from steelai.enterprise_lab.ports import OutboxClaim, OutboxDeliveryRepository, EventTransport
from steelai.enterprise_lab.application import OutboxDispatcher, OutboxDispatcherConfig, OutboxDispatchOutcome
from steelai.enterprise_lab.adapters import MemoryOutboxDeliveryRepository, RecordingEventTransport
from steelai.enterprise_lab.adapters.postgresql import PostgreSQLOutboxDeliveryRepository   # 需要可选依赖
```

顶层 `steelai.enterprise_lab` 也导出上述 T83 公共类型（除 PostgreSQL 适配器）：导入它**不会**加载 SQLAlchemy/Alembic/Psycopg；`import app` 后依旧不加载 `enterprise_lab`、数据库包或 Dispatcher。

被修改但**未改逻辑**的既有文件：`steelai/enterprise_lab/__init__.py`、`ports/__init__.py`、`application/__init__.py`、`adapters/__init__.py`、`adapters/postgresql/__init__.py`（仅新增导出与修正过时 docstring），以及 `TASKS.md`、`docs/ARCHITECTURE.md`、`project_log/CHANGELOG.md`。
**未修改**：T80 领域模型与既有 Port 契约、T81 `schema.py`/`constraints.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements 文件、`app.py`、`pages/`、科研数据与方法注册表。

### 3.1 DTO 契约（可直接构造并接受同一套校验）

| 对象 | 强制要求 |
| --- | --- |
| `OutboxClaim` | `delivery_status == 'publishing'`；正整数 `claim_attempt`；**带时区**的 `lease_deadline`；`event` 必须是 `DomainEvent` |
| `OutboxReclaim` | `delivery_status ∈ {pending, failed}`；正整数 `attempts`；`last_error_code` 通过安全错误码校验；`available_at` 带时区 |
| `OutboxDeliveryState` | 已声明的投递状态；`attempts >= 0`（新写入的 `pending` 行为 0）；时间戳带时区；`last_error_code` 安全 |
| `OutboxDispatchOutcome` | 五种已声明状态之一；`error_code` 安全；`available_at` 带时区 |

任何违反都以 `ENT-OUTBOX-CONFIG-001` 关闭式失败，因此 `pending`/`published`/`failed` 的 claim 永远进不了 Dispatcher。

## 4. 状态机（复用既有五列，零迁移）

| 起始 | 事件 | 目标 | 列变化 |
| --- | --- | --- | --- |
| `pending` | 成功领取 | `publishing` | `attempts = attempts + 1`；`available_at = 数据库时间 + lease_seconds`（此时 `available_at` 是租约截止） |
| `publishing` | `mark_published(event_id, claim_attempt)` | `published` | `published_at = 数据库时间`；`last_error_code = NULL`；`attempts` 保留 |
| `publishing` | `mark_failed(..., retryable=True)` | `pending` | `available_at = 数据库时间 + 指数退避`；`last_error_code = 安全错误码` |
| `publishing` | `mark_failed(..., retryable=False)` 或 `attempts` 达上限 | `failed` | `last_error_code = 安全错误码`；不再自动领取 |
| `publishing` | 租约过期且 `attempts` 未达上限 | `pending` | `available_at = 数据库时间 + 首个退避步长`；`last_error_code = ENT-OUTBOX-LEASE-EXPIRED` |
| `publishing` | 租约过期且 `attempts` 已达上限 | `failed` | `last_error_code = ENT-OUTBOX-LEASE-EXPIRED` |

`failed` 是终止态：不自动领取，且**阻塞同一 run 的后续事件**（见 §6）；T83 不提供跳过或解锁入口。

## 5. 领取、fencing 与短事务

**领取 SQL（同一短事务内两条语句）**

```sql
SELECT o.event_id, o.attempts
FROM steelai_enterprise.outbox_events AS o
WHERE o.delivery_status = 'pending'
  AND o.available_at <= now()
  AND o.attempts < :max_attempts
  AND o.sequence = (SELECT min(e.sequence)
                    FROM steelai_enterprise.outbox_events AS e
                    WHERE e.run_id = o.run_id AND e.delivery_status <> 'published')
ORDER BY o.run_id, o.sequence
LIMIT :limit
FOR UPDATE SKIP LOCKED;

UPDATE steelai_enterprise.outbox_events
SET delivery_status = 'publishing',
    attempts = attempts + 1,
    available_at = now() + make_interval(secs => :lease_seconds),
    published_at = NULL
WHERE event_id = :event_id AND delivery_status = 'pending' AND attempts = :seen_attempts
RETURNING *;
```

- `FOR UPDATE SKIP LOCKED` 让两个 dispatcher 领取不同行：不会领取同一 `event_id`，也不会等待另一个 worker；
- `UPDATE ... WHERE attempts = :seen_attempts` 是第二重保护：即使锁异常丢失，也只有刚读到的 `attempts` 能被领取；
- 没有可领取行时**立即返回空列表**，不等待其他 worker；
- 领取事务在 `transport.send` **之前**提交并归还连接；确认与记失败各自是新的短事务；
- 租约时间全部来自 PostgreSQL `now()`，不使用 worker 本机时间。

**fencing**

`mark_published` / `mark_failed` 的 `WHERE` 子句要求 `delivery_status = 'publishing'` **且** `attempts = :claim_attempt`；不匹配时 0 行受影响，适配器抛 `ENT-OUTBOX-CLAIM-001`，旧 worker 无法覆盖新租约。

## 6. 同一 run 的顺序保证

领取谓词的 `sequence = min(该 run 尚未 published 的 sequence)` 一条语句同时给出四个性质：

1. 一个 run 一次只有一个事件处于 `publishing`（顺序投递）；
2. 前序事件未 `published` 时后序事件不可领取（含退避等待期）；
3. 前序事件 `failed` 后，后序事件**持续阻塞**，不跳过、不降级；
4. 不同 run 之间互不影响：可同时 `publishing`，可被不同 dispatcher 并发领取。

## 7. 错误码边界

| 情形 | 码 |
| --- | --- |
| 领取已失效 / `attempts` 不匹配 / 租约过期后的旧确认 | `ENT-OUTBOX-CLAIM-001` |
| 未知 transport 异常（含不安全自定义码回退） | `ENT-OUTBOX-TRANSPORT-001` |
| 非法 `limit` / `lease_seconds` / `max_attempts` / 退避参数 / 不安全错误码 | `ENT-OUTBOX-CONFIG-001` |
| 租约恢复写入的固定码 | `ENT-OUTBOX-LEASE-EXPIRED` |
| 数据库异常 | 沿用 T82 SQLSTATE/约束名映射（`ENT-DB-001`…`ENT-DB-005`） |

`last_error_code` 只保存安全错误码（`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`）：异常文本、URL、host、凭据与 payload 都不可能写入该列，也不会由 Dispatcher 向上返回。

## 8. 离线契约测试（67 passed + 74 subtests）

`tests/test_t83_outbox_dispatcher.py` 覆盖：`pending → publishing → published`；transport 调用发生在领取边界关闭之后（断言 `in_short_transaction == False`、调用顺序 `claim → send → mark_published`）；`event_id` 作为 transport `idempotency_key`；可重试失败回到 `pending` 并设置退避；退避翻倍与封顶；不可重试失败进入 `failed`；`attempts` 达上限进入 `failed`；原始异常信息不泄漏（含含伪连接串/密码的异常）；过期租约恢复；旧 `claim_attempt` 无法确认；旧 `claim_attempt` 无法记失败；同 run 后序事件被前序事件阻塞（含退避中与 `failed` 两种情况）；不同 run 可并行领取；`published` / `failed` 不会重新领取；非法 `limit`/`lease_seconds`/`max_attempts`/退避配置关闭式失败；Recording Transport 不访问网络或文件系统（`socket`/`builtins.open` 被替换为抛异常仍可工作）；以及架构边界（内层不导入数据库/后台框架、无 `while True`/`threading`/`asyncio`）。

第一轮契约修正新增的用例：

- **两种未知状态**：`send 成功 + mark_published 失败 → sent_unacknowledged`（`delivered=True`、`persistence_state_known=False`、`redelivery_possible=True`）；`send 失败 + mark_failed 失败 → failure_unrecorded`（`delivered=False`、`persistence_state_known=False`）；两者的错误码与 payload 都不泄漏原始异常文本、URL、host 或凭据；任一未知状态都**不阻止**同批其他事件继续处理（分别用 2 个与 3 个事件的批次验证）；stale claim 的失败记录失败也归入 `failure_unrecorded`；
- **属性表**：`OUTCOME_PROPERTIES` 与约定的五行映射逐行相等；两种未知状态互不相同且 `failure_unrecorded` 永不 `delivered`；未知 status（含旧的 `unacknowledged`）被拒绝；`needs_redelivery` 已不存在；`to_dict()` 暴露三个属性；
- **DTO 直接构造校验**：`OutboxClaim` 拒绝 `pending`/`published`/`failed`/未声明状态、非法 `claim_attempt`、无时区或不可解析的 `lease_deadline`、非 `DomainEvent`；`OutboxReclaim` 只接受 `pending`/`failed`，拒绝不安全错误码、非正 `attempts`、无时区时间戳；
- **公共导入路径**：`ports` / `application` / `adapters` / 顶层 `enterprise_lab` 的导出清单逐一验证；子进程验证导入这些包**不加载** SQLAlchemy/Psycopg/Alembic 与 PostgreSQL 适配器；`adapters.postgresql` 导出 `PostgreSQLOutboxDeliveryRepository`；`import app` 后不加载 `enterprise_lab`、数据库包与 Dispatcher。

## 9. 真实 PostgreSQL 验收

| 项目 | 值 |
| --- | --- |
| 镜像 | `postgres:18.6-alpine3.23`（`sha256:697c180dbf244d3ce4a8f4cbc0156cde840af055c1bf8b76aebe422a4822086f`，`amd64/linux`） |
| 容器 | `steelai-t83-postgres-test`，标签 `com.steelai.task=T83`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，`RestartPolicy=no`，无 volume |
| 端口 | `127.0.0.1:55468 → 5432`（loopback-only） |
| 数据库/用户 | `steelai_enterprise_test` / `steelai_t83_test`（密码运行时随机生成，验收后销毁） |
| 前置 | 空库执行 T81 `alembic upgrade head` 后再运行 T83 验收；T83 **未**新增任何列或迁移 |
| 结果 | **17 passed**（0 skipped，连续复跑 3 次稳定） |

| # | 场景 | 结果 |
| --- | --- | --- |
| 1 | 两个 dispatcher 并发领取：`event_id` 不重复 | 通过 |
| 2 | 不同 run 的事件可同时处于 `publishing` | 通过 |
| 3 | 同一 run 只领取最小未发布 `sequence` | 通过 |
| 4 | 无可领取行时立即返回空批次（不等待其他 worker） | 通过 |
| 5 | `attempts` 原子递增并作为 fencing token（领取 → 过期 → 恢复 → 再领取为 2） | 通过 |
| 6 | 旧 worker 无法确认新租约（`ENT-OUTBOX-CLAIM-001`，`published_at` 保持为空） | 通过 |
| 7 | 租约过期后可重新领取并成功投递 | 通过 |
| 8 | 过期且达到上限进入 `failed`，不再领取 | 通过 |
| 9 | 成功确认写入 `published_at`，且落在数据库时钟区间内 | 通过 |
| 10 | 可重试失败的 `available_at` 使用数据库时间 + 退避 | 通过 |
| 11 | claim/send/ack 之间无长期 checked-out connection（transport 内 `pool.checkedout() == 0`） | 通过 |
| 12 | 测试结束无 `idle in transaction`，pool 归零 | 通过 |
| 13 | T82 写入的 `pending` outbox 行可被 T83 正常消费，且 `replay` 的领域事件不变 | 通过 |
| 14 | 前序 `failed` 时同 run 后序事件保持阻塞（含过期恢复后仍阻塞） | 通过 |
| 15 | **确认失败 = `sent_unacknowledged`**：真实数据库拒绝确认（冻结 CHECK 约束）后回滚，行保持 `publishing`，租约恢复后同键重发并最终 `published` | 通过 |
| 16 | **失败无法记录 = `failure_unrecorded`**：transport 失败且 `mark_failed` 被真实数据库约束拒绝，`delivered=False`、行保持 `publishing`、`last_error_code` 仍为空，租约恢复后成功投递 | 通过 |
| 17 | transport 失败只持久化安全错误码（行内不含 URL/host/密码/payload） | 通过 |

并发测试使用有界线程池与 starting barrier（只在并发段开始前设置），失败不会无限等待。

## 10. 复现命令

```powershell
$env:STEELAI_TEST_DATABASE_URL = "postgresql+psycopg://<user>:<pw>@127.0.0.1:55468/steelai_enterprise_test"
$env:STEELAI_ENTERPRISE_DATABASE_URL = $env:STEELAI_TEST_DATABASE_URL
$env:STEELAI_ENTERPRISE_TEST_DATABASE_ONLY = '1'

.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t83_outbox_dispatcher.py
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t83_outbox_integration.py
```

未设置 `STEELAI_TEST_DATABASE_URL` 时集成测试明确 skip；离线测试不需要数据库。

## 11. 回归、清理证据与遗留

**测试证据**（同一轮验收，真实集成实跑）：T83 离线 **67 passed + 74 subtests**；T83 真实集成 **17 passed + 0 skipped**（连续复跑稳定）；T82 离线/集成 **57 passed / 22 passed**；T81 schema/migrations **28 passed / 26 passed + 0 skipped**；T80 回归 **74 passed**；Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **608 passed、8 skipped、287 subtests、0 failed**；`git diff --check` exit 0。

**冻结哈希证据**：T81 `schema.py`/`constraints.py`/`config.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements、两份热模拟数据、方法注册表、科研数据契约与全局治理配置共 **14 项复测，mismatches = 0**；T83 未新增列、索引、迁移或依赖。

**容器与凭据清理证据**：一次性容器由保存的 ID 停止并自动移除（`--rm`），无残留容器、端口 `55468` 已释放（无监听进程）、无 T83 volume、官方镜像保留（Image ID 仍为 `sha256:697c180d…`）；随机密码文件与临时目录已删除，系统临时目录无 `steelai-t83*` 残留；未修改 Docker 代理/守护进程配置。

**遗留问题（真实存在，不得隐藏，也不得写成已解决）：**

1. `failed` 会永久阻塞同一 run 的后续事件，且没有跳过或人工解锁入口；
2. 退避为固定指数曲线，无抖动、无按 run 的公平调度；
3. 无调度器：吞吐取决于调用方调用 `dispatch_batch` 的频率；
4. 无监控、告警、指标与投递延迟观测；
5. `attempts` 达上限后需人工处置（T83 不提供改表入口，也不建议直接改表）；
6. 只在 PostgreSQL 18.6 单实例验证；未覆盖复制、PgBouncer 或托管服务下的领取语义；
7. 真实 broker 仍未接入：`EventTransport` 只有内存 Recording 实现，**不代表 Kafka**；
8. **客户端时钟偏差**：`pending` 行的初始 `available_at` 由 T82 写入侧以事件时间戳（客户端时钟）落库，而领取比较的是数据库时钟；若客户端时钟领先数据库时钟，首次领取会延迟该偏差量（本机实测约 2 ms，容器刚启动时偏差更大）。T83 不修改 T82 写入语义，因此这是已知边界；集成测试在领取前显式等待该时间戳在数据库时钟上可领取，以保证确定性；
9. 两种"状态未知"的结果（`sent_unacknowledged`、`failure_unrecorded`）只能靠**租约过期后的重新领取**收敛，收敛时间由 `lease_seconds` 决定，没有主动探测或告警。

**这些限制不造成事件丢失，也不使 fencing 失效**：所有未完成事件都仍留在 `outbox_events` 且处于 `pending`/`publishing`/`failed` 之一，任何"状态未知"的结果都会被租约恢复重新领取（`attempts` 单调递增并继续作为 fencing token，旧 worker 无法确认新租约）；`failed` 的阻塞是**刻意的顺序保护**，而不是静默丢弃。上述第 1–9 条只是把当前能力边界写清楚，本任务**不声称**已解决它们，也不得据此表述为生产可用或 exactly-once 已实现。
