# SteelAI micro-sam adapter

This directory keeps the microscopy model isolated from the main Streamlit application.

## Scientific boundary

- Original SEM files are read-only and are never copied or modified.
- The smoke test removes the 223-pixel instrument information strip before inference.
- A SAM mask is a prompt response, not a metallographic class label.
- Only human-reviewed masks may be converted into quantitative microstructure evidence.

## Local runtime

The formal deployment uses a dedicated Miniforge environment with GPU-enabled PyTorch and the conda-forge `z5py` package. Its local path is configured in the Git-ignored `config/settings.toml` and `config/local-tools.cmd` files. The project launch adapter normalizes
Windows paths before z5py writes Zarr annotation history. Large environments, weights, caches,
and experimental outputs are intentionally excluded from version control.

Use a separate existing Commit directory for every source image:

- `<local-annotations-root>\B-DQ-1-06.zarr`
- `<local-annotations-root>\R-DQ-1-03.zarr`
