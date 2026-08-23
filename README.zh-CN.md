# SteelAI Workbench 中文说明

**[在线公开演示](https://steelai-workbench.streamlit.app/)** · [English README](README.md)

SteelAI Workbench 是一个面向耐磨钢研究的本地科研 AI 工作台，将成分—工艺—组织—性能数据、经验物理公式、SEM/EBSD 分析、证据校验和研究报告串成可追溯流程。

## 公开版说明

- 仓库中的 B-DQ/R-DQ 数据全部为合成演示数据。
- 不包含真实实验数据、原始图片、CTF/TIF、本地路径、论文原文或 API Key。
- DeepSeek、MATLAB/MTEX 和 GPU 模型在公开演示中关闭。
- 当前演示结论只说明系统能力，不代表真实材料结论。

## 主要能力

1. 样品、成分、工艺、组织、性能的结构化浏览和 B/R 对比。
2. Ms、Ac1、Ac3、Tnr、Ceq、Pcm 经验公式及适用范围警告。
3. 成分—工艺—组织—性能—物理观测数据契约和安全导入闸门。
4. 只读 Research Agent、25题固定评测和隐私阻断。
5. MTEX-EBSD 与 micro-SAM 的隔离式模型适配架构。
6. 证据等级、允许/禁止表述、Run Manifest 和求职作品集沉淀。

## 科学边界

- 空白不等于零。
- 经验模型估算不等于实验真值。
- 视场和分割对象不能冒充独立试样。
- 不同 EBSD 采集尺度不能直接合并。
- 当前公开 B/R 数据只用于软件演示。

运行和测试方法见英文主页 [README](README.md)。
