# T20：Workbench DSH 接入 SteelData v0.2 预览

状态：Done。代码、公开注册示例、迁移测试和本机补丁切换均已完成；迁移前 SteelData 补丁保留为本机回滚文件。

后续状态：T21 已在不改变本页 T20 验收边界的前提下新增建议元数据工具，并把当前 DSH 配置切到 suggest 模式。pre-T21 补丁仍可恢复本页的三工具 preview 模式。

Workbench 原有 `mcp__steelai__*` 七个科研只读工具保持不变。T20 在 DSH 隔离工作区增加独立的 `steeldata_v2` 服务注册示例，它使用 SteelData 自己的 Python 环境和 `--mode preview`，不把 SteelData 安装进 Workbench 环境。

DSH 可见的 SteelData 工具严格为：

- `status`：确认 preview 模式和无写权限；
- `list_inputs`：最多返回 1000 个 `inbox_v2` 相对文件名；
- `preview_profile`：调用 v0.2 确定性核心，只返回数量、问题代码和摘要。

不提供 profile 审批、结果入库、批次执行、删除或任意 Shell 工具。映射提案持久化、审批 UI 和获准执行分别留给 T21、T22、T23。

本机已把 `dsh_workspace/.dsh/cordis.patch.example.yml` 中的 `mcp-steeldata-v02-preview` 结构加入被忽略的补丁，并通过 DSH `--dump-config` 解析。若后续握手或工具目录不符，停止 DSH 并恢复迁移前补丁；现有 SteelAI 只读桥和确定性 CLI 不受影响。
