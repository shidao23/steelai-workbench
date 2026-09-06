# T21 映射建议契约与人机状态边界

状态：Done。Workbench DSH 继续保留原有科研只读桥，并把 SteelData 服务从 T20 的纯预览模式升级为 T21 suggest 模式。

DSH 当前可使用四个 SteelData 工具：status、list_inputs、preview_profile、submit_mapping_suggestion。前三个保持 T20 行为；第四个只能保存一份结构化建议元数据，不能创建审批、启动运行或写入 Workbench 长表。

建议必须明确携带来源相对路径和哈希、domain、完整 v0.2 profile、逐字段 source/target/dtype/单位/证据/置信度/备选项，以及单独的 uncertainties。未知实验类型必须保持 domain=null 并进入 unsupported，不能勉强套用已有 profile。

服务器自动选择初始状态：完整无歧义建议为 candidate，有 uncertainty 为 needs_human，未知 domain 为 unsupported。Agent 无权提供 status、批准人或执行参数，也不能调用状态转换。T22 的 Workbench 人工界面将读取内容哈希和修订号后处理 approved/rejected；T23 才消费 approved 记录。

本机 DSH 补丁已切到 `--mode suggest` 并通过配置解析。回滚时恢复被 Git 忽略的 `cordis.patch.pre-t21.yml`，即可回到 T20 三工具预览模式；已保存建议保持本地且不会自动执行。
