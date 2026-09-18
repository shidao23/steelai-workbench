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

## License

The repository is released under the MIT License. Public dataset attribution and its CC BY 4.0 terms are recorded in [`docs/T62_REAL_DATA_CASE.md`](docs/T62_REAL_DATA_CASE.md).
