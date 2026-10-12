# STEEL-V1-01 · 独立产品能力与缺口审计

> 性质：按 2026-09-28 夜间工作队列第 3 项交付的**只读审计**。本项不改任何 SteelAI 代码；既有未跟踪文件（`config/calphad_adapter_v1.0.json`、`steelai/thermal_softening_case_ref.py`、`scripts/export_thermal_softening_case_ref.py`、`tests/test_thermal_softening_case_ref.py`、已修改的 `docs/THERMAL_SOFTENING_CASE_WORKFLOW.md`）**原样未动**。
>
> 状态标签四态：**【已有代码】**（实现 + 测试在库）、**【本机可运行】**（本批实际运行并记录退出码）、**【仅文档/历史验收】**（README/doc 宣称、本批未复跑）、**【缺失】**。凡未在本批运行的，一律标「本批未验证」。

---

## 0. 本批实测记录（唯一的新运行证据）

| 命令（仓库规定入口形态） | 结果 | 退出码 |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe -B -m pytest -q tests/test_thermal_softening_case_ref.py` | 首跑 **8 passed, 24 errors** —— 24 个错误全部是**环境性**的：pytest `tmp_path` 工厂在既有共享根 `%TEMP%\pytest-of-pc` 上撞 `PermissionError (WinError 5)`（`.venv\Lib\site-packages\_pytest\pathlib.py:175`），非代码缺陷 | 0* |
| 同上 + `--basetemp=<本批自建临时目录>` | **32 passed**（4.27s→1.69s） | 0 |
| `.\.venv\Scripts\python.exe -B -m pytest -q tests/test_thermal_softening_case.py --basetemp=…` | **5 passed** | 0 |

\* pytest 对「收集/装配错误」的退出码语义；两次运行均无断言失败。**结论**：双道次软化只读案例链的两个测试文件在本机全绿（37/37），前提是避开共享 pytest 临时根的 ACL 限制。完整 `.\scripts\test.ps1` 本批**未**运行（纯文档任务，避免以偏概全的「全量绿」表述）。

---

## 1. 目标链逐段能力表

目标链：**输入数据/文献 → 确定性校验与计算 → 图表 → 文献来源 → 报告 → 独立运行**。

### 1.1 输入数据 / 文献

| 能力 | 入口 | 证据 | 状态 |
| --- | --- | --- | --- |
| 外部数据标准化（陌生 CSV → 受治理标准表） | `steelai/external_data_standardizer.py`；T70 | `tests/test_t70_external_standardization.py`（8 个测试函数）；`docs/T70_EXTERNAL_DATA_STANDARDIZATION.md` | 【已有代码】 |
| 热模拟曲线点入库（不回读原始仪器文件） | `steelai/thermal_simulation_intake.py`；T71 | `tests/test_t71_thermal_simulation_intake.py`（8）；`docs/T71_THERMAL_SIMULATION_INTAKE.md` | 【已有代码】 |
| 文献口径登记（double-hit 规则 + DOI 依据） | `config/thermal_double_hit_processing_v1.0.json`（被 `steelai/thermal_simulation_analysis.py:15` 加载） | `docs/T73_DOUBLE_HIT_LITERATURE_PROCESSING.md`；`load_double_hit_policy`（`thermal_simulation_analysis.py:39`） | 【已有代码】（静态规则登记，**非**文献检索） |
| 文献检索 / RAG / 引文库 | —— | 全库无对应模块（`grep matplotlib|plotly|docx|literature 检索` 仅命中规则登记与曲线处理） | **【缺失】** |

### 1.2 确定性校验与计算

| 能力 | 入口 | 证据 | 状态 |
| --- | --- | --- | --- |
| 治理内核五域适配（数据/统计/图像/Agent 网关/运行中心） | `steelai/governance/`、`data_intake_governance.py`、`image_model_governance.py`、`agent_evidence_gateway.py`、`run_center.py`；T52~T56 | `tests/test_t52_governed_data_physics.py`（7）/ `test_t53_statistics_governance.py`（7）/ `test_t54_image_model_governance.py`（7）/ `test_t55_agent_evidence_gateway.py`（11）/ `test_t56_run_center.py`（9），共 41 个测试函数 | 【已有代码】 |
| SteelData 标准化 + QC（跨库桥接） | `steelai/steeldata_bridge.py`；SteelData 独立库 | T40 文档记录 SteelData 88 项通过（`docs/T40_FLAGSHIP_DEMO.md:9`）；本批未复跑 SteelData | 【仅文档/历史验收】 |
| SteelStats 组级统计（跨库桥接） | `steelai/steelstats_bridge.py`；SteelStats 独立库 | T40 文档记录 31 项通过；本批未复跑 | 【仅文档/历史验收】 |
| double-hit 曲线处理（文献口径 → 有效加载段） | `steelai/thermal_simulation_analysis.py` 的 `process_double_hit_curve`（`:162`） | 经 `tests/test_t74_thermal_simulation_features.py`（4）与 T75 链间接覆盖；**无独立 `test_t73`** | 【已有代码】（测试借道 T74/T75） |
| 受治理特征表（16 行正式特征） | `steelai/thermal_simulation_features.py:102` 调用上项 | `tests/test_t74_thermal_simulation_features.py`；`docs/T74_THERMAL_SIMULATION_FEATURE_TABLE.md` | 【已有代码】 |
| 软化率计算（方法冻结：2% 偏移主方法，5% 定真应变对照） | T75 | `tests/test_t75_softening_method_readiness.py`（4）；`docs/T75_SOFTENING_METHOD_DECISION.md`（2026-09-11 冻结记录） | 【已有代码】 |

### 1.3 图表

| 能力 | 入口 | 证据 | 状态 |
| --- | --- | --- | --- |
| 治理表内嵌可视化（温度/力/位移/应力-应变，B/R 对比） | Streamlit `st.line_chart`（`steelai/views/physics_view.py:320,529`）；T72 | `tests/test_t72_thermal_simulation_visualization.py`（6）；`docs/T72_THERMAL_CURVE_VISUALIZATION.md` | 【已有代码】（Streamlit 内嵌，非出版级） |
| 出版级图表导出（矢量/独立图片文件） | —— | 全库无 matplotlib/plotly 依赖命中 | **【缺失】** |

### 1.4 文献来源

| 能力 | 入口 | 证据 | 状态 |
| --- | --- | --- | --- |
| 处理规则的依据登记（DOI + 来源链接入 config） | `config/thermal_double_hit_processing_v1.0.json`；`docs/T73…`「依据登记在 config」 | 本批确认文件存在（tracked） | 【已有代码】 |
| 引用条目管理 / 自动引文 / 检索 | —— | 无对应模块 | **【缺失】** |

### 1.5 报告

| 能力 | 入口 | 证据 | 状态 |
| --- | --- | --- | --- |
| 受限解释 + 摘要绑定成果包（37 项、sha256 绑定） | `steelai/flagship_demo.py`；T40 | `tests/test_t40_flagship_demo.py`（2）；`docs/T40_FLAGSHIP_DEMO.md`（Workbench 142 通过/3 跳过、SteelData 88、SteelStats 31，状态 `Done`） | 【已有代码】（全量套件本批未复跑） |
| 案例内受治理 Markdown 分析草稿 `analysis_draft.md`（由 `publish_softening_case` 写入并封入 Manifest） | `steelai/thermal_softening_case.py` 的 `_draft_markdown` | STEEL-V1-03A 修正后：草稿全部由案例自身行/QC/警告/来源派生（含合成演示标记预留位）；聚焦测试见 `tests/test_thermal_softening_case.py` | 【已有代码】（初版曾硬编码已批准批次表述——「四个通过项」与 A79/A80/A84/A85——已订正，见 §0/§5） |
| docx/html 报告导出 | —— | 无 python-docx/导出模块命中 | **【缺失】** |
| 校验报告（历史） | `docs/T57_VALIDATION_REPORT.md` | 仅文档 | 【仅文档/历史验收】 |

### 1.6 独立运行

| 能力 | 入口 | 证据 | 状态 |
| --- | --- | --- | --- |
| 冻结演示一键重放 + 独立复核 | `steelai/flagship_demo.py` 的 `demo_identity`（`:90`）/ `verify_flagship_demo`（`:105`）；`docs/T40_FLAGSHIP_DEMO.md`「一键运行」节 | 重放 `reused=true`、独立复核 `passed`（T40 文档记录） | 【仅文档/历史验收】（本批未复跑 T40） |
| Streamlit 应用（六页复杂页结构） | `app.py`（`st.navigation`：首页/项目与样品/数据处理/分析与报告/AI 助手/作品集/高级功能） | `app.py:14-27`；`docs/USER_GUIDE.md` | 【已有代码】（UI 本批未启动，未验证） |
| 双道次软化只读案例参考（对外公开接口） | `steelai/thermal_softening_case_ref.py` 的 `build_case_reference`（`:97-151`）；CLI `scripts/export_thermal_softening_case_ref.py:80` | **本批实测 32/32 + 5/5 通过**（见 §0） | **【本机可运行】** |

**逐段小结**：链的前半段（输入标准化 → 确定性计算 → 内嵌图表）能力完整且测试在库；缺口集中在**链的后半段**——文献检索/引用管理（1.1/1.4）、出版级图表与 docx/html 报告（1.3/1.5）、以及「全量绿」的历史验收未在本批复跑（1.5/1.6）。

---

## 2. 推荐 v1 可展示业务路径（一条）

**推荐：「双道次软化只读案例链」的合成端到端演示**（从合成 DH 采集数据到冻结复核包，全程确定性、可公开）：

```
合成 double-hit CSV（公开替身，非真实 ZHT.A* 测量）
  → T70 外部标准化（受治理标准表，人工形状确认）
  → T71 曲线点入库（needs_human 门）
  → T72 治理表可视化（Streamlit 内嵌图）
  → T73 规则 + T74 受治理特征表（16 行，已具名批准的机制复用）
  → T75 冻结方法软化率（2% 偏移主方法）
  → T40 式冻结复核包（sha256 绑定 + verify_flagship_demo 式独立复核）
```

- **可公开合成替身**：合成 DH 采集数据 + 合成 governed case 包（与平台测试 `test_thermal_softening_case_ref.py` 的合成 package_root 同构）。公开演示不接触任何真实测量。
- **真实科研案例**：只列候选与**缺少的人工核对条件**——① 真实 ZHT.A* 仪器的原始文件读取与人工形状确认（T71 门）；② T74 特征的具名批准流程重走；③ T75 冻结方法对真实道次的适用性核对（0.2% 偏移法按 T75 决策**不发布**正式结果）。本审计不接触原始测量，不产出新科研结论。
- **两个易混概念的区分**：
  - **双道次软化只读案例参考**（已有，【本机可运行】）：`build_case_reference` 输出受限六字段，供 PAOS 只读登记，不搬运数据；
  - **材料数据上传分析工作流**（部分存在）：T70 是它的起点，但「上传 → 自动全链分析 → 报告」的自动化编排不存在，也不应该存在（治理要求逐段人工门）。

---

## 3. STEEL-V1-03A/B～04 最小改动顺序（2026-09-28 按主路线图订正编号）

> 编号订正：主路线图中 `STEEL-V1-02` = 确定性分析链、`STEEL-V1-03` = 文献依据与报告。本审计初版把报告切片误称 V1-02，现更正为 **V1-03A/B**；本阶段两切片**只复用**已存在的双道次案例计算，**不**宣称 V1-02 通用分析链已完成。

| 顺序 | 工作单 | 最小可验收成果 | 依赖 | 是否需要 PAOS |
| --- | --- | --- | --- | --- |
| 1 | **STEEL-V1-03A · 分析草稿的合成案例正确性**（本批已完成） | `_draft_markdown` 全部由案例自身行/QC/警告/来源派生：1 行合成案例不再声称「四个通过项」或凭空列出 A79/A80/A84/A85；真实批次形状的具名警告与文献方法局限不丢失；预留合成演示标记 | 无 | **否** |
| 2 | **STEEL-V1-03B · 一键公开合成案例演示**（本批已完成，见 `docs/STEEL_V1_03_SYNTHETIC_DEMO.md`） | 离线演示入口调用 `publish_softening_case` / `verify_package`：合成包 Manifest 标 `synthetic_demo_data`，幂等复用、篡改失败，正式路径不变 | V1-03A | **否** |
| 3 | **STEEL-V1-04 · 与 PAOS 公开接口对齐** | 平台侧跨仓库契约测试（钉住 `build_case_reference` 返回形状）+ 按 PAOS-005C4B 关口完成一次真实只读登记 | 平台 C4B 关口（建根 + 用户决策）；SteelAI 侧零改动 | 是（仅经公开接口） |

- **可脱离 PAOS 直接启动/复现的**：V1-03A/B，以及本批已验证的两个案例测试（§0）。PAOS 只通过 `build_case_reference` / export CLI 等**公开接口**读取受限结果（case_id、manifest_digest、计数），**永不**打开 `lab_data/`、私有 `outputs/` 或原始测量。
- **重复建设风险**：①不要在 PAOS 侧复制案例读取逻辑（跨仓库只读调用即边界）；②报告生成不得引入第二条「绕过治理内核」的取数路径（`analysis_draft.md` 已由 `publish_softening_case` 统一产出，不再另起报告管线）；③图表若引入 matplotlib 须先过 T54 图像治理适配，而不是旁路。

---

## 4. 四态清单汇总与「未验证」声明

- **【本机可运行】（本批实测）**：`test_thermal_softening_case_ref.py` 32/32、`test_thermal_softening_case.py` 首批 5/5 → STEEL-V1-03A 后 **10/10**（新增 5 个草稿派生测试；`--basetemp` 规避共享临时根 ACL 限制）。
- **【已有代码】（测试在库，本批未复跑）**：T52~T56（41 个测试函数）、T70/T71/T72/T74/T75（30 个测试函数）、double-hit 规则处理、案例内 Markdown 草稿（V1-03A 后按案例事实派生）。
- **【仅文档/历史验收】（不得据 README 宣称当下可用）**：T40 全量 142+88+31 的历史记录、Streamlit UI 六页。
- **【缺失】**：通用文献检索/引用管理、出版级图表导出、docx/html 报告导出、独立 `test_t73`（T73 逻辑当前借道 T74/T75 测试覆盖）。**注意区分**：受治理 Markdown 草稿**已有**（见 1.5），缺失的是通用检索与 Word/HTML 等导出形态。
- **【需要外部条件】**：真实 ZHT.A* 原始测量的人工核对与 T71 门批准；T86 CALPHAD 系列的外部数据库候选条件（其工作目录 `docs/T86_*.md` 六份与本批未跟踪的 `config/calphad_adapter_v1.0.json` 均未触碰、未运行）。

---

## 5. 自验记录（本项）

- 证据方法：只读 `grep -n` / `sed -n` 定位 + 两处聚焦测试实跑（§0，仓库规定解释器与入口形态，准确记录退出码）；未读 `lab_data/`、原始科研文件、私有 `outputs/`、个人目录；未触碰 CALPHAD 配置与双道次软化引用代码/测试的**内容**（仅运行其测试）。
- `git diff --check`：退出 **0**（开工时与收工时均核）；本项仅新增本文档 + 批量执行记录，既有脏文件（1 改 + 4 未跟踪）内容与开工基线一致。
- 运行遗留：`--basetemp` 指向本批自建临时目录 `paos-overnight-20260928`（steel-pytest/steel-pytest2），无仓库内残留。
- 最短下一工作单：**STEEL-V1-02**（报告导出，无需 PAOS、无新依赖决策点）。
