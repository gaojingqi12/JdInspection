from __future__ import annotations

import re
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from failure_records import record_job_failure
from schedule_policy import action_schedule_status, file_modified_date, fixed_cycle_data_freshness, parse_date


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_XUNJIAN_PYTHON = Path(sys.executable)
JOB_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60 * 60
JOB_WAIT_BUFFER_SECONDS = 5 * 60
DAILY_INSPECTION_RETRY_LIMIT = 1
DAILY_OKR_TIMEOUT_SECONDS = 10 * 60
DAILY_AI_TIMEOUT_SECONDS = 12 * 60
DAILY_CONTINUOUS_DELIVERY_TIMEOUT_SECONDS = 10 * 60
SINGLE_DAILY_STEP_TIMEOUT_SECONDS = 12 * 60
AGGREGATE_REPORT_TIMEOUT_SECONDS = 8 * 60
AGGREGATE_WITH_REPAIR_TIMEOUT_SECONDS = 50 * 60
AGGREGATE_REPAIR_SCRIPT_TIMEOUT_SECONDS = 20 * 60
REPAIR_ACTION_TIMEOUT_SECONDS = 35 * 60
THURSDAY_ADJUSTMENT_TIMEOUT_SECONDS = 45 * 60


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def python_bin() -> str:
    configured_value = os.environ.get("XUNJIAN_PYTHON", "").strip()
    if configured_value:
        configured = Path(configured_value).expanduser()
        if configured.exists():
            return str(configured)
        resolved = shutil.which(configured_value)
        if resolved:
            return resolved
    return str(DEFAULT_XUNJIAN_PYTHON)


def append_job_log(job_id: str, text: str) -> None:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.setdefault("logs", []).append(f"[{now_text()}] {text}")
        job["logs"] = job["logs"][-200:]
        job["updated_at"] = now_text()


def set_job(job_id: str, **updates) -> None:
    with JOB_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)
            JOBS[job_id]["updated_at"] = now_text()


def record_failure_for_job(job_id: str) -> None:
    with JOB_LOCK:
        job = dict(JOBS.get(job_id) or {})
        if not job or job.get("failure_recorded") or job.get("status") not in {"failed", "partial", "timeout"}:
            return
        JOBS[job_id]["failure_recorded"] = True

    try:
        record = record_job_failure(job)
    except Exception as exc:
        with JOB_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["failure_recorded"] = False
        append_job_log(job_id, f"写入失败记录失败：{exc}")
        return

    if not record:
        return
    with JOB_LOCK:
        if job_id in JOBS:
            JOBS[job_id]["failure_record_id"] = record.get("id")
            JOBS[job_id]["failure_recorded_at"] = record.get("recorded_at")
            JOBS[job_id]["updated_at"] = now_text()
    append_job_log(job_id, f"已记录失败原因：{record.get('primary_category')}（{record.get('id')}）")


def run_command(job_id: str, command: list[str], cwd: Path, timeout_seconds: int | None = None) -> dict:
    timeout_seconds = int(timeout_seconds or DEFAULT_COMMAND_TIMEOUT_SECONDS)
    display = " ".join(command)
    append_job_log(job_id, f"开始执行：{display}")
    started_at = now_text()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_tail = tail_text(exc.stdout or "")
        stderr_tail = tail_text(exc.stderr or "")
        if stdout_tail:
            append_job_log(job_id, "stdout:\n" + stdout_tail)
        if stderr_tail:
            append_job_log(job_id, "stderr:\n" + stderr_tail)
        append_job_log(job_id, f"执行超时，timeout={timeout_seconds}")
        return {
            "status": "timeout",
            "returncode": None,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "started_at": started_at,
            "finished_at": now_text(),
            "error": f"执行超过 {timeout_seconds} 秒",
        }
    except Exception as exc:
        append_job_log(job_id, f"执行异常：{exc}")
        return {
            "status": "failed",
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "started_at": started_at,
            "finished_at": now_text(),
            "error": str(exc),
        }

    stdout_tail = tail_text(completed.stdout or "", 3000)
    stderr_tail = tail_text(completed.stderr or "", 3000)
    if completed.stdout:
        append_job_log(job_id, "stdout:\n" + stdout_tail)
    if completed.stderr:
        append_job_log(job_id, "stderr:\n" + stderr_tail)
    append_job_log(job_id, f"执行结束，returncode={completed.returncode}")
    return {
        "status": "success" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "started_at": started_at,
        "finished_at": now_text(),
        "error": "" if completed.returncode == 0 else "脚本返回非 0 状态",
    }


def tail_text(value: str, max_chars: int = 3000) -> str:
    if len(value) <= max_chars:
        return value.strip()
    return value[-max_chars:].strip()


def step(
    command: list[str],
    cwd: Path,
    label: str,
    retry_limit: int = 0,
    continue_on_failure: bool = False,
    timeout_seconds: int | None = None,
) -> dict:
    return {
        "command": command,
        "cwd": cwd,
        "label": label,
        "retry_limit": retry_limit,
        "continue_on_failure": continue_on_failure,
        "timeout_seconds": timeout_seconds or DEFAULT_COMMAND_TIMEOUT_SECONDS,
    }


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def daily_dir() -> Path:
    return ROOT_DIR / "daily-inspection-skill"


def friday_dir() -> Path:
    return ROOT_DIR / "friday-inspection-skill"


def thursday_dir() -> Path:
    return ROOT_DIR / "thursday-to-friday-adjustment"


def delayed_test_repair_dir() -> Path:
    preferred = daily_dir() / "reschedule-delayed-test"
    legacy = daily_dir() / "reschedule-delayed-test "
    return preferred if preferred.exists() else legacy


def daily_inspection_steps(skip_repair: bool = True) -> list[dict]:
    root = daily_dir()
    py = python_bin()
    aggregate = [py, "joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py"]
    aggregate_timeout = AGGREGATE_WITH_REPAIR_TIMEOUT_SECONDS
    if skip_repair:
        aggregate.append("--skip-repair")
        aggregate_timeout = AGGREGATE_REPORT_TIMEOUT_SECONDS
    else:
        aggregate.extend(["--repair-timeout", str(AGGREGATE_REPAIR_SCRIPT_TIMEOUT_SECONDS)])
    return [
        step(
            [py, "scripts/run_skill.py"],
            root / "OKR-inspection" / "delay-test-rate-skill",
            "延期提测率巡检",
            DAILY_INSPECTION_RETRY_LIMIT,
            True,
            DAILY_OKR_TIMEOUT_SECONDS,
        ),
        step(
            [py, "scripts/run_skill.py"],
            root / "OKR-inspection" / "delay-online-rate-skill",
            "延期上线率巡检",
            DAILY_INSPECTION_RETRY_LIMIT,
            True,
            DAILY_OKR_TIMEOUT_SECONDS,
        ),
        step(
            [py, "scripts/run_skill.py"],
            root / "OKR-inspection" / "technical-refactor-working-hours-skill",
            "技术改造工时占比巡检",
            DAILY_INSPECTION_RETRY_LIMIT,
            True,
            DAILY_OKR_TIMEOUT_SECONDS,
        ),
        step(
            [py, "scripts/run_skill.py"],
            root / "OKR-inspection" / "bi-weekly-delivery-rate-skill",
            "双周交付率巡检",
            DAILY_INSPECTION_RETRY_LIMIT,
            True,
            DAILY_OKR_TIMEOUT_SECONDS,
        ),
        step(
            [py, "scripts/run_skill.py"],
            root / "AI-inspection",
            "AI 深度用户巡检",
            DAILY_INSPECTION_RETRY_LIMIT,
            True,
            DAILY_AI_TIMEOUT_SECONDS,
        ),
        step(
            [py, "scripts/run_skill.py"],
            root / "ContinuousDelivery-inspection",
            "持续交付巡检",
            DAILY_INSPECTION_RETRY_LIMIT,
            True,
            DAILY_CONTINUOUS_DELIVERY_TIMEOUT_SECONDS,
        ),
        step(aggregate, root, "生成日常巡检报告", timeout_seconds=aggregate_timeout),
    ]


def friday_inspection_steps() -> list[dict]:
    py = python_bin()
    return [step([py, "scripts/run_skill.py", "--headless"], friday_dir(), "周度 INE 指标抓取", timeout_seconds=30 * 60)]


def aggregate_report_step(skip_repair: bool = True) -> dict:
    root = daily_dir()
    py = python_bin()
    command = [py, "joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py"]
    timeout_seconds = AGGREGATE_WITH_REPAIR_TIMEOUT_SECONDS
    if skip_repair:
        command.append("--skip-repair")
        timeout_seconds = AGGREGATE_REPORT_TIMEOUT_SECONDS
    else:
        command.extend(["--repair-timeout", str(AGGREGATE_REPAIR_SCRIPT_TIMEOUT_SECONDS)])
    return step(command, root, "刷新日常巡检总报告", timeout_seconds=timeout_seconds)


def single_daily_inspection_steps(cwd: Path, label: str) -> list[dict]:
    return [
        step([python_bin(), "scripts/run_skill.py"], cwd, label, timeout_seconds=SINGLE_DAILY_STEP_TIMEOUT_SECONDS),
        aggregate_report_step(skip_repair=True),
    ]


def action_registry() -> dict[str, dict]:
    py = python_bin()
    d = daily_dir()
    f = friday_dir()
    t = thursday_dir()
    return {
        "daily_inspection": {
            "title": "日常巡检",
            "group": "主流程",
            "description": "依次执行 OKR、AI、持续交付巡检；如延期提测/上线存在待修复需求，会自动触发修复并刷新总报告。",
            "risk": "write",
            "confirm_phrase": "确认执行修复",
            "aliases": ["日常巡检", "每日巡检", "帮我日常巡检", "帮我巡检", "daily"],
            "steps": daily_inspection_steps(skip_repair=False),
        },
        "daily_inspection_with_repair": {
            "title": "日常巡检并自动修复",
            "group": "主流程",
            "description": "执行完整日常巡检，并允许汇总阶段按延期指标触发修复脚本。",
            "risk": "write",
            "confirm_phrase": "确认执行修复",
            "aliases": ["日常巡检并修复", "完整日常巡检", "带修复日常巡检"],
            "steps": daily_inspection_steps(skip_repair=False),
        },
        "friday_inspection": {
            "title": "周度巡检",
            "group": "主流程",
            "description": "抓取周度 INE 指标数据，生成 friday-inspection-skill/scripts/out/ine_metrics.json。",
            "risk": "safe",
            "schedule": {"type": "weekday", "weekday": 4},
            "aliases": ["周度巡检", "周五巡检", "friday"],
            "steps": friday_inspection_steps(),
        },
        "okr_all": {
            "title": "OKR 四项巡检",
            "group": "单项巡检",
            "description": "运行延期提测、延期上线、技术改造工时、双周交付率四项，并刷新总报告。",
            "risk": "safe",
            "aliases": ["okr巡检", "OKR巡检", "okr四项"],
            "steps": daily_inspection_steps(skip_repair=True)[:4] + [aggregate_report_step(skip_repair=True)],
        },
        "delay_test_rate": {
            "title": "延期提测率",
            "group": "单项巡检",
            "description": "单独抓取延期提测率指标，并刷新总报告。",
            "risk": "safe",
            "aliases": ["延期提测率", "提测率巡检"],
            "steps": single_daily_inspection_steps(d / "OKR-inspection" / "delay-test-rate-skill", "延期提测率巡检"),
        },
        "delay_online_rate": {
            "title": "延期上线率",
            "group": "单项巡检",
            "description": "单独抓取延期上线率指标，并刷新总报告。",
            "risk": "safe",
            "aliases": ["延期上线率", "上线率巡检"],
            "steps": single_daily_inspection_steps(d / "OKR-inspection" / "delay-online-rate-skill", "延期上线率巡检"),
        },
        "technical_refactor": {
            "title": "技术改造工时",
            "group": "单项巡检",
            "description": "单独抓取技术改造工时占比，并刷新总报告。",
            "risk": "safe",
            "aliases": ["技术改造", "技术改造工时", "技改工时"],
            "steps": single_daily_inspection_steps(d / "OKR-inspection" / "technical-refactor-working-hours-skill", "技术改造工时占比巡检"),
        },
        "biweekly_delivery": {
            "title": "双周交付率",
            "group": "单项巡检",
            "description": "单独抓取双周交付率，并刷新总报告。",
            "risk": "safe",
            "aliases": ["双周交付", "双周交付率"],
            "steps": single_daily_inspection_steps(d / "OKR-inspection" / "bi-weekly-delivery-rate-skill", "双周交付率巡检"),
        },
        "ai_inspection": {
            "title": "AI 深度用户",
            "group": "单项巡检",
            "description": "下载并筛选 AI 非深度用户名单，并刷新总报告。",
            "risk": "safe",
            "aliases": ["AI巡检", "ai巡检", "非深度用户"],
            "steps": single_daily_inspection_steps(d / "AI-inspection", "AI 深度用户巡检"),
        },
        "continuous_delivery": {
            "title": "持续交付",
            "group": "单项巡检",
            "description": "抓取持续交付三张指标卡，并刷新总报告。",
            "risk": "safe",
            "aliases": ["持续交付", "持续交付巡检"],
            "steps": single_daily_inspection_steps(d / "ContinuousDelivery-inspection", "持续交付巡检"),
        },
        "aggregate_report": {
            "title": "刷新总报告",
            "group": "报告",
            "description": "只读取已有 JSON 重新生成日常巡检 HTML，不触发修复。",
            "risk": "safe",
            "aliases": ["刷新报告", "刷新总报告", "生成总报告", "重新生成报告"],
            "steps": [aggregate_report_step(skip_repair=True)],
        },
        "friday_report_text": {
            "title": "周报备文案",
            "group": "报告",
            "description": "读取周度 JSON，生成支付生态研发部报备文案。",
            "risk": "safe",
            "requires_current_data": "weekly",
            "aliases": ["周报备", "周报备文案", "生成周报文案", "周五报备", "周五报备文案", "生成周五文案"],
            "steps": [
                step(
                    [
                        py,
                        "joyclaw-payment-ecosystem-report-skill/scripts/render_joyclaw_report.py",
                        "--json",
                        "scripts/out/ine_metrics.json",
                        "--out",
                        "scripts/out/joyclaw_report.txt",
                    ],
                    f,
                    "生成周报备文案",
                )
            ],
        },
        "thursday_report": {
            "title": "计划日期调整报告",
            "group": "日期调整",
            "description": "只读取已有 JSON，刷新计划日期调整 HTML 报告。",
            "risk": "safe",
            "requires_current_data": "thursday_adjustment",
            "aliases": ["计划日期调整报告", "刷新日期调整报告", "刷新计划日期调整报告"],
            "steps": [step([py, "generate_modification_report.py"], t, "刷新计划日期调整报告")],
        },
        "thursday_adjustment": {
            "title": "计划日期顺延",
            "group": "日期调整",
            "description": "打开星云看板，将计划提测/上线日期命中本周四的需求顺延至本周五。",
            "risk": "write",
            "schedule": {"type": "weekday", "weekday": 3},
            "confirm_phrase": "确认执行日期调整",
            "aliases": ["执行计划日期调整", "计划日期调整", "计划日期顺延", "执行计划日期顺延", "本周四顺延至本周五", "计划日期从本周四顺延至本周五"],
            "steps": [step([py, "open_jd_cashier.py"], t, "执行计划日期顺延", timeout_seconds=THURSDAY_ADJUSTMENT_TIMEOUT_SECONDS)],
        },
        "repair_delayed_test": {
            "title": "修复延期提测",
            "group": "修复",
            "description": "执行延期提测修复脚本，会打开详情页并修改计划提测日期。",
            "risk": "write",
            "confirm_phrase": "确认修复延期提测",
            "aliases": ["修复延期提测", "延期提测修复"],
            "steps": [step([py, "main.py"], delayed_test_repair_dir(), "修复延期提测", timeout_seconds=REPAIR_ACTION_TIMEOUT_SECONDS)],
        },
        "repair_delayed_online": {
            "title": "修复延期上线",
            "group": "修复",
            "description": "执行延期上线修复脚本，会打开详情页并修改计划上线日期。",
            "risk": "write",
            "confirm_phrase": "确认修复延期上线",
            "aliases": ["修复延期上线", "延期上线修复"],
            "steps": [step([py, "main.py"], d / "repair-delayed-launch", "修复延期上线", timeout_seconds=REPAIR_ACTION_TIMEOUT_SECONDS)],
        },
    }


def weekly_metrics_source_date(data: dict):
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    return (
        parse_date(meta.get("inspection_date"))
        or parse_date(meta.get("generated_at"))
        or file_modified_date(friday_dir() / "scripts" / "out" / "ine_metrics.json")
    )


def weekly_current_data_status() -> dict:
    path = friday_dir() / "scripts" / "out" / "ine_metrics.json"
    data = read_json_file(path)
    return fixed_cycle_data_freshness(
        key="weekly",
        title="周度巡检",
        weekday=4,
        source_date=weekly_metrics_source_date(data),
        exists=path.exists() and bool(data),
    )


def thursday_adjustment_source_date():
    candidates = [
        (thursday_dir() / "thursday_to_friday_modified.json", "source_date"),
        (thursday_dir() / "thursday_demands.json", "target_date"),
        (thursday_dir() / "thursday_submit_test_demands.json", "target_date"),
        (thursday_dir() / "thursday_online_demands.json", "target_date"),
    ]
    for path, key in candidates:
        data = read_json_file(path)
        parsed = parse_date(data.get(key))
        if parsed:
            return parsed
    return file_modified_date(thursday_dir() / "thursday_to_friday_modified.json")


def thursday_current_data_status() -> dict:
    path = thursday_dir() / "thursday_to_friday_modified.json"
    return fixed_cycle_data_freshness(
        key="thursday_adjustment",
        title="计划日期顺延",
        weekday=3,
        source_date=thursday_adjustment_source_date(),
        exists=path.exists(),
    )


def required_current_data_status(data_key: str) -> dict:
    if data_key == "weekly":
        return weekly_current_data_status()
    if data_key == "thursday_adjustment":
        return thursday_current_data_status()
    return {}


def public_actions() -> list[dict]:
    items = []
    for action_id, item in action_registry().items():
        public = {key: value for key, value in item.items() if key not in {"steps", "aliases"}}
        public["id"] = action_id
        public["step_count"] = len(item.get("steps", []))
        public["availability"] = action_availability(action_id)
        items.append(public)
    return items


def action_steps(action: str) -> list[dict]:
    return action_registry()[action]["steps"]


def action_title(action: str) -> str:
    return action_registry().get(action, {}).get("title", action)


def action_availability(action: str) -> dict:
    item = action_registry().get(action, {})
    availability = action_schedule_status(item.get("schedule") if isinstance(item, dict) else None)
    data_key = str(item.get("requires_current_data") or "") if isinstance(item, dict) else ""
    freshness = required_current_data_status(data_key) if data_key else {}
    if not freshness:
        return availability
    if not freshness.get("is_current"):
        return {
            **availability,
            "can_run": False,
            "status": freshness.get("state") or "stale_data",
            "reason": freshness.get("message") or "当前没有可用的本周数据。",
            "data_freshness": freshness,
        }
    return {**availability, "data_freshness": freshness}



def action_unavailable_reason(action: str) -> str:
    availability = action_availability(action)
    if availability.get("can_run", True):
        return ""
    return str(availability.get("reason") or "当前不在该操作的执行窗口。")


def action_requires_confirmation(action: str, message: str = "") -> str:
    item = action_registry().get(action, {})
    phrase = item.get("confirm_phrase", "")
    if item.get("risk") == "write" and phrase and phrase not in message:
        return phrase
    return ""


def update_step_result(job_id: str, index: int, **updates) -> None:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        results = job.setdefault("step_results", [])
        if not (0 <= index - 1 < len(results)):
            return
        results[index - 1].update(updates)
        job["updated_at"] = now_text()


def failed_step_results(job: dict) -> list[dict]:
    return [
        item
        for item in job.get("step_results", [])
        if item.get("status") in {"failed", "timeout"}
    ]


def mark_skipped_steps(job_id: str, start_index: int, total_steps: int) -> None:
    for skipped_index in range(start_index, total_steps + 1):
        update_step_result(job_id, skipped_index, status="skipped")


def step_timeout_seconds(item: dict) -> int:
    try:
        return max(1, int(item.get("timeout_seconds") or DEFAULT_COMMAND_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_COMMAND_TIMEOUT_SECONDS


def job_wait_timeout_seconds(steps: list[dict]) -> int:
    total = 0
    for item in steps:
        retry_limit = max(0, int(item.get("retry_limit") or 0))
        total += step_timeout_seconds(item) * (retry_limit + 1)
    return max(DEFAULT_COMMAND_TIMEOUT_SECONDS, total + JOB_WAIT_BUFFER_SECONDS)


def run_step_with_retry(job_id: str, index: int, total_steps: int, item: dict) -> dict:
    retry_limit = max(0, int(item.get("retry_limit") or 0))
    attempts_allowed = retry_limit + 1
    timeout_seconds = step_timeout_seconds(item)
    last_result: dict = {}
    for attempt in range(1, attempts_allowed + 1):
        update_step_result(
            job_id,
            index,
            status="running",
            attempts=attempt,
            retry_limit=retry_limit,
            started_at=now_text(),
            returncode=None,
            error="",
            stdout_tail="",
            stderr_tail="",
            timeout_seconds=timeout_seconds,
        )
        if attempt == 1:
            append_job_log(job_id, f"步骤 {index}/{total_steps}：{item['label']}")
        else:
            append_job_log(job_id, f"步骤 {index}/{total_steps} 重试 {attempt - 1}/{retry_limit}：{item['label']}")

        result = run_command(job_id, item["command"], item["cwd"], timeout_seconds=timeout_seconds)
        last_result = {**result, "attempts": attempt, "retry_limit": retry_limit}
        update_step_result(job_id, index, **last_result)
        if result.get("status") == "success":
            if attempt > 1:
                append_job_log(job_id, f"步骤 {index} 重试后成功，继续后续巡检。")
            return last_result
        if attempt <= retry_limit:
            append_job_log(job_id, f"步骤 {index} 失败，准备自动重试。")

    return last_result


def run_job(job_id: str) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        action = job["action"]
    set_job(job_id, status="running", started_at=now_text())
    steps = action_steps(action)
    try:
        for index, item in enumerate(steps, 1):
            set_job(job_id, current_step=index, total_steps=len(steps))
            result = run_step_with_retry(job_id, index, len(steps), item)
            if result.get("status") != "success":
                if item.get("continue_on_failure"):
                    append_job_log(job_id, f"步骤 {index} 仍失败，已记录失败并继续后续巡检。")
                    continue
                mark_skipped_steps(job_id, index + 1, len(steps))
                set_job(
                    job_id,
                    status=result.get("status") or "failed",
                    finished_at=now_text(),
                    returncode=result.get("returncode"),
                    failed_step=index,
                    failed_step_label=item["label"],
                    error=result.get("error") or "",
                )
                append_job_log(job_id, "任务失败，已停止后续步骤。")
                record_failure_for_job(job_id)
                return
        with JOB_LOCK:
            current_job = dict(JOBS.get(job_id) or {})
        failed_steps = failed_step_results(current_job)
        if failed_steps:
            first_failed = failed_steps[0]
            set_job(
                job_id,
                status="partial",
                finished_at=now_text(),
                returncode=1,
                failed_step=first_failed.get("index"),
                failed_step_label=first_failed.get("label"),
                failed_steps=[
                    {
                        "index": item.get("index"),
                        "label": item.get("label"),
                        "status": item.get("status"),
                        "attempts": item.get("attempts"),
                        "retry_limit": item.get("retry_limit"),
                        "timeout_seconds": item.get("timeout_seconds"),
                        "error": item.get("error"),
                    }
                    for item in failed_steps
                ],
                error=f"{len(failed_steps)} 个巡检步骤失败，其余步骤已继续执行。",
            )
            append_job_log(job_id, f"任务部分完成：{len(failed_steps)} 个步骤失败，其余步骤已执行。")
            record_failure_for_job(job_id)
            return
        set_job(job_id, status="success", finished_at=now_text(), returncode=0)
        append_job_log(job_id, "任务完成。")
    except subprocess.TimeoutExpired as exc:
        append_job_log(job_id, f"任务超时：{exc}")
        set_job(job_id, status="timeout", finished_at=now_text(), returncode=None)
        record_failure_for_job(job_id)
    except Exception as exc:
        append_job_log(job_id, f"任务异常：{exc}")
        set_job(job_id, status="failed", finished_at=now_text(), error=str(exc))
        record_failure_for_job(job_id)


def start_job(action: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    steps = action_steps(action)
    step_results = [
        {
            "index": index,
            "label": item["label"],
            "command": " ".join(item["command"]),
            "cwd": str(item["cwd"]),
            "status": "queued",
            "retry_limit": item.get("retry_limit", 0),
            "continue_on_failure": bool(item.get("continue_on_failure")),
            "timeout_seconds": step_timeout_seconds(item),
        }
        for index, item in enumerate(steps, 1)
    ]
    wait_timeout_seconds = job_wait_timeout_seconds(steps)
    with JOB_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "action": action,
            "title": action_title(action),
            "status": "queued",
            "created_at": now_text(),
            "updated_at": now_text(),
            "current_step": 0,
            "total_steps": len(steps),
            "wait_timeout_seconds": wait_timeout_seconds,
            "step_results": step_results,
            "logs": [],
        }
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return JOBS[job_id]


def wait_for_job(job_id: str, timeout_seconds: int | None = None) -> dict:
    with JOB_LOCK:
        initial_job = dict(JOBS.get(job_id) or {})
    if timeout_seconds is None:
        timeout_seconds = int(initial_job.get("wait_timeout_seconds") or DEFAULT_COMMAND_TIMEOUT_SECONDS)
    timeout_seconds = max(1, int(timeout_seconds))
    deadline = time.time() + timeout_seconds
    terminal_statuses = {"success", "partial", "failed", "timeout"}
    while time.time() < deadline:
        with JOB_LOCK:
            job = dict(JOBS.get(job_id) or {})
        if not job:
            return {}
        if job.get("status") in terminal_statuses:
            return job
        time.sleep(1)

    set_job(job_id, status="timeout", finished_at=now_text(), error="等待任务完成超时")
    record_failure_for_job(job_id)
    with JOB_LOCK:
        return dict(JOBS.get(job_id) or {})


STRONG_ACTION_WORDS = (
    "执行",
    "运行",
    "启动",
    "开始",
    "发起",
    "重跑",
    "重新跑",
    "跑一下",
    "跑一遍",
    "刷新",
    "重新生成",
    "生成",
    "同步",
    "更新",
    "修复",
    "顺延",
    "调整",
    "抓取",
    "拉取",
    "确认",
)

DISCUSSION_WORDS = (
    "为什么",
    "为啥",
    "怎么",
    "如何",
    "是什么",
    "啥",
    "说明",
    "解释",
    "讲一下",
    "看一下",
    "看下",
    "看看",
    "分析",
    "优化",
    "设计",
    "架构",
    "报告怎么写",
    "能不能",
    "可以吗",
    "是否",
    "是不是",
    "会不会",
    "吗",
    "有几个",
    "多少",
    "状态",
    "结果",
    "数据",
    "代码",
    "逻辑",
    "意思",
    "?",
    "？",
)


def _has_strong_action_intent(text: str) -> bool:
    return any(word in text for word in STRONG_ACTION_WORDS)


def _has_discussion_intent(text: str) -> bool:
    return any(word in text for word in DISCUSSION_WORDS)


def has_explicit_action_intent(message: str, action: str = "") -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    if re.search(r"(?:执行|运行|启动)?\s*action:([a-z0-9_]+)", text):
        return True
    if re.search(r"(?:tool|工具)\s*:\s*([a-zA-Z0-9_]+)", text):
        return True
    if _has_discussion_intent(text) and not any(word in text for word in ("确认", "执行", "运行", "启动", "开始", "发起", "重跑", "重新跑", "跑一下", "跑一遍", "刷新", "重新生成")):
        return False
    if _has_strong_action_intent(text):
        return True
    if "巡检一下" in text or "帮我巡检" in text or "帮我日常巡检" in text or "帮我周度巡检" in text:
        return True
    if action.startswith("repair_") and "修复" in text:
        return True
    if action == "thursday_adjustment" and ("顺延" in text or "调整" in text):
        return True
    return False


def _alias_can_trigger_action(text: str, alias: str, action: str) -> bool:
    alias_text = alias.lower()
    if alias_text not in text:
        return False
    if has_explicit_action_intent(text, action):
        return True
    if _has_discussion_intent(text):
        return False
    action_like_alias = (
        "巡检" in alias_text
        or "修复" in alias_text
        or "刷新" in alias_text
        or "生成" in alias_text
        or "顺延" in alias_text
        or "调整" in alias_text
    )
    if not action_like_alias:
        return False
    stripped = re.sub(r"\s+", "", text)
    compact_alias = re.sub(r"\s+", "", alias_text)
    command_forms = {
        compact_alias,
        f"帮我{compact_alias}",
        f"请{compact_alias}",
        f"麻烦{compact_alias}",
    }
    return stripped in command_forms


def detect_action(message: str) -> str:
    text = (message or "").strip().lower()
    registry = action_registry()
    direct = re.search(r"(?:执行|运行|启动)?\s*action:([a-z0-9_]+)", text)
    if direct and direct.group(1) in registry:
        return direct.group(1)
    aliases = [
        (alias.lower(), action_id)
        for action_id, item in registry.items()
        for alias in item.get("aliases", [])
    ]
    for alias, action_id in sorted(aliases, key=lambda pair: len(pair[0]), reverse=True):
        if _alias_can_trigger_action(text, alias, action_id):
            return action_id
    return "none"


def is_inspection_related(message: str, action: str = "none") -> bool:
    text = (message or "").strip().lower()
    if not text:
        return True
    if action != "none":
        return True
    keywords = (
        "巡检", "指标", "数据", "报告", "报表", "风险", "异常", "问题", "缺失", "失败",
        "延期", "提测", "上线", "修复", "交付", "双周", "持续交付", "技术改造",
        "ai", "非深度", "名单", "报备", "周报", "总结", "草稿", "任务", "脚本",
        "收银台", "内单", "交易域", "okr", "joyclaw", "mimo", "模型", "连接",
        "今天", "本周", "概览", "多少", "状态",
    )
    return any(keyword in text for keyword in keywords)
