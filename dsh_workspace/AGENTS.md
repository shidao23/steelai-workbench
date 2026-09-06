# SteelAI DSH Sidecar Workspace

This workspace intentionally contains no raw or processed research data.

- Use only the `mcp__steelai__*` tools for SteelAI research facts. For structural
  intake suggestions, use only `mcp__steeldata_v2__status`, `list_inputs`,
  `preview_profile`, and `submit_mapping_suggestion` from the separately
  registered suggestion server.
- Never inspect parent directories, local configuration, raw microscopy files, or
  `data/processed` through shell or filesystem tools.
- Never modify SteelAI or SteelData research data. The only SteelData write allowed
  is a structured mapping-suggestion record through its MCP tool. Do not approve
  profiles or run SteelData batches. You may write user-requested notes only under
  `results/`.
- Treat empirical formulas as model estimates, not experimental measurements.
- Do not infer causation from directional comparisons.
- Keep EBSD acquisition scales separate and respect the validation tool's scientific
  gates.
- If the SteelAI MCP server is unavailable, stop and report the bridge error instead
  of bypassing the bridge.
