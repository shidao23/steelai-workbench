# T23：人工批准后的执行与接入

状态：Done。入口仍在“数据与物理 → 数据质量与扩展准备 → SteelData 标准化接入”，不新增页面。T23 把 T22 的单条 human 批准接到确定性执行，但保留正式科研数据的最后人工确认。

## 页面流程

一条建议批准后，Workbench 会把 suggestion ID 和已核对的 suggestion SHA-256 传给同级 SteelData 独立环境。若本次执行未完成，批准记录不会丢失；刷新并加载建议后可以查看状态、安全恢复或重试。已完成记录只会重新校验并载入原结果，不再运行一次。

载入的结果仍进入原有流程：

1. 校验 `manifest.json`、`COMPLETE` 和所有登记文件的 SHA-256；
2. 校验建议、human 批准、人工决定和系统执行请求之间的摘要绑定；
3. 显示 SteelData QC、逐试样记录与来源单元格；
4. 由用户逐个把 SteelData 物理试样对应到 Workbench `sample_id`，并选择真实来源状态；
5. 生成预检摘要，用户明确确认后才经过共用 append-only 闸门。

因此“批准后自动执行”只表示运行标准化管线，不表示自动写入科研长表。

## 完整审计链

Workbench 要求 T23 结果包额外包含并交叉核验：

- 实际执行的 suggestion 记录和独立摘要；
- 决定为 approved 的人工 review 记录及其 approval 记录摘要；
- 只含固定字段的 system execution request；
- suggestion、approval、review、source 共同导出的幂等键和 attempt；
- manifest 中的结果引用以及所有审计文件摘要。

仅重新计算外层文件清单不能掩盖内部审批决定或绑定被更改；审计链任一环不一致，结果不会进入映射预览。

## 重复与失败边界

SteelData 以单建议锁避免并发执行，并用同一内容链的幂等键复用完成结果。中断的 attempt 不会产生可消费的 `COMPLETE`；重试使用新 attempt，不覆盖旧结果。

Workbench 的入库闸门还按 SteelData 来源单元格身份阻止重复导入，所以把同一结果重新对应到另一个 `sample_id` 也不能重复写入。若目标主键已存在，仍然关闭式失败，绝不覆盖旧记录。

Agent/DSH 没有审批或执行工具，Agent 回复不能作为 `source_status` 或实验数据来源。允许的真实来源状态仍是 `instrument_export`、`verified_from_source` 和 `manual_extraction_verified`。

## 验收

测试覆盖固定 CLI 参数、批准后页面编排、审计链通过、篡改后拒绝、来源身份去重、主键不覆盖和原有结果闸门。Workbench 全量结果为 128 项通过，3 项既有环境条件测试跳过；SteelData 全量结果为 76 项通过。
