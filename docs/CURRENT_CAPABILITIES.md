# SteelAI Workbench 当前能力与旧入口状态

日期：2026-09-17

> 本文件描述 **SteelAI 自身的应用能力**。平台级 Agent/Preset/工具权限的当前状态以 [`../../SHIDAO_WORKBENCH_CURRENT_STATUS.md`](../../SHIDAO_WORKBENCH_CURRENT_STATUS.md) 为准；§“当前开发协作方式”已于 2026-09-25 按该入口页核对更新。

## 当前能力矩阵

| 能力 | 状态 | 当前边界 |
| --- | --- | --- |
| 外部文件标准化入库 | 已完成 T70 | CSV/TSV/XLSX 字段映射、明确单位换算、人工批准后只追加进入标准数据层；复杂仪器报告仍走 SteelData |
| 热模拟曲线标准化接入 | 已完成 T71 | `ZHT.A*` 批量只读解析、逐 interval QC、计划—实测对照、运行表/点表事务式追加和治理审计；单位或身份冲突未解除时仍阻断 |
| 热模拟曲线可视化 | 已完成 T72 | 基于标准化数据查看单采集和 B/R 对比；Φ10×15 mm DH 公式版本化计算应力—应变，同时保留温度、Force 和 Stroke 原始曲线 |
| Double-hit 有效加载段 | 已完成 T73 | 两道次局部应变、基线修正应力、接触/终点候选和全路径对照；16 个 DH 采集的 32 个分段均已具名复核并进入 T74 特征表 |
| 热模拟特征表 | 已完成 T74 | 16 个 DH 采集已具名批准并正式入库；一行一个采集，含两道次峰值、定点流动应力、时间/温度/间隔、位移/应变和全链路哈希 |
| Double-hit 软化分析 | 已完成 T75 | 已批准 2% 偏移主方法和 5% 定真应变对照；16 行正式结果已由复核人 `yjh` 具名复核并写入 `thermal_simulation_softening.csv`，其中 12 行 `passed`，A79、A80、A84、A85 保留 `warning_needs_human_review`；四个超过 100% 的原始值未截断、未删除，不据此声称额外冶金机制或生产结论 |
| 双道次案例分析草稿 | 已实现只读纵向案例 | 从正式 T75、T74、T71 重新核对 16 行与方法批准状态，验证张玲论文副本哈希，生成待人工复核的治理结果包；Workbench Research Agent 可按案例编号通过证据网关读取。联网模型调用仍取决于本机代理依赖与服务可用性；不是通用 PDF RAG。 |
| 标准表导入 | 已实现并保留 | 接受受控五类长表，经过预检、人工确认和仅追加写入 |
| SteelData v0.2 拉伸接入 | 已实现 | 通过独立环境 CLI 和结果契约读取结果包，明确映射 `sample_id` 后写入性能长表 |
| SteelData 成分和曲线接入 | 只读预览 | 不自动写入长表，不从曲线推断性能 |
| Research Data Contract 与质量门禁 | 已实现 | 当前 B/R 证据仍为 `directional_evidence_only`，不支持因果或机器学习结论 |
| Research Agent 与 DSH 旁路 | 已实现为只读 | 不允许写数据、审批配置、启动重型任务或读取未登记原始文件 |
| Physics Model Registry | 已实现 | 公式输出是经验估算，不是实验真值；缺输入不补零 |
| CALPHAD 平衡相分数（可选 T86） | 作品集：`portfolio_exploration_complete`（已签署）；科研：`scientific_use_blocked_by_solver_stability` | **公开合成演示可用**：Fe–C（Fe-0.45 wt.% C）、4 个已验证相、25 点、400–1600 °C、`independent_single_point_process_v1`（每温度点独立进程），两次运行最大差 **0.0**，页面展示相分数—温度曲线并可下载 Markdown/JSON/CSV；结果携带 `portfolio_demo`、`public_synthetic_input`、`model_prediction_not_experimental_measurement`、`not_for_scientific_conclusion`、`is_complete_phase_diagram=false`、`writes_back_formal_experimental_data=false`，不读取私人数据、不写回 `data/processed/`。作品集验收已由负责人 **世道** 于 **2026-09-25**（Asia/Shanghai）签署，范围 `portfolio_engineering_acceptance_only`（`config/calphad_owner_acceptance_v1.0.json`），**不构成**真实钢种科研审批：`scientific_use_approved=false`、`real_sample_curves_published=false`、`materials_conclusion_approved=false`。**真实样品探索保持阻断、不发布曲线、不形成材料结论**：全组元 16 个条目超过本机实测容量上界 13；缩减体系在 B-DQ 875/900 °C 附近不稳定收敛（全新进程 900 °C 成功 1/8、875 °C 2/4）；批量与独立模式在 R-DQ 675 °C 相差 1.069×10⁻⁴（容差 1e-7）。登记社区派生数据库 `mc_fe_v2062_clean`（SHA-256 `7cf37dd4…`，上游 ODbL 1.0 + DbCL 1.0，不随仓库分发、未被修改）与固定 `steel_matrix_equilibrium_v1`（12 组元 + `VA`）、`steel_matrix_major_carbides_v1`（7 相，独立探针 7/7）。页面明确分为「区域 1 · 公开合成演示」与「区域 2 · 真实样品探索」 |
| 获准真实拉伸批次端到端验收 | 已完成 T10 | 一批脱敏 DQ 结果已通过 human 批准、SteelData 完整性/QC/重放和 Workbench 18 条观测暂存预检；正式长表未自动提交 |
| 真实格式公开回归 | 已完成 T11 | SteelData 合成夹具覆盖中英文表头、空行、多工作表、模板歧义、单位冲突、重复和坏值；Workbench 入库门禁不变 |
| 毕业主线数据契约 | 已完成 T12 | `SteelAI-Graduation-Core-v1.0` 冻结材料/炉次/条件/试样/报告/观测关系；当前只含拉伸 YS、UTS、EL，尚未迁移真实数据 |
| 开源复用登记 | 已完成 T13 | 5 项候选已核对固定版本、官方来源和 OSI 许可证；T13 选出的 Frictionless 已在 T14 完成可选适配 |
| 标准数据包可选校验 | 已完成 T14 | Frictionless 5.19.0 可为六张公开合成表生成并校验 Data Package；独立哈希锁环境，不是核心依赖 |
| DSH 调用 SteelData v0.2 预览 | 已完成 T20 | 独立环境、3 工具白名单、CLI/MCP 同摘要；不审批、不执行、不披露原始行 |
| 映射建议契约与状态机 | 已完成 T21 | DSH 可保存结构化建议元数据；初始状态受控，Agent 不能批准或执行 |
| 映射建议人工审批 | 已完成 T22 | Workbench 逐条展示来源、字段/单位证据、风险、差异与摘要；用户填写身份和说明后批准或驳回，Agent 不能代填或批量批准 |
| 获准建议的执行与接入 | 已完成 T23 | human 批准后可自动标准化；支持状态、锁、幂等重试和完整审计链，正式长表仍需用户对应样品并确认追加 |
| Intake Agent 固定评测 | 已实现 | 40 个脱敏案例标签已获确认并冻结，确定性评分和参考回归已接入；尚无云模型成绩 |
| SteelStats 模块接入 | 已完成 T33 | 选择已验证 SteelData 拉伸结果包，经人工确认统计身份后调用独立 SteelStats CLI；结果只写 Workbench outputs，不回写源包 |
| 公开旗舰演示 | 已完成 T40 | 公开合成成功链路与未知单位失败链路均已冻结并由项目负责人验收 |
| 公开仓库候选 | 已完成 T41，尚未发布 | 已有隐私审计、架构、安装、许可证和限制说明；是否推送 GitHub 仍由项目负责人决定 |
| 全局科研治理 | 已完成 T50–T55 | 九工作区共享状态、身份、审批、QC、来源、Manifest、完整性和 Agent 证据边界；自动化执行适配延期 |
| 统一运行与成果中心 | 已完成 T56 | 汇总运行、待确认、阻断、失效和已验收结果；作品集只读取 complete 且具名验收的完整结果 |
| v0.2 冻结候选 | 已完成 T57，本地候选 | 发布契约、跨模块矩阵、离线降级、T40 重放、全量测试与隐私审计可重复执行；Git 标签待负责人决定 |
| 材料科研多智能体框架 | 已完成 T60 | 五类职责使用固定工具与两个人工关口；交接、重试、阻断、人工接管和离线降级均可追溯 |
| MCP 工具与轻量 A2A | 已完成 T61 | 五个本地 stdio 工具具有闭合 Schema、角色权限、超时、错误码和幂等收据；A2A 只实现项目内可验证任务信封 |
| 公开真实钢板数据案例 | 已完成 T62 | UCI CC BY 4.0、1941 行、固定 60/20/20 划分、多数类基线与 CPU kNN；测试 Macro F1 0.0735 → 0.7591，仍需人工验收 |
| 人工与智能体流程比较 | T63 实现完成、待实测 | 四项任务、三种流程、双重复和七类指标已冻结；结构校准与可追溯报告通过，24 条真实测量未齐前不判断优势 |
| 岗位作品集与公开发布包 | T64 实现完成、待人工终审 | 双语入口、16 项公开资产、4 条能力—证据映射、演示脚本、面试清单和可追溯准备包已就绪；视频、技术报告、清洁环境复现与最终 Release 未完成 |

## 入口状态

| 入口 | 状态 | 说明 |
| --- | --- | --- |
| 标准表导入 | 当前入口 | 手工整理好的长表继续使用，不被 SteelData 取代 |
| SteelData 标准化接入 | 当前入口 | 可逐条人工复核映射建议；批准后由受信任宿主自动执行或安全恢复，结果校验后仍需人工对应样品和确认追加 |
| 可追溯统计 | 当前入口 | 人工确认试样对应、方法版本和纳入决定后，调用独立 SteelStats 生成并复核描述统计报告 |
| `Start_SteelAI_DSH.cmd` | 受控旁路 | 保留 SteelAI 科研只读桥；SteelData suggest 服务只能写建议元数据，没有科研数据写入、审批或执行权限 |
| WearSteel-AI v0.1 适配器 | 兼容入口 | 只在本机路径可用时读取旧模型；不可把兼容测试当成重新核验原始数据 |

## Enterprise Lab 可选实验能力（T80–T84，可选，未接入默认应用）

- **T80–T84 已完成**：六边形边界与内存纵向流程（T80）、PostgreSQL Schema/迁移基线（T81）、PostgreSQL Repository/UoW 与事务型 outbox 写入侧（T82）、有限调用式 outbox dispatcher（T83）、有限调用式 background job worker（T84）；五个任务均已 `Done`，对应 ADR-0001～ADR-0005 均已 `accepted`，阶段已冻结（`T85` 收尾）。
- **能演示什么**：在真实 PostgreSQL 18.6 单实例上演示"业务写入与 outbox 同一事务提交"、outbox 的领取/确认/重试/过期租约恢复、后台任务的租约与心跳/失败重试/过期租约恢复，以及幂等、事务边界、fencing 与错误脱敏等契约；当前全量基线 **705 passed、8 skipped、358 subtests、0 failed**。
- **不属于默认用户功能**：`app.py`、`pages/`、Streamlit 默认入口与 T76 启动器都不导入该模块，也不连接数据库、不自动启动后台进程；没有 `STEELAI_ENTERPRISE_DATABASE_URL` 时应用照常完全离线运行。
- **不代表** Kafka、微服务或生产部署已完成：没有真实 broker、没有常驻 dispatcher/worker、没有 HTTP API/RBAC/多租户、没有监控告警与生产备份/高可用；投递与执行都是 **at-least-once**，需要下游以 `event_id`、Handler 以稳定 `job_id` 幂等。
- **日常科研使用仍以现有链路为主**：Streamlit 界面、`data/processed/*.csv`、Manifest + SHA-256 + `COMPLETE` 结果包、共享治理内核与运行中心；Enterprise Lab 只是可选参考实现，阶段冻结说明见 `docs/enterprise/T85_ENTERPRISE_LAB_PHASE_CLOSEOUT.md`。

## 项目分工

SteelAI 负责研究工作流、权限闸门、样品对应、统计审核和结果展示；SteelData 负责确定性解析、标准化、QC 与可重放结果包；SteelStats 负责统计输入验证、描述统计、组级 QC 和可追溯报告。三个项目通过版本化文件/CLI 契约协作，不共享 Python 依赖。

## 当前开发协作方式

- 代码修改由平台 Agent `software_engineering_agent`（Preset `shidao-engineer`）在 `SteelAI-Workbench` 工作区内完成；该 Agent 当前启用，并以 construction preset 直接使用文件系统与 PowerShell 工具，负责实现、最小相关测试和自复查。
- 自定义 Engineer 已进入当前默认开发链路；**Reviewer（`software_code_reviewer`）当前为 `staged` 且未部署**，其独立只读复查链路保持 fail-closed 休眠，需重新激活后才可路由。
- 单项任务规划与结果复核仍可由 Codex 承担。
- 精确的启用状态、工具权限与人工审批点见 [`../../SHIDAO_WORKBENCH_CURRENT_STATUS.md`](../../SHIDAO_WORKBENCH_CURRENT_STATUS.md)。
