# SteelAI × DeepSeek Harness 旁路工作区

此目录是 DSH 的隔离工作区，不存放原始实验文件或 processed 表。DSH 通过本地
stdio MCP 子进程调用 SteelAI 已审计的结构化只读工具。

## 启动

推荐双击 SteelAI 项目根目录的 `Start_SteelAI_DSH.cmd`。也可以在本目录运行：

```powershell
npm install --no-audit --no-fund
Copy-Item .\.dsh\cordis.patch.example.yml .\.dsh\cordis.patch.yml
# 只在被 Git 忽略的 cordis.patch.yml 中填写本机路径
.\node_modules\.bin\dsh.cmd --profile web --patch .\.dsh\cordis.patch.yml
```

`package.json` 将 DSH 固定为已验证的 `0.1.1-rc.2`。升级开发者预览版前应先运行
SteelAI 全量测试与 MCP 握手测试，确认补丁结构没有发生破坏性变化。

启动脚本会把新会话默认权限设为 `read-only`；不要切换到
`danger-full-access`。首次启动后先询问：

```text
调用 SteelAI bridge status，并列出当前样品；不要读取任何文件。
```

正常情况下会出现 `mcp__steelai__*` 工具，且 bridge status 显示：

- `mode = read_only_structured_data`
- `writes_allowed = false`
- `raw_files_allowed = false`
- `api_key_required = false`

## 数据边界

- MCP 子进程不会接收或读取 DeepSeek API Key。
- 工具参数不接受路径；输出会再次拦截绝对路径及 CTF/TIF/TIFF 文件名。
- SteelAI 原始数据、processed 数据和既有输出均不允许 DSH 直接修改。
- `results/` 仅用于 DSH 按用户要求生成的旁路笔记，不是科研主数据。

`.dsh/cordis.patch.yml` 包含本机项目和可选 composition MCP 的绝对路径，因此被 Git 忽略；仓库只保留占位示例。若移动项目，只修改本机补丁中的 `command`、`args` 和 `cwd`。
