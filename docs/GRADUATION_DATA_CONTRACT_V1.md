# 毕业主线数据契约 v1

契约：`SteelAI-Graduation-Core-v1.0`

状态：Frozen

范围：个人毕业作品的逐试样拉伸 YS、UTS、EL；不是钢铁企业主数据平台。

## 为什么单独冻结这一版

现有 `research_data_contract_v1.0.json` 继续服务当前 B/R 汇总表和长表入口。毕业主线 v1 增加一层更严格、可迁移的身份与来源关系，但本任务不自动改写旧表，也不把 T10 暂存提交到正式长表。

机器可读契约位于 `config/graduation_data_contract_v1.0.json`，公开合成示例位于 `data/examples/graduation_contract_v1/`。本地质量门禁会验证契约和示例图。

## 身份与来源关系

```text
material（材料设计/牌号）
  └─ heat（独立熔炼炉次，可未知）
       └─ sample（研究条件，不是统计重复）
            └─ specimen（物理试样）
                 └─ individual observation（一个量、一个值、一个单位）

report（来源报告/值副本） ───────────────┘

sample ── reported_mean / reported_sd / reported_min / reported_max
          （报告汇总，必须带 replicate_count，不能冒充 specimen）
```

核心身份含义：

| 字段 | 含义 | 禁止混用 |
| --- | --- | --- |
| `material_id` | 材料设计或牌号 | 不是炉次或试样 |
| `heat_id` | 已核实的独立熔炼炉次 | 未知时留空；不能由 `batch_id` 猜测 |
| `sample_id` | 跨表使用的研究条件 | 不是一个物理重复试样 |
| `specimen_id` | 一个物理测试试样 | 不能用报告、图像视场、曲线点或像素代替 |
| `report_id` | 一个来源报告或值副本 | 只提供来源，不参与重复数统计 |
| `observation_id` | 一个指标的一个记录值 | 三个性能指标是三条观测，不是三个试样 |

## 六张冻结核心表

| 表 | 主键 | 关键字段 | 关系 |
| --- | --- | --- | --- |
| `materials` | `material_id` | `material_name`, `material_status` | 材料设计根节点 |
| `heats` | `heat_id` | `material_id`, `heat_status` | 多炉次可属于一个材料 |
| `samples` | `sample_id` | `material_id`, `heat_id`, `condition_label` | 一个研究条件；炉次允许在未核实时留空 |
| `specimens` | `specimen_id` | `sample_id`, `specimen_type` | 多个物理试样可属于一个研究条件 |
| `reports` | `report_id` | `report_type`, `source_status`, `source_sha256` | 来源容器；真实文件仍在外部只读目录 |
| `observations` | `observation_id` | `report_id`, `subject_type`, `subject_id`, `quantity`, `value`, `unit`, `statistic_type`, `replicate_count`, `source_record_id`, `source_field` | 单值与来源、统计单位显式绑定 |

毕业 v1 只接收：

| quantity | unit |
| --- | --- |
| `ys_mpa` | `MPa` |
| `uts_mpa` | `MPa` |
| `elongation_pct` | `%` |

增加成分、冲击、硬度或其他量，必须通过受审查的契约次版本；改变身份、主键、统计含义或既有单位含义必须升主版本。

## 逐试样与报告汇总不可混用

- `subject_type=specimen`：`subject_id` 必须已登记在 `specimens`；`statistic_type` 只能是 `individual`；`replicate_count` 只能空白或 1。
- `subject_type=sample_summary`：`subject_id` 必须已登记在 `samples`；统计量必须显式为 `reported_mean`、`reported_sd`、`reported_min` 或 `reported_max`；`replicate_count` 必须为正整数。
- 每条观测必须关联已登记报告，并保留 `source_record_id` 与 `source_field`。观测的 `source_status` 必须与报告一致。
- 缺失保持空白，不填 0；校验失败不删除、不插补、不覆盖旧记录。

## 本版明确延期的对象

- 拉伸曲线是有序 `curve_series/curve_point`，不是一组独立试样，也不在本版自动反算 YS/UTS。
- SEM 或其他图像中的 `image_field`、分割对象不是独立试样。
- EBSD 像素嵌套于图中，绝不能按像素数扩大统计重复数。
- 报告本身、表格行数和测量指标数都不能代替物理试样数。

这些对象以后可有自己的版本化契约，但不得塞进 v1 的 specimen 观测表绕过边界。

## 从现有系统迁移

| 来源 | v1 迁移方式 | 当前动作 |
| --- | --- | --- |
| `property_observations.csv` | 先登记 specimen 和 report，再逐行保留 sample/specimen/property/value/unit/source status | 暂不自动迁移 |
| `properties.csv` 汇总宽表 | 每个非空指标转成 `sample_summary`，明确统计量和 n | 不制造 specimen 行 |
| SteelData tensile table | 一个来源 record 的 YS/UTS/EL 转成三条 specimen observation | 需要显式样品对应、试样登记和报告登记 |
| SteelData tensile curve | 进入未来曲线契约 | 不自动提取性能 |
| 图像与 EBSD | 进入未来图像/空间契约 | 视场、对象、像素保持嵌套 |

`batch_id` 只保留为来源/工艺信息，不能自动映射成 `heat_id`。真实迁移需要独立任务完成备份、映射复核、预检、逐值抽查和仅追加提交。

## 冻结与变更规则

- Major：身份含义、主键、subject/statistic 语义或既有单位含义变化。
- Minor：向后兼容的可选字段或经过审核的新 quantity。
- Patch：不改变校验行为的文字或合成示例修订。
- Frozen 不代表数据已迁移；它表示后续代码和数据必须引用明确版本，不能静默改变本契约。
