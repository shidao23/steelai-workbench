# SteelData → SteelAI：双入口，共用入库闸门

版本：宿主适配器 1.0 / SteelData 结果契约 1 / 对接模块 0.2.0。

## 为什么保留原来的 part

旧入口解决“格式已经符合 SteelAI 模板，是否允许进入研究数据集”的问题；SteelData 解决“仪器表的字段、单位、布局如何整理和检查”的问题。两者不是替代关系。

```text
已整理好的标准 CSV ─────────────────────┐
                                       ↓
原始 CSV/TSV/XLSX → SteelData → 结果校验 → 显式样品对应 → 共用入库闸门
                                                  ↓
                                      人工确认 → 仅追加长表 + 审计
```

现有五类手工模板不删除。UI 改名为“标准表导入”，旁边新增“SteelData 标准化接入”，侧栏不增加页面。

## 第一次怎么操作

1. 启动/刷新 SteelAI，进入“数据与物理 → 数据质量与扩展准备 → SteelData 标准化接入”。
2. 选择“合成演示（禁止入库）”，点击“运行合成演示”。后台调用同级 SteelData 自己的 `.venv`，无需激活环境或填写 API Key。
3. 看到 5 个文件、43 条记录和 QC 事项。演示里的 `partial`、`failed` 是预设坏数据；“确认接入性能长表”应禁用。
4. 也可以选择“读取已有结果包”，填写含 `manifest.json` 和 `COMPLETE` 的整个运行目录，而不是 HTML 文件路径。旧版 `master.xlsx` 或仅一个 CSV 不是 v0.2 结果包。

真实数据接入：

1. 在 SteelData 准备只含本批数据的输入目录和已人工批准的 v0.2 JSON。旧 DSH/旧 `approved_mappings` 不会自动升级；不要把旧映射当作新批准记录。
2. 用“运行原始数据批次 → 选择文件（可多选/拖拽）”，点选本批 `.xlsx` / `.csv` / `.tsv` 文件，再点选已人工批准的 v0.2 JSON；也可切回“填写文件夹路径”。确认允许在 SteelData 结果包中保存原始文件快照，再点击运行。
3. 等待处理。固定输出为同级 SteelData 的 `output/steelai_runs/`；合成演示是 `output/steelai_demo/`。选取模式只处理选中的文件，浏览器将内容传给本机服务，运行期间写入独立临时目录，正常完成或报错后清理；真实原文件不修改、不发给云端 AI。程序异常中断时临时目录可能残留。
4. 批次全部处理成功且 QC 为 `passed` 或 `warning` 才进入对应与预检环节。坏数据要回到源记录/批准模板处理后重跑，不在 SteelAI 里改掉报错值。
5. 为每个“来源文件 + specimen_id”明确选择 SteelAI `sample_id`。默认留空，不猜 B/R；当前仍只允许登记过的 `B-DQ`、`R-DQ`。
6. 选择真实来源状态，查看展开后的全部观测和警告，填写审核人、审核说明并勾选确认。
7. 点击“确认接入性能长表”。提交时重新读取结果、校验摘要、重建观测，再在共用写入锁内重做当前数据库检查，最终仅追加。

`instrument_export` 表示仪器导出来源，不代表人工认证；`verified_from_source` / `manual_extraction_verified` 只有实际做过核对才能选。标准化不是来源核验，也不证明试样独立性。

选取文件限制：实验文件单个 ≤20 MiB，最多 1000 个、合计 ≤100 MiB；批准 JSON 单个 ≤2 MiB，最多 40 个、合计 ≤8 MiB。同名文件（不区分大小写）会拦截，不覆盖或自动改名。旧 `.xls` 需先另存为 `.xlsx`。普通 profile 或演示批准不能代替 human 批准；上传批准文件不会重新批准或修改其内容。切换输入方式、改选文件或路径，会清除上次的运行确认。

这是现有 SteelAI 内的 SteelData 入口；独立 SteelData 的静态 HTML 报告仍只读，没有给报告本身添加上传功能。

## 本轮接入到哪里

| SteelData 逐试样字段 | SteelAI property | unit |
| --- | --- | --- |
| ys_mpa | ys_mpa | MPa |
| uts_mpa | uts_mpa | MPa |
| el_pct | elongation_pct | % |

例如一个真实试样有 YS=950、UTS=1250、EL=12，则形成三条不同指标的观测，不是三个平行样。数值在桥接层不再换单位；单位必须由 SteelData 明确标准化。

目标是 `data/processed/property_observations.csv`。保留真实 `specimen_id`、用户确认的 `sample_id`、来源状态，并在 `notes` 存储稳定的来源指纹。批次/工艺及逐单元格来源另存审计，不把仪器 batch_id 自动当成统计独立重复组。

成功后 `outputs/data_intake/DI-.../` 包含：

- `normalized_staging.csv`：本次规范观测。
- `validation_manifest.json`：SteelAI 契约预检。
- `steeldata_provenance.json`：输入结果摘要、批准摘要、样品对应、审核信息、原文件摘要、sheet/单元格、标准 record_id。
- `commit_result.json`：追加数量和提交状态；提交前失败时标记 `not_committed`。

原始文件只保留在 SteelData 自己的结果包里。请保留该结果包，否则 SteelAI 的来源索引无法恢复原始内容。审计里有本地路径，只用于本地追溯，不发送给 Agent，不应直接公开到 GitHub。

## 哪些事情故意没有自动做

- 不更新 `properties.csv` 或 `composition.csv` 等已有摘要。因此旧 B/R 比较、Physics 和研究 Agent 不会因为导入观测就静默改变结果。要让它们消费新长表，需要另一个明确、可复现、经确认的汇总步骤。
- 不把成分报告里的 individual / reported_mean / reported_sd 混作独立观测；不把 `<0.001` 变成 0 或精确浓度；不把 atomic % 当 wt.%。
- 不从力—时间曲线凭空推断 YS/UTS。曲线只有结果预览；提取性能还需要试样尺寸、应变定义、判据和验证。
- 不放开 T200 或 1–14 号实验，不改研究范围，不自动建立真实试样身份。
- 不删除缺失/异常/重复值来“让数据通过”，不做均值/标准差，不宣称统计显著。
- 不接通 DSH 写工具、不自动批准 profile、不发送原始实验数据给云端模型。

混合领域批次采用整批阻断导入策略：不会自动挑出看似干净的部分。当确实需要只接入拉伸时，明确分成独立的拉伸批次再运行，保留拆分依据。

## 代码分工

- `steelai/steeldata_bridge.py`：模块客户端、结果契约检查、拉伸宽转长、样品对应、来源审计和重新确认后的提交。
- `steelai/views/steeldata_panel.py`：新入口表单，只编排用户动作，不执行上传结果中的 HTML/脚本。
- `steelai/views/data_quality_panel.py`：承载旧入口和新入口，共用现有页面。
- `steelai/data_intake.py`：两路共用的规范列、主键、样品登记、有限数值和写入检查。新增提交重检/写入锁和来源重复检查。
- 同级 `SteelData/steeldata/`：独立的数据适配、pyjanitor 整理、Pint 单位转换、Pandera QC、结果打包。不依赖 SteelAI。

宿主通过 `subprocess.run([python, '-B', '-m', 'steeldata', ...], shell=False)` 调用明确 CLI，180 秒超时。两套 Python 环境不混装依赖。默认同级目录自动发现，不暴露任意可执行文件配置。

宿主使用标准库按结果契约检查 COMPLETE、manifest、所有声明的文件 SHA-256、批准摘要和数据集一致性，无需在 SteelAI 中导入 SteelData。检查不是数字签名或操作系统沙箱，不能防止有本地写权限的人同时伪造整个包。宿主在提交时重新检查，不能仅信任之前的网页预览。

共用锁协调本应用的并发导入，不约束外部 Excel/脚本编辑。`.intake.lock` 若因进程崩溃残留，应先确认没有运行中的导入，再由人工恢复；不要在不明状态下删除锁。数据表原子替换，但 CSV、审计和事件日志不是跨文件数据库事务。

## 后续如何以小项目支撑 SteelAI

先实现一个领域的小项目及独立测试 → 定义带版本的输入/结果契约 → 编写宿主适配器 → 通过共用科学数据闸门 → 再选择后续分析模块。无需把所有模块源码合到 SteelAI，也不需要现在就建设通用插件平台。

优先下一步：以一份真实、脱敏拉伸批次验证映射与来源；然后再规划独立的统计汇总模块。成分需要能表达报告统计量、检出限、质量/原子基准的契约；曲线需要信号/试样几何接口。二者不能仅增加一个 CSV 列名映射就算完成。

求职时可以准确描述：设计并实现独立材料数据标准化模块与科研工作台的契约式集成，保留人工审批、质量拦截和逐单元格来源追溯。不要描述为“AI 自动认定实验结果可信”。
