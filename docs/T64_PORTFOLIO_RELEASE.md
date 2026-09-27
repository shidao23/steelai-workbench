# T64 岗位作品集与公开发布包

T64 的目标是把 SteelAI Workbench、T62 公开真实钢板数据案例和 T63 流程评估整理成招聘者能够快速理解、运行和核验的公开材料。它不是增加一个新的科研算法，而是冻结“代码—测试—案例—限制—讲解”的一致版本。

## 当前状态

T64 已建立发布契约、能力—证据映射、双语入口、演示脚本、面试讲解清单和可追溯发布准备包。当前状态仍是 `needs_human`，因为以下事项必须由项目负责人完成：全新环境复现、T63 24 条真实测量、视频、技术报告初稿、许可证与隐私终审。

## T86 开源计算热力学探索（作品集资产）

- 单页中英总结：[T86 作品集总结：开源计算热力学探索](T86_PORTFOLIO_SUMMARY.md)。
- 状态：工程与作品集 `portfolio_exploration_complete`（已由负责人 **世道** 于 **2026-09-25**（Asia/Shanghai）签署，范围 `portfolio_engineering_acceptance_only`）；真实科研 `scientific_use_blocked_by_solver_stability`。
- 入口：**分析与报告 → 物理计算 → 页签「平衡相分数—温度（可选 · T86）」**，内含「区域 1 · 公开合成演示」与「区域 2 · 真实样品探索」。
- 公开合成演示可运行、可下载（Markdown/JSON/CSV），两次运行最大差 0.0；真实 B-DQ/R-DQ 计算保持阻断，不发布曲线、不形成材料结论。
- 负责人验收记录：`config/calphad_owner_acceptance_v1.0.json`（`responsible_person_id = 世道`，`decision_scope = portfolio_engineering_acceptance_only`），并登记于 `config/portfolio_acceptance_v1.0.json`。该签署**不构成**真实钢种计算审批或科研结论批准（`scientific_use_approved=false`、`real_sample_curves_published=false`、`materials_conclusion_approved=false`）。

## 一键准备发布包

双击项目根目录的 `Run_T64_Portfolio_Prep.cmd`，或者执行：

```powershell
.\.venv\Scripts\python.exe -B -m steelai.portfolio_release
```

只校验配置时执行：

```powershell
.\.venv\Scripts\python.exe -B -m steelai.portfolio_release --validate-config
```

输出位于 `outputs/portfolio_releases/<publication_id>/`，包含发布契约、机器校验结果、检查清单、Governance Manifest 和 COMPLETE 标记。该包是 `working_candidate`，不会自动进入作品集，也不会替代 GitHub Release。

## 对外展示顺序

1. 用 README 说明系统解决的问题和 AI 权限边界。
2. 用三分钟演示展示公开合成 T40 成功链路和未知单位失败关闭。
3. 用 T62 说明公开钢铁数据案例：固定划分、CPU 轻量模型、指标、失败分析和不能推出的结论。
4. 用 T60/T61 说明受治理的多智能体协作：固定角色、工具、人工关口和 A2A 任务信封。
5. 用 T63 说明价值评估方法；在实测前只展示评估设计，不展示虚构的效率提升。

## 能力—证据原则

每项简历表述都必须能链接到代码、测试或已验收文档。建议表述“实现了可追溯数据与 Agent 治理链路”“完成公开钢板缺陷分类案例”“建立同题人工、单智能体、多智能体评测”，避免表述成生产系统、冶金机制发现或已经证明的通用效率提升。

## 公开终审

- `python -m steelai.public_release_audit` 通过且无隐私发现。
- `python -m steelai.release_candidate` 通过。
- README、报告、视频和简历使用同一个 release 版本。
- 不包含真实实验原始文件、私人路径、密钥、模型权重、个人审批记录或未审阅 Agent 原文。
- T62 的 UCI 来源与 CC BY 4.0 署名保持可见。
