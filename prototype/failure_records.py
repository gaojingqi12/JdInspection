from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


FAILURE_RECORD_PATH = Path(__file__).resolve().parent / "data" / "failure-records.jsonl"
FAILURE_LOCK = threading.Lock()
FAILURE_STATUSES = {"failed", "partial", "timeout"}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def compact_text(value: Any, max_chars: int = 1200) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.splitlines())
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def classify_failure(step: dict[str, Any], job: dict[str, Any]) -> str:
    text = " ".join(
        compact_text(value, 400)
        for value in (
            step.get("status"),
            step.get("error"),
            step.get("stdout_tail"),
            step.get("stderr_tail"),
            job.get("error"),
        )
        if value
    ).lower()

    if "networkidle" in text:
        return "networkidle_timeout"
    if "timeout" in text or "超时" in text:
        if "locator" in text or "wait_for" in text or "waiting for locator" in text:
            return "locator_timeout"
        return "timeout"
    if "dashboard iframe" in text or "没找到目标 dashboard" in text or "frame" in text and "没找到" in text:
        return "iframe_not_found"
    if "tooltip" in text or "echarts" in text or "未能从 dom" in text or "解析" in text:
        return "metric_parse_failed"
    if "expect_download" in text or "download" in text or "下载" in text:
        return "download_failed"
    if step.get("returncode") not in (None, 0):
        return "script_nonzero_exit"
    if step.get("status") == "timeout" or job.get("status") == "timeout":
        return "timeout"
    return "unknown"


def optimization_hint(category: str) -> str:
    return {
        "networkidle_timeout": "页面存在持续请求时不要把 networkidle 作为硬失败条件，优先等待关键 DOM 或数据区出现。",
        "locator_timeout": "定位器等待超时，优先检查页面 DOM 是否变更、筛选条件是否导致空表、等待目标是否过窄。",
        "iframe_not_found": "目标 iframe 未出现，优先检查登录态、页面跳转地址、BI 菜单加载和 iframe URL 规则。",
        "metric_parse_failed": "指标解析失败，优先补充 DOM/ECharts/截图 OCR 的多路兜底，或更新指标标题与字段映射。",
        "download_failed": "下载失败，优先检查下载按钮定位、浏览器下载权限、文件稳定等待和登录态。",
        "script_nonzero_exit": "脚本非 0 退出，优先查看 stderr/stdout 尾部和最近截图定位具体异常。",
        "timeout": "步骤达到执行上限，优先缩短固定等待、增加关键节点检测，或拆分为更小的可恢复步骤。",
    }.get(category, "先查看失败步骤的 error/stdout/stderr 和截图，再归类为可优化的等待、定位、解析或登录态问题。")


def failure_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [
        item
        for item in job.get("step_results", [])
        if isinstance(item, dict) and item.get("status") in FAILURE_STATUSES
    ]
    if steps:
        return steps
    failed_step = job.get("failed_step")
    if isinstance(failed_step, int):
        return [
            item
            for item in job.get("step_results", [])
            if isinstance(item, dict) and item.get("index") == failed_step
        ]
    return []


def build_failure_record(job: dict[str, Any]) -> dict[str, Any]:
    failed_steps = failure_steps(job)
    recorded_steps = []
    categories = []
    for step in failed_steps:
        category = classify_failure(step, job)
        categories.append(category)
        recorded_steps.append(
            {
                "index": step.get("index"),
                "label": step.get("label"),
                "status": step.get("status"),
                "category": category,
                "reason": compact_text(step.get("error") or step.get("stderr_tail") or step.get("stdout_tail") or job.get("error")),
                "suggestion": optimization_hint(category),
                "attempts": step.get("attempts"),
                "retry_limit": step.get("retry_limit"),
                "timeout_seconds": step.get("timeout_seconds"),
                "returncode": step.get("returncode"),
                "command": step.get("command"),
                "cwd": step.get("cwd"),
                "stdout_tail": compact_text(step.get("stdout_tail")),
                "stderr_tail": compact_text(step.get("stderr_tail")),
                "started_at": step.get("started_at"),
                "finished_at": step.get("finished_at"),
            }
        )

    primary_category = categories[0] if categories else classify_failure({}, job)
    primary_step_reason = recorded_steps[0].get("reason") if recorded_steps else ""
    return {
        "id": f"failure_{uuid.uuid4().hex[:12]}",
        "recorded_at": now_text(),
        "job_id": job.get("id"),
        "action": job.get("action"),
        "title": job.get("title"),
        "status": job.get("status"),
        "primary_category": primary_category,
        "primary_reason": compact_text(primary_step_reason or job.get("error")),
        "suggestion": optimization_hint(primary_category),
        "failed_step": job.get("failed_step"),
        "failed_step_label": job.get("failed_step_label"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "returncode": job.get("returncode"),
        "current_step": job.get("current_step"),
        "total_steps": job.get("total_steps"),
        "failed_steps": recorded_steps,
        "logs_tail": list(job.get("logs") or [])[-30:],
    }


def record_job_failure(job: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(job, dict) or job.get("status") not in FAILURE_STATUSES:
        return None
    record = build_failure_record(job)
    FAILURE_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FAILURE_LOCK:
        with FAILURE_RECORD_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def recent_failure_records(limit: int = 100) -> list[dict[str, Any]]:
    if not FAILURE_RECORD_PATH.exists():
        return []
    with FAILURE_LOCK:
        lines = FAILURE_RECORD_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records
