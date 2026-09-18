# T82 PostgreSQL Repository、UnitOfWork 与事务型 Outbox

- 状态：`Done`（真实 PostgreSQL 18.6 验收、两轮契约修正与 Codex 最终复核均已完成；2026-09-18 由 `Review` 转为 `Done`，ADR-0003 同步转为 `accepted`）
- 决策日期：2026-09-17；完成日期：2026-09-18
- 边界决策：`docs/enterprise/ADR-0003_POSTGRESQL_UNIT_OF_WORK.md`
- 前置任务：T80（Ports/领域模型，Done）、T81（Schema/迁移，Done）
- 范围：可选 PostgreSQL Repository、UnitOfWork、事务型 Outbox 写入侧、数据库内任务租约
- **不属于本任务**：dispatcher、Kafka、worker 服务、HTTP API、RBAC、多租户、生产备份与高可用
- 验收结论（2026-09-18）：Codex 最终复核通过，T82 由 `Review` 转为 `Done`。真实 PostgreSQL 18.6 集成验收 22 项场景全部通过，两轮契约修正（并发取号双成功与租约/锁行语义、UoW 失败生命周期；显式 rollback 失败不得静默成功、生命周期优先于参数校验、advisory lock 错误脱敏）均已落地并回归通过。本文档不声明事件投递能力、不声明 exactly-once 投递语义、也不声明生产可用性。

## 1. 已实现 vs 未实现

**已实现（本任务）**

- 五个 Port 的 PostgreSQL 适配器：`PostgreSQLRunRepository`、`PostgreSQLAuditRepository`、
  `PostgreSQLArtifactStore`、`PostgreSQLEventPublisher`、`PostgreSQLJobQueue`；
- `PostgreSQLUnitOfWork` / `PostgreSQLUnitOfWorkFactory`：一个连接、一个事务、五个仓储共享；
- 事务型 Outbox 的**写入侧**：`publish` 与业务写入同事务提交；
- 数据库内任务租约（`FOR UPDATE SKIP LOCKED`）与状态转换；
- 行恢复（hydration）：五类领域对象的确定性重建；
- SQLSTATE/约束名到既有 `ENT-*` 错误码的稳定映射。

**未实现（T82 之外）**

- 事件投递器（dispatcher）、Kafka 生产者/消费者、exactly-once 投递；
- worker 服务、心跳、租约超时回收、重试调度；
- HTTP API、RBAC、多租户、审计查询接口；
- 生产备份、高可用、只读副本；
- **默认应用接入**：`app.py`、`pages/`、Streamlit 入口与 T76 启动器都不导入该适配器。

## 2. 文件与模块

```
steelai/enterprise_lab/adapters/postgresql/
    _context.py      # PostgreSQLContext：单连接/单事务生命周期、advisory lock 入口
    _locks.py        # 稳定 SHA-256 派生的 advisory lock 键（含 SteelAI/T82 命名空间）
    errors.py        # SQLSTATE + constraint_name → ENT-* 映射，脱敏
    hydration.py     # 行 → 领域对象（五类），时间戳归一化与 payload 白名单复检
    repositories.py  # 五个 Repository + PostgreSQLUnitOfWork + Factory
    __init__.py      # 可选边界入口（导出上述实现）
tests/
    test_t82_postgresql_repositories.py    # 离线契约测试（57 项）
    test_t82_postgresql_integration.py     # 真实 PostgreSQL 场景（22 项）
```

被修改但**未改逻辑**的既有文件：`steelai/enterprise_lab/application/services.py` 中
`UnitOfWorkFactory` 的 docstring 由 "T81 replaces…" 改为 "T82 replaces…"。

## 3. UnitOfWork 生命周期与连接所有权

| 阶段 | 行为 |
| --- | --- |
| `factory.unit_of_work()` | 只创建对象；不连接；`committed == False` |
| 进入 `with` 边界 | `engine.connect()` + `begin()`；此时才检出连接 |
| 仓储调用 | 每次调用重新校验"该 UoW 仍是活动事务"，否则 `ENT-UOW-001` |
| `commit()` | 提交事务、归还连接、`committed = True`（永久，属于该 UoW 自身） |
| `rollback()` | 回滚事务、归还连接、`rolled_back = True` |
| 未给出结果就离开 `with` | **一律回滚**，因此异常退出不留部分写入 |
| 边界结束后使用旧句柄 | 五个句柄的读写全部 `ENT-UOW-001` |
| 进入 `with` 之前调用 `commit()`/`rollback()` | `ENT-UOW-001`（没有已 start 的活动事务） |
| `connect()` 成功但 `begin()` 失败 | 立即关闭该连接并抛脱敏 `ENT-DB-001` |
| `commit()` 失败 | 立即尝试 rollback、关闭连接、标记边界已关闭、只抛脱敏 `ENT-DB-001` |
| `commit()` 失败且 rollback 也失败 | 不掩盖原 commit 异常；连接仍被关闭 |
| **显式 `rollback()` 失败** | `rolled_back=False`，仍关闭连接与边界，抛脱敏 `ENT-DB-001`（不静默成功） |
| **正常离开未 commit 的 `with`、自动 rollback 失败** | 抛脱敏 `ENT-DB-001`（不静默成功），连接与边界均已关闭 |
| `with` 内已有异常、自动 rollback 也失败 | 保留原始业务异常，连接仍被关闭（rollback 失败不掩盖原异常） |
| 句柄生命周期优先于参数校验 | 已关闭 UoW 的保存句柄即使传入不匹配的 `idempotency_key`，也先返回 `ENT-UOW-001`（PostgreSQL 与 Memory 一致） |
| advisory lock 失败 | 经同一 SQLSTATE/约束名映射转为脱敏 `ENT-DB-*`，不泄露语句、参数、URL 或驱动文本 |

Factory 只接受显式注入的 Engine；`describe()` 只返回驱动名与数据库名，不含主机、用户或密码。模块导入
不连接数据库，也没有全局 Engine/Connection/Session。

## 4. 具体实现要点

**幂等（RunRepository / ArtifactStore / JobQueue）**

```sql
INSERT INTO steelai_enterprise.workflow_runs (...) VALUES (...)
ON CONFLICT (run_id) DO NOTHING
RETURNING *;
```

以**是否返回行**判断是否插入成功（该语句形状下 psycopg 报告 `rowcount == -1`，不能用行数判断）。
未插入时重新读取并判定：内容与绑定一致 → `reused=True`；否则 `ENT-IDEMPOTENCY-001` /
`ENT-ARTIFACT-001`。冲突在任何下游副作用之前关闭式失败。

`create_run` 还**先**校验参数 `idempotency_key` 等于 `run.idempotency_key`：不一致时在**任何 SQL 之前**
返回 `ENT-IDEMPOTENCY-001`（Memory 适配器同步修正）。`ArtifactStore.register` 只在**全部持久化字段**
（`artifact_id`、`relative_path`、`sha256`、`artifact_type`、`artifact_version`、`run_id`、`created_at`）
完全相同时才算复用；任一不同（包括只有 `created_at` 不同）返回 `ENT-ARTIFACT-001`，因此派生 ID 相同
但内容不同的引用不会被误判为重放。

**乐观并发（update_run_state）**

```sql
UPDATE steelai_enterprise.workflow_runs SET ... , revision = revision + 1
WHERE run_id = :run_id AND revision = :expected_revision
RETURNING *;
```

0 行时按"运行不存在"（`ENT-NOTFOUND-001`）或"修订已变化"（`ENT-CONCURRENCY-001`）区分。

**Advisory lock**

```sql
SELECT pg_advisory_xact_lock(:key);
```

`key = int.from_bytes(sha256("steelai-t82-enterprise-lab" + scope + identity)[:8])`，只有**两种**作用域：
全局审计序号、per-run outbox 序号。任务租约**不使用** advisory lock（见下）。命名空间的作用是**降低**
与其他应用在同一 advisory lock 空间意外碰撞的概率，不声称"绝不可能碰撞"。**不使用 `hash()`**；
离线测试在子进程中验证键稳定。

**审计序号**

`count()` 与 `append()` 都先取同一把事务级锁，再 `coalesce(max(sequence), 0) + 1`。因此两个并发事务
各自 "`count() + 1` → `append`" **都会成功**，得到 1、2；正常并发写入不需要调用方重试。仅当调用方
**直接提交**陈旧或乱序序号时才以 `ENT-AUDIT-001` 关闭式失败。并发下即使应用逻辑出错，
`trg_audit_events_append_only` 仍拒绝 UPDATE/DELETE。

**Outbox 序号**

`next_sequence(run_id)` 与 `publish(event)` 取同一把 per-run 锁，且都在读取最大值**之前**取锁：
两个并发事务各自 "`next_sequence()` → `publish`" **都会成功**，得到 1、2；**直接提交**重复或乱序序号
仍以 `ENT-EVENT-001` 关闭式失败。

**任务租约**

```sql
SELECT * FROM steelai_enterprise.background_jobs
WHERE state IN ('queued','retrying')
ORDER BY created_at, job_id LIMIT 1
FOR UPDATE SKIP LOCKED;
```

只依赖 `FOR UPDATE SKIP LOCKED`，不加任何全局 advisory lock：两个重叠事务各自租到**不同**任务；只有一个
任务可用时，第二个事务**立即**得到 `None`（跳过被锁行，不等待第一个事务提交）。`complete`/`fail`/
`retry`/`cancel` 一律先 `SELECT ... FOR UPDATE` 锁定目标行，再把 T80 的 `BackgroundJob.transition`
作用于锁内读到的最新状态；`retry` 的 attempts 上限判断同样在锁内，**没有**锁外的重复预检查。同一个
leased 任务上并发 `complete` 与 `fail` 只有一个成功，另一方以 `ENT-JOB-001` 关闭式失败。不另造状态机。

**错误映射**

唯一约束 → `ENT-IDEMPOTENCY-001` / `ENT-ARTIFACT-001` / `ENT-EVENT-001` / `ENT-AUDIT-001`；
外键 → `ENT-NOTFOUND-001`；CHECK（含 `relative_path_posix`）→ 对应业务码或 `ENT-DB-002`；
trigger `23001` → 审计码；序列化失败 → `ENT-DB-004`；缺表 → `ENT-DB-005`；未分类 → `ENT-DB-001`。
只按 SQLSTATE 与 `constraint_name` 判定，异常只带 `sqlstate`/`constraint`/`error_type`。

## 5. 真实 PostgreSQL 验收

| 项目 | 值 |
| --- | --- |
| 镜像 | `postgres:18.6-alpine3.23`（`sha256:697c180dbf244d3ce4a8f4cbc0156cde840af055c1bf8b76aebe422a4822086f`，`amd64/linux`） |
| 容器 | `steelai-t82-postgres-test`，标签 `com.steelai.task=T82`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，`RestartPolicy=no`，无 volume |
| 端口 | `127.0.0.1:55468 → 5432`（loopback-only） |
| 数据库/用户 | `steelai_enterprise_test` / `steelai_t82_test`（密码运行时随机生成，验收后销毁） |
| 前置 | 空库执行 T81 `alembic upgrade head` 后再运行 T82 验收 |

场景结果（22 项全部通过）：

| # | 场景 | 结果 |
| --- | --- | --- |
| 1 | `EnterpriseWorkflowService` 使用 PostgreSQL Factory 完成完整纵向流程 | 通过 |
| 2 | run/artifact/audit/outbox 在同一 commit 后同时可见（outbox 行为 `pending`/`attempts=0`） | 通过 |
| 3 | 在四个写入阶段注入异常，回滚后五张表计数恢复基线 | 通过 |
| 4 | 未提交数据对第二连接不可见，commit 后可见 | 通过 |
| 5 | 完全相同请求重放不增加记录且返回原 ID | 通过 |
| 6 | 同幂等键不同请求并发竞争：恰好一个成功，另一个 `ENT-IDEMPOTENCY-001`，无部分写入 | 通过 |
| 6b | `idempotency_key` 参数与 run 自身键不一致：在任何 SQL 写入前 `ENT-IDEMPOTENCY-001`，五张表计数不变 | 通过 |
| 6c | 直接构造的同 `artifact_id` 不同内容引用：`ENT-ARTIFACT-001`；完全一致时才 `reused=True` | 通过 |
| 7 | 两个并发状态更新：一个成功，另一个 `ENT-CONCURRENCY-001`，修订最终为 2 | 通过 |
| 8 | 四个重叠审计写入全部成功，序号 1,2,3,4 唯一且连续（无需重试） | 通过 |
| 8b | 两个重叠事务各自 `count()+1` → `append`：**都成功**，序号 1、2 | 通过 |
| 8c | 直接提交陈旧 (1) / 跳跃 (5) 序号：`ENT-AUDIT-001` / `ENT-EVENT-001`，无写入 | 通过 |
| 9 | 两个重叠事务各自 `next_sequence()` → `publish`：**都成功**，序号 1、2 | 通过 |
| 9b | 顺序追加 outbox 得到 1,2,3 | 通过 |
| 10 | 两个重叠事务加 Barrier 后各持一个不同任务（证明租约真的重叠） | 通过 |
| 10b | 仅一个任务可用时，第二个事务在第一个事务提交**之前**立即得到 `None` | 通过 |
| 11 | 同一 leased 任务并发 `complete` 与 `fail`：只有一个成功，另一方 `ENT-JOB-001`，胜者结果未被覆盖 | 通过 |
| 11b | `retry` 达到 attempts 上限时以 `ENT-JOB-001` 关闭式失败，状态与 attempts 不变 | 通过 |
| 12 | commit 与 rollback 后五类句柄全部 `ENT-UOW-001` | 通过 |
| 13 | audit UPDATE/DELETE 仍被 trigger 拒绝（SQLSTATE `23001`） | 通过 |
| 14 | 仓储返回领域对象（`WorkflowRun`/`BackgroundJob`），不是 Row/Mapping | 通过 |
| 15 | 连接归还连接池，无 `idle in transaction` 遗留 | 通过 |

并发测试使用有界线程池、`threading.Barrier` 与 join 超时，失败不会无限等待。Barrier 只在**并发段开始前**
设置：任何"一方已持锁、另一方必须到达同一 Barrier"的写法都会制造测试自身的死锁，因此不予采用。

补充证据（离线契约测试 `tests/test_t82_postgresql_repositories.py`，**57 passed + 38 subtests**）：UoW
失败生命周期（connect / begin / commit / 显式 rollback / 正常退出自动 rollback / 异常退出时的 rollback 失败）、
advisory lock 失败脱敏、生命周期优先于参数校验（PostgreSQL 与 Memory）、键不一致零 SQL、直接构造的
artifact 冲突。两轮契约修正后复跑：T81 schema **28 passed**、T81 migrations **26 passed + 0 skipped**、
T80 回归 **74 passed**、Streamlit pages **5 passed**、全量 `.\scripts\test.ps1` **524 passed、8 skipped、
213 subtests、0 failed**、`git diff --check` exit 0。

## 6. 复现命令

```powershell
$env:STEELAI_TEST_DATABASE_URL = "postgresql+psycopg://<user>:<pw>@127.0.0.1:55468/steelai_enterprise_test"
$env:STEELAI_ENTERPRISE_DATABASE_URL = $env:STEELAI_TEST_DATABASE_URL
$env:STEELAI_ENTERPRISE_TEST_DATABASE_ONLY = '1'

.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t82_postgresql_repositories.py
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t82_postgresql_integration.py
```

未设置 `STEELAI_TEST_DATABASE_URL` 时集成测试明确 skip；离线测试不需要数据库。

## 7. 未完成项与遗留（T82 转为 `Done` 不改变以下边界）

1. 无 dispatcher 与 Kafka：`outbox_events` 只有写入侧，**不得**声称事件已投递或 exactly-once；
2. 无 worker：`leased` 行不会因心跳缺失而自动回收，需要后续任务补齐；
3. 正常并发取号**不会**关闭式失败（锁会串行化等待）；只有直接提交陈旧/乱序序号才会 `ENT-AUDIT-001` /
   `ENT-EVENT-001`，T82 不提供调用方重试循环，因为没有可重试的正常路径；
4. 全局审计序号是单点锁，写入量大时需要重新评估分段或序列方案；
5. `outbox_events` 与 `audit_events` 无归档/保留策略；
6. 只在 PostgreSQL 18.6 单实例验证，未覆盖其他主版本、复制、PgBouncer 或托管服务；
7. `projects` 表与 `ProjectRepository` 仍未建立，`project_id` 仍是外部标识；
8. 没有 `IntegrityError` 之外的重试/退避机制，也没有可观测性（指标、追踪、结构化日志）。
