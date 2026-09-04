# SteelAI DSH Sidecar Workspace

This workspace intentionally contains no raw or processed research data.

- Use only the `mcp__steelai__*` tools for SteelAI research facts.
- Never inspect parent directories, local configuration, raw microscopy files, or
  `data/processed` through shell or filesystem tools.
- Never modify SteelAI data. You may write user-requested notes only under `results/`.
- Treat empirical formulas as model estimates, not experimental measurements.
- Do not infer causation from directional comparisons.
- Keep EBSD acquisition scales separate and respect the validation tool's scientific
  gates.
- If the SteelAI MCP server is unavailable, stop and report the bridge error instead
  of bypassing the bridge.
