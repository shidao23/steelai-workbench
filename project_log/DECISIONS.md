# Decisions

## 2026-09-05 · Select one bounded open-source feature for T14 evaluation

- Decision: evaluate only Frictionless `5.19.0` as an optional Data Package descriptor and independent public-export validator in T14.
- It may describe and validate the public graduation package, but it cannot replace SteelAI's frozen data contract, QC, approvals or append-only import gate.
- NOMAD `1.4.3` is architecture reference only; GEMD `2.2.4` and MLflow `3.16.0` are deferred until a concrete interoperability or scale need exists.
- Great Expectations `1.21.0` is rejected now because its official package requires Python below 3.14 while this project uses 3.14.2, and its validation scope overlaps existing controls.
- T13 imports no code. T14 still requires isolated installation measurement, exact package/hash pinning, license retention, synthetic-only tests and proof that the core works when the adapter is absent.

## 2026-09-05 · Freeze graduation core data contract v1

- Decision: freeze `SteelAI-Graduation-Core-v1.0` as the personal graduation MVP contract for specimen-level tensile YS, UTS and elongation.
- Material design, heat, research sample/condition, physical specimen, source report and scalar observation have separate IDs and explicit parent relationships.
- A specimen observation is `individual`; report-level mean/SD/min/max is a `sample_summary` with an explicit replicate count and never creates specimen rows.
- Curve points, image fields, detected image objects and EBSD pixels remain nested/deferred objects and cannot be used as independent specimens.
- Existing B/R tables and the T10 local staging package are not migrated or committed by this decision. Activation requires a separate reviewed migration with backup and acceptance evidence.
- Adding quantities may use a reviewed minor version; changing identity, keys, statistical meaning or existing units requires a major version.

## 2026-08-22 · Local research sessions before broader orchestration

- Decision: make a resumable local research session the unit of daily work before introducing multi-agent orchestration or a heavier experiment platform.
- A session records the question, B/R scope, workflow template, stage progress, structured findings, next actions and relative run references; raw files and absolute paths remain outside session files.
- Five bounded templates cover the current recurring work: integrated B/R analysis, data intake review, Physics calibration, dual-scale EBSD and SEM fracture analysis.
- Session JSON files use revision checks and atomic replacement. They are project workflow records, not experimental source truth and not a substitute for the append-only observation ledgers.
- Research Case runs may attach to the active session, but a model run never becomes an experimental observation merely because it is linked.
- Completed sessions write only a structured summary to the existing event log for Career Portfolio extraction.
- Experiments 1-14 remain excluded, and the new capability stays inside Research Overview/Research Assistant rather than creating another navigation area.

## 2026-08-22 · Versioned Physics Model Registry

- Decision: use `config/physics_model_registry_v1.0.json` as the authoritative local metadata contract for Ms, Ac1, Ac3, Tnr, Ceq and Pcm formula versions.
- Streamlit, Research Agent and the research-case pipeline use the same six-family default selection; availability of the external WearSteel-AI v0.1 folder no longer changes the active scientific calculation set.
- Missing required chemistry causes a skipped result. Unknown values are never replaced by zero merely to obtain a model output.
- Applicability ranges are explicit review guardrails with documented range bases; they are not universal accuracy guarantees or experimental validation.
- Experimental observations, model estimates and residuals remain separate. Residual is defined as model value minus experimental value, and no fitted result may overwrite a published formula version.
- Model calibration remains unavailable until matched B/R dilatometry or thermomechanical observations with provenance enter through the append-only data gate.
- The registry and UI stay inside the existing Physics Engine area; no seventh navigation area is added and experiments 1-14 remain excluded.

## 2026-08-19 · Validation-first, append-only data intake

- Decision: all future B/R structured observations enter through a local staging and validation gate rather than direct spreadsheet replacement of processed files.
- Only explicit schema aliases are normalized; unknown columns are blocked so spelling errors cannot silently create new scientific variables.
- Existing primary keys are never overwritten. A replacement or correction requires a later reviewed amendment workflow with provenance, not an import-side shortcut.
- Raw uploads are not copied into the project. Audit packages retain only normalized structured rows, content hashes, validation results and commit metadata.
- A field of view remains nested within a physical specimen. The system will not manufacture specimen IDs or treat fields as independent replicates.
- Experiments 1-14 remain outside the allowed sample scope until a separate quality decision changes the contract.

## 2026-08-19 · Agent evaluation policy v0.8

- Decision: evaluate the Research Agent with fixed domain cases and deterministic scorers before adding a more complex orchestration framework.
- The benchmark covers six abilities and includes explicit privacy, pseudoreplication, EBSD scale, empirical-model and causal-inference traps.
- Evaluation uses expected tools, evidence concepts and prohibited wording; no LLM-as-judge score is accepted as the sole quality measure.
- Live batches are limited in the UI to five cases to control cost and simplify failure analysis.
- A path or raw CTF/TIF filename in user input is blocked locally before any provider call.
- MLflow tracing remains a later integration target; v0.8 artifacts are framework-independent JSON and Markdown.

## 2026-08-18 · Research Case Pipeline v0.7

- Decision: make one reproducible B-DQ/R-DQ research task the primary product story instead of adding more independent pages.
- The deterministic Python stages run first and remain authoritative; the external Agent is an optional final evidence-synthesis layer.
- Every completed case must write a report, evidence snapshot and Run Manifest with data/code hashes, stage status, scientific readiness and privacy state.
- The workflow rejects 1-14 experiments and rejects raw locators before an external Agent call.
- LangGraph and MLflow remain the next orchestration/evaluation layer; they are not required for the v0.7 deterministic pipeline.

## 2026-08-18 · Six-area workbench navigation

- Decision: organize the UI around six user tasks rather than one sidebar entry per technical module.
- Dashboard, Data & Physics, Research Assistant, Microstructure & Evidence, Model & Automation, and Career Portfolio are the only main navigation entries.
- Physics, EBSD, Agent, validation and automation remain separate feature views internally for maintainability and testing.
- Removing a sidebar entry does not remove its calculations, outputs, audit records or scientific guardrails.

## 2026-08-18 · Experiments 1-14 excluded from the core evidence set

- Decision: do not ingest experiments 1-14 into the current processed core because the user considers their data quality insufficient.
- They must not be used for statistics, machine learning, Agent evidence or mechanism conclusions until a future quality review explicitly changes this decision.
- Current development focuses on making the B-DQ/R-DQ case scientifically bounded, reproducible and portfolio-ready.

## 2026-08-18 · Evidence-level and claim-gate policy

- Decision: separate evidence strength from conclusion status using L0-L4 plus NA.
- Reported three-repeat mechanical summaries are L2 with an independence caveat until specimen IDs and raw records are registered.
- Each EBSD acquisition group is L1 because it contains one field per condition; consistent directions across the two unpooled groups may support an L2 directional statement only.
- AutoDimple is L2 image-level descriptive evidence, not specimen-level inference; intervals crossing zero remain not confirmed.
- Causal claims require at least L3 evidence plus a credible mechanism or intervention chain.
- Research Agent must obey the deterministic allowed/prohibited wording matrix when discussing evidence strength.

## 2026-08-18 · Default domestic model provider

- Decision: use the official DeepSeek API with `deepseek-v4-flash` as the default Research Agent provider.
- Basis: domestic balance recharge, low token cost, OpenAI SDK compatibility and official support for tool calls.
- DeepSeek uses its own strict Chat Completions adapter at the beta endpoint; OpenAI remains an optional fallback rather than a hard dependency.
- The model provider may change, but Python calculations, evidence boundaries, tool permissions and audit contracts remain provider-independent.

## 2026-08-17 · Research Agent v0.1 architecture

- Decision: add one read-only research coordinator before considering a multi-agent system.
- The agent may call only six strict tools covering processed samples, deterministic comparisons, physics estimates, EBSD summaries and AutoDimple summaries.
- The agent cannot modify source data, launch MATLAB/GPU jobs, run arbitrary code or expose raw file paths.
- Low- and high-resolution EBSD results remain separate; image objects and fields are not treated as independent specimen replicates.
- Direct OpenAI Responses API tool calling is sufficient for the present workflow, so LangChain is deferred until there is a demonstrated need for cross-provider orchestration or a larger workflow graph.
- Agent output is not written automatically. The user must explicitly save an accepted analysis before it becomes a project event and career evidence.

## 2026-08-14 · EBSD acquisition matching policy

- Decision: maintain two independent B/R comparison groups and never pool measurements across acquisition scales.
- The low-resolution group uses B-DQ region 3 and R-DQ region 1; both are 0.5 um, 1000x, 601 x 360, 20 kV and 70 degrees.
- The high-resolution group uses B-DQ region 2 and R-DQ region 3; their CTF headers are approximately 0.15 um and 2000x, with field dimensions and acquisition settings within a 1% compatibility tolerance.
- CTF header metadata, rather than folder labels or informal naming, is the authoritative basis for assigning an EBSD map to a comparison group.
- One-map differences are recorded as directional observations only; replication is required before mechanism claims.

## 2026-08-14 · EBSD pilot evidence boundary

- Decision: use MTEX as an isolated crystallographic engine controlled by the Python/Streamlit workbench.
- The current 3-degree objects are named BCC orientation grains, not martensite blocks, packets or prior-austenite grains.
- The reported FCC fraction is an indexed phase-assignment result and is not yet accepted as a retained-austenite measurement.
- Parent reconstruction will be enabled only after the basic IPF, phase, boundary and KAM outputs are reviewed.

## 2026-08-14 · Integration architecture

- Decision: define "integrated system" as one user interface, one data contract and one job/status system, not one monolithic Python environment.
- Streamlit remains the control plane; GPU vision, thermodynamics and future specialist tools run in isolated environments.
- Raw experimental files remain read-only sources of truth. The workbench stores paths, indexes, processed tables, standardized results and audit logs.
- Every specialist model must return a standard result package before its output can enter research conclusions or Career Portfolio evidence.

## 2026-08-10 · Automatic dimple workflow after Review30

- Decision: disable routine object-by-object manual review after the initial Review30 calibration.
- Basis: the user reported 22/30 correct automatic candidates, an aggregate acceptance rate of 73.3%.
- Guardrail: apply the rule only to matched 1000× SEM images with compatible pixel calibration and acquisition conditions.
- Exception policy: images outside metadata, coverage or median-size limits are marked `out_of_standard` and excluded rather than silently pooled.
- Evidence limitation: the saved mask retains 25 labels, so the standard uses the aggregate 22/30 rate without inventing identities for the three unresolved objects.

## 2026-08-11 · Distribution shifts are warnings, not exclusion rules

- Decision: upgrade the comparison rule to `AutoDimple-BR-1000x-v0.2`.
- Reason: hard limits derived from one B image excluded six of ten matched B/R images and would bias the comparison against real morphology shifts.
- Hard exclusions now apply to metadata mismatch or gross segmentation failure only.
- Coverage and median-size shifts remain visible warnings and stay in the exploratory comparison.
- Routine per-object manual review remains disabled.

## 2026-08-09：MVP 技术与范围决策

- Python + Streamlit 作为本地轻量多页应用。
- Python 是确定性计算和数据处理层；GPT 只做证据约束下的自然语言分析/报告。
- `02_实验数据` 保持 source of truth；项目内只保存路径索引和 processed 数据。
- 微观照片第一阶段只做路径登记与人工参数提取，不做复杂图像模型。
- 每次数据、公式、分析和决定进入 project log，自动转化为求职证据。
- 生活管理不纳入本项目，继续留在 Notion。
- 第一版不使用 XGBoost/DeepXDE。
## 2026-08-19 · Scientific data contract before MLflow

- Decision: establish the extensible composition-process-microstructure-property-physics contract before adding MLflow or training models.
- Current summary CSVs remain compatible; future repeated observations use separate long-form ledgers instead of continually widening one spreadsheet.
- Missing experimental values remain blank. Model estimates, calibrated estimates and experimental observations are stored as different measurement types.
- Experiments 1-14 remain excluded. Current B/R data may support directional comparisons but not causal inference or reliable machine learning.
- GitHub CI must use synthetic fixtures and environment-variable API configuration; publishing or uploading research data requires a separate explicit privacy review.
