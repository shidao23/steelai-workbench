# T41 公开仓库候选内容

状态：**Done（候选包已完成，尚未发布）**

冻结日期：2026-09-08

## 交付内容

- 根目录 MIT `LICENSE`，第三方复用继续由 `THIRD_PARTY.md` 单独登记。
- README 测试、Python 与许可证徽章，以及主链路架构图。
- Windows、macOS、Linux 从零安装说明和明确的独立模块依赖。
- 已知限制与不能宣称的科学结论。
- `python -m steelai.public_release_audit` 公开候选审计及自动化回归测试。
- `.gitignore` 明确排除真实数据、运行结果、科研会话、密钥、模型环境与权重。

## 隐私与公开边界

审计只面向 Git 跟踪的候选内容，并会拦截：

- 用户目录或桌面目录的绝对路径；
- 常见 API 密钥、GitHub Token、AWS Key 和私钥头；
- `data/processed`、`data/index`、`outputs`、真实 intake 区、个人科研会话和事件日志；
- 常见密钥文件与模型权重后缀。

公开候选只保留源码、测试、合成示例、空白模板、示例配置、架构与验收文档。T40 截图和数值来自公开合成演示，不是实验真值或真实科研输出。

## 验收方式

```powershell
python -m steelai.public_release_audit
python -m steelai.public_workspace
python -m steelai.quality_gate
python -m unittest discover -s tests -v
```

`public_workspace` 只把仓库中已跟踪的公开合成夹具复制到被 Git 忽略的运行目录；目标存在且内容不同会拒绝覆盖。使用全新虚拟环境按 `docs/INSTALL.md` 安装主依赖并重跑以上检查。实际验收结果记录在 `project_log/CHANGELOG.md`。

## 发布决定

本任务只形成“可公开审查的候选包”。按照任务边界，没有创建远程仓库、没有执行 `git push`，也没有公开内部 Git 历史。是否发布仍由项目负责人另行决定。

T42“演示视频与面试讲解”和 T43“岗位反馈迭代记录”已由项目负责人决定不再实施，因此不属于本候选包的未完成项。
