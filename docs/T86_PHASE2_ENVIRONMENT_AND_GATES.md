# T86 第二阶段：独立环境、数据库来源与兼容性门禁

日期：2026-09-25 · 任务：T86 第二阶段 · **状态：`Blocked`（第一道兼容性门禁未通过，原始 `mc_fe v2.062` 不可选用）**

> 后续：第三阶段已按项目负责人决定改用第三方社区派生候选，并完成差异审计与验证复现；原始原件的门禁结论仍如本文件所记。第三阶段结果与本环境新发现的求解器容量上限见 [T86 第三阶段：社区兼容版数据库审查与兼容性验证](T86_PHASE3_COMMUNITY_COMPATIBILITY.md)。

本轮只做本文件与配置/证据的记录；**没有删除任何 TDB 关键字、没有改写数据库、没有制作"兼容版 TDB"、没有执行任何真实平衡计算**。

---

## 1. 独立环境（已按项目负责人批准安装）

| 项目 | 值 |
| --- | --- |
| 环境路径 | `.venv-pycalphad`（Git 忽略） |
| 解释器 | CPython **3.12.14**（与主应用同版本） |
| pycalphad | **0.11.2** |
| wheel SHA-256 | `53f6547738d02abb7349606548cce11747e22fc8a1308a1b866fb627e713ac58`（与第一阶段登记值**完全一致**） |
| 安装包总数 | **34** |
| 哈希锁文件 | [`requirements-calphad-win-py312.lock`](../requirements-calphad-win-py312.lock)（每个包都带 `--hash=sha256:`） |
| 主应用依赖 | **未改动**：`requirements.txt` / `requirements-dev.txt` / `requirements-enterprise.txt` 均不含 pycalphad |

安装命令（实际执行）：

```powershell
.\.venv\Scripts\python.exe -m venv .venv-pycalphad
.\.venv-pycalphad\Scripts\python.exe -m pip install --no-input --report outputs\calphad_install_report.json "pycalphad==0.11.2"
```

从安装报告生成的锁定文件覆盖全部 34 个包（含传递依赖：numpy 2.5.3、scipy 1.18.1、symengine 0.13.0、xarray 2026.7.0、matplotlib 3.11.2、pint 0.26.1、tinydb 4.9.0 等）。**未做洁净环境按锁重装**，属已记录的限制。

## 2. 数据库来源与许可（MatCalc mc_fe v2.062）

| 项目 | 值 |
| --- | --- |
| 官方发布位置 | <https://www.matcalc.at/images/stories/Download/Database/mc_fe_v2062.tdb> |
| 官方页面 | <https://www.matcalc.at/index.php/databases/open-databases> |
| 发布方 | MatCalc / TU Wien IMST；评估人 Erwin Povoden-Karadeniz、Aurélie Jacob；版权人与编辑 Erwin Povoden-Karadeniz |
| 版本 / 文件日期 | 2.062 / 2024-11-08 |
| 文件大小 | 489,296 字节 |
| SHA-256 | `aa02077eac3f602dd7479cbeafb09b450e282716752b3ae2b1fc3a57d9c64865` |
| 编码 | cp1252（含 9 个非 ASCII 字节） |
| 许可 | **ODbL 1.0 + DbCL 1.0**（页面与**数据库文件头部第 26–29 行**都声明） |
| 本地位置 | `model_lab/calphad/databases/mc_fe_v2062.tdb`（Git 忽略） |
| 登记文件 | `config/calphad_tdb.local.json`（Git 忽略） |
| 获取说明 | [`model_lab/calphad/README.md`](../model_lab/calphad/README.md) |

**不随仓库分发**：`.gitignore` 已忽略 `model_lab/calphad/databases/`；公开仓库只保留登记模板、来源记录与获取说明。ODbL 署名要求（发布派生成果时）见 README。

**从文件本身核实的结构事实**（`scripts/calphad_tdb_inspect.py`，只读）：

- 合金元素 **25 个**：Al B C Co Cr Cu Fe H Hf La Mn Mo N Nb Ni O P Pd S Si Ta Ti V W Y（另有 VA=空位）
- **不含 As、Sn、Sb** —— 连 `ELEMENT` 行都没有
- `PHASE` 语句 132 条 / 132 个基相；`TYPE_DEFINITION` 11 条，**其中 IF/THEN 型 0 条**
- **没有 `TEMPERATURE_LIMITS` 命令**；温区只写在注释里：`Temperature: 673 K - 2000 K`（第 60 行）
- 非 pycalphad 关键字共 **14 处 / 3 个**：`ADD_COMPOSITION_SET`×12（首次第 183 行）、`ATTACH_CONTRIBUTION BCC_B2 BCC_A2 ORDER_DISORDER`×1（第 199 行）、`REFERENCE_ELEMENT FE`×1（第 180 行）

## 3. 第一道门禁：**未通过**

命令（在隔离解释器中执行，数据库文件始终只读）：

```powershell
.\.venv-pycalphad\Scripts\python.exe -I scripts\calphad_compatibility_gate.py `
    model_lab\calphad\databases\mc_fe_v2062.tdb `
    --tdb-facts outputs\calphad_tdb_inspect.json --json outputs\calphad_gate_report.json
```

### 3.1 原始文件直接加载：编码失败

```
builtins.UnicodeDecodeError: 'gbk' codec can't decode byte 0x96 in position 485974: illegal multibyte sequence
  pycalphad/io/database.py:229 in from_file -> format_registry[fmt].read(dbf, fd)
  pycalphad/io/tdb.py:964 in read_tdb  -> lines = fd.read().upper()
```

pycalphad 用**平台 locale 编码**打开数据库；本机为 GBK，而厂商文件是 **cp1252**（首个非 ASCII 字节在偏移 828，`0xE9`，第 24 行；GBK 不接受的是偏移 485974 的 `0x96`）。

### 3.2 显式指定编码后：**语法门禁失败**（决定性）

即使把字节按 cp1252 正确解码（`Database.from_file(open(path, encoding='cp1252'), fmt='tdb')` 与 `Database.from_string(text, fmt='tdb')` 两条 pycalphad 官方入口都试过；**文件字节未改动**）：

```
pyparsing.exceptions.ParseException: Invalid TDB syntax.
     REFERENCE_ELEMENT FE
                      ^, found ' '  (at char 2199), (line:180, col:18)
```

**关键词：`REFERENCE_ELEMENT`；行号：180；列：18。**

### 3.3 关键字隔离探针（合成、内存内，不写文件、不计算）

用最小合法 TDB 作基线（可通过），逐条加入 MatCalc 专用命令，**每一条都单独失败**：

| 命令 | 结果 |
| --- | --- |
| 基线（无扩展） | passed |
| `REFERENCE_ELEMENT FE !` | failed — ParseException（line 7, col 18） |
| `ADD_COMPOSITION_SET BCC_A2 :FE:C: !` | failed — ParseException（line 7, col 19） |
| `ATTACH_CONTRIBUTION BCC_B2 BCC_A2 ORDER_DISORDER !` | failed — ParseException（line 7, col 19） |
| `CREATE_NEW_PHASE BCC_B2 3 0.5 0.5 3 !` | failed — ParseException（line 7, col 16） |
| `PARAMETER HMVA(BCC_A2,FE:C;0) … !` | failed — ParseException（line 7, col 14） |

即：**不是"第一个关键字挡路，后面的能过"，而是整套 MatCalc 扩展都不在 pycalphad 0.11.2 的 TDB 文法内。**

## 4. 第二道门禁：**无法评估**

第二道门禁要求先得到一个可解析的 `Database` 对象；第一道门禁没有产出对象，因此**未评估**，也没有为了绕过它而生成任何派生物。它本应核对：

元素列表 · 相列表 · 有序/无序相（`ATTACH_CONTRIBUTION … ORDER_DISORDER` 是否被 pycalphad 识别为 ordered/disordered 关系）· 碳化物/氮化物/碳氮化物（MatCalc 用 `ADD_COMPOSITION_SET` 把 MC 碳氮化物表示为 `fcc_A1#01` 成分集）· 温度限制 · 成分限制 · 相分数合计与收敛。

结构上已经可以确定的风险（来自只读 inspection，非推测替代）：

- pycalphad 的相选项白名单只有 `ionic_liquid_2SL / symmetry_FCC_4SL / symmetry_BCC_4SL / liquid / gas / aqueous / charged_phase`，有序关系只由 `TYPE_DEFINITION … DIS_PART` 建立；MatCalc 走的是另一套机制。
- 即使把 3 个扩展命令删掉（**本轮明令禁止、也未做**），MC 碳氮化物作为成分集的建模也会丢失 —— 那不是"兼容性修复"，而是**改变物理模型**。

## 5. 受控元素排除政策（与门禁无关，已建立）

- 政策：[`config/calphad_exclusion_policy_v1.0.json`](../config/calphad_exclusion_policy_v1.0.json)（版本化、逐条枚举、**无通配符、无通用忽略开关**）
- 模板：[`config/calphad_exclusions.example.json`](../config/calphad_exclusions.example.json)
- 批准范围：R-DQ 的 As/Sn/Sb（`database_not_covered`）、B-DQ 的 As/Sn/Sb（`measured_zero`）、两炉 O/W（`input_unknown`）——共 10 个 (样品, 元素) 组合
- 政策与**具体数据库身份绑定**（`database_scope.database_id = MATCALC-MC-FE-V2062`）；换库即失效，需重新决策
- 其他任何未覆盖的非零元素仍然 `CALPHAD-COMP-002` 阻断；每次运行必须由具名确认人确认，并把排除清单、原始值/缺失状态、类别、原因、数据库版本与 SHA-256 写进结果记录
- **公开仓库中的政策文件不含任何实测成分数值**；含实测值的逐次运行记录只写入 Git 忽略的 `outputs/`

## 6. 结果限制（已嵌入每个导出）

所有页面、Markdown、JSON、CSV 都携带：

> 本结果是基于 pycalphad 0.11.2 与 mc_fe v2.062 的缩减成分体系平衡热力学预测。R-DQ 中 As、Sn、Sb 未被数据库建模；O、W 因缺少测量值未进入计算。结果不能用于判断这些元素对偏聚、夹杂、晶界脆化、相稳定性或性能的影响。

同时保留 `model_prediction_not_experimental_measurement`、`reduced_component_system`、`excluded_elements`、`pending_human_review`、`is_complete_phase_diagram=false`、`writes_back_formal_experimental_data=false`。CSV 在前导注释行**和每一数据行**都写入限制文本。

## 7. 验证顺序执行情况

| # | 步骤 | 状态 |
| --- | --- | --- |
| 1 | 原始 TDB 解析测试 | **已执行 → 失败**（第 3 节） |
| 2 | 数据库自带公开验证体系复现 | 未执行（无可解析数据库；且 mc_fe 未公布验证体系） |
| 3 | 单温度平衡测试 | 未执行 |
| 4 | 多温度相分数扫描 | 未执行 |
| 5 | 相分数合计/点数/相名/收敛验证 | 未执行 |
| 6 | B-DQ 完整覆盖体系试算 | 未执行 |
| 7 | R-DQ 受控排除后缩减体系试算 | 未执行 |
| 8 | 重复运行一致性 | 未执行 |
| 9 | Streamlit 页面与下载文件验证 | **已执行 → 通过**（`tests/test_streamlit_pages.py` 5 passed；含阻断分支渲染） |

单元/契约测试：`tests/test_t86_calphad_adapter.py` **55 passed**（含门禁记录、政策枚举与绑定、受控排除、通知嵌入 MD/JSON/CSV、锁文件哈希）。

**因此 T86 状态保持 `Blocked`，不标记为 `pilot_ready_pending_scientific_review`。**

## 8. 需要项目负责人决定的事项

1. **是否允许受控预处理**：若要继续用 mc_fe v2.062，唯一的技术路径是生成一个**有记录、可复现的派生数据库**（去掉/改写 3 类 MatCalc 扩展命令）。这需要你明确批准，因为：①它**会改变物理模型**（MC 碳氮化物成分集与 B2 有序关系都会按 pycalphad 的理解重建）；②ODbL §4.4/§4.6 要求派生数据库同样以 ODbL 公开，并在公开使用派生数据库或其成果时提供派生库或"改动清单/算法"。**在本轮我未做任何预处理。**
2. **是否改用 pycalphad 原生的开源钢库**（例如 MIT 许可、为 pycalphad 编写的 LibreCalphad `mf-steel.tdb`）作为技术路径，把 mc_fe 留作对照；但按第一阶段审查，它同样缺 As/Sn/Sb 的评估参数，且作者明确不作准确性担保。
3. **是否向 TU Wien/MatCalc 询问**是否存在官方 pycalphad 兼容版本（pycalphad 仓库里的 `mc_fe_v2.059.pycalphad.tdb` 是第三方派生、版本更旧，本轮未使用）。
4. **若上述都不选**：把 T86 冻结为"技术框架 + 门禁记录"，不再推进真实计算。

## 9. 阶段 3 的后续结论（2026-09-25）

第 8 节第 1 项已被项目负责人以"**采用已有社区兼容版审查路线、不自行预处理原件**"回答，第 2–4 项随之不再适用。阶段 3 的结论：

- 社区派生候选可通过解析，差异审计 `passed_syntax_repairs_only`（**0 条未解释差异**），上游 5 个二元体系 **15/15** 检查复现、项目相关 **18/18** 检查通过。
- 但本环境 `pycalphad 0.11.2` 对**组元列表长度 ≥14** 的体系无法求解（实测上界 13；在 pycalphad 自带数据库 `COST507` 上复现同一边界），而两个炉次都需 16 个组元条目 → **真实炉次仍无结果，T86 保持 `Blocked`**。
- 因此第 8 节第 4 项（冻结为技术框架）在本轮实际上被采纳；是否缩减成分体系或修复隔离环境仍需具名决定。详见 [T86 第三阶段](T86_PHASE3_COMMUNITY_COMPATIBILITY.md)。
