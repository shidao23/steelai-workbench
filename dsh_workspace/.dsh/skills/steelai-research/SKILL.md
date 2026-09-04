---
name: steelai-research
description: Use SteelAI's read-only MCP tools for evidence-bounded wear-resistant-steel research.
---

# SteelAI research through DSH

Use this skill whenever the user asks about SteelAI samples, B/R comparisons,
physics cards, EBSD, AutoDimple, or the scientific evidence boundary.

1. Call `mcp__steelai__get_bridge_status` once when bridge availability is unclear.
2. Obtain exact sample identifiers from `mcp__steelai__list_samples`; do not guess IDs.
3. Use only `mcp__steelai__*` tools for research data. Do not use filesystem or shell
   tools to inspect the parent SteelAI directory, `data/processed`, `outputs`, or local
   configuration.
4. Treat Physics Card values as empirical model estimates, never measurements.
5. Keep low- and high-resolution EBSD results separate. Fields and segmented objects
   are not independent specimen replicates.
6. Before a mechanism or evidence-strength statement, call
   `mcp__steelai__get_evidence_validation_summary` and obey its gates.
7. If the MCP bridge is unavailable, report that condition. Never bypass it by reading
   raw files or asking the user to upload confidential research data.

Answer in Chinese with confirmed facts, current judgment, evidence limits, and next
actions clearly separated.
