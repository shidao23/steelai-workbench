# Changelog

## stage1-t11-real-format-regressions - 2026-09-05

- Recorded SteelData's public synthetic regression coverage for Chinese/English headers, blank rows, worksheet selection, profile ambiguity, unit conflicts, duplicates and bad values.
- Kept the Workbench result-contract and formal-import gates unchanged; the T10 local staging package remains `not_committed`.
- Confirmed that no real report content, measurement values, identities, report identifiers or local paths were added to either repository.

## stage1-t10-real-tensile-acceptance - 2026-09-04

- Accepted one human-approved, desensitized DQ SteelData package with 6 physical specimens and passed integrity, QC and same-runtime replay checks.
- Applied the six explicit specimen-to-sample bindings and `manual_extraction_verified` source status to a Workbench preflight containing 18 unique YS/UTS/EL observations.
- Saved an ignored local staging package, validation manifest and source audit with `not_committed` status; no formal `property_observations.csv` append occurred.
- Marked T10 complete while retaining T200, curves, impact, geometry, reduction of area and microscopy outside this task.

## stage0-governance - 2026-09-04

- Established the local Git privacy baseline and documented excluded real-data, path, credential, output and model-weight areas.
- Recorded the 105-test offline baseline, with two documented environment-dependent skips.
- Added a lightweight task board, task template, status definitions, task numbering and change-record rules.
- Synchronized the README and capability matrix with the implemented SteelData v0.2 CLI/result-contract integration and retained DSH boundary.

## 0.13.0-research-session-workflow - 2026-08-22

- Added five versioned daily research workflow templates inside the existing Research Assistant area without adding a sidebar entry.
- Added local research sessions with revisioned atomic JSON persistence, stage progress, structured findings, next actions, status transitions and relative run references.
- Added active, blocked, completed and open-action summaries to the existing Research Overview.
- Linked completed B/R Research Case runs to the current research session and automatically completed the corresponding workflow stage.
- Kept sessions limited to B-DQ/R-DQ, rejected absolute paths and raw CTF/TIF filenames, and retained experiments 1-14 outside the workflow.
- Added a Research Session Contract to the offline quality gate and added component-level coverage for the creation workflow.
- Expanded the automated suite from 57 to 64 tests.

## 0.12.0-physics-model-registry - 2026-08-22

- Added a local, machine-readable Physics Model Registry for 10 existing formula versions across Ms, Ac1, Ac3, Tnr, Ceq and Pcm.
- Registered model version, family, formula, source, required inputs, unit, applicability range, limitations, license note, review status, experimental-reference interface, residual convention and calibration status.
- Added per-family formula selection, model cards and non-destructive version-comparison reports inside the existing Data & Physics → Physics Engine view.
- Changed missing-input behavior to skip calculation without replacing unknown chemistry with zero; retained explicit composition-range warnings.
- Added a read-only experimental/model/residual interface using controlled `physics_observations.csv` records and the convention model value minus experimental value.
- Unified the Streamlit view, Research Agent and research-case pipeline on the same local registry while keeping the legacy v0.1 adapter available for compatibility tests.
- Added the Physics Model Registry contract to the offline quality gate; experiments 1-14 remain excluded and model estimates remain distinct from experimental truth.
- Expanded the automated suite from 54 to 57 tests.

## 0.11.0-data-intake-gate - 2026-08-19

- Added a local validation-first Data Intake workflow inside the existing Data & Physics area without adding navigation pages.
- Added controlled header-only templates for composition observations, process steps, microstructure fields, property specimens and physics observations.
- Added an explicit research ID hierarchy covering material, heat, batch, sample, specimen, field, observation and run levels.
- Added UTF-8/GB18030 CSV parsing, explicit Chinese column aliases, numeric and required-value checks, scope/orphan checks, primary-key conflict blocking and unit warnings.
- Enforced dry-run by default, explicit user confirmation and append-only processed writes; existing keys are never replaced.
- Added privacy-safe intake audit packages containing only normalized structured staging data, hashes and manifests; raw uploads, local paths and API calls remain outside the flow.
- Kept experiments 1-14 excluded and kept the current B/R evidence at directional-only readiness.
- Expanded the automated suite from 49 to 54 tests.

## 0.10.0-research-data-contract - 2026-08-19

- Added a machine-readable contract for sample, composition, process, microstructure, property and physics-observation data.
- Preserved current summary tables while defining optional long-form ledgers for process steps, microstructure fields, independent property specimens and experimental/model physics values.
- Added column, numeric-type, duplicate-ID, foreign-key, scope and completeness checks without filling missing measurements.
- Added a data-quality and expansion-readiness panel inside the existing Data & Physics area.
- Added an offline quality-gate command and a GitHub Actions workflow using synthetic public fixtures, current official v7 checkout/setup-python actions and read-only repository permissions.
- Kept experiments 1-14 excluded and kept causal inference and machine learning marked not ready.
- Expanded the automated suite from 44 to 49 passing tests.

## 0.9.0-agent-observability - 2026-08-19

- Verified the first live DeepSeek baseline: 3/3 smoke cases passed, including pre-API path blocking; this is a smoke baseline rather than a claim of general Agent reliability.
- Added evaluation history, score/latency/token trends and common-case run comparison with explicit regression detection.
- Added per-tool timing and a sanitized trace export that excludes questions, answers, tool arguments, local paths and raw files.
- Added a trace explorer inside the existing Agent Evaluation view without adding a seventh sidebar area.
- Kept MLflow/OpenTelemetry as a later optional adapter so the stable main environment does not gain a heavy dependency prematurely.
- Expanded the automated suite from 42 to 44 passing tests.

## 0.8.0-agent-evaluation - 2026-08-19

- Added a 25-case B/R Research Agent benchmark across data grounding, Physics, EBSD, SEM, scientific guardrails, privacy and permissions.
- Added transparent deterministic scoring for expected tool calls, required evidence concepts, prohibited claims, privacy, status and latency.
- Added a small-batch live DeepSeek evaluation workflow with per-case traces, token usage, failure diagnosis, reports and manifests.
- Added a local pre-API gate that rejects questions containing absolute paths or raw CTF/TIF filenames.
- Added an Agent quality dashboard inside Research Assistant without increasing the six-entry sidebar.
- Added machine-readable evaluation artifacts ready for later MLflow/OpenTelemetry ingestion.

## 0.7.0-research-case-pipeline - 2026-08-18

- Replaced the separate quick-report view with one end-to-end B/R research task, avoiding another navigation entry.
- Added deterministic orchestration across processed-data checks, sample comparison, Physics, dual-scale EBSD, AutoDimple and evidence validation.
- Added optional DeepSeek synthesis after all deterministic stages; the offline pipeline remains complete without an API.
- Added one run package containing a Markdown report, privacy-scrubbed evidence snapshot and versioned Run Manifest.
- Recorded processed-data hashes, code hashes, stage timing, Agent trace, scientific readiness and privacy policy for reproducibility.
- Kept experiments 1-14 excluded and rejected local paths or raw CTF/TIF names before any external Agent call.

## 0.6.1-consolidated-navigation - 2026-08-18

- Reduced the sidebar from eleven entries to six task-oriented workbench areas.
- Merged sample data with Physics, offline analysis with Research Agent and validation, evidence indexing with EBSD, and Model Lab with automation results.
- Kept the original feature implementations as independently tested embedded views, so navigation cleanup does not remove scientific functionality.
- Added explicit Streamlit navigation titles, compact submodule selectors and shared visual styling.
- Removed duplicated page-level configuration and hidden local-only deployment/menu controls.

## 0.6.0-evidence-validation-center - 2026-08-18

- Added the B/R Evidence & Validation Center as the eleventh workbench page.
- Added a deterministic evidence registry covering composition, mechanics, physics, dual-scale EBSD, AutoDimple and missing XRD validation.
- Added nine claim assessments with allowed wording, prohibited wording, evidence gaps and next actions.
- Enforced six scientific gates for source truth, replicate independence, image pseudoreplication, EBSD scale separation, empirical-model labeling and causal claims.
- Added a seventh read-only Research Agent tool that exposes the validation matrix without source locators or raw-file information.
- Explicitly excluded experiments 1-14 from the core evidence set, statistics and machine learning by user decision.
- Expanded the automated suite to 30 passing tests.

## 0.5.1-deepseek-provider - 2026-08-18

- Switched the default Research Agent provider to DeepSeek V4 Flash for domestic RMB billing and lower operating cost.
- Added provider-aware key, model and base-URL configuration while retaining the OpenAI provider as a fallback.
- Added a dedicated DeepSeek strict Chat Completions tool loop instead of assuming identical Responses API behavior across providers.
- Kept all six scientific tools read-only and retained the existing audit trace and user-controlled save boundary.

## 0.5.0-research-agent - 2026-08-17

- Added a single read-only Research Agent page with six strict, whitelisted tools.
- Reused the deterministic sample, physics, EBSD and AutoDimple modules instead of duplicating scientific calculations.
- Added explicit tool-call and round limits, path filtering, scientific guardrails and a user-controlled save step.
- Kept LangChain out of the current architecture; the agent uses the OpenAI Responses API directly and remains offline when no API key is configured.
- Added offline status, tool-loop and full-page rendering tests.

## 0.4.2-dual-scale-ebsd - 2026-08-14

- Added the R-DQ region-3 high-resolution CTF and paired it with B-DQ region 2.
- Added tolerant CTF compatibility checks for step size, magnification and physical field dimensions while keeping voltage, tilt and phase definitions exact.
- Added a second high-resolution B/R MTEX workflow, status contract, comparison report and paired Streamlit display.
- Enforced independent low- and high-resolution groups with no cross-resolution metric pooling.
- Completed the high-resolution B/R run and expanded the automated suite to 19 passing tests.

## 0.4.1-matched-br-ebsd - 2026-08-14

- Added the selected R-DQ region-1 1000x CTF to the EBSD workflow.
- Added acquisition compatibility checks and selected the matched B-DQ region-3 1000x map.
- Added sequential B/R MTEX execution, structured metric comparison, paired map display and CSV download.
- Added explicit one-field-per-condition and phase/grain interpretation guardrails.
- Expanded the automated suite to 18 tests.

## 0.4.0-ebsd-mtex-pilot - 2026-08-14

- Added the EBSD Analysis Streamlit page.
- Added a non-interactive MATLAB/MTEX job runner and persistent job status.
- Added read-only CTF metadata inspection plus standardized grain, boundary, KAM, phase and plot outputs.
- Added EBSD parser, status and scientific-guardrail tests; the workspace suite now has 17 passing tests.
- Completed the first real B-DQ region-2 1000x EBSD pilot with MTEX 6.1.0.

## 0.3.0-automation-center - 2026-08-14

- Added a Streamlit Automation Center page.
- Added a hidden background-job launcher for the isolated Conda/GPU AutoDimple workflow.
- Added persistent job status and log files plus result loading for B/R metrics, tables, plots and reports.
- Added automated tests for launch configuration and status handling; the full suite now contains 14 passing tests.

## 2026-08-10 · AutoDimple v0.1

- Added the preliminary 1000× SEM automatic dimple standard.
- Added acceptance-rate correction and automatic eligibility checks.
- Disabled routine per-object review and added out-of-standard exclusion rules.
- Added the Review30 validation summary to Open Model Lab.

## 2026-08-11 · B/R ten-image batch analysis

- Added the one-click `Run_AutoDimple_BR10.cmd` workflow.
- Added GPU batch segmentation, post-filtering, per-image tables, overlays and resumable outputs.
- Added image-level B/R bootstrap comparison and pseudoreplication guardrails.
- Added AutoDimple-BR-1000x-v0.2 warning-versus-exclusion policy.
- Added the B/R batch result panel to Open Model Lab.

## 0.2.0-model-lab - 2026-08-10

- Added Open Model Lab with a model registry and isolated-install status.
- Added NVIDIA GPU detection and SEM TIF/HDR metadata parsing.
- Added balanced B/R pilot selection using five 1000× images per steel.
- Added normalized 16-bit TIF previews without modifying source files.
- Added tests for model-lab scanning and all seven Streamlit entry pages.

## 0.1.0-mvp - 2026-08-09

- 建立六页 Streamlit 本地工作台骨架。
- 建立 samples/composition/process/microstructure/properties processed 数据层。
- 加入 Ms、Ac1、Ac3、Tnr、Ceq、Pcm 经验公式注册表、来源、审查护栏与 warning。
- 加入离线结构化研究报告，以及可选 OpenAI Responses API 润色层。
- 加入证据路径索引、project event log 和 Career Portfolio 自动生成。
- 明确 DEMO 数据、模型估算和实验真值边界；暂不引入 XGBoost/DeepXDE。
# 2026-08-10 · micro-sam GPU pilot

- Added an isolated Python 3.12 environment for `micro-sam 1.8.8`.
- Installed and validated GPU-enabled `PyTorch 2.7.1+cu128` on RTX 4060 Ti.
- Added the official Meta Segment Anything ViT-B checkpoint.
- Ran paired B/R 1000× SEM smoke tests without modifying source TIF files.
- Added traceable JSON output, overlays, micro-sam embedding cache, and two one-click annotator launchers.
- Marked every current mask as a technical test pending target definition and human review.
# 2026-08-10 · Conda Commit backend

- Installed signed Miniforge 26.3.2 without changing the global Python or PATH.
- Created a dedicated local Miniforge environment with Python 3.12, micro-sam 1.8.8, z5py 3.0.2, and CUDA PyTorch; its machine-specific path is not tracked.
- Added a Windows Zarr path adapter and switched the B/R launchers to the Conda environment.
- Created separate B/R Commit stores to prevent annotation history from being mixed across images.
- Retained the prior pip environment as a temporary rollback option until the first UI Commit is confirmed.
