# 双道次软化实验：一次可追溯分析流程

## 入口与输入

此流程使用已批准的 T71 运行表和曲线点表、T74 特征表、T75 正式软化结果表，以及项目负责人批准的 T75 方法登记。文献输入为张玲 2007 年博士论文《TSDR 工艺热加工过程的组织演变与控制》的 PDF 副本；程序核对其 SHA-256 后引用第 4.1.2.1 节、图 4.4、图 4.5 和式 (4.1)。文献路径由运行者传入，不写入程序或模型请求。

```powershell
cd '<SteelAI-Workbench项目根目录>'
.\.venv\Scripts\python.exe -B -m scripts.analyze_thermal_softening_case --literature-pdf '<文献PDF的本机路径>'
```

运行命令打印 `case_id` 和草稿位置。程序先从批准的标准化曲线重新计算 T75，逐字段核对正式结果、T74 特征链接、方法登记哈希及具名批准状态；任何不一致都会停止。计算与文献检查均为只读操作。结果包写入被 Git 忽略的 `outputs/thermal_softening_cases/<case_id>/`，含 `evidence.json`、`analysis_draft.md`、治理 Manifest 和 `COMPLETE`。重复运行同一输入可复用已校验包；包被修改后不能继续作为证据。

## Agent 分析入口

在 SteelAI Workbench 的“证据约束问答”中使用类似问题：

> 请调用 `get_thermal_softening_case` 读取 `<case_id>`，按已确认事实、当前判断、待验证假设、证据与局限、下一步行动五部分分析双道次软化实验。不要把大于 100% 的机械软化率解释为再结晶体积分数，也不要将 Nb2/Nb4 的结论直接套用到 B-DQ/R-DQ。

`get_thermal_softening_case` 只接受案例编号，只从完整性验证通过的包读取结构化证据；Agent 证据网关审核工具参数和输出，不接收任意文件路径。云模型结果是分析草稿，必须由研究者核对曲线、方法、异常点与冶金解释后才能进入论文或正式结论。平台 DSH 的独立桥接白名单尚未包含这个新工具；当前入口是 Workbench 的 Research Agent 页面。

2026-09-24 本机验证：真实案例包与证据网关读取通过；模拟模型完成“工具调用—证据返回—五段式回答”的完整往返。本机通过 SOCKS 代理访问云模型，经用户授权后仅在此项目独立 `.venv` 安装了 `socksio==1.0.0`；可选依赖记录在 `requirements-agent-proxy.txt`。若其他机器也使用 SOCKS 代理，可运行 `python -m pip install -r requirements-agent-proxy.txt`。未使用 SOCKS 代理的环境无需安装。

真实 DeepSeek 往返也已完成：案例 `TSC-9DF11B41FB31FF5C6C08` 经 `get_thermal_softening_case` 和 `get_evidence_validation_summary` 两个只读工具送入模型，证据网关审计包为 `outputs/agent_gateway/AGENTGW-5462F00AB8C5AC0A7246/`，状态 `completed`，结构化输出契约通过，仍要求人工复核。模型建议 2% 已批准方法作主报告口径、5% 作敏感性对照，保留 4 个主结果超界警告，并指出论文与本项目的 `sigma_m` 定义不同。人工检查同时发现模型有一处**列表归属表述错误**：它把 A90 写进“方法差至少 10 个百分点”的列表；案例证据中的准确列表只有 **A82、A87、A88**。这说明网关通过只代表来源和输出形式合规，不能取代逐句科研复核。模型还引用了本项目其他 EBSD/SEM 证据门禁；这些不是本次软化实验的直接组织证据。

## 受限只读引用接口（PAOS-004B1 / 004B1R / 004B1R2）

给平台侧登记用的**最小只读引用**，只接受案例编号，不接受任何文件路径。从仓库根目录直接运行，**无需设置 `PYTHONPATH`**：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\export_thermal_softening_case_ref.py <case_id>
```

**包根目录不可由调用方指定**：接口只使用 SteelAI 自有的固定案例根目录；既没有路径参数，也不读取任何环境变量（早期版本的环境变量覆盖已移除）。脚本的参数解析同样遵守该边界。

成功时向 stdout 打印机器可读 JSON，字段仅限：

| 字段 | 含义 |
| --- | --- |
| `case_id` | 案例编号（`TSC-` + 20 位大写十六进制） |
| `package_verification` | 复用 `verify_package` 的完整性核验结果，成功时恒为 `passed` |
| `manifest_digest` | **已核验**治理 Manifest 的 SHA-256（取自核验结果，非调用方参数） |
| `review_state` | 成功时恒为 `needs_human` |
| `row_count` / `artifact_count` | 非敏感计数：整理后证据行数、Manifest 声明的工件数 |

拒绝时 **stdout 为空、退出码非零**，stderr 只输出一行稳定的路径无关错误码（**不打印 traceback、不回显用户输入、不转发治理层内部错误文本、不含本机路径**）：

| 退出码 | 错误码 | 含义 |
| --- | --- | --- |
| `2` | `CASE_ARGUMENT_UNKNOWN` | 出现未知命令行参数（含任何试图指定路径的参数） |
| `2` | `CASE_ARGUMENT_INVALID` | 命令行不是单个案例编号（缺参数等） |
| `2` | `CASE_ID_INVALID` | 编号不符合 `TSC-[A-F0-9]{20}` |
| `2` | `CASE_PACKAGE_MISSING` | 该编号没有对应的受治理案例包 |
| `2` | `CASE_EVIDENCE_UNAVAILABLE` | 包的整理后证据无法读取 |
| `2` | `CASE_PACKAGE_INVALIDATED` | 包未通过治理完整性核验（含被篡改、Manifest 缺失） |
| `2` | `CASE_IDENTITY_MISMATCH` | 身份不符：Manifest 身份不是请求编号，**或**包内证据的 `case_id` 不是请求编号 |
| `2` | `CASE_REVIEW_STATE_NOT_NEEDS_HUMAN` | 治理状态不是 `needs_human` |
| `3` | `CASE_REFERENCE_INTERNAL_ERROR` | 非预期内部失败（同样不打印 traceback） |

**身份语义是唯一的**：包完整且 Manifest 身份正确、但**包内 `evidence.json` 的 `case_id` 与请求编号不同**时，固定返回 `CASE_IDENTITY_MISMATCH`（不是完整性失效）。这是复用既有 `load_softening_case` 的证据身份核对结果——它会在已核验包内交叉检查证据 `case_id` 与 Manifest／请求编号。

**语义边界（必须保持）**：本接口只表示“**此时该包的治理完整性已核验**”，**不等于科研结论已批准**，也不等于人工关口已满足；平台侧登记时人工关口必须保持 `open`。本接口只读：不重跑 T71/T74/T75、不创建或修改结果包、不写任务记录、不调用模型、不满足任何关口，输出不含原始数据行、实验值、文献正文、本机绝对路径或草稿正文。

合成测试见 `tests/test_thermal_softening_case_ref.py`（正常导出；非法编号；未知编号；缺失 Manifest；缺失／不可读证据；包篡改；Manifest 身份不一致；证据编号不符但包重新封存有效；`needs_human` 之外状态；公开 CLI 的 `--help`、成功输出与全部拒绝路径均不含本机路径与 traceback；含路径的未知参数在干净进程中不回显输入；旧环境变量不再改变包根选择）。

## 本批状态与科学边界

- 16 个 DH 采集均已有正式 T75 结果；A79、A80、A84、A85 的主结果超过 100%，继续保留为警告。A80、A84 的 5% 对照同样超过 100%。
- 约 1000 ℃、有效变形间隔 9–11 s 的四个范围 QC 通过结果，仅支持本批描述性 B-DQ/R-DQ 比较；约 1100 ℃结果存在较大波动及超界值，暂不拟合动力学。
- T75 主方法取第一道次**峰值**应力为 `sigma_m`；张玲论文式 (4.1) 取第一道次**结束**应力。5% 对照又使用 Hollomon 投影作为 `sigma_m`。因此本项目方法引用了论文的双道次框架，但不是逐项复现；2% 与 5% 的差值不能只解释为取点应变改变。
- 论文中回复、再结晶及 Nb 析出的判断来自其 Nb2/Nb4 材料和指定试验条件。当前案例没有将这些阈值或机制直接赋给 B-DQ/R-DQ；机制判断仍需成分、预应变、应变速率及显微组织等独立证据。
- 此纵向案例使用一篇预登记文献的页码证据。PDF 全库检索、向量索引及 SQL+PDF+其他文件的 Agentic RAG 编排仍是后续工作。

## 验收

成功条件：重新计算的 16 行与正式 T75 逐字段一致；原始超界值未被截断；PDF 哈希匹配；结果包完整性验证通过；Agent 只读工具经证据网关可读取且不返回本机路径；分析维持 `needs_human` 状态。

## 后续残余元素结论报告与阅读缓存

科研工作区的 `01_文献库/PDF库/TMCP/` 中，张玲论文 PDF 旁有对应的 `*_解读卡.md`；`03_论文与投稿/03_热模拟小论文/文献/` 中有 Kapoor 等（2024）综述 PDF 的解读卡。两张卡记录原件哈希、已核页码、方法定义和不可迁移的结论。结合本案例与正式成分表的《残余元素对静态再结晶影响_结论分析报告_2026-09-24.md》放在同一热模拟小论文的 `初稿/` 目录。该报告的可确认结果是约 1000 ℃、9–11 s 两组配对中 R-DQ 机械软化率高于 B-DQ；它没有证明某个残余元素造成静态再结晶的因果效应。

目前 Agent 工具只读取结构化案例证据，**不会自动检索这些 Markdown 解读卡**；未来接入 PDF/文件 RAG 时应先比较原 PDF 和正式数据的哈希，再选择有效卡片作为低成本摘要，具体页码或新问题仍回原件。
