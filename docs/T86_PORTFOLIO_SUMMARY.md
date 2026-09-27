# T86 Portfolio Summary · 开源计算热力学探索

> One-page bilingual summary for the job-application portfolio. Full evidence is linked at the end;
> no new phase documents are added.

## 一句话结论 · One-line status

| 维度 | 状态 |
| --- | --- |
| Portfolio / engineering | `portfolio_exploration_complete` |
| Scientific use | `scientific_use_blocked_by_solver_stability` |

T86 是作品集里的**开源计算热力学探索功能**：公开合成演示已端到端通过并可下载；真实 B-DQ/R-DQ 科研计算保持**阻断**，不发布真实钢种曲线，也不形成材料结论。

T86 is a **computational-thermodynamics exploration feature** for the portfolio. The public synthetic demo passes end to end and is downloadable; the real B-DQ/R-DQ scientific calculation stays **blocked** — no real steel-grade curve and no materials conclusion is published.

## 负责人验收签署 · Owner sign-off

| 项目 | 值 |
| --- | --- |
| 记录文件 | `config/calphad_owner_acceptance_v1.0.json`（`registry_id = SteelAI-CALPHAD-Owner-Acceptance-v1.0`） |
| `record_id` | `T86-PORTFOLIO-OWNER-SIGN-OFF-20260925` |
| `responsible_person_id` | **世道** |
| `signed_at` | **2026-09-25** |
| `timezone` | **Asia/Shanghai** |
| `decision_scope` | **`portfolio_engineering_acceptance_only`** |
| `portfolio_demo_evidence_version` | `SteelAI-T86-Portfolio-Demo-Evidence-v1.0` |
| 演示数据库 SHA-256 | `7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042` |
| `scientific_use_approved` | **false** |
| `real_sample_curves_published` | **false** |
| `materials_conclusion_approved` | **false** |
| 作品集验收索引 | `config/portfolio_acceptance_v1.0.json`（同一 `record_id`） |

签署接受的结论：

> T86 的公开合成 Fe–C 演示已通过工程与作品集验收，可作为求职作品展示。T86 不承担真实钢种科研分析；B-DQ/R-DQ 继续保持 `scientific_use_blocked_by_solver_stability`，不发布真实曲线，不形成材料结论。

**边界**：本次签署**只**覆盖公开合成演示的工程与作品集验收，**不得**解释为真实钢种计算审批、科研结论批准或生产决策依据。记录为追加式、版本化、具名，不含任何实测成分数值。

**Owner decision on record / 负责人决定记录**（签署前的工作定位决定）：

> T86 定位为求职作品集中的开源计算热力学探索功能，不承担真实钢种科研分析。公开合成演示通过即可完成工程验收；真实 B-DQ/R-DQ 计算保持阻断。

## 展示要点 · What this demonstrates

| # | 能力 | 证据 |
| --- | --- | --- |
| 1 | **开源计算热力学工具选型** | 选用 `pycalphad==0.11.2`（MIT）作为可关闭适配器，主应用不导入它；候选在模型登记册中先以 `database_required` 立项再逐步收敛。`config/calphad_adapter_v1.0.json` |
| 2 | **软件与数据库许可证审查** | pycalphad MIT（OSI 已核）；MatCalc `mc_fe v2.062` 为 **ODbL 1.0 + DbCL 1.0**，与 MIT 相互独立、不随仓库分发；社区派生库保留上游许可与署名，来源仓库**无 LICENSE 文件**故未复制任何代码。`THIRD_PARTY.md` |
| 3 | **独立环境与依赖锁定** | `.venv-pycalphad`（CPython 3.12.14）34 个包全部按版本 + wheel SHA-256 锁定；主应用 `requirements*.txt` 未改动。`requirements-calphad-win-py312.lock` |
| 4 | **TDB 方言兼容性审计** | 官方原件无法被 pycalphad 解析（平台编码 + 第 180 行 `REFERENCE_ELEMENT`）；用合成关键字探针逐条证明 `REFERENCE_ELEMENT`/`ADD_COMPOSITION_SET`/`ATTACH_CONTRIBUTION`/`CREATE_NEW_PHASE`/`HMVA` 均不在文法内。**未删除关键字、未改写数据库、未制作"兼容版 TDB"**。`config/calphad_gate_evidence_v1.0.json` |
| 5 | **社区派生数据库的差异验证** | 对第三方社区派生库做规范化全量差异审计：4,515 条共享语句、**0 条未解释差异**；并独立复现上游 5 个二元体系 15/15 检查与项目相关 18/18 检查。`docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md` |
| 6 | **`VA` 缺失导致"数值合计正常但物理结果错误"** | 组元列表漏掉空位 `VA` 时 pycalphad **不报错**，B-DQ 在 400 °C 报 **LIQUID 0.97**，而相分数合计仍是 **0.99942** —— 只检查合计无法发现。修复后同点为 `BCC_A2 0.9685 + CEMENTITE 0.0277 + FCC_A1 0.0032`；并因此加入物理合理性守卫。`docs/T86_PHASE4_REDUCED_SYSTEM.md` §7 |
| 7 | **高维计算的内存与求解稳定性边界** | 本机 pycalphad 0.11.2 对 **≥14 个组元条目**直接中止（`MemoryError` / `minimizer.pyd` 原生 `0xC0000005`、`0xC0000374`），在独立对照库 `COST507` 上复现同一边界；同一解释器内构造大量相记录会触发 symengine LLVM JIT 中止。`docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md` §3.1 |
| 8 | **关闭式失败、结果溯源与科研诚信** | 每个门禁都阻断而非降级：缺环境/缺 TDB/哈希不符/兼容性未过/元素未覆盖/未具名批准一律阻断；结果命名为 `12-component reduced-system matrix equilibrium prediction`，永远携带排除元素及原因、模型损失、版本与哈希、`pending_human_review`、不写回、非完整相图。`config/calphad_reduced_system_v1.0.json` |
| 9 | **公开演示能力与真实科研限制** | 公开合成演示（Fe–C，25 点，独立单点进程）两次运行**最大差 0.0**，页面可展示曲线并下载 Markdown/JSON/CSV；真实样品区域明确标注 `scientific_use_blocked_by_solver_stability` 与三条具体原因。`scripts/calphad_portfolio_demo_acceptance.py` |

## 公开合成演示 · Public synthetic demo

| 项目 | 值 |
| --- | --- |
| 体系 | Fe–C 亚稳系（悬置石墨），固定成分 Fe-0.45 wt.% C |
| 输入 | **公开合成**，不读取 B-DQ/R-DQ 或任何私人实验数据 |
| 组元 / 相集合 | `FE, C`（+`VA`）/ `LIQUID, FCC_A1, BCC_A2, CEMENTITE`（全部为第四阶段已验证相） |
| 温度 / 压力 | 400–1600 °C，步长 50 °C，25 点（落在数据库声明的 400–1727 °C 内）；101325 Pa |
| 求解模式 | `independent_single_point_process_v1`（每个温度点一个全新 worker 进程） |
| 数据库 | `MATCALC-MC-FE-V2062-COMMUNITY-CLEAN-19B1164`，SHA-256 `7cf37dd4…42` |
| 两次运行最大差 | **0.0**（容差 1×10⁻⁷） |
| 结果标记 | `portfolio_demo`、`public_synthetic_input`、`model_prediction_not_experimental_measurement`、`not_for_scientific_conclusion`、`is_complete_phase_diagram=false`、`writes_back_formal_experimental_data=false` |
| 下载 | Markdown / JSON / CSV（每行都带限制与求解模式） |
| 写入 `data/processed/` | **否** |

## 真实科研限制 · Why scientific use is blocked

1. **容量**：全组元体系 16 个组元条目超过本机实测求解上界 13。
2. **稳定性**：缩减体系在 **B-DQ 875/900 °C** 附近不稳定收敛；全新进程中重复求解同一单点条件，900 °C 成功 **1/8**、875 °C **2/4**，失败形态是"没有任何相摩尔数"（不是崩溃、不是超时）。324 点验收首次成功率 **320/324 = 98.77%**。
3. **模式差异**：批量模式与独立点模式在 **R-DQ 675 °C** 相差 **1.069×10⁻⁴**（容差 1×10⁻⁷），相同三相组合、相分数不同 → 两条曲线都不发布。

因此：**不发布真实钢种曲线，也不形成材料结论**；两条真实曲线的取舍需要具名科研决定。

## 入口 · Where to look

- 页面：**分析与报告 → 物理计算 → 页签「平衡相分数—温度（可选 · T86）」**，内含「区域 1 · 公开合成演示」与「区域 2 · 真实样品探索」。
- 负责人验收记录：`config/calphad_owner_acceptance_v1.0.json`（并登记在 `config/portfolio_acceptance_v1.0.json`）。
- 复现公开演示：见下方命令。
- 详细证据（本页不重复内容）：见链接。

```powershell
# 状态一致性（签署记录 + 双状态）
.\.venv\Scripts\python.exe -X utf8 -c "from steelai.calphad_adapter import owner_acceptance_status; import json; print(json.dumps(owner_acceptance_status(), ensure_ascii=False, indent=2))"

# 快速验收（公开合成演示端到端两次 + 下载与降级检查）
.\.venv\Scripts\python.exe -X utf8 scripts\calphad_portfolio_demo_acceptance.py `
  --json outputs\calphad_portfolio_demo_acceptance.json

# 定向测试
.\.venv\Scripts\python.exe -B -m pytest -q tests\test_t86_calphad_adapter.py
```

## 链接的详细证据 · Linked evidence

- [T86 CALPHAD 相分数（阶段 1）](T86_CALPHAD_PHASE_FRACTION.md)
- [T86 第二阶段：隔离环境与兼容性门禁](T86_PHASE2_ENVIRONMENT_AND_GATES.md)
- [T86 第三阶段：社区兼容版数据库审查与兼容性验证](T86_PHASE3_COMMUNITY_COMPATIBILITY.md)
- [T86 第四阶段：固定缩减成分体系与固定相范围](T86_PHASE4_REDUCED_SYSTEM.md)
- [T86 第五阶段：每个温度点独立进程求解](T86_PHASE5_INDEPENDENT_POINTS.md)
- [第三方开源复用登记](../THIRD_PARTY.md)，[已知限制](KNOWN_LIMITATIONS.md)，[当前能力](CURRENT_CAPABILITIES.md)
- 负责人验收记录：[config/calphad_owner_acceptance_v1.0.json](../config/calphad_owner_acceptance_v1.0.json)，作品集验收索引：[config/portfolio_acceptance_v1.0.json](../config/portfolio_acceptance_v1.0.json)
