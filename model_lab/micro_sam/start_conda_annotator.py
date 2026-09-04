from __future__ import annotations

import os


def _normalize_z5_path(path: object) -> str:
    """Normalize Windows paths for the z5py C++ storage backend."""
    return os.fspath(path).replace("\\", "/")


def main() -> None:
    from micro_sam.sam_annotator import _widgets

    if _widgets.z5py is None:
        raise RuntimeError("z5py is unavailable. Start this adapter from the SteelAI Conda environment.")

    original_zarr_file = _widgets.z5py.ZarrFile

    def windows_safe_zarr_file(path: object, *args, **kwargs):
        return original_zarr_file(_normalize_z5_path(path), *args, **kwargs)

    _widgets.z5py.ZarrFile = windows_safe_zarr_file

    from micro_sam.sam_annotator.annotator_2d import main as annotator_main

    annotator_main()


if __name__ == "__main__":
    main()
