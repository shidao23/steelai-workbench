# SteelAI Workbench

SteelAI Workbench is a traceable research-software prototype for materials and steel-data workflows. Deterministic Python code handles data contracts, quality checks, statistics, physics estimates and evidence manifests. A cloud model may organize verified structured evidence, but it cannot approve data, write formal results or run arbitrary commands.

## Reproducible paths

- `Run_Flagship_Demo.cmd` replays the public synthetic T40 chain, including the unknown-unit closed path.
- `Run_T62_RealData_Case.cmd` replays a CPU-friendly UCI Steel Plates Faults case. The source is CC BY 4.0; raw data is downloaded at runtime and is not committed.
- `Run_T63_Benchmark_Prep.cmd` prepares a fixed comparison of human-only, single-agent and governed multi-agent workflows. It does not invent timing or token measurements.

The T62 result is a working candidate for a public algorithm case, not a metallurgical mechanism, production recommendation or causal conclusion. T63 remains `needs_human` until the same four tasks are actually run twice under all three workflows.

## Architecture

```text
public or approved input
        -> deterministic contract and QC
        -> named human decision gate
        -> statistics / Physics / model task
        -> evidence gateway and append-only manifest
        -> bounded report and portfolio review
```

The main UI is a local Streamlit Workbench. It can run without a local AI model. Cloud calls are optional and receive only audited structured summaries when enabled.

## Quick start

Use Python 3.11 or newer on Windows, macOS or Linux:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
streamlit run app.py
```

For complete setup and release checks, follow [`docs/INSTALL.md`](docs/INSTALL.md). Read [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) before interpreting any result.

## Evidence and boundaries

Every portfolio capability maps to code, tests and a documented boundary. The public candidate excludes private experiment files, local paths, credentials, model weights and unreviewed agent answers. See [`docs/T64_PORTFOLIO_RELEASE.md`](docs/T64_PORTFOLIO_RELEASE.md) and [`docs/T64_INTERVIEW_GUIDE.md`](docs/T64_INTERVIEW_GUIDE.md).

## Optional CALPHAD adapter (T86, currently blocked)

The Workbench offers an **optional, switchable** CALPHAD phase-fraction module. `pycalphad==0.11.2` is installed in a separate environment (`.venv-pycalphad`, 34 packages hash-locked in `requirements-calphad-win-py312.lock`); the main application never imports it and its requirements files are unchanged. The database is MatCalc `mc_fe v2.062` from TU Wien, obtained from the vendor's official publication location, with SHA-256 `aa02077e…`. It is licensed **ODbL 1.0 + DbCL 1.0 — entirely separate from pycalphad's MIT licence — and is not redistributed with this repository**; only the registration template, the acquisition instructions and the gate evidence are committed.

**Compatibility gate 1 failed on the vendor original.** pycalphad 0.11.2 cannot parse it: loading by path fails with `UnicodeDecodeError` (the file is cp1252, pycalphad uses the platform locale encoding), and after supplying the encoding it raises `ParseException: Invalid TDB syntax` at **line 180, `REFERENCE_ELEMENT`**. MatCalc-only commands (`REFERENCE_ELEMENT`, `ADD_COMPOSITION_SET`, `ATTACH_CONTRIBUTION`, `CREATE_NEW_PHASE`, `HMVA`) each fail individually. The original is kept only for provenance and for the diff audit, and is not selectable.

**Phase 3 — community derivative candidate.** The project owner chose not to preprocess the vendor original and instead to review an existing community compatibility derivative: `2databases/mc_fe_v2062_clean.tdb` from the `adityamoolya/maraging-steel-calphad-dft` repository at commit `19b11640253543fe412145498438cb8355a32561`, SHA-256 `7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042`. It is registered **only as a third-party community derivative database candidate** — never as a TU Wien official pycalphad-compatible build, a pycalphad official database or a validated SteelAI database. The file is **unmodified**, is stored in a git-ignored directory, is never redistributed from this repository, and the upstream ODbL 1.0 + DbCL 1.0 header notice is preserved. The source repository publishes no LICENSE file, so no third-party code was copied.

Results: the diff audit against the vendor original reports `passed_syntax_repairs_only` with **0 unexplained deviations** over 4,515 shared statements (syntax repairs plus MatCalc-only commands/parameters commented out; no Gibbs energy, breakpoint or numeric-coefficient change). The repository's own claim of five binary systems / fifteen checks was re-implemented from the stated criteria and **15/15 reproduced**; nine project-relevant systems covering Fe-C (stable and metastable), Fe-Cr-C, Fe-Mn, Fe-Si, Fe-Nb, Fe-V, Fe-B and Fe-N passed **18/18** plausibility checks. Those checks prove software behaviour and basic plausibility only — they are **not** experimental validation of a steel grade.

**Phase 4 — fixed reduced component system and fixed phase range.** The project owner approved a fixed, versioned `steel_matrix_equilibrium_v1` profile (12 components: `Fe, C, Mn, Si, Cr, Ni, Mo, Cu, Al, Nb, Ti, V`, plus the `VA` vacancy so that 13 component-list entries are sent to pycalphad — the measured capacity bound on this host) and a fixed `steel_matrix_major_carbides_v1` phase range (`LIQUID, FCC_A1, BCC_A2, CEMENTITE, M23C6, M7C3, M6C`; all seven verified by an independent probe and none removed). `B/N/P/S` are excluded under a new `capacity_reduction` category — they **do** carry measured values but are dropped to stay inside the solver capacity limit; `As/Sn/Sb` are not covered by the database; `O/W` have no measured value and are never treated as zero. There is **no generic element or phase switch**: a component set that differs from the profile blocks with `CALPHAD-COMP-012`, a missing phase blocks with `CALPHAD-PHASE-001`, and a real-sample run without a named approval blocks with `CALPHAD-COMP-011` (**the code never fills in a reviewer name**). Results are named `12-component reduced-system matrix equilibrium prediction` and always carry the reduced-system notice, the excluded elements and reasons, the BCC_B2/HMVA/MC-MX model losses, the versions and hashes, `pending_human_review`, and no write-back.

**Ten-step validation.** Steps 1–5 and 9 pass. **R-DQ converges at all 54 temperature points** (phase-fraction sums 0.9999999998–1.0000000004, run-to-run difference within 3e-9, identical assemblages, sequence ferrite + cementite → ferrite + austenite → austenite → delta ferrite + liquid → liquid). **B-DQ does not converge at 875 °C in the multi-temperature batch scan** (a bounded single-temperature retry did not recover it; the identical request produced 0/1/2/3 non-converged points in different processes, and `pdens` 500–8000 does not remove it). Step 6 therefore fails and **T86 stays `Blocked`** — never `pilot_ready_pending_scientific_review`.

**Defect found and fixed.** Omitting the `VA` vacancy from the pycalphad component list does **not** raise: it returns a physically wrong assemblage (B-DQ reported LIQUID 0.97 at 400 °C) while the phase-fraction sum still equals 0.99942, so a sum-only check cannot detect it. The worker now always adds `VA` when the database declares it and reports `pycalphad_components`; the validation adds a physical plausibility guard (no liquid below 1000 °C, liquid required above 1500 °C, a BCC_A2/FCC_A1 matrix below 700 °C). No temperature point was dropped, no criterion was relaxed and no TDB was edited to make a run pass.

**Phase 5 — independent single-point process per temperature.** The formal path is now `solver_mode=independent_single_point_process_v1`: one fresh worker process per temperature point, exactly one temperature per process, **strictly serial**, no warm start, and identical inputs except temperature. The old batch warm-start path is demoted to `diagnostic_only`. Every point records the full contract (request hash, worker PID and exit code, whether `VA` was present, database SHA-256, solve status, active phases and mole fractions, phase-fraction sum, runtime, sanitized stderr, first-attempt flag, solver mode) and the run carries a point manifest with an integrity hash. The parent merges only first-attempt successes that pass contract validation — **a missing point yields no partial curve** — and a single diagnostic retry never turns a failure into a pass and is never spliced into the formal curve.

**The phase-5 acceptance is still `blocked`.** Of the **324 independent points, 320 succeeded on the first independent process call (98.77 %)**; all four failures were B-DQ at **875 °C and 900 °C** (and the diagnostic retry failed there too), with zero native aborts, `MemoryError`s and timeouts. R-DQ passed 54/54 in all three runs with a three-run maximum difference of 1.3×10⁻⁹. The independent mode did **not** remove the failure, which corrects the phase-4 attribution to batch warm-starting: repeating the *same single-point* condition in **fresh processes** gives B-DQ 900 °C a 1/8 success rate and 875 °C 2/4, failing with "no phase moles". The system is simply **non-deterministic near the α/γ boundary** in pycalphad 0.11.2 on this host, independent of the solver mode. A second blocking finding: on R-DQ the batch and independent modes disagree by **1.069×10⁻⁴ at 675 °C** (tolerance 1e-7) with the same three-phase assemblage but different fractions, so per the "choose neither curve" rule **neither curve is published**. T86 therefore stays `Blocked` — not `pilot_ready_pending_scientific_review`. Total wall clock: 4013 s (66.9 min).

T86 therefore stays `Blocked`, and the database candidate is recorded as `compatibility_candidate`.

See [`docs/T86_PHASE5_INDEPENDENT_POINTS.md`](docs/T86_PHASE5_INDEPENDENT_POINTS.md), [`docs/T86_PHASE4_REDUCED_SYSTEM.md`](docs/T86_PHASE4_REDUCED_SYSTEM.md), [`docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md`](docs/T86_PHASE3_COMMUNITY_COMPATIBILITY.md), [`docs/T86_PHASE2_ENVIRONMENT_AND_GATES.md`](docs/T86_PHASE2_ENVIRONMENT_AND_GATES.md), [`docs/T86_CALPHAD_DATABASE_CANDIDATE_REVIEW.md`](docs/T86_CALPHAD_DATABASE_CANDIDATE_REVIEW.md) and [`model_lab/calphad/README.md`](model_lab/calphad/README.md).

## License

The repository is released under the MIT License. Public dataset attribution and its CC BY 4.0 terms are recorded in [`docs/T62_REAL_DATA_CASE.md`](docs/T62_REAL_DATA_CASE.md).
