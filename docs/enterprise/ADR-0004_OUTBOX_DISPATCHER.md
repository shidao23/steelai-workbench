# ADR-0004 事务型 Outbox Dispatcher、租约恢复与至少一次投递

- 状态：`accepted`
- 决策日期：2026-09-18
- 接受日期：2026-09-18
- 决策范围：Enterprise Lab 事务型 outbox 的**派发侧**（有限调用式 Dispatcher、租约与 fencing、失败重试与过期租约恢复、离线 Recording Transport）
- 相关任务：T80（Ports 与领域模型，Done）；T81（Schema 与迁移基线，Done）；T82（Outbox 写入侧与 UnitOfWork，Done）；T83（本 ADR 的引入者，Done）；T84 及以后（常驻 worker、Kafka、API、监控）
- 相关文档：`docs/enterprise/ADR-0002_POSTGRESQL_PERSISTENCE.md`、`docs/enterprise/ADR-0003_POSTGRESQL_UNIT_OF_WORK.md`、`docs/enterprise/T83_OUTBOX_DISPATCHER.md`
- 边界前置：本 ADR **不修改** T80 领域模型与既有 `EventPublisher` 契约，**不修改** T81 冻结迁移 `0001_enterprise_baseline`、Schema、约束与既有 DDL，**不新增列、不新增索引、不新增迁移**，也不修改三个 requirements 文件
- 验收结论（2026-09-18）：PostgreSQL 18.6 **真实集成验收通过**（17 项场景、0 skipped）；**第一轮契约修正完成**（派发结果拆分为五种状态并由 status 唯一推导三个属性、`failure_unrecorded` 不再报告为 delivered、`OutboxClaim`/`OutboxReclaim` DTO 契约收紧、T83 公共包出口收口）；**Codex 最终技术复核通过**；T83 由 `Review` 转为 `Done`，本 ADR 由 `proposed` 转为 `accepted`。
- 本 ADR **不构成生产可用性声明**：它只决策 outbox 派发侧在上述已界定范围内的语义；下列能力仍**不属于**本 ADR/T83——真实 broker（Kafka/RabbitMQ/Redis/Celery）、常驻 worker/调度器、监控告警指标、人工重放控制台、HTTP API、RBAC、多租户与 exactly-once。

## 1. 背景

T82 建立了 outbox 的**写入侧**：业务写入与 `outbox_events` 行在同一事务提交，行以 `pending` 落库，`delivery_status`、`attempts`、`available_at`、`published_at`、`last_error_code` 五列已在 T81 基线中冻结。T82 **没有**任何东西去消费这些行：没有 dispatcher、没有 worker、没有重试、没有租约恢复。

T83 需要在不改 Schema 的前提下补上派发闭环：**领取 → 外部发送 → 成功确认 / 失败重试 → 过期租约恢复**。本任务只使用内存 Recording Transport 与真实 PostgreSQL：不接 Kafka，不实现常驻服务。

## 2. 决策

### 2.1 独立的投递 Port，投递状态不进入领域模型

- 新增 `steelai/enterprise_lab/ports/outbox.py`：不可变 `OutboxClaim`（`DomainEvent` + `claim_attempt` + `lease_deadline`）、`OutboxDeliveryRepository`（`claim_batch` / `mark_published` / `mark_failed` / `reclaim_expired`）、`EventTransport`（`send(event, *, idempotency_key)`）。
- 投递状态是基础设施：它**不进入** `DomainEvent`，也不改变 T80 的 `EventPublisher.publish` / `next_sequence` / `replay` 契约。T83 只**读取**既有 Port 与领域对象。
- 理由：把 `attempts`、租约与错误码塞进领域事件会让"领域事件"的含义随投递实现变化，并使 T80 的冻结契约失效。
- DTO 自带契约校验：`OutboxClaim` 只接受 `delivery_status == 'publishing'` 的行、正整数 `claim_attempt` 与**带时区**的 `lease_deadline`（`pending`/`published`/`failed` 的 claim 会被拒绝）；`OutboxReclaim` 只接受 `pending`/`failed`、正整数 `attempts` 与通过安全校验的 `last_error_code`。这些对象可以**直接构造**并接受同一套校验，因此契约不依赖某个适配器的行为。
- 公共入口固定为 `steelai.enterprise_lab.ports`（投递契约与状态码）、`.application`（Dispatcher、Config、Outcome 与状态常量）、`.adapters`（内存投递适配器与 Recording Transport）、`.adapters.postgresql`（PostgreSQL 投递适配器）；顶层 `steelai.enterprise_lab` 只导出**不需要可选 PostgreSQL 依赖**的 T83 类型，导入它不会加载 SQLAlchemy/Alembic/Psycopg。

### 2.2 复用既有五列，零迁移

- 领取：`pending` → `publishing`，`attempts = attempts + 1`，`available_at = 数据库当前时间 + lease_seconds`；
- 成功：`publishing` → `published`，`published_at` 必填、使用数据库时间，`last_error_code` 清空，`attempts` 保留；
- 可重试失败：`publishing` → `pending`，`available_at` 设为指数退避后的时间；
- 终止失败：`publishing` → `failed`，不再自动领取；
- 过期租约：`publishing` 且 `available_at <= 数据库当前时间`，`attempts` 未达上限 → `pending`，已达上限 → `failed`，`last_error_code = ENT-OUTBOX-LEASE-EXPIRED`。

`pending` 的 `available_at` 表示最早可领取时间，`publishing` 的 `available_at` 表示租约截止时间：同一列承担两种语义，这是 T81 冻结 Schema 下的既定解释，本 ADR 只是把它写清楚。

### 2.3 attempts 同时是领取 fencing token

- `attempts` 在每次成功领取时**原子加 1**（`UPDATE ... SET attempts = attempts + 1 ... RETURNING`）；领取后的值即 `claim_attempt`。
- `mark_published` / `mark_failed` 只在 `delivery_status = 'publishing'` **且** `attempts = claim_attempt` 时生效；否则以 `ENT-OUTBOX-CLAIM-001` 关闭式失败。
- 因此租约过期、事件被重新领取后，旧 worker 持有的较小 `attempts` **不可能**覆盖新 worker 的结果。

### 2.3.1 投递结果必须区分"已发送但确认未知"与"未发送且失败也未记录"

一次派发调用的结果只有**五种**状态，且三个属性**只由状态推导**，调用方无法拼出互相矛盾的组合：

| status | delivered | persistence_state_known | redelivery_possible | 含义 |
| --- | --- | --- | --- | --- |
| `published` | true | true | false | 发送成功且 `published` 已提交 |
| `retry_scheduled` | false | true | true | 发送失败，已持久化 `pending` + 退避 |
| `failed_terminal` | false | true | false | 发送失败且已达上限/不可重试，已持久化 `failed` |
| `sent_unacknowledged` | true | false | true | **确实发送过**，但确认（`mark_published`）未提交，最终状态未知 |
| `failure_unrecorded` | false | false | true | **没有发送成功**，且失败状态（`mark_failed`）也未记录，最终状态未知 |

- 前四种之外的任何状态都会被 `OutboxDispatchOutcome` 拒绝（`ENT-OUTBOX-CONFIG-001`）；
- `failure_unrecorded` **绝不**报告为 delivered：事件没有被送出，把它算作已送达是错误结论；
- 两种未知状态都允许后续 worker 通过租约恢复接管（`redelivery_possible = true`），这正是它们不能被当作"完成"的原因；
- 旧的三值属性 `needs_redelivery` 已删除：它把"以后可能重发"和"已送达"混在一个布尔里，无法表达上述区别。

### 2.4 短事务领取，发送在事务之外

- 领取、确认、记失败、恢复租约各是一次**独立短事务**，提交后立即归还连接；
- `transport.send` **绝不在**数据库事务内执行；`claim` 事务在 `send` 之前完成并归还连接；
- 一个事件的一次失败不影响同批次其他事件。

### 2.5 同一 run 严格按 sequence

领取谓词要求该行是**该 run 中尚未 `published` 的最小 sequence**：

- 前序事件未 `published`（含 `pending`、退避中、`publishing`、`failed`）时，后序事件不可领取；
- 前序事件 `failed` 时，后序事件**持续阻塞**；T83 不实现跳过失败事件，也不提供人工解锁；
- 不同 run 之间互不影响，可同时处于 `publishing`，可被不同 dispatcher 并发领取。

### 2.6 数据库时间是租约的权威时间

租约截止与退避时间全部由 PostgreSQL 的 `now()` 计算，不使用任何 worker 的本机时间：多个 worker 的时钟偏差不可能造成重复领取或永不恢复的行。

### 2.7 投递错误只带安全字段

- `TransportError(error_code, retryable)` 只携带安全错误码与是否可重试，**不携带**原始异常文本、URL、host、凭据或 payload；
- 未知 transport 异常统一映射为固定安全码 `ENT-OUTBOX-TRANSPORT-001`；
- 领取已失效、`attempts` 不匹配或租约过期 → `ENT-OUTBOX-CLAIM-001`；
- 配置非法（`limit`、`lease_seconds`、`max_attempts`、退避参数、不安全的错误码）→ `ENT-OUTBOX-CONFIG-001`；
- 租约恢复写入固定码 `ENT-OUTBOX-LEASE-EXPIRED`；
- 所有数据库异常继续沿用 T82 的 SQLSTATE/约束名脱敏映射（`ENT-DB-*`）。

### 2.8 有限调用，不做常驻服务

`OutboxDispatcher` 只提供 `dispatch_batch(limit)` 与 `reclaim_expired(limit)`：一次调用做有限的工作后返回。T83 不实现 daemon、Windows 服务、定时器或长期运行进程；何时调用由调用方决定。

## 3. 后果与代价

**交付语义（必须随任何 T83 结论一起引用）：**

- T83 提供的是 **at-least-once**，**不是** exactly-once，也不声称 exactly-once；
- **transport 已发送成功但数据库确认失败时**（进程崩溃、确认事务失败、租约被其他 worker 接管），该事件在租约恢复后**会再次发送**；
- 因此**下游必须以 `event_id` 作为幂等键**去重；
- `RecordingEventTransport` 只是在内存中记录将要发送的内容，用于离线演练与测试：它**只能证明接口与流程正确**，**不能**代表 Kafka（或任何 broker）已接入。

**代价与风险：**

- 一个 run 的 `failed` 事件会永久阻塞该 run 的后续事件，直到人工处置；T83 刻意不提供跳过或解锁入口；
- 退避是固定指数曲线（基值翻倍、带上限），没有抖动，也没有按 run 的公平调度；
- 领取批量上限是单次调用的并发上限；吞吐取决于调用频率，T83 不提供调度器；
- `attempts` 达上限后进入 `failed`，需要人工把行改回 `pending`（T83 不提供该入口，也不建议在生产中直接改表）；
- 没有监控、告警、指标与人工重放控制台；没有投递延迟的观测；
- `pending` 行的初始 `available_at` 来自 T82 写入侧的事件时间戳（客户端时钟），而领取比较的是**数据库**时钟：若客户端时钟领先数据库时钟，首次领取会延迟该偏差量（实测偏差约 2 ms）。T83 不修改 T82 的写入语义，因此该偏差是已知边界而非缺陷；
- "确认失败"与"失败也未记录"两种状态都只能靠**租约过期后的重新领取**收敛，收敛时间由 `lease_seconds` 决定，没有主动探测。

## 4. 明确不属于本 ADR / T83 的范围

- Kafka、RabbitMQ、Redis、Celery 与任何真实 broker 生产/消费：**未实现**；`EventTransport` 只有内存 Recording 实现。
- 常驻 worker、daemon、Windows 服务、定时器、调度器：**未实现**。
- HTTP API、RBAC、多租户、投递查询接口与人工重放控制台：**未实现**。
- exactly-once 投递语义：**未实现，也未声称**。
- 跳过失败事件、按 run 的人工解锁、失败事件的自动降级：**未实现**。
- 监控、告警、指标、分布式追踪与结构化投递日志：**未实现**。
- 默认 SteelAI 应用接入 dispatcher 或数据库：**未接入**；`app.py`、`pages/`、Streamlit 默认入口与 T76 启动器都不导入 T83 代码。
- 修改 T80 领域模型/既有 Port 契约、T81 Schema/迁移、新增数据库列或迁移：**禁止**（本 ADR 的前置边界）。

本 ADR 与 T83 都**不得**表述为生产可用或 exactly-once 已实现；本 ADR 由 `proposed` 转为 `accepted` 只表示上述**已界定范围**内的技术决策通过验收，不代表超出该范围的任何能力已经具备。第 2 节的全部决策（at-least-once、`event_id` 幂等、事务外发送、`attempts` fencing、数据库时钟租约、同一 run 严格按 `sequence` 顺序）在验收后**保持不变**。
