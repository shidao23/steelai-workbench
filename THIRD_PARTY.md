# 第三方开源复用登记

登记版本：`SteelAI-ThirdParty-Candidates-v1.0`

核对日期：2026-09-05

任务：T13 建立登记；T14 已完成一个可选适配器（第三方代码不复制入仓库）

机器可读登记位于 `config/third_party_candidates_v1.0.json`，并由本地质量门禁检查。

## 复用政策

- 只有官方仓库、明确 OSI 开源许可证和固定版本/源码引用都已核对的候选，才可进入实现评估。
- 未知许可证、无许可证、仅“source available”或非开源实现一律不复制。
- 真正引入时必须固定精确版本，保留许可证、版权及 NOTICE 要求，并记录直接/传递依赖。
- 外部能力只能作为可关闭适配器；禁用后 SteelAI/SteelData 核心流程仍须运行。
- T13 不授权上传科研数据、连接外部服务、改变科学规则或执行真实数据迁移。
- 项目功能相似不代表可以照搬界面、文档或实现；概念借鉴与代码复用分别记录。

## 候选矩阵

| 候选小功能 | 官方版本与源码 | 许可证 | 本机/依赖成本 | 决策 |
| --- | --- | --- | --- | --- |
| Frictionless Data Package 描述与独立验证报告 | `frictionless-py 5.19.0`, `43a63e0` | MIT | CPython 3.12.14 已验证；共 40 个安装包 | **T14 已采用**，仅做可选公开导出适配器 |
| NOMAD 材料 schema / ELN / FAIR 工作流概念 | `NOMAD 1.4.3`, `0e2fecd` | Apache-2.0 | 完整平台需要数据库、搜索、Worker 和 Web 部署 | 仅作架构参考，不部署、不复制 |
| GEMD 材料—工艺—测量关系导出 | `gemd-python 2.2.4`, `af4336f` | Apache-2.0 | 中等；与 graduation-v1 身份模型重叠 | 延后，出现真实互操作需求再评估 |
| Great Expectations 验证文档/规则集 | `1.21.0`, `eb0faa5…` | Apache-2.0 | 兼容当前 Python 3.12，但与现有 QC 重复 | 当前拒绝 |
| MLflow 运行/产物追踪 | `3.16.0`, `998f710` | Apache-2.0 | 新增追踪运行时和存储模型；当前 manifest 已够用 | 延后到实验规模明显增长后 |
| OpenBB Workspace 前端小模块（分栏/面板状态/iframe 协议与注册表） | `workspace` `be00e95019a55d57af146919ee46b7e1a4859226` | Apache-2.0（上游 NOTICE 排除 TradingView Advanced Charts） | 只读 5 个小模块；**不安装 OpenBB 整栈** | **WO-31 已采用**：按本项目状态重写，见下节 |

## WO-31 OpenBB Workspace 选择性复用登记

2026-10-13。参考已读源码在 `08_Archive/00_Workspace_Migration/Batch_WO31/planning_20261013/`
（`openbb_selected/` 选读副本 + `OPENBB_SOURCE_MANIFEST.json` 固定提交与逐件 SHA-256）。

- 上游：<https://github.com/OpenBB-finance/workspace>，固定提交 `be00e95019a55d57af146919ee46b7e1a4859226`。
- 许可：**Apache-2.0**；上游 `NOTICE` 明确把 **TradingView Advanced Charts 排除在许可之外**，本项目未使用该组件。
- 许可原文随分发：`frontend/third_party/openbb/LICENSE`
  （sha256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`）与
  `frontend/third_party/openbb/NOTICE`
  （sha256 `7ead59cd1679b65fb3be5d056b6415564f9c6849b37401c0f0b5020b9dce4c8b`），
  两个摘要与选读清单完全一致。

**逐文件改编登记**（完整表格见 `frontend/THIRD_PARTY.md`）：

| 本项目文件 | 上游文件 | 修改 |
| --- | --- | --- |
| `frontend/src/layout/usePanelsState.ts` | `terminalpro/.../hooks/usePanelsState.ts` | 去 `react-router`/`usehooks-ts`；按 `schemaVersion+project+page` 隔离；新增 `resetPanels()` |
| `frontend/src/layout/GridLayout.tsx` | `terminalpro/src/components/GridLayout.tsx` | 去 TabContext/app/theme store 与上传耦合、去拖动排序；重连项目状态；补键盘与 aria |
| `frontend/src/iframe/protocol.ts` | `terminalpro/src/types/iframeProtocol.ts` | 去 `zod`；命名空间改 `steelai-*`；**删除 `openbb-auth`/authHeaders 转发**；加 `projectId/taskId/frameInstanceId/requestId` |
| `frontend/src/iframe/registry.ts` | `terminalpro/src/lib/iframeWidgetRegistry.ts` | 键改 `frameInstanceId`；新增项目切换失效、卸载清 pending、请求超时 |
| `frontend/src/iframe/IframePanel.tsx` | `terminalpro/.../useIframeProtocol.tsx` | **上游「同 origin 即放行」不作为本项目隔离边界**；三重校验 origin + `event.source` + 三元组；未实现协议时退化为普通 iframe 并标"未绑定" |
| `frontend/src/components/LineChart.tsx` | `terminalpro/src/components/Charting/PlotlyChart.tsx` | 懒加载与尺寸自适应；轴标题/单位由调用方显式给出 |

**明确未采用**：`terminalpro/package.json` 的金融/SSO/遥测依赖树、OpenBB 的 DB/Redis/SSO/Docker/云模型整栈、
上游修改性 lint 脚本、`backend-api` 的 FastAPI 应用、TradingView Advanced Charts、AG Grid Enterprise 等需商业授权的组件。

**WO-31 新增前端依赖**（`frontend/package-lock.json` 锁定）：`react` 19.3.0 (MIT)、`react-dom` 19.3.0 (MIT)、
`plotly.js-dist-min` 4.1.2 (MIT)；dev：`typescript` 5.9.3 (Apache-2.0)、`vite` 7.3.7 (MIT)、
`@vitejs/plugin-react` 5.2.0 (MIT)、`@types/react` 19.3.0 (MIT)、`@types/react-dom` 19.3.0 (MIT)。

**WO-31 新增 Python 依赖**（独立环境 `.venv-web`，不改冻结的科学计算环境，见 `requirements-web.txt`）：
`fastapi` 0.115.6 (MIT)、`uvicorn` 0.34.0 (BSD-3-Clause)、`python-multipart` 0.0.20 (Apache-2.0)、
`openpyxl` 3.1.5 (MIT)、`pydantic` 2.10.4 (MIT)。


## T14 实施结果

采用项：`frictionless-data-package`。

只允许评估以下最小功能：从 graduation-v1 的公开合成表生成标准 Data Package 描述，并用独立验证报告校验包结构。它不能替代现有 Python 契约、QC、人工批准或入库门禁。

T14 已在两个隔离环境完成普通安装和哈希锁定重装，只使用 `SYN-` 合成示例。Frictionless 本体及 39 个传递依赖共 40 个包，没有加入主 `requirements.txt`；MIT 许可证、wheel 哈希、性能对照和移除方法均已保存。未安装组件时原生质量门禁照常通过。

实测和使用说明见 [T14 Frictionless 可选适配器](docs/T14_FRICTIONLESS_ADAPTER.md)。

## T86 pycalphad 登记（CALPHAD 平衡相分数）

`config/third_party_candidates_v1.0.json` 是 T13 的历史登记（5 项候选，核对日期 2026-09-05），**本轮不改写它**；pycalphad 的核对结果单独登记在 `config/calphad_adapter_v1.0.json`，并在此登记。

| 项目 | 值 |
| --- | --- |
| 候选功能 | 固定样品成分下平衡相分数随温度变化（CALPHAD 平衡计算） |
| 项目 | `pycalphad` |
| 固定版本 | `0.11.2`（状态：`pinned_and_installed_in_isolated_environment`，2026-09-25 经项目负责人批准安装到 `.venv-pycalphad`） |
| 源码引用 | tag `0.11.2` 的提交 `2d4c744ddb890e179542894d070150797e13b325` |
| 许可证 | MIT，`verified_osi`，[LICENSE.txt@0.11.2](https://github.com/pycalphad/pycalphad/blob/0.11.2/LICENSE.txt) |
| 官方来源 | [仓库](https://github.com/pycalphad/pycalphad)、[v0.11.2](https://github.com/pycalphad/pycalphad/releases/tag/0.11.2)、[PyPI 0.11.2](https://pypi.org/project/pycalphad/0.11.2/) |
| 运行成本 | `requires-python >=3.11`；实测 34 个安装包（含编译依赖 `symengine`），全部哈希锁在 `requirements-calphad-win-py312.lock` |
| 决策 | **已采用为可关闭适配器**；主应用不导入，隔离环境单独安装 |

政策一致性：未知许可证拒绝、版本精确固定、许可证链接完整、**外部能力只能作为可关闭适配器**。本候选不进入 `requirements.txt` / `requirements-dev.txt` / `requirements-enterprise.txt`，未复制第三方代码；不安装 pycalphad 时原生物理计算与质量门禁照常通过。

### 数据库（TDB）—— 独立许可，**不随仓库分发**

| 项目 | 值 |
| --- | --- |
| 数据库 | MatCalc `mc_fe` **v2.062**（2024-11-08），TU Wien IMST 评估 |
| 官方来源 | [MatCalc 开放数据库页面](https://www.matcalc.at/index.php/databases/open-databases)（官方下载链接在同一页面） |
| SHA-256 | `aa02077eac3f602dd7479cbeafb09b450e282716752b3ae2b1fc3a57d9c64865`（489,296 字节） |
| 许可证 | **ODbL 1.0 + DbCL 1.0**（允许商业使用与再分发；派生数据库须同许可；公开成果需署名声明） |
| 与 pycalphad 许可证的关系 | **完全独立**：pycalphad 是 MIT，数据库是 ODbL/DbCL；两者的许可互不覆盖 |
| 仓库内处理 | 数据库文件放在 Git 忽略的 `model_lab/calphad/databases/`，**不提交、不再分发**；仓库只保留 `config/calphad_tdb.example.json` 模板、`model_lab/calphad/README.md` 获取说明与证据文件 |
| 兼容性门禁 | **未通过**：pycalphad 0.11.2 无法解析原始文件（编码失败 + `REFERENCE_ELEMENT` 等 MatCalc 扩展命令不在 TDB 文法内）。原件保留用于溯源与差异审计，**不可选用** |

### 社区派生数据库候选（第三方）—— 阶段 3 登记

按项目负责人决定，第三阶段**不自行预处理**原始 `mc_fe v2.062`，改用已有的社区兼容派生文件。它只登记为"第三方社区派生数据库候选"。

| 项目 | 值 |
| --- | --- |
| 候选标识 | `MATCALC-MC-FE-V2062-COMMUNITY-CLEAN-19B1164` |
| 来源仓库 | [adityamoolya/maraging-steel-calphad-dft](https://github.com/adityamoolya/maraging-steel-calphad-dft)（该仓库**没有 LICENSE 文件**，因此仓库内未复制其任何代码） |
| 文件与固定提交 | `2databases/mc_fe_v2062_clean.tdb` @ `19b11640253543fe412145498438cb8355a32561` |
| 背景证据 | [pycalphad GitHub Discussion #705](https://github.com/pycalphad/pycalphad/discussions/705) |
| 大小 / SHA-256 | 479,418 字节 / `7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042` |
| 许可证 | **上游 ODbL 1.0 + DbCL 1.0 原样保留**在文件头第 26–29 行；派生库同为 ODbL 派生数据库，须保持 ODbL 并保留原评估者与社区修改者署名 |
| 仓库内处理 | 存放于 Git 忽略的 `model_lab/calphad/databases/community/`；**未修改**该文件，**未制作**任何"兼容版 TDB"；仓库只保留登记、许可证说明、提交与哈希、差异审计结论与获取说明 |
| 命名纪律 | 只能称为"第三方社区派生数据库候选"；**不得**称为 TU Wien 官方 pycalphad 兼容版、pycalphad 官方数据库或 SteelAI 已验证数据库 |
| 差异审计 | `passed_syntax_repairs_only`，**0 条未解释差异**（4,515 条共享语句；仅语法修复与 MatCalc 专有命令/参数注释化，未发现任何 Gibbs 能量、断点或系数改动） |
| 兼容性门禁 | 解析与结构检查**通过**；上游 5 个二元体系 **15/15** 检查复现，项目相关检查 **18/18** 通过 |
| 求解容量 | **不足**：本机 pycalphad 0.11.2 对组元列表长度 ≥14 的体系无法求解（实测上界 13），在 pycalphad 自带数据库 `COST507` 上同样复现，属环境限制而非数据库缺陷 |
| 状态 | 数据库候选 `compatibility_candidate`；**T86 保持 `Blocked`** |

### 固定缩减体系（T86 第四阶段）

项目负责人批准建立固定、版本化的 `steel_matrix_equilibrium_v1`（12 组元）与 `steel_matrix_major_carbides_v1`（7 相），用途限定为研究 B-DQ/R-DQ 在数据库有效温区内的基体相与主要碳化物平衡趋势。

| 项目 | 值 |
| --- | --- |
| 成分体系政策 | `config/calphad_reduced_system_v1.0.json`（`SteelAI-CALPHAD-Reduced-System-Policy-v1.0`） |
| 纳入组元 | `Fe, C, Mn, Si, Cr, Ni, Mo, Cu, Al, Nb, Ti, V`（12；送入 pycalphad 时另加 `VA`，共 13 个条目 = 本机实测容量上界） |
| 排除元素 | `B/N/P/S`（`capacity_reduction`，**有测量值**但为满足容量上限而排除）、`As/Sn/Sb`（数据库未覆盖）、`O/W`（无测量值，不按 0） |
| 相集合政策 | 同上文件内 `phase_profile`（`steel_matrix_major_carbides_v1`） |
| 相集合 | `LIQUID, FCC_A1, BCC_A2, CEMENTITE, M23C6, M7C3, M6C`（7 相，独立探针 7/7 验证通过，无移除） |
| 通用开关 | **不存在**：无元素选择开关、无相选择开关；成分推导出的组元集与政策不一致即 `CALPHAD-COMP-012` 阻断 |
| 排除政策升级 | `config/calphad_exclusion_policy_v1.2.json`（supersedes v1.1；新增 `capacity_reduction` 类别，批准三元组共 18 项） |
| 具名批准 | 真实运行前必须填写 `reviewer_id`／批准时间／批准理由并勾选确认文本，**代码不代填姓名**；缺失即 `CALPHAD-COMP-011` 阻断 |
| 结果命名 | 统一为 `12-component reduced-system matrix equilibrium prediction` |
| 相探针证据 | `config/calphad_phase_profile_evidence_v1.0.json` |
| 十步验证证据 | `config/calphad_phase4_evidence_v1.0.json` |
| 验证结果 | 第 1–5、7、9 步通过；**第 6 步（B-DQ）在 875 °C 批量求解不收敛 → `Blocked`** |

完整报告见 [T86 第四阶段：固定缩减成分体系与固定相范围](docs/T86_PHASE4_REDUCED_SYSTEM.md)。该阶段还发现并修复了一个会让错误结果通过合计检查的缺陷：组元列表缺少空位 `VA` 时 pycalphad 会静默返回物理错误的结果（400 °C 报 97% 液相）而相分数合计仍为 1。

### 独立单点求解模式（T86 第五阶段）

| 项目 | 值 |
| --- | --- |
| 正式模式 | `solver_mode=independent_single_point_process_v1`（`status=formal_pilot`） |
| 每点规则 | 每个温度点一个**全新 worker 进程**、每进程只解一个温度、**串行**、无热启动；同一规范化成分、相同 12 组元加 `VA`、相同固定相集合、相同压力/数据库/pycalphad 版本 |
| 诊断模式 | `batch_workspace_warm_start` 降级为 `diagnostic_only`，仅用于诊断与模式对照，**不再作为正式试点路径** |
| 重试规则 | 正式验收要求每点首次独立进程调用即成功；允许 1 次诊断重试，但首次失败仍记为失败，重试成功**不改变**正式结果、**不拼接**进正式曲线 |
| 单点契约 | `request_hash`、温度 °C/K、组元与相集合、`va_present`、数据库 SHA-256、worker PID/退出码、求解状态、活跃相与摩尔分数、相分数合计、运行时间、脱敏 stderr 摘要、是否首次成功、`solver_mode` |
| 完整性 | 独立点运行清单 `point_manifest` + `manifest_digest`；缺少任何点即不输出部分正式曲线 |
| 验收脚本 | `scripts/calphad_phase5_acceptance.py`（重型验收，独立于定向测试） |
| 验收结果 | **`blocked`** —— 324 个独立点中 320 个首次成功（0.9877）；4 个失败点全部是 B-DQ 的 875 °C 与 900 °C |
| 关键结论 | 独立单点模式**没有**消除失败；全新进程中重复求解同一条件会随机返回"没有任何相摩尔数"（B-DQ 900 °C 成功 1/8、875 °C 成功 2/4），因此这是该体系在 α/γ 相界附近的**求解不确定性问题**，与求解模式无关 |
| 第二阻断项 | R-DQ 批量模式与独立点模式在 **675 °C** 的共同收敛点上相差 **1.069×10⁻⁴**（容差 1×10⁻⁷）：相同三相组合、相分数不同 → 两条曲线都不发布，差异如实报告 |

完整报告见 [T86 第五阶段：每个温度点独立进程求解](docs/T86_PHASE5_INDEPENDENT_POINTS.md)。第五阶段**未**引入新的第三方组件或数据集。

完整证据与复现命令见 [T86 第三阶段：社区兼容版数据库审查与兼容性验证](docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md)，机器可读证据见 `config/calphad_gate_evidence_v1.1.json`；第二阶段门禁证据仍保留在 `config/calphad_gate_evidence_v1.0.json`，流程与阻断规则见 [T86 CALPHAD 相分数](docs/T86_CALPHAD_PHASE_FRACTION.md)。

## 官方核对链接

- Frictionless：[仓库](https://github.com/frictionlessdata/frictionless-py)、[v5.19.0](https://github.com/frictionlessdata/frictionless-py/releases/tag/v5.19.0)、[MIT License](https://github.com/frictionlessdata/frictionless-py/blob/v5.19.0/LICENSE.md)、[PyPI](https://pypi.org/project/frictionless/5.19.0/)
- NOMAD：[仓库](https://github.com/FAIRmat-NFDI/nomad)、[v1.4.3](https://github.com/FAIRmat-NFDI/nomad/releases/tag/v1.4.3)、[Apache-2.0 License](https://github.com/FAIRmat-NFDI/nomad/blob/v1.4.3/LICENSE)、[官方文档](https://docs.nomad-lab.eu/1.4.3/)
- GEMD：[仓库](https://github.com/CitrineInformatics/gemd-python)、[v2.2.4](https://github.com/CitrineInformatics/gemd-python/releases/tag/v2.2.4)、[Apache-2.0 License](https://github.com/CitrineInformatics/gemd-python/blob/v2.2.4/LICENSE)
- Great Expectations：[仓库](https://github.com/fivetran/great_expectations)、[1.21.0](https://github.com/fivetran/great_expectations/releases/tag/1.21.0)、[Apache-2.0 License](https://github.com/fivetran/great_expectations/blob/1.21.0/LICENSE)、[PyPI](https://pypi.org/project/great-expectations/1.21.0/)
- MLflow：[仓库](https://github.com/mlflow/mlflow)、[v3.16.0](https://github.com/mlflow/mlflow/releases/tag/v3.16.0)、[Apache-2.0 License](https://github.com/mlflow/mlflow/blob/v3.16.0/LICENSE.txt)、[PyPI](https://pypi.org/project/mlflow/3.16.0/)
- pycalphad（T86）：[仓库](https://github.com/pycalphad/pycalphad)、[v0.11.2](https://github.com/pycalphad/pycalphad/releases/tag/0.11.2)、[MIT License](https://github.com/pycalphad/pycalphad/blob/0.11.2/LICENSE.txt)、[PyPI](https://pypi.org/project/pycalphad/0.11.2/)
- MatCalc `mc_fe` v2.062（T86 数据库上游）：[开放数据库页面](https://www.matcalc.at/index.php/databases/open-databases)、[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)、[DbCL 1.0](https://opendatacommons.org/licenses/dbcl/1-0/)
- 社区派生候选（T86 阶段 3）：[maraging-steel-calphad-dft](https://github.com/adityamoolya/maraging-steel-calphad-dft)（无 LICENSE 文件）、[pycalphad Discussion #705](https://github.com/pycalphad/pycalphad/discussions/705)
- T86 第四阶段为**项目内政策与验证**，未新增任何第三方组件或数据集：只登记固定缩减体系与相集合，未引入新依赖、未下载新数据。

后续重新评估时必须更新核对日期和固定引用，不能把这里记录的版本自动解释成“永远最新”。

## T62 公开数据登记

`Steel Plates Faults` 由 UCI Machine Learning Repository 发布，数据集 ID 198，DOI `10.24432/C5J88N`，页面明确标注 CC BY 4.0。T62 固定官方 ZIP 及内部数据/字段文件 SHA-256，保留 Buscema、Terzi 与 Tastle 的署名；仓库只提交获取代码、许可记录和验证规则，不重新分发原始数据。完整登记见 `config/real_data_case_v1.0.json` 和 `docs/T62_REAL_DATA_CASE.md`。
