from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_BIN = Path("/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python")
JOB_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def python_bin() -> str:
    return str(PYTHON_BIN if PYTHON_BIN.exists() else Path(sys.executable))


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


def run_command(job_id: str, command: list[str], cwd: Path, timeout_seconds: int = 60 * 60) -> int:
    display = " ".join(command)
    append_job_log(job_id, f"开始执行：{display}")
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.stdout:
        append_job_log(job_id, "stdout:\n" + tail_text(completed.stdout, 3000))
    if completed.stderr:
        append_job_log(job_id, "stderr:\n" + tail_text(completed.stderr, 3000))
    append_job_log(job_id, f"执行结束，returncode={completed.returncode}")
    return completed.returncode


def tail_text(value: str, max_chars: int = 3000) -> str:
    if len(value) <= max_chars:
        return value.strip()
    return value[-max_chars:].strip()


def step(command: list[str], cwd: Path, label: str) -> dict:
    return {"command": command, "cwd": cwd, "label": label}


def daily_dir() -> Path:
    return ROOT_DIR / "daily-inspection-skill"


def friday_dir() -> Path:
    return ROOT_DIR / "friday-inspection-skill"


def thursday_dir() -> Path:
    return ROOT_DIR / "thursday-to-friday-adjustment"


def daily_inspection_steps(skip_repair: bool = True) -> list[dict]:
    root = daily_dir()
    py = python_bin()
    aggregate = [py, "joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py"]
    if skip_repair:
        aggregate.append("--skip-repair")
    return [
        step([py, "scripts/run_skill.py"], root / "OKR-inspection" / "delay-test-rate-skill", "延期提测率巡检"),
        step([py, "scripts/run_skill.py"], root / "OKR-inspection" / "delay-online-rate-skill", "延期上线率巡检"),
        step([py, "scripts/run_skill.py"], root / "OKR-inspection" / "technical-refactor-working-hours-skill", "技术改造工时占比巡检"),
        step([py, "scripts/run_skill.py"], root / "OKR-inspection" / "bi-weekly-delivery-rate-skill", "双周交付率巡检"),
        step([py, "scripts/run_skill.py"], root / "AI-inspection", "AI 深度用户巡检"),
        step([py, "scripts/run_skill.py"], root / "ContinuousDelivery-inspection", "持续交付巡检"),
        step(aggregate, root, "生成日常巡检报告"),
    ]


def friday_inspection_steps() -> list[dict]:
    py = python_bin()
    return [step([py, "scripts/run_skill.py", "--headless"], friday_dir(), "周度 INE 指标抓取")]


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
            "risk": "safe",
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
            "aliases": ["周度巡检", "周五巡检", "周五", "friday"],
            "steps": friday_inspection_steps(),
        },
        "okr_all": {
            "title": "OKR 四项巡检",
            "group": "单项巡检",
            "description": "只运行延期提测、延期上线、技术改造工时、双周交付率四项。",
            "risk": "safe",
            "aliases": ["okr巡检", "OKR巡检", "okr四项"],
            "steps": daily_inspection_steps(skip_repair=True)[:4],
        },
        "delay_test_rate": {
            "title": "延期提测率",
            "group": "单项巡检",
            "description": "单独抓取延期提测率指标。",
            "risk": "safe",
            "aliases": ["延期提测率", "提测率巡检"],
            "steps": [step([py, "scripts/run_skill.py"], d / "OKR-inspection" / "delay-test-rate-skill", "延期提测率巡检")],
        },
        "delay_online_rate": {
            "title": "延期上线率",
            "group": "单项巡检",
            "description": "单独抓取延期上线率指标。",
            "risk": "safe",
            "aliases": ["延期上线率", "上线率巡检"],
            "steps": [step([py, "scripts/run_skill.py"], d / "OKR-inspection" / "delay-online-rate-skill", "延期上线率巡检")],
        },
        "technical_refactor": {
            "title": "技术改造工时",
            "group": "单项巡检",
            "description": "单独抓取技术改造工时占比。",
            "risk": "safe",
            "aliases": ["技术改造", "技术改造工时", "技改工时"],
            "steps": [step([py, "scripts/run_skill.py"], d / "OKR-inspection" / "technical-refactor-working-hours-skill", "技术改造工时占比巡检")],
        },
        "biweekly_delivery": {
            "title": "双周交付率",
            "group": "单项巡检",
            "description": "单独抓取双周交付率。",
            "risk": "safe",
            "aliases": ["双周交付", "双周交付率"],
            "steps": [step([py, "scripts/run_skill.py"], d / "OKR-inspection" / "bi-weekly-delivery-rate-skill", "双周交付率巡检")],
        },
        "ai_inspection": {
            "title": "AI 深度用户",
            "group": "单项巡检",
            "description": "下载并筛选 AI 非深度用户名单。",
            "risk": "safe",
            "aliases": ["AI巡检", "ai巡检", "非深度用户"],
            "steps": [step([py, "scripts/run_skill.py"], d / "AI-inspection", "AI 深度用户巡检")],
        },
        "continuous_delivery": {
            "title": "持续交付",
            "group": "单项巡检",
            "description": "抓取持续交付三张指标卡。",
            "risk": "safe",
            "aliases": ["持续交付", "持续交付巡检"],
            "steps": [step([py, "scripts/run_skill.py"], d / "ContinuousDelivery-inspection", "持续交付巡检")],
        },
        "aggregate_report": {
            "title": "刷新总报告",
            "group": "报告",
            "description": "只读取已有 JSON 重新生成日常巡检 HTML，不触发修复。",
            "risk": "safe",
            "aliases": ["刷新报告", "生成总报告", "重新生成报告"],
            "steps": [step([py, "joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py", "--skip-repair"], d, "生成日常巡检报告")],
        },
        "friday_report_text": {
            "title": "周报备文案",
            "group": "报告",
            "description": "读取周度 JSON，生成支付生态研发部报备文案。",
            "risk": "safe",
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
            "aliases": ["计划日期调整报告", "刷新日期调整报告", "刷新周四报告", "周四改周五报告", "刷新改周五报告"],
            "steps": [step([py, "generate_modification_report.py"], t, "刷新计划日期调整报告")],
        },
        "thursday_adjustment": {
            "title": "执行计划日期调整",
            "group": "日期调整",
            "description": "打开星云看板，将命中的计划提测/上线日期调整到目标日期。",
            "risk": "write",
            "confirm_phrase": "确认执行日期调整",
            "aliases": ["执行计划日期调整", "计划日期调整", "周四改周五", "执行周四改周五", "改周五"],
            "steps": [step([py, "open_jd_cashier.py"], t, "执行计划日期调整")],
        },
        "repair_delayed_test": {
            "title": "修复延期提测",
            "group": "修复",
            "description": "执行延期提测修复脚本，会打开详情页并修改计划提测日期。",
            "risk": "write",
            "confirm_phrase": "确认修复延期提测",
            "aliases": ["修复延期提测", "延期提测修复"],
            "steps": [step([py, "main.py"], d / "reschedule-delayed-test ", "修复延期提测")],
        },
        "repair_delayed_online": {
            "title": "修复延期上线",
            "group": "修复",
            "description": "执行延期上线修复脚本，会打开详情页并修改计划上线日期。",
            "risk": "write",
            "confirm_phrase": "确认修复延期上线",
            "aliases": ["修复延期上线", "延期上线修复"],
            "steps": [step([py, "main.py"], d / "repair-delayed-launch", "修复延期上线")],
        },
    }


def public_actions() -> list[dict]:
    items = []
    for action_id, item in action_registry().items():
        public = {key: value for key, value in item.items() if key not in {"steps", "aliases"}}
        public["id"] = action_id
        public["step_count"] = len(item.get("steps", []))
        items.append(public)
    return items


def action_steps(action: str) -> list[dict]:
    return action_registry()[action]["steps"]


def action_title(action: str) -> str:
    return action_registry().get(action, {}).get("title", action)


def action_requires_confirmation(action: str, message: str = "") -> str:
    item = action_registry().get(action, {})
    phrase = item.get("confirm_phrase", "")
    if item.get("risk") == "write" and phrase and phrase not in message:
        return phrase
    return ""


def run_job(job_id: str) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        action = job["action"]
    set_job(job_id, status="running", started_at=now_text())
    steps = action_steps(action)
    try:
        for index, item in enumerate(steps, 1):
            set_job(job_id, current_step=index, total_steps=len(steps))
            append_job_log(job_id, f"步骤 {index}/{len(steps)}：{item['label']}")
            code = run_command(job_id, item["command"], item["cwd"])
            if code != 0:
                set_job(job_id, status="failed", finished_at=now_text(), returncode=code)
                append_job_log(job_id, "任务失败，已停止后续步骤。")
                return
        set_job(job_id, status="success", finished_at=now_text(), returncode=0)
        append_job_log(job_id, "任务完成。")
    except subprocess.TimeoutExpired as exc:
        append_job_log(job_id, f"任务超时：{exc}")
        set_job(job_id, status="timeout", finished_at=now_text(), returncode=None)
    except Exception as exc:
        append_job_log(job_id, f"任务异常：{exc}")
        set_job(job_id, status="failed", finished_at=now_text(), error=str(exc))


def start_job(action: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    steps = action_steps(action)
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
            "logs": [],
        }
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return JOBS[job_id]


def wait_for_job(job_id: str, timeout_seconds: int = 60 * 60) -> dict:
    deadline = time.time() + timeout_seconds
    terminal_statuses = {"success", "failed", "timeout"}
    while time.time() < deadline:
        with JOB_LOCK:
            job = dict(JOBS.get(job_id) or {})
        if not job:
            return {}
        if job.get("status") in terminal_statuses:
            return job
        time.sleep(1)

    set_job(job_id, status="timeout", finished_at=now_text(), error="等待任务完成超时")
    with JOB_LOCK:
        return dict(JOBS.get(job_id) or {})


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
        if alias in text:
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
