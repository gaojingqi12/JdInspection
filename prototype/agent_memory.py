from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


MEMORY_VERSION = 2
MAX_SESSIONS = 30
MAX_RECENT_REPAIRS = 20
MAX_OPEN_ITEMS = 20
MAX_TEXT = 240

DEFAULT_MEMORY = {
    "version": MEMORY_VERSION,
    "updated_at": "",
    "working_memory": {
        "last_turn": {},
        "last_action": {},
        "last_daily_inspection": {},
        "open_items": [],
        "user_preferences": [],
    },
    "session_summaries": {},
    "recent_repairs": [],
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def truncate_text(value: Any, max_chars: int = MAX_TEXT) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def load_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return fresh_memory()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fresh_memory()
    if not isinstance(data, dict):
        return fresh_memory()
    return normalize_memory(data)


def save_memory(path: Path, memory: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = compact_memory(normalize_memory(memory))
    payload["version"] = MEMORY_VERSION
    payload["updated_at"] = now_text()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fresh_memory() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_MEMORY, ensure_ascii=False))


def normalize_memory(data: dict[str, Any]) -> dict[str, Any]:
    if "working_memory" not in data:
        data = migrate_v1_memory(data)
    memory = fresh_memory()
    memory.update({key: value for key, value in data.items() if key in memory or key in {"version", "updated_at"}})

    working = memory.get("working_memory")
    if not isinstance(working, dict):
        working = {}
    base_working = fresh_memory()["working_memory"]
    base_working.update({key: value for key, value in working.items() if key in base_working})
    memory["working_memory"] = base_working

    if not isinstance(memory.get("session_summaries"), dict):
        memory["session_summaries"] = {}
    if not isinstance(memory.get("recent_repairs"), list):
        memory["recent_repairs"] = []
    return compact_memory(memory)


def migrate_v1_memory(data: dict[str, Any]) -> dict[str, Any]:
    sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
    session_summaries = {}
    for session_id, item in sessions.items():
        if not isinstance(item, dict):
            continue
        session_summaries[session_id] = {
                "summary": truncate_text(item.get("last_answer_preview") or item.get("last_message"), 220),
            "last_message": truncate_text(item.get("last_message")),
            "last_action": item.get("last_action") or "none",
            "updated_at": item.get("updated_at") or "",
            "turn_count": item.get("turn_count", 0),
        }
    return {
        "version": MEMORY_VERSION,
        "updated_at": data.get("updated_at") or "",
        "working_memory": {
            "last_turn": data.get("last_turn") or {},
            "last_action": data.get("last_action") or {},
            "last_daily_inspection": data.get("last_daily_inspection") or {},
            "open_items": [],
            "user_preferences": [],
        },
        "session_summaries": session_summaries,
        "recent_repairs": repair_records_from_daily(data.get("last_daily_inspection") or {}),
    }


def compact_memory(memory: dict[str, Any]) -> dict[str, Any]:
    working = memory.get("working_memory") or {}
    working["open_items"] = list_items(working.get("open_items"))[:MAX_OPEN_ITEMS]
    working["user_preferences"] = dedupe_texts(working.get("user_preferences"))[:MAX_OPEN_ITEMS]

    sessions = memory.get("session_summaries") or {}
    sorted_sessions = sorted(
        [(session_id, item) for session_id, item in sessions.items() if isinstance(item, dict)],
        key=lambda pair: pair[1].get("updated_at", ""),
        reverse=True,
    )
    memory["session_summaries"] = dict(sorted_sessions[:MAX_SESSIONS])

    repairs = list_items(memory.get("recent_repairs"))
    repairs = sorted(repairs, key=lambda item: item.get("updated_at", ""), reverse=True)
    memory["recent_repairs"] = repairs[:MAX_RECENT_REPAIRS]
    memory["working_memory"] = working
    return memory


def summarize_for_prompt(memory: dict[str, Any], session_id: str = "", *, lightweight: bool = False) -> dict[str, Any]:
    memory = normalize_memory(memory)
    working = memory.get("working_memory") or {}
    session = (memory.get("session_summaries") or {}).get(session_id) if session_id else {}
    if not isinstance(session, dict):
        session = {}
    prompt_memory = {
        "last_daily_inspection": working.get("last_daily_inspection") or {},
        "last_action": working.get("last_action") or {},
        "current_session_summary": session,
        "open_items": working.get("open_items") or [],
    }
    if lightweight:
        return {
            "last_action": prompt_memory["last_action"],
            "current_session_summary": prompt_memory["current_session_summary"],
            "open_items": prompt_memory["open_items"][:5],
        }
    prompt_memory["recent_repairs"] = (memory.get("recent_repairs") or [])[:5]
    prompt_memory["user_preferences"] = working.get("user_preferences") or []
    return prompt_memory


def update_memory_from_turn(memory: dict[str, Any], state: dict[str, Any], assessment: dict[str, Any], repairs: list[dict[str, Any]]) -> dict[str, Any]:
    memory = normalize_memory(memory)
    working = memory["working_memory"]
    session_id = str(state.get("active_session_id") or "")
    message = truncate_text(state.get("message"), 200)
    action = str(state.get("action") or "none")
    answer = truncate_text(state.get("answer") or "".join(state.get("answer_parts") or []), 320)

    working["last_turn"] = {
        "session_id": session_id,
        "message": message,
        "action": action,
        "intent": state.get("intent") or {},
        "updated_at": now_text(),
    }
    working["last_action"] = {
        "action": action,
        "job": compact_job(state.get("job")),
        "updated_at": now_text(),
    }
    if assessment:
        working["last_daily_inspection"] = {
            "inspection_date": assessment.get("inspection_date") or (state.get("summary") or {}).get("inspection_date"),
            "display_domain": (state.get("summary") or {}).get("display_domain"),
            "status": assessment.get("status"),
            "checks": compact_checks(assessment.get("checks") or []),
            "abnormal_items": compact_checks(assessment.get("abnormal_items") or []),
            "updated_at": now_text(),
        }

    open_items = list_items(working.get("open_items"))
    open_items = [item for item in open_items if item.get("source") != "daily_inspection"]
    for item in compact_checks(assessment.get("abnormal_items") or []):
        open_items.append(
            {
                "source": "daily_inspection",
                "title": item.get("name"),
                "status": "open",
                "detail": f"{item.get('value')} / 阈值 {item.get('threshold')}",
                "updated_at": now_text(),
            }
        )
    working["open_items"] = open_items

    session_summaries = memory.setdefault("session_summaries", {})
    previous_session = session_summaries.get(session_id) if session_id else {}
    if not isinstance(previous_session, dict):
        previous_session = {}
    turn_count = int(previous_session.get("turn_count") or 0) + 1
    session_summaries[session_id] = {
        "summary": summarize_session_text(previous_session.get("summary"), message, answer, action),
        "last_message": message,
        "last_action": action,
        "updated_at": now_text(),
        "turn_count": turn_count,
    }

    if repairs:
        memory["recent_repairs"] = repairs + list_items(memory.get("recent_repairs"))
    return compact_memory(memory)


def compact_job(job: Any) -> dict[str, Any] | None:
    if not isinstance(job, dict):
        return None
    return {
        "id": job.get("id"),
        "action": job.get("action"),
        "title": job.get("title"),
        "status": job.get("status"),
        "updated_at": job.get("updated_at"),
    }


def compact_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "name": item.get("name"),
                "value": item.get("value"),
                "threshold": item.get("threshold"),
                "normal": item.get("normal"),
                "abnormal_reason": item.get("abnormal_reason"),
            }
        )
    return compacted[:12]


def repair_records_from_daily(daily: dict[str, Any]) -> list[dict[str, Any]]:
    repairs = daily.get("repairs") if isinstance(daily, dict) else []
    records = []
    for repair in list_items(repairs):
        for detail in list_items(repair.get("details")):
            records.append(
                {
                    "repair_type": repair.get("repair_type"),
                    "status": repair.get("status"),
                    "code": detail.get("code"),
                    "name": detail.get("name"),
                    "owner": detail.get("owner"),
                    "url": detail.get("url"),
                    "updated_at": daily.get("updated_at") or "",
                }
            )
    return records


def summarize_session_text(previous: Any, message: str, answer: str, action: str) -> str:
    parts = []
    if previous:
        parts.append(truncate_text(previous, 180))
    if action and action != "none":
        parts.append(f"执行/识别动作：{action}")
    if message:
        parts.append(f"用户：{message}")
    if answer:
        parts.append(f"助手：{answer}")
    return truncate_text("；".join(parts), 320)


def list_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def dedupe_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen = set()
    result = []
    for item in value:
        text = truncate_text(item, 160)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
