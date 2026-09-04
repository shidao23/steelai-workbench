from __future__ import annotations

import tomllib
from pathlib import Path

from steelai.paths import ROOT


SETTINGS_FILE = ROOT / "config" / "settings.toml"
EXAMPLE_SETTINGS_FILE = ROOT / "config" / "settings.example.toml"


def load_settings() -> dict:
    path = SETTINGS_FILE if SETTINGS_FILE.exists() else EXAMPLE_SETTINGS_FILE
    with path.open("rb") as handle:
        return tomllib.load(handle)


def source_statuses() -> list[dict[str, str]]:
    settings = load_settings()
    rows = []
    for key, value in settings.get("sources", {}).items():
        path = Path(value).expanduser() if value else None
        rows.append({
            "source": key,
            "path": value,
            "status": "available" if path and path.exists() else ("not_configured" if not value else "not_found"),
        })
    return rows
