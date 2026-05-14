from __future__ import annotations

import json
import mimetypes
import re
import shutil
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from agent_memory import load_memory, save_memory, summarize_for_prompt, update_memory_from_turn
from ai_settings import (
    AI_CONFIG_LOCK,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    load_ai_config,
    normalize_model_name,
    public_ai_config,
    save_ai_config,
)
from actions import (
    JOBS,
    JOB_LOCK,
    action_title,
    has_explicit_action_intent,
    is_inspection_related,
    public_actions,
    wait_for_job,
)
from agent_tools import (
    action_from_tool_call,
    build_agent_plan,
    detect_tool_call,
    execute_tool_call,
    evaluate_agent_state,
    next_tool_call_after_result,
    normalize_model_tool_call,
    openai_tool_schemas,
    public_tools,
    render_tool_chain_summary,
    resolve_routed_tool_call,
    tool_call_from_action,
    tool_catalog_for_prompt,
    tool_requires_confirmation,
    tool_title,
    validate_tool_call,
)
from chat_store import (
    CHAT_LOCK,
    begin_chat_turn,
    create_chat_session,
    default_chat_messages,
    find_chat_session,
    finish_chat_turn,
    load_chat_store,
    save_chat_store,
    sorted_chat_sessions,
)
from data_query import query_inspection_data
from daily_templates import DailyInspectionRenderer
from failure_records import recent_failure_records
from failure_recovery import render_failure_recovery
from http_files import path_is_within
from inspection_agent import InspectionAgent, InspectionAgentDeps
from report_views import (
    build_static_site_index_html,
    display_unit,
    extract_report_main_content,
    format_value,
    html_text,
    latest_non_null,
    report_metric,
    report_nav,
    report_shell,
    static_report_shell,
    status_badge_html,
    table_section,
)
from schedule_policy import fixed_cycle_data_freshness, file_modified_date, parse_date, week_end, week_start
from tool_audit import clear_tool_events, recent_tool_events, record_tool_event

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
SUMMARY_PATH = ROOT_DIR / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "weekly-inspection-summary.json"
REPORT_HTML_PATH = ROOT_DIR / "daily-inspection-skill" / "index.html"
THURSDAY_REPORT_HTML_PATH = ROOT_DIR / "thursday-to-friday-adjustment" / "index.html"
THURSDAY_MODIFIED_JSON_PATH = ROOT_DIR / "thursday-to-friday-adjustment" / "thursday_to_friday_modified.json"
THURSDAY_DEMANDS_JSON_PATH = ROOT_DIR / "thursday-to-friday-adjustment" / "thursday_demands.json"
THURSDAY_SUBMIT_TEST_JSON_PATH = ROOT_DIR / "thursday-to-friday-adjustment" / "thursday_submit_test_demands.json"
THURSDAY_ONLINE_JSON_PATH = ROOT_DIR / "thursday-to-friday-adjustment" / "thursday_online_demands.json"
WEEKLY_METRICS_PATH = ROOT_DIR / "friday-inspection-skill" / "scripts" / "out" / "ine_metrics.json"
AI_INSPECTION_OUT_DIR = ROOT_DIR / "daily-inspection-skill" / "AI-inspection" / "out"
AI_INSPECTION_HISTORY_DIR = AI_INSPECTION_OUT_DIR / "history"
CONTINUOUS_DELIVERY_OUT_DIR = ROOT_DIR / "daily-inspection-skill" / "ContinuousDelivery-inspection" / "out"
AGENT_MEMORY_PATH = Path(__file__).resolve().parent / "data" / "agent-memory.json"

METRIC_LABELS = {
    "planned_test_requirements": "计划提测需求数",
    "delayed_test_requirements": "延期提测需求数",
    "delay_test_rate_okr": "延期提测率",
    "planned_online_requirements": "计划上线需求数",
    "delayed_online_requirements": "延期上线需求数",
    "delay_online_rate": "延期上线率",
    "total_working_hours": "总工时",
    "technical_refactor_working_hours": "技术改造工时",
    "technical_refactor_working_hours_rate": "技术改造工时占比",
    "biweekly_delivery_rate": "双周交付率",
    "team_space_dev_test_online_requirements": "团队空间开发测试上线需求数",
    "team_space_continuous_delivery_dev_test_online_requirements": "持续交付上线需求数",
    "continuous_delivery_team_space_online_requirement_rate": "持续交付占比",
}

REPAIR_METRIC_CONFIG = {
    "delayed_test": {
        "metric_key": "delayed_test_requirements",
        "count_label": "筛选延期提测数",
        "label": "提测待处理",
        "caption": "修复筛选",
        "indicator_type": "delay_test_rate",
    },
    "delayed_online": {
        "metric_key": "delayed_online_requirements",
        "count_label": "筛选延期上线数",
        "label": "上线待处理",
        "caption": "修复筛选",
        "indicator_type": "delay_online_rate",
    },
}

REPAIR_HISTORY_DIRS = {
    "delayed_test": ROOT_DIR / "daily-inspection-skill" / "reschedule-delayed-test" / "history",
    "delayed_online": ROOT_DIR / "daily-inspection-skill" / "repair-delayed-launch" / "history",
}
LEGACY_REPAIR_HISTORY_DIRS = {
    "delayed_test": ROOT_DIR / "daily-inspection-skill" / "reschedule-delayed-test " / "history",
}

STATIC_ROOT_INDEX_PATH = ROOT_DIR / "index.html"
STATIC_ROOT_DAILY_REPORT_PATH = ROOT_DIR / "daily-report.html"
STATIC_ROOT_WEEKLY_REPORT_PATH = ROOT_DIR / "weekly-report.html"
STATIC_ROOT_REPAIR_REPORT_PATH = ROOT_DIR / "repair-report.html"
STATIC_ROOT_THURSDAY_REPORT_PATH = ROOT_DIR / "thursday-report.html"

PREVIEW_ASSET_CONFIG = {
    "delay_test_rate_okr": {
        "asset_name": "delay_test_rate.png",
        "sources": [
            ROOT_DIR / "daily-inspection-skill" / "assets" / "screenshots" / "delay_test_rate.png",
            ROOT_DIR / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "assets" / "screenshots" / "delay_test_rate.png",
            ROOT_DIR / "daily-inspection-skill" / "OKR-inspection" / "delay-test-rate-skill" / "out" / "05_after_query.png",
        ],
    },
    "delay_online_rate": {
        "asset_name": "delay_online_rate.png",
        "sources": [
            ROOT_DIR / "daily-inspection-skill" / "assets" / "screenshots" / "delay_online_rate.png",
            ROOT_DIR / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "assets" / "screenshots" / "delay_online_rate.png",
            ROOT_DIR / "daily-inspection-skill" / "OKR-inspection" / "delay-online-rate-skill" / "out" / "05_after_query.png",
        ],
    },
    "technical_refactor_working_hours_rate": {
        "asset_name": "technical_refactor_working_hours.png",
        "sources": [
            ROOT_DIR / "daily-inspection-skill" / "assets" / "screenshots" / "technical_refactor_working_hours.png",
            ROOT_DIR / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "assets" / "screenshots" / "technical_refactor_working_hours.png",
            ROOT_DIR / "daily-inspection-skill" / "OKR-inspection" / "technical-refactor-working-hours-skill" / "out" / "05_after_query.png",
        ],
    },
    "biweekly_delivery_rate": {
        "asset_name": "bi_weekly_delivery_rate.png",
        "sources": [
            ROOT_DIR / "daily-inspection-skill" / "assets" / "screenshots" / "bi_weekly_delivery_rate.png",
            ROOT_DIR / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "assets" / "screenshots" / "bi_weekly_delivery_rate.png",
            ROOT_DIR / "daily-inspection-skill" / "OKR-inspection" / "bi-weekly-delivery-rate-skill" / "out" / "03_after_query.png",
        ],
    },
}

def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback

def write_json_file(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def weekly_metrics_source_date(data: dict) -> object:
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    return (
        parse_date(meta.get("inspection_date"))
        or parse_date(meta.get("generated_at"))
        or file_modified_date(WEEKLY_METRICS_PATH)
    )

def thursday_adjustment_source_date() -> object:
    candidates = [
        (THURSDAY_MODIFIED_JSON_PATH, "source_date"),
        (THURSDAY_DEMANDS_JSON_PATH, "target_date"),
        (THURSDAY_SUBMIT_TEST_JSON_PATH, "target_date"),
        (THURSDAY_ONLINE_JSON_PATH, "target_date"),
    ]
    for path, key in candidates:
        data = read_json(path, {})
        if isinstance(data, dict):
            parsed = parse_date(data.get(key))
            if parsed:
                return parsed
    return file_modified_date(THURSDAY_MODIFIED_JSON_PATH)

def weekly_report_freshness(data: dict | None = None) -> dict:
    weekly = data if isinstance(data, dict) else read_json(WEEKLY_METRICS_PATH, {})
    return fixed_cycle_data_freshness(
        key="weekly",
        title="周度巡检",
        weekday=4,
        source_date=weekly_metrics_source_date(weekly if isinstance(weekly, dict) else {}),
        exists=WEEKLY_METRICS_PATH.exists() and bool(weekly),
    )

def thursday_report_freshness() -> dict:
    return fixed_cycle_data_freshness(
        key="thursday_adjustment",
        title="计划日期顺延",
        weekday=3,
        source_date=thursday_adjustment_source_date(),
        exists=THURSDAY_MODIFIED_JSON_PATH.exists(),
    )

def data_freshness() -> dict:
    items = [thursday_report_freshness(), weekly_report_freshness()]
    return {
        "fixed_cycle_reports": items,
        "has_stale_fixed_cycle_data": any(not item.get("is_current") for item in items),
    }

def render_freshness_placeholder_report(title: str, freshness: dict, source_note: str) -> str:
    sections = [
        table_section(
            "数据时效说明",
            "固定执行日模块只展示本周有效窗口内的数据",
            ["项目", "说明"],
            [
                ["执行频率", html_text(freshness.get("schedule_label") or "-")],
                ["本周执行日", html_text(freshness.get("expected_date") or "-")],
                ["上一份数据日期", html_text(freshness.get("source_date") or "-")],
                ["处理策略", html_text("上一周期数据已归档，不参与当前看板、报告和 Agent 回答。")],
            ],
        )
    ]
    return report_shell(
        title,
        str(freshness.get("message") or "当前没有可展示的本周数据。"),
        [
            report_metric("状态", freshness.get("label") or "-", freshness.get("message") or ""),
            report_metric("本周执行日", freshness.get("expected_date") or "-", freshness.get("schedule_label") or ""),
            report_metric("上一份数据", freshness.get("source_date") or "-", source_note),
        ],
        sections,
    )

def relative_path_text(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)

def latest_existing_file(paths: list[Path]) -> Path | None:
    candidates = [path for path in paths if path.exists() and path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)

def preview_asset_target(asset_name: str) -> Path:
    return STATIC_DIR / "assets" / asset_name

def metric_preview_asset_version() -> str:
    mtimes = []
    for config in PREVIEW_ASSET_CONFIG.values():
        target = preview_asset_target(str(config.get("asset_name") or ""))
        if target.exists():
            mtimes.append(int(target.stat().st_mtime))
    return str(max(mtimes)) if mtimes else ""

def versioned_preview_asset(path_text: str) -> str:
    rel_path = path_text.removeprefix("./")
    path = ROOT_DIR / rel_path
    if not path.exists():
        return path_text
    separator = "&" if "?" in path_text else "?"
    return f"{path_text}{separator}v={int(path.stat().st_mtime)}"

def metric_preview_asset(key: str) -> str | None:
    config = PREVIEW_ASSET_CONFIG.get(key)
    if not config:
        return None
    asset_name = str(config.get("asset_name") or "")
    if not asset_name:
        return None
    return versioned_preview_asset(f"./prototype/static/assets/{asset_name}")

def sync_metric_preview_assets() -> list[dict]:
    synced = []
    (STATIC_DIR / "assets").mkdir(parents=True, exist_ok=True)
    for key, config in PREVIEW_ASSET_CONFIG.items():
        asset_name = str(config.get("asset_name") or "")
        target = preview_asset_target(asset_name)
        source = latest_existing_file(list(config.get("sources") or []))
        if not source:
            synced.append(
                {
                    "key": key,
                    "target": relative_path_text(target),
                    "status": "missing_source",
                }
            )
            continue

        source_stat = source.stat()
        target_stat = target.stat() if target.exists() else None
        should_copy = (
            target_stat is None
            or int(target_stat.st_mtime) < int(source_stat.st_mtime)
            or target_stat.st_size != source_stat.st_size
        )
        if should_copy:
            shutil.copy2(source, target)
        final_stat = target.stat()
        synced.append(
            {
                "key": key,
                "source": relative_path_text(source),
                "target": relative_path_text(target),
                "updated": should_copy,
                "version": int(final_stat.st_mtime),
            }
        )
    return synced

def render_daily_report_html() -> str:
    summary = current_summary()
    metrics = [
        report_metric(card.get("label"), card.get("display_value"), f"{card.get('date', '-')}")
        for card in summary.get("overview", [])[:8]
    ]
    indicator_rows = []
    for index, indicator in enumerate(summary.get("indicators", []), 1):
        focus_key = indicator.get("focus_metric_key")
        point = latest_point((indicator.get("history") or {}).get(focus_key, []))
        unit = (indicator.get("unit") or {}).get(focus_key, "")
        indicator_rows.append(
            [
                f'<span class="index">{index}</span>',
                f'<div class="demand">{html_text(indicator.get("indicator_name") or indicator.get("skill_name"))}</div>',
                html_text(METRIC_LABELS.get(focus_key, focus_key)),
                html_text(format_value(point.get("value"), unit)),
                html_text(point.get("date") or "-"),
            ]
        )
    sections = [
        table_section(
            "核心指标",
            "",
            ["#", "指标", "关注项", "最新值", "日期"],
            indicator_rows,
        )
    ]
    ai = summary.get("ai_inspection") or {}
    users = ai.get("users") or []
    ai_rows = [
        [
            f'<span class="index">{index}</span>',
            html_text(user.get("name")),
            html_text(user.get("erp")),
            html_text(format_value(user.get("ai_code_local_submit_rate"), "%")),
            status_badge_html(user.get("is_deep_user") or "-"),
        ]
        for index, user in enumerate(users, 1)
    ]
    sections.append(table_section("AI 非深度用户", f"{ai.get('date', '-')} · 共 {len(users)} 人", ["#", "姓名", "ERP", "AI 提交占比", "是否深度用户"], ai_rows))
    return report_shell(
        "日常巡检报告",
        f"{summary.get('display_domain') or summary.get('department_c3') or '收银台&内单交易域'} · {summary.get('time_range', {}).get('start_date', '-')} ~ {summary.get('time_range', {}).get('end_date', '-')}",
        metrics,
        sections,
        summary.get("generated_at") or summary.get("loaded_at") or "",
    )

def repair_items_from_summary(summary: dict) -> list[dict]:
    items = []
    repair_metrics = build_repair_metrics(summary)
    for repair in summary.get("repair_inspections", []):
        detail = repair.get("summary") or {}
        repair_type = repair.get("repair_type")
        metric = repair_metrics.get(repair_type, {})
        count_label = REPAIR_METRIC_CONFIG.get(repair_type, {}).get("count_label", "筛选数")
        selected = metric.get("value")
        if selected is None:
            selected = parse_numberish(detail.get(count_label)) or 0
        status = metric.get("status") or detail.get("巡检状态") or "-"
        if status in ("无当天JSON", "未触发"):
            status = "通过" if not selected else "待执行"
        domain = summary.get("display_domain") or "当前交易域"
        note = f"{domain}实际筛选待处理数为{format_value(selected, 'count')}。"
        if selected:
            note += "确认后可执行对应修复脚本。"
        else:
            note += "无需执行修复。"
        items.append(
            {
                "title": repair.get("title"),
                "date": repair.get("date"),
                "selected": selected,
                "status": status,
                "clicked": detail.get("已点击数"),
                "fixed": detail.get("已修复数"),
                "failed": detail.get("失败数"),
                "success": detail.get("成功明细") or [],
                "failures": detail.get("失败明细") or [],
                "missing": detail.get("缺失字段明细") or [],
                "notes": [note],
            }
        )
    return items

def render_repair_report_html() -> str:
    summary = current_summary()
    repairs = repair_items_from_summary(summary)
    metrics = [
        report_metric("修复巡检项", len(repairs), "延期提测 / 延期上线"),
        report_metric("待处理筛选数", sum(int(item.get("selected") or 0) for item in repairs), "来自修复脚本筛选口径"),
        report_metric("已修复", sum(int(item.get("fixed") or 0) for item in repairs), "成功明细合计"),
        report_metric("失败", sum(int(item.get("failed") or 0) for item in repairs), "失败明细合计"),
        report_metric("巡检日期", summary.get("inspection_date") or "-", summary.get("status") or "-"),
    ]
    rows = []
    for index, item in enumerate(repairs, 1):
        rows.append(
            [
                f'<span class="index">{index}</span>',
                f'<div class="demand">{html_text(item.get("title"))}</div><div class="meta">{html_text("；".join(map(str, item.get("notes") or [])))}</div>',
                html_text(item.get("selected")),
                html_text(item.get("clicked")),
                html_text(item.get("fixed")),
                html_text(item.get("failed")),
                status_badge_html(item.get("status")),
            ]
        )
    sections = [
        table_section("修复概览", "按收银台&内单交易域实际筛选结果展示", ["#", "巡检项", "筛选数", "点击数", "修复数", "失败数", "状态"], rows)
    ]
    for item in repairs:
        success_rows = []
        for index, detail in enumerate(item.get("success") or [], 1):
            success_rows.append(
                [
                    f'<span class="index">{index}</span>',
                    f'<div class="demand">{html_text(detail.get("需求名称") or detail.get("demand_name") or detail.get("name"))}</div>',
                    html_text(detail.get("研发负责人") or detail.get("owner") or detail.get("负责人")),
                    html_text(detail.get("修正后日期") or detail.get("new_value") or detail.get("修正后计划提测日期") or detail.get("修正后计划上线日期")),
                    external_link_html(detail.get("跳转地址") or detail.get("detail_url") or detail.get("url")),
                ]
            )
        sections.append(table_section(str(item.get("title") or "修复明细"), f"状态：{item.get('status') or '-'}", ["#", "需求", "负责人", "修正后日期", "链接"], success_rows, "暂无成功明细"))
    return report_shell("修复巡检报告", "延期提测与延期上线修复结果", metrics, sections, summary.get("generated_at") or "")

def render_thursday_report_html() -> str:
    freshness = thursday_report_freshness()
    if not freshness.get("is_current"):
        return render_freshness_placeholder_report("计划日期顺延报告", freshness, "历史顺延记录不参与本周展示")
    if not THURSDAY_REPORT_HTML_PATH.exists():
        return report_shell("计划日期调整报告", "当前未找到报告文件", [report_metric("状态", "missing", "thursday-to-friday-adjustment/index.html")], [])
    html = THURSDAY_REPORT_HTML_PATH.read_text(encoding="utf-8")
    if '<nav class="report-nav">' in html:
        return html
    return html.replace('<main class="shell">', f'<main class="shell">\n    {report_nav()}', 1)

def read_weekly_metrics() -> dict:
    data = read_json(WEEKLY_METRICS_PATH, {})
    if isinstance(data, dict):
        for metric in data.values():
            if not isinstance(metric, dict):
                continue
            rows = metric.get("rows")
            if not isinstance(rows, dict):
                continue
            legacy_row = rows.pop("支付方案直挂C3", None)
            if legacy_row is not None and "直挂C3" not in rows:
                if isinstance(legacy_row, dict):
                    legacy_row["虚拟组"] = "直挂C3"
                rows["直挂C3"] = legacy_row
    return data if isinstance(data, dict) else {}

def weekly_generated_at() -> str:
    if not WEEKLY_METRICS_PATH.exists():
        return ""
    return datetime.fromtimestamp(WEEKLY_METRICS_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

def preferred_weekly_row(rows: dict) -> tuple[str, dict]:
    preferred_names = ["支付生态研发部", "收银台&内单交易域", "C3汇总"]
    for name in preferred_names:
        if name in rows and isinstance(rows.get(name), dict):
            return name, rows[name]
    for name, row in rows.items():
        if isinstance(row, dict):
            return name, row
    return "-", {}

def weekly_value(row: dict, key: str) -> str:
    return str(row.get(key) or "-")

def render_weekly_report_html() -> str:
    weekly = read_weekly_metrics()
    freshness = weekly_report_freshness(weekly)
    if not freshness.get("is_current"):
        return render_freshness_placeholder_report("周度巡检报告", freshness, "历史周报数据不参与本周展示")
    if not weekly:
        return report_shell(
            "周度巡检报告",
            "当前未找到周度巡检产出文件",
            [report_metric("状态", "missing", "friday-inspection-skill/scripts/out/ine_metrics.json")],
            [],
        )

    metric_order = [
        "延期提测率",
        "延期上线率",
        "双周交付率",
        "技术改造工时占比",
    ]
    available_metrics = [name for name in metric_order if isinstance(weekly.get(name), dict)]
    if not available_metrics:
        available_metrics = [name for name, value in weekly.items() if isinstance(value, dict) and not str(name).startswith("_")]

    overview_rows = []
    detail_sections = []
    metrics = []

    for index, metric_name in enumerate(available_metrics, 1):
        metric = weekly.get(metric_name) or {}
        rows = metric.get("rows") or {}
        focus_name, focus_row = preferred_weekly_row(rows)
        wtd = weekly_value(focus_row, "WTD（当前周期）")
        wtd_delta = weekly_value(focus_row, "WTD（环比差值）")
        mtd = weekly_value(focus_row, "MTD（当前周期）")
        mtd_delta = weekly_value(focus_row, "MTD（同比差值）")
        ytd = weekly_value(focus_row, "YTD（当前周期）")
        metrics.append(report_metric(metric_name, wtd, f"WTD · {focus_name}"))
        overview_rows.append(
            [
                f'<span class="index">{index}</span>',
                f'<div class="demand">{html_text(metric_name)}</div><div class="meta">{html_text(metric.get("title") or "")}</div>',
                html_text(focus_name),
                html_text(wtd),
                html_text(wtd_delta),
                html_text(mtd),
                html_text(mtd_delta),
                html_text(ytd),
            ]
        )

        detail_rows = []
        for row_index, (group_name, row) in enumerate(rows.items(), 1):
            detail_rows.append(
                [
                    f'<span class="index">{row_index}</span>',
                    f'<div class="demand">{html_text(group_name)}</div>',
                    html_text(weekly_value(row, "WTD（当前周期）")),
                    html_text(weekly_value(row, "WTD（环比差值）")),
                    html_text(weekly_value(row, "MTD（当前周期）")),
                    html_text(weekly_value(row, "MTD（同比差值）")),
                    html_text(weekly_value(row, "YTD（当前周期）")),
                ]
            )
        detail_sections.append(
            table_section(
                metric_name,
                metric.get("title") or "",
                ["#", "团队/虚拟组", "WTD", "WTD 环比", "MTD", "MTD 同比", "YTD"],
                detail_rows,
            )
        )

    sections = [
        table_section(
            "核心指标概览",
            "",
            ["#", "指标", "主视角", "WTD", "WTD 环比", "MTD", "MTD 同比", "YTD"],
            overview_rows,
        )
    ]
    sections.extend(detail_sections)
    return report_shell(
        "周度巡检报告",
        "收银台&内单交易域 · 周度 INE 指标巡检",
        metrics,
        sections,
        weekly_generated_at(),
    )

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def out_of_scope_answer() -> str:
    return "这个问题没有命中巡检工具；如果需要执行巡检、刷新报告或修复，请直接说明要执行的动作。"

def merged_ai_config(client_config: dict | None = None) -> dict:
    with AI_CONFIG_LOCK:
        config = load_ai_config()
    incoming = client_config or {}
    for key in ("base_url", "api_key"):
        value = str(incoming.get(key) or "").strip()
        if value:
            config[key] = value
    model_value = str(incoming.get("model") or "").strip()
    if model_value:
        config["model"] = normalize_model_name(model_value)
    return config

_DAILY_INSPECTION_RENDERER: DailyInspectionRenderer | None = None

def daily_inspection_renderer() -> DailyInspectionRenderer:
    global _DAILY_INSPECTION_RENDERER
    if _DAILY_INSPECTION_RENDERER is None:
        _DAILY_INSPECTION_RENDERER = DailyInspectionRenderer(
            template_dir=Path(__file__).resolve().parent / "templates",
            parse_numberish=parse_numberish,
            build_overview=build_overview,
            build_repair_metrics=build_repair_metrics,
            repair_metric_config=REPAIR_METRIC_CONFIG,
        )
    return _DAILY_INSPECTION_RENDERER

def daily_inspection_assessment(summary: dict) -> dict:
    return daily_inspection_renderer().daily_inspection_assessment(summary)

def read_agent_memory(session_id: str = "", lightweight: bool = False) -> dict:
    return summarize_for_prompt(load_memory(AGENT_MEMORY_PATH), session_id, lightweight=lightweight)

def chat_model_context(summary: dict, session_id: str = "") -> dict:
    return {
        "inspection_date": summary.get("inspection_date"),
        "status": summary.get("status"),
        "department_c3": summary.get("department_c3"),
        "display_domain": summary.get("display_domain"),
        "overview": build_overview(summary)[:10],
        "freshness": summary.get("freshness") or data_freshness(),
        "daily_inspection_assessment": daily_inspection_assessment(summary),
        "agent_memory": read_agent_memory(session_id),
    }

SYSTEM_PROMPT = (
    "你是收银台&内单交易域巡检控制台里的中文 AI 助手。"
    "你的第一职责是理解用户真实意图：用户问数据、原因、代码、架构、方案、报告写法或继续上下文时，正常回答；不要把所有问题都改写成巡检执行。"
    "当用户询问具体人员、具体指标、具体需求、负责人、链接、日期、数量、占比或状态时，要先使用本地数据查询工具返回的结果作答；"
    "如果工具结果里有命中，不要说当前数据不存在。"
    "用户明确要求执行巡检、刷新报告、修复、日期顺延等动作时，系统会通过工具链执行；你只需要解释动作、结果和下一步。"
    "回答巡检数据时只能使用提供的巡检摘要、记忆和历史对话，不要编造未提供的数据。"
    "只有当用户明确要求“日常巡检总结/今日巡检结果/按模板输出/报备草稿”时，才严格按照 daily_inspection_assessment.selected_template 输出；"
    "如果用户是在追问原因、解释指标、讨论代码或提优化建议，要自然回答，不要套模板。"
    "不在阈值内的指标如果来自模板，保留模板中的标识、数值、顺序和结构。"
)

def recent_model_history(history_messages: list[dict] | None, limit: int = 8) -> list[dict]:
    return [
        {
            "role": item.get("role") if item.get("role") in ("user", "assistant") else "user",
            "content": str(item.get("content") or "")[:1200],
        }
        for item in (history_messages or [])[-limit:]
        if item.get("content")
    ]

INTENT_ROUTER_PROMPT = (
    "你是巡检助手的意图路由器。只能输出 JSON，不要输出解释。"
    "你的原则是保守调用工具：只有用户明确表达要执行、运行、启动、刷新、生成、修复、顺延、同步或重跑某个动作时，才选择 tool_call。"
    "如果用户只是询问数据、状态、原因、解释、总结、风险、代码、架构、优化建议或继续上下文，tool_call 必须为 null，action 必须为 none。"
    "不要因为消息里出现“巡检、持续交付、技术改造、AI、延期、报告”等关键词就调用工具；这些也可能只是问答。"
    "写操作即使缺少确认短语也要输出工具调用，确认门由系统后置处理。"
)

DATA_QUERY_TOOL_NAME = "query_inspection_data"

def data_query_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": DATA_QUERY_TOOL_NAME,
            "description": "只读查询本地巡检数据、报告产物和历史 JSON。适合查询具体人员、指标、需求、负责人、链接、日期、数量、占比或状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户想查询的数据问题，保留姓名、指标名、需求编码等关键词。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少条命中记录，默认 8。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }

def extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def post_chat_completion(url: str, api_key: str, payload: dict, timeout: int = 45) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body if isinstance(body, dict) else {}

def tool_arguments(raw_arguments) -> dict:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {"query": raw_arguments}
        return parsed if isinstance(parsed, dict) else {}
    return {}

def normalize_data_tool_call(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    name = str(function.get("name") or raw.get("name") or "").strip()
    if name != DATA_QUERY_TOOL_NAME:
        return None
    return {
        "id": str(raw.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
        "name": name,
        "arguments": tool_arguments(function.get("arguments", raw.get("arguments", {}))),
        "source": "model-data-tool",
    }

DATA_LOOKUP_HINTS = (
    "多少",
    "几个",
    "哪",
    "谁",
    "名单",
    "负责人",
    "链接",
    "地址",
    "状态",
    "占比",
    "率",
    "数量",
    "需求",
    "指标",
    "提交",
    "代码",
    "深度用户",
    "延期",
    "提测",
    "上线",
    "交付",
    "工时",
    "日期",
)

def should_prefetch_data_query(message: str, action: str = "none") -> bool:
    text = str(message or "").strip()
    if not text or action != "none":
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in DATA_LOOKUP_HINTS):
        return True
    return bool(re.search(r"[\u4e00-\u9fff]{2,4}", text) and ("ai" in lowered or "AI" in text))

def execute_data_query(query: str, limit: int = 8, source: str = "data-query-tool", session_id: str = "") -> dict:
    result = query_inspection_data(ROOT_DIR, query, limit)
    record_tool_event(
        "data_query_completed",
        {
            "session_id": session_id,
            "source": source,
            "query": query,
            "match_count": result.get("match_count"),
            "matches": (result.get("matches") or [])[:5],
        },
    )
    return result

def append_data_query_context(
    url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    user_message: str,
    session_id: str = "",
    action: str = "none",
) -> list[dict]:
    payload = {
        "model": model,
        "temperature": 0,
        "tools": [data_query_tool_schema()],
        "tool_choice": "auto",
        "messages": [
            *messages,
            {
                "role": "system",
                "content": (
                    "如果用户是在查具体数据，请调用 query_inspection_data。"
                    "如果只是解释、写作或闲聊，可以不调用工具。"
                ),
            },
        ],
    }
    data_result = None
    tool_call = None
    try:
        body = post_chat_completion(url, api_key, payload, timeout=25)
        choices = body.get("choices") or []
        message_payload = (choices[0].get("message") or {}) if choices else {}
        for raw_call in message_payload.get("tool_calls") or []:
            tool_call = normalize_data_tool_call(raw_call)
            if tool_call:
                break
    except Exception as exc:
        record_tool_event(
            "data_query_planner_failed",
            {"session_id": session_id, "query": user_message, "error": str(exc)},
        )

    if tool_call:
        args = tool_call.get("arguments") or {}
        query = str(args.get("query") or user_message).strip()
        limit = int(args.get("limit") or 8)
        record_tool_event(
            "data_query_requested",
            {"session_id": session_id, "tool_call": tool_call, "query": query},
        )
        data_result = execute_data_query(query, limit, "model-data-tool", session_id)
    elif should_prefetch_data_query(user_message, action):
        data_result = execute_data_query(user_message, 8, "data-query-prefetch", session_id)

    if not data_result:
        return messages

    return [
        *messages,
        {
            "role": "system",
            "content": (
                "本地数据查询工具返回 JSON如下。回答用户时优先使用 matches 和 answer_hint；"
                "如果 match_count > 0，不要回答“当前巡检数据没有该指标”。\n"
                f"{json.dumps(data_result, ensure_ascii=False)}"
            ),
        },
    ]

def suppress_nonexplicit_tool_call(message: str, action: str, tool_call: dict | None, source: str, reason: str = "") -> dict | None:
    if action == "none" or has_explicit_action_intent(message, action):
        return None
    return {
        "action": "none",
        "tool_call": None,
        "confidence": 0,
        "reason": reason or "用户是在问答或讨论，没有明确要求执行工具。",
        "source": source,
        "suppressed_tool_call": tool_call,
    }

def route_intent_with_model(
    message: str,
    summary: dict,
    memory: dict,
    client_config: dict,
    history_messages: list[dict] | None = None,
) -> dict:
    fallback_tool_call = detect_tool_call(message)
    fallback = {
        "action": action_from_tool_call(fallback_tool_call),
        "tool_call": fallback_tool_call,
        "source": "rules",
    }
    config = merged_ai_config(client_config)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return fallback

    recent_history = recent_model_history(history_messages, limit=6)
    context = {
        "inspection_date": summary.get("inspection_date"),
        "display_domain": summary.get("display_domain"),
        "daily_inspection_status": daily_inspection_assessment(summary).get("status"),
        "freshness": summary.get("freshness") or data_freshness(),
        "memory": memory,
        "tools": tool_catalog_for_prompt(),
    }
    payload = {
        "model": str(config.get("model") or DEFAULT_MODEL).strip(),
        "temperature": 0,
        "tools": openai_tool_schemas(),
        "tool_choice": "auto",
        "messages": [
            {"role": "system", "content": INTENT_ROUTER_PROMPT},
            *recent_history,
            {
                "role": "user",
                "content": (
                    f"用户消息：{message}\n"
                    f"上下文 JSON：{json.dumps(context, ensure_ascii=False)}\n"
                    "请输出 JSON："
                    '{"tool_call":null 或 {"name":"候选工具名","arguments":{"reason":"一句话原因"}},'
                    '"action":"none 或对应 action id","confidence":0到1,"reason":"一句话原因"}'
                ),
            },
        ],
    }
    request = Request(
        f"{str(config.get('base_url') or DEFAULT_BASE_URL).strip().rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {**fallback, "router_error": str(exc)}

    choices = body.get("choices") or []
    if not choices:
        return fallback
    message_payload = choices[0].get("message") or {}
    native_tool_calls = message_payload.get("tool_calls") or []
    if isinstance(native_tool_calls, list) and native_tool_calls:
        tool_call = normalize_model_tool_call(native_tool_calls[0])
        action = action_from_tool_call(tool_call)
        suppressed = suppress_nonexplicit_tool_call(message, action, tool_call, "native-tool-call", "模型提出了工具调用，但用户没有明确表达执行意图。")
        if suppressed:
            return suppressed
        return {
            "action": action,
            "tool_call": tool_call,
            "confidence": 1 if tool_call else 0,
            "reason": "模型原生 tool_call",
            "source": "native-tool-call",
        }

    content = str(message_payload.get("content") or "")
    routed = extract_json_object(content)
    tool_call = resolve_routed_tool_call({**routed, "source": "llm-router"})
    action = action_from_tool_call(tool_call)
    suppressed = suppress_nonexplicit_tool_call(message, action, tool_call, "llm-router", "路由器提出了工具调用，但用户没有明确表达执行意图。")
    if suppressed:
        return suppressed
    return {
        "action": action,
        "tool_call": tool_call,
        "confidence": routed.get("confidence"),
        "reason": str(routed.get("reason") or ""),
        "source": "llm-router",
    }

def call_chat_model(message: str, action: str, summary: dict, client_config: dict, history_messages: list[dict] | None = None) -> str:
    if action in {"daily_inspection", "daily_inspection_with_repair"}:
        return daily_inspection_assessment(summary)["selected_template"]

    config = merged_ai_config(client_config)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return ""

    base_url = str(config.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    model = str(config.get("model") or DEFAULT_MODEL).strip()
    url = f"{base_url}/chat/completions"
    action_text = {
        "none": "用户没有明确要求启动脚本，只是在询问巡检数据或对话。",
    }.get(action, f"用户想启动动作：{action_title(action)}。")
    context = chat_model_context(summary, str(client_config.get("_session_id") or ""))
    recent_history = recent_model_history(history_messages, limit=8)
    session_id = str(client_config.get("_session_id") or "")
    model_messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        *recent_history,
        {
            "role": "user",
            "content": (
                f"用户消息：{message}\n"
                f"系统判定：{action_text}\n"
                f"当前巡检摘要 JSON：{json.dumps(context, ensure_ascii=False)}\n"
                "请根据用户真实意图回答。"
                "如果用户明确要日常巡检总结、今日巡检结果、按模板输出或报备草稿，严格使用 daily_inspection_assessment.selected_template；"
                "如果用户是在问原因、解释、代码、架构、优化建议、指标含义或继续上下文，正常自然回答，不要套巡检模板，也不要暗示已经启动任务。"
            ),
        },
    ]
    model_messages = append_data_query_context(url, model, api_key, model_messages, message, session_id, action)
    payload = {
        "model": model,
        "temperature": 0.35,
        "messages": model_messages,
    }
    body = post_chat_completion(url, api_key, payload, timeout=45)
    choices = body.get("choices") or []
    if not choices:
        return ""
    message_payload = choices[0].get("message") or {}
    return str(message_payload.get("content") or "").strip()

def call_chat_model_stream(message: str, action: str, summary: dict, client_config: dict, history_messages: list[dict] | None = None):
    if action in {"daily_inspection", "daily_inspection_with_repair"}:
        yield daily_inspection_assessment(summary)["selected_template"]
        return

    config = merged_ai_config(client_config)
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return

    base_url = str(config.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    model = str(config.get("model") or DEFAULT_MODEL).strip()
    url = f"{base_url}/chat/completions"
    action_text = {
        "none": "用户没有明确要求启动脚本，只是在询问巡检数据或对话。",
    }.get(action, f"用户想启动动作：{action_title(action)}。")
    context = chat_model_context(summary, str(client_config.get("_session_id") or ""))
    recent_history = recent_model_history(history_messages, limit=8)
    session_id = str(client_config.get("_session_id") or "")
    model_messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        *recent_history,
        {
            "role": "user",
            "content": (
                f"用户消息：{message}\n"
                f"系统判定：{action_text}\n"
                f"当前巡检摘要 JSON：{json.dumps(context, ensure_ascii=False)}\n"
                "请根据用户真实意图回答。"
                "如果用户明确要日常巡检总结、今日巡检结果、按模板输出或报备草稿，严格使用 daily_inspection_assessment.selected_template；"
                "如果用户是在问原因、解释、代码、架构、优化建议、指标含义或继续上下文，正常自然回答，不要套巡检模板，也不要暗示已经启动任务。"
            ),
        },
    ]
    model_messages = append_data_query_context(url, model, api_key, model_messages, message, session_id, action)
    payload = {
        "model": model,
        "temperature": 0.35,
        "stream": True,
        "messages": model_messages,
    }
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            content = delta.get("content") or choice.get("text") or ""
            if content:
                yield str(content)

def latest_point(points: list[dict]) -> dict:
    for point in reversed(points or []):
        if point.get("value") is not None:
            return point
    return {}

def parse_numberish(value):
    if isinstance(value, (int, float)):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().replace("%", "")
    try:
        parsed = float(text)
    except ValueError:
        return value
    return int(parsed) if parsed.is_integer() else parsed

def repair_history_json_path(repair: dict) -> Path | None:
    json_file = repair.get("json_file")
    if not json_file:
        return None
    path = ROOT_DIR / "daily-inspection-skill" / str(json_file)
    if path.exists():
        return path
    legacy_text = str(json_file)
    normalized_text = legacy_text.replace("reschedule-delayed-test /", "reschedule-delayed-test/")
    normalized = ROOT_DIR / "daily-inspection-skill" / normalized_text
    return normalized if normalized.exists() else path

def derived_repair_status(data: dict, fallback_status: str) -> str:
    results = data.get("results")
    failures = data.get("modify_failed_items")
    modified = data.get("modified_items")
    result_count = len(results) if isinstance(results, list) else 0
    failed_count = len(failures) if isinstance(failures, list) else 0
    modified_count = len(modified) if isinstance(modified, list) else 0
    if failed_count:
        return "存在失败项"
    if result_count and modified_count < result_count:
        return "需人工复核"
    if isinstance(results, list):
        return "通过"
    return fallback_status or "-"

def build_repair_metrics(summary: dict) -> dict[str, dict]:
    metrics: dict[str, dict] = {}
    for repair in summary.get("repair_inspections", []):
        repair_type = repair.get("repair_type")
        config = REPAIR_METRIC_CONFIG.get(repair_type)
        if not config:
            continue

        repair_summary = repair.get("summary") or {}
        value = parse_numberish(repair_summary.get(config["count_label"]))
        value = value if isinstance(value, (int, float)) else 0
        trigger_value = parse_numberish((repair.get("trigger") or {}).get("value"))
        status = repair_summary.get("巡检状态") or "-"
        script_status = str(((repair.get("script") or {}).get("status")) or "")
        if script_status == "skipped" and isinstance(trigger_value, (int, float)) and trigger_value > 0:
            status = "待执行修复"
        date_value = repair_summary.get("巡检日期") or repair.get("date") or summary.get("inspection_date")

        history_path = repair_history_json_path(repair)
        if history_path and history_path.exists():
            data = read_json(history_path, {})
            if isinstance(data, dict):
                results = data.get("results")
                if isinstance(results, list):
                    value = len(results)
                date_value = repair.get("date") or summary.get("inspection_date")
                status = derived_repair_status(data, status)

        metrics[repair_type] = {
            "repair_type": repair_type,
            "key": config["metric_key"],
            "label": config["label"],
            "caption": config["caption"],
            "indicator_type": config["indicator_type"],
            "value": value,
            "display_value": format_value(value, "count"),
            "unit": "count",
            "date": date_value,
            "status": status,
            "title": f"{summary.get('display_domain') or '当前交易域'}修复筛选结果",
        }
    return metrics

def first_present_value(item: dict, *keys: str):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None

def external_link_html(url: str | None, label: str = "打开详情") -> str:
    value = str(url or "").strip()
    if not value:
        return '<span class="muted">-</span>'
    escaped_url = html_text(value)
    return f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">{html_text(label)}</a>'

def normalize_ai_user_for_summary(item: dict) -> dict:
    submit_rate = first_present_value(
        item,
        "ai_code_local_submit_rate",
        "AI代码本地提交占比",
        "AI 代码本地提交占比",
        "AI代码本地提交占比(%)",
        "AI 代码本地提交占比(%)",
    )
    return {
        "erp": first_present_value(item, "erp", "用户erp", "用户 erp", "用户ERP") or "",
        "name": first_present_value(item, "name", "用户姓名", "姓名", "用户erp", "用户 erp", "erp") or "",
        "ai_code_local_submit_rate": parse_numberish(submit_rate),
        "is_deep_user": first_present_value(item, "is_deep_user", "是否深度用户") or "",
    }

def ai_inspection_target_date(today: date | None = None) -> date:
    value = today or datetime.now().date()
    if value.weekday() == 0:
        return value - timedelta(days=3)
    if value.weekday() == 6:
        return value - timedelta(days=2)
    return value - timedelta(days=1)

def choose_ai_json(inspection_json: Path, query_json: Path) -> Path:
    if inspection_json.exists() and query_json.exists():
        inspection_data = read_json(inspection_json, None)
        if isinstance(inspection_data, dict) and (inspection_data.get("inspection_date") or inspection_data.get("query_date")):
            return inspection_json
        if query_json.stat().st_mtime > inspection_json.stat().st_mtime:
            return query_json
        return inspection_json
    if inspection_json.exists():
        return inspection_json
    if query_json.exists():
        return query_json
    return inspection_json

def load_runtime_ai_inspection() -> dict | None:
    inspection_day = datetime.now().date().isoformat()
    query_day = ai_inspection_target_date().isoformat()
    source_json = choose_ai_json(
        AI_INSPECTION_OUT_DIR / f"non_deep_users_{inspection_day}.json",
        AI_INSPECTION_OUT_DIR / f"non_deep_users_{query_day}.json",
    )
    output_json = choose_ai_json(
        AI_INSPECTION_OUT_DIR / f"non_deep_user_names_{inspection_day}.json",
        AI_INSPECTION_OUT_DIR / f"non_deep_user_names_{query_day}.json",
    )

    if source_json.exists():
        try:
            raw_data = read_json(source_json, None)
            raw_users = raw_data if isinstance(raw_data, list) else raw_data.get("users", []) if isinstance(raw_data, dict) else []
            users = [
                normalize_ai_user_for_summary(item)
                for item in raw_users
                if isinstance(item, dict)
                and str(first_present_value(item, "是否深度用户", "is_deep_user") or "").strip() == "否"
            ]
            names = [user["name"] for user in users if user.get("name")]
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": "ai_inspection",
                "indicator_name": "AI 深度用户",
                "status": raw_data.get("status", "success") if isinstance(raw_data, dict) else "success",
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}" if output_json.exists() else "",
                "count": raw_data.get("count", len(names)) if isinstance(raw_data, dict) else len(names),
                "names": names,
                "users": users,
            }
        except Exception as exc:
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": "ai_inspection",
                "indicator_name": "AI 深度用户",
                "status": "failed",
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}" if output_json.exists() else "",
                "count": 0,
                "names": [],
                "users": [],
                "error": str(exc),
            }

    if output_json.exists():
        try:
            data = read_json(output_json, None)
            if isinstance(data, dict):
                users = [normalize_ai_user_for_summary(item) for item in data.get("users", []) if isinstance(item, dict)]
                names = data.get("names") or [user["name"] for user in users if user.get("name")]
                count = data.get("count", len(names))
                status = data.get("status", "success")
            elif isinstance(data, list):
                users = [normalize_ai_user_for_summary(item) for item in data if isinstance(item, dict)]
                names = [user["name"] for user in users if user.get("name")]
                count = len(names)
                status = "success"
            else:
                raise ValueError(f"Unexpected data type: {type(data)}")
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": "ai_inspection",
                "indicator_name": "AI 深度用户",
                "status": status,
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}",
                "count": count,
                "names": names,
                "users": users,
            }
        except Exception as exc:
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": "ai_inspection",
                "indicator_name": "AI 深度用户",
                "status": "failed",
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}",
                "count": 0,
                "names": [],
                "users": [],
                "error": str(exc),
            }

    return None

def refresh_runtime_summary_blocks(summary: dict) -> dict:
    payload = dict(summary)
    ai_inspection = load_runtime_ai_inspection()
    if ai_inspection:
        payload["ai_inspection"] = ai_inspection
    return payload

def current_summary() -> dict:
    return compact_summary(refresh_runtime_summary_blocks(read_json(SUMMARY_PATH, {})))

def build_overview(summary: dict) -> list[dict]:
    cards: list[dict] = []
    for indicator in summary.get("indicators", []):
        focus_key = indicator.get("focus_metric_key")
        history = indicator.get("history", {})
        units = indicator.get("unit", {})
        point = latest_point(history.get(focus_key, []))
        cards.append(
            {
                "key": focus_key,
                "title": indicator.get("indicator_name") or indicator.get("skill_name"),
                "label": METRIC_LABELS.get(focus_key, focus_key),
                "value": point.get("value"),
                "display_value": format_value(point.get("value"), units.get(focus_key, "")),
                "unit": units.get(focus_key, ""),
                "date": point.get("date") or summary.get("inspection_date"),
                "status": indicator.get("status", "unknown"),
                "indicator_type": indicator.get("indicator_type"),
                "caption": "OKR 指标",
            }
        )

    repair_metrics = build_repair_metrics(summary)
    for repair_type in ("delayed_test", "delayed_online"):
        metric = repair_metrics.get(repair_type)
        if not metric:
            continue
        cards.append(
            {
                "key": metric["key"],
                "title": metric["title"],
                "label": metric["label"],
                "value": metric["value"],
                "display_value": metric["display_value"],
                "unit": metric["unit"],
                "date": metric["date"],
                "status": metric["status"],
                "indicator_type": metric["indicator_type"],
                "caption": metric["caption"],
            }
        )

    continuous = summary.get("continuous_delivery") or {}
    metrics = continuous.get("metrics") or {}
    units = continuous.get("unit") or {}
    key = "continuous_delivery_team_space_online_requirement_rate"
    if key in metrics:
        cards.append(
            {
                "key": key,
                "title": continuous.get("indicator_name", "持续交付"),
                "label": METRIC_LABELS.get(key, key),
                "value": metrics.get(key),
                "display_value": format_value(metrics.get(key), units.get(key, "")),
                "unit": units.get(key, ""),
                "date": continuous.get("date") or summary.get("inspection_date"),
                "status": continuous.get("status", "unknown"),
                "indicator_type": "continuous_delivery",
                "caption": "交付结构",
            }
        )

    ai = summary.get("ai_inspection") or {}
    if ai:
        cards.append(
            {
                "key": "ai_non_deep_users",
                "title": ai.get("indicator_name", "AI 巡检"),
                "label": "AI 非深度用户数",
                "value": ai.get("count"),
                "display_value": format_value(ai.get("count")),
                "unit": "人",
                "date": ai.get("date") or summary.get("inspection_date"),
                "status": ai.get("status", "unknown"),
                "indicator_type": "ai",
                "caption": "AI 使用",
            }
        )

    return cards

def compact_summary(summary: dict) -> dict:
    payload = dict(summary)
    payload["repair_metrics"] = build_repair_metrics(summary)
    payload["overview"] = build_overview(summary)
    payload["freshness"] = data_freshness()
    payload["loaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["asset_version"] = metric_preview_asset_version()
    payload["chart_options"] = build_chart_options(payload)
    payload["report_html_exists"] = REPORT_HTML_PATH.exists()
    return payload

def find_history_metric(summary: dict, key: str) -> dict | None:
    for indicator in summary.get("indicators", []):
        unit = indicator.get("unit") or {}
        points = (indicator.get("history") or {}).get(key)
        if points:
            return {
                "id": f"{indicator.get('indicator_type')}:{key}",
                "key": key,
                "title": METRIC_LABELS.get(key, key),
                "unit": unit.get(key) or (points[0] or {}).get("unit") or "",
                "points": points,
            }
    return None

def single_point_metric(metric_id: str, key: str, title: str, unit: str, date: str, value) -> dict:
    return {
        "id": metric_id,
        "key": key,
        "title": title,
        "unit": unit,
        "points": [{"date": date or "-", "value": value, "unit": unit}],
    }

def date_from_filename(path: Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else ""

def chart_week_bounds(summary: dict):
    anchor = parse_date(summary.get("inspection_date")) or datetime.now().date()
    return week_start(anchor), week_end(anchor)

def filter_points_to_current_week(points: list[dict], summary: dict) -> list[dict]:
    start, end = chart_week_bounds(summary)
    filtered = []
    for point in points:
        point_date = parse_date(point.get("date"))
        if point_date and start <= point_date <= end:
            filtered.append(point)
    return filtered

def filter_chart_option_to_current_week(option: dict | None, summary: dict) -> dict | None:
    if not option:
        return None
    start, end = chart_week_bounds(summary)
    return {
        **option,
        "points": filter_points_to_current_week(list(option.get("points") or []), summary),
        "range": {
            "type": "current_week",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
    }

def metric_series_option(metric_id: str, key: str, title: str, unit: str, points: list[dict], fallback_date: str, fallback_value) -> dict:
    by_date: dict[str, dict] = {}
    for point in points:
        date = str(point.get("date") or "").strip()
        value = point.get("value")
        if not date or value is None or value == "":
            continue
        by_date[date] = {"date": date, "value": value, "unit": point.get("unit") or unit}
    if fallback_date and fallback_date not in by_date and fallback_value is not None:
        by_date[fallback_date] = {"date": fallback_date, "value": fallback_value, "unit": unit}
    sorted_points = [by_date[key] for key in sorted(by_date)]
    return {
        "id": metric_id,
        "key": key,
        "title": title,
        "unit": unit,
        "points": sorted_points or [{"date": fallback_date or "-", "value": fallback_value, "unit": unit}],
    }

def ai_non_deep_user_points(summary: dict) -> list[dict]:
    points: list[dict] = []
    for path in sorted(AI_INSPECTION_OUT_DIR.glob("non_deep_users_*.json")):
        data = read_json(path, None)
        if isinstance(data, list):
            value = len(data)
            date_value = date_from_filename(path)
        elif isinstance(data, dict):
            users = data.get("users")
            value = data.get("count")
            if value is None and isinstance(users, list):
                value = len(users)
            date_value = str(data.get("inspection_date") or data.get("date") or date_from_filename(path))
        else:
            continue
        points.append({"date": date_value, "value": value, "unit": "count"})

    for path in sorted(AI_INSPECTION_HISTORY_DIR.glob("*.json")):
        data = read_json(path, None)
        if not isinstance(data, dict):
            continue
        users = data.get("users")
        value = data.get("count")
        if value is None and isinstance(users, list):
            value = len(users)
        date_value = str(data.get("inspection_date") or data.get("date") or date_from_filename(path) or path.stem)
        points.append({"date": date_value, "value": value, "unit": "count", "source": "history"})

    ai = summary.get("ai_inspection") or {}
    current_value = ai.get("count")
    if current_value is None and isinstance(ai.get("users"), list):
        current_value = len(ai.get("users") or [])
    points.append({"date": ai.get("date") or summary.get("inspection_date"), "value": current_value, "unit": "count"})
    return points

def continuous_delivery_points(summary: dict, key: str) -> list[dict]:
    points: list[dict] = []
    paths = [
        *sorted((CONTINUOUS_DELIVERY_OUT_DIR / "history").glob("*.json")),
        *sorted(CONTINUOUS_DELIVERY_OUT_DIR.glob("continuous_delivery_*.json")),
    ]
    for path in paths:
        data = read_json(path, {})
        if not isinstance(data, dict):
            continue
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        value = metrics.get(key)
        if value is None:
            continue
        points.append(
            {
                "date": data.get("date") or date_from_filename(path),
                "value": parse_numberish(value),
                "unit": ((data.get("unit") or {}) if isinstance(data.get("unit"), dict) else {}).get(key) or "%",
            }
        )

    delivery = summary.get("continuous_delivery") or {}
    metrics = delivery.get("metrics") if isinstance(delivery.get("metrics"), dict) else {}
    points.append(
        {
            "date": delivery.get("date") or summary.get("inspection_date"),
            "value": parse_numberish(metrics.get(key)),
            "unit": ((delivery.get("unit") or {}) if isinstance(delivery.get("unit"), dict) else {}).get(key) or "%",
        }
    )
    return points

def history_metric_points(summary: dict, indicator_type: str, key: str) -> list[dict]:
    for indicator in summary.get("indicators", []):
        if indicator.get("indicator_type") != indicator_type:
            continue
        points = (indicator.get("history") or {}).get(key)
        if isinstance(points, list):
            return [point for point in points if isinstance(point, dict)]
    return []

def repair_history_count_map(repair_type: str) -> dict[str, int]:
    history_dir = REPAIR_HISTORY_DIRS.get(repair_type)
    if not history_dir or not history_dir.exists():
        history_dir = LEGACY_REPAIR_HISTORY_DIRS.get(repair_type)
    if not history_dir or not history_dir.exists():
        return {}
    counts: dict[str, int] = {}
    for path in sorted(history_dir.glob("*.json")):
        date_value = date_from_filename(path) or path.stem
        data = read_json(path, {})
        if not isinstance(data, dict):
            continue
        results = data.get("results")
        counts[date_value] = len(results) if isinstance(results, list) else 0
    return counts

def repair_trend_option(summary: dict, repair_type: str, indicator_type: str, key: str) -> dict:
    repair_metric = (summary.get("repair_metrics") or {}).get(repair_type, {})
    focus = next((item for item in summary.get("focus_series", []) or [] if item.get("indicator_type") == indicator_type), {})
    focus_metric = next((item for item in focus.get("metrics", []) or [] if item.get("key") == key), {})
    repair_counts = repair_history_count_map(repair_type)
    for point in focus_metric.get("points") or []:
        date_value = str(point.get("date") or "").strip()
        value = parse_numberish(point.get("value"))
        if date_value and isinstance(value, (int, float)):
            repair_counts[date_value] = int(value)

    repair_date = repair_metric.get("date") or summary.get("inspection_date")
    current_value = parse_numberish(repair_metric.get("value"))
    if repair_date and isinstance(current_value, (int, float)):
        repair_counts[str(repair_date)] = int(current_value)

    points: list[dict] = []
    for point in history_metric_points(summary, indicator_type, key):
        date_value = str(point.get("date") or "").strip()
        raw_value = parse_numberish(point.get("value"))
        if not date_value or not isinstance(raw_value, (int, float)):
            continue
        if raw_value <= 0:
            value = 0
        else:
            value = repair_counts.get(date_value)
            if value is None:
                value = raw_value
        points.append(
            {
                "date": date_value,
                "value": value,
                "unit": "count",
                "source": "repair_history" if date_value in repair_counts else "okr_trigger",
            }
        )

    seen_dates = {point.get("date") for point in points}
    for date_value, value in repair_counts.items():
        if date_value not in seen_dates:
            points.append({"date": date_value, "value": value, "unit": "count", "source": "repair_history"})
    points = sorted(points, key=lambda point: str(point.get("date") or ""))

    return {
        "id": f"{indicator_type}:{key}",
        "key": key,
        "title": METRIC_LABELS.get(key, repair_metric.get("label") or key),
        "unit": "count",
        "points": points or [{"date": repair_date or "-", "value": repair_metric.get("value", 0), "unit": "count"}],
    }

def build_chart_options(summary: dict) -> list[dict]:
    options = [
        repair_trend_option(summary, "delayed_test", "delay_test_rate", "delayed_test_requirements"),
        repair_trend_option(summary, "delayed_online", "delay_online_rate", "delayed_online_requirements"),
        find_history_metric(summary, "technical_refactor_working_hours_rate"),
        find_history_metric(summary, "biweekly_delivery_rate"),
    ]
    chart_options = [option for option in options if option]
    ai = summary.get("ai_inspection") or {}
    delivery = summary.get("continuous_delivery") or {}
    chart_options.append(
        metric_series_option(
            "ai_inspection:ai_non_deep_users",
            "ai_non_deep_users",
            "AI 深度用户为否",
            "count",
            ai_non_deep_user_points(summary),
            ai.get("date") or summary.get("inspection_date"),
            ai.get("count") or 0,
        )
    )
    delivery_key = "continuous_delivery_team_space_online_requirement_rate"
    chart_options.append(
        metric_series_option(
            f"continuous_delivery:{delivery_key}",
            delivery_key,
            "持续交付占比",
            "%",
            continuous_delivery_points(summary, delivery_key),
            delivery.get("date") or summary.get("inspection_date"),
            (delivery.get("metrics") or {}).get(delivery_key, 0),
        )
    )
    weekly_options = [
        option
        for option in (filter_chart_option_to_current_week(option, summary) for option in chart_options)
        if option
    ]
    return weekly_options[:6]

def sync_public_static_site() -> dict:
    assets = sync_metric_preview_assets()
    summary = current_summary()
    chart_options = build_chart_options(summary)
    preview_assets = {
        str(card.get("key") or ""): metric_preview_asset(str(card.get("key") or ""))
        for card in summary.get("overview", [])
    }
    files = {
        STATIC_ROOT_INDEX_PATH: build_static_site_index_html(summary, chart_options, preview_assets),
        STATIC_ROOT_DAILY_REPORT_PATH: static_report_shell("日常巡检报告", "daily", extract_report_main_content(render_daily_report_html())),
        STATIC_ROOT_WEEKLY_REPORT_PATH: static_report_shell("周度巡检报告", "weekly", extract_report_main_content(render_weekly_report_html())),
        STATIC_ROOT_REPAIR_REPORT_PATH: static_report_shell("修复巡检报告", "repair", extract_report_main_content(render_repair_report_html())),
        STATIC_ROOT_THURSDAY_REPORT_PATH: static_report_shell("计划日期调整报告", "thursday", extract_report_main_content(render_thursday_report_html())),
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "file": str(STATIC_ROOT_INDEX_PATH),
        "files": [str(path) for path in files],
        "assets": assets,
        "updated_at": now_text(),
    }

def metric_lines(summary: dict) -> list[str]:
    lines: list[str] = []
    for card in build_overview(summary):
        unit = card.get("unit") or ""
        suffix = "人" if card["key"] == "ai_non_deep_users" else display_unit(unit)
        if suffix in ("%", ""):
            value = card["display_value"]
        else:
            value = f"{card['display_value']}{suffix}"
        lines.append(f"{card['label']}：{value}（{card.get('date') or '-'}）")
    return lines

def missing_or_partial(summary: dict) -> list[str]:
    issues: list[str] = []
    for indicator in summary.get("indicators", []):
        status = indicator.get("status")
        if status != "success":
            issues.append(f"{indicator.get('indicator_name') or indicator.get('skill_name')} 状态为 {status}")

        for metric_key, points in (indicator.get("history") or {}).items():
            if any(point.get("value") is None for point in points or []):
                issues.append(f"{METRIC_LABELS.get(metric_key, metric_key)} 存在空值")

    for block_name in ("ai_inspection", "continuous_delivery"):
        block = summary.get(block_name) or {}
        if block and block.get("status") not in ("success", None):
            issues.append(f"{block.get('indicator_name') or block_name} 状态为 {block.get('status')}")

    for repair in summary.get("repair_inspections", []):
        status = (repair.get("summary") or {}).get("巡检状态")
        if status not in ("通过", "未触发", None):
            issues.append(f"{repair.get('title')} 状态为 {status}")
    return issues

def ai_user_names(summary: dict) -> list[str]:
    ai = summary.get("ai_inspection") or {}
    names = ai.get("names") or []
    if names:
        return [str(name) for name in names]
    return [str(user.get("name")) for user in ai.get("users", []) if user.get("name")]

def answer_chat(message: str, summary: dict, action: str = "none", model_answer: str = "") -> str:
    text = (message or "").strip()
    lowered = text.lower()
    issues = missing_or_partial(summary)
    lines = metric_lines(summary)
    names = ai_user_names(summary)

    if not text:
        return "你可以直接问我今天指标、异常项、AI 非深度用户，或让我生成一段 JoyClaw 报备草稿。"

    if action != "none":
        title = action_title(action)
        prefix = f"已开始执行：{title}。任务面板会持续刷新步骤、状态和最近日志。"
        return f"{prefix}\n{model_answer}" if model_answer else prefix

    if model_answer:
        return model_answer

    if not is_inspection_related(text, action):
        return "这个问题没有命中巡检工具，也没有可用的大模型回答。你可以先检查模型配置，或换成巡检数据、项目逻辑、代码实现相关的问题继续问我。"

    if any(token in text for token in ("报备", "周报", "总结", "草稿")):
        highlights = "；".join(lines[:7])
        issue_text = "；".join(issues[:4]) if issues else "暂无明显缺失或失败项"
        return (
            f"{summary.get('display_domain') or summary.get('department_c3')}巡检结果：{highlights}。"
            f"当前整体状态为 {summary.get('status')}，需关注：{issue_text}。"
        )

    if any(token in text for token in ("异常", "风险", "问题", "缺失", "partial", "失败")):
        if not issues:
            return "当前巡检数据里没有明显异常项，整体状态看起来比较平稳。"
        return "我看到这些需要关注的点：\n" + "\n".join(f"- {item}" for item in issues[:8])

    if "ai" in lowered or "非深度" in text or "名单" in text:
        if not names:
            return "当前报告里没有读取到 AI 非深度用户名单。"
        preview = "、".join(names[:18])
        tail = f"等 {len(names)} 人" if len(names) > 18 else f"共 {len(names)} 人"
        return f"AI 非深度用户名单：{preview}，{tail}。"

    if any(token in text for token in ("延期", "提测", "上线")):
        related = [line for line in lines if "延期" in line or "提测" in line or "上线" in line]
        return "相关指标如下：\n" + "\n".join(f"- {line}" for line in related)

    if any(token in text for token in ("指标", "今天", "数据", "多少", "概览")):
        return "今天的核心数据：\n" + "\n".join(f"- {line}" for line in lines[:10])

    if re.search(r"双周|交付", text):
        related = [line for line in lines if "交付" in line or "双周" in line]
        return "交付相关数据：\n" + "\n".join(f"- {line}" for line in related)

    return (
        "我先按本地巡检数据回答：\n"
        + "\n".join(f"- {line}" for line in lines[:8])
        + "\n\n这一版是原型里的数据感知对话，后面可以把这里替换成真实大模型并保留同一套上下文。"
    )

def repair_memory_items(summary: dict) -> list[dict]:
    items: list[dict] = []
    for repair in summary.get("repair_inspections", []):
        repair_summary = repair.get("summary") or {}
        details = repair_summary.get("成功明细") or []
        if not isinstance(details, list):
            details = []
        count = repair_summary.get("筛选延期提测数", repair_summary.get("筛选延期上线数", 0))
        success_count = repair_summary.get("已修复数", 0)
        failed_count = repair_summary.get("失败数", 0)
        if not (count or success_count or failed_count or details):
            continue
        items.append(
            {
                "repair_type": repair.get("repair_type"),
                "title": repair.get("title"),
                "status": repair_summary.get("巡检状态"),
                "count": count,
                "success_count": success_count,
                "failed_count": failed_count,
                "details": [
                    {
                        "code": item.get("需求编码"),
                        "name": item.get("需求名称"),
                        "owner": item.get("研发负责人"),
                        "url": item.get("跳转地址") or item.get("页面URL"),
                    }
                    for item in details
                    if isinstance(item, dict)
                ],
            }
        )
    return items

def write_agent_memory_from_state(state: dict) -> None:
    summary = state.get("summary") or {}
    assessment = daily_inspection_assessment(summary) if summary else {}
    memory = load_memory(AGENT_MEMORY_PATH)
    repairs = repair_memory_items(summary)
    memory = update_memory_from_turn(memory, state, assessment, repairs)
    save_memory(AGENT_MEMORY_PATH, memory)

_INSPECTION_AGENT: InspectionAgent | None = None

def inspection_agent() -> InspectionAgent:
    global _INSPECTION_AGENT
    if _INSPECTION_AGENT is None:
        _INSPECTION_AGENT = InspectionAgent(
            InspectionAgentDeps(
                begin_chat_turn=begin_chat_turn,
                finish_chat_turn=finish_chat_turn,
                read_summary=current_summary,
                read_memory=read_agent_memory,
                detect_tool_call=detect_tool_call,
                route_intent=route_intent_with_model,
                resolve_routed_tool_call=resolve_routed_tool_call,
                action_from_tool_call=action_from_tool_call,
                build_plan=build_agent_plan,
                assess_summary=daily_inspection_assessment,
                evaluate_state=evaluate_agent_state,
                is_inspection_related=is_inspection_related,
                out_of_scope_answer=out_of_scope_answer,
                tool_requires_confirmation=tool_requires_confirmation,
                tool_title=tool_title,
                execute_tool_call=execute_tool_call,
                wait_for_job=wait_for_job,
                next_tool_call=next_tool_call_after_result,
                render_tool_chain_summary=render_tool_chain_summary,
                render_failure_recovery=render_failure_recovery,
                call_chat_model=call_chat_model,
                call_chat_model_stream=call_chat_model_stream,
                answer_chat=answer_chat,
                write_memory=write_agent_memory_from_state,
                audit_tool_event=record_tool_event,
            )
        )
    return _INSPECTION_AGENT

class PrototypeHandler(BaseHTTPRequestHandler):
    server_version = "JoyClawPrototype/0.1"

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/health":
            self.send_response(204)
            self.end_headers()
            return None
        if path == "/":
            return self.serve_file(STATIC_DIR / "index.html", head_only=True)
        if path.startswith("/static/"):
            rel_path = path.removeprefix("/static/")
            return self.serve_file((STATIC_DIR / rel_path).resolve(), base=STATIC_DIR.resolve(), head_only=True)
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/health":
            self.send_response(204)
            self.end_headers()
            return None
        if path == "/":
            return self.serve_file(STATIC_DIR / "index.html")
        if path == "/api/summary":
            sync_metric_preview_assets()
            summary = current_summary()
            return self.write_json(summary)
        if path == "/api/actions":
            return self.write_json({"actions": public_actions(), "tools": public_tools()})
        if path == "/api/tools":
            return self.write_json({"tools": public_tools(), "openai_tools": openai_tool_schemas()})
        if path == "/api/tools/audit":
            return self.write_json({"events": recent_tool_events(100)})
        if path == "/api/failures":
            return self.write_json({"records": recent_failure_records(100)})
        if path == "/api/ai-config":
            with AI_CONFIG_LOCK:
                return self.write_json(public_ai_config(load_ai_config()))
        if path == "/api/chat/sessions":
            with CHAT_LOCK:
                store = load_chat_store()
                if not store.get("sessions"):
                    create_chat_session(store)
                    save_chat_store(store)
                return self.write_json(
                    {
                        "sessions": sorted_chat_sessions(store),
                        "active_session_id": store.get("active_session_id") or "",
                    }
                )
        if path.startswith("/api/chat/sessions/"):
            session_id = path.removeprefix("/api/chat/sessions/").strip("/")
            with CHAT_LOCK:
                store = load_chat_store()
                session = find_chat_session(store, session_id)
                if session:
                    store["active_session_id"] = session["id"]
                    save_chat_store(store)
            if not session:
                return self.send_error(404)
            return self.write_json(
                {
                    "session": session,
                    "sessions": sorted_chat_sessions(store),
                    "active_session_id": store.get("active_session_id") or "",
                }
            )
        if path == "/api/jobs":
            with JOB_LOCK:
                jobs = sorted(JOBS.values(), key=lambda item: item.get("created_at", ""), reverse=True)
            return self.write_json({"jobs": jobs[:20]})
        if path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/").strip("/")
            with JOB_LOCK:
                job = JOBS.get(job_id)
            if not job:
                return self.send_error(404)
            return self.write_json(job)
        if path in ("/report", "/reports/daily"):
            return self.write_html(render_daily_report_html())
        if path == "/reports/weekly":
            return self.write_html(render_weekly_report_html())
        if path == "/reports/repair":
            return self.write_html(render_repair_report_html())
        if path == "/reports/thursday":
            return self.write_html(render_thursday_report_html())
        if path.startswith("/static/"):
            rel_path = path.removeprefix("/static/")
            return self.serve_file((STATIC_DIR / rel_path).resolve(), base=STATIC_DIR.resolve())
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/chat", "/api/chat/stream", "/api/actions/run", "/api/tools/call", "/api/tools/audit/clear", "/api/jobs/clear", "/api/chat/sessions", "/api/chat/sessions/clear-all", "/api/ai-config", "/api/ai-config/test", "/api/public-site/sync") and not (
            parsed.path.startswith("/api/chat/sessions/") and parsed.path.endswith("/clear")
        ):
            return self.send_error(404)

        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}

        if parsed.path == "/api/jobs/clear":
            with JOB_LOCK:
                JOBS.clear()
            return self.write_json({"ok": True, "jobs": []})

        if parsed.path == "/api/tools/audit/clear":
            clear_tool_events()
            return self.write_json({"ok": True, "events": []})

        if parsed.path == "/api/ai-config":
            with AI_CONFIG_LOCK:
                config = save_ai_config(payload)
                return self.write_json(public_ai_config(config))

        if parsed.path == "/api/ai-config/test":
            config = merged_ai_config(payload)
            if not config.get("api_key"):
                return self.write_json({"ok": False, "message": "后端还没有配置 API Key。", "config": public_ai_config(config)})
            try:
                answer = call_chat_model("请只回复：连接正常", "none", current_summary(), config, [])
            except Exception as exc:
                return self.write_json({"ok": False, "message": f"模型连接失败：{exc}", "config": public_ai_config(config)})
            return self.write_json({"ok": bool(answer), "message": answer or "模型没有返回内容。", "config": public_ai_config(config)})

        if parsed.path == "/api/public-site/sync":
            return self.write_json(sync_public_static_site())

        if parsed.path == "/api/chat/sessions":
            with CHAT_LOCK:
                store = load_chat_store()
                session = create_chat_session(store)
                save_chat_store(store)
                return self.write_json({"session": session, "sessions": sorted_chat_sessions(store)})

        if parsed.path == "/api/chat/sessions/clear-all":
            with CHAT_LOCK:
                store = {"sessions": [], "active_session_id": ""}
                session = create_chat_session(store)
                save_chat_store(store)
                return self.write_json({"session": session, "sessions": sorted_chat_sessions(store)})

        if parsed.path.startswith("/api/chat/sessions/") and parsed.path.endswith("/clear"):
            session_id = parsed.path.removeprefix("/api/chat/sessions/").removesuffix("/clear").strip("/")
            with CHAT_LOCK:
                store = load_chat_store()
                session = find_chat_session(store, session_id)
                if not session:
                    return self.send_error(404)
                session["title"] = "新对话"
                session["messages"] = default_chat_messages()
                session["updated_at"] = now_text()
                store["active_session_id"] = session["id"]
                save_chat_store(store)
                return self.write_json({"session": session, "sessions": sorted_chat_sessions(store)})

        if parsed.path in ("/api/actions/run", "/api/tools/call"):
            tool_call = validate_tool_call(payload.get("tool_call") if isinstance(payload.get("tool_call"), dict) else None)
            action = str(payload.get("action") or "")
            if not tool_call and action:
                tool_call = tool_call_from_action(action, source="api")
            action = action_from_tool_call(tool_call)
            message = str(payload.get("message") or "")
            if action == "none":
                return self.write_json({"error": "unknown_tool", "message": "未知工具或动作"})
            required = tool_requires_confirmation(tool_call, message)
            if required:
                record_tool_event(
                    "api_tool_confirmation_required",
                    {"action": action, "tool_call": tool_call, "required_phrase": required},
                )
                return self.write_json(
                    {
                        "error": "confirmation_required",
                        "action": action,
                        "tool_call": tool_call,
                        "required_phrase": required,
                        "answer": f"这个动作会修改线上数据。请在输入框里包含“{required}”后再执行。",
                    }
                )
            tool_result = execute_tool_call(tool_call)
            record_tool_event(
                "api_tool_queued" if tool_result.get("ok") else "api_tool_rejected",
                {"action": action, "tool_call": tool_call, "tool_result": tool_result},
            )
            return self.write_json(
                {
                    "action": action,
                    "tool_call": tool_call,
                    "tool_result": tool_result,
                    "job": tool_result.get("job"),
                    "answer": tool_result.get("message") or f"已开始执行：{tool_title(tool_call)}。",
                }
            )

        if parsed.path == "/api/chat/stream":
            return self.handle_chat_stream(payload)

        return self.write_json(inspection_agent().invoke(payload))

    def handle_chat_stream(self, payload: dict):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        for event, event_payload in inspection_agent().stream(payload):
            self.write_sse(event, event_payload)
        return None

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/chat/sessions/"):
            return self.send_error(404)

        session_id = parsed.path.removeprefix("/api/chat/sessions/").strip("/")
        if not session_id:
            return self.send_error(404)

        with CHAT_LOCK:
            store = load_chat_store()
            sessions = store.get("sessions") or []
            next_sessions = [session for session in sessions if session.get("id") != session_id]
            if len(next_sessions) == len(sessions):
                return self.send_error(404)

            store["sessions"] = next_sessions
            active_session_id = store.get("active_session_id") or ""
            if active_session_id == session_id:
                if next_sessions:
                    replacement = sorted(next_sessions, key=lambda item: item.get("updated_at", ""), reverse=True)[0]
                else:
                    replacement = create_chat_session(store)
                store["active_session_id"] = replacement.get("id") or ""
            elif not next_sessions:
                replacement = create_chat_session(store)
                store["active_session_id"] = replacement.get("id") or ""

            active_session = find_chat_session(store, store.get("active_session_id") or "")
            save_chat_store(store)

        return self.write_json(
            {
                "ok": True,
                "deleted_session_id": session_id,
                "session": active_session,
                "sessions": sorted_chat_sessions(store),
                "active_session_id": store.get("active_session_id") or "",
            }
        )

    def write_sse(self, event: str, payload: dict):
        data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()
        return None

    def serve_file(self, path: Path, base: Path | None = None, head_only: bool = False):
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            return self.send_error(404)
        if base and not path_is_within(resolved, base.resolve()):
            return self.send_error(403)
        if not resolved.exists() or not resolved.is_file():
            return self.send_error(404)

        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)
        return None

    def write_json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return None

    def write_html(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
        return None

    def log_message(self, fmt, *args):
        print(f"[prototype] {self.address_string()} - {fmt % args}")

def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), PrototypeHandler)
    print("JoyClaw prototype running at http://127.0.0.1:8765")
    server.serve_forever()

if __name__ == "__main__":
    main()
