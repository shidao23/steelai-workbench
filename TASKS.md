# SteelAI Workbench 开发任务看板

更新日期：2026-09-18

## 状态定义

- `Planned`：范围已记录，尚未开始。
- `In progress`：已有负责人和当前工作分支，同一任务只允许一个主要实施分支。
- `Blocked`：缺少输入、批准或外部条件，必须记录解除条件。
- `Review`：实现完成，等待测试、隐私复核或科学表述确认。
- `Done`：验收条件全部满足，测试和文档已记录。
- `Canceled`：项目负责人明确决定不再实施；不是失败，也不再作为收尾阻塞项。

## 编号与变更规则

- 阶段零使用 `T00-T09`，阶段一使用 `T10-T19`，后续阶段依次类推。
- 每个任务必须包含目标、范围、输入、输出、禁止事项、验收条件和依赖。
- 一个任务不得同时跨越多个阶段；范围扩大时拆分新编号。
- 代码或行为变化必须在同一提交中更新测试和 `project_log/CHANGELOG.md`；任务状态变化必须更新本看板。
- 优先级、入库和科学表述由项目负责人确认，Agent 不自行批准。

## 看板

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收证据 |
| --- | --- | --- | --- | --- | --- |
| T00 | 建立本地 Git 与隐私基线 | P0 | Done | 无 | `.gitignore`、隐私清单、测试快照、基线标签 |
| T01 | 同步项目说明与实际能力 | P0 | Done | T00 | 能力矩阵、入口状态、README 与集成说明一致 |
| T02 | 建立 Task 看板与任务模板 | P1 | Done | T00 | 本看板、Issue 模板、状态和变更规则 |
| T10 | 验收一批获准的真实脱敏拉伸数据 | P0 | Done | T00-T02 | SteelData 结果校验、样品对应、暂存与重放证据 |
| T11 | 建立真实格式回归样例 | P0 | Done | T10 | SteelData 公开合成夹具与 6 项格式回归；Workbench 入库边界不变 |
| T12 | 冻结毕业主线数据契约 | P0 | Done | T10 | graduation-v1 机器契约、字段说明、合成示例、迁移规则与边界测试 |
| T13 | 建立开源复用登记与决策记录 | P1 | Done | T12 | THIRD_PARTY、5 项候选矩阵、许可证链接、固定引用与关闭式登记测试 |
| T14 | 接入一个高价值开源小功能 | P2 | Done | T13 | Frictionless 可选适配器、哈希锁、MIT 许可证、独立验证与性能/移除记录 |
| T20 | 让 DSH 收敛到 SteelData v0.2 核心 | P0 | Done | T13 | 双 DSH 注册、preview-only 工具白名单、CLI/MCP 同摘要、迁移与回滚记录 |
| T21 | 定义映射建议契约与状态机 | P0 | Done | T20 | 结构化字段/单位/不确定性、受控状态、哈希修订、错误码和角色门禁 |
| T22 | 实现 SteelAI 人工审批界面 | P0 | Done | T21 | 单条来源/字段/单位/风险/差异预览、摘要绑定、人工批准或驳回、防重复提交 |
| T23 | 实现批准后的执行与接入 | P0 | Done | T22 | 人工批准触发、执行状态、幂等重试、结果审计链、原有仅追加接入闸门 |
| T24 | 建立 Intake Agent 评测集 | P0 | Done | T21、T23 | 40 个获批脱敏案例、确定性评分、参考回归与 Workbench 标签查看入口 |
| T33 | 接入 SteelAI 并建立模块边界测试 | P1 | Done | T32 | SteelData 包选择、人工统计决策、独立 SteelStats CLI、结果页与端到端不回写测试 |
| T40 | 冻结端到端旗舰演示 | P0 | Done | T24、T33 | 公开合成输入、一键脚本、成功/未知单位案例、完整性包、运行清单与截图 |
| T41 | 准备公开仓库候选内容 | P0 | Done | T40 | 隐私扫描、README 架构、测试徽章、MIT 许可证、安装与限制说明、全新环境验收 |
| T42 | 制作演示视频与面试讲解 | P0 | Canceled | T40 | 项目负责人于 2026-09-08 决定不再实施 |
| T43 | 建立岗位反馈迭代记录 | P1 | Canceled | T42 | 项目负责人于 2026-09-08 决定不再实施 |
| T50 | 冻结全局科研治理规范 | P0 | Done | T40、T41 | 全局治理规范、机器契约、九工作区覆盖矩阵、状态转换与责任矩阵、契约测试 |
| T51 | 实现共享科研治理包 | P0 | Done | T50 | `steelai.governance`、状态/审批/QC/Manifest/发布保护、迁移说明与回归测试 |
| T52 | 数据接入与 Physics Engine 接入共享治理内核 | P0 | Done | T51 | 两路数据治理适配器、Physics 运行包、模型卡/Manifest、异常与仅追加测试 |
| T53 | 改造可追溯统计与证据验证 | P0 | Done | T51、T52 | 统计结果登记器、证据表述规则、报告完整性适配器、统计与证据回归测试 |
| T54 | 改造 EBSD SEM 与模型任务 | P1 | Done | T51 | 图像任务 Manifest、模型运行契约、人工复核界面、结果索引与治理测试 |
| T55 | 建立 Agent 证据网关 | P0 | Done | T51、T53、T54 | 发送摘要、证据许可、脱敏边界、五段式解释、无原文审计包与权限测试 |
| T56 | 建立统一运行与成果中心 | P0 | Done | T52–T55 | 统一运行索引、状态筛选、跨工作区导航、作品集严格过滤与轻量页面测试 |
| T57 | 全系统回归测试与版本冻结 | P0 | Done | T50–T56 | 九工作区矩阵、八类场景、离线降级、T40 重放、公开审计、v0.2 候选与阶段归档 Word |
| T60 | 实现材料科研多智能体框架 | P0 | Done | T51、T53、T55、T57 | 五角色契约、受控工具、人工关口、交接轨迹、重试与成功/失败/离线演示 |
| T61 | 实现 MCP 工具层与轻量 A2A 协作 | P0 | Done | T60、T51 | 五工具清单、闭合 Schema、权限/超时/错误/幂等、任务信封、stdio 服务与结构化交接演示 |
| T62 | 建立真实材料数据案例 | P0 | Done | T52、T53、T61 | UCI CC BY 4.0 数据登记、固定划分、基线与轻量 kNN、模型卡、错误分析、治理包与一键重放 |
| T63 | 评估人工、单智能体与多智能体流程 | P0 | Review | T60–T62 | 四项固定任务、三流程双重复、冻结指标与判定、测量模板、可追溯评估包；等待 24 条真实测量 |
| T64 | 冻结岗位作品集与公开发布包 | P0 | Review | T57、T60–T63 | 双语 README、能力—证据映射、演示脚本、面试清单、可追溯发布准备包；等待人工终审与外部材料 |
| T70 | 建立外部数据标准化接入 | P0 | Done | T57 | CSV/TSV/XLSX 预览、确定性映射、人工确认、治理写入与边界测试 |
| T71 | 接入热模拟曲线 | P0 | Done | T70 | 18 个采集与 14,352 个曲线点治理入库、公式与数据质控界面 |
| T72 | 建立热模拟曲线可视化 | P0 | Done | T71 | 单采集与 B/R 对比、公式/几何/类型门禁及回归测试 |
| T73 | 建立双道次文献对齐预处理 | P0 | Done | T72 | 32 个候选加载段、版本化分段与人工复核边界 |
| T74 | 建立热模拟特征表 | P0 | Done | T73 | 16 行正式特征、哈希追溯、具名复核与治理写入 |
| T75 | 冻结双道次软化方法并验收结果表 | P0 | Done | T74 | 16 行正式结果、`yjh` 复核、12 通过 + 4 警告保留、`INTAKE-E4FC0CFBAEE9C97BECB0` |
| T76 | 修复本机启动器在代理环境下的实例检测 | P0 | Review | T75 | `scripts/check_local_streamlit_health.ps1` 仅对 loopback 请求禁用代理、`Start_SteelAI.bat` 调用该探针、5 项启动器回归测试与页面/全量测试 |
| T80 | 建立企业架构边界与可替换接口骨架 | P1 | Done | T57、T75 | `steelai/enterprise_lab/` 六边形分层、六个领域对象、六个 Ports、纯 Python 内存适配器、最小纵向流程、ADR-0001 与 T80 架构文档；Codex 最终复核通过，三轮契约修正完成，专项测试 74 passed + 71 subtests passed，全量测试 391 passed + 8 skipped + 0 failed |
| T81 | 建立 PostgreSQL Schema 与迁移基线 | P1 | Done | T80 | `steelai_enterprise` Schema 五张表、35 个命名约束与 8 个业务索引、audit 只追加 trigger、手写冻结 Alembic 初始迁移（upgrade/downgrade/再 upgrade 实测通过）、显式连接配置与 URL 脱敏、领域↔表映射契约、`requirements-enterprise.txt` 可选依赖、ADR-0002（accepted）与 T81 基线文档；**只交付 Schema/迁移/连接/映射契约，不含 Repository/UnitOfWork/dispatcher/worker**；PostgreSQL 18.6 单机容器真实验收（SQLSTATE 23514/23505/23001 实测），集成测试 26 passed + 0 skipped + 28 subtests，schema 28 passed、T80 74 passed、全量 445 passed + 8 skipped + 0 failed，`git diff --check` exit 0 |
| T82 | 实现 PostgreSQL Repository、UnitOfWork 与事务型 Outbox 写入链路 | P1 | Done | T80、T81 | `adapters/postgresql/` 的五个 Repository、`PostgreSQLUnitOfWork`/Factory（单连接单事务）、行恢复、SQLSTATE 错误映射、事务型 outbox 写入侧与数据库内任务租约；真实 PostgreSQL 18.6 验收 22 项场景全通过（原子性/隔离/幂等绑定零写入/artifact 冲突/乐观并发/审计序号并发双成功/outbox 序号并发双成功/陈旧乱序序号关闭式失败/SKIP LOCKED 租约重叠与即时 None/complete-vs-fail 单胜者/retry 上限/句柄失效/trigger 仍生效/连接池归还）；两轮契约修正完成（并发取号双成功、租约与锁行语义、UoW 失败生命周期、生命周期优先于参数校验、锁错误脱敏）；离线 57 passed、集成 22 passed、T81 26 passed、T80 74 passed、全量 524 passed + 8 skipped + 0 failed；ADR-0003（accepted）与 T82 文档；**不含 dispatcher/Kafka/worker/API，默认应用仍未接入数据库** |
| T83 | 事务型 Outbox Dispatcher、租约恢复与至少一次投递基线 | P1 | Done | T82 | `ports/outbox.py`、`application/outbox_dispatcher.py`、`adapters/outbox_memory.py`（含 Recording Transport）、`adapters/postgresql/outbox.py`；复用 `outbox_events` 既有五列、**零迁移**；领取用 `FOR UPDATE SKIP LOCKED` + 短事务 + `attempts = attempts + 1` + 数据库时间租约；`attempts` 作为 fencing token，ack/nack 必须匹配 `event_id + publishing + attempts`；同 run 严格按 `sequence`；过期租约恢复；五种派发结果由 status 唯一推导 `delivered`/`persistence_state_known`/`redelivery_possible`；at-least-once（**不声称 exactly-once**）；离线 67 passed + 74 subtests、真实 PostgreSQL 18.6 集成 17 passed（0 skipped）、全量 608 passed + 8 skipped + 0 failed；ADR-0004（accepted）与 T83 文档；**不接 Kafka，无常驻服务，未接入默认应用** |
| T84 | Background Job Worker、心跳与过期租约恢复基线 | P1 | Done | T83 | `ports/workers.py`、`application/job_worker.py`、`adapters/worker_memory.py`（含 Recording Handler）、`adapters/postgresql/worker.py`；复用 `background_jobs` 既有表、**零迁移**；领取 `FOR UPDATE SKIP LOCKED` + 全新 `lease_id`（首次领取不增加 `attempts`）；`job_id + lease_id + attempt` fencing，旧 worker 心跳/成功/失败三种写入全部关闭式失败；心跳以数据库时间刷新 `updated_at`；过期租约恢复 `retrying`（`attempts+1`）或 `failed`（`ENT-WORKER-LEASE-EXPIRED`）；失败重试复用 `leased→failed→retrying` 两次合法转换；五种 Worker Outcome 由 status 唯一推导；Handler 只见安全元数据，Registry 显式注册；at-least-once（**不声称 exactly-once**）；**两轮契约修正完成**（Handler 异常边界：`DomainError` 与其他 `Exception` 统一脱敏并隔离，不中断批次、不残留 `leased`、`BaseException` 不吞掉；`JobOutcome` 完整不变量已冻结：status 与 `state`/`attempts`/`error_code` 必须一致）；离线 72 passed + 65 subtests、真实 PostgreSQL 18.6 集成 25 passed + 6 subtests（0 skipped）、全量 705 passed + 8 skipped + 358 subtests + 0 failed、`git diff --check` exit 0；ADR-0005（accepted）与 T84 文档；**不接 Kafka，无常驻服务，未接入默认应用** |
| T85 | 冻结 Enterprise Lab 企业化演练阶段与后续路线 | P1 | Done | T80–T84 | 阶段能力总结、非生产边界、重新开启条件、后续产品路线；Codex 最终复核通过，T80–T85 企业化演练阶段正式冻结（2026-09-18） |
| T86 | 将 pycalphad 候选接入物理计算（可选、可关闭） | P1 | 作品集已完成（已签署）/ 真实科研 Blocked | T13、T75 | **双状态**：工程与作品集 `portfolio_exploration_complete`（已由负责人 **世道** 于 **2026-09-25**（Asia/Shanghai）签署，范围 `portfolio_engineering_acceptance_only`，记录 `config/calphad_owner_acceptance_v1.0.json`，并登记于 `config/portfolio_acceptance_v1.0.json`）；真实科研 `scientific_use_blocked_by_solver_stability`。**公开合成演示**（Fe–C，Fe-0.45 wt.% C，4 个已验证相，25 点，400–1600 °C，`independent_single_point_process_v1`）两次运行**最大差 0.0**（容差 1e-7），页面展示曲线并可下载 Markdown/JSON/CSV，不读取私人数据、不写回 `data/processed/`；真实 B-DQ/R-DQ 计算**不发布曲线、不形成材料结论**（容量上界 13、875/900 °C 求解不确定、675 °C 模式差异 1.069×10⁻⁴）。签署**只**覆盖公开演示的工程验收：`scientific_use_approved=false`、`real_sample_curves_published=false`、`materials_conclusion_approved=false`。第五阶段全部失败证据保留不变；未开展第六阶段求解器调试、未更换或升级 pycalphad、未排除温度点、未继续缩减组元或相集合、未重跑 324 点重型验收。证据见 `docs/T86_PORTFOLIO_SUMMARY.md`、`config/calphad_portfolio_demo_evidence_v1.0.json` |

## 阶段八：企业化架构边界（T80 起）

阶段八只建立边界与可替换接口，不安装也不接入外部组件。ADR-0001 冻结了模块化单体、CSV/Manifest 证据、
PostgreSQL 只承载业务元数据、大文件只登记引用与哈希、Kafka 只承载领域事件、Kafka 之前必须先做
Transactional Outbox，以及 Enterprise Lab 为可选扩展这些决策。

## 已完成任务 T10

完成情况：读取通过完整性校验的 SteelData DQ 结果包，按项目负责人批准的 6 个逐试样对应和来源状态生成 Workbench 预检与本地暂存。

验收结果：6 个试样形成 18 条 YS/UTS/EL 观测，18 个唯一主键，预检 ready、0 个错误；来源审计和暂存摘要已保存，提交状态明确为 not_committed。

边界：T200、成分、曲线、冲击、硬度、图像、试样几何和断面收缩率均未接入；真实结果包、暂存、来源路径和审批证据继续保持本地并由 Git 忽略。

## 已完成任务 T11

完成情况：SteelData 已把 T10 暴露出的格式特征转成完全合成的公开回归夹具，覆盖中英文表头、空行、多工作表、模板歧义、单位冲突、重复和坏值；Workbench 继续只消费通过既有结果契约和质量门禁的结果包。

验收结果：正常格式稳定通过，模板歧义稳定进入人工复核，单位冲突不换算，重复不删除，坏值保留原文并阻止合格状态。SteelData 全量自动化测试通过。

边界：未把真实报告或真实数值复制进任一仓库，未更改 Workbench 正式入库行为；T10 暂存仍为 `not_committed`。

## 已完成任务 T12

完成情况：冻结 `SteelAI-Graduation-Core-v1.0`，明确材料、炉次、研究条件、物理试样、来源报告和逐值观测六类身份；当前 quantity 只含已验收拉伸 YS、UTS、EL。

验收结果：机器可读契约、六张公开合成示例表、字段/关系说明、旧表与 SteelData 迁移规则已建立，并纳入本地质量门禁。自动化测试证明报告汇总、曲线点、图像视场和 EBSD 像素不能冒充独立试样，错误单位和未登记报告会关闭式失败。

边界：T12 只冻结目标契约，不自动迁移或提交真实数据；现有 B/R 契约和入口继续兼容，T10 暂存仍为 `not_committed`。成分、冲击、硬度、曲线和图像需要后续版本与独立验收。

## 已完成任务 T13

完成情况：建立机器可读第三方候选登记和 `THIRD_PARTY.md`，核对 Frictionless、NOMAD、GEMD、Great Expectations 与 MLflow 的官方仓库、固定版本/源码引用、OSI 许可证、运行成本和采用决策。

验收结果：质量门禁要求未知/非开源代码拒绝、版本精确固定、许可证链接完整、可选适配器不绑架核心；T13 状态下任何 `code_imported=true` 都会失败。唯一进入 T14 评估的是 Frictionless Data Package 可选导出，其他候选均参考、延后或拒绝。

边界：T13 当时未下载、安装或复制任何第三方代码，未连接外部服务，也未改变数据契约、QC 或入库行为。T14 核对实际环境为 Workbench Python 3.12.14；Great Expectations 的当前拒绝依据已修正为功能重复和维护成本，而非解释器不兼容。

## 已完成任务 T14

完成情况：实现 Frictionless `5.19.0` 可选适配器，将 graduation-v1 的六张公开合成表导出为标准 Tabular Data Package，并进行字段、主键和普通外键独立校验。

验收结果：40 个安装包全部固定版本和 Windows CPython 3.12 wheel 哈希；MIT 许可证和来源可追踪。隔离环境集成测试通过，未安装组件时原生质量门禁仍通过。30 次性能对照中原生中位数 1.691 ms，适配器端到端 36.033 ms。

边界：不上传数据、不处理真实资料、不替代按类型试样关系、单位、统计、来源或入库规则。Frictionless 未进入主 `requirements.txt`，移除不需要迁移数据或修改核心配置。

## 已完成任务 T20

完成情况：Workbench DSH 保留原有 SteelAI 科研只读桥，同时以 SteelData 自己的 Python 环境注册 `steeldata_v2` preview-only 服务；SteelData 独立 DSH 也从旧 standardizer 切到同一 v0.2 入口。

验收结果：DSH 只获得 status、list_inputs、preview_profile 三个 SteelData 工具；实际 stdio 测试证明 MCP 脱敏摘要与 CLI `summary` 完全一致，不返回秘密试样号或本机路径。本机两份 DSH 补丁均通过配置解析，旧 SteelData 补丁已保留供回滚。

边界：T20 没有审批工具、批次执行工具或任意 Shell 工具，不改变现有 SteelAI 入库门禁和科研数据。映射提案、审批 UI、获准执行分别留给 T21、T22、T23。

## 已完成任务 T21

完成情况：SteelData 定义并实现映射建议 Pydantic 契约、状态机、内容哈希、修订事件和本地持久化；Workbench DSH 增加 `steeldata-mapping` 操作规程并切到 suggest 模式。

验收结果：Agent 只能产生 candidate、needs_human 或 unsupported。未知 domain 可显式为空；歧义字段和单位必须进入 uncertainties；Agent 批准、未批准执行、非法转换、过期修订和内容篡改均关闭式失败。建议工具的嵌套 schema 和真实 stdio 持久化已测试。

边界：建议记录不是批准配置，不会运行 SteelData 或写入 Workbench。T22 负责人工 approved/rejected 界面；T23 负责批准后的锁、幂等执行和 append-only 接入。

## 已完成任务 T22

完成情况：在现有 SteelData 页面加入逐条人工审批区，展示来源摘要、字段和单位证据、不确定性、风险、配置差异、建议摘要与 profile 摘要；用户必须亲自填写审批人和说明并明确批准或驳回。

验收结果：批准绑定建议 ID、内容摘要、审批修订和 profile 摘要，人工决定及其摘要独立保存。后端重读修订并使用单建议锁；配置或源文件变化、重复点击、过期页面和空审核身份均关闭式失败。

边界：无批量批准，Agent/DSH 仍无审批权。T22 不执行已批准建议、不写正式科研长表；执行幂等、失败恢复和 append-only 接入留给 T23。

## 已完成任务 T23

完成情况：单条建议人工批准成功后，Workbench 调用 SteelData 的受控执行命令；也可从审批区查看状态、恢复中断、重试失败或重新载入已完成结果。执行结果先通过完整性和跨文件审计链校验，再进入既有人工样品对应与仅追加入库流程。

验收结果：未批准记录不能启动执行；执行绑定建议、批准、人工决定、源摘要和幂等键；中断结果没有可消费 `COMPLETE`，安全重试不重复运行完整结果。结果来源身份独立于用户选择的 `sample_id`，所以改样品对应也不能重复接入；已有主键仍不覆盖。Workbench 128 项测试通过，3 项既有环境条件测试跳过。

边界：自动的是“已批准建议的标准化处理”，不是“自动写正式科研数据”。用户仍要核对物理试样对应和来源状态并明确提交；Agent/DSH 无审批、执行或入库权限，Agent 文本不能成为数据来源。

## 已完成任务 T24

完成情况：现有“研究助手 → Agent评测”页增加 Intake Agent 固定测试集区域。用户点击后可读取 40 个脱敏案例的表头、预期字段对应、预期路线、不确定性和重放组；另一个显式按钮运行不调用云端的确定性参考基线。

验证结果：参考基线 40/40；已知字段准确率 100%，未知单位与歧义转人工率 100%，未批准执行、来源修改和隐私失败均为 0，批准模板重放一致。评分和失败分类由 Python 固定规则完成，并记录延迟与 Token；这只是评分框架自检，不是云模型得分。

验收结果：项目负责人以“继续下一项”确认结束 T24 审核；v0.1 标签冻结为 `approved`，已知映射门槛保持 95%，未知单位和歧义仍要求 100% 转人工审查。

边界：标签批准不代表 DeepSeek 或其他云模型达到参考分数。真实模型基线仍需另行显式运行，且不得发送真实敏感路径、原始数值、报告或批准文件。

## 已完成任务 T33

完成情况：“数据与物理”新增“可追溯统计”模块。用户选择通过完整性校验的 SteelData 逐试样拉伸结果包，逐一确认 `specimen_id` 到 `sample_id` 的对应，填写统计方法版本和人工审核人后，Workbench 生成冻结 T30 四文件输入包并调用独立 SteelStats 环境。

验收结果：Workbench 不导入 SteelStats 内部脚本，仅使用模块描述中固定的 `report` 和 `verify-report` CLI；页面显示 SteelData QC、SteelStats 状态、综合质量状态和完整性复核。专项测试包含真实跨项目子进程调用，并证明调用前后的 SteelData 结果包逐文件 SHA-256 完全一致。Workbench 全量 139 项通过，3 项既有环境条件测试跳过；SteelStats 全量 31 项通过。

边界：不合并两个虚拟环境，不向云模型发送数据，不自动猜测样品对应或方法版本，不接入非拉伸数据，不做显著性检验。统计输入和报告只写入 Workbench 被 Git 忽略的 `outputs/`，绝不写回 SteelData、`data/processed/` 或原始观测列。

## 已完成任务 T40

完成情况：“研究助手 → 旗舰演示”与 `Run_Flagship_Demo.cmd` 已串起公开合成 CSV、Agent 形状建议、明确的 synthetic-only 人工作决定夹具、SteelData 标准化/QC、SteelStats 组级统计和 SteelAI 描述性解释。结果作为带 SHA-256 manifest 和 `COMPLETE` 的仅追加包发布；同输入重放复用，篡改包拒绝覆盖。

技术验收：成功链路产生 6 个试样、18 条观测、6 个统计组且每组 n=3；SteelData QC 与 SteelStats 完整性均通过。失败链路的 YS 单位故意未知，状态稳定为 `needs_human`，未批准执行返回 `execution_not_approved` 且没有结果。Workbench 全量 142 项通过、3 项既有环境条件测试跳过；SteelData 全量 88 项通过；SteelStats 全量 31 项通过。

验收结果：项目负责人于 2026-09-08 实际打开“研究助手 → 旗舰演示”，核对成功链路、未知单位拦截、组级结果和描述性解释后，明确回复“T40 验收通过”；任务由 `Review` 冻结为 `Done`。

边界：全部输入和值为公开合成资料；冻结决定夹具不冒充真实人工实验审批。演示不调用云端或本地 AI，不写正式科研长表，不做推断统计、因果判断或工艺推荐，也不临场修改输出。

## 已完成任务 T41

完成情况：形成只面向 Git 跟踪内容的公开仓库候选审计，补齐 MIT 许可证、README 架构与测试徽章、从零安装说明、已知限制和公开候选清单；本地科研会话已纳入忽略范围。

验收结果：公开候选审计会对本机用户路径、常见密钥、真实数据/运行区、个人科研会话和模型权重关闭式失败，并纳入质量门禁与自动测试。候选包在全新 Python 3.12 虚拟环境安装后通过质量门禁和离线测试。

边界：没有创建远程仓库，没有执行 GitHub 推送，没有发布真实数据、运行结果、内部审批记录或完整历史。T42 与 T43 依项目负责人决定取消，不作为项目收尾缺口。

## 已完成任务 T50

完成情况：冻结 `SteelAI-Global-Research-Governance-v1.0`，统一九个科研工作区的研究对象身份、十状态语义、结果等级、人工审批记录、正式写入条件和失败关闭行为；同时登记各工作区现有入口、输出与旧状态词，供后续逐模块迁移。

验收结果：数据接入、Physics Engine、可追溯统计、EBSD/SEM、研究助手、模型实验室、自动化任务、科研会话和作品集均已映射到统一状态、结果身份及人工门槛。每个 `needs_human` 和 `blocked` 类别均有唯一错误码、显式触发与解除/恢复路径；机器契约测试验证禁止未批准执行、合成数据冒充实验真值、Agent 自行批准和静默覆盖。

边界：T50 只新增治理规范、机器可读契约和契约测试，不实现共享运行时、不迁移既有状态、不重构页面、不读写真实科研数据。T40 旗舰演示、既有结果包与公开合成夹具保持不变；共享治理包和工作区适配从 T51 开始。

## 已完成任务 T51

完成情况：新增 `steelai.governance` 公共包，把 T50 规范实现为稳定数据类、标准 JSON/SHA-256、状态转换、审批快照、来源引用、QC/正式写入门禁、Governance Manifest 和仅追加原子发布器。相同身份与内容可幂等复用，不同内容冲突或无效目标均拒绝覆盖。

验收结果：受控执行只有持有当前对象摘要绑定的人工作决定才能从 `approved` 进入 `running`；非法捷径关闭式失败。包内文件、Manifest 或 `COMPLETE` 被修改后验证状态为 `invalidated`。专项测试覆盖成功、失败、重复执行、冲突和篡改，治理契约已加入本地质量门禁；现有离线测试与 T40 旗舰演示继续通过。

边界：T51 建立公共底座和迁移映射，不批量改写九个页面或既有历史，不读取、复制或写入真实科研数据。数据接入、统计、图像、Agent 等业务链路从 T52 起逐项接入公共包。

## 已完成任务 T52

完成情况：新增数据接入治理适配器，使标准 CSV 与 SteelData 结果包复用“预检建议 → 具名人工批准 → 受控执行 → QC → 仅追加写入 → 治理审计包”链路；新增 Physics 治理适配器，保存输入成分快照、公式 ID/版本、适用范围、警告、实验对照、残差定义、逐模型卡和 Governance Manifest。两个页面均按当前状态、主要操作、结果、技术详情和下一步展示。

验收结果：未知单位在标准化前进入 `needs_human` 且无法提交；缺失 Physics 输入保持 `None` 并关闭式阻断，不按 0 代填；越界结果必须显式接受警告；所有公式结果固定标记为经验模型估算而非实验真值。正式数据继续由写入锁、提交前重检、主键冲突检查和仅追加发布保护；同一 Physics 身份可幂等复用，篡改包变为 `invalidated` 且拒绝覆盖。专项测试覆盖成功、未批准、未知单位、缺失输入、越界、重复主键、幂等和篡改路径。

边界：T52 不迁移或改写既有真实数据、历史结果包和 T40 冻结演示，不自动批准、不把模型结果写回实验观测、不做模型校正或统计推断。SteelData 仍在独立环境运行，Workbench 只接收其已验证结果包；可追溯统计及其他工作区留给后续任务接入共享治理。

## 已完成任务 T53

完成情况：新增 `steelai.statistics_governance`，把独立 SteelStats 报告连同统计单位、分组、逐值观测、纳入决定、实验方法版本、统计方法版本、审核身份和 SteelData 源 Manifest 摘要封装为仅追加治理包。包内同时生成统计结果登记器、反查索引、允许/谨慎/禁止表述规则和可下载的治理版描述统计报告；证据验证页只读取完整性通过的最新治理统计包。

验收结果：一个治理报告可反查到统计试样、18 条逐值观测、逐条纳入决定、方法版本、SteelStats 原始结果和 SteelData 来源摘要；包内任一文件被修改后复核状态变为 `invalidated`，不会覆盖原包，也不会进入证据表述。描述性差异始终禁止自动升级为统计显著、总体无差异或因果结论；warning 必须保存摘要绑定的人工接受记录。跨独立 SteelStats CLI 的端到端测试确认统计和治理封装前后 SteelData 源包逐文件摘要完全一致。

边界：T53 不向 SteelStats 增加显著性检验，不自动删除异常值、填补缺失值或做因果推断，不修改 SteelStats 内部算法，不把统计结果写回 SteelData、`data/processed/` 或实验观测。旧 T33 入口和结果包继续兼容，T40 冻结演示保持不变。

## 已完成任务 T54

完成情况：新增 `steelai.image_model_governance`，以统一契约登记 EBSD、SEM 与独立模型任务的只读来源、样品、物理试样、图像视场、软件和模型版本、参数及隔离环境；外部运行结果只登记文件摘要和私有定位摘要，不复制原始图像、CTF、权重或重型输出。运行状态覆盖完成、部分、失败、取消和重跑，完成与部分结果默认进入 `needs_human`。EBSD 与模型实验室页面共用任务登记、运行登记和人工复核面板。

验收结果：人工接纳前，模型结果只能是 `working_candidate`，不能进入结果索引；完整结果经具名复核后登记为 `model_result`，部分结果必须显式选择 `warning_accepted` 并保留局限。失败和取消稳定映射为关闭状态，重跑保存尝试次数和前序运行引用。任务、运行和复核包均可验证 Manifest，任一文件被修改后变为 `invalidated`。专项测试覆盖 EBSD/SEM 双模态、原文件不复制不改写、版本与参数反查、人工复核、部分结果、失败、取消、重跑和篡改。

边界：T54 不把模型输出改称实验测量，不自动产生组织或断口科学结论，不替代人工分割复核，不迁移真实原始文件，不把 MATLAB/MTEX、micro-sam 或 GPU 依赖装入 Workbench 主环境，也不要求本机运行大语言模型。现有 EBSD 和 SEM 技术流程继续兼容。

## 已完成任务 T55

完成情况：新增 `steelai.agent_evidence_gateway`，把 Research Agent 的 OpenAI Responses 与 DeepSeek 兼容调用统一放到证据网关之后。问题先做路径、受保护文件名和疑似密钥扫描；每次云调用前生成发送摘要。普通数据与 Physics 工具要求 T52 数据契约通过，EBSD/SEM 工具要求 T54 结果已经人工接纳；脱敏载荷获得稳定 `AGEVID` 身份后才能进入模型。

验收结果：回答归一化为事实、判断、假设、局限和下一步五段式结构，并固定声明不能审批、不能正式写入、不能执行 Shell、必须人工复核。审计包只保存供应商、模型、哈希、调用状态、证据引用、Token 和失败类型，不保存问题、回答、参数、工具载荷、绝对路径或原始文件名。页面提供发送前摘要，并把手动保存改为“待人工复核草稿”。专项测试覆盖证据资格、隐私、权限、稳定输出、篡改验证和无 Key 离线路径。

边界：T55 不授予 Agent 人工审批、受控执行、正式科研数据写入、任意命令、原始文件读取或科学结论发布权限；不调用真实云端 API，不迁移真实资料，也不改变 T40 冻结演示及 T51–T54 的确定性计算规则。

## 已完成任务 T56

完成情况：新增 `steelai.run_center` 和“研究助手 → 运行与成果”页面，把 T52 数据接入、Physics、T53 统计、T54 图像任务/运行/复核、T55 Agent 网关、科研会话、自动化状态与 T40 冻结演示归一为轻量只读记录。页面统一展示任务 ID、模块、状态、时间、审核身份、相对结果位置、作品集资格和来源工作区下一步入口，并支持进行中、待人工确认、被阻止、完整性失效、已完成和已验收成果筛选。

验收结果：完整性失败始终归入 `invalidated`；待人工确认、阻断和已验收结果在页面明显区分。作品集改为只消费 Manifest 完整性通过、状态 `complete`、结果等级合格且具有具名人工接纳的成果；Agent `working_candidate`、科研会话、自动化状态和普通项目事件均被排除。T40 旧演示必须同时通过原完整性检查与显式验收登记，并固定标记为公开合成工程演示。

边界：T56 只建立只读索引、筛选和导航，不执行任务、不改变审批、不修复或覆盖结果包、不读取重型原始文件、不把合成演示包装为真实科研结论。页面只显示项目相对位置，并保持普通个人电脑可轻量运行。

## 已完成任务 T57

完成情况：新增 `config/release_candidate_v0.2.json` 和 `steelai.release_candidate`，把九个工作区的目标链路、实现证据、测试证据、限制与延期状态冻结为 `v0.2.0-rc1`。跨模块矩阵固定覆盖成功、字段缺失、单位未知、身份冲突、重复写入、未批准执行、文件篡改和隐私泄漏；Research Agent、SteelData 与 SteelStats 的离线或不可用路径也有独立验证。

验收结果：发布契约已纳入质量门禁；完整离线测试、公开候选审计和 T40 合成旗舰演示可通过 `Freeze_v0.2_Candidate.cmd` 重放。架构、安装、已知限制、用户操作和验收报告已经同步，阶段五归档 Word 单独生成并完成版面复核。

延期说明：自动化任务尚未完成共享治理执行适配，v0.2 只冻结其状态记录与统一中心展示，不能把自动化输出升级为已验收成果。Git 提交、标签和 GitHub Release 等待项目负责人明确执行，不由 T57 自动完成。

## 已完成任务 T60

完成情况：新增 `SteelAI-Materials-Multi-Agent-v1.0` 角色契约和 `steelai.multi_agent_orchestrator`。规划、数据、统计与物理、材料解释、审查五类角色按固定顺序交接；每个角色都有明确输入、输出、工具白名单、权限否定和停止条件。计划执行前与结果完成前设置两个具名人工关口，Agent、system 或 model 身份不能审批。

验收结果：每次交接记录任务、证据引用、输出状态和责任角色；工具调用只保存参数摘要、结果摘要、尝试次数和稳定错误码。证据不足稳定阻断为 `GOV-EVIDENCE-001`，工具失败重试一次后阻断为 `GOV-RUNTIME-001`，无来源主张由审查角色阻止。冻结成功、证据不足、工具失败和云端不可用四条合成演示；云端不可用时，确定性数据、描述统计和 Physics Card 仍可完成。运行轨迹使用阶段五 Manifest、SHA-256、COMPLETE 与仅追加发布，并进入统一运行中心。

边界：多智能体角色不是自由自治进程，不持有审批、正式写入、来源修改或任意 Shell 权限。演示只使用公开合成证据和明确标记的决定夹具，不读取真实资料、不代表真实实验审批、不把工作候选升级为科研结论或作品集成果。阶段六后续按 T61、T62、T63、T64 推进。

## 已完成任务 T61

完成情况：新增 `SteelAI-Research-MCP-Tools-v1.0` 五工具清单、`SteelAI-Lightweight-A2A-Task-v1.0` 任务信封、`steelai.research_protocol` 受控工具层和 `steelai.research_mcp_server` 本地 stdio 入口。样品查询、核验证据、描述统计、Physics Card 与候选报告均固定 JSON Schema、允许角色、权限、超时、错误码、版本和幂等键；任务信封绑定任务、修订、发送/接收角色、证据、状态、时间、摘要与整体 SHA-256。

验收结果：无权角色、未知工具、闭合 Schema 之外字段、缺失或过期任务批准均在后端执行前阻断。每次工具调用生成仅追加治理包，可追溯到任务修订、输入版本、工具版本、结果摘要和错误原因；相同请求幂等复用，同一幂等键绑定不同输入则以 `GOV-DUPLICATE-001` 拒绝。冻结合成演示完成规划角色到数据角色、统计与物理角色、材料解释角色的三次结构化任务修订，以及四次非正式工具调用。

边界：所有工具固定 `formal_result=false` 和 `human_review_required=true`，不执行正式写入。当前只验证本地 stdio MCP 和 SteelAI 项目内 A2A 任务信封，不宣称远程发现、网络认证联盟、流式消息、推送通知或完整厂商协议兼容。阶段六下一项为 T62 真实材料数据案例。

## 已完成任务 T62

完成情况：采用 UCI `Steel Plates Faults`（ID 198、DOI `10.24432/C5J88N`、CC BY 4.0）建立第一套公开真实工业钢铁数据案例。固定官方页面、下载地址、署名和 ZIP/数据/字段文件 SHA-256；原始数据只在运行时读取，不进入仓库或结果包。研究问题、七类目标、27 个输入、逐类 SHA-256 60/20/20 划分、多数类基线、标准化距离加权 kNN、候选 k 和选型规则均冻结。

验收结果：一键联网运行和离线 `--zip` 均复现同一 `T62-UCI198-6259B200739902AC0541` 结果，第二次幂等复用。393 条测试记录不参与选型；多数类基线测试 accuracy / balanced accuracy / macro F1 为 0.3461 / 0.1429 / 0.0735，选中 `k=3` 的轻量模型为 0.7354 / 0.7534 / 0.7591。结果包包含数据卡、获取收据、固定划分、逐行预测、指标、模型卡、失败分析、中文报告、Governance Manifest 和完整性标记。

边界：这是钢板表面缺陷模式识别案例，不是成分—性能模型。来源缺少板号/批次键、完整单位和成分/工艺/组织信息，隐藏采集组泄漏和采集条件偏差不能完全排除；禁止包装为生产部署、冶金机制、因果判断或工艺推荐。当前结果等级仍为 `working_candidate`，没有自动进入正式证据或作品集。后续进入 T63 人工、单智能体与多智能体同题流程评估。

## 待实测验收任务 T63

完成情况：已冻结数据检查、统计解释、Physics 缺失输入判断和证据约束报告整理四项任务，以及纯人工、单智能体、受治理多智能体三种流程。每项流程固定重复两次，共 24 条测量；完成率、关键错误、人工修订、耗时、Token、费用和追溯完整率均在运行前定义。新增测量模板、关闭式记录校验、冻结优势判定、仅追加治理结果包、运行中心索引和页面入口。

当前验收结果：契约与 12 条结构校准记录可以生成和重放，校准记录明确排除在效率结论外。系统在 24 条真实记录不完整时固定返回 `insufficient_evidence / needs_human`，不会把演示或模拟耗时包装成优势；完整实测后，无优势和失败结果同样保留。

待完成：由项目负责人实际完成或监督 24 次同题测量，记录真实耗时、人工修订、Token 和费用，并复核比较报告。完成前 T63 保持 `Review`，不得宣称单智能体或多智能体提高了科研效率。

边界：结论只适用于冻结任务集、模型版本和本次运行环境；不保存提示词/回答原文、私有实验值、本机路径或密钥，也不授予智能体审批、正式写入或任意命令权限。

## 待人工终审任务 T64

完成情况：新增岗位作品集公开发布契约，固定 16 项公开资产、4 条能力—证据映射、八项验收门槛和隐私边界；补充英文 README、三分钟演示脚本、五类面试讲解清单、一键发布准备脚本、可追溯 `needs_human` 发布包及页面入口。机器校验只证明材料齐全和引用存在，不会代替人工验收或 GitHub 发布。

待完成：T63 的 24 条真实测量、全新环境独立复现、实际视频录制、技术报告或软件型论文初稿、简历三类表述定稿，以及许可证、隐私、指标一致性和夸大表述终审。上述项目全部完成前保持 `Review`，不得标记最终 Release。

边界：T64 不上传 GitHub、不创建标签或 Release、不把合成演示包装成实验结论，也不把 T62 分类结果包装成冶金机制或生产建议。

## 已完成任务 T70

完成情况：把阶段七首项收敛为“外部文件标准化入库”。新增 CSV、TSV、XLSX 内存读取、工作表选择、常见中英文字段建议、人工字段映射、明确单位换算、标准化预览、新样品受控登记和一键治理入库；入口已放到“数据接入与质控”首个标签页，旧标准 CSV 与 SteelData 流程保留为高级入口。

验收结果：GPa → MPa 等登记换算由确定性代码执行；未知单位、缺少字段、未登记样品、重复目标和主键冲突关闭式阻断。新样品只能先通过 `samples.csv` 登记，随后其他层才能引用。提交继续复用 T52 的具名人工审批、写入锁、提交前重检、仅追加发布和 Governance Manifest，并额外保存字段与单位标准化记录。

边界：T70 当前针对平面数据表，不解析任意复杂仪器报告、宏、旧 XLS 或曲线，也不会自动建立真实炉次、试样或视场身份。复杂报告继续走高级 SteelData；标准化数据层当前仍是本地结构化 CSV，不是多用户网络数据库。T70 不调用云端 AI，不复制或改写原始实验文件，不自动生成统计或科研结论。

## 已完成任务 T71

完成情况：新增热模拟仪器文本解析器和“数据接入与质控 → 热模拟曲线”入口。系统可批量读取 `ZHT.A*`，核对文件头、通道、声明点数、interval、点号和时间顺序，分开生成热模拟运行表与曲线点表候选；计划参数、实测指标、单位和试样身份均保留独立证据状态。

真实批次结果：指定 `double-hit` 文件夹的 18 个文件和 14,352 个点全部完成只读结构解析并正式入库。项目负责人确认 Time/Period 为秒、Force 为仪器 kg 力值且不换算 N、Stroke 为 cm、B/R—采集号—物理试样映射正确，原试样为直径 10 mm、长度 15 mm。A82–A87 温度偏差及 A86/A87/A90/A91 道次间隔偏差均保留计划值并以实际仪器数据作为有效值。运行表与点表通过同锁重检、预构建、失败回退和治理审计写入。

边界：本阶段不修改或复制原始 A 文件，不从仪器 kg 力值推断 N，也不因已有 10×15 mm 几何就自动生成应力—应变。底层正式数据仍是本地 CSV，双表提交提供应用内失败回退，但不是网络数据库事务。

## 已完成任务 T72

完成情况：把项目负责人提供的 Φ10×15 mm 压缩公式登记为独立版本，从标准化点表确定性计算应力和真应变；热模拟页面新增单采集、B/R 成对对比、应力—应变、温度—时间、原始力—时间、原始位移—时间和当前换算数据下载。

验收结果：A75 默认曲线和 B/R 1100 ℃、计划间隔 1 s 对比已在本地界面实测显示。公式数值、错误几何、非 DH 类型、非正当前长度和 B/R 配对均有自动测试；T71 接入测试和数据质控页面启动测试同时通过。

边界：不自动删除负力、卸载或回程数据，不平滑或校正，不把图中峰值包装为本构参数；PAG 不套用 DH 压缩公式。

## 已完成任务 T73

完成情况：按照 double-hit 文献常用口径新增两道次有效加载段处理。每个 hit 独立建立局部真应变，累计真应变和原公式全路径同时保留；分析曲线做可追溯力基线修正，不做平滑、摩擦或绝热温升修正。接触点和加载终点算法登记为版本化项目规则，界面可在文献分析视图与公式全路径之间切换，并可下载有效加载段建议。

真实批次结果：16 个 DH 采集全部自动识别出两道次，共 32 个候选段，局部最大真应变约 0.231–0.278。A75 第一、二道次候选接触点分别为 81、102，候选终点分别为 329、325。所有结果保持 `suggested_needs_human`，原始标准化数据未被修改。

边界：文献规定后续可按 0.2% 偏移法计算 `X=(sigma_m-sigma_2)/(sigma_m-sigma_1)`，但没有规定通用仪器接触阈值。T73 因此不生成正式软化率；32 个候选段需目视复核，0.2% 偏移拟合与结果批准留到下一任务。

## 已完成任务 T74

完成情况：新增一行一个采集的热模拟特征提取器、特征版本配置和 Research Data Contract 表定义。提取两道次峰值应力及其应变/温度、0.05/0.10/0.15/0.20 局部真应变流动应力、起止时间与温度、T71 运行间隔、有效变形间隔、最大 Stroke/相对位移/局部真应变，以及公式、分段、特征、源文件、源点、候选段和特征行哈希。界面可下载候选 `thermal_simulation_features.csv`，也提供具名复核后经共享治理门禁只追加写入正式表的入口。

真实批次结果：16 个 DH 采集均成功生成候选特征，共对应 32 个有效加载段；后续统计、报告和 Agent 可读取特征表而不必反复扫描 14,352 个曲线点。定点流动应力对重复应变取中位数后线性插值，禁止外推。

边界：T74 不计算正式屈服应力、软化率或再结晶动力学参数；这些结果仍需 T75 的具名方法选择和拟合质量门禁。

验收补充：项目负责人随后完成复核。A75 已由界面以复核人 `yjh` 写入；系统在整批重试时正确阻止重复覆盖，随后仅补写其余 15 个采集。正式 `thermal_simulation_features.csv` 现有 16 行，新增治理记录为 `INTAKE-1ED5882C1521A2760C77`。

## 已完成任务 T75

已建立 double-hit 软化方法登记和当前批次应变分辨率诊断。16 个 DH 采集的正应变步长最小约 0.003226、中位约 0.004068；0.2% 偏移量 0.002 低于单个采样步长，而 2% 偏移量 0.02 约覆盖 4.92 个中位步长。

方法验收：项目负责人已确认 `offset_2p0_srx_focused` 为主方法、`fixed_true_strain_0p05` 为敏感性对照，统一使用 `X=(sigma_m-sigma_2)/(sigma_m-sigma_1)`；0.2% 偏移法只作为未来高分辨率数据选项。

完成情况：已实现版本化的 2% 偏移交点、拟合 R² 门禁、5% 定真应变 Hollomon 投影、主/对照软化率、B/R/实际间隔可视化、完整诊断下载和共享治理正式写入口。2026-09-16，复核人 `yjh` 对 16 行精确结果完成具名复核并正式写入 `thermal_simulation_softening.csv`；12 行状态为 `passed`，A79、A80、A84、A85 四行保留 `warning_needs_human_review`，治理记录为 `INTAKE-E4FC0CFBAEE9C97BECB0`。

边界：四条警告的主软化率原始值 107.29%、120.44%、109.66%、103.48% 未截断、未删除，不据此推断额外冶金机制或生产结论。

## 待验收任务 T76

完成情况：`Start_SteelAI.bat` 原先用 `Invoke-WebRequest` 直接探测 `127.0.0.1:%STEELAI_PORT%/_stcore/health`。当系统设置了 `HTTP_PROXY=http://127.0.0.1:7890` 且没有 localhost 例外时，该请求被发给代理并得到 502，启动器因此把正在运行的实例误判为未启动，随后尝试再次占用 8501。Windows PowerShell 5.1 的 `Invoke-WebRequest` 没有 `-NoProxy` 参数，所以新增 `scripts/check_local_streamlit_health.ps1`：它用 `System.Net.WebRequest` 只探测 loopback 健康端点，并只把本次请求的 `Proxy` 置空，随后关闭响应对象；exit 0 表示已在运行，exit 1 表示未运行或无法确认。启动器改为调用该探针，已在运行时输出既有提示并在 `STEELAI_NO_BROWSER` 设置时不打开浏览器、返回 0；探针失败时继续进入原有 Streamlit 启动路径。

代理边界：不读取、不修改、不持久化 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`；不设置全局默认代理；不引入 curl 或任何新依赖；监听地址、默认端口和 Streamlit 启动参数未变。

测试证据：新增 `tests/test_windows_launcher.py`（5 项）在临时 loopback 健康服务 + 不可达代理（`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 指向死端口、清空 `NO_PROXY`）下证明启动器能识别已运行实例、不会启动第二个 Streamlit，并证明探针在无响应时返回未运行。

真实验证：`.\.venv\Scripts\python.exe -B -m pytest -q tests/test_windows_launcher.py` → 5 passed；`tests/test_streamlit_pages.py` → 5 passed；`tests/test_windows_launcher.py tests/test_streamlit_pages.py` → 10 passed；`.\scripts\test.ps1` → 317 passed, 8 skipped, 38 subtests passed（149.79s，exit code 0）。受限沙箱中所有临时目录夹具都会因 `WinError 5` 失败，属环境限制，需在普通用户终端重跑，不得改写夹具绕过。

未完成：本项仍为 `Review`，等待 Codex 与项目负责人在真实桌面终端双击 `Start_SteelAI.bat` 复核代理场景，不由实施方自行标记 Done。

边界：只改启动器与本机健康探针、`README.md` 运行章节、看板与变更日志；不修改代码逻辑、页面功能、科研数据、方法注册表、Streamlit 参数或用户代理配置，也不创建中文启动脚本。

## 已完成任务 T80

完成情况：新增可选包 `steelai/enterprise_lab/`，按六边形架构分为 `domain`、`application`、`ports`、`adapters`。领域层提供 `EnterpriseProject`、`WorkflowRun`、`ArtifactReference`、`AuditEvent`、`DomainEvent`、`BackgroundJob` 六个稳定对象，均带稳定 ID、修订号、状态、创建时间和内容摘要；运行状态直接复用 T50 的十个 `GovernanceState` 取值，不新建第二套科研状态机。Ports 用 `typing.Protocol` 冻结 `RunRepository`、`AuditRepository`、`ArtifactStore`、`EventPublisher`、`JobQueue` 和 `UnitOfWork`。适配器只有纯 Python 内存实现。应用层演示一条最小纵向流程：创建运行 → 登记 artifact metadata → 追加审计 → 生成领域事件 → 提交事务，全部使用公开合成元数据。

契约边界：幂等创建同内容复用、同幂等键不同内容关闭式失败；`WorkflowRun.request_digest` 为必填的小写 64 位 SHA-256，没有合法请求摘要的运行无法入库；状态更新必须带 `expected_revision`，不一致时拒绝写入；审计只能追加，重复 `audit_id` 或乱序序号被拒；ArtifactStore 只登记相对引用、SHA-256、类型与版本，拒绝绝对路径、路径穿越、空哈希和非法哈希；事件按每个运行内连续序号可重放；后台任务状态机拒绝非法转换且入队受幂等索引保护，T80 不实现并发 worker；`UnitOfWork` 是唯一事务接口（读也是读后 rollback），且明确声明内存实现**不是**数据库事务，只保证已提交状态对外唯一可见、回滚不留部分写入。描述性字段在类型层面拒绝数字、绝对路径、UNC 路径、URL 和常见凭据模式，因此原始实验值、本机绝对路径和密钥无法进入运行记录、审计记录或领域事件；`model_output` 不能登记为 `accepted_evidence`。

测试证据：新增 `tests/test_t80_enterprise_architecture.py`（74 passed + 71 subtests）。覆盖无企业依赖时导入、`app.py` 与 `steelai/**` 均不导入该包、六边形依赖方向的 AST 检查、领域对象校验、事务与幂等契约、纵向流程与脱敏输出，以及“不写仓库文件、不写系统临时目录、不读写环境变量”的边界。

Codex 复核修正（三项契约）：其一，`MemoryStore.state` 现在始终只代表已提交状态，UoW 只改自己的私有 working state，commit 时一次原子替换，rollback 只丢弃 working state；仓库在创建时绑定到该 UoW 的生命周期，commit/rollback 后即使调用方保存了引用，任何读写都返回 `ENT-UOW-001`；同一 store 上的第二个 UoW 被明确拒绝，不允许看到第一个 UoW 的未提交数据。其二，新增覆盖全部影响副作用字段（run/project/task、module version、result/evidence、next_action、created_by、artifacts、audit_entries、event_note）且不含运行时时间戳的 `request_digest`，同一幂等键只有配上相同摘要才复用，不同摘要在任何副作用产生前返回 `ENT-IDEMPOTENCY-001`。其三，任务队列新增幂等索引，把幂等键绑定到 job_id 与请求摘要，同键不同 job_id/payload、同 job_id 换键都被拒绝。旧测试中只检查回滚后最终状态的写法已改为真正检查进行中的已提交状态。

最后收口（原三项阻塞问题复核通过后）：`WorkflowRun.request_digest` 改为必填的小写 64 位 SHA-256，删除空字符串默认值与“仅非空时校验”分支，`WorkflowRun.create` 必须显式接收该参数，空值、长度错误、非十六进制和大写摘要全部拒绝；删除返回 `Any` 的 `read_only` 预探针与只读会话类型，统一使用显式 `UnitOfWork`——幂等检查与 `create_run` 在同一事务内且在 artifact/audit/event 之前完成，重放分支只读后 rollback，`read_run`/`list_runs` 同样读后 rollback；`committed` 改为该 UoW 自己的提交结果标志，commit 后永久为 True、rollback 后为 False，不受其他 UoW 后续提交影响，并新增两个连续 UoW 提交的回归测试；同时删除未使用的 `_committed_snapshot` 遗留字段。

验收结果：Codex 最终复核通过，三轮契约修正全部完成——第一轮事务边界（已提交状态唯一可见、仓库句柄随 UoW 生命周期失效、重叠 UoW 被拒绝）、第二轮请求与任务幂等（`request_digest` 全覆盖、幂等键绑定 job_id 与请求摘要）、第三轮收口（`request_digest` 强制化、删除返回 `Any` 的只读预探针、`committed` 改为 UoW 自身结果标志）。专项测试 `tests/test_t80_enterprise_architecture.py` 为 **74 passed、71 subtests passed**；全量测试 `.\scripts\test.ps1` 为 **391 passed、8 skipped、0 failed**。已确认未新增第三方依赖、未修改科研数据与方法注册表、现有 SteelAI 默认行为不变、未开始 PostgreSQL/Kafka/微服务实现。

边界：不安装或接入 PostgreSQL、Docker、Kafka、Redis、FastAPI、SQLAlchemy、Alembic、OpenTelemetry；不修改 `requirements.txt` / `requirements-dev.txt`；不新增第三方依赖；不建表、不写 migration、不增加 Streamlit 页面、不迁移 CSV；不修改科研数据、方法注册表、T40/v0.2 冻结边界或 T76 实现。文档明确不把尚未实现的 PostgreSQL、Kafka、微服务或云部署写成现有能力。

后续：T81 的 PostgreSQL Schema、迁移基线与连接配置已完成（PostgreSQL 18.6 真实验收 + Codex 最终复核通过）。**T82 已完成 PostgreSQL Repository/UnitOfWork、事务型 outbox 写入侧和数据库任务队列基础；outbox dispatcher、worker、Kafka 与 API 属于 T83 及以后。** 内存适配器仍无持久性与跨进程隔离，领域对象与 T51 治理包的映射待后续任务设计。

## 已完成任务 T81

任务定位：T81 只建立 **PostgreSQL Schema、Alembic 迁移基线和连接配置边界**，不是完整的 PostgreSQL 持久化适配器。它不实现 `RunRepository`/`AuditRepository`/`ArtifactStore`/`EventPublisher`/`JobQueue`/`UnitOfWork` 的 PostgreSQL 版本，不实现 worker、outbox dispatcher、Kafka 或 API，也不接入默认应用。

完成情况：新增可选边界包 `steelai/enterprise_lab/adapters/postgresql/`（`config.py` 显式配置与 Engine 工厂、`constraints.py` 纯常量与 SQL 文本（无 SQLAlchemy 对象）、`schema.py` live SQLAlchemy Core Metadata、`mapping.py` 领域↔表映射契约与纯函数行构造器）、手写并**冻结**的初始迁移 `migrations/enterprise/versions/0001_enterprise_baseline.py` 与 `alembic-enterprise.ini`，以及专用 Schema `steelai_enterprise` 上的五张业务元数据表：`workflow_runs`、`artifact_references`、`audit_events`、`outbox_events`、`background_jobs`。所有主键、外键、唯一约束、CHECK 约束与索引均有稳定名称；状态列一律字符串 + 命名 CHECK，不使用 PostgreSQL 原生 ENUM；`audit_events` 增加由 `fn_audit_events_reject_mutation()` 与 `trg_audit_events_append_only` 强制的只追加保护。新增可选依赖清单 `requirements-enterprise.txt`（SQLAlchemy 2.0.54、Alembic 1.20.0、psycopg[binary] 3.3.5，精确锁定、无预发布版）。

契约边界：连接串只能来自显式参数或 `STEELAI_ENTERPRISE_DATABASE_URL`，无默认值与凭据；缺失时以 `ENT-DB-CONFIG-001` 关闭式失败；任何 repr、异常、日志与测试输出都经过脱敏（用户名、密码、主机、查询串全部替换）；模块导入不连接数据库、不创建全局 Session；启用 `pool_pre_ping` 且只使用同步 Psycopg 3。迁移默认拒绝名称不同时含 `steelai` 与 `test` 的目标库（`ENT-DB-CONFIG-004`）。downgrade 按依赖逆序删除 trigger、function 与表，不含 `CASCADE`、不含 `DROP DATABASE`、不删除 Schema、不触碰科研路径；迁移不含 seed、演示账号或真实业务数据。`projects` 表未创建，`workflow_runs.project_id` 暂作为外部项目标识。

映射与治理：`workflow_runs.state` 复用 T50/T51 `GovernanceState`，`background_jobs.state` 复用 T80 `JobState`；`DomainEvent` 以 outbox 行落库且 `payload` 继续遵守脱敏白名单；数据库只保存运行、审计、引用、任务与 outbox 元数据，不取代 CSV/Manifest/hash 证据包；`ApprovalSnapshot`、`GovernanceManifest` 与正式发布包仍由现有治理核心负责；数据库中的 artifact 只是一条引用与哈希，不代表审批通过。T81 不迁移、不重算、不覆盖任何科研数据。

测试证据：新增 `tests/test_t81_postgresql_schema.py` 与 `tests/test_t81_postgresql_migrations.py`。离线部分覆盖五张表与 Schema、约束/索引稳定命名、关键 CHECK 语义、映射完整性、URL 脱敏（含特殊字符密码）、缺失环境变量关闭式失败、离线 SQL 生成、downgrade 无破坏性语句、`import app` 不引入 SQLAlchemy/Alembic/Psycopg、内层无数据库框架依赖、科研目录哈希不变。集成部分（真实 PostgreSQL）只在显式提供安全 `STEELAI_TEST_DATABASE_URL` 时运行。

真实 PostgreSQL 验收（2026-09-17，项目负责人授权）：使用官方精确镜像 `postgres:18.6-alpine3.23`（Image ID = RepoDigest = `sha256:697c180d…`，`amd64/linux`，与 Docker Hub 官方 manifest index digest 一致）启动一次性容器 `steelai-t81-postgres-test`（标签 `com.steelai.task=T81`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，无 named volume），服务端为 `PostgreSQL 18.6 on x86_64-pc-linux-musl (gcc Alpine 15.2.0)`。**端口偏差**：`127.0.0.1:55432` 落在 Windows 保留端口段 `55368-55467`，绑定被系统拒绝，改用 `127.0.0.1:55468 → 5432`（仍为 loopback-only）。

验收结果：`upgrade head` → `current`/`heads` 均为 `0001_enterprise_baseline (head)` → `downgrade base`（业务表 0、trigger/function 0、索引 0、依赖对象 0，数据库未删除、Schema 保留为空、无 CASCADE）→ 再次 `upgrade head` 成功且 `current` 一致。catalog 实测 35 个命名约束（21 CHECK + 5 PK + 5 FK + 4 UNIQUE，缺失清单为空）、8 个业务索引、trigger `trg_audit_events_append_only` 与函数 `fn_audit_events_reject_mutation` 全部存在。直接 SQLSTATE 探针：audit UPDATE/DELETE → `23001`；重复幂等键 → `23505`（`uq_workflow_runs_idempotency_key`）；非法 request_digest、未登记 state、`revision=0`、非法 content_digest、未登记 evidence_class、以及 `.`/`..`/`./a`/`a/../b`/`a//b` 五种 relative_path → 均 `23514` 且约束名精确匹配；合法相对路径被接受。真实集成测试 **26 passed + 0 skipped + 28 subtests passed**（原 6 项 skip 全部实际执行）；未设置测试 URL 时仍为 20 passed + 6 skipped。回归：T81 schema 28 passed、T80 74 passed、全量 `.\scripts\test.ps1` **445 passed + 8 skipped + 169 subtests passed, 0 failed**。验收对非 schema/migration 代码的唯一修正：集成测试 `test_base_to_head_creates_every_declared_object` 的 `set(...) | {...}.issubset(...)` 运算符优先级缺陷（`TypeError`），改为先求并集再判断；Schema、migration、DDL、依赖与配置均未修改，修正后从空测试库重跑全部验收。验收容器已停止并因 `--rm` 自动删除，端口已释放，无新增 volume/network，凭据与本机 Docker 代理改动均已还原或清除。

边界：不修改 `requirements.txt` / `requirements-dev.txt`；不引入 psycopg2、asyncpg、FastAPI、Kafka、Redis、Celery、OpenTelemetry、Testcontainers；未在 Windows 宿主机安装 PostgreSQL（真实验收使用已恢复运行的 Docker Desktop 与一次性 PostgreSQL 容器，容器已删除、镜像按授权保留）；不新增页面、数据库开关或科研状态机；不改动 `app.py`、`pages/`、`Start_SteelAI.bat`、T76、科研 CSV 与方法注册表。

验收结果：Codex 最终复核通过，T81 由 `Review` 冻结为 `Done`，ADR-0002 同步转为 `accepted`。**T81 交付的是 PostgreSQL Schema、Alembic 迁移基线、显式连接配置与领域↔表映射契约，不是完整的 PostgreSQL Repository/UnitOfWork 持久化适配器**：`RunRepository`/`AuditRepository`/`ArtifactStore`/`EventPublisher`/`JobQueue`/`UnitOfWork` 的 PostgreSQL 实现、outbox 与业务写入同事务、dispatcher、worker、Kafka 与 API 均未实现，属于 T82 及以后，不得据此宣称已具备数据库持久化能力。（后续更新：其中 PostgreSQL Repository/UnitOfWork 与事务型 outbox 写入侧已由 T82 完成并转为 `Done`；outbox dispatcher、worker、Kafka 与 API 仍未实现。）

验收证据（2026-09-17 真实 PostgreSQL 18.6 验收 + 离线专项）：PostgreSQL 18.6 / Alpine / `amd64` 单机容器（官方精确镜像 `postgres:18.6-alpine3.23`，Image ID = RepoDigest = `sha256:697c180d…`）；`alembic upgrade head` → `downgrade base` → 再次 `upgrade head` 全部成功且 `current`/`heads` 一致；实测 35 个命名约束（21 CHECK + 5 PK + 5 FK + 4 UNIQUE，缺失清单为空）、8 个业务索引、trigger `trg_audit_events_append_only` 与函数 `fn_audit_events_reject_mutation` 全部存在；SQLSTATE 实测 `23514`（非法 request_digest / 未登记 state / `revision=0` / 非法 content_digest / 未登记 evidence_class / `.`、`..`、`./a`、`a/../b`、`a//b` 五种 relative_path）、`23505`（重复幂等键）、`23001`（audit UPDATE/DELETE 被 trigger 拒绝）。测试：`tests/test_t81_postgresql_migrations.py` 真实集成 **26 passed、0 skipped、28 subtests passed**；`tests/test_t81_postgresql_schema.py` **28 passed**；T80 回归 **74 passed**；全量 `.\scripts\test.ps1` **445 passed、8 skipped、169 subtests passed、0 failed**；`git diff --check` exit 0。

复核要点：T81 让冻结的 T80 回归测试中一条断言失效——`tests/test_t80_enterprise_architecture.py::ImportIsolationTests::test_runtime_surface_does_not_depend_on_forbidden_packages` 原先把“整个 `enterprise_lab` 包不得出现 SQLAlchemy/Psycopg/Alembic 导入”作为判据，而该报告扫描整包树，因此在 `adapters/postgresql/` 出现的依赖必然被计入。经项目负责人选择方案 A，仅把该断言的作用范围收窄到其原始意图（`domain`、`application`、`ports` 三个内层 + `adapters/memory.py` 仍必须零数据库框架依赖），测试项数量保持 74 项不变，未放宽任何内层约束；T81 自身的隔离测试另行保证内层与默认应用不得引入数据库框架。此项作为待复核事项明确列出。

契约修正（T81 复核意见）：其一，revision id 由 33 字符的 `0001_enterprise_metadata_baseline` 缩短为 24 字符的 `0001_enterprise_baseline`，不再超出 version table 的 `version_num VARCHAR(32)` 宽度，并新增断言校验 revision 长度不超过该宽度；其二，修复离线 SQL 顺序——此前 Alembic 的离线分支会先输出 `CREATE TABLE ...alembic_version_enterprise`，现在 `env.py` 的离线分支显式先输出 `CREATE SCHEMA IF NOT EXISTS`，测试比较两条语句的字节位置而非仅检查存在；其三，冻结初始迁移：`0001_enterprise_baseline` 不再导入 `schema.metadata`、删除 `_table_definition` 动态读取，五张表的列、主键、外键、唯一约束与 CHECK 约束全部在 revision 内显式声明，并新增“历史 revision 不得导入 `enterprise_metadata` 或使用运行时 `Table`/`MetaData`”的回归测试；其四，`relative_path` 的 CHECK 明确加入 `NOT IN ('.', '..')`，metadata、冻结迁移与离线 SQL 断言同步；其五，真实 PostgreSQL 非法行测试改为每个变体使用独立 `run_id` 与 `idempotency_key`，并断言具体 SQLSTATE（CHECK `23514`、唯一约束 `23505`、audit 只追加 `23001`）。

冻结收口（第二轮复核意见）：`0001_enterprise_baseline` 此前仍导入 `constraints.py` 的常量、状态词表与 SQL 生成函数，探针证明改动该模块会改变历史 DDL，因此未真正冻结。现该 revision **不导入任何 `steelai.*` 模块**，只允许 `__future__`、标准库、`alembic`、`sqlalchemy`、`sqlalchemy.dialects.postgresql`；naming convention、约束名、SHA/content digest 正则、`GovernanceState`/`ResultLevel`/`EvidenceClass`/`JobState` 的 T81 基线字面量、delivery status、relative_path CHECK SQL、audit trigger/function 名称与 SQL 全部在 revision 内部冻结，T81 基线变化必须新增 revision。live 侧 `schema.py` 继续使用 `constraints.py`，运行时代码不依赖 migration。原“冻结 revision 必须永久等于 live schema”的断言已删除，改为断言 revision 自身冻结的 T81 基线字面量与精确 relative_path 语义；新增 AST 断言（`versions/*.py` 不导入 `steelai`/live schema/constraints/domain、不访问运行时 Metadata、不调用共享 SQL 生成函数）与隔离探针（猴子补丁 `constraints` 后重新加载 revision，列、约束与 SQL 必须逐字节不变）。revision 长度、离线 SQL 顺序、裸点路径与 downgrade 安全测试均保留并复跑。

## 已完成任务 T82

任务定位：T82 只交付**可选的 PostgreSQL Repository/UnitOfWork 与事务型 Outbox 写入侧**，不包含事件投递器、Kafka、worker 服务、HTTP API、RBAC、多租户、生产备份与高可用，也**不把默认 SteelAI 应用接入数据库**。

完成情况：新增 `steelai/enterprise_lab/adapters/postgresql/` 下的 `_context.py`（单连接单事务上下文、advisory lock 入口）、`_locks.py`（稳定 SHA-256 派生的锁定键）、`errors.py`（SQLSTATE/约束名 → `ENT-*` 映射）、`hydration.py`（五类领域对象的行恢复）、`repositories.py`（`PostgreSQLRunRepository`、`PostgreSQLAuditRepository`、`PostgreSQLArtifactStore`、`PostgreSQLEventPublisher`、`PostgreSQLJobQueue`、`PostgreSQLUnitOfWork`、`PostgreSQLUnitOfWorkFactory`），并更新该包 `__init__.py`。仅把 `application/services.py` 中 `UnitOfWorkFactory` 的过时 docstring 从 “T81 replaces…” 改为 “T82 replaces…”，**未改任何服务逻辑**。

关键实现：`EnterpriseWorkflowService` 只替换注入的 Factory 即可运行在 PostgreSQL 上；一个 UoW 持有一个连接与一个事务，五个仓储共享，commit 原子提交全部写入，异常退出自动回滚，提交或回滚后任何旧句柄读写都返回 `ENT-UOW-001`，`committed` 是该 UoW 自身的永久结果标志；边界开始前调用 `commit()`/`rollback()` 返回 `ENT-UOW-001`，`begin()` 失败立即关闭连接，`commit()` 失败立即尝试 rollback、关闭连接并只抛脱敏 `ENT-DB-001`（rollback 失败不掩盖原异常、连接仍关闭）；**显式 `rollback()` 失败**时 `rolled_back=False`、连接与边界仍关闭、抛脱敏 `ENT-DB-001`（不静默成功），**正常离开未提交的 `with` 而自动 rollback 失败**同样抛脱敏 `ENT-DB-001`，只有 `with` 内已有异常正在传播时才保留原始业务异常；**所有仓储调用先校验 UoW 生命周期、再校验参数**，因此已关闭边界的保存句柄即使传入不匹配键也优先返回 `ENT-UOW-001`（PostgreSQL 与 Memory 一致），advisory lock 语句失败也经同一 SQLSTATE/约束名映射脱敏（并删除了仅 `safe_lock_key()` 使用的死代码）；幂等以 `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` 为裁决者（该语句形状下 psycopg 报 `rowcount = -1`，因此以是否返回行判定，不依赖"先 SELECT 再 INSERT"，也不在已中止事务上继续），且 `create_run` 先校验参数键与 run 自身键一致、不一致时在任何 SQL 之前以 `ENT-IDEMPOTENCY-001` 失败（Memory 适配器同步修正），同 `artifact_id` 只有在全部持久化字段一致时才 `reused=True` 否则 `ENT-ARTIFACT-001`；乐观并发使用 `UPDATE ... WHERE run_id=? AND revision=? RETURNING`；审计序号与 per-run outbox 序号各自使用带 SteelAI/T82 命名空间的 `pg_advisory_xact_lock`，`count()`/`append()` 与 `next_sequence()`/`publish()` 都在同一把锁内先取锁再读最大值，因此**正常并发写入都成功**（序号 1、2），只有直接提交陈旧/乱序序号才 `ENT-AUDIT-001`/`ENT-EVENT-001`；任务租约**不取 advisory lock**，只用 `SELECT ... FOR UPDATE SKIP LOCKED`（两个重叠事务租到不同任务，仅一个可用时第二个立即得到 `None`），`complete`/`fail`/`retry`/`cancel` 先 `SELECT ... FOR UPDATE` 锁行再做转换、`retry` 的 attempts 上限也在锁内判断；状态变化全部复用 `BackgroundJob.transition`，不另造状态机。

真实 PostgreSQL 验收（2026-09-17）：官方精确镜像 `postgres:18.6-alpine3.23`（Image ID = RepoDigest = `sha256:697c180d…`，`amd64/linux`），一次性容器 `steelai-t82-postgres-test`（标签 `com.steelai.task=T82`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，`RestartPolicy=no`，无 volume），`127.0.0.1:55468 → 5432`（loopback-only）；空库先执行 T81 `upgrade head` 再验收。22 项场景全部通过：完整纵向流程、单一 commit 后四类记录同时可见、四个写入阶段注入异常后五张表计数回到基线、未提交数据对第二连接不可见、相同请求重放不增加记录并返回原 ID、同键不同请求并发仅一个成功（另一个 `ENT-IDEMPOTENCY-001` 且无部分写入）、键不一致零写入、同 artifact_id 不同内容 `ENT-ARTIFACT-001`、并发状态更新仅一个成功（另一个 `ENT-CONCURRENCY-001`）、四个重叠审计写入全部成功且序号 1-4 唯一、两个重叠事务各自 `count()+1`→`append` 都成功（序号 1、2）、直接提交陈旧/跳跃序号 `ENT-AUDIT-001`/`ENT-EVENT-001`、两个重叠事务各自 `next_sequence()`→`publish` 都成功（序号 1、2）、顺序追加 outbox 为 1,2,3、两个重叠事务 Barrier 后各持一个不同任务、仅一个任务可用时第二个事务在第一个提交前立即得到 `None`、同一 leased 任务并发 `complete`/`fail` 只有一个成功（另一方 `ENT-JOB-001`、胜者结果未被覆盖）、`retry` 超限 `ENT-JOB-001`、commit/rollback 后五类句柄失效、audit UPDATE/DELETE 仍被 trigger 拒绝（`23001`）、仓储返回领域对象而非 `Row`/`Mapping`、连接归还连接池且无 `idle in transaction`。

离线测试证据（`tests/test_t82_postgresql_repositories.py`，**57 passed + 38 subtests**）：错误分类与脱敏、行恢复、两个作用域的稳定锁键、UoW 句柄生命周期、connect/begin/commit/rollback 失败生命周期（含**新增**"显式 `rollback()` 失败"与"正常离开未提交 `with` 时自动 rollback 失败"两项，均断言脱敏 `ENT-DB-001`、连接已关闭、旧句柄失效；另有既有的"`with` 内已有业务异常且 rollback 失败"用例断言保留原始异常并已补上旧句柄失效断言）、advisory lock 失败脱敏（保留结构化 `sqlstate`、不泄露 URL/密码/host）、生命周期优先于参数校验（PostgreSQL 与 Memory）、键不一致零 SQL、直接构造的 artifact 冲突。

测试证据：`tests/test_t82_postgresql_integration.py` 真实集成 **22 passed + 6 subtests**（连续复跑 3 次稳定）；T81 schema **28 passed**；T81 migrations（真实集成实跑）**26 passed + 0 skipped**；T80 回归 **74 passed**；`tests/test_streamlit_pages.py` **5 passed**；全量 `.\scripts\test.ps1`（保持安全测试 URL，T81/T82 集成实跑）**524 passed、8 skipped、213 subtests passed、0 failed**；`git diff --check` exit 0。

验收结果（2026-09-18）：**Codex 最终复核通过，T82 由 `Review` 冻结为 `Done`，ADR-0003 同步转为 `accepted`。两轮契约修正已经完成**：第一轮修正并发取号语义（审计 `count()+1`→`append` 与 per-run `next_sequence()`→`publish` 在重叠事务中**都成功**，序号 1、2；任务租约不使用 advisory lock，只用 `FOR UPDATE SKIP LOCKED`；`complete`/`fail`/`retry`/`cancel` 先 `SELECT ... FOR UPDATE` 锁行；UoW 失败生命周期关闭式处理；`idempotency_key` 参数与 run 自身键一致性前置校验），第二轮修正显式 `rollback()` 与正常退出自动 rollback 失败不得静默成功、advisory lock 错误脱敏、以及"所有仓储调用先校验 UoW 生命周期再校验参数"的校验顺序。验收证据：T82 离线测试 **57 passed + 38 subtests**；真实 PostgreSQL 18.6 集成测试 **22 passed + 6 subtests**；T81 migrations **26 passed + 0 skipped**；T81 schema **28 passed**；T80 回归 **74 passed**；Streamlit pages **5 passed**；全量测试 **524 passed、8 skipped、213 subtests、0 failed**；`git diff --check` exit 0。

**范围边界（必须与原状态一起引用，不得省略）**：T82 完成的是可选 PostgreSQL Repository、UnitOfWork、事务型 outbox 写入侧和数据库任务队列基础，**不代表**已经实现事件投递、Kafka、worker 服务、心跳与租约回收、HTTP API、RBAC、多租户、生产备份、高可用或 exactly-once。`outbox_events` 只有写入侧，**不得**声称事件已投递或 exactly-once；`leased` 任务不会因心跳缺失自动回收；默认 SteelAI 应用仍未接入数据库；正常并发取号不会关闭式失败（锁会串行化等待），因此 T82 不提供也不需要调用方重试循环。

边界：未修改 T80 的 domain 与 ports 契约、T81 的 `schema.py`/`constraints.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements 文件、`app.py`/`pages/`、科研数据、方法注册表、治理状态机、Memory 适配器语义与 T76；未安装 PostgreSQL 到 Windows 宿主机；容器已删除、端口已释放、无新增 volume，随机密码已销毁；未 commit/push/tag。

## 已完成任务 T83

任务定位：T83 只在 T82 建立的 outbox 写入侧之上补上**派发侧**闭环——领取 → 外部发送 → 成功确认 / 失败重试 → 过期租约恢复；交付语义是 **at-least-once**。它**不接** Kafka/RabbitMQ/Redis/Celery，**不实现**常驻 worker、daemon、定时器或调度器，**不新增**数据库列或迁移，**不修改** T80 领域模型与既有 Port 契约、T81 Schema/迁移/DDL 或三个 requirements 文件，**不接入**默认应用。

完成情况：新增 `steelai/enterprise_lab/ports/outbox.py`（不可变 `OutboxClaim`/`OutboxReclaim`/`OutboxDeliveryState`、`OutboxDeliveryRepository`、`EventTransport`、`TransportError`、四个稳定错误码与安全码校验）、`steelai/enterprise_lab/application/outbox_dispatcher.py`（`OutboxDispatcher` 的有限调用 `dispatch_batch`/`reclaim_expired`、`OutboxDispatcherConfig`、`OutboxDispatchOutcome`）、`steelai/enterprise_lab/adapters/outbox_memory.py`（`MemoryOutboxDeliveryRepository` + `RecordingEventTransport`，无网络与文件 I/O）、`steelai/enterprise_lab/adapters/postgresql/outbox.py`（`PostgreSQLOutboxDeliveryRepository`，复用既有 `outbox_events` 五列，短事务）。投递状态**不进入** `DomainEvent`，T80 的 `EventPublisher` 契约未改。

关键实现：领取在同一短事务内执行 `SELECT ... FOR UPDATE SKIP LOCKED`（谓词含 `pending`、`available_at <= now()`、`attempts < max_attempts`、`sequence = min(该 run 尚未 published 的 sequence)`）再 `UPDATE ... SET delivery_status='publishing', attempts = attempts + 1, available_at = now() + make_interval(secs => lease_seconds) ... WHERE attempts = :seen_attempts RETURNING *`；**领取事务在 `transport.send` 之前提交并归还连接**，确认与记失败各自是新的短事务；`attempts` 即 fencing token，`mark_published`/`mark_failed` 只在 `publishing` 且 `attempts` 匹配时生效，否则 `ENT-OUTBOX-CLAIM-001`；成功写 `published_at`（数据库时间）并清空 `last_error_code`；可重试失败回到 `pending` 并设指数退避（基值翻倍、封顶），不可重试或 `attempts` 达上限进入 `failed` 且不再领取；过期租约（`publishing` 且 `available_at <= now()`）在 `attempts` 未达上限时回到 `pending`、已达上限时进入 `failed`，固定写入 `ENT-OUTBOX-LEASE-EXPIRED`；同一 run 严格按 `sequence` 投递，前序事件 `failed` 会持续阻塞后序事件（无跳过、无人工解锁）；不同 run 可并发领取。错误边界只保存安全字段：未知 transport 异常 → `ENT-OUTBOX-TRANSPORT-001`，失效领取 → `ENT-OUTBOX-CLAIM-001`，配置非法 → `ENT-OUTBOX-CONFIG-001`，数据库异常沿用 T82 的 SQLSTATE 脱敏映射。

交付语义（必须随结论一起引用）：T83 是 **at-least-once**，**不是** exactly-once；transport 发送成功但数据库确认失败（含进程崩溃、确认事务失败、租约被接管）时，事件会在租约恢复后**再次发送**，因此**下游必须以 `event_id` 作为幂等键**；`RecordingEventTransport` 只能证明接口与流程，**不代表 Kafka 已接入**；T83 不提供常驻 worker、监控、告警或人工重放控制台。

派发结果（第一轮契约修正后）：只有五种状态，三个属性**只由 status 推导**，调用方不能传入互相矛盾的组合——`published`（delivered=true / known=true / redelivery=false）、`retry_scheduled`（false / true / true）、`failed_terminal`（false / true / false）、**`sent_unacknowledged`（true / false / true）**＝确实发送过但确认未提交、最终状态未知、**`failure_unrecorded`（false / false / true）**＝没有发送成功且失败状态也未记录，**绝不得报告为 delivered**；未知 status 被 `OutboxDispatchOutcome` 以 `ENT-OUTBOX-CONFIG-001` 拒绝；旧的 `needs_redelivery` 已删除。DTO 自带契约校验：`OutboxClaim` 只接受 `publishing` + 正整数 `claim_attempt` + 带时区 `lease_deadline`（`pending`/`published`/`failed` 的 claim 被拒绝），`OutboxReclaim` 只接受 `pending`/`failed` + 正 `attempts` + 通过安全校验的 `last_error_code`，两者均可**直接构造**并接受同一套校验。公共入口：`ports`（契约与状态码）、`application`（Dispatcher/Config/Outcome/状态常量）、`adapters`（内存投递适配器与 Recording Transport）、`adapters.postgresql`（PostgreSQL 投递适配器），顶层 `steelai.enterprise_lab` 只导出不需要可选 PostgreSQL 依赖的 T83 类型。

真实 PostgreSQL 验收（2026-09-18）：官方精确镜像 `postgres:18.6-alpine3.23`（Image ID = RepoDigest = `sha256:697c180d…`，`amd64/linux`），一次性容器 `steelai-t83-postgres-test`（标签 `com.steelai.task=T83`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，`RestartPolicy=no`，无 volume），`127.0.0.1:55468 → 5432`（loopback-only）；空库先执行 T81 `upgrade head` 再验收，**未新增列或迁移**。17 项场景全部通过（0 skipped）：两个 dispatcher 并发领取不重复、不同 run 可同时 `publishing`、同一 run 只领取最小未发布 `sequence`、空队列立即返回、`attempts` 原子递增并作为 fencing token、旧 worker 无法确认新租约、租约过期后可重新领取、过期且达上限进入 `failed`、成功确认写入 `published_at`、重试 `available_at` 使用数据库时钟、claim/send/ack 之间无 checked-out connection、结束无 `idle in transaction`、T82 写入的 `pending` 行可被正常消费、前序 `failed` 阻塞后序事件、确认失败＝`sent_unacknowledged`（真实约束拒绝确认后回滚、租约恢复后同键重发并最终 `published`）、失败无法记录＝`failure_unrecorded`（`delivered=False`、行保持 `publishing`、租约恢复后成功投递）、transport 失败只持久化安全错误码。

测试证据：`tests/test_t83_outbox_dispatcher.py` 离线 **67 passed + 74 subtests**（含 transport 调用发生在领取边界关闭之后、`event_id` 幂等键、退避与终止判定、原始异常不泄漏、fencing、租约恢复、同 run 顺序、不同 run 并发、非法配置关闭式失败、Recording Transport 不访问网络或文件系统、at-least-once 恢复路径、架构边界与 `import app` 不加载 dispatcher）；`tests/test_t83_outbox_integration.py` 真实集成 **17 passed**（0 skipped，连续复跑 3 次稳定）；回归：T80 **74 passed**、T81 schema **28 passed**、T81 migrations **26 passed + 0 skipped**、T82 离线 **57 passed**、T82 集成 **22 passed**、Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **608 passed、8 skipped、287 subtests passed、0 failed**；`git diff --check` exit 0。

验收结果（2026-09-18）：

- Codex 最终技术复核通过；
- 第一轮契约修正完成；
- outcome 已拆分为 `published`、`retry_scheduled`、`failed_terminal`、`sent_unacknowledged`、`failure_unrecorded`；
- `failure_unrecorded` 不再错误报告为 delivered（`delivered=False`、`persistence_state_known=False`、`redelivery_possible=True`）；`sent_unacknowledged` 表示"确实发送过、确认状态未知"；
- `OutboxClaim`/`OutboxReclaim` DTO 契约已收紧（claim 只接受 `publishing` + 正整数 `claim_attempt` + 带时区 `lease_deadline`；reclaim 只接受 `pending`/`failed` + 正 `attempts` + 安全 `last_error_code`，两者均可直接构造并接受同一套校验）；
- T83 公共包出口已经收口（`ports`/`application`/`adapters`/`adapters.postgresql` 各导出对应契约与实现，顶层 `enterprise_lab` 只导出不需要可选 PostgreSQL 依赖的类型）；
- T83 离线 **67 passed + 74 subtests**；
- 真实 PostgreSQL 18.6 集成 **17 passed + 0 skipped**，连续复跑稳定；
- T82 离线/集成 **57/22 passed**；
- T81 schema/migrations **28/26 passed**，真实集成 **0 skipped**；
- T80 回归 **74 passed**；
- Streamlit pages **5 passed**；
- 全量 **608 passed、8 skipped、287 subtests、0 failed**；
- `git diff --check` exit 0。

**边界（必须随验收结论一起引用，不得省略）**：

- T83 是**有限调用**的 outbox dispatcher（`dispatch_batch` / `reclaim_expired`），**不是常驻 worker**：无 daemon、无定时器、无调度器；
- 只提供 **at-least-once**，**不提供 exactly-once**；
- `RecordingEventTransport` **不代表 Kafka**（它只在内存记录，不进行任何网络访问）；
- **无真实 broker**、无调度器、无监控、无告警、无人工重放控制台；
- `failed` 事件继续**阻塞同一 run 的后序事件**（无跳过、无人工解锁入口）；
- **下游必须使用 `event_id` 幂等**去重（确认失败后事件会在租约恢复时再次发送）。

边界：未修改 T80 领域模型与既有 Port 契约、T81 `schema.py`/`constraints.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements 文件、`app.py`/`pages/`、科研数据、方法注册表与治理配置；未新增数据库列或迁移、未新增第三方依赖；未安装 PostgreSQL 到 Windows 宿主机；容器已删除、端口已释放、无新增 volume，随机密码已销毁；未 commit/push/tag，未启动 T84。

## 已完成任务 T84

任务定位：T84 只在 T82 已建立的 `background_jobs` 表与 T80 任务状态机之上补上**执行侧**闭环——领取任务 → 事务外执行 Handler → 心跳续租 → 成功确认 / 失败重试 → 过期租约恢复；执行语义是 **at-least-once**。它**不接** Kafka/Redis/Celery/RabbitMQ/FastAPI，**不实现**常驻 worker、Windows 服务、daemon、无限循环、定时器或自动启动，**不新增**表、列、索引、迁移或第三方依赖，**不修改** T81 冻结迁移/Schema/约束，**不接入**默认应用，也**不执行**真实科研计算或读写科研文件。

完成情况：新增 `steelai/enterprise_lab/ports/workers.py`（不可变 `JobLease`/`JobExecutionState`、`JobExecutionRepository`、`JobHandler`、`JobHandlerRegistry`、`JobExecutionContext`、`JobHandlerError` 与安全 token/错误码校验）、`steelai/enterprise_lab/application/job_worker.py`（`JobWorker` 的有限调用 `run_once`/`run_batch`/`reclaim_expired`、`JobWorkerConfig`、`JobOutcome`、`OUTCOME_PROPERTIES`）、`steelai/enterprise_lab/adapters/worker_memory.py`（`MemoryJobExecutionRepository` + `RecordingJobHandler`，无任何 I/O）、`steelai/enterprise_lab/adapters/postgresql/worker.py`（`PostgreSQLJobExecutionRepository`，复用既有表，短事务）。T80 `JobQueue` 与 T82 `PostgreSQLJobQueue` 语义未改；执行确认**不调用** T82 无 fencing 参数的 `complete`/`fail`；投递/执行状态都不进入 `BackgroundJob` 或 `DomainEvent`。

关键实现：领取在同一短事务内 `SELECT ... FOR UPDATE SKIP LOCKED`（`state IN ('queued','retrying')`，`ORDER BY created_at, job_id`，`LIMIT 1`）后 `UPDATE ... SET state='leased', lease_id=:lease_id, updated_at=now() ... RETURNING *`，写入**全新** `lease_id`，`updated_at` 使用数据库时间，**第一次领取不增加 `attempts`**（新建任务已是 `attempts=1`）；Handler 在**任何事务之外**执行，成功/失败确认各自是新的短事务；`heartbeat` 以 `state='leased' AND job_id AND lease_id AND attempts=:attempt` 为条件把 `updated_at` 刷新为数据库时间；过期判断为 `updated_at <= now() - lease_timeout_seconds`；成功 `leased→succeeded`（清除 `lease_id`/`error_code`）；可重试失败在同一事务内做两次合法转换 `leased→failed→retrying`（`attempts+1`、清除 `lease_id`、保存安全错误码），达上限或不可重试则 `leased→failed`；过期租约未达上限 → `retrying`（`attempts+1`）、已达上限 → `failed`，固定写入 `ENT-WORKER-LEASE-EXPIRED`；不新增 `JobState`、不改 `ALLOWED_JOB_TRANSITIONS`、不写第二套状态机（唯一领域层扩展是 `BackgroundJob.transition(..., clear_lease=True)`，默认行为不变）。

派发结果（初始即区分五种，避免 T83 的 outcome 混淆）：三个属性**只由 status 推导**——`succeeded`（handler_succeeded=true / known=true / reexecution=false）、`retry_scheduled`（false/true/true）、`failed_terminal`（false/true/false）、**`success_unrecorded`（true/false/true）**＝Handler 已执行成功但成功状态未提交、租约过期后可能再次执行、**`failure_unrecorded`（false/false/true）**＝Handler 失败且失败状态也未提交；两种未知状态都不得写成最终成功，未知 status 被 `JobOutcome` 以 `ENT-WORKER-CONFIG-001` 拒绝。错误边界只保存安全字段：未知 Handler 异常 → `ENT-WORKER-EXECUTION-001`，未注册 Handler → `ENT-WORKER-HANDLER-NOT-FOUND`（不可重试，写入 `failed`），失效领取/`attempts` 不匹配 → `ENT-WORKER-CLAIM-001`，非法配置 → `ENT-WORKER-CONFIG-001`，数据库异常沿用 T82 SQLSTATE 映射；**禁止**保存 traceback、异常消息、URL、host、凭据、payload 内容或文件路径。Handler 只拿到 `job_id`/`job_type`/`run_id`/`attempt`/`max_attempts`/`payload_digest`/`idempotency_key` 与 `heartbeat()`；Registry 只支持显式注册，禁止动态 import 或按字符串加载模块。

真实 PostgreSQL 验收（2026-09-18）：官方精确镜像 `postgres:18.6-alpine3.23`（Image ID = RepoDigest = `sha256:697c180d…`，`amd64/linux`），一次性容器 `steelai-t84-postgres-test`（标签 `com.steelai.task=T84`、`com.steelai.purpose=integration-test`，`--rm`，`--tmpfs /var/lib/postgresql`，`RestartPolicy=no`，无 volume），`127.0.0.1:55468 → 5432`（loopback-only）；空库先执行 T81 `upgrade head` 再验收，**未新增表/列/索引/迁移**。25 项场景全部通过（0 skipped）：T82 `queued` 任务可被 Worker 执行、两个并发 Worker 不重复领取、两个任务可重叠执行、仅一个任务时第二个 Worker 立即得到 `None`、Handler 执行时无连接被占用、成功后 `state=succeeded` 且 `lease_id`/`error_code` 为空、可重试失败原子进入 `retrying` 且 `attempts+1`、下一次领取获得全新 `lease_id`、达 `max_attempts` 后 `failed`、心跳使用数据库时间、心跳后在超时内不被回收、超时后被回收、旧 Worker 三种写入全部 `ENT-WORKER-CLAIM-001`、新 Worker 状态未被覆盖、`success_unrecorded` 后租约恢复并重新执行、`failure_unrecorded`、未注册 Handler 安全失败、无原始异常文本进入 `error_code`、所有短事务后 pool 归零、无 `idle in transaction`、T82 complete-vs-fail 并发语义仍成立、T83 Dispatcher 回归不受影响、真实库上 Handler `DomainError` 只留下 `ENT-WORKER-EXECUTION-001` 且不残留 `leased`、真实 outcome 与数据库行逐项一致、真实 Repository+Handler 组合执行成功。

测试证据：`tests/test_t84_job_worker.py` 离线 **72 passed + 65 subtests**；`tests/test_t84_job_worker_integration.py` 真实集成 **25 passed + 6 subtests**（0 skipped，连续复跑稳定）；回归：T80 **74 passed**、T81 schema **28 passed**、T81 migrations **26 passed + 0 skipped**、T82 离线 **57 passed**、T82 集成 **22 passed**、T83 离线 **67 passed + 74 subtests**、T83 集成 **17 passed**、Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **705 passed、8 skipped、358 subtests passed、0 failed**；`git diff --check` exit 0。

验收结果（2026-09-18）：**Codex 最终技术复核通过，T84 于 2026-09-18 由 `Review` 转为 `Done`，ADR-0005 同步由 `proposed` 转为 `accepted`**。

- **第一轮修正**（初始实现的契约收口）：五种 Worker Outcome 由 status 唯一推导（`handler_succeeded`/`persistence_state_known`/`reexecution_possible`），并让 `JobOutcome` 初始即区分 `success_unrecorded` 与 `failure_unrecorded`，避免重复 T83 的 outcome 混淆；`JobExecutionContext` 只暴露安全元数据；Registry 显式注册；失败重试复用 `leased→failed→retrying` 两次合法转换；过期租约恢复按 `attempts` 是否达上限进入 `retrying` 或 `failed`。
- **第二轮修正**（两个缺口的修复）：其一，**Handler 异常边界**——`JobHandlerError` 之外的**一切 `Exception`（含 `DomainError`）**统一视为未分类失败并脱敏转换为 `JobHandlerError(ENT-WORKER-EXECUTION-001, retryable=True)`，因此不再中断 `run_once`/`run_batch`、不再泄漏原始 `code`/`message`/`details`/URL/host/凭据/路径、任务被正常记入 `retrying`（达上限则 `failed`）而**不残留 `leased`**；`KeyboardInterrupt`/`SystemExit` 等 `BaseException` **不吞掉**；修复点位于 Handler 执行边界，`run_batch` 外层没有笼统吞异常，Repository 领取错误与非法配置仍照常抛出。其二，**JobOutcome 完整不变量**——`succeeded` 必须 `state=succeeded`/`attempts==attempt`/无错误码，`retry_scheduled` 必须 `state=retrying`/`attempts==attempt+1`/错误码必填，`failed_terminal` 必须 `state=failed`/`attempts==attempt`/错误码必填，`success_unrecorded` 与 `failure_unrecorded` 必须 `state=None`/`attempts=None`/错误码必填；任何不匹配（含 `bool`/负数/字符串 `attempts`）以 `ENT-WORKER-CONFIG-001` 关闭式失败。
- 完整测试与真实数据库证据：离线 **72 passed + 65 subtests**；真实 PostgreSQL 18.6 集成 **25 passed + 6 subtests（0 skipped，连续复跑稳定）**；回归 T80 **74 passed**、T81 schema **28 passed**、T81 migrations **26 passed + 0 skipped**、T82 离线/集成 **57/22 passed**、T83 离线/集成 **67 passed + 74 subtests / 17 passed**、Streamlit pages **5 passed**；全量 `.\scripts\test.ps1` **705 passed、8 skipped、358 subtests、0 failed**；`git diff --check` exit 0；14 项冻结哈希复测 mismatches = 0。

遗留（真实存在，不造成状态丢失或 fencing 失效，但不得隐藏或写成已解决）：`lease_timeout_seconds` 是进程配置且没有逐任务持久化；心跳频率由 Handler 决定，长任务不心跳会被回收并重复执行；无取消运行中任务、无调度/优先级/限流、无监控告警指标与死信队列；`failed` 需人工处置；无 payload/对象存储；`RecordingJobHandler` 不代表真实科研任务；只在 PostgreSQL 18.6 单实例验证。

**范围边界（必须随验收结论一起引用，不得省略）**：

- T84 仅为**有限调用式执行基线**（`run_once` / `run_batch` / `reclaim_expired`），**不是常驻 worker 服务**；
- 只提供 **at-least-once**，**不是 exactly-once**；
- Handler 若产生外部副作用，**必须使用稳定 `job_id` 作为幂等键**；
- **enqueue 的 `idempotency_key` 不能替代 `job_id`**（它只保证入队不重复，无法阻止确认失败或租约恢复后的再次执行）；
- **无常驻 worker 服务、无调度器、无 Kafka、无真实 broker、无监控告警、无人工重放控制台、无 HTTP API、无 RBAC、无多租户、无生产备份或高可用**；
- **默认 Streamlit 应用仍未接入 Enterprise Lab**（`app.py`、`pages/`、T76 启动器都不导入 T84 代码）。

第二轮契约修正（2026-09-18，两个缺口）：其一，**Handler 异常边界**——此前 `handler.execute` 抛出的 `DomainError` 会被重新抛出，导致 `run_once`/`run_batch` 中断、原始 `code`/`message`/`details` 泄漏、任务残留 `leased`；现在 `JobHandlerError` 之外的**一切 `Exception`（含 `DomainError`）** 都视为未分类失败并统一转换为 `JobHandlerError(ENT-WORKER-EXECUTION-001, retryable=True)`，因此不再中断批次、不再泄漏原始信息、任务被正常记入 `retrying`（达上限则 `failed`）而不会残留租约；`KeyboardInterrupt`/`SystemExit` 等 `BaseException` **不吞掉**（操作员信号照常传播，租约留给过期恢复）；修复点位于 Handler 执行边界，`run_batch` 外层没有笼统吞异常，Repository 领取错误与非法配置仍照常抛出（均有专项测试）。其二，**JobOutcome 完整不变量**——`succeeded`/`retry_scheduled`/`failed_terminal` 必须报告与之匹配的持久化 `state`（`succeeded`/`retrying`/`failed`）、正确的 `attempts`（`attempt`/`attempt+1`/`attempt`）与错误码要求（成功必须为 `None`，失败必填），`success_unrecorded`/`failure_unrecorded` 必须 `state=None`、`attempts=None` 且携带安全错误码；任何不匹配（含 `bool`/负数/字符串 `attempts`）都以 `ENT-WORKER-CONFIG-001` 关闭式失败，表驱动测试覆盖 19 类矛盾组合，并验证五条真实输出路径全部满足新不变量。本轮新增离线测试 13 项（`HandlerExceptionBoundaryTests` 8 项 + `JobOutcomeInvariantTests` 5 项）、真实集成 3 项（场景 23–25）；离线由 59 提升到 **72 passed + 65 subtests**、集成由 22 提升到 **25 passed + 6 subtests**、全量由 689 提升到 **705 passed、8 skipped、358 subtests、0 failed**。幂等边界再次明确：外部副作用必须以稳定 `job_id` 为幂等键，enqueue 的 `idempotency_key` **不能**替代该要求。

边界：未修改 T80 领域模型（唯一例外是 `BackgroundJob.transition` 新增向后兼容的 `clear_lease=True`）与既有 `JobQueue`/`EventPublisher` 契约、T81 `schema.py`/`constraints.py`/`0001_enterprise_baseline.py`/`env.py`/`alembic-enterprise.ini`、三个 requirements 文件、`app.py`/`pages/`、科研数据、方法注册表与治理配置；未新增表、列、索引、迁移或第三方依赖；未读取科研文件、未执行真实模型、未保存原始实验值；未安装 PostgreSQL 到 Windows 宿主机；容器已删除、端口已释放、无新增 volume，随机密码已销毁；未 commit/push/tag，未启动 T85。

## 已完成任务 T85

任务定位：T85 是**纯文档任务**，用于正式冻结 T80–T84 企业化演练阶段并收口后续路线。它**不新增任何运行能力**：不写代码、不加测试、不加依赖、不加 Schema/迁移、不启动 Kafka/API/微服务、不接入默认应用。任务完成时**保持 `Review`** 等待复核，随后于 2026-09-18 经 Codex 最终复核转为 `Done`（见下"验收结果"）；**不创建 T86**。

阶段能力总结（T80–T84 全部完成真实验收并已被接受）：

- **T80**：六边形架构边界与内存纵向流程——`domain`/`application`/`ports`/`adapters` 四层与六个 `typing.Protocol` Port，配纯 Python 内存适配器演示"创建运行 → 登记 artifact → 追加审计 → 生成事件 → 提交"的最小链路，并明确内存实现**不是**数据库事务；
- **T81**：PostgreSQL Schema、Alembic 迁移与连接基线——`steelai_enterprise` 五张业务元数据表、手写冻结迁移 `0001_enterprise_baseline`、`alembic-enterprise.ini`、可选依赖清单 `requirements-enterprise.txt`，连接串必须显式提供且缺失时关闭式失败；
- **T82**：PostgreSQL Repository/UnitOfWork、事务型 outbox **写入侧**和数据库任务队列——五个 PostgreSQL 仓储共享一个连接与一个事务，`INSERT ... ON CONFLICT DO NOTHING ... RETURNING` 裁决幂等、受保护的 `UPDATE ... RETURNING` 做乐观并发、`FOR UPDATE SKIP LOCKED` 做任务租约，SQLSTATE/约束名脱敏映射；
- **T83**：有限调用式 outbox dispatcher——`dispatch_batch`/`reclaim_expired`；`FOR UPDATE SKIP LOCKED` 短事务领取、`attempts` 作为 fencing token、同 run 严格按 `sequence`、指数退避与终止失败、过期租约恢复；**transport 调用在领取事务关闭之后**；at-least-once，下游以 `event_id` 幂等；
- **T84**：有限调用式 background job worker——`run_once`/`run_batch`/`reclaim_expired`；全新 `lease_id` 与 `job_id + lease_id + attempt` 三元 fencing、心跳以数据库时间刷新 `updated_at`、过期租约恢复、失败重试复用两次合法转换；Handler 在任何事务之外执行且只见安全元数据；at-least-once，Handler 外部副作用以稳定 `job_id` 幂等。

阶段定位与冻结结论：

- Enterprise Lab 是**可选参考实现**，是"企业化契约与边界"的演练产物，**不是**默认 SteelAI 运行链路，也**不是**生产平台；
- **默认应用不导入、不连接、不自动启动**：`app.py`、`pages/`、Streamlit 默认入口、T76 启动器与既有科研链路都不导入 Enterprise Lab；没有 `STEELAI_ENTERPRISE_DATABASE_URL` 时应用照常完全离线运行；
- 阶段已验证的是**契约与边界**：PostgreSQL 18.6 单实例上的 Schema/迁移、Repository/UoW、事务型 outbox 写入侧、dispatcher、worker/heartbeat/lease recovery，以及幂等、事务、fencing 与脱敏边界；
- 阶段**明确不是**：默认应用数据库化、生产级任务平台、Kafka 或任何真实 broker、常驻服务、exactly-once、API/RBAC/多租户、高可用/备份/灾难恢复方案；
- 当前全量基线 **705 passed、8 skipped、358 subtests、0 failed**（T84 验收时点，实时 PostgreSQL 集成实跑 0 skipped；`git diff --check` exit 0）。

重新开启企业化实施的触发条件（出现前不启动）：多用户并发写入成为真实需求；任务必须跨进程长期运行；需要与外部系统投递事件；需要 HTTP API 与权限控制；需要生产部署、监控、备份或高可用。触发条件出现前：不接 Kafka、不拆微服务、不引入 Kubernetes/服务网格/Redis/Celery/RabbitMQ、不把 Enterprise Lab 接入默认 Streamlit。

后续路线：T76 真实桌面验收；经负责人授权后整理 Git 基线（本轮不做任何 Git 操作）；完成一轮真实 Streamlit 使用验收；每次只选择一个真实科研或用户阻塞问题实施；T63/T64 保持延期条件不变（继续 `Review`）。

测试证据与验证范围：T85 不新增测试。阶段基线沿用 T84 验收时点的 T80 **74 passed**、T81 schema **28 passed**、T81 migrations **26 passed + 0 skipped**、T82 离线/集成 **57/22 passed**、T83 离线/集成 **67 passed + 74 subtests / 17 passed**、T84 离线/集成 **72 passed + 65 subtests / 25 passed + 6 subtests（0 skipped）**、Streamlit pages **5 passed**、全量 `.\scripts\test.ps1` **705 passed、8 skipped、358 subtests、0 failed**、`git diff --check` exit 0、14 项冻结哈希 mismatches = 0。**本轮未运行** pytest、Docker、PostgreSQL 或 Streamlit。

验收结果（2026-09-18）：

- **Codex 最终复核通过**；
- **T85 于 2026-09-18 转为 `Done`**；
- **T80–T85 企业化演练阶段正式冻结**：T80–T84 五个任务全部 `Done`，ADR-0001～ADR-0005 全部 `accepted`，阶段收尾文档 `docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md` 记录了阶段能力地图、非生产边界、重新开启条件与后续路线；
- **不新增运行能力**：本轮及其冻结结论都不增加代码、测试、依赖、Schema、迁移、后台进程或默认应用接入；Enterprise Lab 仍是可选参考实现；
- **后续只有在已记录的真实触发条件出现时，才能用新任务和新 ADR 重新启动**：触发条件为多用户并发写入成为真实需求、任务必须跨进程长期运行、需要与外部系统投递事件、需要 HTTP API 与权限控制、需要生产部署/监控/备份或高可用；届时按新任务编号立项，并由新 ADR 明确取代、修订或废止既有决策（既有 ADR 作为本阶段历史决策冻结，不直接改写）；
- 触发条件出现前仍不接 Kafka、不拆微服务、不引入 Kubernetes/服务网格/Redis/Celery/RabbitMQ、不把 Enterprise Lab 接入默认 Streamlit；
- 测试基线沿用 T84 验收时点：全量 **705 passed、8 skipped、358 subtests、0 failed**（`git diff --check` exit 0，14 项冻结哈希 mismatches = 0），**本轮未重新运行** pytest、Docker、PostgreSQL 或 Streamlit。

边界：本轮只修改 `TASKS.md`、`docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md` 与 `project_log/CHANGELOG.md` 三个文档；未修改任何 Python/PowerShell/BAT/CMD、测试、Schema 或 migration、requirements 文件、科研数据、方法注册表与治理配置、T80–T84 的实现与既有 ADR 技术决策、`app.py`/`pages/`/默认 Streamlit 入口、`docs/ARCHITECTURE.md`、`docs/CURRENT_CAPABILITIES.md`、`docs/KNOWN_LIMITATIONS.md`、T63/T64/T76 的状态与 Git 历史；未启动 Kafka/API/微服务；**未创建 T86**；未 commit/push/tag。详细阶段收尾说明见 `docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`。

## 受阻任务 T86

任务定位：把模型登记册里已有的 pycalphad 候选（`readiness=database_required`）接入物理计算，做成**可关闭的本地功能**。第一阶段只做“固定样品成分下，平衡相分数随温度变化”的计算与展示，不写回正式实验数据，也不把该曲线称为完整相图。

完成情况：新增 `steelai/calphad_adapter.py`（门禁、单位与输出基准声明、wt.%→摩尔分数换算、TDB 登记校验、请求构造、worker 调度与结果校验，主应用**不导入** pycalphad）、`scripts/calphad_phase_fraction_worker.py`（在独立解释器中运行，复核 pycalphad 版本与 TDB SHA-256 后求解平衡，按基相名聚合相成分集）、`config/calphad_adapter_v1.0.json`（第三方登记 + 方法/单位约定 + 原子量表 + 声明边界）、`config/calphad_tdb.example.json`（本地 TDB 登记模板）；物理计算页新增第 4 个页签“平衡相分数—温度（可选 · T86）”，模型实验室同步显示 CALPHAD 真实本地状态与入口指引。

单位与基准：输入成分 `wt.%`、温度 `°C`（内部 `T_K = T_degC + 273.15`）、压力固定 `101325 Pa`；**输出为各相摩尔分数**（`NP_phase / ΣNP`），不换算质量分数，界面与下载记录都逐项标注。

关闭式规则：TDB 缺少任何**非零**元素一律阻断且没有覆盖开关（不省略、不补零）；“已声明但无值”的元素不得按 0 处理，必须补值或由具名用户声明排除；Fe 按余量计算必须由具名用户确认；成分中 `0 wt.%` 且不在 TDB 内的元素记录为排除项但不阻断；超出 TDB 声明温度区间只警告并标注“模型外推”。结果统一标为 `model_prediction_not_experimental_measurement` + `pending_human_review`，不写回 `data/processed/`。

第三方登记（2026-09-24 核对官方 PyPI JSON 元数据与固定 tag 上的 LICENSE.txt，并用 GitHub REST API 解析 tag 提交）：`pycalphad 0.11.2`、MIT、仓库 `https://github.com/pycalphad/pycalphad`、源码引用 `2d4c744ddb890e179542894d070150797e13b325`、sdist SHA-256 `588ad2c0…`、`cp312 win_amd64` wheel SHA-256 `53f65477…`、`requires-python >=3.11`；未下载、未安装、未复制任何第三方代码，三个 requirements 文件未修改。

测试证据：`tests/test_t86_calphad_adapter.py` **42 passed**（登记/许可证/哈希、缺失环境、缺失依赖、版本不符、缺失与非法 TDB 登记、哈希不符、未授权数据库、非零元素未覆盖、无值元素、Fe 余量确认、单位与基准声明、温度区间门禁、worker 结果校验、相成分集聚合、阻断预览不调用 worker、结果标注与“不是完整相图”、模型登记册集成、worker 脚本契约）。`tests/test_physics.py` 与 `tests/test_streamlit_pages.py` 通过（页面测试实际渲染含阻断分支的物理页）。全量入口 `.\scripts\test.ps1` 在受限文件沙箱中会因所有 `tempfile` 夹具 `WinError 5` 失败（与本项目 T76 记录的环境限制相同），**不得改写既有夹具绕过**，需在普通用户终端重跑。

受阻原因与解除条件：项目当前**没有 TDB，也没有安装 pycalphad**。解除条件为：(1) 用户提供有使用授权且适用于目标钢种的 TDB（含来源、版本、授权依据、覆盖元素、温度区间与 SHA-256）；(2) 用户明确同意把 `pycalphad==0.11.2` 安装到独立环境。**在此之前不安装软件，也不声称完成真实钢种计算验收**；真实成分的相分数结果、TDB 适用性判断与相分数—温度的冶金解释都仍待人工复核。

边界：未修改 `requirements*.txt`、既有经验公式注册表与计算路径、`data/processed/` 科研数据、T52 治理内核与发布流程、T40/v0.2 冻结边界、T76/T85 状态；未新增 Streamlit 页面；未 commit/push/tag。

### 第二阶段（2026-09-25）：独立环境、数据库与兼容性门禁

项目负责人正式确定技术路线（`pycalphad==0.11.2` + MatCalc `mc_fe v2.062`），并批准在独立环境安装固定版本依赖、从 TU Wien 官方来源取得该数据库用于本地验证。

完成情况：

- 建立 `.venv-pycalphad`（CPython 3.12.14），安装 `pycalphad==0.11.2`；实测 **34 个包**全部锁定版本与 wheel SHA-256（`requirements-calphad-win-py312.lock`）。pycalphad wheel 的 SHA-256 与第一阶段登记值完全一致。主应用三个 requirements 文件未改动，主应用仍不导入 pycalphad。
- 从 TU Wien / MatCalc 官方发布位置取得 `mc_fe v2.062`（2024-11-08，489,296 字节，SHA-256 `aa02077eac3f602dd7479cbeafb09b450e282716752b3ae2b1fc3a57d9c64865`），放入 Git 忽略的 `model_lab/calphad/databases/`，并登记官方 URL、版本、日期、SHA-256、ODbL 1.0 + DbCL 1.0、版权与署名要求（`config/calphad_tdb.local.json`、`model_lab/calphad/README.md`）。**数据库不随仓库分发**，公开仓库只保留模板、来源记录与获取说明。
- 新增只读工具 `scripts/calphad_tdb_inspect.py`（结构/许可/关键字探测，从不改写数据库）与 `scripts/calphad_compatibility_gate.py`（两道门禁 + 关键字隔离探针）。
- 建立**受控元素排除政策** `config/calphad_exclusion_policy_v1.0.json`：逐条枚举 (样品, 元素, 类别) 共 10 项，与数据库身份绑定，**无通配符、无通用忽略开关**；其他未覆盖的非零元素仍然 `CALPHAD-COMP-002` 阻断；每次运行需具名确认人，并把排除清单、原始值/缺失状态、类别、原因、数据库版本与 SHA-256 写入结果记录。公开政策文件**不含实测成分数值**。
- 结果限制（缩减成分体系、As/Sn/Sb 未建模、O/W 无测量值、不能用于偏聚/夹杂/晶界脆化/相稳定性/性能判断）已嵌入页面、Markdown、JSON 与 **CSV 的前导注释与每一数据行**；同时保留 `reduced_component_system`、`excluded_elements`、`pending_human_review`、`is_complete_phase_diagram=false`、`writes_back_formal_experimental_data=false`。
- 兼容性门禁结果写入登记与证据：`config/calphad_gate_evidence_v1.0.json`（可提交的净化版）、`docs/T86_PHASE2_ENVIRONMENT_AND_GATES.md`（完整报告）。适配器新增 `CALPHAD-TDB-007`（兼容性未通过即阻断）、`CALPHAD-COMP-011`（使用受控排除必须具名确认）与 `CALPHAD-POLICY-001`（政策非法）三个关闭式门禁。

**第一道门禁未通过**，因此**未进入第二道门禁，未执行任何真实钢种计算，T86 保持 `Blocked`**：

1. `Database(path)` → `UnicodeDecodeError: 'gbk' codec can't decode byte 0x96 in position 485974`（pycalphad 按平台 locale 打开文件；厂商文件是 cp1252，含 9 个非 ASCII 字节，首个在偏移 828）。
2. 显式按 cp1252 解码后再加载（两条 pycalphad 官方入口，**文件字节未改动**）→ `pyparsing.exceptions.ParseException: Invalid TDB syntax`，**第 180 行第 18 列，关键字 `REFERENCE_ELEMENT`**。
3. 关键字隔离探针（合成 TDB、内存内、不写文件、不计算）：基线通过，而 `REFERENCE_ELEMENT`、`ADD_COMPOSITION_SET`、`ATTACH_CONTRIBUTION`、`CREATE_NEW_PHASE`、`PARAMETER HMVA(...)` **逐条都失败** —— 不是"第一个挡住后面的能过"。

明确未做的事：**没有删除或注释任何关键字、没有改写数据库、没有制作"兼容版 TDB"、没有执行任何平衡计算**。第二道门禁本应核对元素/相/有序无序/碳氮化物/温区/成分限/相分数合计与收敛，由于没有可解析对象而**未评估**。

测试证据：`tests/test_t86_calphad_adapter.py` **55 passed**（第一阶段 42 项 + 第二阶段 13 项：锁文件哈希与 wheel 一致性、门禁证据内容、本地登记的门禁判定、`CALPHAD-TDB-007` 阻断与状态上报、兼容性版本漂移关闭式失败、排除政策枚举/绑定/通配符拒绝、受控排除与具名确认、限制声明嵌入记录/Markdown/CSV、阻断记录仍带限制）。`tests/test_physics.py`、`tests/test_streamlit_pages.py`、`tests/test_model_lab.py`、`tests/test_third_party_registry.py`、`tests/test_t52_governed_data_physics.py` 共 **25 passed**。

解除条件：(1) 项目负责人决定是否批准**有记录、可复现的受控预处理**（派生数据库），并接受其物理模型变化与 ODbL 派生公开义务；或改用 pycalphad 原生开源钢库（如 MIT 的 LibreCalphad，但同样缺 As/Sn/Sb 评估参数）；或向 TU Wien/MatCalc 询问是否有官方 pycalphad 兼容版本；或把 T86 冻结为技术框架。

边界：未提交或再分发数据库文件；未修改 `requirements*.txt`、既有经验公式路径、`data/processed/` 科研数据、T52 治理内核；未 commit/push/tag。

### 第三阶段（2026-09-25）：社区兼容版数据库候选审查与兼容性验证

项目负责人确定：**不自行预处理原始 `mc_fe v2.062`**，改用已有的社区兼容派生文件，只登记为"第三方社区派生数据库候选"。

完成情况：

- 登记候选 `MATCALC-MC-FE-V2062-COMMUNITY-CLEAN-19B1164`：仓库 `adityamoolya/maraging-steel-calphad-dft`、文件 `2databases/mc_fe_v2062_clean.tdb`、固定提交 `19b11640253543fe412145498438cb8355a32561`、479,418 字节、SHA-256 `7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042`、utf-8；上游 ODbL 1.0 + DbCL 1.0 原样保留在文件头第 26–29 行，保留原评估者与社区修改者署名。文件存在 Git 忽略的 `model_lab/calphad/databases/community/`，**未修改**该文件，**未制作**任何"兼容版 TDB"。来源仓库无 LICENSE 文件，**未复制任何第三方代码**。
- 全量差异审计（`scripts/calphad_tdb_diff_audit.py`）：判据 `passed_syntax_repairs_only`，4,515 条共享语句，**0 条未解释差异**。逐条归类：`reference_key_normalisation` 4、`invalid_delimiter_repair` 1、`invalid_numeric_literal_repair` 2、`duplicate_fragment_repair_verified` 2、`duplicate_or_stray_fragment_removal` 1、`missing_terminator_split` 1、`structural_change_numbers_preserved` 1、`matcalc_only_command_removed` 7、`matcalc_only_parameter_removed` 21（HMVA）。77 行 `$ Cleaned by script:` 注释块重新拼装为 35 条语句并**全部匹配**上游。**未发现**任何 Gibbs 能量、相互作用参数、磁性参数、温度断点或数值系数被改动。**没有**用作者"未改动参数"的声明替代本地验证。
- 兼容性门禁（`scripts/calphad_compatibility_gate.py`）：解析通过（显式 utf-8 解码；`Database(path)` 因本机 GBK 区域设置失败、加 `-X utf8` 后通过——主机区域设置问题）。计数：25 合金元素（含 VA 共 26）、132 相、26 物种、123 函数、4,094 参数。有序-无序链接 **0**（BCC_B2 未耦合）；组合集相 **0**（MC/MX 不可达）。Workspace 构造通过（16 组元 × 132 相）。
- 独立验证（`scripts/calphad_candidate_validation.py`，每次平衡在**独立子进程 + 墙钟超时**中运行，实现崩溃隔离）：上游 5 个二元体系 15 项检查 **15/15 复现**（判据按条件重新实现，未用作者图片/结论/源码）；项目相关 9 个体系 **18/18 通过**（Fe-C 稳定系与亚稳系各 2 项、Fe-Cr-C 2 项、Fe-Mn/Fe-Si/Fe-Nb/Fe-V/Fe-B/Fe-N 各 2 项）；MC/MX 可达性探针结果为"不可达"，与文档化模型损失一致（`agrees_with_expectation = true`）；温度请求 400–1725 °C = 673.15–1998.15 K 落在数据库声明区间内。这些检查**只证明软件行为与基本合理性，不是钢种实验验收**。
- **阻断级新发现**：本机 `pycalphad==0.11.2` 对**组元列表长度 ≥14** 的体系无法求解，实测上界 13（Fe + 11 合金元素 + VA）。排除性对照：在 pycalphad 自带独立数据库 `COST507.tdb` 上**边界完全相同**（13 可解 / 14 失败）；与相列表无关（单相/两相/132 相都中止）、与 `pdens` 无关（10/50/200/2000 都中止）、与具体元素无关（第 14 个组元换成 B/N/P/S/Co/Ta/Y/W/Hf 全部中止）、与线程栈无关（4/16/64 MB 均中止）。失败形态：`MemoryError`（无法分配 10.9 GiB，形状 `(1, 1, 54, 933583, 29)`，产品路径 worker 退出码 2）、`pycalphad/core/minimizer.cp312-win_amd64.pyd` 内 `0xC0000005` ACCESS_VIOLATION 与 `0xC0000374` HEAP_CORRUPTION、以及无结果的内存无界增长。中止点定位精确：**Workspace 构造成功，首次求解即中止**。
- 产品路径修复与关闭式失败：worker 原先用 `Database(path)`（平台 locale）打开 TDB，导致注册候选在真实请求下报 GBK 解码错误——已改为**从文件字节显式解码**（utf-8 → cp1252 兜底），与门禁证据口径一致。修复后真实请求进入求解并在容量上限处失败，worker 报 `CALPHAD-WORKER-MEMORY-001`、适配器报 `CALPHAD-RUN-001`、`state=blocked`，消息写明实测容量上限与"减少组元/更换环境必须先经具名批准并更新受控元素排除声明"。**未丢弃组元、未裁剪相列表、未代入默认值**。适配器另新增原生中止（ACCESS_VIOLATION / HEAP_CORRUPTION 等）的可读解释字段 `worker_returncode` / `native_abort`。
- 受控元素排除政策升级为 `config/calphad_exclusion_policy_v1.1.json`：批准的三元组不变（10 项），只把绑定身份换成社区派生候选，并记录 `supersedes` v1.0；适配器默认指向 v1.1。
- 证据：`config/calphad_gate_evidence_v1.1.json`（可提交净化版）、`docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md`（完整报告）；原始报告写入 Git 忽略的 `outputs/`。

**状态判定**：数据库候选 `compatibility_candidate`；**T86 保持 `Blocked`**。未声明 `validated`、`production_ready`、`pilot_ready_pending_scientific_review`。理由：候选可解析、差异审计与验证复现均通过，但两个真实炉次（16 个组元条目）在本环境**无法求解**，门禁中与声明成分相关的项无法评估，功能无法对真实样品产出结果。

解除条件（需具名决定，任一都不得静默执行）：(1) 修复或更换隔离环境，使 ≥16 组元体系可解；或 (2) 具名批准**缩减成分体系**并同步新版本政策；或 (3) 具名批准**受限相列表**并说明科学依据与边界；或 (4) 把 T86 冻结为技术框架。第 2、3 项都会改变科学声明。

边界：未提交或再分发任何数据库内容；未修改 `requirements*.txt`、既有经验公式路径、`data/processed/` 科研数据、T52 治理内核；未处理临时目录 ACL 与随机 ID 抖动断言（独立任务）；未 commit/push/tag。

### 第四阶段（2026-09-25）：固定缩减成分体系与固定相范围

项目负责人批准：**不换环境、不升级 pycalphad、不尝试全 16 组元求解**，建立固定缩减体系 `steel_matrix_equilibrium_v1` 与固定相集合 `steel_matrix_major_carbides_v1`，用途限定为研究 B-DQ/R-DQ 在数据库有效温区内的基体相与主要碳化物平衡趋势。

完成情况：

- 固定成分体系（`config/calphad_reduced_system_v1.0.json`，`SteelAI-CALPHAD-Reduced-System-Policy-v1.0`）：纳入 `Fe, C, Mn, Si, Cr, Ni, Mo, Cu, Al, Nb, Ti, V` 共 12 个组元；排除 `B/N/P/S`（新类别 `capacity_reduction`，**有测量值**，为满足容量上限而排除）、`As/Sn/Sb`（数据库未覆盖）、`O/W`（无测量值，不按 0）。**没有**任何通用元素选择开关：适配器把成分推导出的组元集与政策逐项比对，不一致即 `CALPHAD-COMP-012` 阻断；政策本身用模块常量校验，改文件也无法悄悄放宽。
- 固定相集合（同文件 `phase_profile`）：`LIQUID, FCC_A1, BCC_A2, CEMENTITE, M23C6, M7C3, M6C`。相名以解析后的数据库为准，全部存在；新增 `scripts/calphad_phase_profile_probe.py` 独立探针（名称存在 / 有参数 / 相记录可构造 / 体系内可达），**7/7 通过、无相被移除**（若任一相不通过则必须从第一版移除并记录原因，不得改写 TDB 强行启用）。
- 具名批准：真实运行前必须填写 `reviewer_id`、批准时间、批准理由并勾选确认文本；`config/calphad_exclusion_policy_v1.2.json` 记录缩减体系版本、排除元素列表、相集合版本、数据库版本与 SHA-256；**代码不代填姓名**，缺失即 `CALPHAD-COMP-011` 阻断。
- 输出与限制：统一命名 `12-component reduced-system matrix equilibrium prediction`；页面、Markdown、JSON、CSV 与运行记录均包含 `component_profile`、`phase_profile`、`reduced_component_system`、纳入元素、排除元素及原因、禁止解释的问题、BCC_B2/HMVA/MC-MX 模型损失、pycalphad 与数据库（含社区派生提交）版本与 SHA-256、`pending_human_review`、`writes_back_formal_experimental_data=false`。CSV 每一数据行都带这些字段。
- 受控排除政策升级为 v1.2（supersedes v1.1，批准三元组 18 项，新增 `capacity_reduction` 类别与容量型排除范围）；`capacity_reduction` 只能与固定缩减体系政策共用，否则 `CALPHAD-COMP-013` 阻断。
- 新增 `scripts/calphad_phase4_validation.py`（十步验证，驱动真实适配器与隔离 worker）与 `config/calphad_phase4_evidence_v1.0.json`（可提交证据）。
- **十步验证结果**：第 0 步（无具名批准必须阻断）**通过**；第 1–5 步（12 组元单相、固定相集合单点、温度扫描、逐点合计、重复一致性）**通过**；**第 6 步 B-DQ 失败**（875 °C 批量求解不收敛，已实现有界单点重算，重算后仍未收敛）；第 7 步 R-DQ **通过**（54 点、合计 0.9999999998–1.0000000004、重复运行最大绝对差 3×10⁻⁹、稳定相组合一致）；第 8、10 步因第 6 步失败而**未评估**；第 9 步（被排除元素未进入 worker）**通过**。→ **T86 保持 `Blocked`**，不标记 `pilot_ready_pending_scientific_review`。
- **本轮修复的关键缺陷**：组元列表缺少空位 `VA` 时 pycalphad **不报错**，而是返回物理错误的结果（B-DQ 在 400 °C 报 LIQUID 0.97），且相分数合计仍为 0.99942，**只检查合计无法发现**。worker 现已在数据库声明 `VA` 时总是加入并输出 `pycalphad_components`；验证脚本新增物理合理性检查（1000 °C 以下不得出现液相、1500 °C 以上必须出现液相、700 °C 以下必须有 BCC_A2/FCC_A1 基体）。
- 另一个环境级限制被记录：在同一解释器中构造大量不同相记录会触发 symengine 的 `LLVM ERROR: IMAGE_REL_AMD64_ADDR32NB relocation requires an ordered section layout` 原生中止，因此相探针按"每相一个子进程"运行、可达性网格用单次多轴调用求值。

**状态**：固定成分体系"已批准并登记"，固定相集合"已验证并登记"，数据库候选 `compatibility_candidate`，**T86 保持 `Blocked`**。解除条件（需具名决定）：解决 B-DQ 在 875 °C 附近的批量求解不收敛并使重复运行稳定通过；或具名批准把该温区排除并说明影响；或进一步缩减成分体系/相集合；或冻结为技术框架。**不得**通过删除温度点、放宽合计判据或改写 TDB 来"通过"验证。

边界：未更换环境、未升级 pycalphad、未尝试全 16 组元；未增删组元或相以让运行成功；未改写 TDB；未写回 `data/processed/`；未处理临时目录 ACL 与随机 ID 抖动断言；未 commit/push/tag。

### 第五阶段（2026-09-25）：每个温度点独立进程求解

项目负责人决定：正式路径改为**每个温度点独立进程求解**；保持 12 组元、固定相集合、温度网格与所有科研限制不变；批量 Workspace 热启动路径只保留为诊断证据。

完成情况：

- 新增版本化模式 `solver_mode=independent_single_point_process_v1`（`config/calphad_reduced_system_v1.0.json` 的 `solver_modes`，`status=formal_pilot`）：每个温度点使用同一份规范化成分、相同 12 组元加 `VA`、相同固定相集合、相同压力/数据库/pycalphad 版本与配置，启动**全新 worker 进程**并在其中重新创建 `Database`、模型与 `Workspace`，只求解一个温度点，退出后再处理下一个；**按温度顺序串行，禁止并行**。worker 侧以 `CALPHAD-WORKER-MODE-001/002` 拒绝多温度请求或缺声明；测试断言最大并发为 1。
- 旧批量路径 `batch_workspace_warm_start` 标记为 `diagnostic_only`（`formal_pilot=false`），仅用于诊断与模式对照。
- 科学输入不可变更：政策 `forbidden` 列表逐条禁止删除失败点、改温度步长、插值、平滑、动态增删组元或相、按结果调整 `pdens`、挑选成功的一次、用前一点作下一点初值；实现中每个点只改温度，其余字段逐点相同（有测试逐字段比对）。
- 重试规则：正式验收要求每点首次独立进程调用即成功；允许 1 次诊断重试，但首次失败仍记为失败，重试成功不改变正式结果、不拼接进正式曲线（有专门测试断言 `points=[]` 且 `first_attempt_success=false`）。
- 单点结果契约：`request_hash`、温度 °C/K、组元与相集合、`va_present`、数据库 SHA-256、worker PID/退出码、求解状态、活跃相与摩尔分数、相分数合计、运行时间、脱敏 stderr 摘要、`first_attempt_success`、`solver_mode`；父进程只合并全部首次成功且契约验证通过的点，缺少任何点即不输出部分正式曲线（`partial_curve_returned=false`）。新增运行清单完整性哈希 `manifest_digest`。
- 新增重型验收脚本 `scripts/calphad_phase5_acceptance.py`（324 个独立点：B-DQ 3 轮 + R-DQ 3 轮 × 54 点；另做 R-DQ 批量 vs 独立模式对照），机器可读报告写入 Git 忽略的 `outputs/`；**定向测试不启动重型求解**（第五阶段测试全部使用单点 worker 替身）。
- **验收结论：`blocked`**。324 个独立点中 **320 个首次调用即成功（成功率 0.9877）**，**4 个失败点全部是 B-DQ 的 875 °C 与 900 °C**（run 1、run 3 各两个），诊断为 0 个 native abort、0 个 `MemoryError`、0 个超时；R-DQ 三轮全部 54/54，三轮最大重复差 1.3×10⁻⁹（容差 1e-7）。决定性证据：在**全新进程**中重复求解同一单点条件，B-DQ 900 °C 成功 1/8、875 °C 成功 2/4，失败形态是"没有任何相摩尔数"。这修正了第四阶段"失败来自批量热启动"的判断：该体系在本机 pycalphad 0.11.2 下于 α/γ 相界附近**本身求解不确定**。
- **第二阻断项（模式差异）**：R-DQ 批量模式与独立点模式在 54 个共同收敛点中有 1 个点（675 °C）相差 **1.069×10⁻⁴**，远超 1×10⁻⁷；两种模式得到相同的 BCC_A2+CEMENTITE+FCC_A1 三相组合但相分数不同。按"不得自行选择其中一条曲线"的规则，**两条曲线都不发布**，差异如实记录。
- 未采取任何规避：没有删除 875/900 °C、没有改步长、没有插值或平滑、没有挑选成功的那一次、没有把诊断重试结果拼进正式曲线。
- 总运行时间 **4013 秒（约 66.9 分钟）**；B/R 在请求层完全一致（组元、相集合、温度网格、profile、求解模式）。
- 文件读写统一使用显式 UTF-8（Python `encoding="utf-8"` 与编辑工具），不再使用依赖系统 ANSI 码页的 PowerShell 文本 cmdlet 批量改写源码或测试文件。

**状态**：独立单点模式已版本化为正式试点路径，批量模式降级为诊断；固定成分体系与固定相集合不变；数据库候选 `compatibility_candidate`；**T86 保持 `Blocked`**，不标记 `pilot_ready_pending_scientific_review`。

解除条件（需具名决定）：解决 875/900 °C 附近的求解不确定性并使 324 点全部首次成功；或具名批准排除该温区并说明影响；或进一步缩减成分体系/相集合；或冻结为技术框架。

边界：未更改科研输入与限制；未更换环境、未升级 pycalphad；未改写 TDB；未写回 `data/processed/`；未处理临时目录 ACL 与随机 ID 抖动断言；未 commit/push/tag。
## 配置化 SteelStats 定位（2026-10-10，B03-B 迁移接线）

完成情况：SteelStats 项目整体迁至工作空间 `05_Engineering/03_SteelStats` 后，`SteelStatsClient` 默认定位改为三级解析——显式 `project` 参数 > 现有 `load_settings()` 的 `tools.steelstats_project` 字段（相对路径按 Workbench 根解释）> 未配置时旧同级 `../SteelStats` 兼容查找。未新增第二份配置系统、未改 `steelai/settings.py` 解析器；`isolated_cli`、`report`/`verify-report` 固定命令、cwd=项目根、子进程环境剥离、180 秒超时与输入不回写均保持不变。

验收结果：`config/settings.example.toml` 新增公开空字段 `steelstats_project`（注释说明解析顺序与关闭式失败语义，不含本机盘符）；被 Git 忽略的 `config/settings.toml` 仅新增本机指向字段，其余内容原样。专项测试覆盖显式优先、配置绝对/相对路径、空值/缺省回落旧同级、配置无效时关闭式报未就绪且不回落、以及经真实默认 `SteelStatsClient()` 的跨项目合成端到端（合成审核人明确标识为仅测试夹具）。

边界：不改 SteelStats 模块契约、统计实现与 T40 冻结演示；不把本机盘符写入版本化源码或公开示例；不提交/推送。

## 配置错误边界补修（2026-10-10，WO-16 / B03-B-R1）

完成情况：修复查收指出的混淆——原实现把"设置读取/解析失败、`[tools]` 非表、`tools.steelstats_project` 非字符串"与"未配置"同样回落旧同级。现改为新增 `SteelStatsConfigError`：只有字段缺失/空/空白算未配置并保留旧同级兼容；配置存在但不可用改为构造时保留错误（不抛出、不出 traceback），`availability()` 返回 `reason=config_error` 并给简洁原因（不回显配置正文），`_call` 拒绝并提示修正 `tools.steelstats_project` 或显式传路径。显式 `project` 参数仍最高优先级；正常 UI 因配置错误只看到未就绪提示，不出现未处理异常。`load_settings` 全局解析器、`settings.toml`、公开示例与 `test.ps1` 未动。

验收结果：`tests/test_steelstats_bridge.py` 24 项通过（含 6 项新边界回归：TOML 解析错/非字符串/`[tools]` 非表/读取失败均关闭式不回落且不泄漏配置值，仅空白=未配置回落，显式路径在坏配置下仍可用，合成夹具证明坏配置不会选中有效旧同级）；T53+治理核心 19 过 1 跳；真实默认 `SteelStatsClient()` 消费链独立复验通过（报告生成/复核/篡改拒绝，输出隔离）。规定入口 `.\scripts\test.ps1` 全量两轮实跑均 **exit 1：49 failed / 170 errors / 764 passed / 79 skipped**——完整门槛未满足，按诚实保留。已逐类归因：170 errors 为沙箱强制 Python 临时目录到系统 `Temp\pytest-of-pc`（WinError 5，环境级）；43 项 t86 全量失败在隔离复现全部通过（套件内沙箱删除钩子中断，环境级）；4 项 UI/文档断言失败与 1 项 launcher 失败为既有用户 dirty/历史状态，与本改无关；**1 项 t40 演示测试失败为迁移相关真实问题**——`steelai/flagship_demo.py` 硬编码旧同级 `SteelStats/steelstats.module.json` 溯源拷贝，超出本轮允许写入范围，留下一单授权修复。

边界：不为追零改跨模块功能、不加 skip/xfail、不放宽断言；原 WO-15 在完整门槛未过即退出源属流程偏差，历史证据保留，不因此回滚新根。

## T40 实际消费身份修复（2026-10-11，WO-17 / B03-B-R2）

完成情况：修复查收确认的迁移相关真实问题——`flagship_demo.py` 的 `_code_fingerprint()` 用旧同级硬编码路径（`ROOT.parent/SteelData|SteelStats`）读取模块 descriptor 并枚举包源码，SteelStats 迁至工作空间后 `demo_identity()` 真实 FileNotFoundError，且生成指纹早于实际客户端选择。现改为：`demo_identity()` 增加可选 `steeldata`/`steelstats` 客户端参数，`_code_fingerprint(steeldata_project, steelstats_project)` 从实际被调用客户端实例的 project 根读取 descriptor 与枚举 `*.py`（键仍为 `SteelData/...`、`SteelStats/...` 相对键，不写盘符/绝对位置进 manifest 或身份）；`run_flagship_demo` 初始化顺序改为先解析实际客户端再算身份，显式参数与指纹保证同一实例/同一根，不再自造路径解析器。默认入口保留：未传参时沿现有 `SteelDataClient()`/`SteelStatsClient()` 三级解析（本机真实根由 `tools.steelstats_project` 指向新根）。配置坏（project=None）、模块 descriptor 缺失、必需文件缺失在创建生产输出前以可操作 ValueError 失败（错误只含逻辑键名，不泄漏配置正文）；不靠符号链接/复制描述/伪造指纹绕过。文件读取失败统一包装为含逻辑键的可操作错误。冻结六夹具、6 试样/6 组/每组 n=3、synthetic 标记、人工审核夹具、未知单位 needs_human 且不执行、输出不可覆盖/篡改检测全部未动。

验收结果：定向测试（t40+t53+steelstats_bridge+steeldata_bridge）**67 passed / 1 skipped / 14 subtests**，其中真实三模块端到端（生成→复核→同根复用→篡改拒绝/不覆盖）由 skip 风格转为真实通过（默认配置根+旧根仅剩迁移说明下）。新增 5 项指纹行为回归：显式客户端根与指纹逐键一致、相同内容换位置身份不变且键全相对（无盘符/绝对路径/..）、被调用模块源码改变改变 demo_id（隔离副本，不改活仓库）、缺失 descriptor 可操作拒绝、config_error 客户端拒绝且不回落。规定入口 `.\scripts\test.ps1` 一次完整回归（PYTEST_ADDOPTS 仅改 basetemp）：**exit 1 诚实保留——52 failed / 936 passed / 79 skipped**。逐类归因与 WO-16 基线（53F/930P）对比：47 项环境级删除守卫拒绝（43 t86 + 4 thermal，机制与隔离复现同 WO-16）、5 项既有用户 dirty 断言与 WO-16 五项完全一致、**0 项由本轮引起**；WO-16 的 1 项 T40 迁移失败已转通过（+6 passed = 1 真实端到端 + 5 新回归）。完整门槛仍未满足，不为追绿改断言/禁守卫。

边界：不改 bridge、settings、test.ps1、pytest.ini 与科学夹具；不把绝对路径写进身份或 manifest；不处理 47 项环境拒绝与 5 项用户 dirty 断言（留证不修）；本轮只随 WO-28 授权提交推送，不改写既有结论。证据：迁移批次归档目录 `Batch_B03B/repair_R2/`（本地归档，不随仓库发布；公开副本已移除本机绝对路径）。
