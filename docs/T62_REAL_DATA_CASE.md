# T62 真实材料数据案例

T62 选择 UCI `Steel Plates Faults`（数据集 ID 198）作为第一套合法公开的真实工业钢铁案例。它包含 1941 条记录、27 个数值输入和 7 类钢板表面缺陷，适合普通个人电脑运行。该数据由 UCI 明确标注为 CC BY 4.0；项目固定 DOI、官方页面、下载地址、署名、ZIP 与内部文件 SHA-256。

## 为什么先选这一套

本案例直接服务于“钢铁 + 算法工程 + 科研可信链路”的作品方向，同时避开未经授权的企业数据和许可证边界不清的数据。它不是钢成分—性能模型，不能用于钢种或工艺推荐；其定位是第一个可公开、可重放、可审计的真实工业数据案例。

## 一键运行

在联网环境双击项目根目录的 `Run_T62_RealData_Case.cmd`，或执行：

```powershell
.\.venv\Scripts\python.exe -B -m steelai.real_data_case
```

若 UCI 下载临时不可用，可从官方页面下载 ZIP 后离线运行：

```powershell
.\.venv\Scripts\python.exe -B -m steelai.real_data_case --zip "下载文件的完整路径"
```

程序先核对固定 SHA-256，再在内存中读取数据。原始 ZIP 和 `Faults.NNA` 不会复制进仓库或结果包。结果写入 `outputs/real_data_cases/<publication_id>/`，重复运行相同数据和规则时幂等复用。

## 冻结实验规则

1. 研究问题固定为七类钢板表面缺陷分类，不临时改成更容易的二分类。
2. 每类内部按稳定 SHA-256 排序后划分 60% 训练、20% 验证、20% 测试。
3. 多数类预测作为简单基线。
4. 改进方法是训练集标准化后的距离加权 kNN；只用验证集在 `k = 3, 5, 7, 11` 中选择。
5. 测试集不参与模型选择。最终同时报告 accuracy、balanced accuracy 与 macro F1。
6. 结果包包含数据卡、获取收据、划分清单、预测、指标、模型卡、错误分析、中文案例报告和治理 Manifest。

## 科研与治理边界

- 结果是 `working_candidate`，技术完整性通过不等于科研结论通过。
- 数据没有板号/批次分组键，隐藏的采集组泄漏无法完全排除。
- 坐标、输送线和派生对数字段可能携带采集条件信息，不能解释成冶金机制。
- 数据没有成分、工艺、组织信息，禁止据此提出钢种、热处理或生产参数建议。
- 项目负责人单独验收并做披露审查前，结果不会进入正式证据或作品集。

## 官方来源

- UCI 数据页：https://archive.ics.uci.edu/dataset/198/steel+plates+faults
- DOI：https://doi.org/10.24432/C5J88N
- CC BY 4.0：https://creativecommons.org/licenses/by/4.0/

建议引用：Buscema, M., Terzi, S., & Tastle, W. (2010). *Steel Plates Faults*. UCI Machine Learning Repository. DOI: 10.24432/C5J88N.
