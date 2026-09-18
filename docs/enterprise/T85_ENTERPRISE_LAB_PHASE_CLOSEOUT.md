# T85 Enterprise Lab 企业化演练阶段冻结与后续路线收口

- 状态：`Done`（Codex 最终复核通过，2026-09-18 由 `Review` 转为 `Done`）
- 日期：2026-09-18
- 完成日期：2026-09-18
- 文件路径（固定）：`docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`
- 任务性质：**纯文档任务**——只做能力总结、非生产边界、重新开启条件与后续路线，不新增任何运行能力
- 前置：T80、T81、T82、T83、T84 均已 `Done`；ADR-0001～ADR-0005 均已 `accepted`
- 决策依据：`docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md`、`ADR-0002_POSTGRESQL_PERSISTENCE.md`、`ADR-0003_POSTGRESQL_UNIT_OF_WORK.md`、`ADR-0004_OUTBOX_DISPATCHER.md`、`ADR-0005_BACKGROUND_JOB_WORKER.md`
- 相关看板：`TASKS.md` T80–T85；相关能力与限制：`docs/CURRENT_CAPABILITIES.md`、`docs/KNOWN_LIMITATIONS.md`、`docs/ARCHITECTURE.md`

## 0. 验收结论（2026-09-18）

- **Codex 最终复核通过**；
- **阶段能力地图、非生产边界、重新开启条件与后续路线均已完成**（见第 2–7 节）；
- **T80–T85 企业化演练阶段正式冻结**：T80–T84 全部 `Done`、ADR-0001～ADR-0005 全部 `accepted`、T85 由 `Review` 转为 `Done`；
- **当前测试基线沿用 T84 的 705 passed、8 skipped、358 subtests、0 failed**，本轮**未重新运行**任何测试、Docker、PostgreSQL 或 Streamlit；
- 冻结不改变第 4 节的否定边界：Enterprise Lab 仍只是可选参考实现，默认应用仍未接入，也不是生产平台。

## 1. 阶段目标与完成结论

**阶段目标**：在不改动既有科研链路、默认 Streamlit 应用与共享治理内核的前提下，验证"企业化架构所需的关键契约"是否可以在本仓库内被正确表达、实现并验收——即六边形边界、PostgreSQL Schema 与迁移、Repository/UnitOfWork、事务型 outbox、投递派发与后台任务执行。

**完成结论**：T80–T84 五个任务全部实现、全部通过真实验收、全部已被接受，**现在正式冻结**（T85 于 2026-09-18 经 Codex 最终复核转为 `Done`）。

- 该阶段验证的是**契约与边界**，不是交付一个生产平台；
- **ADR-0001～ADR-0005 作为本阶段的历史决策冻结**：它们记录了当时的取舍与边界，**不直接改写**；
- 未来重新开启企业化实施时（触发条件见第 5 节），应**创建新任务和新 ADR**，由**新 ADR 明确取代、修订或废止**既有决策——既有的五条 ADR 仍然保持 `accepted` 的历史状态，但其技术决策是否继续适用，由新 ADR 显式裁决，不做静默修改；
- 阶段冻结后，企业化实施**不再继续推进**，除非出现第 5 节列出的触发条件；
- 后续开发重心回到真实用户验收、科研功能与工程基线管理（见第 7 节）。

## 2. T80–T84 能力地图

| 任务 | 交付能力 | 关键产物 | 状态 | ADR |
| --- | --- | --- | --- | --- |
| T80 | 六边形架构边界与可替换接口骨架；内存纵向流程演示 | `enterprise_lab/{domain,application,ports,adapters}`、六个 `typing.Protocol` Port、纯内存适配器 | Done | ADR-0001（accepted） |
| T81 | PostgreSQL Schema、Alembic 迁移基线与显式连接配置 | `steelai_enterprise` 五张业务元数据表、`0001_enterprise_baseline`、`alembic-enterprise.ini`、`requirements-enterprise.txt` | Done | ADR-0002（accepted） |
| T82 | PostgreSQL Repository/UnitOfWork、事务型 outbox 写入侧、数据库内任务租约 | 五个 PostgreSQL 仓储、`PostgreSQLUnitOfWork`/Factory、SQLSTATE 脱敏映射 | Done | ADR-0003（accepted） |
| T83 | 有限调用式 outbox dispatcher（领取 → 事务外发送 → 确认/重试 → 过期租约恢复） | `ports/outbox.py`、`application/outbox_dispatcher.py`、内存投递适配器 + Recording Transport、PostgreSQL 投递适配器 | Done | ADR-0004（accepted） |
| T84 | 有限调用式 background job worker（领取 → 事务外执行 → 心跳 → 确认/重试 → 过期租约恢复） | `ports/workers.py`、`application/job_worker.py`、内存执行适配器 + Recording Handler、PostgreSQL 执行适配器 | Done | ADR-0005（accepted） |

按时间递进关系：T80 建立**接口与内存演示**；T81 建立**数据库基线与迁移**；T82 建立**同一事务内的真实写入链路**；T83 建立**事件投递侧**；T84 建立**任务执行侧**。后一任务只在前一任务已验收的边界之上补充能力，**没有回改** T80 的 Port 契约、T81 的 Schema/迁移或既有 ADR 决策。

## 3. 已验证内容（真实验收，不是设计声明）

- **PostgreSQL 18.6 单实例**：官方精确镜像 `postgres:18.6-alpine3.23`（Image ID = RepoDigest = `sha256:697c180d…`，`amd64/linux`），每次验收使用一次性 loopback 容器（`--rm`、`--tmpfs`、无 volume、`RestartPolicy=no`），验收后删除容器、释放端口、销毁随机密码；
- **Schema 与 migration**：五张表、35 个命名约束、8 个业务索引、audit 只追加 trigger/function；`upgrade`/`downgrade`/再次 `upgrade` 实测通过；
- **Repository / UnitOfWork**：一个 UoW = 一个连接 = 一个事务，五类记录同事务提交；失败生命周期（connect/begin/commit/显式 rollback/自动 rollback 失败）关闭式处理且不泄漏连接；`ENT-UOW-001` 句柄失效语义实测；
- **Transactional outbox（写入侧）**：业务写入与 `outbox_events` 行同事务提交，行以 `pending` 落库；幂等以 `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` 裁决；乐观并发使用受保护的 `UPDATE ... RETURNING`；
- **Dispatcher（T83）**：`FOR UPDATE SKIP LOCKED` 短事务领取、`attempts` 作为 fencing token、同 run 严格按 `sequence`、指数退避与终止失败、过期租约恢复；**transport 调用发生在领取事务关闭之后**（实测 `pool.checkedout() == 0`）；并发场景实测（两个 dispatcher 不重复领取、重叠事务各自成功、陈旧序号关闭式失败）；
- **Worker / heartbeat / lease recovery（T84）**：全新 `lease_id`、`job_id + lease_id + attempt` 三元 fencing、心跳以数据库时间刷新 `updated_at`、过期租约按 `attempts` 是否达上限进入 `retrying` 或 `failed`；旧 worker 的心跳/成功/失败三种写入全部关闭式失败；Handler 在**任何事务之外**执行；失败重试复用冻结状态机的两次合法转换；
- **幂等、事务、fencing 与脱敏边界**：参数键与对象自身键一致性前置校验、同 `artifact_id` 全字段比对、`event_id`/`job_id` 幂等边界、错误只保存安全码（不含 traceback、异常消息、URL、host、凭据、payload 或路径）、数据库错误只按 SQLSTATE/约束名映射；
- **当前全量测试基线**：**705 passed、8 skipped、358 subtests、0 failed**（实时 PostgreSQL 集成实跑，0 skipped；`git diff --check` exit 0）。该基线来自 T84 验收时点，T85 不改变任何代码或测试。

## 4. 明确不是（不得据此宣称）

Enterprise Lab 阶段完成**不等于**以下任何一项已经实现或可用：

- **不是默认应用数据库化**：`app.py`、`pages/`、Streamlit 默认入口、T76 启动器与既有科研链路都不导入 Enterprise Lab，也不连接数据库；没有 `STEELAI_ENTERPRISE_DATABASE_URL` 时应用照常完全离线运行；
- **不是生产级任务平台**：没有调度器、优先级、限流、公平性、取消运行中任务、死信队列与管理界面；
- **不是 Kafka 或任何真实 broker**：`EventTransport` 只有内存 Recording 实现，dispatcher 只证明接口与流程；
- **不是常驻服务**：dispatcher 与 worker 都只有**有限调用**（`dispatch_batch` / `run_once` / `run_batch` / `reclaim_expired`），没有 daemon、Windows 服务、定时器、自动启动或后台线程；
- **不是 exactly-once**：投递与执行都是 **at-least-once**，确认失败后会再次发送/执行，下游必须以 `event_id`、Handler 外部副作用必须以稳定 `job_id` 去重；
- **不是 API/RBAC/多租户**：没有 HTTP API、权限控制、租户隔离或投递/任务查询接口；
- **不是高可用、备份或灾难恢复方案**：没有复制、故障转移、备份/恢复演练、容量规划或只读副本；只在单实例上验证。

## 5. 重新开启企业化实施的触发条件

只有在下列**真实需求**出现时，才重新评估是否继续企业化实施（届时按新任务编号立项，并重新做 ADR 决策）：

1. **多用户并发写入成为真实需求**：多个用户/进程需要同时写入同一批科研元数据，且内存适配器与单机 Streamlit 无法满足；
2. **任务必须跨进程长期运行**：出现必须脱离当前请求-响应与"有限调用"模式的长时间任务（例如长时间计算、外部系统轮询、批处理窗口）；
3. **需要与外部系统投递事件**：出现真实的下游消费者（消息中间件、外部服务、数据平台），且必须保证"业务写入与事件投递"的一致性；
4. **需要 HTTP API 与权限控制**：出现外部系统/多客户端集成需求，需要 API、认证、授权与审计查询；
5. **需要生产部署、监控、备份或高可用**：出现真实上线要求，需要部署编排、监控告警、备份恢复、容灾与容量规划。

触发条件出现前，均**不启动**企业化实现工作；出现问题时应先记录需求与验收口径，而不是先行引入组件。

## 6. 触发条件出现前不做的事

- **不接 Kafka**（以及任何真实 broker：RabbitMQ、Redis Streams、云消息服务）；
- **不拆微服务**，不引入 Kubernetes、服务网格或云部署编排；
- **不引入 Redis、Celery、RabbitMQ** 等新的运行时依赖；
- **不把 Enterprise Lab 接入默认 Streamlit 应用**（不新增页面入口、不新增数据库开关、不自动启动任何后台进程）；
- **不新增数据库表/列/索引/迁移**，除非先有触发条件与新的 ADR；
- **不把阶段冻结表述为"生产就绪"**：文档、报告与对外说明都必须保留第 4 节的否定边界。

## 7. 后续路线（企业化暂缓后的工作重点）

1. **T76 真实桌面验收**：由项目负责人在真实桌面终端双击 `Start_SteelAI.bat` 复核代理场景，完成后才能把 T76 由 `Review` 转为 `Done`；
2. **经负责人授权后整理 Git 基线**：T80–T85 的产物目前仍未纳入版本管理；提交、标签与发布必须由项目负责人明确执行，本轮不做任何 Git 操作；
3. **完成一轮真实 Streamlit 使用验收**：以真实用户路径（数据导入 → 物理计算 → 统计与证据 → 运行中心）走一遍并记录问题，形成下一批真实需求；
4. **每次只选择一个真实科研或用户阻塞问题实施**：优先修复阻塞日常科研使用的问题，而不是扩展架构；同一时间只允许一个主要实施分支；
5. **T63/T64 保持延期条件不变**：T63（24 条真实测量）与 T64（人工终审与外部材料）在各自条件满足前继续保持 `Review`，本轮不修改其状态与验收口径；
6. **工程基线管理**：保持 `.\scripts\test.ps1` 作为唯一测试入口、保持 705 passed 基线不回退，任何新工作都必须先说明为什么它服务于真实用户或科研需求。

## 8. 范围说明（阶段收尾轮与验收收口轮）

**阶段收尾轮（T85 初稿）**：

- 只修改六个文档：`TASKS.md`、`docs/ARCHITECTURE.md`、`docs/CURRENT_CAPABILITIES.md`、`docs/KNOWN_LIMITATIONS.md`、本文件、`project_log/CHANGELOG.md`；
- **未修改**任何 Python、PowerShell、BAT/CMD、测试、Schema 或 migration，未修改 requirements 文件，未修改科研数据、方法注册表与治理配置，未修改 T80–T84 的实现与既有 ADR 决策，未修改 `app.py`、`pages/` 与默认 Streamlit 入口，未修改 T63/T64/T76 的状态，未改动 Git 历史；
- **未新增**任何代码、测试、依赖、Schema、迁移或运行能力；**未启动** Kafka/API/微服务；**未运行** pytest、Docker、PostgreSQL 或 Streamlit。

**验收收口轮（2026-09-18）**：

- 只修改三个文档：`TASKS.md`、本文件、`project_log/CHANGELOG.md`——把 T85 由 `Review` 转为 `Done`、补入验收结论、修正 ADR 冻结表述的准确性，并更新 CHANGELOG；
- **未修改** `docs/ARCHITECTURE.md`、`docs/CURRENT_CAPABILITIES.md`、`docs/KNOWN_LIMITATIONS.md`，也未修改任何代码、测试、Schema、迁移、依赖、科研数据、方法注册表、治理配置、`app.py`、`pages/`、默认 Streamlit 入口、T80–T84 实现、既有 ADR 决策、T63/T64/T76 状态与 Git 历史；
- **未运行** pytest、Docker、PostgreSQL 或 Streamlit（测试基线沿用 T84 的 705 passed、8 skipped、358 subtests、0 failed）；
- **未创建 T86**；**未 commit/push/tag**。

本文件路径固定为 `docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`。
