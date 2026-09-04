# SteelAI Workbench 隐私与版本边界

## 可以进入本地 Git 基线

应用源码、测试、合成示例、空白模板、示例配置、模型注册表、CI 配置和不含真实路径的文档可以进入本地提交。

## 必须保持未跟踪

| 内容 | 路径或模式 | 原因 |
| --- | --- | --- |
| 真实研究表与索引 | `data/processed/`、`data/index/` | 可能包含未公开数值、样品关系、原始文件名和路径 |
| 运行结果 | `outputs/`、`project_log/events.jsonl` | 报告、审计和事件可能含未公开研究信息 |
| 本机配置 | `config/settings.toml`、`.streamlit/secrets.toml` | 包含绝对路径或密钥；只跟踪示例配置 |
| 真实 intake 区 | `raw_data/`、`inbox*/`、`approved_mappings/`、`approved_v2/` | 包含原始输入、人工批准或字段映射 |
| DSH 本地状态 | `dsh_workspace/node_modules/`、`dsh_workspace/results/` | 本地依赖、会话和生成结果 |
| 凭据 | `.env*`、`*.key`、`*.pem`、`*.pfx`、`*.token`、`**/secrets.*` | API 密钥和身份凭据 |
| 模型环境与权重 | `model_lab/micro_sam/.venv-micro-sam/`、`cache/`、`wheels/`、`weights/`、常见权重扩展名 | 大文件，可能受许可证或数据来源限制 |

`data/examples/` 只允许明确标记的合成数据。新增示例必须先确认不包含真实样品编号、绝对路径或原始文件名。

## 提交前检查

```powershell
git status --short --ignored
git grep -n -I -E "(API[_-]?KEY|SECRET|TOKEN|D:/Desktop|D:\\\\Desktop)"
git diff --cached --name-only
```

发现真实路径、原始文件名、凭据、模型权重或未公开结果时停止提交。阶段零不创建远程仓库，也不执行 `git push`。
