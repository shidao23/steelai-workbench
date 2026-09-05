# Graduation contract v1 public examples

This directory is the executable public example for `SteelAI-Graduation-Core-v1.0`.

- Every identifier starts with `SYN-`; every value is invented for testing.
- The report digests are deliberate repeated-character placeholders, not hashes of real files.
- No real sample mapping, report name, source path, identity or measurement is included.
- `observations.csv` contains both specimen-level values and explicitly labelled reported summaries so they cannot be counted as the same statistical unit.
- Curve points, image fields and EBSD pixels are intentionally absent from these six core tables because graduation v1 does not accept them as specimen observations.

The authoritative field and migration rules are in `config/graduation_data_contract_v1.0.json`.
