# SteelData 集成验证记录

日期：2026-09-03。本轮只接入拉伸逐试样数据，不迁移真实数据，不修改 DSH。

## 验证结果

- SteelAI 全量离线测试：96 项，95 通过、1 跳过，24.738 秒。
- 唯一跳过：旧 `WearSteel-AI v0.1` 路径未配置的适配测试，与本次接入无关。
- 全量测试包含已启用的跨环境端到端测试：在临时目录里创建明确合成的 3 个试样，经真实 SteelData CLI 的 profile / approve / run / verify 协议，得到 9 条标准观测，通过 SteelAI 闸门追加到临时长表；重复提交被拒绝，原测试输入 SHA-256 不变。
- 为测试真实运行分支，自动化测试在临时目录使用 `kind=human` 格式的测试批准；审核人明确写为 automated-test，不代表真实人工审批。测试数据、批准和结果在测试结束后全部随临时目录移除，不进入真实项目。
- SteelData 独立项目原有测试：51/51 通过，10.109 秒。
- SteelAI 科学/模型/会话/Agent/隐私五项质量门禁全部通过。
- Streamlit AppTest 覆盖全部既有页面、新旧导入标签、新入口只读初始状态、合成结果禁用提交、正常结果展示对应表；本轮未用浏览器做像素级截图验证。
- 不安装新依赖：SteelAI Python 3.12.13，SteelData Python 3.14.2，使用各自已有 `.venv`。

另外实际从 SteelAI 客户端调用合成演示，保留一个可查看结果包：

`<SteelData项目目录>\output\steelai_demo\run-...`

5 文件、4 数据集、43 记录、15 问题；整体 partial / QC failed，synthetic=true，宿主正确拒绝真实入库。

## 真实数据未改动

测试前后，SteelAI 的 `data/processed/` 文件清单和 SHA-256 完全一致，仍只有以下五张原表，没有创建真实 `property_observations.csv`：

| 文件 | SHA-256 |
| --- | --- |
| composition.csv | B1CEF462821392288B24B4D781A713ECE246A3CB6E448C42B36DDB2C21BBBE5F |
| microstructure.csv | BFAB952C921C5811749A0EC9D50932EA717F8F83C1D128C2CBD35DCE366DA315 |
| process.csv | D96072FFE812F9EFA5DF7DFE24092A185CBE72648719647A3F6F6E25325B2047 |
| properties.csv | B8A362D63876610F6A5F35C9A73960E54391864A1D3F9FB91AA684F0E4D59AA9 |
| samples.csv | A8FC4169B234854DC52C6AB3EF791FE1B9741501D192ED0F6F23D0977DC11EDA |

原 SteelAI 的 README、data_intake.py、data_quality_panel.py 在修改前保存在：

`<SteelAI项目目录>\outputs\integration_backups\steeldata-v1-...`

## 可复现命令

在 PowerShell：

```powershell
Set-Location <SteelAI项目目录>
$env:PYTHONUTF8='1'
$env:STEELDATA_E2E='1'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m steelai.quality_gate
```

不设置 `STEELDATA_E2E=1` 时，跨项目测试默认跳过，SteelAI 的常规测试不要求安装同级 SteelData。

本地尚未以用户的真实实验批次完成入库验收。测试证明约定输入和坏数据样例下的程序行为，不证明仪器数据可靠、试样独立或研究结论成立。
