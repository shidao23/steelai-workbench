# 第三方开源复用登记

登记版本：`SteelAI-ThirdParty-Candidates-v1.0`

核对日期：2026-09-05

任务：T13（只做调研与决策，不安装、不复制代码）

机器可读登记位于 `config/third_party_candidates_v1.0.json`，并由本地质量门禁检查。

## 复用政策

- 只有官方仓库、明确 OSI 开源许可证和固定版本/源码引用都已核对的候选，才可进入实现评估。
- 未知许可证、无许可证、仅“source available”或非开源实现一律不复制。
- 真正引入时必须固定精确版本，保留许可证、版权及 NOTICE 要求，并记录直接/传递依赖。
- 外部能力只能作为可关闭适配器；禁用后 SteelAI/SteelData 核心流程仍须运行。
- T13 不授权上传科研数据、连接外部服务、改变科学规则或执行真实数据迁移。
- 项目功能相似不代表可以照搬界面、文档或实现；概念借鉴与代码复用分别记录。

## 候选矩阵

| 候选小功能 | 官方版本与源码 | 许可证 | 本机/依赖成本 | 决策 |
| --- | --- | --- | --- | --- |
| Frictionless Data Package 描述与独立验证报告 | `frictionless-py 5.19.0`, `43a63e0` | MIT | 支持 Python 3.14；依赖规模待 T14 实测 | **进入 T14 评估**，仅做可选公开导出适配器 |
| NOMAD 材料 schema / ELN / FAIR 工作流概念 | `NOMAD 1.4.3`, `0e2fecd` | Apache-2.0 | 完整平台需要数据库、搜索、Worker 和 Web 部署 | 仅作架构参考，不部署、不复制 |
| GEMD 材料—工艺—测量关系导出 | `gemd-python 2.2.4`, `af4336f` | Apache-2.0 | 中等；与 graduation-v1 身份模型重叠 | 延后，出现真实互操作需求再评估 |
| Great Expectations 验证文档/规则集 | `1.21.0`, `eb0faa5…` | Apache-2.0 | 官方 PyPI 要求 Python `<3.14`，且与现有 QC 重复 | 当前拒绝 |
| MLflow 运行/产物追踪 | `3.16.0`, `998f710` | Apache-2.0 | 新增追踪运行时和存储模型；当前 manifest 已够用 | 延后到实验规模明显增长后 |

## T14 唯一入选项

候选：`frictionless-data-package`。

只允许评估以下最小功能：从 graduation-v1 的公开合成表生成标准 Data Package 描述，并用独立验证报告校验包结构。它不能替代现有 Python 契约、QC、人工批准或入库门禁。

T14 的继续条件：

1. 在隔离环境验证 Python 3.14 安装与实际传递依赖数量。
2. 固定 `frictionless==5.19.0` 和安装包哈希，保存 MIT 许可证/归属记录。
3. 只使用 `SYN-` 合成示例做测试，不把真实数据发往网络。
4. 对比“无适配器”和“有适配器”的可移植性收益、运行时间与维护成本。
5. 关闭或未安装该组件时，核心质量门禁与毕业演示仍正常工作。

T13 不等于批准 T14 实施；这里只确定唯一、边界明确的候选。

## 官方核对链接

- Frictionless：[仓库](https://github.com/frictionlessdata/frictionless-py)、[v5.19.0](https://github.com/frictionlessdata/frictionless-py/releases/tag/v5.19.0)、[MIT License](https://github.com/frictionlessdata/frictionless-py/blob/v5.19.0/LICENSE.md)、[PyPI](https://pypi.org/project/frictionless/5.19.0/)
- NOMAD：[仓库](https://github.com/FAIRmat-NFDI/nomad)、[v1.4.3](https://github.com/FAIRmat-NFDI/nomad/releases/tag/v1.4.3)、[Apache-2.0 License](https://github.com/FAIRmat-NFDI/nomad/blob/v1.4.3/LICENSE)、[官方文档](https://docs.nomad-lab.eu/1.4.3/)
- GEMD：[仓库](https://github.com/CitrineInformatics/gemd-python)、[v2.2.4](https://github.com/CitrineInformatics/gemd-python/releases/tag/v2.2.4)、[Apache-2.0 License](https://github.com/CitrineInformatics/gemd-python/blob/v2.2.4/LICENSE)
- Great Expectations：[仓库](https://github.com/fivetran/great_expectations)、[1.21.0](https://github.com/fivetran/great_expectations/releases/tag/1.21.0)、[Apache-2.0 License](https://github.com/fivetran/great_expectations/blob/1.21.0/LICENSE)、[PyPI](https://pypi.org/project/great-expectations/1.21.0/)
- MLflow：[仓库](https://github.com/mlflow/mlflow)、[v3.16.0](https://github.com/mlflow/mlflow/releases/tag/v3.16.0)、[Apache-2.0 License](https://github.com/mlflow/mlflow/blob/v3.16.0/LICENSE.txt)、[PyPI](https://pypi.org/project/mlflow/3.16.0/)

后续重新评估时必须更新核对日期和固定引用，不能把这里记录的版本自动解释成“永远最新”。
