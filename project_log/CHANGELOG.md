# Changelog

## 2026-09-18 · T85 acceptance

- Codex 最终复核通过：T85 由 `Review` 冻结为 `Done`（2026-09-18），**T80–T85 企业化演练阶段正式冻结**；`docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md` 状态改为 `Done` 并补入完成日期与验收结论。
- Enterprise Lab 最终定位：**可选参考实现**——不是默认 SteelAI 运行链路，也不是生产平台；默认应用仍未接入（`app.py`、`pages/`、Streamlit 默认入口与 T76 启动器都不导入它，也不连接数据库、不自动启动后台进程）。投递与执行仍是 **at-least-once**，不是 exactly-once。
- 验收结论记录：阶段能力地图、非生产边界、重新开启条件与后续路线均已完成；**ADR-0001～ADR-0005 作为本阶段历史决策冻结、不直接改写**，未来触发条件出现时应创建**新任务和新 ADR**，由新 ADR 明确取代、修订或废止既有决策；当前测试基线沿用 T84 的 **705 passed、8 skipped、358 subtests、0 failed**，本轮未重新运行。
- 本轮**只修改三个文档**：`TASKS.md`（T85 `Review` → `Done`、标题改为"已完成任务 T85"、补入验收结果与边界）、`docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`、`project_log/CHANGELOG.md`；未修改 `docs/ARCHITECTURE.md`、`docs/CURRENT_CAPABILITIES.md`、`docs/KNOWN_LIMITATIONS.md`，也未修改任何代码、测试、Schema、迁移、依赖、科研数据、方法注册表、治理配置、`app.py`/`pages/`/默认 Streamlit 入口、T80–T84 实现、既有 ADR 决策、T63/T64/T76 状态或 Git 历史。
- 本轮**未运行** pytest、Docker、PostgreSQL 或 Streamlit；**未创建 T86**；**未 commit/push/tag**。

## 2026-09-18 · T85 enterprise lab phase closeout

- T80–T84 企业化演练链路已完成并**正式冻结**：六边形边界与内存纵向流程、PostgreSQL Schema/迁移基线、PostgreSQL Repository/UoW 与事务型 outbox 写入侧、有限调用式 outbox dispatcher、有限调用式 background job worker。五个任务全部 `Done`，ADR-0001 至 ADR-0005 全部 `accepted`。
- 本轮**只做能力总结、边界与后续路线**：新增 `docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`（阶段目标与完成结论、T80–T84 能力地图、已验证内容与 705 passed 基线、明确的"不是"清单、重新开启企业化实施的五个触发条件、触发条件出现前不做的事、后续路线），并在 `TASKS.md` 增加 T85 看板行与"待复核任务 T85"（阶段能力总结、Enterprise Lab 保持可选、默认应用不导入/不连接/不自动启动、T85 不新增运行能力），在 `docs/ARCHITECTURE.md` 增加"Enterprise Lab 阶段冻结（T85）"小节并修正"T80 目前只有内存适配器"这类易被读成当前全局状态的阶段性表述（改为"T80 当时仅建立内存适配器；T81–T84 已补充可选 PostgreSQL、dispatcher 与 worker"，同时保留 T81–T84 的历史范围边界），在 `docs/CURRENT_CAPABILITIES.md` 增加"Enterprise Lab 可选实验能力"条目，在 `docs/KNOWN_LIMITATIONS.md` 增加 Enterprise Lab 限制摘要。
- Enterprise Lab 的最终定位：**可选参考实现**——不是默认 SteelAI 运行链路，也不是生产平台；默认应用不导入、不连接、不自动启动；投递与执行都是 **at-least-once**，不是 exactly-once；没有 Kafka/真实 broker、常驻服务、API/RBAC/多租户、监控告警、生产备份与高可用。
- 重新开启企业化实施的触发条件：多用户并发写入成为真实需求；任务必须跨进程长期运行；需要与外部系统投递事件；需要 HTTP API 与权限控制；需要生产部署、监控、备份或高可用。触发条件出现前：不接 Kafka、不拆微服务、不引入 Kubernetes/服务网格/Redis/Celery/RabbitMQ、不把 Enterprise Lab 接入默认 Streamlit。
- 后续路线：T76 真实桌面验收；经负责人授权后整理 Git 基线（本轮不做任何 Git 操作）；完成一轮真实 Streamlit 使用验收；每次只选择一个真实科研或用户阻塞问题实施；T63/T64 保持延期条件不变并继续 `Review`。
- 本轮**未新增**任何代码、测试、依赖、Schema、迁移或运行能力；**未启动** Kafka/API/微服务；只修改六个文档（`TASKS.md`、`docs/ARCHITECTURE.md`、`docs/CURRENT_CAPABILITIES.md`、`docs/KNOWN_LIMITATIONS.md`、`docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`、`project_log/CHANGELOG.md`），未修改 `app.py`/`pages/`/默认 Streamlit 入口、T80–T84 实现与既有 ADR 决策、requirements 文件、科研数据、方法注册表、治理配置、T63/T64/T76 状态或 Git 历史。
- T85 当时**保持 `Review`**，随后经 Codex 最终复核转为 `Done`（见上一条 acceptance 记录）；**未创建 T86**；本轮**未运行** pytest、Docker、PostgreSQL 或 Streamlit；**未 commit/push/tag**。

## 2026-09-18 · T84 acceptance

- Codex 最终技术复核通过：T84 由 `Review` 冻结为 `Done`，`docs/enterprise/ADR-0005_BACKGROUND_JOB_WORKER.md` 同步由 `proposed` 转为 `accepted`（接受日期 2026-09-18），`docs/enterprise/T84_BACKGROUND_JOB_WORKER.md` 状态改为 `Done`。
- 两轮契约修正内容：第一轮——五种 Worker Outcome 由 status 唯一推导（`handler_succeeded`/`persistence_state_known`/`reexecution_possible`），初始即区分 `success_unrecorded` 与 `failure_unrecorded`，`JobExecutionContext` 只暴露安全元数据，Registry 只支持显式注册，失败重试复用 `leased→failed→retrying` 两次合法转换，过期租约按 `attempts` 是否达上限进入 `retrying` 或 `failed`；第二轮——Handler 异常边界收紧（`JobHandlerError` 之外的**一切 `Exception`，含 `DomainError`**，统一脱敏为 `ENT-WORKER-EXECUTION-001` 并隔离，不再中断 `run_once`/`run_batch`、不再泄漏原始 `code`/`message`/`details`/URL/host/凭据/路径、任务不再残留 `leased`；`BaseException` 不吞掉；Repository 与配置错误仍照常抛出），以及 `JobOutcome` 完整不变量冻结（`succeeded`/`retry_scheduled`/`failed_terminal` 的 `state`/`attempts`/`error_code` 必须与 status 匹配，`success_unrecorded`/`failure_unrecorded` 必须 `state=None`/`attempts=None` 且携带安全错误码；任何不匹配以 `ENT-WORKER-CONFIG-001` 关闭式失败）。
- 完整测试数字：T84 离线 **72 passed + 65 subtests**；真实 PostgreSQL 18.6 集成 **25 passed + 6 subtests，0 skipped**（连续复跑稳定）；全量 `.\scripts\test.ps1` **705 passed、8 skipped、358 subtests、0 failed**；`git diff --check` exit 0；14 项冻结哈希复测 mismatches = 0。
- 交付语义与范围边界（保持不变）：T84 仅为**有限调用式执行基线**，**不是**常驻 worker 服务；只提供 **at-least-once**，**不是 exactly-once**；Handler 外部副作用**必须使用稳定 `job_id` 作为幂等键**，**enqueue 的 `idempotency_key` 不能替代 `job_id`**；无 Kafka、无真实 broker、无调度器、无监控告警、无人工重放控制台、无 HTTP API、无 RBAC、无多租户、无生产备份与高可用；默认 Streamlit 应用仍未接入 Enterprise Lab。上述限制不造成状态丢失或 fencing 失效，但不得隐藏或写成已解决。
- 本轮**仅为文档收口**：未修改代码、测试、Schema、迁移、依赖、科研数据或方法注册表，未运行 pytest、Docker、PostgreSQL 或 Streamlit，未启动 T85，未 commit/push/tag。T80-T83 保持 `Done`，ADR-0001 至 ADR-0004 保持 `accepted`，T63/T64/T76 仍为 `Review`。

## 2026-09-18 · T84 round 2 contract correction (handler exception boundary and outcome invariants)

- **Gap 1 - the handler exception boundary.** A handler raising `DomainError` used to be re-raised out of the worker, which aborted `run_once`/`run_batch`, leaked the original `code`, `message` and `details` (a fake connection string, password, host, Windows path and token in the test), and left the job stuck in `leased` with no recorded outcome. `JobWorker._run_handler` now treats **every** `Exception` other than `JobHandlerError` - `DomainError` included - as an unclassified handler failure and converts it to `JobHandlerError(ENT-WORKER-EXECUTION-001, retryable=True)`. A handler domain error therefore never escapes the worker, never interrupts the rest of the batch, never leaves a lease behind, and never exposes its text: the job is recorded as `retrying` (or terminally `failed` once the attempt budget is spent) with the fixed safe code. `BaseException` such as `KeyboardInterrupt` or `SystemExit` is **not** swallowed, so an operator signal still reaches the caller and the lease is left to expiry recovery. The fix sits at the handler execution boundary: `run_batch` has no blanket `except`, and repository claim failures and illegal configuration still propagate (both covered by tests).
- **Gap 2 - complete `JobOutcome` invariants.** An outcome could previously report a status without the persisted fields that go with it. `JobOutcome.__post_init__` now enforces a full status table: `succeeded` requires `state == 'succeeded'`, `attempts == attempt` and no error code; `retry_scheduled` requires `state == 'retrying'`, `attempts == attempt + 1` and an error code; `failed_terminal` requires `state == 'failed'`, `attempts == attempt` and an error code; both `success_unrecorded` and `failure_unrecorded` require `state is None`, `attempts is None` and an error code. Any other combination - including a boolean, negative or string `attempts` counter - fails closed with `ENT-WORKER-CONFIG-001`, so an outcome can no longer claim a persisted state it does not describe, forget the failure code of a known failure, or invent persisted fields for an unknown one. A table-driven test covers 19 contradictory combinations and a further test drives all five real worker paths to prove the invariants hold end to end.
- Added 13 offline tests (`HandlerExceptionBoundaryTests`: the leaky `DomainError` batch case, the attempt-limit terminal case, `run_once` never raising, the sanitised persisted code, `BaseException` propagation with later lease recovery, a repository claim failure still propagating, a configuration error still propagating, and the claim/handler/confirm call order; `JobOutcomeInvariantTests`: the valid shape of every status, the 19 contradictory combinations, the boolean attempt counter, an unsafe error code, and the five real output paths) and 3 real-database scenarios (a handler `DomainError` on PostgreSQL leaving only `ENT-WORKER-EXECUTION-001` with no residual lease, every real outcome matching its database row, and a real repository plus handler executing a job).
- Results after round 2: T84 offline **72 passed + 65 subtests**, T84 integration **25 passed + 6 subtests** with 0 skipped (re-run twice, stable), T80 74 passed, T81 schema 28 passed, T81 migrations 26 passed with 0 skipped, T82 offline 57 passed, T82 integration 22 passed, T83 offline 67 passed, T83 integration 17 passed, Streamlit pages 5 passed, and the full `.\scripts\test.ps1` reported **705 passed, 8 skipped, 358 subtests passed, 0 failed**; `git diff --check` exited 0. The frozen hashes of the T81 `schema.py`/`constraints.py`/`config.py`/migration/`env.py`/`alembic-enterprise.ini`, the three requirements files, the two thermal datasets, the method registry, the research-data contract and the global governance config were re-measured and are unchanged.
- Boundaries kept in round 2: exactly eight files changed - `steelai/enterprise_lab/application/job_worker.py`, `steelai/enterprise_lab/application/__init__.py`, `tests/test_t84_job_worker.py`, `tests/test_t84_job_worker_integration.py`, `docs/enterprise/T84_BACKGROUND_JOB_WORKER.md`, `docs/enterprise/ADR-0005_BACKGROUND_JOB_WORKER.md`, `TASKS.md` and `project_log/CHANGELOG.md`. The PostgreSQL schema, the Alembic migration, the frozen T81 DDL, the requirements files, the T80 `JobQueue`, the T82 repository/unit-of-work semantics, the T83 dispatcher semantics, `JobState` with its transition set, research data, the method registry and the default Streamlit application were not touched. The idempotency boundary is unchanged and restated: a handler with external side effects must use the stable `job_id` as its idempotency key, and the enqueue `idempotency_key` does **not** replace that requirement. At the time of round 2 T84 was still under review and ADR-0005 was still proposed; both moved to `Done` and `accepted` in the acceptance entry above, and no commit, push or tag was made.

## 2026-09-18 · T84 background job worker, heartbeat and expired-lease recovery baseline

- Added the background job **execution side** on top of the T82 ``background_jobs`` table and the frozen T80 job state machine: `steelai/enterprise_lab/ports/workers.py` (immutable `JobLease` and `JobExecutionState`, the `JobExecutionRepository`, `JobHandler`, `JobHandlerRegistry`, `JobExecutionContext` and `JobHandlerError` contracts, plus safe-token and safe-error-code validation), `steelai/enterprise_lab/application/job_worker.py` (the finite-call `JobWorker.run_once` / `run_batch` / `reclaim_expired`, `JobWorkerConfig`, `JobOutcome` and `OUTCOME_PROPERTIES`), `steelai/enterprise_lab/adapters/worker_memory.py` (`MemoryJobExecutionRepository` and `RecordingJobHandler`, which perform no I/O) and `steelai/enterprise_lab/adapters/postgresql/worker.py` (`PostgreSQLJobExecutionRepository`). The T80 `JobQueue` port and the T82 `PostgreSQLJobQueue` keep their `enqueue`, state-query and state-machine semantics; execution confirmation never goes through the unfenced `complete`/`fail`, and no delivery or execution state enters `BackgroundJob` or `DomainEvent`.
- Claiming runs in one short transaction: `SELECT ... FOR UPDATE SKIP LOCKED` over `state IN ('queued','retrying')` with `ORDER BY created_at, job_id LIMIT 1`, then `UPDATE ... SET state='leased', lease_id=:lease_id, updated_at=now() ... RETURNING *`. Every claim writes a brand new `lease_id` (a safe `lease_<uuid4 hex>` token that can never encode a host, path or credential), `updated_at` comes from the PostgreSQL clock, and the **first claim does not increment `attempts`** because a job is created with `attempts = 1` and that first execution is attempt 1. Only a scheduled retry or an expired-lease recovery increments it, and `attempts` never exceeds `max_attempts`.
- Fencing: `heartbeat`, `mark_succeeded` and `mark_failed` only touch a row that is still `leased` with exactly the same `job_id + lease_id + attempts` triple, and each write re-reads the row under `SELECT ... FOR UPDATE` first, so a worker whose lease expired can never extend the lease nor overwrite the newer worker's `state`, `lease_id`, `attempts`, `updated_at` or `error_code`, and a repeated confirmation of the same lease is refused with `ENT-WORKER-CLAIM-001`. The handler runs **outside any transaction** (a test asserts `pool.checkedout() == 0` while it runs) and confirmation is its own short transaction; the worker is a finite call with no daemon, timer, unbounded loop or background thread.
- Leases and recovery: `updated_at` on a `leased` row is the database time of the last successful claim or heartbeat, a heartbeat refreshes it to `now()`, and expiry is `updated_at <= now() - lease_timeout_seconds`. `lease_timeout_seconds` is process configuration with **no per-job persistence**. Recovery reuses the frozen state machine: an expired lease with attempts left goes `leased -> failed -> retrying` in one transaction (`attempts + 1`, lease cleared, fixed code `ENT-WORKER-LEASE-EXPIRED`), and one at the attempt limit goes `leased -> failed`. A retryable failure takes the same two-step path, a non-retryable failure or one that reached the limit is terminal, and no new `JobState` or second state machine was introduced. The only domain change is a backward-compatible `clear_lease=True` argument on `BackgroundJob.transition`, which explicitly clears a lease (mutually exclusive with setting one) while the default behaviour is unchanged.
- Outcomes: the five statuses `succeeded`, `retry_scheduled`, `failed_terminal`, `success_unrecorded` and `failure_unrecorded` are decided from the status alone through `OUTCOME_PROPERTIES`, so `handler_succeeded` / `persistence_state_known` / `reexecution_possible` can never contradict each other; `success_unrecorded` states plainly that the handler ran but the success state did not commit (so the job may run again after the lease expires - the explicit at-least-once side-effect risk), `failure_unrecorded` states that the handler failed and the failure was not recorded either, and neither is ever reported as a final success. Handlers receive only safe metadata (`job_id`, `job_type`, `run_id`, `attempt`, `max_attempts`, `payload_digest`, `idempotency_key` and `heartbeat()`), never a payload, path, connection or credential; `payload_digest` is a request digest, not the payload, and no payload or object store exists. The registry is explicit - no dynamic import, entry-point scan or module loading from a string - duplicates fail closed, an unregistered job type becomes a non-retryable `ENT-WORKER-HANDLER-NOT-FOUND` failure, unknown handler exceptions are persisted only as `ENT-WORKER-EXECUTION-001`, and no traceback, exception message, URL, host, credential or path can be stored.
- Added `tests/test_t84_job_worker.py` (59 offline tests and 38 subtests: the claim/execute/confirm transitions, the first claim being attempt 1, the handler running after the claim boundary closed, safe handler metadata, heartbeat and lease extension, no reclamation before expiry, recovery to `retrying` with `attempts + 1`, terminal failure at the limit, a new `lease_id` per claim, stale-lease heartbeat/success/failure rejection, atomic retry versus terminal classification, unregistered handlers, sanitised unknown exceptions, both unknown outcomes, batch isolation, registry conflicts, illegal configuration, disabled dynamic loading, the recording handler performing no filesystem, network or subprocess access, no daemon loop or timer, the default application loading neither the lab, the database packages nor the worker, the public import paths staying dependency-free, and `clear_lease` leaving existing behaviour intact) and `tests/test_t84_job_worker_integration.py` (22 real-database scenarios, 0 skipped).
- Real PostgreSQL acceptance on the pinned image `postgres:18.6-alpine3.23` (`sha256:697c180d…`, `amd64/linux`) in a one-off container `steelai-t84-postgres-test` on loopback port 55468 with `--tmpfs` and no volume, after running the T81 migration on an empty database: all 22 scenarios passed, covering a T82 `queued` job being executed, two concurrent workers never claiming the same job, two jobs executing in overlap, a second worker getting `None` immediately while the only job is leased, no pooled connection held while a handler runs, `state=succeeded` with `lease_id` and `error_code` cleared, a retryable failure atomically entering `retrying` with `attempts + 1`, a brand new `lease_id` on the next claim, terminal `failed` at `max_attempts`, heartbeat updating `updated_at` on the database clock, no reclamation inside the timeout and reclamation after it, all three stale-worker writes failing with `ENT-WORKER-CLAIM-001`, the new worker's state never being overwritten, `success_unrecorded` being recovered and re-executed, `failure_unrecorded` leaving the lease and error code untouched, an unregistered handler failing safely, no raw exception text in `error_code`, no checked-out connection after any short transaction, no `idle in transaction`, the T82 complete-versus-fail concurrency semantics still holding, and the T83 dispatcher still working on the same database.
- Results: T84 offline 59 passed, T84 integration 22 passed (0 skipped, stable across repeated runs), T80 74 passed, T81 schema 28 passed, T81 migrations 26 passed with 0 skipped, T82 offline 57 passed, T82 integration 22 passed, T83 offline 67 passed, T83 integration 17 passed, Streamlit pages 5 passed, and the full `.\scripts\test.ps1` with the safe test URL set reported 689 passed, 8 skipped, 328 subtests passed, 0 failed; `git diff --check` exited 0. The frozen hashes of the T81 `schema.py`/`constraints.py`/`config.py`/migration/`env.py`/`alembic-enterprise.ini`, the three requirements files, the two thermal datasets, the method registry, the research-data contract and the global governance config were re-measured and are unchanged.
- Boundaries kept: the T81 schema, constraints, DDL, `env.py` and `alembic-enterprise.ini`, the three requirements files, `app.py`, `pages/`, research data, the method registry and the governance configuration were not modified; no table, column, index, migration or dependency was added; no research file was read, no real model was executed and no raw experimental value was stored. The only domain change is the backward-compatible `clear_lease=True` argument described above. Added `docs/enterprise/ADR-0005_BACKGROUND_JOB_WORKER.md` (proposed) and `docs/enterprise/T84_BACKGROUND_JOB_WORKER.md` (Review), appended the T84 capability boundary to `docs/ARCHITECTURE.md`, and added T84 to `TASKS.md` as P1 `Review` with T80-T83 remaining `Done` and ADR-0001 to ADR-0004 remaining `accepted`. The container was stopped by its captured id and auto-removed, the port released, no volume or network created, the generated password destroyed, and no commit, push or tag was made; T85 was not started.
- Not implemented and not claimed: a resident worker service, Windows service, daemon, autostart, timer or scheduler; cancellation of a running job; priority, rate limiting or fairness; monitoring, alerting, metrics, tracing or a dead-letter queue; payload/object storage; real scientific computation; Kafka, Redis, Celery, RabbitMQ or FastAPI; and exactly-once execution. `lease_timeout_seconds` is process configuration with no per-job persistence, a handler that never heartbeats can be recovered and executed again, and `RecordingJobHandler` proves the interface and flow only - it is not a real scientific job.

## 2026-09-18 · T83 acceptance

- Codex 最终技术复核通过：T83 由 `Review` 冻结为 `Done`，`docs/enterprise/ADR-0004_OUTBOX_DISPATCHER.md` 同步由 `proposed` 转为 `accepted`（接受日期 2026-09-18），`docs/enterprise/T83_OUTBOX_DISPATCHER.md` 状态改为 `Done`。
- 第一轮契约修正内容：派发结果由三种（含含义混淆的 `unacknowledged`）拆分为五种——`published`、`retry_scheduled`、`failed_terminal`、`sent_unacknowledged`（确实发送过但确认未提交、最终状态未知）、`failure_unrecorded`（没有发送成功且失败状态也未记录）——并由 status 唯一推导 `delivered` / `persistence_state_known` / `redelivery_possible`，`failure_unrecorded` 不再错误报告为 delivered，含糊的 `needs_redelivery` 已删除；`OutboxClaim` 只接受 `publishing` 行 + 正整数 `claim_attempt` + 带时区 `lease_deadline`，`OutboxReclaim` 只接受 `pending`/`failed` + 正 `attempts` + 安全 `last_error_code`，两者均可直接构造并接受同一套校验；`ports` / `application` / `adapters` / `adapters.postgresql` 的公共导出收口，顶层 `enterprise_lab` 只导出不需要可选 PostgreSQL 依赖的 T83 类型，`import app` 仍不加载 `enterprise_lab`、数据库包或 dispatcher。
- 完整测试数字：T83 离线 **67 passed + 74 subtests**；真实 PostgreSQL 18.6 集成 **17 passed + 0 skipped**（连续复跑稳定）；T82 离线/集成 **57 / 22 passed**；T81 schema/migrations **28 / 26 passed**（真实集成 0 skipped）；T80 回归 **74 passed**；Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **608 passed、8 skipped、287 subtests、0 failed**；`git diff --check` exit 0；14 项冻结哈希复测 mismatches = 0。
- 交付语义与范围边界（保持不变）：T83 是**有限调用**的 outbox dispatcher，不是常驻 worker；只提供 **at-least-once**，不提供 exactly-once；事务外发送、`attempts` fencing、数据库时钟租约、同一 run 严格按 `sequence` 顺序等决策均未改变；`RecordingEventTransport` 不代表 Kafka；无真实 broker、调度器、监控、告警与人工重放控制台；`failed` 事件继续阻塞同一 run 的后序事件；下游必须使用 `event_id` 幂等。这些限制不造成事件丢失，也不使 fencing 失效，但不得被隐藏或写成已解决。
- 本轮**仅为文档收口**：未修改代码、测试、Schema、迁移、依赖、科研数据或方法注册表，未运行 Docker、PostgreSQL 或 pytest，未启动 T84，未 commit/push/tag。T82 保持 `Done`、ADR-0001/0002/0003 保持 `accepted`，T63/T64/T76 仍为 `Review`。

## 2026-09-18 · T83 transactional outbox dispatcher, lease recovery and at-least-once baseline

- Added the outbox **delivery side** on top of the T82 write side: `steelai/enterprise_lab/ports/outbox.py` (immutable `OutboxClaim` / `OutboxReclaim` / `OutboxDeliveryState`, the `OutboxDeliveryRepository` and `EventTransport` protocols, `TransportError`, the four stable error codes and the safe-error-code guard), `steelai/enterprise_lab/application/outbox_dispatcher.py` (the finite-call `OutboxDispatcher.dispatch_batch` / `reclaim_expired`, `OutboxDispatcherConfig`, `OutboxDispatchOutcome`), `steelai/enterprise_lab/adapters/outbox_memory.py` (`MemoryOutboxDeliveryRepository` plus `RecordingEventTransport`, which performs no network or filesystem I/O) and `steelai/enterprise_lab/adapters/postgresql/outbox.py` (`PostgreSQLOutboxDeliveryRepository`). Delivery state stays in the outbox table and never enters `DomainEvent`: the frozen T80 `EventPublisher` contract is unchanged.
- Reused the five existing `outbox_events` columns (`delivery_status`, `attempts`, `available_at`, `published_at`, `last_error_code`) with **no new column, no new index and no migration**: `pending` means claimable with `available_at` as the earliest claim time, `publishing` means leased with `available_at` as the lease deadline, `published` requires `published_at`, and `failed` is terminal and never claimed again. Every lease and backoff timestamp is computed by PostgreSQL `now()`, never by a worker's local clock.
- Claiming takes `SELECT ... FOR UPDATE SKIP LOCKED` (predicate: `pending`, `available_at <= now()`, `attempts < max_attempts`, and `sequence = min(non-published sequence of the run)`) and then `UPDATE ... SET delivery_status='publishing', attempts = attempts + 1, available_at = now() + make_interval(secs => lease_seconds) ... WHERE attempts = :seen_attempts RETURNING *`, all in one short transaction that commits and releases its connection **before** `transport.send` runs; acknowledgements and failure records are each their own short transaction. `attempts` is the fencing token: `mark_published` / `mark_failed` only affect a row that is still `publishing` with exactly that value, otherwise they fail closed with `ENT-OUTBOX-CLAIM-001`, so a worker whose lease expired can never overwrite the new worker's outcome.
- Failure semantics: a retryable transport failure returns the row to `pending` with exponential backoff (doubling, capped); a non-retryable failure, or one that reached `max_attempts`, moves it to terminal `failed`; an expired lease returns to `pending` while attempts remain and to `failed` once they are exhausted, always with the fixed code `ENT-OUTBOX-LEASE-EXPIRED`. Only safe fields are persisted: unknown transport exceptions map to `ENT-OUTBOX-TRANSPORT-001`, an invalid or stale claim to `ENT-OUTBOX-CLAIM-001`, illegal configuration to `ENT-OUTBOX-CONFIG-001`, and database failures keep the T82 SQLSTATE mapping. One run is strictly ordered by `sequence` (an earlier `failed` event keeps blocking its run, with no skip and no manual unlock), while different runs are claimed in parallel.
- Delivery is **at-least-once, never exactly-once**: when a send succeeds but the database acknowledgement fails, the row stays `publishing` and is sent again after the lease expires, so a downstream consumer must use `event_id` as its idempotency key. `RecordingEventTransport` only proves the interface and the flow; it is not a Kafka adapter and proves nothing about any broker. T83 adds no daemon, timer, scheduler, Kafka/RabbitMQ/Redis/Celery client, HTTP API, monitoring, alerting or replay console, and nothing is wired into the default application.
- Added `tests/test_t83_outbox_dispatcher.py` (67 offline tests and 74 subtests after the round 1 correction: the claim/publish/retry/fail transitions, the transport being called only after the claim boundary closed, `event_id` as the idempotency key, backoff and attempt limits, sanitised unknown exceptions, `attempts` fencing including stale acknowledge and stale negative-acknowledge, lease recovery at and below the attempt limit, per-run ordering and blocking, parallel claims of different runs, illegal configuration, the recording transport performing no network or filesystem access, the at-least-once recovery path after a failed acknowledge, and the architecture boundary including `import app` loading neither the dispatcher nor the database package) and `tests/test_t83_outbox_integration.py` (17 real-database scenarios, 0 skipped).
- Real PostgreSQL acceptance on the pinned image `postgres:18.6-alpine3.23` (`sha256:697c180d…`, `amd64/linux`) in a one-off container `steelai-t83-postgres-test` on loopback port 55468 with `--tmpfs` and no volume, after running the T81 migration on an empty database: all 17 scenarios passed, covering two concurrent dispatchers never claiming the same event, different runs publishing at the same time, a run offering only its smallest unpublished sequence, an empty batch returning immediately, `attempts` incrementing atomically as a fencing token, an old worker being unable to confirm the new lease, lease expiry being reclaimed and redelivered, expiry at the attempt limit becoming terminal, `published_at` and retry `available_at` coming from the database clock, no checked-out connection while the transport runs, no `idle in transaction` afterwards, T82 `pending` rows being consumed normally with `replay` still intact, a failed event blocking the rest of its run, a failed acknowledge leaving no half-applied state while the same idempotency key is redelivered, a failure that could not be recorded staying visibly undelivered, and transport failures persisting only safe codes.
- Results before the round 1 correction: T83 offline 45 passed, T83 integration 16 passed (0 skipped), T80 74 passed, T81 schema 28 passed, T81 migrations 26 passed with 0 skipped, T82 offline 57 passed, T82 integration 22 passed, Streamlit pages 5 passed, and the full `.\scripts\test.ps1` with the safe test URL set reported 585 passed, 8 skipped, 228 subtests passed, 0 failed; `git diff --check` exited 0. The frozen hashes of the T81 `schema.py`/`constraints.py`/`config.py`/migration/`env.py`/`alembic-enterprise.ini`, the three requirements files, the two thermal datasets, the method registry, the research-data contract and the global governance config were re-measured and are unchanged.
- Boundaries kept: the T80 domain models and existing ports, the T81 schema, constraints, DDL, `env.py` and `alembic-enterprise.ini`, the three requirements files, `app.py`, `pages/`, research data, the method registry and the governance configuration were not modified; no database column, index or migration was added and no dependency was installed. Added `docs/enterprise/ADR-0004_OUTBOX_DISPATCHER.md` (proposed at that time) and `docs/enterprise/T83_OUTBOX_DISPATCHER.md` (Review at that time), appended the T83 capability boundary to `docs/ARCHITECTURE.md`, and added T83 to `TASKS.md` as P1 (Review at that time) with T82 remaining `Done` and ADR-0003 remaining `accepted`. The container was stopped by its captured id and auto-removed, the port released, no volume or network created, the generated password destroyed, and no commit, push or tag was made; T84 was not started.
- **Round 1 contract correction (dispatch outcome semantics, DTO contracts and package exports):** one `unacknowledged` status used to cover two different situations and reported `delivered = True` even when nothing had been sent. The five statuses are now `published`, `retry_scheduled`, `failed_terminal`, `sent_unacknowledged` (the transport returned successfully but the acknowledge did not commit: really sent, persisted state unknown) and `failure_unrecorded` (the transport failed **and** the failure could not be persisted: not sent, persisted state unknown), and `delivered` / `persistence_state_known` / `redelivery_possible` are derived from the status alone through `OUTCOME_PROPERTIES`, so a caller can never assemble a contradictory combination; `failure_unrecorded` is never reported as delivered and the imprecise `needs_redelivery` property was removed. `OutboxClaim` now only accepts a `publishing` row with a positive `claim_attempt` and a timezone-aware `lease_deadline` (a `pending`, `published` or `failed` claim is refused), and `OutboxReclaim` only accepts `pending`/`failed` with a positive `attempts` and a safe `last_error_code`; both objects can be constructed directly and are validated by the same rules. The public entry points were completed and their stale "not yet implemented" docstrings corrected: `ports` exports the delivery contracts, status constants and error codes, `application` the dispatcher, its config, its outcomes and the status constants, `adapters` the in-memory delivery repository and the recording transport, `adapters.postgresql` the PostgreSQL delivery repository, and the top-level `enterprise_lab` exports only the T83 types that need no optional PostgreSQL dependency - importing it still loads no SQLAlchemy, Alembic or Psycopg, and `import app` still loads neither the lab, the database packages nor the dispatcher.
- Results after the round 1 correction: T83 offline **67 passed + 74 subtests**, T83 integration **17 passed** with 0 skipped (re-run three times, stable), T80 74 passed, T81 schema 28 passed, T81 migrations 26 passed with 0 skipped, T82 offline 57 passed, T82 integration 22 passed, Streamlit pages 5 passed, and the full `.\scripts\test.ps1` reported **608 passed, 8 skipped, 287 subtests passed, 0 failed**; `git diff --check` exited 0 and the 14 frozen hashes were re-measured unchanged. The integration suite also waits explicitly until the write-side `available_at` stamp is claimable on the database clock, which documents the known cross-clock boundary (the T82 write side stamps `available_at` from the client clock while the claim compares with the database clock; the measured offset here is about 2 ms) without weakening the claim contract.
- Boundaries kept after the round 1 correction: the T80 domain models and existing ports, the T81 schema, constraints, DDL, `env.py` and `alembic-enterprise.ini`, the three requirements files, `app.py`, `pages/`, research data, the method registry and the governance configuration were not modified; no database column, index or migration was added and no dependency was installed. At that point T83 was still under review and ADR-0004 was still proposed; both moved to `Done` and `accepted` in the acceptance entry above, while T82 remains `Done` and ADR-0003 remains `accepted`. The container was stopped by its captured id and auto-removed, the port released, no volume or network created, the generated password destroyed, and no commit, push or tag was made; T84 was not started.

## 2026-09-18 · T82 acceptance

- Codex 最终复核通过：T82 由 `Review` 冻结为 `Done`，`docs/enterprise/ADR-0003_POSTGRESQL_UNIT_OF_WORK.md` 同步由 `proposed` 转为 `accepted`（接受日期 2026-09-18），`docs/enterprise/T82_POSTGRESQL_REPOSITORIES.md` 状态改为 `Done`。
- 两轮契约修正解决的核心问题：第一轮——审计 `count()+1` → `append` 与 per-run `next_sequence()` → `publish` 在重叠事务中**都成功**（序号 1、2，正常并发写入不再关闭式失败、不需要调用者重试），任务租约不再使用 advisory lock 而只依赖 `SELECT ... FOR UPDATE SKIP LOCKED`（两个重叠事务租到不同任务，仅一个可用时第二个立即得到 `None`），`complete`/`fail`/`retry`/`cancel` 先 `SELECT ... FOR UPDATE` 锁行再转换（`retry` 的 attempts 上限在锁内判断），UoW 失败生命周期关闭式处理，`idempotency_key` 参数与 run 自身键一致性前置校验，同 `artifact_id` 只在全部持久化字段一致时才复用；第二轮——显式 `rollback()` 失败与"正常离开未提交的 `with` 时自动 rollback 失败"都必须抛脱敏 `ENT-DB-001` 而非静默成功（只有 `with` 内已有异常时才保留原异常），advisory lock 语句失败经同一 SQLSTATE 映射脱敏，所有仓储调用先校验 UoW 生命周期再校验参数（PostgreSQL 与 Memory 一致）。
- 完整测试数字：T82 离线 **57 passed + 38 subtests**；真实 PostgreSQL 18.6 集成 **22 passed + 6 subtests**；T81 migrations **26 passed + 0 skipped**；T81 schema **28 passed**；T80 回归 **74 passed**；Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **524 passed、8 skipped、213 subtests、0 failed**；`git diff --check` exit 0。
- 本轮**仅为文档收口**：未修改代码、测试、Schema、迁移、依赖、科研数据与方法注册表，未运行 Docker/PostgreSQL/pytest，未启动 T83，未 commit/push/tag。范围边界保持不变：T82 完成的是可选 PostgreSQL Repository、UnitOfWork、事务型 outbox 写入侧和数据库任务队列基础，**不代表**已经实现事件投递、Kafka、worker 服务、心跳与租约回收、HTTP API、RBAC、多租户、生产备份、高可用或 exactly-once；`outbox_events` 仍只有写入侧，默认应用仍未接入数据库。

## 2026-09-17 · T82 PostgreSQL repositories, unit of work and transactional outbox write side

- Added the optional PostgreSQL persistence adapter under `steelai/enterprise_lab/adapters/postgresql/`: `_context.py` (one connection, one transaction, advisory-lock entry point), `_locks.py` (stable SHA-256 derived lock keys with a SteelAI/T82 namespace and only the two sequence scopes - the job-lease scope was removed), `errors.py` (SQLSTATE and constraint-name mapping), `hydration.py` (row to domain-object reconstruction) and `repositories.py` (the five repositories plus `PostgreSQLUnitOfWork` and `PostgreSQLUnitOfWorkFactory`, which exposes a single transaction-creation semantic plus a sanitised `describe()`). `EnterpriseWorkflowService` can now run on PostgreSQL by swapping the injected factory, with no service logic change; only its `UnitOfWorkFactory` docstring was updated from "T81 replaces" to "T82 replaces". Documentation was corrected so it no longer claims a job-lease advisory lock, no longer says ordinary concurrent audit/outbox writers must retry, and describes the lock namespace only as lowering the chance of an accidental collision.
- Transaction boundary: one unit of work owns one connection and one transaction shared by all five repositories, a commit applies every write atomically, an exception leaving the block always rolls back, and any repository handle kept past the boundary fails closed with `ENT-UOW-001`. `committed` is that unit of work's own permanent outcome flag. The failure lifecycle is explicit and never silently successful: `commit()`/`rollback()` before the boundary starts returns `ENT-UOW-001`; a `begin()` failure closes the checked-out connection immediately; a failed `commit()` immediately attempts a rollback, closes the connection, marks the boundary closed and raises only a sanitised `ENT-DB-001`; an explicit `rollback()` that the driver refuses leaves `rolled_back == False`, still closes the connection and the boundary, and raises the sanitised `ENT-DB-001`; a clean exit from an uncommitted `with` whose automatic rollback fails likewise raises the sanitised `ENT-DB-001` instead of returning quietly; and a rollback failure never masks an exception that is already propagating, while the connection is closed in every one of those paths.
- Every repository call validates the unit-of-work lifecycle **before** its arguments: a saved handle from a closed boundary reports `ENT-UOW-001` even when the arguments are also invalid, in the PostgreSQL adapter and the memory adapter alike (the five PostgreSQL repositories already started with the connection check; `create_run` and its memory counterpart were reordered). Identity is then checked before any SQL: `create_run` refuses an `idempotency_key` argument that disagrees with the run's own key with `ENT-IDEMPOTENCY-001` without issuing a single statement. An artifact `artifact_id` that repeats with any different persisted field (path, digest, type, version, run id or creation time) is refused with `ENT-ARTIFACT-001` instead of being reported as a reuse, in both adapters, with tests that construct the conflicting object directly rather than relying on the derived content identity.
- Idempotency is decided in the database with `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` rather than "select then insert": psycopg reports `rowcount == -1` for that statement shape, so the presence of a returned row decides whether the insert happened, and a conflicting binding is refused with `ENT-IDEMPOTENCY-001` before any artifact, audit, outbox or job side effect. Optimistic concurrency uses `UPDATE ... WHERE run_id = ? AND revision = ? RETURNING`, so no update can be lost.
- Concurrency primitives, corrected so normal concurrent writes do not fail: `count()` and `append()` take the same transaction-level `pg_advisory_xact_lock` before reading the current maximum, and `next_sequence()` and `publish()` do the same per run, so two overlapping transactions that each compute `count() + 1` and append, or each call `next_sequence()` and publish, **both succeed** with sequences 1 and 2 and no caller has to retry; directly supplying a stale or out-of-order sequence still fails closed with `ENT-AUDIT-001` / `ENT-EVENT-001`. The key is derived from a SHA-256 digest (never Python `hash()`) inside a SteelAI/T82 namespace that only lowers the chance of an accidental collision with another application, and the only two scopes are the audit sequence and the per-run outbox sequence. Job leasing takes **no** advisory lock: it relies on `SELECT ... FOR UPDATE SKIP LOCKED`, so two overlapping transactions lease two different jobs and, when only one job is available, the second transaction gets `None` immediately instead of waiting. `complete`/`fail`/`retry`/`cancel` lock the target row with `SELECT ... FOR UPDATE` first and then apply the frozen `BackgroundJob.transition` to the state read inside that lock (the retry attempt budget is evaluated there too, with no duplicate pre-check outside the lock), so a concurrent `complete` and `fail` on the same leased job leave exactly one winner and the loser fails closed with `ENT-JOB-001` after reading the latest state. No second state machine was written.
- Database failures are classified from SQLSTATE and the constraint name only, mapped onto the existing `ENT-*` codes, with a stable sanitised adapter error for anything unclassified; exceptions carry only `sqlstate`, `constraint` and `error_type`, never SQL text, parameters or a connection string. The advisory-lock statement is covered by the same mapping: a failing `pg_advisory_xact_lock` is re-raised as a sanitised `ENT-DB-*` with its structured SQLSTATE preserved, so driver text, statement, parameters and any connection string stay out of the error, and the unused `safe_lock_key()` helper was deleted.
- Added `tests/test_t82_postgresql_repositories.py` (57 offline tests: error classification, hydration round-trips through the frozen validators, stable namespaced lock keys with only the two sequence scopes, unit-of-work handle lifetime, the connect/begin/commit/rollback failure lifecycle driven through engine, connection and transaction doubles - including a **new** explicit-`rollback()`-failure test and a **new** clean-exit-automatic-rollback-failure test, both asserting a sanitised `ENT-DB-001`, a closed connection and dead handles, while the pre-existing propagating-exception test covers the "original error is preserved" case and now also asserts the saved handle is dead - the advisory-lock failure mapping, the lifecycle-before-argument ordering on both adapters, the idempotency-identity check that runs no SQL at all, and directly constructed artifact conflicts for both adapters) and `tests/test_t82_postgresql_integration.py` (22 real-database scenarios including the concurrency ones, using a bounded thread pool with a `Barrier` and join timeout so a deadlock fails rather than hangs; barriers are only set before the concurrent section, never while one side already holds a lock, because that would deadlock the test itself).
- Real PostgreSQL acceptance on the pinned image `postgres:18.6-alpine3.23` (`sha256:697c180d…`, `amd64/linux`) in a one-off container `steelai-t82-postgres-test` on loopback port 55468 with `--tmpfs` and no volume, after running the T81 migration on an empty database: all 22 scenarios passed (and the suite was re-run three more times to confirm stability), covering the full vertical flow, single-commit visibility of run/artifact/audit/outbox, rollback after injected failures at four write stages, uncommitted invisibility to a second connection, identical replay adding no rows, concurrent conflicting idempotency keys, an identity mismatch writing nothing, a directly constructed artifact conflict, concurrent state updates, four overlapping audit writers all succeeding with unique sequences 1-4, two overlapping audit writers both succeeding with 1 and 2, stale and gapped sequences failing closed with no write, two overlapping outbox writers both succeeding with 1 and 2, sequential outbox appends staying contiguous, two overlapping lease transactions holding two different jobs behind a barrier, a single available job making the second transaction receive `None` before the first commits, a concurrent `complete` and `fail` leaving exactly one winner, the retry attempt budget being enforced on the locked row, dead handles after commit and rollback, the append-only trigger still rejecting UPDATE/DELETE with `23001`, domain objects rather than rows, and pool hygiene with no `idle in transaction`.
- Results: T82 offline 57 passed, T82 integration 22 passed (re-run three more times, stable), T81 schema 28 passed, T81 migrations 26 passed with 0 skipped (integration executed for real), T80 74 passed, Streamlit pages 5 passed, and the full `.\scripts\test.ps1` with the safe test URL set reported 524 passed, 8 skipped, 213 subtests passed, 0 failed; `git diff --check` exited 0. The frozen hashes of the T81 `schema.py`/`constraints.py`/`config.py`/migration/`env.py`/`alembic-enterprise.ini`, the three requirements files, the two thermal datasets, the method registry, the research-data contract and the global governance config were re-measured and are unchanged.
- Boundaries kept: T80 domain and ports, T81 `schema.py`/`constraints.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`, the three requirements files, `app.py`, `pages/`, research data, the method registry, the governance state machine, the memory adapter semantics and T76 were not modified; `import app` still loads no SQLAlchemy, Psycopg, Alembic or adapter module. Added `docs/enterprise/ADR-0003_POSTGRESQL_UNIT_OF_WORK.md` (proposed) and `docs/enterprise/T82_POSTGRESQL_REPOSITORIES.md`, appended the real T82 capability boundary to `docs/ARCHITECTURE.md`, and added T82 to `TASKS.md` as P1 `Review`.
- Explicitly not implemented and not claimed: outbox dispatcher, Kafka, worker service, heartbeat and lease reaping, HTTP API, RBAC, multi-tenancy, production backup and high availability. The default application remains database-free. The container was stopped by its captured id and auto-removed, the port released, no volume or network created, the generated password destroyed, and no commit, push or tag was made.

## 2026-09-17 · T81 acceptance

- Codex final review passed, `docs/enterprise/ADR-0002_POSTGRESQL_PERSISTENCE.md` moved from `proposed` to `accepted`, and T81 moved from `Review` to `Done` in `TASKS.md`; the T81 section is now titled as a completed task and its pending-review wording is replaced by an acceptance result.
- Accepted evidence: the acceptance ran against PostgreSQL 18.6 on Alpine amd64 in a single throwaway container; `alembic upgrade head -> downgrade base -> upgrade head` all succeeded with `current`/`heads` consistent; 35 named constraints (21 CHECK, 5 PK, 5 FK, 4 UNIQUE), 8 business indexes, and the audit trigger/function were verified present; SQLSTATE `23514`, `23505` and `23001` were verified against the live server; `tests/test_t81_postgresql_migrations.py` 26 passed with 0 skipped and 28 subtests, `tests/test_t81_postgresql_schema.py` 28 passed, the T80 regression 74 passed, the full `.\scripts\test.ps1` 445 passed / 8 skipped / 169 subtests / 0 failed, and `git diff --check` exited 0.
- Scope is recorded explicitly so it cannot be overstated: T81 delivered the PostgreSQL schema, the frozen Alembic migration baseline, the explicit connection-configuration boundary and the domain-to-table mapping contract. It is **not** a complete PostgreSQL Repository/UnitOfWork adapter - those implementations, outbox writes in the same transaction as business writes, a dispatcher, a worker, Kafka and an API remain out of scope for T82 and later.
- Also recorded: no PostgreSQL was installed on the Windows host; the real acceptance used the project owner's already-running Docker Desktop and a one-off PostgreSQL container, Docker/PostgreSQL stay out of SteelAI's default dependencies, the container was deleted and the official image was retained as authorised.
- Documentation-only closure: no code, test, schema, migration, DDL, dependency, research data or method registry was modified in this round, and T82 was not started. No commit, push or tag was made.

## 2026-09-17 · T81 real PostgreSQL acceptance

- Ran the T81 acceptance against a real PostgreSQL server, as authorised: the official pinned image `postgres:18.6-alpine3.23` (`amd64/linux`, Image ID = RepoDigest = `sha256:697c180d…`, matching the Docker Hub official manifest index digest) served `PostgreSQL 18.6 on x86_64-pc-linux-musl`.
- Container boundary: one throwaway container `steelai-t81-postgres-test` with labels `com.steelai.task=T81` and `com.steelai.purpose=integration-test`, `--rm`, `--tmpfs /var/lib/postgresql`, no named volume and a loopback-only port binding. Because `127.0.0.1:55432` falls inside a Windows-reserved range (`55368-55467`) and could not be bound, the run used `127.0.0.1:55468 -> 5432`; the deviation is recorded in the T81 documents.
- Migration acceptance: `upgrade head` reached `0001_enterprise_baseline (head)` (`current` and `heads` agreed), `downgrade base` removed every business table, index, trigger and function while keeping the database and leaving the schema empty with no `CASCADE`, and a second `upgrade head` succeeded with `current`/`head` still consistent.
- Catalog evidence on the live server: 35 named constraints (21 CHECK, 5 PK, 5 FK, 4 UNIQUE, empty missing list), 8 business indexes, and the `trg_audit_events_append_only` trigger plus `fn_audit_events_reject_mutation` function all present.
- Direct SQLSTATE probes on the live server: audit UPDATE and DELETE returned `23001`; a duplicate idempotency key returned `23505` on `uq_workflow_runs_idempotency_key`; an invalid request digest, an unregistered state, `revision = 0`, an invalid content digest, an unregistered evidence class and the five unsafe relative paths (`.`, `..`, `./a`, `a/../b`, `a//b`) each returned `23514` on the expected constraint; a valid relative path was accepted.
- Test results: `tests/test_t81_postgresql_migrations.py` 26 passed with 0 skipped and 28 subtests passed (the six previously skipped integration tests all executed for real); without a test URL it remains 20 passed + 6 skipped. `tests/test_t81_postgresql_schema.py` 28 passed, `tests/test_t80_enterprise_architecture.py` 74 passed, and `.\scripts\test.ps1` reported 445 passed, 8 skipped, 169 subtests passed, 0 failed.
- One defect surfaced and was fixed in test code only: `test_base_to_head_creates_every_declared_object` evaluated `set(...) | {...}.issubset(...)`, unioning a set with a bool and raising `TypeError` instead of asserting. It now builds the expected set first and then asserts `issubset`. No schema, migration, DDL, dependency or configuration file was changed, and the full acceptance was re-run from an empty test database afterwards.
- Cleanup: the container was stopped by its captured id and auto-removed, the port released, and no volume or network was created or pruned. The generated password, database URL and temporary credential files were destroyed; the Docker Desktop proxy settings and `~/.docker/daemon.json` touched while diagnosing the image pull were restored to their original contents, and the pulled image is intentionally retained. T81 stays in `Review` pending Codex review; no commit, push or tag was made.

## 2026-09-17 · T81 offline test contract cleanup

- Removed every comparison between the frozen revision's values and the current live contract constants from `test_frozen_revision_matches_the_t81_baseline_contract`. The test now asserts only explicit T81 baseline literals, so a historical revision is no longer pinned to whatever the live modules say today.
- Deleted the now-unused `_live_definition` helper and the live-constant imports it needed.
- Corrected the stale header note in `migrations/enterprise/versions/0001_enterprise_baseline.py`: it now states that the revision depends on no SteelAI runtime module at all, instead of claiming that it still reads SQL text from `constraints.py`.
- Fixed the isolation probe so it cannot pass vacuously: it captures `baseline_snapshot = _snapshot_frozen_ddl()` before mutating the live module, captures `mutated_snapshot` while the module is mutated, and asserts the two are equal. The previous `_snapshot_frozen_ddl() == _snapshot_frozen_ddl()` self-comparison is gone; the restore check now compares against the saved baseline snapshot.
- No schema, migration DDL, dependency, research data, Port, default application or T76 change: the generated offline SQL hash, `schema.py` and `constraints.py` are untouched by this round.
- Verification: `test_t81_postgresql_schema.py` 28 passed, `test_t81_postgresql_migrations.py` 20 passed with the same 6 integration tests skipped, `test_t80_enterprise_architecture.py` 74 passed, `.\scripts\test.ps1` 439 passed / 14 skipped / 0 failed, `git diff --check` clean. T81 stays in `Review`.

## 2026-09-17 · T81 migration freeze completed

- Made the baseline revision genuinely independent: `migrations/enterprise/versions/0001_enterprise_baseline.py` no longer imports anything from `steelai.*`. It now imports only `__future__`, `alembic`, `sqlalchemy` and `sqlalchemy.dialects.postgresql`, so editing `constraints.py`, `schema.py` or `domain.models` can no longer change the DDL this historical revision emits.
- Froze every contract value inside the revision: the naming convention, all CHECK constraint names, the SHA-256 and content-digest regular expressions, the T81 baseline literals for `GovernanceState`, `ResultLevel`, `EvidenceClass` and `JobState`, the delivery statuses, the relative-path CHECK SQL, and the audit trigger/function names and SQL. A T81 baseline change now requires a new revision.
- The live side is unchanged in its role: `schema.py` still consumes `constraints.py` for T82 and the tests, and no runtime code depends on the migration.
- Replaced `test_frozen_revision_matches_the_live_schema`, which wrongly asserted permanent equality between the historical revision and a future live schema, with a frozen-baseline contract test that compares the revision's own frozen literals against the declared T81 baseline values.
- Removed the assertion that the revision equals the current `relative_path_check_sql()` output and replaced it with a literal assertion of the frozen T81 relative-path semantics, including the bare `.` and `..` rejection and coverage of `.`, `..`, `./a`, `a/../b` and `a//b`.
- Added AST tests proving no `versions/*.py` file imports `steelai` (including the live `schema`, `constraints` and `domain` modules), touches runtime `Metadata`/`Table` objects, or calls the shared SQL builder functions; added per-table column counts, primary key and exact CHECK-name inventories.
- Added an isolation probe that monkeypatches the live `constraints` module (regular expressions, constraint names, naming convention and every SQL builder) and reloads the revision in a fresh interpreter, asserting the generated columns, constraints and SQL are byte-identical; the patched module is restored and reloaded afterwards.
- Retained the revision-length, offline SQL ordering, bare-dot path and downgrade-safety tests, and re-ran them together with the full suite.
- Verification: `test_t81_postgresql_schema.py` 28 passed, `test_t81_postgresql_migrations.py` 20 passed with the same 6 integration tests skipped (no safe test database, so the real PostgreSQL migration remains unverified and T81 stays in `Review`). No dependency version, research data, Port, default application or T76 file was modified.

## 2026-09-17 · T81 contract corrections

- Shortened the Alembic revision id from `0001_enterprise_metadata_baseline` (33 characters) to `0001_enterprise_baseline` (24 characters) so it fits the version table's `version_num VARCHAR(32)` column, renamed the revision file and updated the tests and documents. New assertions compare the revision length against the width parsed from the generated `version_num VARCHAR(n)` DDL.
- Fixed the offline SQL order: in `--sql` mode Alembic emitted `CREATE TABLE ...alembic_version_enterprise` before the revision ran, so the generated script could not execute on a fresh database. `env.py`'s offline branch now emits `CREATE SCHEMA IF NOT EXISTS` first, and the test compares the byte positions of both statements instead of only checking that both exist.
- Froze the baseline revision: `0001_enterprise_baseline` no longer imports `schema.metadata`, the dynamic `_table_definition` reader is gone, and all five tables' columns, primary keys, foreign keys, unique constraints and CHECK constraints are declared explicitly inside the revision. It reuses only the new `adapters/postgresql/constraints.py`, which holds plain constants and SQL-text builders and no SQLAlchemy objects.
- Added `steelai/enterprise_lab/adapters/postgresql/constraints.py` as the shared, SQLAlchemy-free contract module consumed by both the live metadata and the frozen revision, with regression tests proving a historical revision imports no runtime `Table`/`MetaData` and that the frozen definition matches the live schema column by column and constraint by constraint.
- Hardened the `relative_path` CHECK with an explicit `relative_path NOT IN ('.', '..')`, so bare `.` and `..` are rejected in addition to path components. Tests now cover `.`, `..`, `./a`, `a/../b` and `a//b` in the metadata, the frozen revision and the offline SQL.
- Corrected the real-PostgreSQL rejection test so every invalid variant uses its own `run_id` and `idempotency_key`, which removes the possibility that a duplicate-key error explains a failure, and each case now asserts the expected SQLSTATE (`23514` check violation, `23505` unique violation, `23001` append-only trigger).
- Also fixed two latent defects found while correcting the above: the frozen revision passed already-prefixed CHECK names to `op.create_table`, which applied the naming convention a second time and produced truncated names such as `ck_artifact_references_ck_artifact_references_relative__c6a2`; and the live metadata double-prefixed the relative-path CHECK name. Both now match the documented stable names exactly.
- Verification: `test_t81_postgresql_schema.py` 28 passed, `test_t81_postgresql_migrations.py` 18 passed with 6 integration tests skipped (no safe test database, so the real PostgreSQL migration remains unverified and T81 stays in `Review`). No research data, default application, T76, dependency version or Port was modified.

## 2026-09-17 · T81 PostgreSQL persistence baseline

- Authorised optional dependencies added as `requirements-enterprise.txt` with exact stable pins: SQLAlchemy 2.0.54, alembic 1.20.0 and psycopg[binary] 3.3.5 (transitive Mako 1.4.1, greenlet 3.5.6). `requirements.txt` and `requirements-dev.txt` are unchanged and the Enterprise Lab stays installable without any of them.
- Added the optional `steelai/enterprise_lab/adapters/postgresql` boundary: `config.py` (explicit configuration, fail-closed `ENT-DB-CONFIG-001..004`, `redact_database_url`, Psycopg 3 engine factory with `pool_pre_ping`, no connection at import), `schema.py` (SQLAlchemy Core metadata, deterministic naming convention) and `mapping.py` (domain-to-table mapping contract plus pure row builders).
- Defined the dedicated `steelai_enterprise` schema with five business-metadata tables: `workflow_runs`, `artifact_references`, `audit_events`, `outbox_events` and `background_jobs`. States stay string columns with named CHECK constraints reusing the T50/T51 `GovernanceState` and T80 `JobState` vocabularies; no PostgreSQL native enum, no `projects` table and no seeded data.
- Added the hand-written, reviewed baseline migration `0001_enterprise_metadata_baseline` plus `alembic-enterprise.ini` and `migrations/enterprise/env.py`. Offline `upgrade head --sql` and `downgrade 0001:base --sql` both generate verified SQL; downgrade drops the audit trigger, the function and the five tables in reverse dependency order with no `CASCADE`, no `DROP DATABASE` and no schema drop.
- Enforced append-only audit in the database with `steelai_enterprise.fn_audit_events_reject_mutation()` and `trg_audit_events_append_only`, which reject UPDATE and DELETE with `restrict_violation`.
- Added `tests/test_t81_postgresql_schema.py` (27 tests) and `tests/test_t81_postgresql_migrations.py` (13 tests + 6 integration skips): table/schema/naming coverage, key CHECK semantics, mapping completeness, URL redaction with special-character passwords, fail-closed configuration, offline SQL generation, destructive-statement checks, `import app` isolation and unchanged research-directory hashes.
- Real PostgreSQL migration execution is **not** verified: no safe test database is available and the task forbids installing PostgreSQL or Docker, so all six integration tests skip unless `STEELAI_TEST_DATABASE_URL` names a database containing both `steelai` and `test`. T81 therefore stays in `Review` and the schema is not claimed to be an implemented persistence adapter.
- Narrowed one assertion in the frozen T80 suite with explicit owner approval: `test_runtime_surface_does_not_depend_on_forbidden_packages` now scans the inner layers plus `adapters/memory.py`, its original intent, instead of the whole package tree, which could not coexist with an optional PostgreSQL adapter. The test count stays 74, no inner-layer constraint was relaxed, and T81's own suite enforces the inner-layer and default-application isolation separately.
- Added `docs/enterprise/ADR-0002_POSTGRESQL_PERSISTENCE.md` (status `proposed`) and `docs/enterprise/T81_POSTGRESQL_PERSISTENCE_BASELINE.md`, appended the real PostgreSQL capability boundary to `docs/ARCHITECTURE.md` and added T81 to `TASKS.md` as P1 `Review`. No Repository, UnitOfWork, dispatcher, worker, Kafka, API, page or database switch was implemented.

## 2026-09-17 · T80 acceptance

- Codex final review passed and the project owner accepted ADR-0001, so T80 moved from `Review` to `Done` after three contract correction rounds (transaction boundary, request and job idempotency, mandatory `request_digest` plus the read-session and `committed` clean-up).
- Accepted evidence: `tests/test_t80_enterprise_architecture.py` 74 passed with 71 subtests passed; `.\scripts\test.ps1` 391 passed, 8 skipped, 0 failed.
- Documentation-only closure: no Python code, test, dependency, research data, method registry or other task status changed, and no PostgreSQL, Kafka or worker work was started.

## 2026-09-17 · T80 final contract tightening

- Made `WorkflowRun.request_digest` mandatory: removed the empty-string default and the "validate only when non-empty" branch, so a run can no longer exist without a bound request digest; `WorkflowRun.create` now requires the argument explicitly and `validate_digest` rejects empty, wrong-length, non-hexadecimal and uppercase digests with `ENT-REDACTION-001`.
- Added `RunRepository.get_run_by_idempotency_key` as the only idempotency lookup and removed the `read_only()` factory method and its `Any`-returning read session: the vertical flow now decides idempotency inside one explicit `UnitOfWork`, before any artifact, audit record or domain event, replays by reading then rolling back, and `read_run`/`list_runs` read inside a unit of work and roll it back.
- Made `MemoryUnitOfWork.committed` a per-unit result flag that is permanently `True` after its own commit and `False` after its rollback, so a later unit of work's commit can no longer rewrite an earlier one's reported outcome; removed the unused `_committed_snapshot` field.
- Extended `tests/test_t80_enterprise_architecture.py` to 74 tests (71 subtests): mandatory-digest rejection, explicit-argument requirement, digest preservation across a state change, repository-level digest acceptance, and a two-consecutive-commit regression test for the `committed` flag.
- Updated `docs/enterprise/T80_ENTERPRISE_ARCHITECTURE_FOUNDATION.md`, `docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md`, `docs/ARCHITECTURE.md` and `TASKS.md` so the interface description matches the tightened contract. T80 stays in `Review`; no dependency, research data, PostgreSQL or Kafka work was started.

## 2026-09-17 · T80 contract correction round after Codex review

- Reworked `MemoryUnitOfWork` so `MemoryStore.state` is **only** the committed state: a unit of work mutates a private working copy, `commit` replaces the committed state in one atomic assignment, and `rollback` merely discards the working copy.
- Bound every adapter repository to one unit of work through a weak reference: a handle captured before `commit` or `rollback` now fails closed with `ENT-UOW-001` on every read and write instead of touching a stale working copy.
- Added the single-writer guard: T80 refuses a second overlapping unit of work on the same store with `ENT-UOW-001` instead of letting it observe uncommitted data; the guard is a weak reference, so a finished or abandoned unit of work never locks the store, and read paths use an explicit read-only session.
- Bound workflow-run idempotency to a stable `WorkflowRunRequest.request_digest` covering project, task, module version, result level, evidence class, next action, creator, artifacts, audit entries and the event note, with no runtime timestamp; `WorkflowRun` now stores that digest.
- Made the replay probe and `RunRepository.create_run` compare the request digest and the run id, so the same idempotency key with different content, or the same content under a different explicit run id, returns `ENT-IDEMPOTENCY-001` before any artifact, audit record or domain event is written.
- Replaced the background-job idempotency check with an explicit index binding one `idempotency_key` to one `job_id` and one `BackgroundJob.request_digest`: the same key with a different job id or payload, and the same job id with a different key, are now refused.
- Rewrote the regression suite to `tests/test_t80_enterprise_architecture.py` (69 tests): committed state unchanged while a unit of work is writing, overlap refusal, saved repository handles unusable after commit and after rollback, visibility of the committed result to the next unit of work, per-field idempotency conflicts with no side effects, and the job idempotency index. Corrected the older test that only checked the final post-rollback state.
- Updated `docs/enterprise/T80_ENTERPRISE_ARCHITECTURE_FOUNDATION.md` and `docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md` so the wording matches the corrected design (committed-state visibility, single-writer guard, request digest, job idempotency index) instead of the earlier "not visible before commit" phrasing.
- T80 stays in `Review` for re-review; no PostgreSQL, Kafka, worker or API implementation was started, no dependency, research data or method registry changed.

## 2026-09-17 · T80 enterprise architecture boundary and replaceable interface skeleton

- Added the optional `steelai.enterprise_lab` package with a hexagonal layout: `domain` objects, an `application` vertical flow, `ports` as `typing.Protocol` interfaces and one pure Python `adapters.memory` implementation.
- Added the six required domain objects (`EnterpriseProject`, `WorkflowRun`, `ArtifactReference`, `AuditEvent`, `DomainEvent`, `BackgroundJob`) with stable IDs, revisions, states, creation times and content digests; run states reuse the frozen T50 `GovernanceState` vocabulary instead of a second scientific state machine.
- Added the six required ports (`RunRepository`, `AuditRepository`, `ArtifactStore`, `EventPublisher`, `JobQueue`, `UnitOfWork`) with idempotent creation, `expected_revision` optimistic concurrency, append-only audit, reference-only artifact registration, ordered event replay, a checked background-job state machine and an explicit commit/rollback boundary.
- Added one minimal vertical flow (create run → register artifact metadata → append audit → publish domain event → commit) using public synthetic metadata only; it reads no research file and opens neither the repository tree nor the system temporary directory.
- Enforced redaction in the type system: descriptive fields reject digits, absolute and UNC paths, URL schemes and credential patterns, artifact references accept a safe relative POSIX path plus a lowercase SHA-256 only, and domain-event payloads accept only ID, state, version, hash and summary fields. `model_output` cannot be registered as `accepted_evidence`.
- Added `tests/test_t80_enterprise_architecture.py` (53 tests): import isolation without any enterprise dependency, proof that `app.py` and `steelai/**` never import the lab, AST checks of the hexagon dependency direction, the in-memory adapter contracts (idempotency reuse, idempotency conflict, optimistic concurrency, illegal job transitions, path and hash safety, append-only audit, ordered replay, rollback without partial writes), and redaction assertions.
  (Superseded by the correction round above: that first suite did not check the in-progress working state, the repository handle lifetime, overlapping units of work or the request digest.)
- Added `docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md` and `docs/enterprise/T80_ENTERPRISE_ARCHITECTURE_FOUNDATION.md`, recording the modular-monolith decision, CSV/manifest hash packages remaining the scientific evidence, PostgreSQL carrying business metadata only, large files staying in file or object storage with references and hashes in the database, Kafka carrying domain events only, the mandatory Transactional Outbox ordering, the optional-extensible boundary and the exclusion of Kubernetes, service mesh and cloud deployment.
- Explicitly did not install or integrate PostgreSQL, Docker, Kafka, Redis, FastAPI, SQLAlchemy, Alembic or OpenTelemetry, did not change `requirements.txt` or `requirements-dev.txt`, added no third-party dependency, created no table or migration, added no Streamlit page, migrated no CSV data and changed no research data, method registry, T40/v0.2 freeze or T76 implementation.
- Added T80 to `TASKS.md` under new phase eight as P1 with status `Review`, and added an optional Enterprise Lab boundary section to `docs/ARCHITECTURE.md` without rewriting the existing architecture.

## 2026-09-17 · T76 launcher proxy bypass for local instance detection

- Fixed `Start_SteelAI.bat` misreporting a running SteelAI instance when the machine sets `HTTP_PROXY`/`HTTPS_PROXY` without a localhost exception: the loopback health probe was sent to the proxy, answered 502, and the launcher then tried to occupy port 8501 a second time.
- Added `scripts/check_local_streamlit_health.ps1` because Windows PowerShell 5.1 `Invoke-WebRequest` has no `-NoProxy` switch; the probe builds its own `System.Net.WebRequest`, sets `Proxy = $null` for that single loopback request and closes the response object.
- Kept the existing launcher behaviour on HTTP 200: report the running instance, respect `STEELAI_NO_BROWSER` and exit 0; an unreachable endpoint still falls through to the unchanged Streamlit start command.
- Proxy boundary: no proxy environment variable is read, changed or persisted, no global default proxy is set, no curl or new dependency is added, and the listen address, default port and Streamlit arguments are unchanged.
- Added `tests/test_windows_launcher.py` (5 tests) which runs the launcher and the probe against a temporary loopback health server with `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` pointing at a dead local proxy and `NO_PROXY` empty, proving detection still works, that no second instance is started, and that the probe reports "not running" when nothing answers.
- Corrected `README.md`, which documented a `启动_SteelAI.bat` compatibility entry point that does not exist in the repository; the run section now points only to `Start_SteelAI.bat`.
- Added T76 to `TASKS.md` as P0 with status `Review`, awaiting Codex and owner acceptance.

## 2026-09-16 · T75 formal acceptance of the double-hit softening result table

- Accepted the governed 16-row `thermal_simulation_softening.csv` table after named review by `yjh`; governance intake `INTAKE-E4FC0CFBAEE9C97BECB0` records the formal write.
- Confirmed the approved 2% offset primary method, 5% true-strain sensitivity method, common softening equation and four-entry method registry remain unchanged.
- Retained 12 `passed` rows and four `warning_needs_human_review` rows; A79, A80, A84 and A85 keep their unclamped primary values of 107.29%, 120.44%, 109.66% and 103.48%.
- Closed the T75 task and updated its decision record without changing the governed CSV, calculation code, method registry, dependencies or publication state.

## 2026-09-11 · T75 double-hit softening calculation

- Froze the project-owner-approved 2% offset primary method, 5% true-strain sensitivity method and common softening equation; retained 0.2% only as a future option.
- Added deterministic offset-line intersections, fit-resolution gates, Hollomon projection for the 5% reference stress and complete source/config/result hashes.
- Calculated all 16 governed DH acquisitions: 12 pass the 0–1 range check and four retain unclamped warning values above 100%.
- Added a per-acquisition result table, method comparison plot, diagnostic CSV download and named append-only result approval workflow.

## 2026-09-11 · T74 governed thermal-simulation feature table

- Added a versioned, deterministic one-row-per-run feature extractor for approved double-hit loading segments.
- Added two-hit peak, peak-coordinate, temperature, timing, displacement, strain and fixed-strain flow-stress features with no extrapolation.
- Added source-file, source-point, formula, segmentation, feature-policy, segment-candidate and feature-row hashes.
- Added candidate CSV download plus named human segment approval and append-only governed admission to `thermal_simulation_features.csv`.
- Confirmed all 16 governed DH runs generate candidate rows; after named visual review, A75 was admitted first and the remaining 15 rows were appended without overwriting it.

## 2026-09-11 · T73 literature-aligned double-hit preprocessing

- Added a versioned, literature-aligned double-hit policy separating published softening/yield conventions from SteelAI-specific instrument segmentation thresholds.
- Added deterministic per-hit contact and unloading-boundary suggestions, baseline-corrected analysis stress and per-hit local true strain while retaining cumulative strain and the complete raw-formula path.
- Pre-ran all 16 governed DH acquisitions: 32 candidate loading segments were found, all explicitly retained as `suggested_needs_human`.
- Added UI comparison/downloads and fail-closed tests; formal 0.2% offset yields and softening fractions remain out of scope until visual review.

## 2026-09-11 · T72 thermal curve visualization

- Registered the project-owner supplied Phi10x15 mm stress/strain equations as a versioned deterministic formula with geometry, unit and test-type guardrails.
- Added single-acquisition and reviewed-condition B/R comparison views for stress-strain, temperature-time, raw force-time and raw stroke-time curves.
- Kept negative-force, unload and return segments visible by default; no smoothing, zero correction, friction correction or point deletion is implied.
- Added current-selection derived-data download and fail-closed tests for formula values, geometry, test type and nonpositive current height.

## 2026-09-11 · T71 governed thermal-simulation intake

- Added a deterministic parser for `ZHT.A*` thermal-simulation text exports, including header, channel, interval, count, point-order and time-order QC.
- Added separate optional run and curve-point schemas to the research data contract, preserving raw force values and blocking ambiguous `Kg` conversion.
- Added the “热模拟曲线” intake UI, plan-mapping template, unit/identity confirmations, plan-versus-curve comparison, ignored review-package export and named human approval.
- Added related-table validation plus same-lock preparation and rollback so run and point tables cannot be partially admitted by the application.
- Admitted the selected real `double-hit` folder as 18 runs and 14,352 points after project-owner confirmation; source files were not modified or copied.
- Preserved incorrect plan settings as deviation history while using reviewed instrument values, preserved Force as instrument kg values without inferring N, converted Stroke cm to mm and recorded 10 mm × 15 mm specimen geometry.

## 2026-09-11 - T70 external file standardization intake

- Added one daily-use CSV/TSV/XLSX intake page with source preview, deterministic field suggestions, explicit human mapping and unit confirmation.
- Reused the existing governed append-only gate and added an `external_file` route with source digest and standardization-record evidence.
- Allowed new research samples to be registered only through the governed samples table; all dependent records still reject unregistered sample identities.
- Added dependency-free XLSX flat-table reading, deterministic registered conversions and fail-closed tests for unknown units, duplicate mappings and unregistered samples.

## 2026-09-10 - T64 portfolio and public-release preparation

- Froze 16 public assets, four claim-to-evidence mappings, eight release gates and explicit privacy boundaries for the job-portfolio candidate.
- Added an English README, a three-minute demo script, an interview guide and a one-command governed release-checklist package.
- Integrated the T64 contract into the quality gate, run center and Career Portfolio page while retaining `needs_human` status.
- Left clean-environment replay, T63 measurements, actual video recording, technical report, resume wording and final public release as named human tasks.

## 2026-09-10 - T63 governed human and agent workflow benchmark preparation

- Froze four material-research tasks, three comparable workflows, two repetitions, seven measurement families and a pre-run advantage rule.
- Added closed record validation, a 24-row measurement template, failed-run retention, deterministic comparison and append-only governance packages.
- Added 12 instrumentation-calibration records that prove the reporting path but are explicitly excluded from efficiency claims.
- Exposed benchmark preparation and status in the multi-agent page and run center; T63 remains `Review / needs_human` until 24 real measurements are completed.

## 2026-09-10 - T62 governed real steel-data case

- Registered the UCI Steel Plates Faults dataset with DOI, CC BY 4.0 attribution and fixed archive/member SHA-256 values while keeping raw data out of the repository and result package.
- Froze a stratified 60/20/20 SHA-256 split, majority baseline and training-standardized distance-weighted kNN selected only on validation macro F1.
- Added one-command online/offline reproduction, dataset/split/model cards, predictions, error analysis, Chinese report and append-only governance package with idempotent reuse.
- Added a lightweight Workbench result view and run-center entry; the technically passed result remains a human-review-required `working_candidate`, not a production or metallurgical claim.

## 2026-09-10 - T61 governed MCP tools and lightweight A2A handoff

- Added five versioned local stdio MCP research tools with closed schemas, role permissions, timeouts, stable errors and idempotency keys.
- Added a hash-bound lightweight A2A task envelope and revision-bound human task permit for T60 roles.
- Added append-only tool receipts, duplicate-input conflict protection, a structured multi-role handoff demo and an MCP handshake test.
- Explicitly limited compatibility claims to the tested SteelAI local subset; every output remains nonformal and human-review-required.

## 2026-09-10 - T60 governed materials multi-agent orchestration

- Added five role and permission contracts for planning, data, statistics/physics, materials interpretation and machine review.
- Added named-human plan/result checkpoints, auditable handoffs, one controlled retry, human takeover and append-only run traces.
- Froze synthetic success, insufficient-evidence, tool-failure and cloud-offline demonstrations; deterministic processing remains available offline.
- Added a Research Assistant multi-agent page, run-center integration, contract validation and focused regression tests.

## 0.2.0-rc1-stage5-release-candidate - 2026-09-10

- Froze the T57 release contract across nine research workspaces, eight cross-module regression scenarios, three offline-degradation paths and zero-failure/zero-privacy-finding gates.
- Added fail-closed release validation and integrated it into the deterministic quality gate; target chains must match the global governance contract and all evidence references must remain repository-relative and present.
- Added one Windows candidate-freeze command covering the release contract, quality gate, full offline suite, T40 synthetic flagship replay and public audit without creating commits, tags or remote releases.
- Updated architecture, installation, limitations, capabilities and user-operation documentation; recorded full governed automation execution as an explicit post-v0.2 deferral rather than an accepted result.
- Prepared the stage-five acceptance archive and the local `v0.2.0-rc1` candidate while preserving synthetic-demo and public-data boundaries.

## stage5-t56-unified-run-and-results-center - 2026-09-10

- Added one read-only run-center index spanning governed intake, Physics, statistics, image/model tasks, Agent gateway audits, research sessions, automation status and the frozen T40 demo.
- Normalized task identity, module, state group, integrity, time, reviewer, relative result location, portfolio eligibility and source-workspace navigation without loading heavyweight artifacts or exposing absolute paths.
- Added explicit filters for active, human-review, blocked, invalidated, completed and accepted-result records plus dashboard and Research Assistant entry points.
- Changed Career Portfolio to consume only complete, integrity-passed and named-human-accepted results; ordinary events, Agent working candidates and unreviewed intermediates remain excluded, while T40 requires a separate synthetic-only acceptance registry.

## stage5-t55-agent-evidence-gateway - 2026-09-09

- Added one fail-closed gateway in front of both supported cloud-agent adapters, with fixed read-only tool contracts, pre-call send summaries and stable `AGEVID` identities for allowed structured evidence.
- Required passed T52 research-data contracts for processed data and Physics tools, plus complete human-reviewed T54 result-index entries before EBSD or SEM model output can be sent.
- Added recursive field redaction and value scanning for local paths, protected raw filenames and likely credentials; audit packages retain hashes, evidence references, usage and failure types without questions, answers, arguments or tool payloads.
- Normalized model prose into a five-section restricted explanation contract, removed approval/formal-write/Shell authority, renamed local saving to a human-review draft and added offline privacy/authority regression tests without real API calls.

## stage5-t54-governed-image-and-model-tasks - 2026-09-09

- Added one T51-based EBSD/SEM image-task contract covering read-only sources, sample/specimen/field identities, versioned parameters and isolated runtime identities without copying raw files or heavyweight artifacts.
- Added append-only model-run records for completed, partial, failed, canceled and rerun outcomes; completed and partial outputs remain `needs_human` until a separate review package is created.
- Added explicit human acceptance and rejection packages, partial-result warning acceptance, tamper invalidation and a verified result-index adapter while preserving `model_output` as distinct from experimental measurement.
- Added a shared task/run/review panel to the EBSD and model-laboratory pages plus isolated regression tests for both modalities, failure closure, traceability and source preservation.

## stage5-t53-governed-statistics-and-evidence - 2026-09-09

- Added a T51-based statistics governance adapter that packages verified SteelStats reports with statistical units, observations, inclusion decisions, method versions, reviewer identity and SteelData source hashes.
- Added an append-only traceability index, governed descriptive report, evidence level and allowed/cautious/prohibited statement policy; warning completion requires explicit hash-bound human acceptance.
- Connected Evidence & Validation to the latest valid governed statistics package and excluded invalidated packages from scientific wording.
- Added isolated and real sibling-CLI regression tests for backtracing, no inference or causal promotion, warning handling, idempotent reuse, tamper invalidation and byte-for-byte SteelData source preservation.

## stage5-t52-governed-data-and-physics - 2026-09-09

- Routed both manual standard-CSV intake and SteelData result intake through one T51 identity, human approval, state-transition, QC, manifest and append-only audit adapter.
- Changed unknown intake units from advisory warnings to fail-closed pre-standardization errors; missing values remain missing and duplicate keys remain non-overwritable.
- Added governed Physics runs with immutable input snapshots, formula IDs/versions, applicability, warnings, model cards, experimental comparisons, residual definitions and explicit empirical-estimate labels.
- Added explicit scope-warning acceptance, idempotent Physics package reuse, tamper invalidation and isolated acceptance tests without reading or changing real research data or the frozen T40 demo.

## stage5-t51-shared-governance-core - 2026-09-09

- Added the dependency-free `steelai.governance` package with stable object identity, source reference, human approval, transition, manifest, verification and publication data classes.
- Implemented canonical JSON/SHA-256, T50 state-transition enforcement, hash-bound execution authorization, ten-condition formal-write gates and stable fail-closed errors.
- Added governed package sealing, complete-marker binding, tamper invalidation, same-filesystem atomic append-only publication, idempotent replay and conflicting-content refusal.
- Added migration guidance, quality-gate integration and isolated regression tests without reading or changing real research data or changing the T40 workflow.

## stage5-t50-global-research-governance-freeze - 2026-09-09

- Froze one global research-governance contract across data intake, Physics Engine, traceable statistics, EBSD/SEM, Research Agent, model laboratory, automation tasks, research sessions and portfolio projection.
- Defined stable research-object identities, ten common states, explicit `needs_human` and `blocked` triggers, result levels, hash-bound human approval records and ten formal-write gates.
- Separated real research data, synthetic demo data, model output and human conclusion so demonstrations and AI-generated content cannot masquerade as experimental truth.
- Added a human-readable specification, responsibility/coverage matrices and offline contract tests without changing real data, existing outputs, page behavior or the frozen T40 flagship demo.

## stage4-t41-public-repository-candidate - 2026-09-08

- Added a fail-closed audit for the Git-tracked public candidate, covering local user paths, common secrets, private runtime areas, research sessions and model-weight formats.
- Added the MIT license, README badges and architecture overview, cross-platform clean-install instructions, explicit known limitations and a frozen T41 release-candidate checklist.
- Added the public audit to the deterministic quality gate and regression suite; kept all real data, local outputs, approvals and personal sessions outside the public candidate.
- Added a cross-platform public-workspace bootstrap that copies only tracked synthetic fixtures and refuses to overwrite different local data, replacing CI-specific shell copy commands.
- Removed hidden clean-clone test dependencies on local settings, sibling-module availability and private processed values; pinned the four direct runtime dependencies to the versions used for clean-install acceptance.
- Recorded T42 and T43 as owner-canceled rather than incomplete; no remote repository was created and no GitHub push occurred.

## unified-complex-page-flow-and-next-actions - 2026-09-08

- Added consistent workspace workflow strips and a shared four-part complex-page structure cue: current state, primary action, result and technical details.
- Added contextual next-step actions across data, physics, QC, statistics, research, evidence, model and automation views.
- Implemented safe same-page module callbacks plus explicit cross-workspace deep links, including statistics-to-validation, evidence-to-QC and model-to-validation routes.
- Browser-tested the full data path from sample comparison through physics and QC to statistics, then across to evidence validation without a Streamlit state error.

## workspace-navigation-and-data-comparison-redesign - 2026-09-08

- Replaced crowded horizontal submodule pills with one consistent current-function selector plus plain-language purpose guidance across the four technical workspaces.
- Renamed user-facing module labels in Chinese while keeping existing view files, calculations, review gates and stored data unchanged.
- Rebuilt the B/R comparison landing view around four descriptive performance differences, sample cards and vertically organized Chinese field tables; missing values remain explicit and are never treated as zero.
- Added a focused model-lab content selector so B/R results, Review30 work and environment/pilot details no longer render as one long mixed page.

## dashboard-research-cockpit-redesign - 2026-09-08

- Reframed the research overview as a graduation-project cockpit with a clear project statement, primary actions, system snapshot and four-stage evidence pipeline.
- Promoted the two current B/R research objects and daily next steps while moving raw tables, completeness checks and local paths into collapsed technical details.
- Added a direct, state-safe entry from the overview to the accepted T40 flagship demo and refreshed shared visual styling without changing research data or calculation behavior.

## stage4-t40-owner-acceptance - 2026-09-08

- Recorded the project owner's explicit “T40 验收通过” after viewing the live flagship page.
- Moved T40 from Review to Done; implementation, data boundaries, frozen output identity and test evidence remain unchanged.

## stage4-t40-frozen-flagship-demo-review - 2026-09-08

- Added a one-command public-synthetic showcase spanning source-bound Agent-shaped suggestion, explicit frozen human-decision fixture, SteelData normalization/QC, isolated SteelStats reporting and bounded SteelAI interpretation.
- Added a real negative path where an unresolved YS unit stays `needs_human`; an attempted unapproved execution returns `execution_not_approved` and writes no result.
- Added semantic expected values, recursive SHA-256 package verification, idempotent reuse, tamper refusal, a Workbench result view, operating checklist and regression tests.
- Bound nested completion markers and the complete SteelData/SteelStats Python source fingerprints into the frozen identity, with bounded retry for transient Windows directory locks and no-overwrite behavior unchanged.
- Kept T40 in Review until the project owner accepts the visual presentation; no real data, cloud call, automatic approval, formal data intake or inferential claim is part of the demo.

## stage3-t33-steelstats-integration - 2026-09-08

- Added a “可追溯统计” Workbench view that verifies a SteelData tensile result package and requires explicit specimen-to-sample mapping, method version and human inclusion approval.
- Added an isolated SteelStats client that uses only the sibling module's declared `report` and `verify-report` CLI, with a scrubbed environment, fixed arguments, no shared Python imports and no cloud call.
- Added append-only T30 input-bundle preparation, result/QC display, independent report verification and fail-closed handling for invalid source packages, duplicate specimens, missing review data, module errors and output-path violations.
- Added a real cross-project subprocess test proving that report generation leaves every SteelData source-package file digest unchanged.

## stage2-t24-label-approval - 2026-09-07

- Recorded project-owner acceptance of the 40 sanitized Intake Agent v0.1 labels and moved T24 from Review to Done.
- Preserved the 95% known-mapping threshold, mandatory human routing for unknown units and ambiguity, and all existing Agent permission limits.
- Label approval does not represent a DeepSeek or other cloud-model baseline; live model evaluation remains a separate explicit action.

## stage2-t24-intake-agent-evaluation-review - 2026-09-07

- Added an explicit Intake Agent section to the existing Agent Evaluation view for inspecting 40 synthetic case labels and running the deterministic reference baseline.
- Added fixed SteelData CLI calls for benchmark inspection and local report generation; opening the page does not execute a benchmark or call a cloud model.
- Exposed known-mapping accuracy, human-review routing, unapproved execution, source modification, replay, latency, token and failure-class evidence without adding Agent permissions.
- Kept T24 in Review until the project owner approves the labels; the reference score is not presented as DeepSeek or general Agent performance.

## stage2-t23-approved-execution-intake - 2026-09-06

- Connected a successful single-item human approval to SteelData's hash-bound execution command and exposed status, safe retry/recovery and completed-result reload in the existing panel.
- Verified the embedded suggestion, human review and system execution-request audit chain before exposing result records to Workbench.
- Routed verified results through the existing explicit specimen-to-sample mapping, source-status selection and append-only intake gate; no processed row is written automatically.
- Retained source-origin deduplication across changed sample IDs, primary-key no-overwrite behavior and DSH/Agent denial of approval and execution.

## stage2-t22-steeldata-human-review - 2026-09-06

- Added a single-item SteelData review area to the existing Workbench data-quality page, showing source integrity, mapping/unit evidence, uncertainties, risks, configuration diff and content digests.
- Required an explicitly entered human reviewer, note and decision-specific confirmation for approval or rejection; no batch-approval action exists.
- Called SteelData through fixed CLI verbs with expected revision and suggestion digest so stale pages and repeated submissions fail closed.
- Saved proposal, approval and human-decision digests separately while leaving approved execution and processed-data writes to T23.

## stage2-t21-mapping-suggestion-contract - 2026-09-06

- Added the Workbench-side DSH procedure for SteelData's source-bound, structured mapping suggestion contract and controlled candidate/needs-human/unsupported states.
- Switched the local and example DSH registration from preview to suggest mode while keeping research data writes, approval, execution and arbitrary shell tools unavailable.
- Recorded the content-hash/revision boundary that T22 must verify and preserved a local pre-T21 patch for rollback to T20 preview mode.
- Added no approval UI, batch execution or Workbench data write.

## stage2-t20-dsh-steeldata-v02-preview - 2026-09-06

- Kept the seven-tool SteelAI research bridge and added a separately registered SteelData v0.2 preview-only MCP using SteelData's own Python environment.
- Restricted the DSH-facing SteelData catalog to status, relative input listing and redacted profile preview; no approval, batch execution or arbitrary shell tool is exposed.
- Verified both local DSH patches compose successfully and recorded rollback without changing the Workbench intake gate or research data.
- Documented the Harness/Skill/MCP/Python-core responsibility split and deferred proposal state, approval UI and approved execution to T21-T23.

## stage1-t14-frictionless-optional-adapter - 2026-09-05

- Added a lazy, synthetic-only Frictionless 5.19.0 adapter for the graduation-v1 Tabular Data Package descriptor and independent structural validation.
- Pinned all 40 Windows CPython 3.12 packages with wheel hashes; retained the MIT license, source record, measured dependency size and a removal guide outside main requirements.
- Measured 30 warm runs: native median 1.691 ms and adapter end-to-end median 36.033 ms; the extra 34.342 ms is acceptable for an optional export demonstration.
- Added fail-closed evidence checks and verified both installed and unavailable paths. Corrected the Workbench runtime record from 3.14.2 to the observed 3.12.14.

## stage1-t13-open-source-reuse-registry - 2026-09-05

- Added a machine-readable third-party candidate registry and `THIRD_PARTY.md` with five pinned official project references, verified OSI license links, dependency impact and explicit decisions.
- Selected only the Frictionless Data Package/export-validation feature for bounded T14 evaluation; NOMAD is reference-only, GEMD and MLflow are deferred, and Great Expectations is rejected for overlapping scope and maintenance cost. T14 later corrected the recorded Workbench runtime to Python 3.12.14.
- Added fail-closed registry tests to reject unknown licenses, floating versions, multiple eligible candidates and any claim that T13 imported code.
- Installed, downloaded and copied no third-party code; existing scientific and privacy gates remain unchanged.

## stage1-t12-graduation-data-contract - 2026-09-05

- Froze `SteelAI-Graduation-Core-v1.0` for the personal graduation MVP, limited to specimen-level tensile YS, UTS and elongation.
- Added machine-readable material/heat/sample/specimen/report/observation relationships, public synthetic examples and closed validation in the local quality gate.
- Separated specimen observations from reported summaries and explicitly deferred curve points, image fields and EBSD pixels as non-specimen objects.
- Documented non-destructive migration from existing summary/observation tables and SteelData without activating a real-data migration or committing T10 staging.

## stage1-t11-real-format-regressions - 2026-09-05

- Recorded SteelData's public synthetic regression coverage for Chinese/English headers, blank rows, worksheet selection, profile ambiguity, unit conflicts, duplicates and bad values.
- Kept the Workbench result-contract and formal-import gates unchanged; the T10 local staging package remains `not_committed`.
- Confirmed that no real report content, measurement values, identities, report identifiers or local paths were added to either repository.

## stage1-t10-real-tensile-acceptance - 2026-09-04

- Accepted one human-approved, desensitized DQ SteelData package with 6 physical specimens and passed integrity, QC and same-runtime replay checks.
- Applied the six explicit specimen-to-sample bindings and `manual_extraction_verified` source status to a Workbench preflight containing 18 unique YS/UTS/EL observations.
- Saved an ignored local staging package, validation manifest and source audit with `not_committed` status; no formal `property_observations.csv` append occurred.
- Marked T10 complete while retaining T200, curves, impact, geometry, reduction of area and microscopy outside this task.

## stage0-governance - 2026-09-04

- Established the local Git privacy baseline and documented excluded real-data, path, credential, output and model-weight areas.
- Recorded the 105-test offline baseline, with two documented environment-dependent skips.
- Added a lightweight task board, task template, status definitions, task numbering and change-record rules.
- Synchronized the README and capability matrix with the implemented SteelData v0.2 CLI/result-contract integration and retained DSH boundary.

## 0.13.0-research-session-workflow - 2026-08-22

- Added five versioned daily research workflow templates inside the existing Research Assistant area without adding a sidebar entry.
- Added local research sessions with revisioned atomic JSON persistence, stage progress, structured findings, next actions, status transitions and relative run references.
- Added active, blocked, completed and open-action summaries to the existing Research Overview.
- Linked completed B/R Research Case runs to the current research session and automatically completed the corresponding workflow stage.
- Kept sessions limited to B-DQ/R-DQ, rejected absolute paths and raw CTF/TIF filenames, and retained experiments 1-14 outside the workflow.
- Added a Research Session Contract to the offline quality gate and added component-level coverage for the creation workflow.
- Expanded the automated suite from 57 to 64 tests.

## 0.12.0-physics-model-registry - 2026-08-22

- Added a local, machine-readable Physics Model Registry for 10 existing formula versions across Ms, Ac1, Ac3, Tnr, Ceq and Pcm.
- Registered model version, family, formula, source, required inputs, unit, applicability range, limitations, license note, review status, experimental-reference interface, residual convention and calibration status.
- Added per-family formula selection, model cards and non-destructive version-comparison reports inside the existing Data & Physics → Physics Engine view.
- Changed missing-input behavior to skip calculation without replacing unknown chemistry with zero; retained explicit composition-range warnings.
- Added a read-only experimental/model/residual interface using controlled `physics_observations.csv` records and the convention model value minus experimental value.
- Unified the Streamlit view, Research Agent and research-case pipeline on the same local registry while keeping the legacy v0.1 adapter available for compatibility tests.
- Added the Physics Model Registry contract to the offline quality gate; experiments 1-14 remain excluded and model estimates remain distinct from experimental truth.
- Expanded the automated suite from 54 to 57 tests.

## 0.11.0-data-intake-gate - 2026-08-19

- Added a local validation-first Data Intake workflow inside the existing Data & Physics area without adding navigation pages.
- Added controlled header-only templates for composition observations, process steps, microstructure fields, property specimens and physics observations.
- Added an explicit research ID hierarchy covering material, heat, batch, sample, specimen, field, observation and run levels.
- Added UTF-8/GB18030 CSV parsing, explicit Chinese column aliases, numeric and required-value checks, scope/orphan checks, primary-key conflict blocking and unit warnings.
- Enforced dry-run by default, explicit user confirmation and append-only processed writes; existing keys are never replaced.
- Added privacy-safe intake audit packages containing only normalized structured staging data, hashes and manifests; raw uploads, local paths and API calls remain outside the flow.
- Kept experiments 1-14 excluded and kept the current B/R evidence at directional-only readiness.
- Expanded the automated suite from 49 to 54 tests.

## 0.10.0-research-data-contract - 2026-08-19

- Added a machine-readable contract for sample, composition, process, microstructure, property and physics-observation data.
- Preserved current summary tables while defining optional long-form ledgers for process steps, microstructure fields, independent property specimens and experimental/model physics values.
- Added column, numeric-type, duplicate-ID, foreign-key, scope and completeness checks without filling missing measurements.
- Added a data-quality and expansion-readiness panel inside the existing Data & Physics area.
- Added an offline quality-gate command and a GitHub Actions workflow using synthetic public fixtures, current official v7 checkout/setup-python actions and read-only repository permissions.
- Kept experiments 1-14 excluded and kept causal inference and machine learning marked not ready.
- Expanded the automated suite from 44 to 49 passing tests.

## 0.9.0-agent-observability - 2026-08-19

- Verified the first live DeepSeek baseline: 3/3 smoke cases passed, including pre-API path blocking; this is a smoke baseline rather than a claim of general Agent reliability.
- Added evaluation history, score/latency/token trends and common-case run comparison with explicit regression detection.
- Added per-tool timing and a sanitized trace export that excludes questions, answers, tool arguments, local paths and raw files.
- Added a trace explorer inside the existing Agent Evaluation view without adding a seventh sidebar area.
- Kept MLflow/OpenTelemetry as a later optional adapter so the stable main environment does not gain a heavy dependency prematurely.
- Expanded the automated suite from 42 to 44 passing tests.

## 0.8.0-agent-evaluation - 2026-08-19

- Added a 25-case B/R Research Agent benchmark across data grounding, Physics, EBSD, SEM, scientific guardrails, privacy and permissions.
- Added transparent deterministic scoring for expected tool calls, required evidence concepts, prohibited claims, privacy, status and latency.
- Added a small-batch live DeepSeek evaluation workflow with per-case traces, token usage, failure diagnosis, reports and manifests.
- Added a local pre-API gate that rejects questions containing absolute paths or raw CTF/TIF filenames.
- Added an Agent quality dashboard inside Research Assistant without increasing the six-entry sidebar.
- Added machine-readable evaluation artifacts ready for later MLflow/OpenTelemetry ingestion.

## 0.7.0-research-case-pipeline - 2026-08-18

- Replaced the separate quick-report view with one end-to-end B/R research task, avoiding another navigation entry.
- Added deterministic orchestration across processed-data checks, sample comparison, Physics, dual-scale EBSD, AutoDimple and evidence validation.
- Added optional DeepSeek synthesis after all deterministic stages; the offline pipeline remains complete without an API.
- Added one run package containing a Markdown report, privacy-scrubbed evidence snapshot and versioned Run Manifest.
- Recorded processed-data hashes, code hashes, stage timing, Agent trace, scientific readiness and privacy policy for reproducibility.
- Kept experiments 1-14 excluded and rejected local paths or raw CTF/TIF names before any external Agent call.

## 0.6.1-consolidated-navigation - 2026-08-18

- Reduced the sidebar from eleven entries to six task-oriented workbench areas.
- Merged sample data with Physics, offline analysis with Research Agent and validation, evidence indexing with EBSD, and Model Lab with automation results.
- Kept the original feature implementations as independently tested embedded views, so navigation cleanup does not remove scientific functionality.
- Added explicit Streamlit navigation titles, compact submodule selectors and shared visual styling.
- Removed duplicated page-level configuration and hidden local-only deployment/menu controls.

## 0.6.0-evidence-validation-center - 2026-08-18

- Added the B/R Evidence & Validation Center as the eleventh workbench page.
- Added a deterministic evidence registry covering composition, mechanics, physics, dual-scale EBSD, AutoDimple and missing XRD validation.
- Added nine claim assessments with allowed wording, prohibited wording, evidence gaps and next actions.
- Enforced six scientific gates for source truth, replicate independence, image pseudoreplication, EBSD scale separation, empirical-model labeling and causal claims.
- Added a seventh read-only Research Agent tool that exposes the validation matrix without source locators or raw-file information.
- Explicitly excluded experiments 1-14 from the core evidence set, statistics and machine learning by user decision.
- Expanded the automated suite to 30 passing tests.

## 0.5.1-deepseek-provider - 2026-08-18

- Switched the default Research Agent provider to DeepSeek V4 Flash for domestic RMB billing and lower operating cost.
- Added provider-aware key, model and base-URL configuration while retaining the OpenAI provider as a fallback.
- Added a dedicated DeepSeek strict Chat Completions tool loop instead of assuming identical Responses API behavior across providers.
- Kept all six scientific tools read-only and retained the existing audit trace and user-controlled save boundary.

## 0.5.0-research-agent - 2026-08-17

- Added a single read-only Research Agent page with six strict, whitelisted tools.
- Reused the deterministic sample, physics, EBSD and AutoDimple modules instead of duplicating scientific calculations.
- Added explicit tool-call and round limits, path filtering, scientific guardrails and a user-controlled save step.
- Kept LangChain out of the current architecture; the agent uses the OpenAI Responses API directly and remains offline when no API key is configured.
- Added offline status, tool-loop and full-page rendering tests.

## 0.4.2-dual-scale-ebsd - 2026-08-14

- Added the R-DQ region-3 high-resolution CTF and paired it with B-DQ region 2.
- Added tolerant CTF compatibility checks for step size, magnification and physical field dimensions while keeping voltage, tilt and phase definitions exact.
- Added a second high-resolution B/R MTEX workflow, status contract, comparison report and paired Streamlit display.
- Enforced independent low- and high-resolution groups with no cross-resolution metric pooling.
- Completed the high-resolution B/R run and expanded the automated suite to 19 passing tests.

## 0.4.1-matched-br-ebsd - 2026-08-14

- Added the selected R-DQ region-1 1000x CTF to the EBSD workflow.
- Added acquisition compatibility checks and selected the matched B-DQ region-3 1000x map.
- Added sequential B/R MTEX execution, structured metric comparison, paired map display and CSV download.
- Added explicit one-field-per-condition and phase/grain interpretation guardrails.
- Expanded the automated suite to 18 tests.

## 0.4.0-ebsd-mtex-pilot - 2026-08-14

- Added the EBSD Analysis Streamlit page.
- Added a non-interactive MATLAB/MTEX job runner and persistent job status.
- Added read-only CTF metadata inspection plus standardized grain, boundary, KAM, phase and plot outputs.
- Added EBSD parser, status and scientific-guardrail tests; the workspace suite now has 17 passing tests.
- Completed the first real B-DQ region-2 1000x EBSD pilot with MTEX 6.1.0.

## 0.3.0-automation-center - 2026-08-14

- Added a Streamlit Automation Center page.
- Added a hidden background-job launcher for the isolated Conda/GPU AutoDimple workflow.
- Added persistent job status and log files plus result loading for B/R metrics, tables, plots and reports.
- Added automated tests for launch configuration and status handling; the full suite now contains 14 passing tests.

## 2026-08-10 · AutoDimple v0.1

- Added the preliminary 1000× SEM automatic dimple standard.
- Added acceptance-rate correction and automatic eligibility checks.
- Disabled routine per-object review and added out-of-standard exclusion rules.
- Added the Review30 validation summary to Open Model Lab.

## 2026-08-11 · B/R ten-image batch analysis

- Added the one-click `Run_AutoDimple_BR10.cmd` workflow.
- Added GPU batch segmentation, post-filtering, per-image tables, overlays and resumable outputs.
- Added image-level B/R bootstrap comparison and pseudoreplication guardrails.
- Added AutoDimple-BR-1000x-v0.2 warning-versus-exclusion policy.
- Added the B/R batch result panel to Open Model Lab.

## 0.2.0-model-lab - 2026-08-10

- Added Open Model Lab with a model registry and isolated-install status.
- Added NVIDIA GPU detection and SEM TIF/HDR metadata parsing.
- Added balanced B/R pilot selection using five 1000× images per steel.
- Added normalized 16-bit TIF previews without modifying source files.
- Added tests for model-lab scanning and all seven Streamlit entry pages.

## 0.1.0-mvp - 2026-08-09

- 建立六页 Streamlit 本地工作台骨架。
- 建立 samples/composition/process/microstructure/properties processed 数据层。
- 加入 Ms、Ac1、Ac3、Tnr、Ceq、Pcm 经验公式注册表、来源、审查护栏与 warning。
- 加入离线结构化研究报告，以及可选 OpenAI Responses API 润色层。
- 加入证据路径索引、project event log 和 Career Portfolio 自动生成。
- 明确 DEMO 数据、模型估算和实验真值边界；暂不引入 XGBoost/DeepXDE。
# 2026-08-10 · micro-sam GPU pilot

- Added an isolated Python 3.12 environment for `micro-sam 1.8.8`.
- Installed and validated GPU-enabled `PyTorch 2.7.1+cu128` on RTX 4060 Ti.
- Added the official Meta Segment Anything ViT-B checkpoint.
- Ran paired B/R 1000× SEM smoke tests without modifying source TIF files.
- Added traceable JSON output, overlays, micro-sam embedding cache, and two one-click annotator launchers.
- Marked every current mask as a technical test pending target definition and human review.
# 2026-08-10 · Conda Commit backend

- Installed signed Miniforge 26.3.2 without changing the global Python or PATH.
- Created a dedicated local Miniforge environment with Python 3.12, micro-sam 1.8.8, z5py 3.0.2, and CUDA PyTorch; its machine-specific path is not tracked.
- Added a Windows Zarr path adapter and switched the B/R launchers to the Conda environment.
- Created separate B/R Commit stores to prevent annotation history from being mixed across images.
- Retained the prior pip environment as a temporary rollback option until the first UI Commit is confirmed.
