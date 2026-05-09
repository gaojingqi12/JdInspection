from __future__ import annotations

import re
import uuid
from typing import Any

from actions import (
    action_registry,
    action_requires_confirmation,
    action_title,
    detect_action,
    start_job,
)


TOOL_NAME_PREFIX = "run_"
TOOL_CALL_SCHEMA_VERSION = "2026-05-09"


def tool_name_for_action(action: str) -> str:
    return f"{TOOL_NAME_PREFIX}{action}"


def action_from_tool_name(name: str) -> str:
    if not name.startswith(TOOL_NAME_PREFIX):
        return ""
    action = name.removeprefix(TOOL_NAME_PREFIX)
    return action if action in action_registry() else ""


def tool_call_from_action(action: str, source: str = "rules", arguments: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if action not in action_registry():
        return None
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "name": tool_name_for_action(action),
        "arguments": dict(arguments or {}),
        "source": source,
        "schema_version": TOOL_CALL_SCHEMA_VERSION,
    }


def validate_tool_call(tool_call: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(tool_call, dict):
        return None
    name = str(tool_call.get("name") or "").strip()
    action = action_from_tool_name(name)
    if not action:
        return None
    arguments = tool_call.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    return {
        "id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
        "type": "function",
        "name": name,
        "arguments": arguments,
        "source": str(tool_call.get("source") or "unknown"),
        "schema_version": str(tool_call.get("schema_version") or TOOL_CALL_SCHEMA_VERSION),
    }


def action_from_tool_call(tool_call: dict[str, Any] | None) -> str:
    valid = validate_tool_call(tool_call)
    return action_from_tool_name(valid["name"]) if valid else "none"


def detect_tool_call(message: str) -> dict[str, Any] | None:
    action = detect_action(message)
    if action == "none":
        return None
    return tool_call_from_action(action, source="rules")


def tool_title(tool_call_or_action: dict[str, Any] | str | None) -> str:
    action = tool_call_or_action if isinstance(tool_call_or_action, str) else action_from_tool_call(tool_call_or_action)
    return action_title(str(action or ""))


def tool_requires_confirmation(tool_call: dict[str, Any] | None, message: str = "") -> str:
    action = action_from_tool_call(tool_call)
    if action == "none":
        return ""
    return action_requires_confirmation(action, message)


def tool_spec(action: str, item: dict[str, Any]) -> dict[str, Any]:
    risk = item.get("risk") or "safe"
    confirm_phrase = item.get("confirm_phrase") or ""
    return {
        "name": tool_name_for_action(action),
        "action": action,
        "title": item.get("title") or action,
        "description": item.get("description") or "",
        "group": item.get("group") or "其他",
        "risk": risk,
        "confirm_phrase": confirm_phrase,
        "step_count": len(item.get("steps") or []),
        "aliases": item.get("aliases") or [],
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "为什么需要调用该工具，使用一句中文说明。",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "用户是否已经明确确认写操作。只读工具可省略或为 false。",
                },
            },
            "additionalProperties": False,
        },
    }


def tool_registry() -> dict[str, dict[str, Any]]:
    return {
        tool_name_for_action(action): tool_spec(action, item)
        for action, item in action_registry().items()
    }


def public_tools() -> list[dict[str, Any]]:
    return list(tool_registry().values())


def openai_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
            },
        }
        for item in public_tools()
    ]


def tool_catalog_for_prompt() -> list[dict[str, Any]]:
    return [
        {
            "name": item["name"],
            "action": item["action"],
            "title": item["title"],
            "description": item["description"],
            "risk": item["risk"],
            "confirm_phrase": item["confirm_phrase"],
            "aliases": item["aliases"],
        }
        for item in public_tools()
    ]


def resolve_routed_tool_call(routed: dict[str, Any]) -> dict[str, Any] | None:
    tool_call = validate_tool_call(routed.get("tool_call") if isinstance(routed, dict) else None)
    if tool_call:
        tool_call["source"] = str(routed.get("source") or tool_call.get("source") or "llm-router")
        return tool_call

    action = str(routed.get("action") or "none").strip() if isinstance(routed, dict) else "none"
    if action in action_registry():
        return tool_call_from_action(action, source=str(routed.get("source") or "llm-router"))
    return None


def parse_direct_tool_call(message: str) -> dict[str, Any] | None:
    text = (message or "").strip()
    match = re.search(r"(?:tool|工具)\s*:\s*([a-zA-Z0-9_]+)", text)
    if not match:
        return None
    name = match.group(1)
    if name in tool_registry():
        return validate_tool_call({"name": name, "arguments": {}, "source": "direct-tool"})
    action = action_from_tool_name(name)
    if action:
        return tool_call_from_action(action, source="direct-tool")
    return None


def execute_tool_call(tool_call: dict[str, Any] | None) -> dict[str, Any]:
    valid = validate_tool_call(tool_call)
    if not valid:
        return {
            "ok": False,
            "status": "rejected",
            "error": "invalid_tool_call",
            "message": "工具调用无效或工具不存在。",
            "tool_call": tool_call,
        }

    action = action_from_tool_call(valid)
    job = start_job(action)
    return {
        "ok": True,
        "status": "queued",
        "tool_call": valid,
        "action": action,
        "job": job,
        "message": f"已开始执行：{action_title(action)}。",
    }
