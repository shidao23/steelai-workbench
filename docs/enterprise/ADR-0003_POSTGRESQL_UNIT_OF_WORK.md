# ADR-0003 PostgreSQL Repository、UnitOfWork 与事务型 Outbox

- 状态：`accepted`
- 决策日期：2026-09-17
- 接受日期：2026-09-18
- 决策范围：Enterprise Lab 的可选 PostgreSQL 持久化适配器（Repository、UnitOfWork、事务型 Outbox 写入侧、数据库内任务租约）
- 相关任务：T80（Ports 与领域模型，Done）；T81（Schema 与迁移基线，Done）；T82（本 ADR 的引入者，Done）；T83 及以后（dispatcher、Kafka、worker、API）
- 相关文档：`docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md`、`docs/enterprise/ADR-0002_POSTGRESQL_PERSISTENCE.md`、`docs/enterprise/T82_POSTGRESQL_REPOSITORIES.md`
- 验收结论（2026-09-18）：PostgreSQL 18.6 **真实集成验收通过**；**两轮契约修正完成**（并发取号双成功/租约与锁行语义/UoW 失败生命周期，以及显式 rollback 失败不得静默成功、生命周期优先于参数校验、锁错误脱敏）；**Codex 最终复核通过**；T82 同步由 `Review` 转为 `Done`，本 ADR 由 `proposed` 转为 `accepted`。
- 本 ADR 不构成生产可用性声明：它只决策 Enterprise Lab 可选适配器的边界与语义，下列能力仍**不属于**本 ADR/T82——outbox dispatcher、Kafka、worker 服务、心跳与租约回收、HTTP API、RBAC、多租户、生产备份、高可用与 exactly-once。

## 1. 背景

T80 冻结了 Ports、领域对象与内存适配器；T81 建立并验收了 `steelai_enterprise` Schema 与 Alembic 迁移。
T82 需要在**不修改** T80 契约与 T81 Schema 的前提下，把内存适配器替换为可选的 PostgreSQL 适配器，并证明
同一数据库事务内可以完成"运行 + 引用 + 审计 + outbox + 任务"的原子写入。

## 2. 决策

### 2.1 使用 SQLAlchemy Core 与同步 Psycopg 3，不使用 ORM

- 语句用 Core 的 `Table.insert/select/update` 构造；不使用 `declarative_base`、`Session`、`sessionmaker`
  或惰性加载。
- 领域对象保持 T80 的 frozen dataclass，行恢复（hydration）是显式函数，不把 `Row`、`Mapping`、
  `Connection` 或基础设施列带进领域层。
- 理由：`Session` 会引入身份映射、自动 flush 与延迟提交，使"一个 UoW = 一个连接 = 一个事务"的边界变得
  不可证明；T82 的验收要求正是这个边界。

### 2.2 一个 UnitOfWork 持有一个连接和一个事务

- `PostgreSQLUnitOfWorkFactory` 接受**显式注入的 Engine**；模块导入不连接数据库，不创建全局 Engine、
  Connection 或 Session，也不读取 `.env` 或默认连接串。
- `PostgreSQLUnitOfWork` 在进入边界时惰性 `engine.connect()` 并 `begin()`；五个 Repository 共享这个连接，
  因此它们的写入天然处于同一事务。
- `commit()` 提交并归还连接；`rollback()` 回滚并归还连接；**离开边界但未显式给出结果时一律回滚**，
  所以异常退出不可能留下部分写入。
- 提交或回滚之后，任何先前保存的 Repository 句柄继续读写都返回 `ENT-UOW-001`；`committed` 是该 UoW
  **自身**的永久结果标志，不受后续 UoW 影响。
- 边界失败也关闭式处理：`commit()`/`rollback()` 在边界尚未 `start`（尚未进入 `with`）时返回
  `ENT-UOW-001`；`engine.connect()` 成功但 `connection.begin()` 失败时立即关闭该连接；`commit()` 失败时
  立即尝试 rollback、关闭连接、把边界标记为已关闭，并只抛出脱敏的 `ENT-DB-001`；rollback 本身失败也
  **不会掩盖**原异常，连接同样被关闭。因此失败路径不会泄漏连接，也不会留下可继续使用的句柄。
- 显式 `rollback()` 失败同样不能静默成功：`rolled_back` 保持 `False`，连接与边界仍然关闭，并抛出脱敏的
  `ENT-DB-001`。正常离开 `with` 而未 commit、自动 rollback 又失败时也抛该脱敏错误；只有当 `with` 内
  已有异常正在传播时，rollback 失败才被忽略以**保留原始业务异常**。
- 所有 Repository 调用先校验 UoW 生命周期、再校验参数：已关闭边界的保存句柄即使同时传入不匹配的
  `idempotency_key`，也优先返回 `ENT-UOW-001`（PostgreSQL 与 Memory 一致）。
- advisory lock 语句的失败经与其他数据库错误相同的 SQLSTATE/约束名映射转为脱敏 `ENT-DB-*`，
  不泄露语句、参数、URL 或驱动文本。
- 工厂只提供一种事务创建语义 `unit_of_work()`（读操作就是回滚掉的 UoW），没有第二种只读会话；
  `describe()` 只返回 driver 与数据库名的脱敏诊断信息。

### 2.3 幂等以数据库为裁决者，不使用"先 SELECT 再 INSERT"

- `create_run`：先按键绑定做一次身份判定，然后执行
  `INSERT ... ON CONFLICT DO NOTHING ... RETURNING`。
  该语句形状下 psycopg 报告 `rowcount == -1`，因此**以是否返回行为准**判断是否真的插入；
  未插入时重新读取该行并据此判定"复用"或"冲突"。
- 因此并发创建不会因为竞态产生重复写入，也不必捕获 unique violation 后在已中止的事务上继续工作。
- 冲突（同键不同摘要、同键不同 `run_id`、同 `run_id` 换键）在 artifact/audit/outbox/job 任何副作用之前
  以 `ENT-IDEMPOTENCY-001` 关闭式失败。

### 2.4 乐观并发使用受保护的 UPDATE ... RETURNING

`update_run_state` 使用 `UPDATE ... WHERE run_id = ? AND revision = ? RETURNING ...`，行数为 0 时按
"未知运行"或"修订已变化"区分返回 `ENT-NOTFOUND-001` / `ENT-CONCURRENCY-001`。不存在丢失更新。

### 2.5 Advisory lock 只用于两处序号分配，键由 SHA-256 派生

- 只有**两处**使用 `pg_advisory_xact_lock(bigint)`：全局审计序号、每个 run 的 outbox 序号。
  任务租约**不使用** advisory lock（见 2.8）。
- 键由 `sha256("steelai-t82-enterprise-lab" + 作用域 + 身份)` 的前 8 字节派生；命名空间的作用是
  **降低**本适配器与其他应用使用同一 advisory lock 空间时意外碰撞的概率，**不构成"绝不可能碰撞"的保证**。
- **不使用 Python `hash()`**：它按进程加盐，跨进程不稳定。派生键在任意进程、重启与平台上都相同。
- 锁是事务级的，随事务结束自动释放，因此不会留下悬挂锁。

### 2.6 审计只追加，序号在事务内串行分配

- `AuditRepository` 只有 `append`/`list_events`/`count`，没有 update 或 delete。
- **`count()` 与 `append()` 都先取同一把事务级 advisory lock，再读取当前最大值**：调用方在事务内
  `count() + 1` 后 `append`，整段计算都在锁的覆盖范围内。
- 因此两个并发事务各自"`count() + 1` → `append`"时**都会成功**，最终序号为 1、2；正常并发写入不需要
  调用方重试，也不会出现"一方被拒绝"的关闭式失败。
- `append` 仍校验调用方提供的序号等于 `coalesce(max(sequence), 0) + 1`；**直接提交陈旧或乱序序号**
  以 `ENT-AUDIT-001` 关闭式失败。**不允许**在无锁情况下使用 `MAX(sequence) + 1`。
- 数据库 trigger `trg_audit_events_append_only` 仍是最终保护：并发下即使应用逻辑出错，UPDATE/DELETE
  仍被数据库拒绝。

### 2.7 Outbox 只做写入侧

- `publish` 只向 `outbox_events` 插入一行 `pending`，与业务写入共享同一事务。
- 每个 run 的 `sequence` 由 per-run advisory lock 分配，`next_sequence()` 与 `publish()` 取同一把锁，
  且都在读取最大值**之前**取锁：两个并发事务各自"`next_sequence()` → `publish`"时**都会成功**，
  序号为 1、2。**直接提交**重复或乱序序号仍以 `ENT-EVENT-001` 关闭式失败。
- `replay` 只读取已提交行并按 `sequence` 返回 `DomainEvent`；`delivery_status`、`attempts`、
  `available_at`、`published_at`、`last_error_code` 是 dispatcher 基础设施，**不进入**领域对象。
- T82 **不实现** dispatcher、不连接 Kafka、**不声称 exactly-once**。它只保证"业务写入与 outbox 记录
  原子提交"。

### 2.8 任务租约使用 SKIP LOCKED，且不实现 worker

- `lease` 只使用 `SELECT ... WHERE state IN ('queued','retrying') ORDER BY created_at, job_id
  LIMIT 1 FOR UPDATE SKIP LOCKED`，**不取任何 advisory lock**。
- 正因为不加全局锁，两个重叠事务可以各自持有**不同**任务：只要队列里有第二个可用任务，第二个事务
  立刻跳过被锁行并租到它；当只有一个任务可用时，第二个事务**立即**得到 `None`，不会等待第一个事务提交。
- `complete`/`fail`/`retry`/`cancel` 一律先 `SELECT ... FOR UPDATE` 锁定目标行，再把 T80 的
  `BackgroundJob.transition` 应用到**锁内读到的最新状态**上；`retry` 的 attempts 上限判断也在锁内完成。
- 同一个 leased 任务上并发 `complete` 与 `fail` 只有一个成功；另一方读到最新状态后以 `ENT-JOB-001`
  关闭式失败，**不会覆盖**胜者的结果。
- 状态变化全部复用 T80 的 `BackgroundJob.transition`，**不另造状态机**；非法转换 `ENT-JOB-001`，
  未知任务 `ENT-NOTFOUND-001`。
- **不实现** worker 循环、心跳、租约超时回收与调度器。

### 2.9 数据库错误只按 SQLSTATE 与 constraint_name 映射

- 已知唯一约束、外键、CHECK 与 trigger 错误依据结构化诊断映射到既有 `ENT-*` 错误码；
  **不解析本地化错误文本**。
- 未登记的约束使用稳定的适配器错误码（`ENT-DB-002` 等）；未分类异常使用 `ENT-DB-001`，
  只带 `sqlstate`/`constraint`/`error_type`，**不暴露 SQL、参数、连接串或凭据**。
- 缺少 Schema 对象（`42P01`/`42703`）单独映射为 `ENT-DB-005`，提示先执行企业迁移。
- 任何错误之后 UoW 仍可安全 rollback/close，连接归还连接池。

## 3. 后果与代价

正面结果：`EnterpriseWorkflowService` 只需替换注入的 Factory，业务逻辑一行未改即可运行在 PostgreSQL 上；
"运行 + 引用 + 审计 + outbox" 的原子性由数据库事务保证并有真实并发测试；数据库层面的幂等、乐观并发、
序号分配与任务租约都有确定语义。

代价与风险：

- 序号分配把同一 run 的 outbox 写入与全局审计写入各自串行化在同一把事务锁上：正常并发写入**都会成功**，
  代价是等待而非重试；只有直接提交陈旧或乱序序号时才会以 `ENT-AUDIT-001` / `ENT-EVENT-001` 关闭式失败。
- 审计序号是全局单点，锁竞争随审计写入量上升；未来需要评估按运行分段或使用序列。
- 租约只记录状态，没有心跳与超时回收；在 T82 之后补齐 worker 之前，`leased` 行不会自动回到队列。
- `outbox_events` 的行会持续累积，尚无归档或保留策略。
- 适配器只在 PostgreSQL 18.6 单实例上验证；未覆盖其他主版本、复制、连接池中间件或托管服务。
- `workflow_runs.project_id` 仍是外部标识，`projects` 表与 `ProjectRepository` 未建立。

## 4. 明确不属于本 ADR / T82 的范围

- 事件投递器（dispatcher）与 Kafka 生产者：**未实现**，`outbox_events` 只有写入侧。
- worker 服务、心跳、租约回收、重试调度：**未实现**。
- HTTP API、RBAC、多租户、审计查询接口：**未实现**。
- 生产备份、高可用、只读副本与容量规划：**未实现**。
- exactly-once 投递语义：**未实现，也未声称**；T82 只保证"业务写入与 outbox 记录原子提交"。
- 默认 SteelAI 应用接入数据库：**未接入**。`app.py`、`pages/`、Streamlit 默认入口与 T76 启动器
  均不导入该适配器；没有 `STEELAI_ENTERPRISE_DATABASE_URL` 时应用照常离线运行。

本 ADR 与 T82 都**不得**表述为生产就绪；本 ADR 由 `proposed` 转为 `accepted` 只表示上述**已界定范围**内的
技术决策通过验收，不代表超出该范围的任何能力已经具备。
