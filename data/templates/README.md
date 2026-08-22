# SteelAI data intake templates

These header-only CSV files are the controlled entry point for new processed observations.

- Keep raw experimental files in an external, read-only source-of-truth location.
- Use only registered `B-DQ` and `R-DQ` sample IDs in the current contract.
- Leave missing measurements blank; never replace missing values with zero.
- A `field_id` is nested within a specimen and is not an independent specimen replicate.
- Use a real `specimen_id` before inferential statistics. Do not invent specimen IDs from image fields.
- Keep `experimental`, `model_estimate`, and `calibrated_estimate` distinct in physics observations.
- Import through the Data & Physics quality panel. The default operation is validation-only and never replaces an existing key.
