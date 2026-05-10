from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


AUDIT_PATH = Path(__file__).resolve().parent / "data" / "tool-audit.jsonl"
AUDIT_LOCK = threading.Lock()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_tool_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    event = {
        "time": now_text(),
        "event": event_type,
        **(payload or {}),
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOCK:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def recent_tool_events(limit: int = 100) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    with AUDIT_LOCK:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def clear_tool_events() -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOCK:
        AUDIT_PATH.write_text("", encoding="utf-8")
