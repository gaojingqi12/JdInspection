from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
SUMMARY_PATH = ROOT_DIR / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "weekly-inspection-summary.json"
REPORT_HTML_PATH = ROOT_DIR / "daily-inspection-skill" / "index.html"
THURSDAY_REPORT_HTML_PATH = ROOT_DIR / "thursday-to-friday-adjustment" / "index.html"
WEEKLY_METRICS_PATH = ROOT_DIR / "friday-inspection-skill" / "scripts" / "out" / "ine_metrics.json"
PYTHON_BIN = Path("/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python")
DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5-pro"
DEFAULT_API_KEY = ""
CHAT_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "chat-history.json"
AI_CONFIG_PATH = Path(__file__).resolve().parent / "data" / "ai-config.json"
JOB_LOCK = threading.Lock()
CHAT_LOCK = threading.Lock()
AI_CONFIG_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}

MODEL_ALIASES = {
    "mimo-v2.5-pro": "mimo-v2.5-pro",
    "mimo-v2.5": "mimo-v2.5",
    "mimo-v2-pro": "mimo-v2-pro",
    "mimo-v2-omni": "mimo-v2-omni",
    "mimo-v2.5-pro".lower(): "mimo-v2.5-pro",
    "mimo-v2.5".lower(): "mimo-v2.5",
    "mimo-v2-pro".lower(): "mimo-v2-pro",
    "mimo-v2-omni".lower(): "mimo-v2-omni",
    "MiMo-V2.5-Pro".lower(): "mimo-v2.5-pro",
    "MiMo-V2.5".lower(): "mimo-v2.5",
    "MiMo-V2-Pro".lower(): "mimo-v2-pro",
    "MiMo-V2-Omni".lower(): "mimo-v2-omni",
}


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


REPORT_STYLE = """
    :root {
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dde6;
      --paper: #f4f7fb;
      --panel: #ffffff;
      --navy: #10243f;
      --green: #0f8b6f;
      --blue: #1d6fb8;
      --amber: #b7791f;
      --red: #b42318;
      --shadow: 0 18px 48px rgba(16, 36, 63, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", sans-serif;
      min-height: 100vh;
      background-color: #10243f;
      background-image:
        linear-gradient(135deg, rgba(9, 21, 35, 0.92), rgba(12, 72, 67, 0.82)),
        linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(9, 21, 35, 0.22)),
        url("/static/assets/page-background.png");
      background-size: cover, cover, cover;
      background-position: center, center, center;
      background-repeat: no-repeat;
      background-attachment: fixed;
    }
    .shell { max-width: 1440px; margin: 0 auto; padding: 32px 28px 56px; }
    .hero {
      color: #fff;
      padding: 28px 0 22px;
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 24px;
      align-items: end;
    }
    h1 {
      margin: 0 0 12px;
      font-size: clamp(32px, 5vw, 64px);
      line-height: 1;
      letter-spacing: 0;
      font-weight: 800;
    }
    .subtitle { max-width: 880px; font-size: 16px; line-height: 1.8; color: rgba(255,255,255,0.82); }
    .run-card {
      background: rgba(255,255,255,0.14);
      border: 1px solid rgba(255,255,255,0.22);
      backdrop-filter: blur(12px);
      border-radius: 8px;
      padding: 18px;
      color: rgba(255,255,255,0.92);
    }
    .run-card strong { display: block; font-size: 22px; margin-bottom: 4px; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 18px 0 26px; }
    .metrics.metrics-5 { grid-template-columns: repeat(5, minmax(0, 1fr)); }
    .metric {
      background: var(--panel);
      border-radius: 8px;
      padding: 18px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(215,221,230,0.85);
      min-height: 112px;
    }
    .metric-label { color: var(--muted); font-size: 13px; }
    .metric-value { font-size: 34px; font-weight: 800; margin: 8px 0 6px; color: var(--navy); overflow-wrap: anywhere; }
    .metric-note { color: var(--muted); font-size: 12px; line-height: 1.5; }
    section {
      background: var(--panel);
      border: 1px solid rgba(215,221,230,0.95);
      box-shadow: var(--shadow);
      border-radius: 8px;
      margin-top: 18px;
      overflow: hidden;
    }
    .section-head {
      padding: 20px 22px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      background: linear-gradient(90deg, #fff, #f7fafc);
    }
    h2 { margin: 0; font-size: 20px; letter-spacing: 0; }
    .section-note { color: var(--muted); font-size: 13px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 860px; }
    th {
      text-align: left;
      padding: 13px 14px;
      color: #445065;
      background: #f3f6fa;
      font-size: 12px;
      font-weight: 700;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }
    td { padding: 15px 14px; border-bottom: 1px solid #e8edf3; vertical-align: top; font-size: 13px; line-height: 1.45; }
    tr:hover td { background: #f8fbfd; }
    .index { color: var(--muted); width: 54px; }
    .demand { font-weight: 700; color: var(--ink); max-width: 420px; }
    .meta { color: var(--muted); font-size: 12px; margin-top: 5px; }
    .muted { color: var(--muted); }
    a { color: var(--blue); text-decoration: none; font-weight: 700; }
    a:hover { text-decoration: underline; }
    .badge, .status {
      display: inline-flex;
      align-items: center;
      height: 24px;
      border-radius: 999px;
      padding: 0 10px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .badge.blue { background: rgba(29,111,184,0.12); color: var(--blue); }
    .badge.green { background: rgba(15,139,111,0.12); color: var(--green); }
    .badge.amber { background: rgba(183,121,31,0.12); color: var(--amber); }
    .status.ok { background: rgba(15,139,111,0.12); color: var(--green); }
    .status.calm { background: rgba(183,121,31,0.12); color: var(--amber); }
    .status.bad { background: rgba(180,35,24,0.10); color: var(--red); }
    .empty { color: var(--muted); text-align: center; padding: 28px; }
    .report-nav {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 4px;
      margin: 0 0 26px;
      padding: 6px;
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 8px;
      background: rgba(12,22,34,0.20);
      box-shadow: 0 16px 38px rgba(0,0,0,0.10);
      backdrop-filter: blur(16px);
    }
    .report-nav a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      color: rgba(255,255,255,0.80);
      border: 1px solid transparent;
      background: transparent;
      border-radius: 6px;
      padding: 0 13px;
      font-size: 14px;
      font-weight: 760;
      white-space: nowrap;
      text-decoration: none;
      transition: background .18s ease, color .18s ease, border-color .18s ease;
    }
    .report-nav a:hover {
      color: #fff;
      background: rgba(255,255,255,0.08);
      border-color: rgba(255,255,255,0.14);
      text-decoration: none;
    }
    .report-nav a[aria-current="page"] {
      color: #10243f;
      background: rgba(255,255,255,0.76);
      border-color: rgba(255,255,255,0.46);
      box-shadow: 0 8px 20px rgba(0,0,0,0.10);
    }
    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
    .split section { margin-top: 0; }
    footer { color: rgba(255,255,255,0.76); font-size: 12px; margin-top: 22px; text-align: right; }
    @media (max-width: 980px) {
      .hero, .split { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .shell { padding: 22px 14px 42px; }
    }
    @media (max-width: 560px) {
      .metrics { grid-template-columns: 1fr; }
      h1 { font-size: 34px; }
    }
"""


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


def api_key_mask(api_key: str) -> str:
    if not api_key:
        return ""
    return "•" * 12 + api_key[-4:]


def default_ai_config() -> dict:
    return {
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "api_key": DEFAULT_API_KEY,
        "updated_at": "",
    }


def normalize_model_name(model: str) -> str:
    text = str(model or "").strip()
    if not text:
        return DEFAULT_MODEL
    return MODEL_ALIASES.get(text.lower(), text)


def load_ai_config() -> dict:
    config = default_ai_config()
    saved = read_json(AI_CONFIG_PATH, {})
    if isinstance(saved, dict):
        config.update({key: value for key, value in saved.items() if value is not None})
    config["base_url"] = str(config.get("base_url") or DEFAULT_BASE_URL).strip()
    config["model"] = normalize_model_name(config.get("model") or DEFAULT_MODEL)
    config["api_key"] = str(config.get("api_key") or "").strip()
    return config


def save_ai_config(config: dict) -> dict:
    current = load_ai_config()
    base_url = str(config.get("base_url") or current.get("base_url") or DEFAULT_BASE_URL).strip()
    model = normalize_model_name(config.get("model") or current.get("model") or DEFAULT_MODEL)
    api_key = str(config.get("api_key") or "").strip() or current.get("api_key", "")
    saved = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "updated_at": now_text(),
    }
    write_json_file(AI_CONFIG_PATH, saved)
    return saved


def public_ai_config(config: dict) -> dict:
    api_key = str(config.get("api_key") or "")
    return {
        "base_url": config.get("base_url") or DEFAULT_BASE_URL,
        "model": config.get("model") or DEFAULT_MODEL,
        "has_api_key": bool(api_key),
        "api_key_mask": api_key_mask(api_key),
        "updated_at": config.get("updated_at") or "",
    }


def html_text(value) -> str:
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def report_nav() -> str:
    return """
      <nav class="report-nav">
        <a href="/">控制台</a>
        <a href="/reports/daily">日常巡检报告</a>
        <a href="/reports/weekly">周度巡检报告</a>
        <a href="/reports/repair">修复巡检报告</a>
        <a href="/reports/thursday">计划日期调整报告</a>
      </nav>
      <script>
        (() => {
          const path = window.location.pathname;
          document.querySelectorAll(".report-nav a").forEach((link) => {
            const href = link.getAttribute("href");
            if ((path === "/" && href === "/") || (href !== "/" && path === href)) {
              link.setAttribute("aria-current", "page");
            }
          });
        })();
      </script>
    """


def report_metric(label: str, value, note: str = "") -> str:
    return f"""
      <div class="metric">
        <div class="metric-label">{html_text(label)}</div>
        <div class="metric-value">{html_text(value)}</div>
        <div class="metric-note">{html_text(note)}</div>
      </div>
    """


def report_shell(title: str, subtitle: str, metrics: list[str], sections: list[str], generated_at: str = "") -> str:
    generated = generated_at or now_text()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_text(title)}</title>
  <style>{REPORT_STYLE}</style>
</head>
<body>
  <main class="shell">
    {report_nav()}
    <header class="hero">
      <div>
        <h1>{html_text(title)}</h1>
        <div class="subtitle">{html_text(subtitle)}</div>
      </div>
      <div class="run-card">
        <strong>{html_text(generated)}</strong>
        <div>报告生成时间</div>
      </div>
    </header>
    <div class="metrics metrics-{len(metrics)}">{''.join(metrics)}</div>
    {''.join(sections)}
    <footer>收银台&内单交易域巡检控制台</footer>
  </main>
</body>
</html>"""


def table_section(title: str, note: str, headers: list[str], rows: list[list[str]], empty_text: str = "暂无记录") -> str:
    head = "".join(f"<th>{html_text(header)}</th>" for header in headers)
    note_html = f'<div class="section-note">{html_text(note)}</div>' if note else ""
    if rows:
        body = "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
        )
    else:
        body = f'<tr><td colspan="{len(headers)}" class="empty">{html_text(empty_text)}</td></tr>'
    return f"""
      <section>
        <div class="section-head">
          <h2>{html_text(title)}</h2>
          {note_html}
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>{head}</tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def status_badge_html(status: str) -> str:
    value = str(status or "-")
    class_name = "ok" if value in ("success", "通过", "未触发") else "calm" if value in ("partial", "missing") else "bad"
    return f'<span class="status {class_name}">{html_text(value)}</span>'


def render_daily_report_html() -> str:
    summary = compact_summary(read_json(SUMMARY_PATH, {}))
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
    summary = compact_summary(read_json(SUMMARY_PATH, {}))
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
                    html_text(detail.get("跳转地址") or detail.get("detail_url") or detail.get("url")),
                ]
            )
        sections.append(table_section(str(item.get("title") or "修复明细"), f"状态：{item.get('status') or '-'}", ["#", "需求", "负责人", "修正后日期", "链接"], success_rows, "暂无成功明细"))
    return report_shell("修复巡检报告", "延期提测与延期上线修复结果", metrics, sections, summary.get("generated_at") or "")


def render_thursday_report_html() -> str:
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
        available_metrics = [name for name, value in weekly.items() if isinstance(value, dict)]

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
            "默认按支付生态研发部展示主视角，并保留各团队周度对比明细。",
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

def python_bin() -> str:
    return str(PYTHON_BIN if PYTHON_BIN.exists() else Path(os.sys.executable))


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def chat_message(role: str, content: str) -> dict:
    return {"role": role, "content": content, "created_at": now_text()}


def default_chat_messages() -> list[dict]:
    return []


def chat_title_from_message(message: str) -> str:
    title = re.sub(r"\s+", " ", (message or "").strip())
    if not title:
        return "新对话"
    return title[:18] + ("..." if len(title) > 18 else "")


def load_chat_store() -> dict:
    store = read_json(CHAT_HISTORY_PATH, {"sessions": [], "active_session_id": ""})
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
    daily_dir = ROOT_DIR / "daily-inspection-skill"
    py = python_bin()
    aggregate = [py, "joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py"]
    if skip_repair:
        aggregate.append("--skip-repair")
    return [
        step([py, "scripts/run_skill.py"], daily_dir / "OKR-inspection" / "delay-test-rate-skill", "延期提测率巡检"),
        step([py, "scripts/run_skill.py"], daily_dir / "OKR-inspection" / "delay-online-rate-skill", "延期上线率巡检"),
        step([py, "scripts/run_skill.py"], daily_dir / "OKR-inspection" / "technical-refactor-working-hours-skill", "技术改造工时占比巡检"),
        step([py, "scripts/run_skill.py"], daily_dir / "OKR-inspection" / "bi-weekly-delivery-rate-skill", "双周交付率巡检"),
        step([py, "scripts/run_skill.py"], daily_dir / "AI-inspection", "AI 深度用户巡检"),
        step([py, "scripts/run_skill.py"], daily_dir / "ContinuousDelivery-inspection", "持续交付巡检"),
        step(aggregate, daily_dir, "生成日常巡检报告"),
    ]


def friday_inspection_steps() -> list[dict]:
    py = python_bin()
    friday_dir = ROOT_DIR / "friday-inspection-skill"
    return [step([py, "scripts/run_skill.py", "--headless"], friday_dir, "周度 INE 指标抓取")]


def action_registry() -> dict[str, dict]:
    py = python_bin()
    d = daily_dir()
    f = friday_dir()
    t = thursday_dir()
    return {
        "daily_inspection": {
            "title": "日常巡检",
            "group": "主流程",
            "description": "依次执行 OKR、AI、持续交付巡检，并刷新总报告。默认不触发自动修复。",
            "risk": "safe",
            "aliases": ["日常巡检", "每日巡检", "帮我日常巡检", "帮我巡检", "daily"],
            "steps": daily_inspection_steps(skip_repair=True),
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


def out_of_scope_answer() -> str:
    return "我只负责巡检相关的对话，可以帮你看指标、风险、报告、任务状态，或执行日常巡检、周度巡检和修复脚本。"


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


def call_chat_model(message: str, action: str, summary: dict, client_config: dict, history_messages: list[dict] | None = None) -> str:
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
    context = {
        "inspection_date": summary.get("inspection_date"),
        "status": summary.get("status"),
        "department_c3": summary.get("department_c3"),
        "display_domain": summary.get("display_domain"),
        "overview": build_overview(summary)[:10],
    }
    recent_history = [
        {
            "role": item.get("role") if item.get("role") in ("user", "assistant") else "user",
            "content": str(item.get("content") or ""),
        }
        for item in (history_messages or [])[-8:]
        if item.get("content")
    ]
    model_messages = [
        {
            "role": "system",
            "content": (
                "你是一个中文巡检助手，只能处理和收银台&内单交易域巡检有关的问题。"
                "你的范围包括：巡检指标解释、风险/异常分析、报告摘要、任务状态、脚本执行反馈、延期提测/延期上线修复、AI非深度用户、持续交付和技术改造等。"
                "如果用户问闲聊、通用知识、代码教学、生活建议、新闻、翻译、写作等非巡检内容，必须拒绝，并用一句话引导用户回到巡检问题。"
                "不要编造未提供的数据。"
            ),
        },
        *recent_history,
        {
            "role": "user",
            "content": (
                f"用户消息：{message}\n"
                f"系统判定：{action_text}\n"
                f"当前巡检摘要 JSON：{json.dumps(context, ensure_ascii=False)}\n"
                "请先判断是否属于巡检范围；属于则用 1-3 句话回复，不属于则按系统规则拒绝。"
            ),
        },
    ]
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": model_messages,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode("utf-8"))
    choices = body.get("choices") or []
    if not choices:
        return ""
    message_payload = choices[0].get("message") or {}
    return str(message_payload.get("content") or "").strip()


def call_chat_model_stream(message: str, action: str, summary: dict, client_config: dict, history_messages: list[dict] | None = None):
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
    context = {
        "inspection_date": summary.get("inspection_date"),
        "status": summary.get("status"),
        "department_c3": summary.get("department_c3"),
        "display_domain": summary.get("display_domain"),
        "overview": build_overview(summary)[:10],
    }
    recent_history = [
        {
            "role": item.get("role") if item.get("role") in ("user", "assistant") else "user",
            "content": str(item.get("content") or ""),
        }
        for item in (history_messages or [])[-8:]
        if item.get("content")
    ]
    payload = {
        "model": model,
        "temperature": 0.2,
        "stream": True,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个中文巡检助手，只能处理和收银台&内单交易域巡检有关的问题。"
                    "你的范围包括：巡检指标解释、风险/异常分析、报告摘要、任务状态、脚本执行反馈、延期提测/延期上线修复、AI非深度用户、持续交付和技术改造等。"
                    "如果用户问闲聊、通用知识、代码教学、生活建议、新闻、翻译、写作等非巡检内容，必须拒绝，并用一句话引导用户回到巡检问题。"
                    "不要编造未提供的数据。"
                ),
            },
            *recent_history,
            {
                "role": "user",
                "content": (
                    f"用户消息：{message}\n"
                    f"系统判定：{action_text}\n"
                    f"当前巡检摘要 JSON：{json.dumps(context, ensure_ascii=False)}\n"
                    "请先判断是否属于巡检范围；属于则用 1-3 句话回复，不属于则按系统规则拒绝。"
                ),
            },
        ],
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


def format_value(value, unit: str = "") -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        shown = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        shown = str(value)
    return f"{shown}%" if unit == "%" else shown


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
    return ROOT_DIR / "daily-inspection-skill" / str(json_file)


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
        value = parse_numberish(repair_summary.get(config["count_label"])) or 0
        status = repair_summary.get("巡检状态") or "-"
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


def display_unit(unit: str) -> str:
    return {
        "count": "个",
        "hour": "人天",
    }.get(unit, unit)


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
    payload["loaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["report_html_exists"] = REPORT_HTML_PATH.exists()
    return payload


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

    if not is_inspection_related(text, action):
        return out_of_scope_answer()

    if action != "none":
        title = action_title(action)
        prefix = f"已开始执行：{title}。任务面板会持续刷新步骤、状态和最近日志。"
        return f"{prefix}\n{model_answer}" if model_answer else prefix

    if model_answer:
        return model_answer

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
            summary = compact_summary(read_json(SUMMARY_PATH, {}))
            return self.write_json(summary)
        if path == "/api/actions":
            return self.write_json({"actions": public_actions()})
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
            if not session:
                return self.send_error(404)
            return self.write_json({"session": session})
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
        if parsed.path not in ("/api/chat", "/api/chat/stream", "/api/actions/run", "/api/jobs/clear", "/api/chat/sessions", "/api/chat/sessions/clear-all", "/api/ai-config", "/api/ai-config/test") and not (
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

        if parsed.path == "/api/ai-config":
            with AI_CONFIG_LOCK:
                config = save_ai_config(payload)
                return self.write_json(public_ai_config(config))

        if parsed.path == "/api/ai-config/test":
            config = merged_ai_config(payload)
            if not config.get("api_key"):
                return self.write_json({"ok": False, "message": "后端还没有配置 API Key。", "config": public_ai_config(config)})
            try:
                answer = call_chat_model("请只回复：连接正常", "none", read_json(SUMMARY_PATH, {}), config, [])
            except Exception as exc:
                return self.write_json({"ok": False, "message": f"模型连接失败：{exc}", "config": public_ai_config(config)})
            return self.write_json({"ok": bool(answer), "message": answer or "模型没有返回内容。", "config": public_ai_config(config)})

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

        if parsed.path == "/api/actions/run":
            action = str(payload.get("action") or "")
            message = str(payload.get("message") or "")
            if action not in action_registry():
                return self.write_json({"error": "unknown_action", "message": "未知动作"})
            required = action_requires_confirmation(action, message)
            if required:
                return self.write_json(
                    {
                        "error": "confirmation_required",
                        "action": action,
                        "required_phrase": required,
                        "answer": f"这个动作会修改线上数据。请在输入框里包含“{required}”后再执行。",
                    }
                )
            job = start_job(action)
            return self.write_json({"action": action, "job": job, "answer": f"已开始执行：{action_title(action)}。"})

        if parsed.path == "/api/chat/stream":
            return self.handle_chat_stream(payload)

        message = str(payload.get("message") or "")
        session_id = str(payload.get("session_id") or "")
        active_session_id, previous_messages = begin_chat_turn(message, session_id)

        summary = read_json(SUMMARY_PATH, {})
        action = detect_action(message)
        if not is_inspection_related(message, action):
            answer = out_of_scope_answer()
            sessions = finish_chat_turn(active_session_id, answer)
            return self.write_json(
                {
                    "answer": answer,
                    "action": action,
                    "job": None,
                    "mode": "inspection-scope-guard",
                    "session_id": active_session_id,
                    "sessions": sessions,
                }
            )
        required = action_requires_confirmation(action, message) if action != "none" else ""
        if required:
            answer = f"我识别到你想执行“{action_title(action)}”，但这个动作会修改线上数据。请明确输入“{required}”后再执行。"
            sessions = finish_chat_turn(active_session_id, answer)
            return self.write_json(
                {
                    "answer": answer,
                    "action": action,
                    "job": None,
                    "confirmation_required": required,
                    "mode": "confirmation-required",
                    "session_id": active_session_id,
                    "sessions": sessions,
                }
            )
        job = start_job(action) if action != "none" else None
        model_answer = ""
        try:
            model_answer = call_chat_model(message, action, summary, payload.get("ai") or {}, previous_messages)
        except Exception as exc:
            model_answer = f"模型调用暂时失败，已使用本地规则继续处理。错误：{exc}"
        answer = answer_chat(message, summary, action=action, model_answer=model_answer)
        sessions = finish_chat_turn(active_session_id, answer)
        return self.write_json(
            {
                "answer": answer,
                "action": action,
                "job": job,
                "mode": "mimo-chat-with-local-actions" if model_answer else "local-action-fallback",
                "session_id": active_session_id,
                "sessions": sessions,
            }
        )

    def handle_chat_stream(self, payload: dict):
        message = str(payload.get("message") or "")
        session_id = str(payload.get("session_id") or "")
        active_session_id, previous_messages = begin_chat_turn(message, session_id)
        summary = read_json(SUMMARY_PATH, {})
        action = detect_action(message)
        job = None
        answer_parts: list[str] = []
        mode = "mimo-chat-stream"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit_text(text: str):
            if not text:
                return
            answer_parts.append(text)
            self.write_sse("delta", {"text": text})

        self.write_sse("meta", {"session_id": active_session_id, "action": action})

        if not is_inspection_related(message, action):
            mode = "inspection-scope-guard"
            emit_text(out_of_scope_answer())
        else:
            required = action_requires_confirmation(action, message) if action != "none" else ""
            if required:
                mode = "confirmation-required"
                emit_text(f"我识别到你想执行“{action_title(action)}”，但这个动作会修改线上数据。请明确输入“{required}”后再执行。")
            else:
                job = start_job(action) if action != "none" else None
                if action != "none":
                    emit_text(f"已开始执行：{action_title(action)}。任务面板会持续刷新步骤、状态和最近日志。\n")
                streamed = False
                try:
                    for chunk in call_chat_model_stream(message, action, summary, payload.get("ai") or {}, previous_messages):
                        streamed = True
                        emit_text(chunk)
                except Exception as exc:
                    fallback = f"模型调用暂时失败，已使用本地规则继续处理。错误：{exc}"
                    emit_text(fallback if action != "none" else answer_chat(message, summary, action=action, model_answer=fallback))
                    mode = "model-error-fallback"
                if not streamed and not answer_parts:
                    fallback = answer_chat(message, summary, action=action, model_answer="")
                    emit_text(fallback)
                    mode = "local-action-fallback"

        answer = "".join(answer_parts)
        sessions = finish_chat_turn(active_session_id, answer)
        self.write_sse(
            "done",
            {
                "answer": answer,
                "action": action,
                "job": job,
                "mode": mode,
                "session_id": active_session_id,
                "sessions": sessions,
            },
        )
        return None

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
        if base and not str(resolved).startswith(str(base)):
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
