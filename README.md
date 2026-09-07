# SteelAI Workbench MVP

一个面向耐磨钢课题的本地科研 AI 工作台：Python 负责可复现的数据处理与物理计算，云端模型只负责在证据约束下组织自然语言报告。生活管理不在本项目范围内，继续放在 Notion。

本机真实资料路径只保存在被 Git 忽略的 `config/settings.toml` 中，仓库只保留 `config/settings.example.toml`。B/R processed 摘要仍来自 v0.1 已核对研究笔记并受其证据边界约束；阶段一 T10 另外完成了一批脱敏 DQ 逐试样拉伸结果的结果包、重放和暂存预检，但尚未提交正式长表。T11 已在 SteelData 中把可公开的真实格式特征转成合成回归测试。T12 已冻结个人毕业主线数据契约 v1，明确材料、炉次、研究条件、物理试样、报告和逐值观测的关系；现有入库门禁不变。

## 当前状态与项目治理

SteelAI Workbench 当前保留“标准表导入”和“SteelData 标准化接入”两个入口。SteelData v0.2 通过独立 Python 环境、CLI 与结果契约接入拉伸逐试样观测；成分和曲线仍只预览。T23 已接通人工批准后的受控执行，但正式长表仍要用户核对样品对应并确认追加。T24 已增加 40 个脱敏 Intake Agent 案例和确定性评分，当前等待项目负责人审阅标签。DSH 是只读/建议旁路，不替代确定性数据处理，也没有审批、执行或写入权限。

- [当前能力与旧入口状态](docs/CURRENT_CAPABILITIES.md)
- [毕业主线数据契约 v1](docs/GRADUATION_DATA_CONTRACT_V1.md)
- [第三方开源复用登记](THIRD_PARTY.md)
- [T14 Frictionless 可选适配器](docs/T14_FRICTIONLESS_ADAPTER.md)
- [T20 DSH × SteelData v0.2 预览接入](docs/T20_DSH_STEELDATA_V02.md)
- [T21 映射建议契约与状态机](docs/T21_MAPPING_SUGGESTION_STATE.md)
- [T22 SteelData 映射建议人工审批](docs/T22_STEELDATA_HUMAN_REVIEW.md)
- [T23 人工批准后的执行与接入](docs/T23_APPROVED_EXECUTION.md)
- [T24 Intake Agent 固定评测集](docs/T24_INTAKE_AGENT_EVALUATION.md)
- [隐私与版本边界](docs/PRIVACY_BOUNDARY.md)
- [阶段零测试基线](docs/BASELINE_2026-09-04.md)
- [开发任务看板](TASKS.md)
- [变更记录](project_log/CHANGELOG.md)

## 工作台导航

侧栏保留六个主入口，专业功能通过页面顶部的横向子模块切换：

1. 科研总览
2. 数据与物理（样品/B-R对比、Physics Engine、数据质量与扩展准备）
3. 研究助手（端到端研究任务、Research Agent、Agent评测、证据验证）
4. 组织与证据（证据索引、EBSD/MTEX）
5. 模型与自动化（Open Model Lab、任务与结果）
6. Career Portfolio

底层功能视图保留独立代码和测试，但不再占用侧栏入口。

## Research Case Pipeline v0.7

“研究助手 → 端到端研究任务”把B/R processed数据检查、Physics Card、AutoDimple、双尺度EBSD、证据验证和可选DeepSeek综合串成一次可复现运行。每次完成后生成：

- `research_report.md`：区分事实、判断、假设、禁止表述和下一步行动。
- `evidence_snapshot.json`：本次运行实际读取的脱敏结构化结果。
- `run_manifest.json`：数据/代码哈希、阶段状态、Agent轨迹、科学就绪度和隐私声明。

输出保存在`outputs/research_cases/<run_id>/`。当前仅允许B-DQ/R-DQ核心案例；1–14号实验仍保持排除。关闭外部Agent时，全部确定性阶段仍可离线完成。

## Agent Evaluation & Observability v0.9

“研究助手 → Agent评测”提供25个固定问题，覆盖数据事实、Physics、EBSD、SEM、科学边界以及隐私与权限六类能力。评分完全由透明Python规则完成，包括：

- 任务状态是否符合预期；
- 是否调用预期只读工具及正确参数；
- 是否包含必要证据概念；
- 是否触发禁止科学表述；
- 是否泄露本地路径或原始文件名；
- 延迟、工具数和API token用量。

实时评测建议每轮选择1–5题，结果写入`outputs/agent_evaluations/<evaluation_id>/`，包括逐题JSON、Markdown评测报告、评测Manifest、脱敏Trace JSONL和可观测性摘要。本地路径或原始CTF/TIF文件名会在API调用前阻断。

评测中心会保留每轮模型、案例、得分、延迟和Token历史；两轮包含共同案例时，可自动标出能力退化、改善以及成本变化。Trace不保存问题、回答、工具参数、本地路径或原始文件，可作为后续接入MLflow/OpenTelemetry的安全中间层。

## Research Data Contract v0.10

“数据与物理 → 数据质量与扩展准备”使用机器可读契约检查成分、工艺、组织、性能和物理实测/校正数据。它同时保留当前摘要表与未来长表：

- `process_steps.csv`：逐道次、逐工序记录；
- `microstructure_observations.csv`：方法、视场、尺度和指标记录；
- `property_observations.csv`：独立试样级性能记录；
- `physics_observations.csv`：实验值、模型值、校正值和残差。

这些长表尚未创建时只显示“未开始”，不会用0、经验公式或AI输出填补。当前B/R数据通过结构契约，但仍被判定为`directional_evidence_only`，因果推断和机器学习保持未就绪。

本地已准备GitHub Actions质量门禁：每次提交自动运行数据契约、25题Agent评测契约、隐私规则和完整离线测试。CI只使用`data/examples/`中的明确合成数据，不需要API密钥，也不读取真实processed数据或原始实验文件。公开仓库发布仍需单独进行脱敏审计，当前没有向GitHub上传任何资料。

## SteelData 模块接入 v0.14

入口：**数据与物理 → 数据质量与扩展准备 → SteelData 标准化接入**。

- 原有 CSV 入口保留为“标准表导入”，手工整理好的五类长表仍可导入。
- 新入口可调用同级 `SteelData` 的独立 Python 环境，或读取已有 v0.2 结果包；不在 SteelAI 环境中安装 pyjanitor/Pandera。
- 首版接通拉伸结果 → `property_observations.csv`，一条试样记录变成 YS、UTS、EL 三条观测；必须人工对应 `sample_id`，保留原 `specimen_id`。
- 合成数据、partial/failed、QC failed/needs_review、未知/重复样品和不明确单位不能入库。成分与曲线仅预览，尚不转入长表。
- 两路共用最终入库闸门，提交前重检并加写入锁；保存接入审计和逐单元格来源，不自动覆盖旧性能摘要、生成统计结论或改动 DSH。
- 人工批准单条映射建议后可自动执行 SteelData；执行状态、幂等键、尝试记录和审批审计链均可核验。执行完成不会自动写 `data/processed/`。
- 阶段一 T10 已用一批人工批准的脱敏 DQ 结果验证 6 个试样到 18 条性能观测的完整预检；本地暂存状态为 `not_committed`，正式 `property_observations.csv` 仍需另行确认。

操作步骤、字段对应、代码分工和扩展边界见 [docs/STEELDATA_INTEGRATION.md](docs/STEELDATA_INTEGRATION.md)。

## Data Intake Gate v0.11

“数据与物理 → 数据质量与扩展准备”保留当前状态、模板与编号规则和标准表导入，并在 v0.14 增加 SteelData 标准化接入。手工新增数据先使用受控 CSV 模板，并经过本地预检；通过后仍需用户勾选确认，系统才会以仅追加方式写入 `data/processed/`。

当前提供五类长表入口：

- `composition_observations.csv`：逐元素/逐炉次成分观测；
- `process_steps.csv`：保留真实顺序的逐道次/逐工序记录；
- `microstructure_observations.csv`：逐方法、逐视场、逐尺度组织指标；
- `property_observations.csv`：具有真实`specimen_id`的性能记录；
- `physics_observations.csv`：区分实验值、模型估算与校正估算。

导入闸门会拦截缺少必要列或必要值、非有限数值、重复主键、现有记录冲突、未登记样品、超出B/R范围、未知列和非法`measurement_type`。系统不覆盖已有主键，不把空白改成0，不复制上传的原始文件，也不调用DeepSeek。成功写入会在`outputs/data_intake/<intake_id>/`生成规范化暂存表、校验Manifest和提交结果，并在项目事件日志中形成可追溯记录。

编号规则明确区分材料、炉次、工艺批次、研究样品、物理试样、图像视场、观测值和模型运行。视场嵌套于试样，不能冒充独立试样；无法核实的编号必须保留为待核验状态。

## Physics Model Registry v0.12

“数据与物理 → Physics Engine”现在使用本地统一模型注册表，覆盖 Ms、Ac1、Ac3、Tnr、Ceq 和 Pcm 六个模型族及 10 个现有公式版本。每个版本登记模型ID、版本、公式、文献来源、必要输入、输出单位、适用范围、范围依据、限制、许可说明、审核状态、实验对照接口、残差约定和校正状态。

- 每个模型族可选择公式版本；默认卡片仍保持六个目标物理量。
- 缺少必要成分时跳过计算，不把未知值按0代填。
- 超出登记范围时保留结果但显示适用性警告。
- 模型卡和版本对比报告可直接在页面查看/下载。
- `physics_observations.csv`存在匹配实验记录时，页面按“模型值 − 实验值”只读展示实验值、模型值和残差；没有实验记录时不生成伪值。
- 校正结果不得覆盖原始公式，所有公式输出仍是经验估算而非实验真值。

Research Agent和端到端研究任务调用同一注册表的六个默认模型，不再根据旧项目路径是否可用切换计算口径。质量门禁会同时校验模型注册表结构。

## Research Session & Daily Workflow v0.13

“研究助手 → 科研会话”把日常科研问题保存为可继续的本地结构化会话。当前提供五个固定模板：B/R综合任务、新增数据质量检查、Physics实验校正、EBSD双尺度比较和SEM断口分析。

每个会话记录研究问题、B/R样品范围、模板版本、阶段状态、事实/判断/假设/局限、下一步行动和相对运行引用。科研总览显示进行中、阻塞和开放行动；端到端B/R任务完成后会自动关联当前会话并更新对应阶段。

- 会话采用独立JSON文件和修订号，写入时使用原子替换，避免半写入状态。
- 会话只能登记B-DQ/R-DQ，1–14号实验继续由契约排除。
- 标题、问题和记录中不接受本地绝对路径或原始CTF/TIF文件名；原始资料仍通过只读目录和证据索引管理。
- 完成会话时只向项目事件日志写入结构化摘要，便于后续Career Portfolio提取。
- Research Session Contract已经加入离线质量门禁；不存在真实会话时也可只验证五个模板契约。

## 运行

当前工作目录若已包含 `.venv`，可直接双击 `Start_SteelAI.bat`。兼容入口 `启动_SteelAI.bat` 也会调用同一个英文启动器。应用只监听本机 `127.0.0.1`，不会主动暴露到局域网；若已运行，启动器会直接打开现有页面。

首次安装可用 Windows PowerShell：

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

如果电脑上没有 `py`，将第一行换成已安装 Python 3.11+ 的完整路径。

应用核心不依赖网络。Research Agent默认使用DeepSeek API。请在Windows用户环境变量中配置：

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
streamlit run app.py
```

未配置密钥或未安装 `openai` 时，Agent保持离线，分析助手仍可使用离线规则报告。API 调用前请确认数据已脱敏；默认只发送当前选中样品的结构化字段，不发送图片或原始文件。

Research Agent只开放样品、Physics Card、既有EBSD、AutoDimple和证据验证摘要等七个只读工具；不允许修改数据、启动MATLAB/GPU任务或访问未登记文件。当前默认使用DeepSeek OpenAI兼容接口；保留OpenAI供应商适配，但不引入LangChain。

## DeepSeek Harness 旁路接入

DSH 不替换 SteelAI 或 SteelData 的确定性核心。项目通过本地 stdio MCP 桥接，
把上述七个已审计只读工具注册为 `mcp__steelai__*`；T20 以独立 Python 环境
注册 SteelData v0.2 预览服务，T21 增加一个只能保存结构化建议元数据的工具。
两个桥都不提供审批、批次执行或任意 Shell 工具，也不接收 DeepSeek API Key；
建议记录不能直接成为批准配置。

双击 `Start_SteelAI_DSH.cmd` 可从隔离的 `dsh_workspace/` 启动；详细边界和
首个验证提示见 `dsh_workspace/README.md`。启动脚本默认把 DSH 会话设为
`read-only`/需审批模式，不使用 `danger-full-access`。

Evidence & Validation Center当前只覆盖B-DQ/R-DQ核心案例。1–14号实验因数据质量决定暂不进入processed核心证据集、不参与统计或机器学习。中心使用L0–L4证据等级，自动区分方向性观察、证据冲突、未确认结果和因果推断禁区；Research Agent可读取脱敏验证摘要，但不会获得原始路径。

## 接入真实资料

1. 在 `config/settings.toml` 中填写现有 `02_实验数据` 和 WearSteel-AI v0.1 的绝对路径。
2. 在“数据与物理 → 数据质量与扩展准备”下载模板、填写并上传预检；不要手工覆盖`data/processed/*.csv`，也不要复制原始照片与仪器文件。
3. 在“证据与微观组织索引”页面登记图片绝对路径、模态和人工提取参数。
4. Physics Engine 会优先动态读取原 v0.1 的 13 个模型；只有路径不可用时才使用 `steelai/physics.py` 的备用公式。
5. Open Model Lab 会读取SEM同名HDR中的倍率和像素尺寸，先生成B/R同倍率小样本试验清单；不会修改或复制原始TIF。

## Open Model Lab

重型开源模型不直接安装到主应用环境。每个模型应使用独立环境，先在公开示例和小规模真实数据上验证，再通过适配器返回结果。当前首个试验为B/R DQ冲击断口的1000× SEM图片配对；页面只完成候选发现、元数据读取、预览与试验清单生成，尚未把模型输出视为科研数据。

CSV 以 `sample_id` 为关联键。空值留空，不要用 0 代替“未测”。1–14号实验继续排除；后续优先补齐B/R核心案例的逐工序、逐视场、独立试样和物理实测长表。

## 数据与证据边界

- `data/processed/`：供应用读取的结构化副本/摘要，不是原始数据真源。
- `data/index/`：原始文件路径、微观照片和证据索引。
- `project_log/events.jsonl`：应用内生成的分析、决定和里程碑事件。
- `project_log/CHANGELOG.md`：版本级变更。
- `outputs/reports/`：可复制到论文笔记或组会材料的分析报告。
- `outputs/portfolio/`：求职展示材料。

公式输出是经验估算值，不是实验真值。当前适用范围提示是工作台审查护栏，并不等同于论文作者声明的完整适用范围。

## 测试

```powershell
python -m unittest discover -s tests -v
```

核心测试不需要外部API；GitHub CI使用合成数据运行同一套质量门禁。
