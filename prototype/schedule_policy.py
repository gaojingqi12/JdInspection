from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


WEEKDAY_LABELS = {
    0: "周一",
    1: "周二",
    2: "周三",
    3: "周四",
    4: "周五",
    5: "周六",
    6: "周日",
}


def today_local() -> date:
    return date.today()


def week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def week_end(value: date) -> date:
    return week_start(value) + timedelta(days=6)


def scheduled_date_for_week(value: date, weekday: int) -> date:
    return week_start(value) + timedelta(days=weekday)


def next_scheduled_date(value: date, weekday: int) -> date:
    current = scheduled_date_for_week(value, weekday)
    return current if value <= current else current + timedelta(days=7)


def parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    candidates = (text, text[:19], text[:10])
    for candidate in candidates:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def file_modified_date(path: Path) -> date | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def action_schedule_status(schedule: dict[str, Any] | None, value: date | None = None) -> dict[str, Any]:
    today = value or today_local()
    if not schedule:
        return {
            "scheduled": False,
            "can_run": True,
            "status": "available",
            "reason": "",
        }

    if schedule.get("type") != "weekday":
        return {
            "scheduled": True,
            "can_run": True,
            "status": "available",
            "reason": "",
        }

    weekday = int(schedule.get("weekday", today.weekday()))
    label = WEEKDAY_LABELS.get(weekday, f"周{weekday + 1}")
    expected = scheduled_date_for_week(today, weekday)
    next_date = next_scheduled_date(today, weekday)
    can_run = today.weekday() == weekday
    if can_run:
        reason = f"今天是{label}，处于执行窗口。"
    elif today < expected:
        reason = f"该操作仅{label}执行，本周执行日为 {expected.isoformat()}。"
    else:
        reason = f"该操作仅{label}执行，本周执行窗口已结束，下次执行日为 {next_date.isoformat()}。"
    return {
        "scheduled": True,
        "can_run": can_run,
        "status": "available" if can_run else "not_scheduled_today",
        "weekday": weekday,
        "weekday_label": label,
        "schedule_label": f"每{label}",
        "expected_date": expected.isoformat(),
        "next_date": next_date.isoformat(),
        "reason": reason,
    }


def fixed_cycle_data_freshness(
    *,
    key: str,
    title: str,
    weekday: int,
    source_date: date | None,
    exists: bool,
    value: date | None = None,
) -> dict[str, Any]:
    today = value or today_local()
    expected = scheduled_date_for_week(today, weekday)
    start = week_start(today)
    end = week_end(today)
    weekday_label = WEEKDAY_LABELS.get(weekday, f"周{weekday + 1}")
    source_text = source_date.isoformat() if source_date else ""
    base = {
        "key": key,
        "title": title,
        "weekday": weekday,
        "weekday_label": weekday_label,
        "schedule_label": f"每{weekday_label}",
        "today": today.isoformat(),
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "expected_date": expected.isoformat(),
        "source_date": source_text,
        "exists": exists,
    }

    is_current = bool(exists and source_date and expected <= source_date <= end)
    if is_current:
        return {
            **base,
            "state": "current",
            "is_current": True,
            "label": "本周已更新",
            "message": f"{title}已读取本周数据，数据日期 {source_text}。",
        }

    if today < expected:
        return {
            **base,
            "state": "pending",
            "is_current": False,
            "label": f"待{weekday_label}执行",
            "message": f"本周尚未到{title}执行日（{expected.isoformat()}），上一周期数据不参与展示。",
        }

    if not exists or not source_date:
        return {
            **base,
            "state": "missing",
            "is_current": False,
            "label": "本周未生成",
            "message": f"本周{weekday_label}执行窗口已到，但还没有读取到本周{title}数据。",
        }

    return {
        **base,
        "state": "stale",
        "is_current": False,
        "label": "数据已过期",
        "message": f"当前只展示本周{weekday_label}后的数据；上一份数据日期为 {source_text}，已归档不参与展示。",
    }
