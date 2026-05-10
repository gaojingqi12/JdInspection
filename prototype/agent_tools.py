from __future__ import annotations

import re
import uuid
import json
from typing import Any

from actions import (
    action_availability,
    action_registry,
    action_requires_confirmation,
    action_title,
    action_unavailable_reason,
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
    direct = parse_direct_tool_call(message)
    if direct:
        return direct
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
    if action_unavailable_reason(action):
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
        "availability": action_availability(action),
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


def normalize_model_tool_call(raw: dict[str, Any] | None, source: str = "native-tool-call") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    name = str(function.get("name") or raw.get("name") or "").strip()
    arguments = function.get("arguments", raw.get("arguments", {}))
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            arguments = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            arguments = {"raw": arguments}
    if not isinstance(arguments, dict):
        arguments = {}
    return validate_tool_call(
        {
            "id": raw.get("id") or f"call_{uuid.uuid4().hex[:12]}",
            "type": raw.get("type") or "function",
            "name": name,
            "arguments": arguments,
            "source": source,
        }
    )


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
    unavailable = action_unavailable_reason(action)
    if unavailable:
        return {
            "ok": False,
            "status": "rejected",
            "error": "not_scheduled_today",
            "message": unavailable,
            "tool_call": valid,
            "action": action,
            "availability": action_availability(action),
        }
    job = start_job(action)
    return {
        "ok": True,
        "status": "queued",
        "tool_call": valid,
        "action": action,
        "job": job,
        "message": f"已开始执行：{action_title(action)}。",
    }


def build_agent_plan(
    message: str,
    intent: dict[str, Any] | None,
    tool_call: dict[str, Any] | None,
    summary: dict[str, Any],
    memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = action_from_tool_call(tool_call)
    plan_type = "tool_execution" if action != "none" else "answer_only"
    calls = [tool_call] if tool_call else []
    return {
        "plan_type": plan_type,
        "goal": str(message or "").strip() or "巡检问答",
        "source": (intent or {}).get("source") or "planner",
        "tool_calls": calls,
        "steps": [
            {
                "type": "tool",
                "action": action,
                "tool_name": call.get("name"),
                "title": action_title(action),
                "reason": (call.get("arguments") or {}).get("reason") or "根据用户意图执行对应巡检工具。",
            }
            for call in calls
        ],
        "context": {
            "inspection_date": summary.get("inspection_date"),
            "memory_last_action": ((memory or {}).get("working_memory") or {}).get("last_action"),
        },
    }


def evaluate_agent_state(
    summary: dict[str, Any],
    assessment: dict[str, Any] | None,
    current_action: str = "none",
    job: dict[str, Any] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assessment = assessment or {}
    checks = [item for item in assessment.get("checks") or [] if isinstance(item, dict)]
    abnormal_items = [item for item in checks if not item.get("normal")]
    abnormal_names = [str(item.get("name") or "") for item in abnormal_items]
    executed_actions = {
        str(item.get("action") or action_from_tool_call(item.get("tool_call")) or "")
        for item in (tool_results or [])
        if isinstance(item, dict)
    }
    job_status = (job or {}).get("status")
    job_failed = job_status in {"failed", "partial", "timeout"}

    repair_types = []
    if "延期提测需求数" in abnormal_names:
        repair_types.append("delayed_test")
    if "延期上线需求数" in abnormal_names:
        repair_types.append("delayed_online")

    repair_issues = []
    for repair in summary.get("repair_inspections", []):
        if not isinstance(repair, dict):
            continue
        status = (repair.get("summary") or {}).get("巡检状态")
        if status not in ("通过", "未触发", None):
            repair_issues.append(
                {
                    "repair_type": repair.get("repair_type"),
                    "title": repair.get("title"),
                    "status": status,
                }
            )

    recommended_actions: list[str] = []
    confirmation_actions: list[str] = []
    if current_action in {"repair_delayed_test", "repair_delayed_online"} and job_status == "success" and "aggregate_report" not in executed_actions:
        recommended_actions.append("aggregate_report")
    if current_action == "thursday_adjustment" and job_status == "success" and "thursday_report" not in executed_actions:
        recommended_actions.append("thursday_report")
    if "delayed_test" in repair_types and "repair_delayed_test" not in executed_actions:
        confirmation_actions.append("repair_delayed_test")
    if "delayed_online" in repair_types and "repair_delayed_online" not in executed_actions:
        confirmation_actions.append("repair_delayed_online")

    needs_human_intervention = bool(job_failed or repair_issues)
    if repair_types and current_action in {"aggregate_report", "daily_inspection", "daily_inspection_with_repair"}:
        needs_human_intervention = True

    return {
        "status": "abnormal" if abnormal_items else "normal",
        "abnormal_items": abnormal_items,
        "needs_repair": bool(repair_types),
        "repair_types": repair_types,
        "needs_refresh_report": any(action in recommended_actions for action in ("aggregate_report", "thursday_report")),
        "needs_human_intervention": needs_human_intervention,
        "repair_issues": repair_issues,
        "job_status": job_status,
        "recommended_actions": recommended_actions,
        "confirmation_actions": confirmation_actions,
        "executed_actions": sorted(action for action in executed_actions if action),
    }


def next_tool_call_after_result(
    current_tool_call: dict[str, Any] | None,
    job: dict[str, Any] | None,
    summary: dict[str, Any],
    tool_results: list[dict[str, Any]] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    current_action = action_from_tool_call(current_tool_call)
    if current_action == "none" or not isinstance(job, dict) or job.get("status") != "success":
        return None

    executed_actions = {
        str(item.get("action") or "")
        for item in (tool_results or [])
        if isinstance(item, dict)
    }
    for action in (evaluation or {}).get("recommended_actions") or []:
        if action in {"aggregate_report", "thursday_report"} and action not in executed_actions:
            return tool_call_from_action(
                action,
                source="evaluator",
                arguments={"reason": "Evaluator 判断需要刷新报告以同步最新执行结果。"},
            )
    if current_action in {"repair_delayed_test", "repair_delayed_online"} and "aggregate_report" not in executed_actions:
        return tool_call_from_action(
            "aggregate_report",
            source="policy",
            arguments={"reason": "修复脚本已完成，需要刷新总报告以汇总最新修复状态。"},
        )
    if current_action == "thursday_adjustment" and "thursday_report" not in executed_actions:
        return tool_call_from_action(
            "thursday_report",
            source="policy",
            arguments={"reason": "日期调整执行完成，需要刷新计划日期调整报告。"},
        )
    return None


def render_tool_chain_summary(tool_results: list[dict[str, Any]] | None, jobs: list[dict[str, Any]] | None) -> str:
    results = [item for item in (tool_results or []) if isinstance(item, dict)]
    job_items = [item for item in (jobs or []) if isinstance(item, dict)]
    if not results:
        return ""

    lines = ["✅ 工具链执行完成："]
    for index, result in enumerate(results, 1):
        action = str(result.get("action") or action_from_tool_call(result.get("tool_call")) or "")
        job = job_items[index - 1] if index - 1 < len(job_items) else result.get("job") or {}
        status = job.get("status") or result.get("status") or "-"
        title = action_title(action) if action else str((result.get("tool_call") or {}).get("name") or "工具")
        lines.append(f"- {title}：{status}")

    last_job = job_items[-1] if job_items else {}
    if last_job.get("status") == "success":
        lines.append("")
        lines.append("已基于最新执行结果刷新上下文，后续对话会读取新的巡检数据。")
    return "\n".join(lines)
