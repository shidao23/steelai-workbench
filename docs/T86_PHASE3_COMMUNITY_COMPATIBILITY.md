# T86 第三阶段：社区兼容版数据库候选审查与兼容性验证

结论先行：**社区派生候选通过了"可解析 + 差异审计 + 上游二元验证复现"三个层面，但本项目两个炉次在当前隔离环境中无法求解，T86 保持 `Blocked`。** 数据库候选本身记为 `compatibility_candidate`，不得记为 `validated` / `production_ready` / `pilot_ready_pending_scientific_review`。

本文件只记录软件行为与基本热力学合理性，**不构成任何钢种的实验验收**。

## 1. 候选登记（第三方社区派生数据库候选）

| 项目 | 值 |
| --- | --- |
| 候选标识 | `MATCALC-MC-FE-V2062-COMMUNITY-CLEAN-19B1164` |
| 来源仓库 | [adityamoolya/maraging-steel-calphad-dft](https://github.com/adityamoolya/maraging-steel-calphad-dft) |
| 仓库内文件 | `2databases/mc_fe_v2062_clean.tdb` |
| 固定提交 | `19b11640253543fe412145498438cb8355a32561` |
| 背景证据 | pycalphad GitHub Discussion #705 |
| 文件大小 | 479,418 字节 |
| SHA-256 | `7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042` |
| 编码 / 行数 / 语句数 | utf-8 / 12,628 行 / 4,517 条语句 |
| 上游原件 | MatCalc `mc_fe` v2.062（TU Wien IMST，2024-11-08），SHA-256 `aa02077e…c64865` |
| 许可证 | 上游 ODbL 1.0 + DbCL 1.0 原样保留在文件头（第 26–29 行）；派生库同为 ODbL 派生数据库，须保持 ODbL；公开成果需署名声明 |
| 署名要求 | 保留原评估者署名（E. Povoden-Karadeniz、A. Jacob）与社区修改者署名 |
| 本地存放 | Git 忽略的 `model_lab/calphad/databases/community/`，**不提交、不再分发** |
| 公开仓库保留 | `config/calphad_tdb.example.json` 模板、`model_lab/calphad/README.md` 获取说明、`config/calphad_gate_evidence_v1.1.json` 证据、本文件 |
| 命名纪律 | 只能称为"第三方社区派生数据库候选"；**不得**称为 TU Wien 官方 pycalphad 兼容版、pycalphad 官方数据库或 SteelAI 已验证数据库 |
| 是否被修改 | **未修改**。SteelAI 未编辑该文件，也未制作任何"兼容版 TDB" |

来源仓库自身没有 LICENSE 文件，因此仓库内**没有复制任何第三方代码**，只按上游许可证取得了数据文件用于本地验证。

## 2. 全量差异审计（相对 TU Wien 原件）

脚本：`scripts/calphad_tdb_diff_audit.py`（原始报告写入 Git 忽略的 `outputs/calphad_diff_audit.json`）。

结论：`passed_syntax_repairs_only`，**未解释差异 0 条**。审计基于规范化后的共享参数集逐条比较，并逐条归类；**没有**用作者"未改动参数"的声明替代本地验证。

| 差异类别 | 条数 | 性质 |
| --- | --- | --- |
| `reference_key_normalisation` | 4 | 语法规范化（引用记录键） |
| `invalid_delimiter_repair` | 1 | `G(G_PHASE;` → `G(G_PHASE,` |
| `invalid_numeric_literal_repair` | 2 | `6000.00.00` → `6000.00` |
| `duplicate_fragment_repair_verified` | 2 | PDMN_B2 重复片段，已用合成探针逐条验证修复后表达式与原意一致 |
| `duplicate_or_stray_fragment_removal` | 1 | 冗余片段删除 |
| `missing_terminator_split` | 1 | LAVES_PHASE 语句缺终止符 |
| `structural_change_numbers_preserved` | 1 | 结构变化但数值全部保留 |
| `matcalc_only_command_removed` | 7 | `REFERENCE_ELEMENT`（1）、`ATTACH_CONTRIBUTION`（1）、`ADD_COMPOSITION_SET`（12 行并入 7 条） |
| `matcalc_only_parameter_removed` | 21 | `PARAMETER HMVA`（pycalphad 无此参数类型） |

- 共享语句比较规模：4,515 条。
- 77 行 `$ Cleaned by script:` 注释块被重新拼装为 35 条语句，**35 条全部匹配**到上游语句。
- **未发现**任何 Gibbs 能量、相互作用参数、磁性参数、温度断点或数值系数被改动；出现即按要求立即阻断。

## 3. 兼容性门禁（与既有 `.venv-pycalphad` / pycalphad 0.11.2）

隔离环境：CPython 3.12.14 + `pycalphad==0.11.2`（wheel SHA-256 `53f654…3ac58`），34 包全部哈希锁在 `requirements-calphad-win-py312.lock`。该环境由本机缓存的 CPython 创建，**不是自包含环境**。

| # | 门禁项 | 结果 |
| --- | --- | --- |
| 1 | 直接解析 | **通过**（显式 utf-8 解码；`Database(path)` 在本机 GBK 区域设置下失败、加 `-X utf8` 后通过——属主机区域设置问题，非数据库不兼容） |
| 2 | 元素 / 相 / 函数 / 参数计数 | **通过**：25 个合金元素（含 VA 共 26）、132 相、26 物种、123 函数、4,094 参数 |
| 3 | 有序-无序关系 | **通过解析**，但有序-无序链接数为 **0**：BCC_B2 未与 BCC_A2 耦合（模型损失，见第 5 节） |
| 4 | Workspace 构造 | **通过**：16 组元 × 132 相可构造 |
| 5 | 单点平衡 | **声明成分下无法评估**：首次求解即中止（见下） |
| 6 | 温度扫描 | **声明成分下无法评估**，同上 |
| 7 | 相分数合计 / 重复性 / 未收敛 | **声明成分下无法评估**；在 ≤13 组元体系上实测合计 `1.000000` |
| 8 | 全部运行落在声明成分与 673–2000 K 内 | **温度范围通过**：请求 400–1725 °C = 673.15–1998.15 K，落在数据库声明区间内；**成分无法运行** |

解析时输出的唯一告警：`TYPE_DEFINITION` 字符 `%` 在 132 个相上被引用但库中无对应定义行；该字符对本库不参与建模。

### 3.1 阻断级发现：本环境求解组元数上限

**pycalphad 0.11.2 在本机对"组元列表长度 ≥14"的体系无法求解**，实测上界为 13（Fe + 11 个合金元素 + VA）。

| 组元列表长度 | 社区候选 | 独立对照 COST507 |
| --- | --- | --- |
| 12 | 求解成功（合计 1.000000） | 求解成功（合计 1.000000） |
| 13 | 求解成功（合计 1.000000） | 求解成功（合计 1.000000） |
| 14 | **进程中止 0xC0000005** | **进程中止 0xC0000005** |
| 15 | **进程中止 0xC0000005** | **进程中止 0xC0000374** |

排除性对照（全部证明与该限制无关）：

- **与数据库无关**：在 pycalphad 自带的独立数据库 `COST507.tdb` 上复现出**完全相同的 13/14 边界**。
- **与相列表无关**：单相列表、两相列表、132 相列表都会中止。
- **与初始点密度无关**：`pdens` = 10 / 50 / 200 / 2000 都中止。
- **与具体元素无关**：把第 14 个组元分别换成 B、N、P、S、Co、Ta、Y、W、Hf，全部中止。
- **与线程栈无关**：4 MB / 16 MB / 64 MB 线程栈均中止。

观测到的失败形态：

| 形态 | 细节 | 出现位置 |
| --- | --- | --- |
| `MemoryError` | 无法分配 10.9 GiB，数组形状 `(1, 1, 54, 933583, 29)` | 产品路径（隔离 worker，退出码 2） |
| 原生中止 | `0xC0000005` ACCESS_VIOLATION，故障模块 `pycalphad/core/minimizer.cp312-win_amd64.pyd` | 验证脚本 |
| 原生中止 | `0xC0000374` HEAP_CORRUPTION，同一原生扩展 | 验证脚本 |
| 挂死 | 无结果、内存无界增长（实测 3.9 GB） | 验证脚本，由超时终止 |

中止点定位精确：**Workspace 构造成功，中止发生在第一次求解**（`workspace.get()` / `equilibrium()`）。

本项目 B-DQ 与 R-DQ 都需要 16 个组元条目，因此**当前环境无法产出任何真实炉次的相分数—温度曲线**。

产品路径的处理是**关闭式**而非降级：`state=blocked`、`CALPHAD-RUN-001`，worker 报 `CALPHAD-WORKER-MEMORY-001` 并写明实测容量上限；**没有**丢弃任何组元、**没有**裁剪相列表、**没有**代入默认值。

## 4. 上游 15 项二元验证复现与项目相关检查

脚本：`scripts/calphad_candidate_validation.py`（原始报告写入 Git 忽略的 `outputs/calphad_candidate_validation.json`）。
每次平衡计算都在**独立子进程**中运行并带墙钟超时——因为 pycalphad 可能以原生方式终止进程而不是抛异常，崩溃隔离是让失败可被记录而不是让整个套件死掉的前提。

### 4.1 社区仓库声称的 5 个二元体系 / 15 项检查

判据由本项目**按下述条件重新实现**，未使用作者图片、结论或源码（该仓库无 LICENSE）。

网格：成分 9 点（x = 0.01–0.99）× 温度 13 点（500–1890 K），相列表限定为该体系点名的相。

| 体系 | 检查项 | 结果 |
| --- | --- | --- |
| Fe-Cr | SIGMA 相出现；Fe 侧 >800 °C 存在 FCC 奥氏体回路；高温出现 LIQUID | **3/3** |
| Fe-Ni | 高 Ni 时 FCC 为主；低 Ni 低温 BCC；高温 LIQUID；存在 BCC+FCC 两相区 | **4/4** |
| Fe-Ti | 出现 LAVES_PHASE（Fe2Ti）；低 Ti 时 BCC 稳定；高温 LIQUID | **3/3** |
| Fe-Mo | 出现 SIGMA 或 MU_PHASE；BCC 为主；高温 LIQUID | **3/3** |
| Ni-Ti | 出现 ETA（Ni3Ti）；Ni 侧 FCC | **2/2** |

**合计 15/15 复现，0 项失败。**

### 4.2 与本项目相关的检查

| 体系 | 成分扫描范围 | 检查项 | 结果 |
| --- | --- | --- | --- |
| Fe-C（稳定系，允许石墨） | x_C 0.0005–0.05 | 出现 GRAPHITE；出现 FCC_A1 | **2/2** |
| Fe-C（亚稳系，悬置石墨） | x_C 0.0005–0.05 | 出现 CEMENTITE；出现 BCC_A2 | **2/2** |
| Fe-Cr-C | x_Cr 0.03–0.30，x_C 固定 0.02 | 出现 M7C3 或 M23C6；出现 M23C6 | **2/2** |
| Fe-Mn / Fe-Si / Fe-Nb / Fe-V / Fe-B / Fe-N | x 0.01–0.99 | 各 2 项（基体相 + 碳/氮/硼/硅化物相） | **12/12** |

**合计 18/18 通过。**

说明：石墨存在时渗碳体是亚稳相，因此 Fe-C 被评估两次——稳定系检查石墨，亚稳系（悬置石墨）检查渗碳体。这与 CALPHAD 惯例一致，不是数据库缺陷。

### 4.3 MC/MX 碳氮化物可达性（模型损失探针）

Fe-C-N-Nb-Ti-V 体系：**MC/MX 组合集不可达**，与文档化的模型损失一致（`agrees_with_expectation = true`）。因此 pycalphad **无法**分辨 Nb/Ti/V 碳氮化物的相分数。

这些检查**只证明软件行为与基本热力学合理性**，不是真实钢种的实验验收。

## 5. 已知模型损失与后果判定

| 模型损失 | 状态 | 后果判定 |
| --- | --- | --- |
| BCC_B2 有序-无序耦合 | `ATTACH_CONTRIBUTION` 被注释，链接数 0 | `unknown_model_impact`——**未证明**"无影响"；也未证明 BCC_B2 会进入 B-DQ/R-DQ 稳定组合（该体系无法求解） |
| MC/MX 组合集 | `ADD_COMPOSITION_SET` 被注释，组合集相为 0 | `unknown_model_impact`——探针证明当前不可达，但对 Nb/Ti/V 碳氮化物在目标窗口的影响无法量化 |
| HMVA 参数（21 条） | 被注释；pycalphad 无此参数类型 | `unknown_model_impact`——这些参数**从未**进入任何一次计算；"当前平衡不受影响"**未获证明**，因此不作此声明 |
| `REFERENCE_ELEMENT FE` | 被注释 | `unknown_model_impact`——参考态设置丢失 |

上述四条已作为**永久限制**，随每次运行的 MD / 图 / JSON / CSV / 结果包一同输出，并与 As/Sn/Sb/O/W 限制一起承载。

## 6. 状态判定与解除条件

| 对象 | 状态 |
| --- | --- |
| 社区派生数据库候选 | `compatibility_candidate` |
| T86 功能 | **`Blocked`** |

判定依据：

- 差异审计通过（仅语法修复，0 条未解释）；
- 候选可解析，门禁 1–4 通过；
- 上游 5 个二元体系 15 项检查 **15/15** 复现，项目相关检查 **18/18** 通过；
- **但**两个真实炉次（16 个组元条目）在本环境**无法求解**，门禁 5–8 中的成分相关项无法评估，验证不完整，且功能无法对真实样品产出结果。

**未**声明：`validated`、`production_ready`、`pilot_ready_pending_scientific_review`。

解除条件（需项目负责人具名决定，任一都不得静默执行）：

1. 修复或更换隔离环境（例如更换 symengine / pycalphad 构建，或改用能处理多组元体系的求解器），使 ≥16 组元体系可解；或
2. 具名批准**缩减成分体系**（例如把 B/N/P/S 中的若干元素纳入受控排除声明），并同步新版本政策；或
3. 具名批准**受限相列表**，并说明其科学依据与适用边界；或
4. 把 T86 冻结为技术框架（保留阶段 1 的适配器与治理边界，不产出真实炉次结果）。

第 2、3 项都会改变科学声明，必须走版本化政策更新，且需要说明对目标窗口结论的影响。

## 7. 复现命令

```powershell
# 门禁与结构检查（隔离解释器）
.\.venv-pycalphad\Scripts\python.exe -X utf8 scripts\calphad_compatibility_gate.py `
  --db model_lab\calphad\databases\community\mc_fe_v2062_clean_19b1164.tdb `
  --json outputs\calphad_community_gate.json

# 全量差异审计（原件 vs 候选）
.\.venv-pycalphad\Scripts\python.exe -X utf8 scripts\calphad_tdb_diff_audit.py `
  --original model_lab\calphad\databases\mc_fe_v2062.tdb `
  --candidate model_lab\calphad\databases\community\mc_fe_v2062_clean_19b1164.tdb `
  --json outputs\calphad_diff_audit.json

# 独立验证套件（含 15 项社区检查、18 项项目检查、组元容量探针）
.\.venv-pycalphad\Scripts\python.exe -X utf8 scripts\calphad_candidate_validation.py `
  --json outputs\calphad_candidate_validation.json
```

产品路径（主解释器，需本地已登记 TDB）：

```powershell
python -c "from steelai import calphad_adapter as a; print(a.calphad_feature_status())"
```

## 8. 本轮明确未做的事

- 未删除、注释或改写数据库中的任何关键字。
- 未制作任何"兼容版 TDB"。
- 未为迁就求解器容量而静默丢弃组元或裁剪相列表。
- 未复制任何第三方源码。
- 未把数据库内容提交进仓库。
- 未把任何结果标记为 `validated` / `production_ready` / `pilot_ready`。
- 未处理临时目录 ACL 与随机 ID 抖动断言（独立任务）。

## 相关文档

- [T86 CALPHAD 平衡相分数（阶段 1）](T86_CALPHAD_PHASE_FRACTION.md)
- [T86 第二阶段：隔离环境与兼容性门禁](T86_PHASE2_ENVIRONMENT_AND_GATES.md)
- [T86 CALPHAD 数据库候选审查](T86_CALPHAD_DATABASE_CANDIDATE_REVIEW.md)
- 登记与证据：`config/calphad_adapter_v1.0.json`、`config/calphad_tdb.local.json`（Git 忽略）、`config/calphad_gate_evidence_v1.1.json`、`THIRD_PARTY.md`
