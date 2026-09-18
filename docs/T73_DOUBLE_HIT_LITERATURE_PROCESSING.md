# T73 Double-hit 文献口径曲线处理

## 目标

把 T71 已入库的热模拟仪器点和 T72 公式曲线，转换成可用于后续 double-hit 软化分析的“有效加载段建议”。整个过程只读取标准化表，不修改原始 `ZHT.A*` 文件，也不覆盖已入库 Force、Stroke 或公式全路径结果。

## 文献通行口径

- 两次压缩分别使用从本道次接触点起算的局部真应变；累计真应变同时保留，避免丢失几何历史。
- 后续软化率采用 `X=(sigma_m-sigma_2)/(sigma_m-sigma_1)`。
- `sigma_1`、`sigma_2` 采用 0.2% 偏移屈服应力，`sigma_m` 取第一道次结束时的流动应力。
- 0.2% 偏移法是常用机械法，但不同偏移量、平均流动应力法、回推法等会产生不同结果，因此不能把机械软化率无条件等同于金相再结晶体积分数。

依据登记在 `config/thermal_double_hit_processing_v1.0.json`，包括 DOI 与来源链接。主要参考：

1. Tamanna et al., *Effect of Sample Geometry on Strain Uniformity and Double Hit Compression Tests for Softening Kinetics Determination*, DOI `10.1002/srin.202200157`。
2. *Study of Static Recrystallization Kinetics and the Evolution of Austenite Grain Size by Dynamic Recrystallization Refinement of an Eutectoid Steel*, DOI `10.3390/met9121289`。
3. *Metadynamic Recrystallization in the Isothermal Double Compression of CP800 Steel*, DOI `10.3390/ma18071549`。

## SteelAI 版本化分段规则

文献并不存在适用于所有仪器的统一“Force 达到多少就算接触”阈值。T73 因此明确把自动接触识别标成项目规则，而不是文献标准：

1. 每个 interval 的前 10% 点估计空载基线，最少 20 点、最多 40 点。
2. 接触阈值取“峰值力增量的 2%”与“基线噪声 6 倍 MAD”中的较大者。
3. 连续 5 点超过阈值才形成接触点候选。
4. 有效加载终点取卸载前第一次达到最大 Stroke 的点。
5. 分析应力使用基线修正 Force；原公式应力另列保存。
6. 每道次局部真应变在候选接触点归零；不做平滑、摩擦修正或绝热升温修正。

这些阈值均在配置中版本化，未来更改必须产生新规则版本，不能静默改写既有结果。

## 当前真实批次结果

已对 16 个 DH 采集（A75–A91 中属于 DH 的记录）完成自动预跑，共识别 32 个有效加载段候选；每个采集均识别出两道次，局部最大真应变约为 0.231–0.278。所有候选状态均为 `suggested_needs_human`。

界面默认显示文献分析视图，可切换回公式全路径；还可查看每道次接触点、加载终点、基线力和局部最大真应变，并下载候选段 CSV。

## 边界与下一步

T73 不输出正式软化率。下一步必须先目视复核 32 个候选段；之后才能实现 0.2% 偏移拟合、拟合区间诊断、软化率不确定性与人工批准。曲线形状、试样摩擦和温升造成的系统误差仍需在论文方法与局限中披露。
