# SteelAI Workbench Agent Rules

## Project purpose

- This repository is a graduation-grade research software project for traceable steel-materials data processing, physics calculations, statistics, evidence governance, and constrained cloud-agent assistance.
- Preserve the accepted v0.2 release-candidate architecture and the frozen T40 flagship demonstration unless the user explicitly requests a change to them.

## Working style

- Communicate in concise Chinese and lead with the result.
- Do not provide line-by-line teaching by default. Explain implementation details only when the user asks, or when a risk or decision requires explanation.
- Inspect the existing implementation and relevant documentation before changing code. Prefer focused changes over broad rewrites.
- Preserve unrelated user changes in a dirty working tree.

## Scientific and data-governance boundaries

- Deterministic Python code performs data validation, normalization, calculations, statistics, and integrity checks. A language model may organize or explain verified evidence, but must not manufacture measurements or replace deterministic calculations.
- AI output is a suggestion or draft until a named human review explicitly accepts it.
- Never silently convert missing values to zero, infer unknown units, invent sample relationships, or treat model output as an experimental measurement.
- Unknown units, ambiguous identifiers, missing required fields, failed integrity checks, or unsupported scientific claims must stop at `needs_human`, `blocked`, or the equivalent existing state.
- Preserve provenance, hashes, approval records, append-only behavior, and the distinction between fact, judgment, hypothesis, limitation, and prohibited claim.
- Do not copy, expose, or commit private raw experimental files, local absolute paths, API keys, credentials, personal information, model weights, or generated private outputs.

## Implementation rules

- Reuse the existing governance core, contracts, adapters, and state machines instead of creating parallel versions.
- Keep SteelData, SteelStats, image/model runtimes, and the Workbench separated according to the current architecture.
- Treat third-party code as reusable only after its license and source are recorded. Do not copy non-open-source implementation code.
- Keep UI changes consistent with the established complex-page structure: current status, primary action, result, technical details, and a context-appropriate next step.
- Do not add a production dependency without explaining why it is needed and obtaining user approval.

## Verification

- The single test entry point is `.\scripts\test.ps1`. Use it by default for every verification.
- Do not assemble your own "full test suite" command, and do not point pytest at `outputs/`, `model_lab/`, `data/`, or `dsh_workspace/`. The scope is fixed by the repository-root `pytest.ini` (`testpaths = tests`).
- For a focused change, pass the affected test file to the same interpreter instead of a wider scope, for example `.\.venv\Scripts\python.exe -B -m pytest -q tests/test_research_data_contract.py`.
- Run the smallest relevant tests after a focused change.
- For cross-module, governance, release, or shared-kernel changes, run the relevant contract tests and then `.\scripts\test.ps1`.
- For Streamlit changes, verify import/startup and the affected page behavior.
- Do not claim success when tests were skipped or failed; state the exact verification status.

## Git and release safety

- Do not commit, push, create tags, publish releases, delete branches, or rewrite history unless the user explicitly requests that action.
- Before a requested public push, inspect the diff and run the repository's privacy/public-release checks.

## Completion report

When finishing a change, report only what is useful:

1. What changed.
2. Which files were affected.
3. What verification passed or failed.
4. How the user can open or use the result.
5. Any remaining limitation or decision that genuinely needs the user.
