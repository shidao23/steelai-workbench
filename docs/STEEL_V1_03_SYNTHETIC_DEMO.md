# STEEL-V1-03 · 公开合成案例演示（synthetic demo）

> 性质：STEEL-V1-03B 交付说明。这是一个**离线合成演示**：全部数据来自脚本内固定、可审查的合成输入；不含真实测量、不含文献核验、不调用云模型、不接 PAOS、不进入正式证据库。它不是科研报告，也不代表 STEEL-V1-02 通用分析链完成。

## 1. 一条命令运行（离线）

```
.\.venv\Scripts\python.exe -B .\scripts\demo_thermal_softening_case.py --output-root <演示输出根>
```

- `--output-root` 可选；缺省为 `outputs/synthetic_demo/thermal_softening_cases`（与正式证据库 `outputs/thermal_softening_cases` 物理分离）。**正式证据库永远不是合法的演示输出根**（CLI 与发布分支双重拒绝）。
- 输出（stdout，持续标注「合成演示 / 非科研结论」）：case_id、`verification: passed`、`reused: true|false`、演示根相对结果位置（`analysis_draft.md` / `evidence.json` / `manifest.json`）。
- 退出码：0 成功或复用；2 治理拒绝（包篡改 / 同 ID 异内容 / 输出根非法）；3 用法错误。
- 本批实测（2026-09-28，输出根指向会话临时目录）：两次运行均退出码 0，`case_id: TSC-B9F2D1C290BECF4FA6B9`，`verification: passed`，`reused: false → true`。

## 2. 数据流与治理分类

```
固定合成输入（脚本内 _SYNTHETIC_ROWS：2 个通过项 + 1 个待复核项，样品 B-DEMO / R-DEMO）
  → build_synthetic_demo_case()：case_id 由合成输入内容摘要派生（同输入恒同 ID）
  → publish_softening_case(..., synthetic_demo=True)   # 显式、默认关闭分支
      · 证据注入 evidence_class=synthetic_demo_data → 草稿页眉渲染「合成演示标记」
      · Manifest：state=needs_human、result_level=working_candidate（复用现有分类）、
        evidence_class=synthetic_demo_data；六个 source 全部 synthetic_demo_data /
        synthetic_demo_input——没有任何来源写成 human_approved 的真实科研数据
      · staging / seal / append-only 发布与正式路径共用，包格式不变
  → verify_package()（治理内核自己的独立复核）
```

草稿中的每个数值都可追溯到 `_SYNTHETIC_ROWS` 的固定行；合成包即使带格式正确的假摘要，草稿也明确「不代表已核验真实论文 PDF」。重复运行同输入只复用已验证包（`reused: true`，零重写）；同 ID 不同内容或包被篡改时明确失败、不覆盖。

## 3. 与正式路径的边界

| | 正式路径（默认） | 合成演示分支（`synthetic_demo=True`） |
| --- | --- | --- |
| 输入 | 真实已批准批次 + 真实文献 PDF 摘要绑定 | 脚本内固定合成行 |
| Manifest 分类 | `real_research_data` | `synthetic_demo_data` |
| 来源状态 | `human_approved` / `literature_digest_verified` / `method_approved` | 一律 `synthetic_demo_input` |
| 证据库 | `outputs/thermal_softening_cases` | 调用方演示根；禁止正式库 |

合成边界（STEEL-V1-03C 起）：

- 演示草稿**从页眉到结论**都只称固定合成输入：明确写「未运行 T75 曲线重算；没有已批准的正式结果；也没有真实文献 PDF 核验」，结论段不再出现「已复核数据 / 已批准正式结果 / 重新计算」类完成性表述。
- 演示输出根**等于或位于**正式证据库之内（含 `..`、符号链接/junction 归一化后的情形）一律拒绝，且零写。
- 合成包**不能**经科研受限引用接口（`build_case_reference` / export CLI）导出：接口读取**已验证 Manifest** 的 `evidence_class`，非 `real_research_data` 一律返回稳定受限错误码 `CASE_NOT_REAL_RESEARCH`（路径与正文不回显）。
- 案例若**已显式声明** `evidence_class=synthetic_demo_data`，而调用方省略或传入 `synthetic_demo=False`，发布入口在任何写盘前稳定拒绝（报错不含本机路径）；合成分类必须与显式 opt-in 一致，不会被静默纠正，也不落入默认真实分类分支。

正式路径默认行为不变（`synthetic_demo` 默认 `False`，测试 `test_formal_path_default_remains_real_research_data` 直接断言签名默认值与真实分类）。

## 4. 验收记录

- `pytest tests/test_demo_thermal_softening_case.py` → **8 passed**（退出码 0）。
- 三套件回归 `test_thermal_softening_case.py + test_thermal_softening_case_ref.py + test_demo_…` → **50 passed**（退出码 0，2026-09-28）。
- 验证状态：本演示链【本机可运行】（见 `STEEL_V1_01_CAPABILITY_GAP_AUDIT.md` §0/§5）；不代表 T70→T75 真实仪器全流程，真实科研结论仍需研究者按现有治理关口核对。
