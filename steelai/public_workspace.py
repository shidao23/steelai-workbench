from __future__ import annotations

import json
import shutil
from pathlib import Path


def _copy_public_fixture(source: Path, target: Path) -> str:
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise FileExistsError(f"Refusing to overwrite non-matching local file: {target}")
        return "reused"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "created"


def prepare_public_workspace(root: Path | None = None) -> dict:
    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    sources = [
        *sorted((repository / "data" / "examples" / "processed").glob("*.csv")),
        repository / "data" / "examples" / "index" / "evidence_index.csv",
    ]
    if not sources or any(not source.is_file() for source in sources):
        raise FileNotFoundError("Public synthetic fixture set is incomplete.")

    copied: list[dict[str, str]] = []
    for source in sources:
        if source.parent.name == "processed":
            target = repository / "data" / "processed" / source.name
        else:
            target = repository / "data" / "index" / source.name
        copied.append(
            {
                "source": source.relative_to(repository).as_posix(),
                "target": target.relative_to(repository).as_posix(),
                "status": _copy_public_fixture(source, target),
            }
        )
    return {
        "schema_version": "1.0",
        "status": "passed",
        "data_classification": "public_synthetic_only",
        "files": copied,
    }


def main() -> int:
    result = prepare_public_workspace()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
