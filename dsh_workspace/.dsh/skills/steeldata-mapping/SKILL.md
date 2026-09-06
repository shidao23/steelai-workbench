---
name: steeldata-mapping
description: Preview an unfamiliar SteelData input and persist one structured mapping suggestion. Use for candidate, needs-human, or unsupported intake proposals; never for approval or execution.
---

# SteelData mapping suggestion

Use only `mcp__steeldata_v2__*` tools.

1. Call `status`. Continue only when mode is `suggest`, research-data writes are false, suggestion-record writes are true, and approval is false.
2. Call `list_inputs`, choose an exact relative name, then call `preview_profile` with an explicit v0.2 profile. Work from counts, codes and hashes; do not request raw rows.
3. Build the `submit_mapping_suggestion` input from its Pydantic tool schema. Repeat every profile column in `field_mappings`, including source, target, dtype, units, evidence, confidence and alternatives.
4. Put every ambiguous or unit-incomplete target in `uncertainties`. For an unknown domain, use null domain/profile, no mappings and an explicit `domain_unknown` uncertainty.
5. Submit once, report status, revision and full suggestion SHA-256, then stop.

Never use shell or filesystem tools to inspect SteelData. Never create an approval, change suggestion state, run a batch, modify research data, or hide a mapping decision in rationale. Agent-created records can only be candidate, needs_human or unsupported.
