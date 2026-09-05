# T14 Frictionless 可选适配器

T14 只接入 Frictionless `5.19.0` 的一个小功能：为 graduation-v1 公开合成数据生成标准 Tabular Data Package 描述，并做独立结构校验。SteelAI 自己的数据契约、科研规则、QC、来源和入库门禁仍是权威规则。

## 使用方式

在 Workbench 根目录执行：

```powershell
.\.venv\Scripts\python.exe -m venv .venv-frictionless
.\.venv-frictionless\Scripts\python.exe -m pip install --require-hashes -r requirements-frictionless-win-py312.lock
.\.venv-frictionless\Scripts\python.exe -m steelai.frictionless_adapter
```

命令只读取 `data/examples/graduation_contract_v1` 中以 `SYN-` 标识的公开合成表，在本机生成/校验 `datapackage.json`，不调用网络服务、不上传数据。锁文件仅面向 CPython 3.12 Windows x64。

不安装 Frictionless 时，同一命令会报告 `unavailable`；原有质量门禁和主测试仍可运行，主 `requirements.txt` 没有改变。

## 收益与成本

| 项目 | 实测结果 |
| --- | --- |
| 标准化收益 | 6 张 CSV 获得统一资源、字段类型、主键和普通外键描述，可被 Data Package 工具读取 |
| 科研边界 | `subject_id` 的按类型关联、单位/统计/来源规则继续由原生契约校验，不交给通用库猜测 |
| 依赖 | 共 40 个安装包，其中 39 个为传递依赖、19 个是 Frictionless 直接依赖 |
| 下载体积 | 40 个 wheel 合计 8,361,624 bytes |
| 隔离环境体积 | 54,926,137 bytes（包含环境基础文件） |
| 原生校验 | 30 次中位数 1.691 ms |
| 适配器端到端 | 30 次中位数 36.033 ms；增加 34.342 ms，约 21.31 倍 |

对这个很小的演示包，绝对增加时间约 34 ms，可接受；依赖数量明显偏多，因此只保留为答辩时可选的互操作演示，不进入日常核心运行。

## 完整性与许可证

- Frictionless wheel SHA-256：`81436b94a950b1a5cf83e953921e64dc888c00f51400f783ea0aa824319a6d67`
- 每个直接和传递依赖均在 `requirements-frictionless-win-py312.lock` 中固定版本及 wheel 哈希。
- MIT 许可证副本和来源记录位于 `third_party/frictionless-5.19.0/`。
- 第一次集成测试捕获并修正了资源缺少 `tabular-data-resource` profile 的问题；修正后独立校验通过。

## 移除方法

1. 删除本机 `.venv-frictionless` 隔离环境。
2. 删除 `steelai/frictionless_adapter.py`、对应测试、`datapackage.json`、可选锁文件和 T14 许可证/评估记录。
3. 无需迁移数据、修改 `requirements.txt` 或更改原生质量门禁；关闭状态测试已经覆盖这条路径。

T14 不包含真实科研数据，也没有把第三方完整系统、界面或源代码复制进仓库。
