# Milestones

## 2026-08-19 · Validation-first data intake gate completed

- SteelAI now has a controlled route from researcher-filled CSV templates to validated processed ledgers without copying or editing raw source files.
- The workbench distinguishes real specimens, nested image fields, observations and model runs before new values can enter the research dataset.
- Missing values, duplicate keys, B/R scope violations, orphan samples, unknown columns and invalid measurement types are blocked before writing.
- Accepted data are append-only and create a normalized staging table, validation manifest, commit result and project event suitable for reproducibility and portfolio evidence.
- The workspace suite passed 54 tests; formal-directory validation remains the deployment gate.

## 2026-08-19 · Extensible research data contract and CI gate completed

- SteelAI now validates the composition-process-microstructure-property-physics chain without treating blank cells as zero or model estimates as measurements.
- The current B/R tables pass structural validation, while process detail, microstructure metrics, specimen-level properties and experimental physics calibration remain explicitly incomplete.
- Optional long-form ledgers provide a stable route for future rolling passes, fields of view, independent specimens, thermodynamic/kinetic models and experimental residuals.
- A local GitHub Actions workflow can run the deterministic quality gate and full offline suite against synthetic fixtures; no repository was created and no research data was uploaded.
- The workspace suite passed 49 tests; formal-directory validation is the deployment gate.

## 2026-08-19 · First live Agent baseline and observability layer completed

- DeepSeek V4 Flash completed DATA-001, PHYS-004 and PRIV-001 with a 100% deterministic smoke-test pass rate; the result is explicitly not treated as full-benchmark reliability.
- The verified run `AE-20260819-004349-e5f5d9` recorded 23,316 tokens and 7.9 s mean latency, and blocked the synthetic local-path case before any API request.
- SteelAI now tracks evaluation history, common-case regressions, latency, Token use and sanitized tool spans in the existing six-area interface.
- Trace exports contain no question, answer, tool arguments, local paths or raw files, preserving the established DeepSeek privacy boundary.
- The workspace suite passed 44 tests; formal-directory validation is the deployment gate.

## 2026-08-18 · B/R Evidence & Validation Center implemented

- SteelAI can now turn the current B/R mechanics, Physics, dual-scale EBSD and AutoDimple outputs into a deterministic evidence registry and claim validation matrix.
- The system distinguishes supported-with-caveat statements, directional consistency, conflicting evidence, unconfirmed image differences and unsupported causal claims.
- Six scientific gates are machine-readable and available to the Research Agent through a path-free read-only tool.
- The implementation passed 30 automated tests in the workspace; formal-workbench validation is the deployment gate.

## 2026-08-17 · Auditable Research Agent v0.1 integrated

- SteelAI gained one bounded research coordinator that can assemble evidence from the existing deterministic modules through a strict read-only tool whitelist.
- The workbench exposes model readiness, permitted tools, per-run tool trace and an explicit evidence-save action.
- The implementation is offline-safe and does not alter the raw-data source of truth; live model validation remains pending until a local API key is configured.
- This milestone demonstrates agent design, function calling, scientific guardrails, audit logging and UI integration as a coherent job-portfolio feature.

## 2026-08-14 · Dual-scale B/R EBSD workflow completed

- SteelAI indexed all four CTF maps as two independent acquisition-matched groups: 1000x/0.5 um and approximately 2000x/0.15 um.
- The high-resolution B-DQ region-2 and R-DQ region-3 pair passed voltage, tilt, phase, magnification, step-size and field-size compatibility checks within the declared 1% tolerance.
- Both high-resolution MTEX runs produced standardized IPF, KAM, grain, phase, boundary, JSON and CSV artifacts plus a paired preliminary report.
- Cross-resolution pooling is disabled; each result remains one field per condition and directional evidence only.

## 2026-08-14 · First acquisition-matched B/R EBSD comparison completed

- SteelAI processed B-DQ region 3 and R-DQ region 1 with identical 1000x, 0.5 um step, 601 x 360 grid, 20 kV and 70-degree acquisition conditions.
- Both MTEX runs completed and produced a structured comparison table, paired maps and an evidence-bounded preliminary report.
- The result is explicitly one field per condition and remains directional evidence rather than an inferential sample-level conclusion.

## 2026-08-14 · First integrated MTEX EBSD pilot completed

- SteelAI launched MATLAB R2023b and MTEX 6.1.0 against the selected read-only B-DQ region-2 CTF file.
- The 479,200-point map completed phase, BCC orientation-grain, boundary and KAM analysis and returned standardized JSON, CSV and PNG artifacts.
- The measured indexing fraction was 84.81%; the output remains a technical pilot pending scientific parameter and map review.
- Parent-austenite, packet and block reconstruction stayed disabled and no raw EBSD file was modified.

## 2026-08-14 · Integrated Automation Center v0.1 operational

- SteelAI Workbench can now launch the B/R ten-image AutoDimple workflow from the Streamlit interface.
- The application shows background-job status, progress logs, B/R summary metrics, plots and the preliminary report in one place.
- The real Conda/GPU workflow completed successfully and all 14 automated tests passed.
- This is the first working control-plane milestone toward the integrated SteelAI research system.

## 2026-08-09 · SteelAI Workbench 0.1.0 MVP 可运行

- 新增事实：六页 Streamlit 本地应用完成，全部页面渲染测试与本地健康检查通过。
- 新增判断：当前主要风险从“能否运行”转为真实数据映射、公式文献复核和证据质量。
- 已作决定：继续保持原始实验资料只读，以路径索引和 processed CSV 接入；生活管理继续留在 Notion。
- 下一步行动：配置真实实验根目录与 WearSteel-AI v0.1 路径，核对公式，接入 1–14 号实验与微观证据索引。
- 是否值得归档：是。可作为科研数字化与求职项目的起始里程碑。
# 2026-08-10 · First local vision model completed a GPU round trip

SteelAI successfully loaded an official SAM ViT-B checkpoint on the local RTX 4060 Ti,
processed matched 1000× B-DQ and R-DQ fracture SEM images, and produced auditable technical
mask previews. The result proves the local vision pipeline works; it is deliberately not treated
as morphology evidence until interactive prompts and human review are completed.
# 2026-08-10 · First persistent automatic SEM baseline

The Conda/z5py Commit pipeline stored 157 unreviewed SAM objects for `B-DQ-1-06` at 1000×.
The masks cover 9.938% of the cropped SEM field. A one-pixel minimum object demonstrates that
the output contains noise, so it is archived as `auto_baseline_unreviewed`, not as dimple evidence.
# 2026-08-10 · AMG candidate generator v1 frozen

The selected automatic settings (`0.78 / 0.87 / 0.60 / 50`) were persisted for `B-DQ-1-06`.
Commit produced 1,349 exclusive labels; enforcing the configured 50-pixel minimum after Commit
leaves 489 unreviewed candidates covering 29.518% of the image. The large fragment count confirms
that raw committed label IDs must not be interpreted directly as dimple count.

# 2026-08-10 · Review30 manual validation set created

SteelAI selected 30 edge-excluded candidates from `B-DQ-1-06` using a 5×6 spatial grid.
The set contains 10 small, 10 medium, and 10 large automatic candidates, each with a stable
review ID and a separate review table. These objects remain `review_seed_unreviewed`; only the
future `review30_reviewed.tif` may be used to calculate validated dimple-size statistics.

# 2026-08-10 · Preliminary automated dimple standard v0.1 frozen

The human aggregate review accepted 22/30 candidates (73.3%) and rejected 8/30 (26.7%).
SteelAI froze the current 1000× acquisition eligibility rules, SAM parameters, 50-pixel
post-filter, edge exclusion and an exploratory 0.733333 count-correction factor. Routine
object-by-object review is disabled; out-of-standard images are excluded and reported.

# 2026-08-11 · First B/R ten-image AutoDimple batch completed

SteelAI processed five B-DQ and five R-DQ 1000× SEM fracture images on the local GPU without
object-by-object review. Image-level exploratory results show R versus B: estimated candidate count
-38.6%, candidate coverage +8.2%, and median equivalent diameter +17.7%. All bootstrap 95% intervals
cross zero, so the observed directions are hypotheses rather than established B/R differences.
