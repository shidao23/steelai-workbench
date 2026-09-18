# G09 synthetic import matrix

Every file in this directory is synthetic test data. Nothing here is a laboratory measurement, a real human approval or a production mapping.

- `valid_tensile.csv` exercises the deterministic approved-Profile success path.
- `unknown_unit_tensile.csv` deliberately changes the YS header unit to `ksi`; the approved MPa Profile must not match it.
- `expectations.json` is the machine-readable five-scenario acceptance table used by `tests/test_g09_import_matrix.py`.

Tests copy these bytes into temporary directories. No test output is retained in SteelAI, SteelData or research-data folders.
