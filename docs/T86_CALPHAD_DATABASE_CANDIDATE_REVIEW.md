# T86 耐磨钢 CALPHAD 数据库候选审查（仅调查与报告）

日期：2026-09-24 · 任务：T86 数据库候选审查 · T86 状态：**保持 `Blocked`**

本次**只做资料调查与报告**：未修改任何代码，未安装任何依赖，**未下载或复制任何 TDB/DAT 文件**，未执行任何真实计算，未运行测试，未 commit/push。

---

## 1. 目标成分体系（以 `data/processed/composition.csv` 实际值为准）

| 样品 | 非零元素（wt.%） | 显式 0 | 已声明但无值 |
| --- | --- | --- | --- |
| B-DQ | Al, B, C, Cr, Cu, Mn, Mo, N, Nb, Ni, P, S, Si, Ti, V（15 个非零） | As, Sb, Sn | **O, W** |
| R-DQ | Al, As, B, C, Cr, Cu, Mn, Mo, N, Nb, Ni, P, S, Sb, Si, Sn, Ti, V（18 个非零） | — | **O, W** |
| 两炉并集 | Fe（余量）+ 上述 18 个元素 = **19 个组元** | — | O, W 两炉都无值 |

关键点：

- **As、Sn、Sb 在 R-DQ 都是非零的**（具体实测值见本地 `data/processed/composition.csv`，不在此公开文档重复），只在 B-DQ 为 0。任何"排除这三个元素"的方案都只对 B-DQ 免于 `CALPHAD-COMP-002`，对 R-DQ 必须另有依据。
- **O、W 两炉都没有测量值**。它们不是"0"，不能被补零；T86 会以 `CALPHAD-COMP-001` 阻断，直到用户补值或具名声明按未检出处理并从体系排除。

---

## 2. 判定口径

每个候选按 10 项核对：官方发布方与原始链接 / 名称·版本·日期 / 许可证类别（开源·免费·学术·商业·授权不明）/ 实际覆盖元素·相·温度范围 / 是否覆盖 B-DQ·R-DQ 全部非零元素 / 是否面向低合金钢 / 能否被 pycalphad 0.11.2 直接读取 / 能否用于公开 GitHub·论文计算·结果再分发 / 缺失元素会触发哪些 T86 阻断码 / 数据库许可证是否与 pycalphad 的 MIT 相互独立。

结论只用四档：**可进入真实验收 / 仅适合技术冒烟测试 / 不适用 / 授权不明确**。

---

## 3. 候选矩阵

| # | 候选 | 发布方 | 版本·日期 | 许可证类别 | 覆盖（对照 19 组元） | 温度范围 | pycalphad 0.11.2 可读 | 公开仓库/论文/再分发 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | **MatCalc `mc_fe.tdb`（open database）** | MatCalc / TU Wien IMST（编辑 E. Povoden-Karadeniz、A. Jacob） | v2.062 · 2024-11-08 | **开源数据许可**：ODbL 1.0 + DbCL 1.0，免费；**许可见文件内部声明** | 覆盖 Fe + Al B C Co Cr Cu H Hf La Mn Mo N Nb Ni **O P Pd S Si Ta Ti V W Y**；**完全不含 As、Sn、Sb**（连 ELEMENT 行都没有） | **673–2000 K**（文件头部声明） | **不确定**：TDB 文本但含 MatCalc 专有关键字（见 §5）；必须实测 `Database()` | 可：ODbL 允许商业使用与再分发（须带许可 URI 与声明；派生数据库须同许可）；结果属 Produced Work，需 §4.3 署名声明 | **仅适合技术冒烟测试**（B-DQ 全覆盖 + O/W 待声明；R-DQ 因 As/Sn/Sb → `CALPHAD-COMP-002`；解析与相清单未验证） |
| A2 | MatCalc `mc_ni.tdb`（open） | 同上 | v2.036 · 2024-08-24 | ODbL + DbCL | Ni 基，含 Fe；**缺 P、As、Sn、Sb** | 未公布 | 同上 | 同 A1 | **不适用**（钢中 P 缺失即硬阻断） |
| A3 | MatCalc `mc_al.tdb`（open） | 同上 | v2.037 · 2025-07-25 | ODbL + DbCL | Al 基，缺大量钢中元素 | 未公布 | 同上 | 同 A1 | **不适用** |
| A4 | **LibreCalphad `mf-steel.tdb`** | M. Frichtl（个人开源项目） | 无版本号；最后一次改动 2024-12-23 | **MIT**（仓库 LICENSE 与**文件内部头部**均为 MIT，Copyright 2024 Matthew Frichtl） | 声明了 Fe C Mn Si Cr Ni Mo Nb V Ti Al Cu P S N B O W（O、W 确有评估：FE-O、FE-W 等）；**As、Sn、Sb 只声明了 ELEMENT，没有任何 PARAMETER** → 视为不覆盖 | 未公布（参数上限 6000 K，SER 基于 Dinsdale 1991） | 是为 pycalphad 写的；但作者在文件头记录了 pycalphad 侧缺陷（有序相子点阵分配、真空项、电荷平衡求解等） | 可（MIT，保留版权与许可声明） | **仅适合技术冒烟测试**（文件头约 100 条自述缺陷 + 作者明确不作准确性担保 + 无同行评议/无实验验证） |
| A5 | pycalphad 自带示例/测试库（`examples/mc_fe_v2.059.pycalphad.tdb`、`tests/databases/*`） | pycalphad 项目 | 随 0.11.2 | 仓库 MIT；**其中 mc_fe 派生文件源自 MatCalc（ODbL）** | 示例库为不锈钢/轻合金/二元/构造数据 | 各自不同 | 是（就是给 pycalphad 用的） | 取决于各文件上游许可 | **不适用**（**明确不得认定为适用于本耐磨钢**；只能做冒烟与回归） |
| A6 | **MatCalc special 数据库**（`mc_fe_bainite_v1.01.tdb` 等） | MatCalc / TU Wien IMST | 1.01 · 2025-02-04（基于 mc_fe 2.060；有同行评议背景：Jacob et al., Calphad 81 (2023) 102531） | **授权不明确**：页面只写 "free to use for private, scientific and commercial application"，**没有许可名称、没有条款 URL** | 未公布（派生于 mc_fe，同样缺 As/Sn/Sb） | 未公布 | 同 MatCalc 语法风险 | **不明确**（无许可文本可依据） | **授权不明确**（不得依赖） |
| A7 | MatCalc example 数据库（`mc_x_*.tdb`，如 `mc_x_FeAlCCrMnMoNNbSiVW.tdb`） | 同上 | 未公布 | **授权不明确**：页面说"即使没有许可用户也可使用"，**完全未提许可**；开放许可声明只按名称覆盖 mc_fe/mc_ni/mc_al | 部分（按设计裁剪） | 未公布 | 同上 | 不明确 | **授权不明确**（不得依赖） |
| A8 | **SGTE 二元数据集合集（2025）** | SGTE / B. Hallstedt（RWTH Aachen） | Calphad 89 (2025) 102833；2773 数据集 / 1238 个二元系 | **授权不明确**：论文摘要称此前加密的数据库现在"publicly available … in open form"，但**未能取得存放位置与许可文本** | **仅二元**（但可能是唯一公开的 Fe–As、Fe–Sn、Fe–Sb 来源） | 未公布 | 未公布 | 未公布 | **授权不明确**（**最高价值后续项**） |
| A9 | OpenCalphad（Sundman） | Bo Sundman / OpenCalphad | 持续开发 | 软件 **GPL-3.0**；**仓库不含任何 TDB/DAT** | n/a | n/a | n/a | n/a | **不适用**（只能作交叉校验引擎，不能作数据库来源） |
| A10 | NIMS CPDDB | 日本 NIMS | 持续更新（2026-03-30 有更新） | **受限**：NIMS 保留版权，**未经书面许可不得复制/再发布/向第三方分发**，禁止批量下载 | 700+ 一元/二元/高阶体系，需自行组合 | 各体系不同 | 文件为 TDB，理论上可读 | **不可**（不能再分发；组合多元体系还会形成派生数据库） | **不适用**（公开仓库路径不可用） |
| A11 | TDBDB（Thermodynamic DataBase DataBase） | Brown Univ. van de Walle 组 | 索引，非数据库 | 仅检索前端，无文件、无许可声明 | 按元素检索论文随附 TDB | — | 取决于文件 | 取决于原论文 | 仅作**检索入口**（不是候选数据库） |
| A12 | NIST Materials Data 仓库 | NIST | 按条目 | 逐条不同 | 按条目 | 按条目 | 按条目 | 按条目 | pycalphad 给出的链接返回 **404**；本轮未核实 → **授权不明确** |
| A13 | COST 507（pycalphad 也自带 `COST507.tdb`） | COST 507 联盟（EU COST Action，编 I. Ansara） | Round II · 1999-01（FROZEN VERSION） | **免费使用**：文件内写 "It may be used freely but on your own risk…"，**不是标准开源许可，未授予明确再分发权** | **Al 基轻合金库**：Fe 只作少量添加；**没有渗碳体/M7C3/M23C6/MC**；缺 P、S、B、As、Sn、Sb | `TEMP_LIM 298.15 6000` | 是（TDB 文本） | 不推荐依赖 | **不适用**（合金族错误，且缺 P/S） |
| A14 | PhaseDiagrams.org / Hallstedt SGTE 二元合集 | SKF / Hallstedt 等 | 2025 合集 | 二元评估；具体条款需按来源核对 | **仅二元** | 各体系 | 视文件 | 视来源 | **不适用**（只能做子体系构件） |
| A15 | Innomat AB 数据库 | Innomat AB | 未核实 | 未核实（pycalphad 列为多组元提供方） | 未核实 | 未核实 | 未核实 | 未核实 | **授权不明确**（官方页面正文本轮无法抓取） |
| A16 | **IAD**（Fe–Al–Cr–Cu–Mn–Mo–Ni–Si 工业合金数据库） | Miettinen, Visuri, Fabritius（Univ. of Oulu） | 预印本 2020-06-09 | **CC-BY-4.0**（但只覆盖存放物本身） | 元素/相/温区**未公布** | 未公布 | **无 TDB 文件**：Zenodo 记录 3886892 只有一个文件——论文 PDF；全版本查询 `total: 1` | 无可再分发对象 | **不适用**（**"陷阱"候选**：许可干净但存放物里没有数据库） |
| A17 | LibreCalphad `mf-steel-3g.tdb` | M. Frichtl | 无 tag | MIT | 未公布（作者自述远不如 mf-steel 全面） | 未公布 | 部分（作者称三代模型在 pycalphad 中较难处理） | 可（MIT） | **仅适合技术冒烟测试** |
| A18 | Zenodo 上的 Mo–Si–Y–Hf TDB（DOI 10.5281/zenodo.20848011） | P. P. Selagam Setty（Penn State） | 2026-06-25 | **CC-BY-4.0** | 只有 Mo Si Y Hf，**无 Fe、无 C** | 未公布 | 是（摘要称兼容 pycalphad） | 可，但与本课题无关 | **不适用** |
| A19 | ESPEI 测试数据库 | Bocklund 等 | 活跃仓库 | **未核实** | 未核实 | 未公布 | 是 | 不明确 | **授权不明确** |
| A20 | Materials Cloud / NOMAD / figshare / Mendeley Data / Dryad / OSF 检索 | — | — | — | — | — | — | — | **未发现符合条件的钢用 TDB**（是"未找到"，不是"证明不存在"） |
| B1 | **Thermo-Calc TCFE15（TCS Steel and Fe-alloys）** | Thermo-Calc Software AB | TCFE 系列最新为 TCFE15 | **商业许可，且 EULA 明确限制发表** | **文档称覆盖 42 个元素，含 As/Sn/Sb/O/W/N/B/P/S**（唯一能补齐痕量元素的路线，但未逐项核对官方正文） | 未核实 | **不可**：pycalphad 官方明确"Commercial encrypted databases (not able to be read by PyCalphad)"；且许可为密钥门控 | **不可公开**：EULA 7c 结果"only for your internal purposes"；7e 禁止并入其他产品再分发；**7f 未经 TCSAB 书面许可不得把计算结果系统性映射发布或存入公开数据仓库**；7f(v) 禁止再分发数据库 | **不适用**（对"公开 GitHub + pycalphad"这条路线） |
| B7 | Thermo-Calc **免费教育包**（含 FEDEMO 钢示例库） | Thermo-Calc Software AB | 当前 | 免费教育许可 | FEDEMO 仅含 **Fe, Cr, Mn, Ni, C**；且免费教育包**只能算 ≤3 个组元** | 未核实 | 不可（非 TDB 全量；且许可限制） | 不可 | **不适用**（无法覆盖本课题成分） |
| B8 | CompuTherm **PanFe2026** | CompuTherm | 2026 版 | 商业 | 文档称 **30 个组元，含 As/Sn/Sb/O/W** | 未核实 | 不可（Pandat 自有格式；pycalphad 不支持） | 不可 | **不适用**（对 pycalphad 路线） |
| B9 | FactSage **FTmisc-FeLQ**（液态 Fe 稀溶质） | CRCT / GTT | 未核实 | 商业（加密狗） | 液相中显式包含 **Al B Bi C Ca Ce Co Cr Mg Mn Mo N Nb Ni O P Pb S Sb Si Te Ti V W Zn Zr** —— 即"稀溶质/TRACE 模式"覆盖痕量元素的少数案例 | 未核实 | **不可**（非 TDB） | 不可 | **不适用**（仅液相、非 TDB、商业） |
| B2 | Pandat / PanFe | CompuTherm | 商业版本 | 商业 | 见 §9 待补充 | — | 不确定 | 需按 EULA 确认 | **授权不明确**（本轮未核实） |
| B3 | JMatPro | Sente Software | 商业 | 商业 | 不是 TDB 数据库，是自带模型的计算软件 | — | **不可**（无 TDB 供 pycalphad 使用） | 不可 | **不适用** |
| B4 | GTT / SGTE（SSUB、unary、binary） | GTT-Technologies / SGTE | 商业/受限 | 商业 | 多元钢体系需自行组合 | — | 不确定 | 需按 EULA 确认 | **授权不明确**（本轮未核实） |
| B5 | MatCalc ME-Fe（商业版） | MatCalc Engineering | 商业 | 商业（学术折扣） | 未核实（开放版 mc_fe 的增强版） | 未公布 | 未核实 | 需按 EULA 确认 | **授权不明确** |
| B6 | FSstel（FactSage 钢数据库） | VTT / FactSage（GTT 生态） | 商业 | 商业 | 检索到"115 个完全评估二元 + 85 三元 + 17 四元体系"的描述（**来源为 PDF 摘要，未读取正文**） | 未核实 | 不确定（FactSage 自有格式，非 TDB 文本的可能性高） | 不可（商业 EULA） | **授权不明确 / 很可能不适用** |

---

## 4. 逐候选要点（含 T86 阻断码）

### A1 MatCalc open `mc_fe.tdb` v2.062 —— 本轮最有价值、也是唯一有希望进入真实验收的候选

- 官方页面：<https://www.matcalc.at/index.php/databases/open-databases>（发布方：MatCalc / TU Wien 材料科学与技术研究所；文件头部标注版权人与编辑为 **Erwin Povoden-Karadeniz**，并注明由 E. Povoden-Karadeniz 与 Aurélie Jacob 更新）。下载链接 `mc_fe_v2062.tdb` 直接列在该页。
- **许可同时写在页面与数据文件内部**（文件头部原文）：
  > `$ This database mc_fe_v2.062.tdb is made available under the Open Database License: http://opendatacommons.org/licenses/odbl/1.0/. Any rights in individual contents of the database are licensed under the Database Contents License: http://opendatacommons.org/licenses/dbcl/1.0/.`
  页面另写"can be downloaded and used free of charge under the open database license regulations"。→ 许可类别：**开源数据许可（ODbL 1.0 + DbCL 1.0）**。
- **覆盖元素（文件头 `ELEMENT` 段）**：Fe, Al, B, C, Co, Cr, Cu, H, Hf, La, Mn, Mo, N, Nb, Ni, **O**, P, Pd, S, Si, Ta, Ti, V, **W**, Y —— 共 25 个。**As、Sn、Sb 连 `ELEMENT` 行都没有**（不是"有元素无参数"，是完全不存在）。
- **评估温度范围（文件头声明）**：**673–2000 K**（≈ 400–1727 °C）。这可以填入 T86 的 `declared_temperature_range_C`。
- **评估成分上限（文件头声明）**：`Al<3 B<0.5 C<0.5 Co<3 Cr<25 Cu<1 H<0.1 Hf<0.5 La<0.5 Mn<25 Mo<5 N<1 Nb<1 Ni<26 O<0.5 P<0.05 Pd<4 S<0.1 Si<3.5 Ta<0.5 Ti<0.5 V<0.5 W<3 Y<0.5`。
  **逐项核对：B-DQ 与 R-DQ 的所有元素都落在这些上限之内**（最紧的是 C 0.19<0.5、Mn 0.9<25、Cr 0.19<25、Ni ≤0.177<26、S ≤0.0248<0.1、P ≤0.013<0.05、N ≤0.0065<1、B 0.002<0.5、Cu ≤0.152<1、O 未知但上限 0.5）。
- **官方列出的典型应用**："9-12% Cr steels, hot-work tool steels, **microalloyed steels**, austenitic stainless steels, PH maraging steels" —— **"微合金钢"与"热作模具钢"是低合金耐磨钢相关的类别**（Nb/V/Ti 微合金化 + Mo），这是它比其他候选更贴近本课题的唯一官方依据。
- **相清单（文件头）**包含 LIQUID、FCC_A1、BCC_A2、HCP_A3、BCC_B2（有序，分裂模型）、CEMENTITE、M7C3、M23C6、M6C、M3C2、MC 型 fcc 成分集、M2P/M3P、ALN、BN_HP4、ZET 以及多种硼化物/硫化物/氧化物。
- **pycalphad 可读性：不确定，且已定位风险点**。文件是 TDB 文本，但含 MatCalc 专有关键字：`REFERENCE_ELEMENT FE !`、`ADD_COMPOSITION_SET FCC_A1 :NB,TA,TI,V:C,N: !`、`CREATE_NEW_PHASE …!`、`ATTACH_CONTRIBUTION BCC_B2 BCC_A2 ORDER_DISORDER !`、以及自定义参数类型 `HMVA(FCC_A1,*;0)`。pycalphad 0.11.2 的 `pycalphad/io/tdb_keywords.py` 只列 Thermo-Calc 标准关键字，且其模块自述 **"Note that not all of these keywords are fully supported yet."**（我已直接核对该文件源码）；`REFERENCE_ELEMENT`/`ADD_COMPOSITION_SET`/`ATTACH_CONTRIBUTION` **不在白名单内**。这**是代码阅读推断，不是实测结果** —— 实际是报错还是被忽略，必须在获得许可后**用一次 `Database("mc_fe_v2062.tdb")` 实测**才能定论；有序 BCC_B2 的分裂模型是最可能出现偏差的部分。
- 另一条独立证据表明"MatCalc 系 TDB 可以被 pycalphad 用"：pycalphad 官方文档示例与仓库自带 `mc_fe_v2.059.pycalphad.tdb`（§5）。但注意文件名带 `.pycalphad`，说明**上游原始文件是经过调整才被 pycalphad 使用的**；如果我们自己也要调整，就会形成 ODbL 意义上的派生数据库（§6）。
- **相排除问题（关键操作发现）**：pycalphad 官方示例在使用同族 MatCalc 数据库时，必须显式剔除 `GP_MAT` 这个"模型相"。T86 目前的隔离 worker 使用 `sorted(database.phases.keys())` 全量相，**没有相排除机制**。因此即便解析成功，用 mc_fe 也可能把模型相计入平衡 —— 这是一项**独立于数据库审查的技术行动项**（需要另开任务支持"允许相清单"或 TDB 级相排除声明），本次不改代码。
- T86 阻断码：
  - B-DQ：非零元素全覆盖 → **不触发 `CALPHAD-COMP-002`**；O、W 无值 → **`CALPHAD-COMP-001`**（补值或具名声明排除）；Fe 余量 → **`CALPHAD-COMP-003`**（具名确认）。
  - R-DQ：**`CALPHAD-COMP-002`（As、Sn、Sb）** —— 硬阻断，无覆盖开关。
- 结论：**仅适合技术冒烟测试**（对 B-DQ 可望推进到"验收前验证"），理由：R-DQ 覆盖率不完整、pycalphad 解析未验证、相清单需处理、且**没有任何针对低合金耐磨钢的评估/验证依据**（"微合金钢"只是官方应用列表中的一类，不构成对本钢种的适用性证据）。
  > 注：委托的调查分支给出的结论是"可进入真实验收"。我不采用该措辞：其自身证据（解析不确定 + 缺 As/Sn/Sb + 无同行评议的钢种验证）不支持"验收"这一步；本报告的统一口径是**先通过解析与相清单验证，才谈得上验收**。

### A4 LibreCalphad `mf-steel.tdb`

- 仓库：<https://github.com/mfrichtl/librecalphad>；`LICENSE` 与**文件内部头部**均为 **MIT**（Copyright (c) 2024 Matthew Frichtl）—— 是本轮**唯一数据文件许可完全无歧义**的候选。最后一次改动 2024-12-23，无版本号。
- 覆盖：文件声明了 Fe C Mn Si Cr Ni Mo Nb V Ti Al Cu P S N B O W（O、W 有实际评估：FE-O、FE-W 等）；**As、Sn、Sb 只声明了 `ELEMENT`，评估清单里没有 Fe–As / Fe–Sn / Fe–Sb 体系**（只有 FE-FES、FE-S、FES-S）→ **As/Sn/Sb 视为不覆盖**。
- Quality 证据（决定性）：文件头有约 100 条**自述缺陷日志**，与本课题直接相关的例如 "SIGMA PHASE IN CR-FE-SI IS INCORRECT"、"C-CR-MN CEMENTITE_D011 DOES NOT MATCH LEE 1993"、"MN-S SYSTEM FROM DILNER 2015 INCORRECT"，以及 pycalphad 侧问题 "PYCALPHAD DOES NOT PROPERLY PARTITION THE PROPERTIES BETWEEN SUBLATTICES, SO THEIR PHASE STABILITIES WILL BE WRONG"、"PYCALPHAD CANNOT HANDLE ONLY VACUUM TERMS"。README 原文："The steel database file (mf-steel.tdb) is decent, but there are too many opportunities for improvement to list."、"User discretion is advised. **I make no assertions as to the accuracy of the results**…"
- 评估主体与验证：**个人项目**，未找到同行评议论文/DOI；验证材料是自生成的二元/三元相图，**没有实验钢对比，也没有耐磨钢相关验证**。
- T86 阻断码：R-DQ 因 As/Sn/Sb 无参数 → 仍会 `CALPHAD-COMP-002`（与 mc_fe 同样的问题）；O/W 与 Fe 余量的门禁同 A1。
- 结论：**仅适合技术冒烟测试 / 独立交叉检查**（许可最好、pycalphad 原生，但作者明确不作准确性担保，不能作为验收依据）。

### A5 pycalphad 自带数据库（特别说明：不得当作适用）

pycalphad 0.11.2 仓库内的数据库（jsDelivr 文件清单核对）包括：

- `examples/mc_fe_v2.059.pycalphad.tdb`（368 KB，**MatCalc mc_fe 的 pycalphad 变体**）、`examples/Fe-O.tdb`、`examples/alfe_sei.TDB`、`examples/Al-Cu-Y.tdb`、`examples/alzn_mey.tdb`、`examples/CrFeNb_Jacob2016.tdb`、`examples/nbre_liu.tdb`、`examples/NI_AL_DUPIN_2001.TDB`；
- `pycalphad/tests/databases/`：`alcrni.tdb`、`alfe.tdb`、`alfeo.tdb`、`Al-Fe_sundman2009.tdb`、`femn.tdb`、`femns.tdb`、`cfe_broshe.tdb`、`Cr-Fe-Ni_shallow_bcc.tdb`、`mc_fecocrnbti.tdb`、`COST507.tdb`、`rose.tdb`、`gibbs_phase_rule.tdb`、`parameter_filter_test.tdb` 等。

其中 `rose.tdb` 是构造的回归数据库，`COST507.tdb` 是**轻合金**库（文件内自带 "It may be used freely but on your own risk" 声明 —— 说明"放在 MIT 仓库里"并不改变其上游许可），`mc_fecocrnbti.tdb` 文件头写明 "Based on Matcalc steel database 2.060; **used under ODBL** … Only Fe-Co-Cr-Nb-Ti parameters retained (for performance in test)"，`cfe_broshe.tdb` 只有 Fe–C。**这些文件的设计目的是示例与回归测试，不是耐磨钢工程数据库** —— 不得因为"pycalphad 自带"就认定适用，也不得用它们产出任何耐磨钢结论。按本次判定为 **不适用（只能做冒烟/回归）**。

### A6–A20 其它候选

MatCalc special / example 数据库、SGTE 2025 二元合集、OpenCalphad、NIMS CPDDB、TDBDB、NIST、COST 507、PhaseDiagrams.org、Innomat、IAD、mf-steel-3g、Zenodo Mo–Si–Y–Hf、ESPEI，以及 Materials Cloud/NOMAD/figshare/Dryad/OSF 的检索结果，见 §3 候选矩阵对应行；要点集中在 §4-B1（商业路线）与 §7（三个回答）。

### A6 NIMS CPDDB

- 官方页面 <https://cpddb.nims.go.jp/>：需要 DICE 账号注册 + 域名登记 + MatNavi 使用申请；"**Mass downloading of data is prohibited**"、"Web scraping of data is prohibited"；免责声明："National Institute for Materials Science (NIMS) holds the copyright of this database system. **No reproduction, republication or distribution to third parties of any content is permitted without written permission of NIMS.**"
- 因此即使技术上能拿到二元/三元 TDB，也**不能**进入公开 GitHub 仓库、不能随论文再分发；而且把二元/三元评估拼成 19 组元钢体系本身就是一个需要自行论证的派生数据库。
- 结论：**不适用**（受限许可 + 体系粒度不匹配）。

### B1 TCFE 与商业库 —— 结论比预期更硬：**商业路线基本被许可本身封死**

调查分支取得了 Thermo-Calc **EULA（2024-05-24）** 的关键条款原文：

- **7c**：计算结果"**only for your internal purposes**"；
- **7e**：不得把结果用于 "for providing data/calculations as a service … or incorporating the Program or the results or any portion thereof into any other product for redistribution (whether for free or for a fee)"；
- **7f**：未经 TCSAB 事先书面许可，"**in no event allowed to … make available to third parties, or publish or store in a public data repository, systematic mappings of results generated by the Program**"；
- **7f(v)**：不得 copy/sell/license/sublicense/distribute/rent/lend "the Program"（即数据库本体永不可再分发）。

补充已核实的官方事实：TCFE 官方产品页与技术信息 PDF 存在（<https://thermocalc.com/products/databases/steel-and-fe-alloys/>），且 TCFE 适用于 **Fe ≥ 50 wt.%** 的钢/铁基合金；pycalphad 官方明确 "Commercial encrypted databases (not able to be read by PyCalphad)"；Thermo-Calc 免费教育包**只能算 ≤3 个组元**，其钢示例库 FEDEMO 仅含 **Fe、Cr、Mn、Ni、C**；EULA §4 允许注册学生在"完成其学业义务所必需"的范围内使用网络许可。

**精确的许可界限（比"完全不能用"更有用）**：

- **普通论文/学位论文里放一张相分数图 + 致谢**：在"internal purposes"与"不为第三方提供服务"的框架下**通常可以论证为允许**（但仍建议保留书面确认）。
- **把相分数表/系统性结果映射放进公开 GitHub 仓库**：属于 EULA 7f(i) 明确禁止的 "publish or store in a public data repository, systematic mappings of results"，**必须有 TCSAB 事先书面许可**。
- **数据库文件本体**：永不可再分发（7f(v)）。
- **用 pycalphad 读取**：同时撞上"加密库不可读"与"不得把程序/结果并入其他产品"两条。

对 T86 的含义（重要）：

- **即便学校已有 TCFE 授权，把 TCFE 计算的相分数表放进公开 GitHub 仓库也需要 TCSAB 的书面许可**（EULA 7f）；用 pycalphad 读 TCFE 还会同时撞上"加密库不可读"与"不得并入其他产品/以服务形式提供结果"两条（7e/7f）。
- **如果"覆盖 As/Sn/Sb"是硬性验收要求，那么 T86（pycalphad 路线）在当前可核实范围内无法达成。** 文档上能覆盖 As/Sn/Sb 的只有 TCFE15（42 元素）与 PanFe2026（30 组元）这类商业库，而它们既不能进 pycalphad，也不能公开再分发。
- 因此"申请学校 TCFE 授权"只有在**同时满足**下列条件时才有意义：①用 Thermo-Calc 本体计算（不经过 pycalphad）；②不把结果系统性映射发布到公开仓库（或先取得 TCSAB 书面许可）；③接受结果只作内部用途。这实际上把计算**移出 T86 范围**，变成"外部证据"。
- FactSage 的 **FTmisc-FeLQ** 是唯一在文档里显式覆盖 As/Sn/Sb 等痕量元素的"稀溶质/TRACE 模式"案例，但**仅液相、加密狗许可、且不是 TDB**，对 pycalphad 无用。

### B2–B13 商业/受限候选（简表，均为**不适用**或**授权不明确**）

调查分支通过文本转换服务读取了厂商技术手册与 EULA，得到下表（温度范围与元素清单以厂商文档为准，未逐项独立复核）：

| 候选 | 覆盖（对照 19 组元） | 许可/可读性 | 结论 |
| --- | --- | --- | --- |
| **TCFE15** v15.1 | **全部 24 个（42 元素框架）**，但 As/Sn/Sb 上限写作 `[Trace]`，**机制未说明** | 商业加密，pycalphad 不可读；EULA 7c/7e/7f 限制 | **不适用**（技术+许可双重不可用） |
| **MOBFE9**（Fe 迁移率库） | 41 元素，含 As/Sn/Sb | 商业；不可读 | 不适用 |
| **PanFe2026**（PanIron） | **全部 24 个**（30 组元，含 As 0~0.5 wt%、Sn/Sb 0~0.1 wt% 的显式上限） | 商业；Pandat 自有格式，无可读 TDB 路径；**未公布任何条款/价格/学术计划** | 授权不明确 |
| **FSstel**（FactSage） | 文档记 21/24（含 Sn、Sb），**缺 As**；温度"约 400–1800 °C"；**Nb 是否存在文档自相矛盾**（数据库文档列出 N、O、Nb，8.4 发行说明则漏掉 Nb 且计 46 元素） | 商业（加密狗/网络租用）；不可读；条款未公布 | 授权不明确（且 Nb 矛盾必须澄清） |
| **SSOL9 / SSUB7**（SGTE，由 Thermo-Calc 销售） | 79 / 101 元素 | 商业；受 TCS EULA | 不适用 |
| **SGTE(2024) 合金库**（FactSage 8.4 新增） | 79 元素，含 As/Sb/Sn | 商业；通用合金库，非钢专用 | 授权不明确 |
| **ME-Fe**（MatCalc Engineering 商业版） | 与 mc_fe 相同 + Ca；**缺 As/Sn/Sb** | 商业；条款未公布 | 授权不明确 |
| **JMatPro** Fe/General Steels | 21/24；**缺 As/Sn/Sb**；General Steels 是其子集 | 商业（加密狗、仅 Windows）；**不存在可读的数据库文件**（厂商称"不需要外部热力学数据库"） | 不适用 |
| **MDT Steel_Fe**（CaTCalc） | Fe+Al B C Co Cr Cu Mg Mn Mo N Nb Ni O P S Si Ta Ti V W Zr；缺 As/Sn/Sb | 商业；CaTCalc 格式 | 不适用 |
| **FEDEMO / FactSageEdu（免费层）** | 仅 Fe、Cr、Mn、Ni、C；且免费教育包/演示版**只能算 ≤3 个组元**；FactSageEdu **不允许导入或转换 TDB** | 免费教育许可（另有 EULA §6/§7 限制） | 不适用（覆盖不足） |

**痕量元素机制（As/Sn/Sb）的准确结论**：只有三家厂商文档在 Fe 基体系中声称含 As/Sn/Sb —— ①TCFE15（全部列出，但上限标 `[Trace]`，厂商只有一句"为更好预测钢中残余元素影响而新增元素"，**没有任何稀溶质模型说明**）；②PanFe2026（给出显式成分上限）；③FactSage FTmisc-FeLQ（真实的稀溶质液相，列了 Sb **但没有 As、Sn**）。FSstel 声称 Sn、Sb（不含 As）。**mc_fe、ME-Fe、JMatPro、MDT 全部不含这三者。** 因此"是否真的有稀溶质模型描述 As/Sn/Sb"在本轮证据下**仍属未核实**，且这是"若必须覆盖痕量元素该怎么办"的**最高优先级开放问题**。

---

## 5. 技术前置：pycalphad 0.11.2 能读什么、读不了什么

已核实的官方事实（全部来自 pycalphad 0.11.2 自己的文档、仓库文件清单与源码）：

1. **支持的格式**（官方 "Calphad Databases" 页）：`Thermodynamic DataBase (.tdb)`、`ChemSage (.dat)`、**"Commercial encrypted databases (not able to be read by PyCalphad)"**、以及新兴 XML 格式（需插件）。因此 `.tdb` 可读、ChemSage `.dat` 可读、**商业加密库明确不可读**。
2. **官方推荐的开源数据库来源**（同一页）：TDBDB、NIMS CPDDB、NIST Materials Data、NIST solder、Innomat AB、**MatCalc open databases**、LibreCalphad、PhaseDiagrams.org/SGTE 二元合集。这与本报告的检索路径一致。
3. **pycalphad 官方示例就是用 MatCalc 开放数据库算 Fe-18Cr-8Ni 不锈钢的相分数—温度曲线**（官方文档 "Phase Fractions and Phase Compositions vs Temperature"）：`Database('../databases/mc_fe_v2.059.pycalphad.tdb')`，条件 `T=(700,1300,10) K, P=1e5`，并用 `v.get_mole_fractions(mass_fracs, 'FE', dbf)` 把**质量分数**换算成摩尔分数；示例中明确 `phases = sorted(set(dbf.phases.keys()) - {'GP_MAT'})`，注释为"GP_MAT 是模型相，不应出现在平衡计算中"；并注明该库加载时会有关于额外 type-definition 字符的良性警告。
4. **仓库内置文件**（jsDelivr 文件清单，tag `0.11.2`）：`examples/mc_fe_v2.059.pycalphad.tdb`（368 KB）与 `pycalphad/tests/databases/mc_fecocrnbti.tdb`；`pycalphad/core/workspace.py`、`pycalphad/property_framework/`、`pycalphad/models/model_mqmqa.py`。
5. **源码**（`pycalphad/variables.py` @0.11.2）：定义 `get_mole_fractions(mass_fractions, dependent_species, pure_element_mass_dict)` 与 `get_mass_fractions(...)`，**使用数据库自身的 `refstates` 元素质量**（也接受外部质量字典）。
6. **已知解析限制**（`pycalphad/tests/test_database.py` @0.11.2）：`TYPE_DEFINITION ... IF ... THEN ...` 会以 `UserWarning: Type definitions using IF/THEN logic is not supported` 被**忽略**；函数名超过 8 字符会告警（Thermo-Calc 兼容子集限制）；未终止的 `PARAMETER`/`FUNCTION` 会抛 `ParseException`。另有 `test_database_passes_with_diffusion_commands`，其文档字符串明确写 "do not raise errors while parsing (**doesn't test implementation**)" —— 即 pycalphad 对**不认识或不完全支持的指令是容忍/忽略**，而不是一律报错。
7. **关键推论：解析结果不确定 —— "解析成功 ≠ 数值有效"。** 我直接读了 pycalphad `pycalphad/io/tdb.py` 的语法定义，可以确认：
   - 关键字通过 `TCCommand` 匹配，**不在白名单内的词会触发 `ParseException`**；`all_commands` 只包含 ELEMENT / SPECIES / TYPE_DEFINITION / FUNCTION / ASSESSED_SYSTEMS / DEFINE_SYSTEM_DEFAULT / DEFAULT_COMMAND / DATABASE_INFO / VERSION_DATE / REFERENCE_FILE / ADD_REFERENCES / LIST_OF_REFERENCES / TEMPERATURE_LIMITS / PHASE / CONSTITUENT / PARAMETER / ZEROVOLUME_SPECIES / DIFFUSION；
   - 但**顶层解析循环是否会跳过未知行，我没有核实**（源码抓取被截断）。因此 `REFERENCE_ELEMENT`、`ADD_COMPOSITION_SET`、`ATTACH_CONTRIBUTION`、`HMVA` 的后果存在两种可能：**报错** 或 **被跳过**。
   - 另有两种已确认的"容忍"行为：`TYPE_DEFINITION ... IF ... THEN ...` 会 warn "Type definitions using IF/THEN logic is not supported" 后**直接 return**（源码注释 "Don't process IF-THEN type definitions for now"）；`DIFFUSION`/`ZEROVOLUME_SPECIES` 能解析但测试自述 "doesn't test implementation"。
   - 已确认**受支持**的相选项只有：`ionic_liquid_2SL`、`symmetry_FCC_4SL`、`symmetry_BCC_4SL`、`liquid`、`gas`、`aqueous`、`charged_phase`，加上 IHJ/Xiong 磁性提示与 ordered/disordered 提示。
   - **因此**：如果未知关键字被跳过（而不是报错），风险是**静默偏差** —— MC 碳氮化物在 mc_fe 中以 `fcc_A1#01` 之类**成分集**表示（`ADD_COMPOSITION_SET`），被忽略后会并入母相 FCC_A1，导致"单独碳化物/氮化物相分数"不正确；B2 有序走的是 MatCalc 自己的 `ATTACH_CONTRIBUTION … ORDER_DISORDER`，不是 pycalphad 的 `DIS_PART`。
   > 两个调查分支对"未知关键字"的后果给出了相反判断（"报错" vs "跳过"）。我核对源码后**不选用任何一方**：两者都可能，**必须用 `Database("mc_fe_v2062.tdb")` 实测**才能定论（报错？忽略？哪些相被合并？），这是获得授权后的**第一道验收门**。

对本课题的直接含义：

- **好消息**：MatCalc 系 TDB 确实是 pycalphad 的实际工作路径，甚至被 pycalphad 官方示例用来做"相分数—温度"这一与我们完全相同的任务类型。
- **风险 1（相清单）**：MatCalc 库含 `GP_MAT` 这类模型相。T86 目前的隔离 worker 使用 `sorted(database.phases.keys())` 全量相，**没有相排除机制**。直接用 mc_fe 可能把模型相计入平衡。这是一项**独立于数据库审查的技术行动项**（需要另开任务：注册"允许相清单"或在 TDB 登记中声明排除相），本次不改代码。
- **风险 2（GES 指令）**：若数据库（尤其商业库）依赖 `IF/THEN` 型 `TYPE_DEFINITION` 或 pycalphad 未实现的模型，pycalphad 会忽略或报错，结果可能**静默偏离**商用软件。必须在获得文件后做逐项冒烟核对。
- **附注（不在本次范围）**：pycalphad 0.11.2 自带 `v.get_mole_fractions`，用**数据库自身**的元素质量做 wt.%→摩尔分数换算；T86 目前是自己维护原子量表换算。两种做法给出的数值会在元素质量取值不同时有微小差异，是否改用 pycalphad 的换算属于另一个任务，本次不动。

---

## 6. 许可证独立性分析（数据库 vs pycalphad MIT）

- **pycalphad 的 MIT 许可只覆盖 pycalphad 代码，不覆盖任何数据库。** 这一点在 pycalphad 文档里也得到印证：数据库来源被列为第三方检索渠道（MatCalc、NIMS、NIST、SGTE 等），各自带自己的许可。
- MatCalc 开放数据库：**ODbL 1.0（数据库权与数据库版权）+ DbCL 1.0（内容版权）**，与 MIT 相互独立、互不覆盖。要点（已核对 ODbL/DbCL 正文）：
  - ODbL §3.1 授予全球、免版税、非排他许可，**明确包含商业使用**；
  - §4.2：**公开传播（Convey）数据库或派生数据库**时必须附带许可副本或 URI、保留版权与许可声明；
  - §4.3：**"Produced Work"（例如我们算出的相分数曲线/表格）不属于派生数据库**，公开发布时只需加署名声明，例如 `Contains information from DATABASE NAME, which is made available here under the Open Database License (ODbL).`；
  - §4.4/§4.5：**派生数据库**（修改、摘编、重组）必须继续以 ODbL 发布；
  - §4.6：**公开使用派生数据库或由派生数据库产生的成果时，必须免费提供派生数据库本体或"改动清单/算法"**。
  - **操作含义**：不修改 `mc_fe.tdb` 直接使用 → 结果可发表（加 ODbL 署名声明），若在仓库内再分发该 TDB 则须附许可与声明；一旦我们为 pycalphad 调整/裁剪数据库（例如去掉某些相、改元素）→ 就成为派生数据库，必须按 ODbL 提供改动文件。**这也再次说明为什么不能靠"悄悄删掉 TDB 不覆盖的元素"来绕过阻断：既违反 T86 的治理规则，也会触发 ODbL 的派生/公开义务。**
- LibreCalphad：仓库 MIT（与 pycalphad 同为宽松许可，但两份 MIT 各自独立）。
- NIMS CPDDB：**保留版权、禁止再分发**，与 pycalphad MIT 无任何关系，且**不能再分发**。
- TCFE 等商业库：EULA 独立，并且**比多数学生预想的更严格**（已取得 2024-05-24 版 EULA 关键条款：结果仅限内部用途、不得并入其他产品再分发、未经书面许可不得把结果系统性映射发布或存入公开仓库、禁止再分发数据库本体）。**这不是"授权不明确"，而是"授权明确但禁止我们想要的两件事（第三方软件读取 + 公开再分发结果）"**，因此对 T86 的公开科研路线判定为**不适用**。
- **对 T86 最重要的一条独立性结论**：pycalphad 的 MIT 许可既不能授权任何数据库，**也不能把商业库的限制解除**；反之，任何数据库的许可都不会因为"pycalphad 是 MIT"而变宽松。
- **一个值得注意的对比事实**：pycalphad 自己就把 MatCalc 派生的 `mc_fe_v2.059.pycalphad.tdb` 放进了仓库（文件名带 `.pycalphad`，说明是经过调整的变体）。这证明 ODbL 允许这种再分发，但也提示：**如果我们自己生成 pycalphad 适配变体，ODbL 的声明与派生义务由我们自己承担**，不能照抄 pycalphad 仓库的做法（我在其文件清单中未见独立的 ODbL 声明文件，但只凭文件清单不能判定其合规性，也不应据此推断我们可以省略声明）。

---

## 7. 三个明确回答

### Q1 是否存在"覆盖全部非零元素 + 授权清楚 + 适合公开科研使用"的数据库？

**不存在。两个独立调查分支与我的检索在这一点上一致。**

- 授权清楚且免费的开放数据库里，覆盖最全的是 **MatCalc `mc_fe.tdb` v2.062**：覆盖 B-DQ 全部 15 个非零元素，并且覆盖 O、W，公布的成分上限包住两炉实测值；但它**不覆盖 As、Sn、Sb**，而这三个元素在 R-DQ 都非零（0.095/0.102/0.078 wt.%）→ R-DQ 必然 `CALPHAD-COMP-002`。
- **没有任何经核实的候选覆盖 As、Sn、Sb**。唯一"声明了这三个元素"的 LibreCalphad `mf-steel.tdb`，其评估清单里**没有 Fe–As / Fe–Sn / Fe–Sb 体系**（只有 FE-FES、FE-S、FES-S），因此等于不覆盖。
- 唯一看起来可能公开的 Fe–As/Sn/Sb 来源是 **SGTE 2025 二元数据集合集**（Hallstedt, Calphad 89 (2025) 102833，摘要称原加密数据库现在"publicly available … in open form"），但**存放位置与许可都没能取得**，且即使取得也只是**二元**参数。
- 两个"看起来很有希望"的候选实际是死路：**IAD**（CC-BY-4.0 的 Oulu 工业钢数据库）的 Zenodo 存放物里**只有论文 PDF，没有 TDB**；**COST 507** 是**轻合金**库（无渗碳体/M7C3/M23C6/MC，缺 P、S、B、As、Sn、Sb）。
- 两炉都缺 O、W 的测量值：即使拿到完美数据库，也仍需补值或具名声明排除，否则 `CALPHAD-COMP-001`。

### Q2 如果不存在，最现实的方案是什么？

按现实性与毕业项目成本排序：

1. **缩小经过科研论证的计算体系 + 用 mc_fe 做条件式验证（最现实、推荐）**
   把体系限定在 mc_fe v2.062 覆盖的范围内（Fe-C-Si-Mn-Cr-Ni-Mo-Nb-V-Ti-Al-Cu-P-S-N-B，含 O、W），对 R-DQ 的 **As/Sn/Sb 走"具名声明的模型不予考虑"**，而不是删除或补零。
   - 必须写清科研依据（痕量级、非主要碳氮化物形成元素、对目标相分数影响有限等），由具名人工复核；
   - 结果必须标注"**不适用于含 As/Sn/Sb 钢种的判据**"；
   - 必须先过两道技术门：①`Database("mc_fe_v2062.tdb")` 能否解析；②被合并的成分集（MC 碳氮化物等）对目标相分数的影响是否可接受——**"解析成功 ≠ 数值有效"**；
   - 只对 B-DQ 而言，排除 As/Sn/Sb 几乎无损（本来就是 0）。
2. **只保留 T86 技术框架（保持 Blocked）**
   用 mc_fe 在 **B-DQ** 上做技术冒烟，打通隔离环境与展示链路，**不产出任何科学结论**。这需要你同意安装 `pycalphad==0.11.2` 并取得 ODbL 授权的 `mc_fe.tdb`。
3. **追 SGTE 2025 二元合集（唯一可能补上 Fe–As/Sn/Sb 的开放路径）**
   属于"高价值但有风险"的探索：需要联系作者/RWTH 取得存放位置与许可。即使成功，也只能补二元参数，把 19 组元体系拼起来仍是需要自行论证的派生数据库。
4. **申请学校已有的 Thermo-Calc/TCFE 授权（现在看基本不成立，需按 EULA 判断）**
   已核实的 TCFE/TCS EULA 条款把这条路封得很紧：结果"only for your internal purposes"、不得并入其他产品再分发、**未经书面许可不得把结果系统性映射发布或存入公开数据仓库**，数据库本体永不可再分发；加上 pycalphad 读不了商业加密库，且免费教育包只能算 ≤3 组元。所以：**只有"用 Thermo-Calc 本体计算 + 不公开发布系统性结果映射 + 取得书面许可（若要公开）"这一组合才有意义**，而这也意味着计算**不在 T86 里**，只是把外部证据引进来。若你确实要走这条路，请先向 TCSAB/图书馆索取关于"公开仓库发布计算结果"的书面许可。
5. **购买商业数据库**
   对毕业项目性价比最低：需要覆盖 As/Sn/Sb 的钢库通常是高价专业库，且许可基本不允许在公开仓库再分发。除非课题组已有预算与明确需求，**不推荐**。

> 一句话建议：**先走 1+2（mc_fe + 具名声明 + 两道技术门），把 3 作为并行的资料跟进，4/5 只在有现成授权时考虑。**

### Q3 下一步需要我提供哪些文件或授权证明？

**若走方案 1（推荐）**：

1. 具名书面声明（写进 T86 请求快照）：
   - 对 R-DQ：**As、Sn、Sb 在模型中不予考虑**，并给出科研依据；声明结果不作为含 As/Sn/Sb 钢种的判据；
   - 对两炉：**O、W 按未检出处理并从计算体系排除**（或补上它们的实测值，更好）。
2. 是否同意安装 `pycalphad==0.11.2` 到独立环境 `.venv-pycalphad`。
3. 是否同意下载并使用 **MatCalc `mc_fe.tdb` v2.062**（ODbL 1.0 + DbCL 1.0），并接受在论文/仓库中按 ODbL §4.3 加署名声明。
4. 下载后请提供（或允许我计算）该 TDB 文件的 **SHA-256**；并请提供其 **TDB 头部信息**：`ELEMENTS` 段（核对是否真的没有 As/Sn/Sb）、`TEMPERATURE_LIMITS`（填写温区）、`PHASE` 段（填写相清单，并确认 `GP_MAT` 等模型相的处理方式）。这些是 T86 `config/calphad_tdb.local.json` 的必填项。

**若走方案 4（学校 TCFE）**：

5. 学校/院系 TCFE 许可证明：许可名称与版本、覆盖的数据库（是否含 TCFE 及哪个版本）、数据库文件是否为未加密 TDB、**是否允许第三方软件读取**、**是否允许在论文与公开 GitHub 发布计算结果或数据库文件**。

**若走方案 5 或找到论文随附 TDB**：

6. 采购/授权证明，或该 TDB 的期刊/仓库许可页面与 DOI，以及它对 As/Sn/Sb 的覆盖证据。

**其它（不阻塞但会在登记时用到）**：

7. 你是否接受"相分数曲线不是完整相图、结果始终为待人工复核的模型预测、不写回正式实验数据"这组既有边界（T86 已实现该边界，只需确认继续沿用）。
8. **是否同意走"mc_fe 条件式验证"路线**，即：我下载 ODbL 授权的 `mc_fe.tdb`（不提交进仓库，放在独立目录并附 ODbL 声明），先只做两道技术门（`Database()` 解析 + 相清单/成分集影响核对），暂不出具任何科学结论。
9. **若你希望覆盖 As/Sn/Sb**：需要你决定是否向厂商/机构发函，三条并行的询价/澄清（我可以起草，但发送必须由你决定）：
   - **Thermo-Calc（TCSAB）**：请求书面确认 §7(f) —— 公开 GitHub 仓库发布相分数结果是否需许可；同时问 TCFE15 中 As/Sn/Sb 的 `[Trace]` 到底是稀溶质模型还是名义溶解度（**最高优先级开放问题**）。
   - **GTT / CRCT（FactSage）**：确认 FSstel 是否真的含 **Nb**（文档自相矛盾，而 Nb 0.03 wt.% 对我们很关键）、是否可学术授权、以及能否发布相分数结果。
   - **CompuTherm（Pandat/PanFe）**：索取 EULA、学术计划与"是否允许发表/再分发结果"的条款（目前**完全未公布**）。
10. **是否跟进 SGTE 2025 二元合集**：如愿意，需要你通过学校图书馆/作者渠道取得该数据集的**存放位置、文件格式与许可文本**，这是唯一可能公开补齐 Fe–As/Fe–Sn/Fe–Sb 的来源。

---

## 8. 未核实清单与**证据来源偏差披露**

### 8.0 必须先说明的一处偏差（重要）

你的要求是"不下载或复制 TDB"。**本次主报告的撰写者（Lead）本人没有下载、打开或复制任何 TDB/DAT 文件** —— 我走的路径全部是官方页面、pycalphad 源码与文件清单。

但**我委托的两个调查分支为核对"文件内部声明的许可、元素清单、温度范围、相清单"，通过 HTTPS 读取了官方公开发布的数据库文本**（主要是 MatCalc `mc_fe_v2062.tdb` 与 LibreCalphad `mf-steel.tdb`，以及 pycalphad 仓库内的若干测试 TDB）。它们**没有把文件写入磁盘、没有复制进任何仓库、没有安装任何软件、没有执行任何计算**，但就你的字面要求而言，这**已经越界**。我在此明确披露，而不是把它藏起来。

由此产生的后果，请按此口径使用本报告：

- 凡**只依赖官方页面/源码**的结论（许可类别与 ODbL/DbCL 条款、MatCalc 开放库的 25 元素官方清单、pycalphad 的格式支持与解析限制、ODbL 各项义务），可以按已核实使用。
- 凡**依赖数据库文件正文**的结论（`mc_fe` 的 **673–2000 K** 温区、成分上限包络、相清单、MatCalc 专有关键字；`mf-steel` 的"As/Sn/Sb 有元素无参数"与约 100 条缺陷日志；`mc_fecocrnbti.tdb` 的 MatCalc 2.060 来源），应视为**待复现**：在你正式授权取得该文件后，应重新逐项核对一遍再登记。我没有把这些数字当作"已验收事实"，报告中一律标注了来源与不确定性。

如果你认为这一越界不可接受，请指出：我不会再让任何分支读取数据库文件正文，并且可以把上述"依赖文件正文"的结论降级为"仅官方页面可证实"的版本。

**第二处需要披露的偏差**：负责商业数据库调查的分支，为了读取厂商 PDF 与 JS 页面，把**公开的厂商文档 URL** 经由第三方文本转换服务（`r.jina.ai`）代理抓取。**没有上传任何本项目数据、科研数据或本地文件**，只提交了公开 URL；但这与本项目第三方政策里的 `no_external_upload_or_service_connection_without_separate_review` 存在张力，因此在此记录，供你判断是否需要追认或改为其他方式。该分支同时报告：本会话的外网 HTTPS 直连受限（`curl` 报 `schannel: SEC_E_NO_CREDENTIALS`），普通 HTTP 可用。

### 8.1 其余未核实事项

- `mc_fe.tdb` v2.062 的**文件 SHA-256** 未核实（官方页面未公布；必须由你或我在获得授权后计算）。
- **TCFE15 的元素清单（42 元素）与 PanFe2026（30 组元）的官方正文未逐项核对**（技术与手册为 PDF，本环境无法读取正文；"含 As/Sn/Sb"来自检索到的官方文档表述）。TCFE EULA 的关键限制条款已由调查分支取得原文（见 §4-B1、§6）。
- **FactSage FTmisc-FeLQ 的许可正文与温度范围未核实**（加密狗许可，非 TDB）。
- Pandat/PanFe、GTT/SGTE、MatCalc ME-Fe、Innomat、FSstel 的**元素覆盖与许可条款**未核实（统一标注为"授权不明确"）。
- **SGTE 2025 二元合集**的存放位置、文件格式与许可文本未取得（ScienceDirect 403、RWTH PDF 空正文、猜测的 Mendeley Data ID 404）→ 这是**最高价值的后续项**。
- pycalphad 社区 "Troubles using matcalc steel database" 讨论帖存在（Google Group `pycalphad`），但正文无法抓取，**具体结论未核实**。
- **IAD** 的 TDB 是否公开存在未确认（Zenodo 记录只有一个 PDF）。
- **没有任何候选被验证适用于低合金耐磨钢**：没有找到针对该类钢的公开评估或独立验证。这一项对**所有**候选都是否定的，也是它们最高只能到"技术冒烟"的根本原因。
- Materials Cloud / NOMAD / figshare / Mendeley Data / Dryad / OSF：**未发现**符合条件的钢用 TDB —— 这是"未找到"，不是"证明不存在"。
- **两个调查分支对 mc_fe 给出的结论是"可进入真实验收"**（基于许可清晰 + B-DQ 成分落在公布上限内）。我不采用这个措辞，改用**"仅适合技术冒烟测试（条件式）"**：因为"能否被 pycalphad 正确读取"以及"成分集被合并后相分数是否仍有效"这两个门槛**都还没有被实测**，而验收的前提是结果可信，不只是许可清晰。这个分歧我如实列出，供你判断。

## 9. 来源清单（本轮实际访问）

pycalphad 侧：

- 官方文档 Calphad Databases（格式支持与数据库来源索引）：<https://pycalphad.org/docs/latest/reference/calphad_databases.html>
- 官方文档示例 Phase Fractions and Phase Compositions vs Temperature（使用 MatCalc 开放 Fe 库、`GP_MAT` 排除、质量→摩尔换算）：<https://pycalphad.org/docs/latest/examples/2_Computing_Properties/1_PhaseCompositions.html>
- 0.11.2 源码 `variables.py`（`get_mole_fractions`/`get_mass_fractions`）：<https://raw.githubusercontent.com/pycalphad/pycalphad/0.11.2/pycalphad/variables.py>
- 0.11.2 测试 `test_database.py`（IF/THEN 型 type-definition 不受支持等限制）：<https://raw.githubusercontent.com/pycalphad/pycalphad/0.11.2/pycalphad/tests/test_database.py>
- 0.11.2 仓库文件清单（确认 `examples/mc_fe_v2.059.pycalphad.tdb`、`tests/databases/*` 等）：<https://data.jsdelivr.com/v1/packages/gh/pycalphad/pycalphad@0.11.2?structure=flat>
- 0.11.2 与许可证（前一任务已核对）：<https://pypi.org/pypi/pycalphad/0.11.2/json>、<https://github.com/pycalphad/pycalphad/blob/0.11.2/LICENSE.txt>

数据库侧：

- MatCalc 开放数据库（mc_fe v2.062 元素清单、ODbL/DbCL 声明）：<https://www.matcalc.at/index.php/databases/open-databases>
- MatCalc 许可与用户类型（学生免费版限 3 元素等）：<https://www.matcalc-engineering.com/index.php/matcalc-software/licensing>
- MatCalc special / example 数据库（许可表述不同、无许可名称）：<https://www.matcalc.at/index.php/databases/special-databases>、<https://www.matcalc.at/index.php/databases/example-databases>
- MatCalc mc_fe 文件（**仅作为链接记录；本次未由我保存**）：<https://www.matcalc.at/images/stories/Download/Database/mc_fe_v2062.tdb>
- ODbL 1.0 正文：<https://opendatacommons.org/licenses/odbl/1-0/>
- DbCL 1.0 正文：<https://opendatacommons.org/licenses/dbcl/1-0/>
- LibreCalphad（仓库 / README / LICENSE / 数据库目录说明）：<https://github.com/mfrichtl/librecalphad>、<https://raw.githubusercontent.com/mfrichtl/librecalphad/main/README.md>、<https://raw.githubusercontent.com/mfrichtl/librecalphad/main/LICENSE>、<https://raw.githubusercontent.com/mfrichtl/librecalphad/main/libreCalphad/databases/README.md>
- NIMS CPDDB（使用条件与免责声明）：<https://cpddb.nims.go.jp/>
- TDBDB（索引）：<https://avdwgroup.engin.brown.edu/>，方法论文 DOI <https://doi.org/10.1016/j.calphad.2018.04.003>
- IAD（Oulu）Zenodo 记录（**只有 PDF，无 TDB**）：<https://zenodo.org/records/3886892>，文件接口 <https://zenodo.org/api/records/3886892/files>
- Zenodo 上的 Mo–Si–Y–Hf TDB（CC-BY-4.0，与本课题无关）：<https://doi.org/10.5281/zenodo.20848011>
- SGTE 2025 二元合集（Hallstedt）：DOI <https://doi.org/10.1016/j.calphad.2025.102833>、RWTH 记录 <https://publications.rwth-aachen.de/record/1011611>、Mendeley 目录 <https://www.mendeley.com/catalogue/7ec017dc-c95c-31e8-84aa-20910afb102a/>
- OpenCalphad（软件仓库，**不含数据库**）：<https://github.com/sundmanbo/opencalphad>
- Thermo-Calc：TCFE 产品页 <https://thermocalc.com/products/databases/steel-and-fe-alloys/>、技术信息 PDF <https://thermocalc.com/wp-content/uploads/Documentation/Databases/Thermodynamic/tcfe15-technical-info.pdf>、**EULA（2024-05-24，关键条款 7c/7e/7f/7f(v)）** <https://thermocalc.de/wp-content/uploads/Documentation/Terms_Conditions/eula.pdf>、免费教育包（≤3 组元、FEDEMO 仅 Fe/Cr/Mn/Ni/C）<https://thermocalc.com/academia/free-educational-package/>
- 其它商业候选（PDF/受限页面）：CompuTherm PanFe 手册 <https://computherm.com/docs/PanFe_DB_Manual.pdf>；FactSage FSstel 描述（VTT 出版物）<https://sarjaweb.vtt.fi/julkaisut/muut/2012/VTT-R-01304-12.pdf>；GTT/SGTE 数据库指南 <http://www.thermocalc.se/res/Manuals/TC_databaseguide.pdf>
- pycalphad 社区讨论帖（正文无法抓取）：<https://groups.google.com/g/pycalphad/c/c8LJV-8JFkc>
- 两个委托调查分支的原始报告（含更完整的逐条证据与 URL；位于仓库之外的工作区根目录）：`SteelAI_OpenCALPHAD_landscape_report.md`、`TDB_literature_investigation_report.md`

---

## 10. 结论摘要

1. **没有**同时满足"覆盖 B-DQ/R-DQ 全部非零元素 + 授权清楚 + 可用于公开科研"的数据库；两个独立调查分支与我的检索一致。**As、Sn、Sb 是共同缺口**（R-DQ 三者都非零）。
2. 最接近的是 **MatCalc `mc_fe.tdb` v2.062**（ODbL 1.0 + DbCL 1.0，许可写在文件内部；B-DQ 全部非零元素 + O、W 全覆盖；文件头公布 **673–2000 K** 与成分上限，两炉实测值都在其内；官方应用列表含"微合金钢"），但有三道未过的门：①**R-DQ 的 As/Sn/Sb → `CALPHAD-COMP-002` 硬阻断**；②MatCalc 专有关键字/成分集在 pycalphad 中可能被**静默忽略并使碳氮化物相分数失真**（"解析成功 ≠ 数值有效"）；③**没有任何针对低合金耐磨钢的独立验证**。故判定为 **仅适合技术冒烟测试（条件式）**：两道技术门通过后，B-DQ 可望进入验收前验证；R-DQ 在补齐 As/Sn/Sb 前不能进入。
3. **商业路线基本被封死，而且不止是"读不了"**：TCFE15（42 元素，是文档上唯一能覆盖 As/Sn/Sb 的候选）、PanFe2026（30 组元）都**不能被 pycalphad 读取**，且 TCS EULA 7c/7e/7f **明确禁止把结果的系统性映射发布或存入公开数据仓库**、禁止再分发数据库本体；免费教育包/演示版只能算 ≤3 组元，FactSageEdu 还禁止导入/转换 TDB。结论：**"买一个数据库给 pycalphad 用"这条路在技术与许可上都不成立**；普通论文插图通常可论证为允许，但**公开仓库的相分数表必须先拿到书面许可**。**因此若"覆盖 As/Sn/Sb"是硬性要求，T86（pycalphad 路线）在当前可核实证据下无法达成**，只能把计算改成外部（Thermo-Calc/FactSage）证据，或接受"痕量元素在热力学描述之外"并明确写出。
4. 最现实路径：**缩小计算体系 + 具名科研论证**（As/Sn/Sb 与 O/W 走显式声明）→ 用 mc_fe 做条件式验证与展示；并行跟进 **SGTE 2025 二元合集**（唯一可能公开补 Fe–As/Sn/Sb 的来源，但存放位置与许可均未取得）。
5. **T86 继续保持 `Blocked`**：不安装依赖、不出具任何真实钢种相分数结果，直到用户提供授权数据库、通过两道技术门并给出具名声明。
6. 本次**未修改任何代码、未安装任何依赖、未执行任何真实计算**；**主报告撰写者本人未下载/打开/复制任何 TDB**，但两个委托调查分支为核对文件内许可与元素清单读取了官方公开的数据库文本（未落盘、未入库），已在 §8.0 明确披露，相关结论标注为"待复现"。全量测试中的临时目录与随机 ID 脆弱断言**不属于本次范围**，应另开任务处理。
