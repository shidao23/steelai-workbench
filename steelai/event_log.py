from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from steelai.paths import PROJECT_LOG


EVENT_FILE = PROJECT_LOG / "events.jsonl"


def record_event(event_type: str, title: str, summary: str, evidence: dict[str, Any] | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    PROJECT_LOG.mkdir(parents=True, exist_ok=True)
    event = {
        "event_id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "event_type": event_type,
        "title": title,
        "summary": summary,
        "evidence": evidence or {},
        "tags": tags or [],
    }
    with EVENT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events() -> list[dict[str, Any]]:
    if not EVENT_FILE.exists():
        return []
    events = []
    with EVENT_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def safe_output_filename(prefix: str, suffix: str = ".md") -> str:
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in prefix)
    return f"{stamp}_{clean}{suffix}"


def write_text_artifact(directory: Path, filename: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / Path(filename).name
    path.write_text(content, encoding="utf-8")
    return path
