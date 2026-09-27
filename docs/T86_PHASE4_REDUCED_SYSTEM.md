# T86 第四阶段：固定缩减成分体系与固定相范围

结论先行：**固定成分体系 `steel_matrix_equilibrium_v1` 与固定相集合 `steel_matrix_major_carbides_v1` 已建立并通过独立探针验证；十步验证中第 1–5、7、9 步通过，但第 6 步（B-DQ 缩减体系）在 875 °C 求解不收敛，因此 T86 保持 `Blocked`，数据库候选仍为 `compatibility_candidate`。** 不换环境、不升级 pycalphad、不尝试全 16 组元求解。

> **第五阶段更新**：本文件描述的批量 Workspace 热启动路径自第五阶段起**降级为仅诊断用**（`solver_mode=batch_workspace_warm_start`，`status=diagnostic_only`），正式路径改为 `independent_single_point_process_v1`（每个温度点一个全新 worker 进程）。第五阶段还证明第 6 步的失败**并非**批量热启动所致：在全新进程中重复求解同一单点条件，875/900 °C 仍会随机无解。详见 [T86 第五阶段：每个温度点独立进程求解](T86_PHASE5_INDEPENDENT_POINTS.md)。

**不得**标记为 `validated` / `production_ready` / `pilot_ready_pending_scientific_review`。

## 1. 固定成分体系 `steel_matrix_equilibrium_v1`

政策文件：`config/calphad_reduced_system_v1.0.json`（固定、版本化；**不是**通用元素选择开关）。

| 项目 | 值 |
| --- | --- |
| 纳入组元（12） | `Fe, C, Mn, Si, Cr, Ni, Mo, Cu, Al, Nb, Ti, V` |
| 送入 pycalphad 的组元条目 | 13（上述 12 + `VA`，见第 7 节） |
| 与求解器容量的关系 | 第三阶段实测本机上界为 13 个组元条目；14 即中止 |

明确排除：

| 元素 | 类别 | 说明 |
| --- | --- | --- |
| `B, N, P, S` | `capacity_reduction` | **有测量值**，但为了建立低于 pycalphad 实测容量上限的基体相计算体系而排除 |
| `As, Sn, Sb` | `database_not_covered` | mc_fe 不含其 ELEMENT 条目 |
| `O, W` | `input_unknown` | 当前没有测量值，**不能按 0** |

固定性由代码保证：适配器把"成分 + 批准排除"推导出的组元集合与政策中的 `included_elements` **逐项比对**，不一致即 `CALPHAD-COMP-012` 阻断；政策本身又用模块常量校验（编辑政策文件也无法悄悄放宽）。**没有**任何界面或参数可以增删元素。

## 2. 固定相范围 `steel_matrix_major_carbides_v1`

| 项目 | 值 |
| --- | --- |
| 相集合（7） | `LIQUID, FCC_A1, BCC_A2, CEMENTITE, M23C6, M7C3, M6C` |
| 实施前核对 | 相名以解析后的数据库为准，全部存在 |
| 独立探针 | `scripts/calphad_phase_profile_probe.py` |
| 探针证据 | `config/calphad_phase_profile_evidence_v1.0.json` |

探针判据（四条全过才保留；不通过即从第一版移除并记录原因，**不得改写 TDB 强行启用**）：

| 相 | 数据库内 | 参数条数 | 组成元数 | 相记录可构造 | 单相可解 | 体系内可达次数 | 结论 |
| --- | --- | ---: | ---: | --- | --- | ---: | --- |
| LIQUID | 是 | 572 | 23 | 是 | 是 | 40 | 保留 |
| FCC_A1 | 是 | 510 | 26 | 是 | 是 | 499 | 保留 |
| BCC_A2 | 是 | 413 | 26 | 是 | 是 | 169 | 保留 |
| CEMENTITE | 是 | 51 | 15 | 是 | 是 | 20 | 保留 |
| M23C6 | 是 | 156 | 10 | 是 | 是 | 86 | 保留 |
| M7C3 | 是 | 23 | 10 | 是 | 是 | 55 | 保留 |
| M6C | 是 | 508 | 10 | 是 | 是 | 68 | 保留 |

**移除相：无。** 可达性在 320 点网格上统计（合成参照成分，C 0.003–0.06、Cr 0.008–0.20、Mo 0.0012–0.030，873–1673 K）；M6C 只在较高 Mo/Cr 下出现，因此该判据必须覆盖高于两个炉次的合金区间，否则会把"这两个炉次用不到"误判成"相不可用"。

本阶段明确**不计算**：BCC_B2 有序-无序相、MC/MX 组合碳氮化物、氮化物、硼化物、硫化物、磷化物、氧化物与夹杂物、As/Sn/Sb 相关相、析出动力学/偏聚/晶界脆化/实际组织含量。

## 3. 具名批准（真实样品运行前）

必须由项目负责人逐项填写，**代码不代填姓名、也不提供默认值**；缺任一项即以 `CALPHAD-COMP-011` 阻断：

- `reviewer_id`（具名批准人）
- 批准时间（`YYYY-MM-DD` 或 ISO 8601）
- 批准理由
- 缩减体系版本 `steel_matrix_equilibrium_v1 v1.0`
- 排除元素列表
- 相集合版本 `steel_matrix_major_carbides_v1 v1.0`
- 数据库版本与 SHA-256

界面显示并必须勾选的确认文本：

> 我确认本次计算采用 12 组元缩减体系。B、N、P、S、As、Sn、Sb、O、W 未进入计算；结果只能用于 Fe 基体相和已验证主要碳化物的平衡趋势探索，不能用于评价这些被排除元素、夹杂物、碳氮化物、晶界偏聚或实际组织。

验证脚本同样要求显式传入 `--reviewer-id/--approved-at/--approval-reason`；不传时第 0 步即确认 `CALPHAD-COMP-011` 阻断（见第 5 节）。

## 4. 输出名称与限制

统一命名：`12-component reduced-system matrix equilibrium prediction`。

禁止使用：完整钢种热力学计算 / 完整相图 / 全成分平衡 / 实际组织预测 / 析出动力学结果。

页面、Markdown、JSON、CSV、图表与运行记录均包含：

`component_profile`、`phase_profile`、`reduced_component_system=true`、纳入元素、排除元素及原因、禁止解释的科学问题、BCC_B2/HMVA/MC-MX 已知模型损失、pycalphad 与数据库（含社区派生文件）版本与 SHA-256、`pending_human_review`、`writes_back_formal_experimental_data=false`。

## 5. 十步验证结果

报告：`outputs/calphad_phase4_validation.json`；可提交证据：`config/calphad_phase4_evidence_v1.0.json`。

| 步 | 内容 | 结果 |
| --- | --- | --- |
| 0 | 无具名批准必须阻断 | **通过**（`CALPHAD-COMP-011`，无请求生成） |
| 1 | 12 组元、1 个相的单点求解 | **通过**（7 个相逐一） |
| 2 | 12 组元、固定相集合的单点求解 | **通过** |
| 3 | 温度扫描 | **通过**（14 点，400–1725 °C） |
| 4 | 每个温度点相分数合计 | **通过**（0.9999999998–1.0000000004） |
| 5 | 重复运行一致性 | **通过**（合成参照体系逐位一致） |
| 6 | B-DQ 缩减体系 | **失败** —— 875 °C 求解不收敛 |
| 7 | R-DQ 缩减体系 | **通过**（54 点，合计 0.9999999998–1.0000000004；重复运行最大绝对差 3×10⁻⁹，容差 10⁻⁶；稳定相组合逐点一致） |
| 8 | B/R 使用完全相同的组元和相集合 | **未评估**（第 6 步失败导致） |
| 9 | 被排除元素确实没有进入 worker | **通过**（请求组元恰为 12 个批准元素） |
| 10 | 页面与所有导出均携带完整限制 | **未评估**（B-DQ 无结果记录） |

**总判定：`Blocked`。** 阻断项：`step6`、`step8`、`step10`（后两项是第 6 步失败的连带结果）。

R-DQ 通过的曲线物理形态正确：400–700 °C 为 BCC_A2 + CEMENTITE + 少量 FCC_A1，约 800 °C 进入 BCC_A2+FCC_A1 两相区，900–1400 °C 为 FCC_A1，1500 °C 为 BCC_A2 + LIQUID（δ 铁素体 + 液相），1600 °C 以上全液相。

### 5.1 第 6 步失败详情（阻断项）

- 现象：多温度批量扫描在 **1148.15 K（875 °C）** 返回"没有任何相摩尔数"。
- 已实现**有界单点重算**（批量求解留下空点的温度，用不带热启动的单温度平衡重算，上限 8 次，并在结果中记录重算温度）。875 °C 重算后**仍未收敛**，因此按规则阻断。
- **非位级抖动问题**：单独调用 850–1000 °C 各点均可收敛（FCC_A1 = 1.0），说明失败来自批量求解的热启动路径，不是热力学本身。
- **不确定性**：同一请求在不同进程中分别出现 0、1、2、3 个未收敛点；`pdens` = 500/1000/2000/4000/8000 都不能消除。
- 未采取任何"绕过"手段：没有删除温度点、没有改温区、没有改步长以避开失败点、没有放宽合计判据。

## 6. 独立探针的环境限制

在**同一解释器**中构造大量不同的 pycalphad 相记录会触发 symengine 的
`LLVM ERROR: IMAGE_REL_AMD64_ADDR32NB relocation requires an ordered section layout` 原生中止。
因此相探针按"每个相一个子进程"运行，可达性网格用**单次**多轴调用求值。该限制与第三阶段记录的求解器容量上限同源，属环境级限制。

## 7. 关键缺陷：`VA` 必须进入组元列表（已修复）

本轮发现并修复了一个会让**错误结果通过合计检查**的缺陷。

- **现象**：产品路径原先只把 12 个元素送进 pycalphad，未含空位 `VA`。pycalphad **不会因此报错**，而是返回物理上错误的结果：B-DQ 在 **400 °C 得到 LIQUID 0.97**（低合金钢在 400 °C 报 97% 液相），而相分数合计仍是 0.99942，**仅看合计无法发现**。
- **修正后**：同一点为 `BCC_A2 0.9685 + CEMENTITE 0.0277 + FCC_A1 0.0032`，温度序列符合预期。
- **修复**：worker 在数据库声明 `VA` 时**总是**把 `VA` 加入 pycalphad 组元列表，并在结果中输出 `pycalphad_components`。
- **新增守卫**：第四阶段验证加入物理合理性检查（1000 °C 以下不得出现液相、1500 °C 以上必须出现液相、700 °C 以下必须有 BCC_A2/FCC_A1 基体），因为合计检查无法覆盖这一类错误。

这条缺陷说明：**"相分数合计为 1"不足以证明结果正确**，必须叠加独立合理性检查。

## 8. 状态判定与解除条件

| 对象 | 状态 |
| --- | --- |
| 固定成分体系 `steel_matrix_equilibrium_v1` | 已批准并登记 |
| 固定相集合 `steel_matrix_major_carbides_v1` | 已验证并登记（7/7 保留） |
| 数据库候选 | `compatibility_candidate` |
| T86 功能 | **`Blocked`** |

解除条件（需具名决定，任一都不得静默执行）：

1. 解决 B-DQ 在 875 °C 附近的批量求解不收敛（例如按温度点独立求解并做一致性合并、调整初始点策略、或更换求解器构建），并使重复运行稳定通过；或
2. 具名批准把该温区从适用区间中排除，并说明对目标窗口结论的影响；或
3. 具名批准进一步缩减成分体系或相集合，并同步新版本政策；或
4. 把 T86 冻结为技术框架。

**不得**通过删除温度点、放宽合计判据或改写 TDB 来"通过"验证。

## 9. 复现命令

```powershell
# 相集合独立探针（隔离解释器；每相一个子进程）
.\.venv-pycalphad\Scripts\python.exe -X utf8 scripts\calphad_phase_profile_probe.py `
  --json outputs\calphad_phase_profile_probe.json

# 十步验证（主解释器；驱动真实适配器与隔离 worker）
.\.venv\Scripts\python.exe -X utf8 scripts\calphad_phase4_validation.py `
  --reviewer-id "<工作单中具名的批准人>" --approved-at 2026-09-25 `
  --approval-reason "<批准理由>" --json outputs\calphad_phase4_validation.json
```

第三阶段的全组元失败证据保留不变：`outputs/calphad_candidate_validation.json`（Git 忽略）与 `config/calphad_gate_evidence_v1.1.json`（可提交）。

## 10. 本轮明确未做的事

- 未更换隔离环境、未升级 pycalphad、未尝试全 16 组元求解。
- 未增删组元或相以让某次运行成功。
- 未删除、隐藏或替换任何温度点。
- 未改写 TDB、未制作兼容版 TDB。
- 未把任何结果写回 `data/processed/`。
- 未处理临时目录 ACL 或随机 ID 抖动断言（独立任务）。

## 相关文档

- [T86 CALPHAD 平衡相分数（阶段 1）](T86_CALPHAD_PHASE_FRACTION.md)
- [T86 第二阶段：隔离环境与兼容性门禁](T86_PHASE2_ENVIRONMENT_AND_GATES.md)
- [T86 第三阶段：社区兼容版数据库审查与兼容性验证](T86_PHASE3_COMMUNITY_COMPATIBILITY.md)
- [T86 耐磨钢 CALPHAD 数据库候选审查](T86_CALPHAD_DATABASE_CANDIDATE_REVIEW.md)
