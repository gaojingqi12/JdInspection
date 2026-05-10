from __future__ import annotations

from typing import Any


TERMINAL_FAILURES = {"failed", "partial", "timeout"}
STEP_FAILURES = {"failed", "timeout"}
REPAIR_FAILURE_STATUSES = {"执行失败", "存在失败项", "需人工复核", "JSON异常", "无当天JSON"}
REPAIR_RELEVANT_ACTIONS = {
    "daily_inspection",
    "daily_inspection_with_repair",
    "aggregate_report",
    "repair_delayed_test",
    "repair_delayed_online",
}


def is_failed_job(job: dict[str, Any] | None) -> bool:
    return isinstance(job, dict) and job.get("status") in TERMINAL_FAILURES


def render_failure_recovery(job: dict[str, Any] | None, summary: dict[str, Any]) -> str:
    repair_failures = failed_repair_inspections(summary) if is_repair_relevant_job(job) else []
    if not is_failed_job(job) and not repair_failures:
        return ""

    job = job or {}
    title = job.get("title") or job.get("action") or "巡检任务"
    failed_steps = failed_step_list(job) if is_failed_job(job) else []
    failed = failed_steps[0] if failed_steps else None
    completed = [item for item in job.get("step_results", []) if item.get("status") == "success"]
    pending = [item for item in job.get("step_results", []) if item.get("status") in {"queued", "skipped", "failed", "timeout"}]
    repair_lines = repair_detail_lines(summary)
    unhandled_lines = unhandled_requirement_lines(summary)
    detail = failure_detail(failed_steps, job, repair_failures)
    heading = f"⚠️ {title}部分完成" if job.get("status") == "partial" else f"⚠️ {title}失败恢复"

    lines = [
        heading,
        "",
        "失败位置：",
        *failure_position_lines(failed_steps, job, repair_failures),
        "",
        "已完成：",
    ]
    lines.extend(completed_lines(completed, job, repair_failures))
    lines.append("")
    lines.append("未完成：")
    lines.extend([f"- {item.get('label')}" for item in pending] or ["- 无"])
    lines.append("")
    lines.append("未处理需求：")
    lines.extend(unhandled_lines or ["- 未读取到未处理需求明细；可能失败发生在筛选、打开详情页或写入修复 JSON 之前。"])
    lines.append("")
    lines.append("失败详情：")
    lines.extend(detail)
    lines.append("")
    lines.append("负责人和链接：")
    owner_link_lines = repair_lines or unhandled_lines
    lines.extend(owner_link_lines or ["- 暂未获取到修复需求负责人或跳转链接"])
    lines.append("")
    lines.append("下一步建议：")
    lines.extend(next_steps(job, failed, owner_link_lines))
    return "\n".join(lines)


def failed_repair_inspections(summary: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for repair in summary.get("repair_inspections", []):
        if not isinstance(repair, dict):
            continue
        repair_summary = repair.get("summary") or {}
        status = str(repair_summary.get("巡检状态") or "")
        script = repair.get("script") or {}
        script_status = str(script.get("status") or "")
        trigger = repair.get("trigger") or {}
        triggered = bool(trigger.get("triggered"))
        if status == "无当天JSON" and script_status == "skipped":
            continue
        if status in REPAIR_FAILURE_STATUSES and (triggered or status != "无当天JSON"):
            failures.append(repair)
        elif script_status in TERMINAL_FAILURES or script_status == "missing_script":
            failures.append(repair)
    return failures


def is_repair_relevant_job(job: dict[str, Any] | None) -> bool:
    if not isinstance(job, dict):
        return False
    return str(job.get("action") or "") in REPAIR_RELEVANT_ACTIONS


def failure_position_lines(
    steps: list[dict[str, Any]],
    job: dict[str, Any],
    repair_failures: list[dict[str, Any]],
) -> list[str]:
    if steps:
        return [f"- {format_step(step)}" for step in steps]
    if is_failed_job(job):
        return [f"- {job.get('error') or '未定位到具体步骤'}"]
    if repair_failures:
        return [
            f"- 修复汇总：{repair.get('title') or repair_type_label(str(repair.get('repair_type') or ''))}"
            f"（{(repair.get('summary') or {}).get('巡检状态') or '未知状态'}）"
            for repair in repair_failures
        ]
    return ["- 未定位到具体步骤"]


def completed_lines(completed: list[dict[str, Any]], job: dict[str, Any], repair_failures: list[dict[str, Any]]) -> list[str]:
    if completed:
        return [f"- {format_completed_step(item)}" for item in completed]
    if job.get("status") == "success" and repair_failures:
        return ["- 巡检脚本已执行完成", "- 汇总报告已生成，但修复结果需要人工复核"]
    return ["- 暂无已完成步骤"]


def failed_step(job: dict[str, Any]) -> dict[str, Any] | None:
    steps = failed_step_list(job)
    return steps[0] if steps else None


def failed_step_list(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [
        item
        for item in job.get("step_results", [])
        if item.get("status") in STEP_FAILURES
    ]
    if steps:
        return steps
    for item in job.get("step_results", []):
        if item.get("status") in TERMINAL_FAILURES:
            return [item]
    index = job.get("failed_step")
    if isinstance(index, int):
        for item in job.get("step_results", []):
            if item.get("index") == index:
                return [item]
    return []


def format_step(step: dict[str, Any] | None) -> str:
    if not step:
        return "-"
    index = step.get("index") or "-"
    label = step.get("label") or "-"
    status = step.get("status") or "-"
    attempts = step.get("attempts")
    retry_limit = step.get("retry_limit")
    retry_text = ""
    if isinstance(attempts, int) and isinstance(retry_limit, int) and retry_limit:
        retry_text = f"，已尝试 {attempts} 次"
    return f"步骤 {index}：{label}（{status}{retry_text}）"


def format_completed_step(step: dict[str, Any]) -> str:
    label = step.get("label") or "-"
    attempts = step.get("attempts")
    if isinstance(attempts, int) and attempts > 1:
        return f"{label}（重试后成功，第 {attempts} 次）"
    return str(label)


def failure_detail(steps: list[dict[str, Any]], job: dict[str, Any], repair_failures: list[dict[str, Any]]) -> list[str]:
    lines = []
    for step in steps:
        label = step.get("label") or "失败步骤"
        lines.append(f"- {label}：")
        if step.get("returncode") is not None:
            lines.append(f"  returncode：{step.get('returncode')}")
        if step.get("error"):
            lines.append(f"  错误：{step.get('error')}")
        stderr = tail_line(step.get("stderr_tail"))
        stdout = tail_line(step.get("stdout_tail"))
        if stderr:
            lines.append(f"  stderr：{stderr}")
        elif stdout:
            lines.append(f"  stdout：{stdout}")
    if not lines and job.get("error"):
        lines.append(f"- 错误：{job.get('error')}")
    for repair in repair_failures:
        repair_summary = repair.get("summary") or {}
        script = repair.get("script") or {}
        status = repair_summary.get("巡检状态") or "-"
        title = repair.get("title") or repair_type_label(str(repair.get("repair_type") or ""))
        note = "；".join(str(item) for item in repair_summary.get("备注") or [] if item)
        script_error = script.get("error") or ""
        if script_error:
            lines.append(f"- {title}：{status}，{script_error}")
        elif note:
            lines.append(f"- {title}：{status}，{note}")
        else:
            lines.append(f"- {title}：{status}")
    return lines or ["- 未读取到错误详情，请查看任务日志"]


def tail_line(value: Any, max_chars: int = 260) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.splitlines()[-3:])
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def repair_detail_lines(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for repair in summary.get("repair_inspections", []):
        repair_type = repair_type_label(str(repair.get("repair_type") or ""))
        repair_summary = repair.get("summary") or {}
        details = repair_summary.get("成功明细") or []
        failures = repair_summary.get("失败明细") or []
        missing = repair_summary.get("缺失字段明细") or []
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                owner = item.get("研发负责人") or "未获取"
                url = item.get("跳转地址") or item.get("页面URL") or "未获取"
                lines.append(
                    f"- {repair_type}：{item.get('需求编码') or '-'} | "
                    f"负责人：{owner}（{'已拿到' if owner != '未获取' else '未拿到'}） | "
                    f"链接：{url}（{'已拿到' if url != '未获取' else '未拿到'}）"
                )
        if isinstance(failures, list):
            for item in failures:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {repair_type}失败：{item.get('需求编码') or '-'} | "
                    f"负责人：未获取（未拿到） | 链接：未获取（未拿到）"
                )
        if isinstance(missing, list):
            for item in missing:
                if not isinstance(item, dict):
                    continue
                fields = item.get("缺失字段") or []
                lines.append(
                    f"- {repair_type}需复核：{item.get('需求编码') or '-'} | "
                    f"缺失：{'、'.join(fields) if isinstance(fields, list) else fields}"
                )
    return lines


def unhandled_requirement_lines(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for repair in summary.get("repair_inspections", []):
        if not isinstance(repair, dict):
            continue
        repair_type = repair_type_label(str(repair.get("repair_type") or ""))
        repair_summary = repair.get("summary") or {}
        success_codes = demand_codes(repair_summary.get("成功明细"))
        failure_items = repair_summary.get("失败明细") or []
        missing_items = repair_summary.get("缺失字段明细") or []
        raw_json = repair.get("raw_json") if isinstance(repair.get("raw_json"), dict) else {}
        raw_results = raw_json.get("results") if isinstance(raw_json, dict) else []

        for item in failure_items if isinstance(failure_items, list) else []:
            if isinstance(item, dict):
                lines.append(requirement_line(repair_type, item, "失败"))
        for item in missing_items if isinstance(missing_items, list) else []:
            if isinstance(item, dict):
                lines.append(requirement_line(repair_type, item, "需复核"))
        for item in raw_results if isinstance(raw_results, list) else []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("需求编码") or item.get("code") or "").strip()
            if code and code in success_codes:
                continue
            if any(code and code in line for line in lines):
                continue
            lines.append(requirement_line(repair_type, item, "未确认修复"))
    return lines


def demand_codes(items: Any) -> set[str]:
    codes: set[str] = set()
    if not isinstance(items, list):
        return codes
    for item in items:
        if isinstance(item, dict):
            code = str(item.get("需求编码") or item.get("code") or "").strip()
            if code:
                codes.add(code)
    return codes


def requirement_line(repair_type: str, item: dict[str, Any], status: str) -> str:
    code = item.get("需求编码") or item.get("code") or "-"
    name = item.get("需求名称") or item.get("name") or ""
    owner = item.get("研发负责人") or item.get("owner") or "未获取"
    url = item.get("跳转地址") or item.get("页面URL") or item.get("url") or "未获取"
    reason = item.get("失败原因") or item.get("缺失字段") or item.get("reason") or ""
    if isinstance(reason, list):
        reason = "、".join(str(value) for value in reason)
    suffix = f" | 原因：{reason}" if reason else ""
    name_part = f" | {name}" if name else ""
    return (
        f"- {repair_type}：{code}{name_part} | 状态：{status} | "
        f"负责人：{owner} | 链接：{url}{suffix}"
    )


def repair_type_label(repair_type: str) -> str:
    return {
        "delayed_test": "延期提测",
        "delayed_online": "延期上线",
    }.get(repair_type, repair_type or "修复")


def next_steps(job: dict[str, Any], step: dict[str, Any] | None, repair_lines: list[str]) -> list[str]:
    label = (step or {}).get("label") or ""
    suggestions = []
    if job.get("status") == "partial":
        suggestions.append("- 失败项已自动重试，其他巡检步骤已继续执行。")
        suggestions.append("- 优先处理失败项；处理后可单独重跑该巡检项，再刷新总报告。")
    elif "修复" in label:
        suggestions.append("- 优先打开失败步骤日志，确认是否是页面加载、权限、元素定位或数据为空导致。")
        suggestions.append("- 若已拿到负责人/链接，先按上方明细人工复核；未拿到则重新运行对应修复脚本。")
    elif "生成日常巡检报告" in label:
        suggestions.append("- 前置巡检已完成，优先检查汇总脚本输出和 summary JSON 是否可写。")
        suggestions.append("- 修复脚本可能已经执行过，请查看修复报告确认负责人和链接。")
    elif label:
        suggestions.append(f"- 修复或重跑“{label}”，成功后再继续后续巡检步骤。")
    else:
        suggestions.append("- 查看任务日志定位失败原因，然后重跑该巡检任务。")
    if not repair_lines:
        suggestions.append("- 当前没有可用负责人/链接，说明失败发生在打开详情页或写入修复 JSON 之前。")
    suggestions.append("- 处理后可再次发起同一巡检动作，agent 会继续汇总最新结果。")
    return suggestions
