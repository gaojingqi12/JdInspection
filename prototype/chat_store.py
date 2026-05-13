from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


CHAT_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "chat-history.json"
CHAT_LOCK = threading.Lock()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def chat_message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content, "created_at": now_text()}


def default_chat_messages() -> list[dict]:
    return []


def chat_title_from_message(message: str) -> str:
    title = re.sub(r"\s+", " ", (message or "").strip())
    if not title:
        return "新对话"
    return title[:18] + ("..." if len(title) > 18 else "")


def load_chat_store() -> dict:
    store = read_json_file(CHAT_HISTORY_PATH, {"sessions": [], "active_session_id": ""})
    if not isinstance(store, dict):
        store = {"sessions": [], "active_session_id": ""}
    sessions = store.get("sessions")
    if not isinstance(sessions, list):
        sessions = []
    store["sessions"] = sessions
    store.setdefault("active_session_id", "")
    return store


def save_chat_store(store: dict) -> None:
    write_json_file(CHAT_HISTORY_PATH, store)


def create_chat_session(store: dict, title: str = "新对话") -> dict:
    session = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "created_at": now_text(),
        "updated_at": now_text(),
        "messages": default_chat_messages(),
    }
    store.setdefault("sessions", []).append(session)
    store["active_session_id"] = session["id"]
    return session


def find_chat_session(store: dict, session_id: str) -> dict | None:
    for session in store.get("sessions", []):
        if session.get("id") == session_id:
            return session
    return None


def chat_session_summary(session: dict) -> dict:
    messages = session.get("messages") or []
    last = messages[-1] if messages else {}
    return {
        "id": session.get("id"),
        "title": session.get("title") or "新对话",
        "created_at": session.get("created_at") or "",
        "updated_at": session.get("updated_at") or "",
        "last_message": str(last.get("content") or "")[:42],
        "message_count": len(messages),
    }


def sorted_chat_sessions(store: dict) -> list[dict]:
    sessions = sorted(store.get("sessions", []), key=lambda item: item.get("updated_at", ""), reverse=True)
    return [chat_session_summary(session) for session in sessions[:50]]


def begin_chat_turn(message: str, session_id: str) -> tuple[str, list[dict]]:
    with CHAT_LOCK:
        store = load_chat_store()
        session = find_chat_session(store, session_id) if session_id else None
        if not session:
            session = create_chat_session(store)
        previous_messages = list(session.get("messages") or [])
        if session.get("title") == "新对话":
            session["title"] = chat_title_from_message(message)
        session.setdefault("messages", []).append(chat_message("user", message))
        session["updated_at"] = now_text()
        store["active_session_id"] = session["id"]
        active_session_id = session["id"]
        save_chat_store(store)
    return active_session_id, previous_messages


def finish_chat_turn(session_id: str, answer: str) -> list[dict]:
    with CHAT_LOCK:
        store = load_chat_store()
        session = find_chat_session(store, session_id)
        if session and answer:
            session.setdefault("messages", []).append(chat_message("assistant", answer))
            session["updated_at"] = now_text()
            store["active_session_id"] = session_id
            save_chat_store(store)
        return sorted_chat_sessions(store)
