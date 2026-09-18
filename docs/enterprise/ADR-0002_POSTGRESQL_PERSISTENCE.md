# ADR-0002 PostgreSQL 持久化基线

- 状态：`accepted`（2026-09-17 经真实 PostgreSQL 18.6 集成验收与 Codex 最终复核后接受；T81 同步转为 `Done`）
- 日期：2026-09-17
- 决策范围：Enterprise Lab 的 PostgreSQL 持久化基线（Schema、迁移、连接配置、映射契约）
- 相关任务：T80（可选扩展骨架，已 Done）；T81（本 ADR 的引入者，Schema/迁移基线，已 Done）；T82（待开始：PostgreSQL Repository/UnitOfWork）
- 相关文档：`docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md`、`docs/enterprise/T81_POSTGRESQL_PERSISTENCE_BASELINE.md`

## 1. 背景

T80 冻结了 Enterprise Lab 的领域模型、Ports、内存适配器和事务/幂等契约，并明确 PostgreSQL 未来只承载
业务元数据。T81 建立第一版可执行的 PostgreSQL 基础：专用 Schema、五张业务表、一个可 upgrade/downgrade
的 Alembic 迁移、显式连接配置边界，以及领域对象到表的映射契约。

T81 **不实现** PostgreSQL Repository 或 UnitOfWork，不接入默认应用，不实现 worker、dispatcher、Kafka 或 API。

## 2. 决策

### 2.1 使用 SQLAlchemy Core，而不是 ORM

- 表结构用 `sqlalchemy.MetaData` + `Table`/`Column` 声明（Core），不使用 `declarative_base`。
- 领域对象保持普通 frozen dataclass，不被 ORM 基类、`relationship`、会话或延迟加载污染。
- 行构造是纯函数（`adapters/postgresql/mapping.py`），领域对象 → 列字典，由 T82 复用来执行 INSERT。

理由：领域模型是 T80 的冻结契约；ORM 映射会把数据库关注点带进领域层，并让"运行状态必须复用 T50/T51
GovernanceState"这类约束难以在类型层面保证。

### 2.2 使用 Psycopg 3，同步驱动

- 连接串必须显式选择 `postgresql+psycopg://`，否则关闭式失败（`ENT-DB-CONFIG-003`）。
- 不引入 psycopg2、asyncpg 或任何异步栈：T80/T81 的 UnitOfWork 契约是同步的，引入异步会造出第二套事务语义。
- Windows 本地开发安装 `psycopg[binary]`，避免本地编译 libpq，也不需要安装 PostgreSQL 客户端。

### 2.3 使用 Alembic，初始迁移手写并完全冻结

- `alembic-enterprise.ini` 不保存任何连接串；`migrations/enterprise/env.py` 从
  `STEELAI_ENTERPRISE_DATABASE_URL` 或显式覆盖读取。
- Alembic version table 固定为 `steelai_enterprise.alembic_version_enterprise`，与其他工具隔离。
- revision id 必须不超过 version table 的 `version_num VARCHAR(32)` 宽度，当前为
  `0001_enterprise_baseline`（24 字符）。
- 初始迁移 `0001_enterprise_baseline` 为**手写、复核并完全冻结**：
  - 只导入 `__future__`、标准库、`alembic`、`sqlalchemy` 与 `sqlalchemy.dialects.postgresql`；
  - **不导入任何 `steelai.*` 模块**，既不导入 live `schema`，也不导入 `constraints`，也不导入 `domain`；
  - naming convention、约束名、SHA/content digest 正则、`GovernanceState`/`ResultLevel`/`EvidenceClass`/
    `JobState` 的 T81 基线字面量、delivery status、relative_path CHECK SQL、audit trigger/function 名称与
    SQL 全部在 revision 内部冻结；
  - 五张表的列、主键、外键、唯一约束与 CHECK 约束全部显式声明，不使用任何运行时 `Table`/`MetaData` 对象。
- 因此修改 live 契约模块**不会**改变历史 revision 的 DDL；T81 基线的任何变化都必须新增一个 revision。
- live 侧 `schema.py` 继续使用 `constraints.py`，运行时代码不依赖 migration。
- 每个 DDL 元素都显式传给 Alembic，因此 `upgrade --sql` 离线生成仍然可用；离线输出中
  `CREATE SCHEMA` 必须排在 `CREATE TABLE ...alembic_version_enterprise` 之前（由 `env.py` 的离线
  分支显式输出），否则在全新数据库上无法执行。
- 不接受未经检查的 autogenerate 输出；`compare_type`/`compare_server_default` 只用于让漂移可见。

### 2.4 专用 Schema，不与其他对象混放

- 所有表位于 `steelai_enterprise` Schema。
- 状态列一律使用字符串列 + 命名 CHECK 约束，**不使用 PostgreSQL 原生 ENUM**：原生 ENUM 的增删值需要
  独立的类型迁移，会把未来的状态变更与表迁移耦合，而 T50/T51 的状态机由治理契约而非数据库拥有。
- downgrade 不删除 `steelai_enterprise` Schema，只删除本迁移拥有的对象；Schema 可保留为空。

### 2.5 outbox-first

- `DomainEvent` 在数据库中映射为 Transactional Outbox 行（`outbox_events`）：`payload` 为 JSONB，
  投递状态独立于领域状态。
- T81 只建表与约束（唯一键 `(run_id, sequence)`、`payload` 必须是 JSON object、投递状态白名单、`attempts >= 0`、
  适合 dispatcher 轮询的索引）。
- **T81 不实现 dispatcher，不连接 Kafka，不声称 exactly-once。**
- 领域事件与业务写入同事务（真正的 outbox 语义）留到 T82：只有 PostgreSQL UnitOfWork 才能把
  "写运行 + 写 outbox"放进同一个数据库事务。

### 2.6 审计只追加由数据库强制

- `audit_events` 除主键外，`sequence` 全局唯一且 > 0。
- 初始迁移创建 `steelai_enterprise.fn_audit_events_reject_mutation()` 与
  `trg_audit_events_append_only`，对 `audit_events` 的 UPDATE/DELETE 直接抛
  `restrict_violation`。
- 应用层没有 update/delete 接口，数据库层再加一道，避免任何后来者绕过。

### 2.7 不创建 projects 表

- T80 有 `EnterpriseProject` 领域对象，但**没有** `ProjectRepository`，也没有 `UnitOfWork.projects`。
- 因此 T81 不建 `projects` 表、不静默自动创建项目、不新增无法通过 Port 访问的半实现项目仓储。
- `workflow_runs.project_id` 暂时作为"已经过领域校验的外部项目标识"，不建立外键。
- **ProjectRepository 缺口是 T82 开始前必须决定的问题**（见第 4 节）。

### 2.8 只存引用与哈希，不存科研数据

- `artifact_references` 只保存相对 POSIX 引用与 SHA-256；数据库中没有文件内容、没有绝对路径。
- 数据库中的 artifact 只是"一条引用 + 一个哈希"，**不代表审批通过、不代表证据已验收**。
- T81 不迁移、不重算、不覆盖任何科研 CSV、方法注册表或结果包。

### 2.9 连接配置边界

- 连接串只能来自函数显式参数或 `STEELAI_ENTERPRISE_DATABASE_URL`；没有默认值，没有用户名/密码/主机。
- 不读取也不写入 `.env`；不创建全局隐式 Session。
- 没有连接串时关闭式失败：`ENT-DB-CONFIG-001`。
- 任何 repr、异常、日志和测试输出都经过 `redact_database_url()`：用户名、密码、主机和查询串全部替换为标记。
- 启用 `pool_pre_ping`；模块导入时不连接数据库。

### 2.10 迁移目标安全闸门

- 迁移默认拒绝目标数据库名不同时包含 `steelai` 与 `test` 的库（`ENT-DB-CONFIG-004`）。
- 集成测试同时设置 `STEELAI_ENTERPRISE_TEST_DATABASE_ONLY=1`，把限制收紧到测试库。
- 专用开发库可通过显式 `STEELAI_ENTERPRISE_ALLOW_ANY_DATABASE=1` opt-in。
- 不安装 PostgreSQL 或 Docker，不自动寻找局域网数据库。

## 3. 与 T50/T51 治理的映射

| 治理对象 | 数据库中的位置 | 说明 |
| --- | --- | --- |
| `GovernanceState` 十状态 | `workflow_runs.state`（字符串 + CHECK） | 复用 T50/T51 词表，不新增第二套状态机 |
| `ResultLevel` / `EvidenceClass` | `workflow_runs.result_level` / `evidence_class` | 同样为字符串 + CHECK |
| `JobState` | `background_jobs.state` | 复用 T80/T51 任务状态词表 |
| `DomainEvent` | `outbox_events` 行 | `payload` 继续遵守 `DomainEvent` 脱敏白名单（只允许 ID/状态/版本/哈希/摘要字段） |
| `ApprovalSnapshot` | 不落库 | 审批仍由现有治理核心负责 |
| `GovernanceManifest` 与正式发布包 | 不落库 | CSV/Manifest/SHA-256 证据包继续是科研证据的唯一载体 |
| `ArtifactReference` | `artifact_references` 行 | 只是引用与哈希，不代表审批通过 |

另外：数据库故障、连接失败或迁移失败**不得**导致系统把模型输出升级为 `accepted_evidence`。
T81 没有改变任何判定逻辑；`workflow_runs` 的 CHECK 约束只允许既有词表取值。

## 4. 后果与代价

正面结果：企业化扩展有了可执行的 Schema 与迁移基线；连接配置、脱敏与迁移安全闸门有明确规则；
领域模型、内存适配器与默认应用完全不受影响；T82 有稳定的表结构与映射契约可以接。

代价与风险：

- 数据库 Schema 现在是一个需要维护的契约：状态词表变化必须同时改 `models.py` 与一个新迁移；
- `outbox_events` 只有表，没有投递语义；在 T82 补上 outbox 事务之前，不得声称事件投递可靠；
- 审计 append-only 只由 trigger 保证，还没有处理"批量维护窗口"的运维流程；
- 迁移执行只在 PostgreSQL 18.6 / Alpine / 单实例容器上验证过，未覆盖其他主版本、集群、复制或托管服务；
- 验收容器使用 `--tmpfs`，数据不持久，生产数据目录与备份策略仍未设计。

## 5. T82 开始前必须决定的问题

1. **ProjectRepository 是否加入 Ports**：加入则新增 `projects` 表与外键，不加入则 `project_id` 长期是外部标识；
2. **全局 audit sequence 的并发分配**：`audit_events.sequence` 当前全局唯一；T82 需要决定用序列、
   咨询锁还是"每运行序号 + 全局序号"两列；
3. **per-run outbox sequence 的并发分配**：`(run_id, sequence)` 唯一，需要决定同事务内的分配方式，
   避免并发写入重试；
4. **PostgreSQL UoW 生命周期**：决定 Session/事务的作用域、提交点、以及 T80 单写者守卫是否也要在数据库中体现；
5. **IntegrityError → DomainError 的稳定映射**：把唯一约束、CHECK、外键冲突映射到
   `ENT-IDEMPOTENCY-001`、`ENT-REVISION-CONFLICT`、`ENT-ARTIFACT-CONFLICT` 等既有错误码；
6. **T51 manifest/approval 只引用还是进一步规范化**：决定是否把 `publication_id`/`approval_id` 只存为
   引用字符串，还是建立受治理的规范化表。

## 6. 验收与范围边界

真实 PostgreSQL 18.6 上的 `upgrade → downgrade → upgrade` 已于 2026-09-17 实测通过（官方精确镜像
`postgres:18.6-alpine3.23`，一次性容器，详见 `docs/enterprise/T81_POSTGRESQL_PERSISTENCE_BASELINE.md`
第 5.1 节）：35 个命名约束、8 个业务索引、audit trigger/function 实测存在；SQLSTATE `23514`、`23505`、
`23001` 实测；集成测试 26 passed + 0 skipped。六个集成测试仍只在显式提供 `STEELAI_TEST_DATABASE_URL`
（库名同时包含 `steelai` 与 `test`）时运行，未提供时明确 skip。

本 ADR 与 T81 的范围**不含** PostgreSQL Repository、UnitOfWork、outbox dispatcher、worker、Kafka、API、
RBAC 与多租户；这些属于 T82 及以后。因此 T81 虽已完成并转为 `Done`，也**不得**写成
"PostgreSQL 持久化适配器已完成"。
