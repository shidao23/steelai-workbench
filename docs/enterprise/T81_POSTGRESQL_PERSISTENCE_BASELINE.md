# T81 PostgreSQL 持久化基线

- 状态：`Done`（Schema、离线迁移、**真实 PostgreSQL 18.6 验收**与 Codex 最终复核均已完成；ADR-0002 同步为 `accepted`）
- 日期：2026-09-17
- 边界决策：`docs/enterprise/ADR-0002_POSTGRESQL_PERSISTENCE.md`
- 前置任务：T80（Enterprise Lab 骨架，Done）
- 范围：PostgreSQL Schema、Alembic 初始迁移、连接配置边界、领域↔表映射契约
- **不属于本任务**：PostgreSQL Repository、UnitOfWork、worker、outbox dispatcher、Kafka、API、RBAC、多租户

## 1. 依赖与安装边界

| 组件 | 版本 | 理由 |
| --- | --- | --- |
| SQLAlchemy | `2.0.54` | 2.0 稳定线最新版；只用 Core，不使用 ORM 基类 |
| Alembic | `1.20.0` | 稳定版迁移工具；version table 可指定 schema |
| psycopg[binary] | `3.3.5` | Psycopg 3 + Windows 预编译 wheel，无需本地编译 libpq |
| 传递依赖 | Mako `1.4.1`、greenlet `3.5.6` | Alembic/SQLAlchemy 带入，已用 `pip check` 验证一致 |

- 全部为精确锁定、正式稳定版本，无预发布版。
- 这些依赖**只**写在 `requirements-enterprise.txt`；`requirements.txt` / `requirements-dev.txt` 未修改。
- 未安装：psycopg2、asyncpg、FastAPI、Kafka、Redis、Celery、OpenTelemetry、Testcontainers、pytest-postgresql。
- **未在 Windows 宿主机安装 PostgreSQL**；真实验收使用项目负责人已恢复运行的 Docker Desktop 与一次性
  PostgreSQL 容器。Docker Desktop/PostgreSQL 不进入 SteelAI 默认依赖，验收容器已删除，官方镜像按授权保留。

## 2. 代码与文件布局

```
steelai/enterprise_lab/adapters/postgresql/
    __init__.py     # 可选边界入口（导入即需要 SQLAlchemy/Psycopg）
    config.py       # 显式配置、URL 脱敏、Engine 工厂
    constraints.py  # live 侧纯常量与 SQL 文本生成函数（无 SQLAlchemy 对象）
    schema.py       # live SQLAlchemy Core Metadata（五张表、约束、索引）
    mapping.py      # 领域对象 → 表/列 映射契约 + 纯函数行构造器
migrations/enterprise/
    env.py          # 只从 STEELAI_ENTERPRISE_DATABASE_URL 解析 URL + 迁移目标闸门 + 离线 schema 前置输出
    script.py.mako
    versions/0001_enterprise_baseline.py   # 手写、复核、完全冻结的初始迁移
alembic-enterprise.ini
requirements-enterprise.txt
tests/test_t81_postgresql_schema.py
tests/test_t81_postgresql_migrations.py
```

冻结迁移规则：`0001_enterprise_baseline` **不导入任何 `steelai.*` 模块**，只允许 `__future__`、标准库、
`alembic`、`sqlalchemy` 与 `sqlalchemy.dialects.postgresql`。naming convention、约束名、SHA/content digest
正则、`GovernanceState`/`ResultLevel`/`EvidenceClass`/`JobState` 的 T81 基线字面量、delivery status、
relative_path CHECK SQL、audit trigger/function 名称与 SQL **全部在 revision 文件内部冻结**，五张表的列与
约束同样显式声明。因此修改 `constraints.py`、`schema.py` 或 `domain.models` 都不会改变历史 revision 的 DDL；
契约变化必须新增 revision。revision id 为 24 字符，不超过 version table 的 `version_num VARCHAR(32)` 宽度。

live 侧（`schema.py` + `constraints.py`）供 T82 与测试使用，**运行时代码不依赖 migration**。

隔离规则：`domain`、`application`、`ports` 禁止导入 SQLAlchemy/Alembic/Psycopg；
`steelai/enterprise_lab/__init__.py` 与 `adapters/__init__.py` **不**导入 PostgreSQL 包；
没有安装可选依赖时，现有 SteelAI 与 T80 内存适配器照常导入。

## 3. Schema 与表结构

Schema：`steelai_enterprise`。共五张业务表，不迁移任何科研 CSV、原始实验值、模型权重或大文件。

### 3.1 workflow_runs

| 列 | 类型 | 说明 |
| --- | --- | --- |
| run_id | text PK | 稳定运行 ID |
| project_id | text | 经过领域校验的外部项目标识（无外键，见 ADR-0002 §2.7） |
| task_id | text | 任务标识 |
| state | text | T50/T51 `GovernanceState` 十值 |
| revision | int | ≥ 1 |
| content_digest | text | `run_<hex>` 内容摘要格式 |
| result_level | text | `ResultLevel` 六值 |
| evidence_class | text | `EvidenceClass` 四值 |
| idempotency_key | text UNIQUE | 幂等绑定 |
| request_digest | text | 小写 64 位 SHA-256 |
| created_at / updated_at | timestamptz | 带时区 |
| created_by | text | 责任身份 |
| next_action | text | 脱敏描述 |

约束：`pk_workflow_runs`、`uq_workflow_runs_idempotency_key`、
`ck_workflow_runs_request_digest_lowercase_hex`、`ck_workflow_runs_content_digest_format`、
`ck_workflow_runs_state_declared`、`ck_workflow_runs_result_level_declared`、
`ck_workflow_runs_evidence_class_declared`、`ck_workflow_runs_revision_positive`。
索引：`ix_workflow_runs_project_id`、`ix_workflow_runs_task_id`、`ix_workflow_runs_state`、`ix_workflow_runs_created_at`。

### 3.2 artifact_references

`artifact_id` PK、`run_id` FK → `workflow_runs.run_id`（**RESTRICT，无级联**）、`relative_path` UNIQUE、
`sha256`、`artifact_type`、`artifact_version`、`created_at`。
约束：`ck_artifact_references_sha256_lowercase_hex`、`ck_artifact_references_relative_path_posix`
（拒绝绝对路径、反斜杠、盘符、裸 `.` 与 `..`、任意 `.`/`..` 路径段、空段与 `//`）、
`uq_artifact_references_relative_path`。
索引：`ix_artifact_references_run_id`。只存引用与哈希，不存文件内容。

### 3.3 audit_events

`audit_id` PK、`sequence` UNIQUE > 0、`run_id` FK、`action`、`actor_role`、`actor_id`、`summary`、
`occurred_at`、`object_type`、`object_id`、`object_revision`、`object_digest`。
约束：`uq_audit_events_sequence`、`ck_audit_events_sequence_positive`、`ck_audit_events_revision_positive`、
`ck_audit_events_object_digest_format`。索引：`ix_audit_events_run_id`。
只追加：触发器 `trg_audit_events_append_only` 调用
`steelai_enterprise.fn_audit_events_reject_mutation()`，对 UPDATE 与 DELETE 抛 `restrict_violation`。

### 3.4 outbox_events

`event_id` PK、`event_type`、`run_id` FK、`sequence`、`payload` JSONB、`occurred_at`、
`delivery_status`（默认 `pending`）、`attempts`（默认 0）、`available_at`、`published_at`（可空）、
`last_error_code`（可空）。
约束：`uq_outbox_events_run_id_sequence`、`ck_outbox_events_sequence_positive`、
`ck_outbox_events_delivery_status_declared`（`pending`/`publishing`/`published`/`failed`）、
`ck_outbox_events_payload_is_json_object`（`jsonb_typeof(payload) = 'object'`）、
`ck_outbox_events_attempts_non_negative`。
索引：`ix_outbox_events_delivery_status_available_at`（供未来 dispatcher 轮询 pending）。
T81 只建表：无 dispatcher、无 Kafka、不声称 exactly-once；"事件与业务同事务"留到 T82。

### 3.5 background_jobs

`job_id` PK、`job_type`、`run_id` FK、`state`（T80 `JobState` 六值）、`attempts`、`max_attempts`、
`idempotency_key` UNIQUE、`request_digest`、`payload_digest`、`created_at`、`updated_at`、
`lease_id`（可空）、`error_code`（可空）。
约束：`ck_background_jobs_request_digest_lowercase_hex`、`ck_background_jobs_payload_digest_lowercase_hex`、
`ck_background_jobs_state_declared`、`ck_background_jobs_attempts_positive`（≥1）、
`ck_background_jobs_max_attempts_positive`（≥1）、`ck_background_jobs_attempts_within_limit`（attempts ≤ max_attempts）。
索引：`ix_background_jobs_state_created_at`（未来租约查询的最小必要索引）。
T81 不实现 worker、租约并发、`SKIP LOCKED` 或重试调度。

### 3.6 命名约定

`MetaData` 使用确定性命名约定，所有 PK/FK/UNIQUE/CHECK/索引名稳定：
`pk_<table>`、`fk_<table>_<column>_<referred>`、`uq_<table>_<columns>`、`ck_<table>_<check_name>`、
`ix_<table>_<columns>`。

## 4. 环境变量与运行方式

| 变量 | 用途 |
| --- | --- |
| `STEELAI_ENTERPRISE_DATABASE_URL` | 迁移与应用使用的连接串（必须 `postgresql+psycopg://`） |
| `STEELAI_TEST_DATABASE_URL` | 仅集成测试读取；库名必须同时包含 `steelai` 与 `test`，否则跳过 |
| `STEELAI_ENTERPRISE_TEST_DATABASE_ONLY=1` | 集成测试设置，把迁移限制到测试库 |
| `STEELAI_ENTERPRISE_ALLOW_ANY_DATABASE=1` | 专用开发库的显式 opt-in（默认拒绝其他库名） |

```powershell
# 迁移（需要先设置 STEELAI_ENTERPRISE_DATABASE_URL）
.\.venv\Scripts\python.exe -m alembic -c alembic-enterprise.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c alembic-enterprise.ini current
.\.venv\Scripts\python.exe -m alembic -c alembic-enterprise.ini downgrade base

# 离线 SQL（不需要数据库，也不会连接）
.\.venv\Scripts\python.exe -m alembic -c alembic-enterprise.ini upgrade head --sql
.\.venv\Scripts\python.exe -m alembic -c alembic-enterprise.ini downgrade 0001_enterprise_baseline:base --sql
```

downgrade 行为：按依赖逆序 `DROP TRIGGER` → `DROP FUNCTION` → `DROP TABLE`（background_jobs、outbox_events、
audit_events、artifact_references、workflow_runs）；不含 `CASCADE`、不含 `DROP DATABASE`、不删除
`steelai_enterprise` Schema、不触碰任何科研路径。

## 5. 测试方法

```powershell
# 离线（无需数据库）
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t81_postgresql_schema.py
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t81_postgresql_migrations.py

# 真实 PostgreSQL 集成（需要安全测试库；否则对应测试明确 skip）
$env:STEELAI_TEST_DATABASE_URL = "postgresql+psycopg://<user>:<pw>@<host>:5432/steelai_enterprise_test"
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t81_postgresql_migrations.py
```

离线覆盖：五张表与所属 Schema、全部约束/索引稳定命名、关键 CHECK 语义（含裸 `.`、`..`、`./a`、
`a/../b`、`a//b` 路径拒绝）、映射完整性（领域字段全覆盖、基础设施列仅限 outbox）、URL 脱敏（含特殊字符
密码）、缺失环境变量关闭式失败、离线 SQL 生成与 `CREATE SCHEMA` 早于 version table 的顺序断言、
revision id 不超过 `version_num VARCHAR(32)`、downgrade 无破坏性语句、`import app` 不引入数据库框架、
内层无数据库框架依赖、科研目录哈希不变。

冻结专项覆盖：AST 断言 `versions/*.py` 不导入 `steelai.*`（含 live `schema`、`constraints`、`domain`）且不
访问运行时 `Metadata`/`Table`，也不调用共享 SQL 生成函数；冻结字面量与声明的 T81 基线值逐项比对；
冻结 relative_path 谓词按字面语义断言（不依赖 live 函数等值）；每张表的列数、主键与 CHECK 名称清单；
以及**隔离探针**——在内存中把 `constraints` 的常量、约束名与全部 SQL 生成函数替换为不同实现后重新加载
revision，其列、约束与 SQL 必须逐字节不变。

集成覆盖（`STEELAI_TEST_DATABASE_URL`）：base→head、五张表/约束/索引/trigger 检查、
非法 SHA/非法状态/重复幂等键/非法 revision 被拒（每个非法变体使用独立 `run_id` 与 `idempotency_key`，
并断言具体 SQLSTATE：CHECK 为 `23514`、唯一约束为 `23505`、audit 只追加为 `23001`）、
audit UPDATE 与 DELETE 被 trigger 拒绝、downgrade→base、再次 upgrade、`alembic current` 与 `head` 一致、
仅写入公开合成元数据。

## 5.1 真实 PostgreSQL 验收结果（2026-09-17）

| 项目 | 值 |
| --- | --- |
| 镜像 | `postgres:18.6-alpine3.23`（官方，精确标签） |
| Image ID / RepoDigest | `sha256:697c180dbf244d3ce4a8f4cbc0156cde840af055c1bf8b76aebe422a4822086f`（两值一致，且与 Docker Hub 官方 manifest index digest 相同） |
| architecture | `amd64/linux` |
| PostgreSQL | `PostgreSQL 18.6 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit`，`SHOW server_version = 18.6` |
| 容器 | `steelai-t81-postgres-test`，标签 `com.steelai.task=T81`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，无 named volume |
| 端口 | `127.0.0.1:55468 → 5432`（**偏差说明**：`55432` 落在 Windows 保留端口段 `55368-55467`，绑定被系统拒绝，故改用相邻的 `55468`；仍为 loopback-only，无 `0.0.0.0` 监听） |
| 数据库/用户 | `steelai_enterprise_test` / `steelai_t81_test`（密码运行时随机生成，未写入仓库或日志，验收后已销毁） |

migration 实测（每一步 exit code 0）：

| 步骤 | 结果 |
| --- | --- |
| `alembic upgrade head` | `Running upgrade  -> 0001_enterprise_baseline` |
| `alembic current` | `0001_enterprise_baseline (head)` |
| `alembic heads` | `0001_enterprise_baseline (head)` |
| `alembic downgrade base` | `Running downgrade 0001_enterprise_baseline ->` |
| 再次 `alembic upgrade head` | `Running upgrade  -> 0001_enterprise_baseline`，`current` 仍为 `0001_enterprise_baseline (head)` |

catalog 实测：`steelai_enterprise` Schema 存在；`alembic_version_enterprise` + 五张业务表存在；
**35 个命名约束全部存在**（21 个 CHECK + 5 个 PK + 5 个 FK + 4 个 UNIQUE，缺失清单为空）；
**8 个业务索引全部存在**；trigger `trg_audit_events_append_only` 与函数 `fn_audit_events_reject_mutation` 存在。

downgrade 实测：五张业务表计数 0、业务索引 0、trigger 0、function 0、依赖对象 0；
`current_database()` 仍为 `steelai_enterprise_test`（未删库）；Schema 保留为空；日志与 SQL 均无 `CASCADE`。

直接 SQLSTATE 探针（psql `VERBOSITY verbose`）：

| 场景 | 实测 | 约束名 |
| --- | --- | --- |
| audit UPDATE | `23001` | trigger `trg_audit_events_append_only` |
| audit DELETE | `23001` | trigger `trg_audit_events_append_only` |
| 重复幂等键 | `23505` | `uq_workflow_runs_idempotency_key` |
| 非法 request_digest（`NOTHEX`） | `23514` | `ck_workflow_runs_request_digest_lowercase_hex` |
| 未登记 state | `23514` | `ck_workflow_runs_state_declared` |
| `revision = 0` | `23514` | `ck_workflow_runs_revision_positive` |
| 非法 content_digest | `23514` | `ck_workflow_runs_content_digest_format` |
| 未登记 evidence_class | `23514` | `ck_workflow_runs_evidence_class_declared` |
| `relative_path` = `.` / `..` / `./a` / `a/../b` / `a//b` | `23514`（5 例全部拒绝） | `ck_artifact_references_relative_path_posix` |
| 合法相对路径 | 接受（`INSERT 0 1`） | — |

真实集成测试：`tests/test_t81_postgresql_migrations.py` 在设置安全测试 URL 后为
**26 passed, 0 skipped, 28 subtests passed**（6 项原 skip 的集成测试全部实际执行）。
未设置 `STEELAI_TEST_DATABASE_URL` 时仍为 20 passed + 6 skipped，即集成测试默认明确跳过。

**本次验收对非 schema/migration 代码的唯一修正**：`test_base_to_head_creates_every_declared_object` 中
`set(EXPECTED_TABLES) | {ALEMBIC_VERSION_TABLE}.issubset(tables)` 因运算符优先级把 `set | bool` 相加而抛
`TypeError`（这是测试代码缺陷，与 Schema/migration 无关）；已改为先求并集再 `issubset`。Schema、migration、
DDL、依赖与配置均未修改，修正后从空测试库重跑了完整验收。

## 6. T82 替换点

- `UnitOfWorkFactory.unit_of_work()` → PostgreSQL 事务（同一 Session/连接内完成 run + outbox 写入）；
- `RunRepository`：`create_run` 用 `idempotency_key` 唯一约束 + `request_digest` 比对实现幂等；
  `update_run_state` 用 `WHERE run_id=? AND revision=?` 实现乐观并发；
- `AuditRepository`：只用 INSERT，依赖 trigger 保护；
- `ArtifactStore`：只 INSERT 引用行，不接触文件；
- `EventPublisher`：与业务写入同事务写 `outbox_events`（outbox-first），投递器后置；
- `JobQueue`：`enqueue` 用 `idempotency_key` 唯一约束实现幂等；`lease` 留给 T82 之后的 worker 任务；
- 错误映射：IntegrityError → 既有 `ENT-*` 错误码（见 ADR-0002 §5）。

## 7. 未完成项与遗留

1. 真实 PostgreSQL 上的 upgrade/downgrade/upgrade **已在 18.6 单机容器上实测通过**（见 5.1），但只在
   PostgreSQL 18.6 / Alpine / 单实例环境下验证过，未覆盖其他主版本、集群、复制或托管服务；
2. 无 Repository / UnitOfWork / dispatcher / worker（T82 及以后）；
3. `projects` 表与 `ProjectRepository` 未建立，`project_id` 仍是外部标识；
4. 全局 audit sequence 与 per-run outbox sequence 的并发分配方式未定；
5. 尚无表空间、备份、权限与运维流程；
6. T81 未接入默认应用，也没有任何数据库开关或页面入口；
7. 验收容器使用 `--tmpfs`，数据不持久，验收结束即销毁；生产数据目录、持久化与备份策略仍未设计；
8. 本机 Docker Desktop 的内置代理对 Docker Hub 做 TLS 干涉，导致镜像无法直接 pull；本次镜像是项目负责人
   手动拉取后由本机校验（Image ID 与官方 manifest index digest 一致）的，该环境问题与本任务代码无关。
