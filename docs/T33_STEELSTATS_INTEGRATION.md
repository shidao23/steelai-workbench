# T33 SteelStats 模块接入

状态：Done。SteelAI Workbench 现在可以选择一个完整的 SteelData 拉伸结果包，在人工确认统计身份后，通过同级 SteelStats 的独立 Python 环境生成可追溯描述统计报告。

## 使用入口

打开“数据与物理”，选择“可追溯统计”。操作顺序如下：

1. 填写包含 `manifest.json` 和 `COMPLETE` 的整个 SteelData 结果包目录。
2. Workbench 校验清单摘要、全部声明文件、QC、批准记录和逐试样拉伸数据。
3. 为每个来源 `specimen_id` 人工填写对应的研究 `sample_id`。
4. 填写来自实验记录的拉伸方法版本和统计审核人，并明确批准本次纳入。
5. Workbench 生成冻结 T30 契约的四文件输入包，再调用 SteelStats `report` 和 `verify-report`。
6. 页面显示 SteelData QC、SteelStats 结果状态、综合质量状态和完整性复核，并可预览或下载 Markdown 报告。

方法版本必须采用 `method-id@MAJOR.MINOR.PATCH`，例如 `tensile-iso6892-1@1.0.0`。Workbench 不从文件名、列名或模型回答猜测方法版本，也不自动推断试样对应。

## 模块边界

SteelAI 不导入 `steelstats` Python 包，不共享虚拟环境，也不安装 SteelStats 的内部依赖。`steelstats_bridge.py` 只识别同级 `SteelStats/steelstats.module.json` 声明的固定 `report` 和 `verify-report` 命令，以参数列表且 `shell=False` 启动 SteelStats 自己的 Python。

调用环境会移除 `PYTHONPATH`、`PYTHONHOME`、OpenAI 和 DeepSeek API Key。T33 全流程不调用云模型。

Workbench 负责：

- 校验 SteelData 结果包并要求人工确认样品、方法和纳入决定。
- 把逐试样 YS、UTS 和伸长率转换为冻结 T30 输入契约。
- 保存本地统计输入包并展示最终质量状态。

SteelStats 负责：

- 独立验证统计单位、方法版本和人工决定。
- 计算 T31 描述统计和组级 QC。
- 发布并独立复核 T32 完整性绑定报告包。

## 写入与失败边界

统计输入保存于 `outputs/steelstats_inputs/`，报告保存于 `outputs/steelstats_reports/`；两者均由 Git 忽略。程序拒绝把任一输出目录放进 SteelData 结果包。

以下情况会关闭式失败，不产生可误认为成功的报告：

- SteelData 包不完整、摘要不一致或 QC 为 failed/needs_review。
- 存在合成包、未知领域、缺失数值、非法单位或未处理文件。
- 试样对应缺项、方法版本无效、审核人为空或由 Agent/system 代填。
- 同一物理试样在结果包中重复出现。
- SteelStats 模块缺失、超时、返回非 JSON、报告身份异常或复核失败。

失败不会修改 SteelData 源包、`data/processed/` 或原始观测列。输入与报告按内容标识安全复用；已有内容不一致时保留现场并拒绝覆盖。

## 验收证据

T33 自动测试覆盖无内部导入、固定子进程参数、环境变量隔离、人工决定、重复试样、输出越界、幂等复用、篡改不覆盖和错误分类。跨项目端到端测试实际调用同级 SteelStats 独立环境生成报告，并对调用前后的 SteelData 结果包逐文件 SHA-256 进行比较，确认没有回写。
