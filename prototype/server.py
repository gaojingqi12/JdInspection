from __future__ import annotations

import json
import mimetypes
import re
import shutil
import threading
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from agent_memory import load_memory, save_memory, summarize_for_prompt, update_memory_from_turn
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
from data_query import query_inspection_data
from daily_templates import DailyInspectionRenderer
from failure_recovery import render_failure_recovery
from inspection_agent import InspectionAgent, InspectionAgentDeps
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
DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5-pro"
DEFAULT_API_KEY = ""
CHAT_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "chat-history.json"
AI_CONFIG_PATH = Path(__file__).resolve().parent / "data" / "ai-config.json"
AGENT_MEMORY_PATH = Path(__file__).resolve().parent / "data" / "agent-memory.json"
CHAT_LOCK = threading.Lock()
AI_CONFIG_LOCK = threading.Lock()

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

REPAIR_HISTORY_DIRS = {
    "delayed_test": ROOT_DIR / "daily-inspection-skill" / "reschedule-delayed-test " / "history",
    "delayed_online": ROOT_DIR / "daily-inspection-skill" / "repair-delayed-launch" / "history",
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
        url("/static/assets/jd-inspection-page-background.png");
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
    .metrics.metrics-5 { grid-template-columns: repeat(6, minmax(0, 1fr)); }
    .metrics.metrics-5 .metric { grid-column: span 2; }
    .metrics.metrics-5 .metric:nth-child(n + 4) { grid-column: span 3; }
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

STATIC_ROOT_INDEX_PATH = ROOT_DIR / "index.html"
STATIC_ROOT_DAILY_REPORT_PATH = ROOT_DIR / "daily-report.html"
STATIC_ROOT_WEEKLY_REPORT_PATH = ROOT_DIR / "weekly-report.html"
STATIC_ROOT_REPAIR_REPORT_PATH = ROOT_DIR / "repair-report.html"
STATIC_ROOT_THURSDAY_REPORT_PATH = ROOT_DIR / "thursday-report.html"
STATIC_ROOT_ASSET_PATH = "./prototype/static/assets/jd-inspection-page-background.png"
STATIC_FRONTEND_STYLESHEET_PATH = "./prototype/static/styles.css"
STATIC_ROOT_REPORT_STYLE = REPORT_STYLE.replace('/static/assets/jd-inspection-page-background.png', STATIC_ROOT_ASSET_PATH)
STATIC_TREND_ILLUSTRATION_PATH = "./prototype/static/assets/jd-static-trend-banner.png"
STATIC_HERO_BRAND_PATH = "./prototype/static/assets/jd-static-showcase-hero-brand.png"

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
STATIC_HOME_OVERRIDE_STYLE = f"""
    body {{
      background-image:
        linear-gradient(135deg, rgba(9, 21, 35, 0.92), rgba(12, 72, 67, 0.82)),
        linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(9, 21, 35, 0.22)),
        url("{STATIC_ROOT_ASSET_PATH}") !important;
    }}
    .public-command-bar {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) clamp(260px, 19vw, 410px);
      align-items: stretch;
      width: 100%;
      margin-bottom: 18px;
    }}
    .public-command-bar::before,
    .public-ai-section::before {{
      display: none;
    }}
    .public-command-bar .report-group {{
      width: auto;
      min-height: 0;
    }}
    .public-command-bar .report-links {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .public-command-bar .button-link {{
      display: flex;
      width: 100%;
      min-height: 74px;
      justify-content: flex-start;
      align-items: flex-start;
      padding: 16px 18px;
      border-radius: 14px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.08));
      border-color: rgba(255,255,255,0.18);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.06),
        0 12px 28px rgba(9, 21, 35, 0.12);
      text-decoration: none;
    }}
    .public-command-bar .button-link:hover {{
      transform: translateY(-4px);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.08),
        0 24px 42px rgba(16, 36, 63, 0.24);
      text-decoration: none;
    }}
    .public-report-link-inner {{
      display: grid;
      gap: 6px;
      width: 100%;
    }}
    .public-report-link-kicker {{
      width: fit-content;
      border-radius: 999px;
      padding: 4px 10px;
      background: rgba(255,255,255,0.14);
      border: 1px solid rgba(255,255,255,0.12);
      color: rgba(255,255,255,0.78);
      font-size: 12px;
      font-weight: 760;
      letter-spacing: 0;
    }}
    .public-report-link-title {{
      color: #fff;
      font-size: 20px;
      line-height: 1.18;
      font-weight: 800;
    }}
    .public-report-link-desc {{
      color: rgba(255,255,255,0.72);
      font-size: 12px;
      line-height: 1.5;
    }}
    .public-report-link-inner::after {{
      content: "打开报告";
      color: rgba(255,255,255,0.62);
      font-size: 12px;
      font-weight: 700;
      margin-top: 4px;
    }}
    .static-lower-grid {{
      grid-template-columns: 1fr;
      margin-top: 18px;
    }}
    .public-ai-section .panel-head {{
      padding-bottom: 8px;
    }}
    .public-ai-section #publicAiMeta {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }}
    .public-ai-grid {{
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      gap: 10px;
      padding: 0 16px 16px;
    }}
    .public-ai-grid .ai-user-pill {{
      width: auto;
      max-width: min(280px, 100%);
      justify-content: flex-start;
      flex: 0 0 auto;
    }}
    .public-ai-grid .ai-user-name {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .public-chart-note {{
      color: #6a7783;
      font-size: 15px;
      line-height: 1.7;
      margin-top: 6px;
    }}
    .public-static-hero-art {{
      position: relative;
      right: auto;
      top: auto;
      z-index: 1;
      width: 100%;
      height: clamp(190px, 14vw, 276px);
      min-height: 0;
      align-self: stretch;
      aspect-ratio: auto;
      margin: 0;
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 18px;
      overflow: hidden;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06));
      box-shadow:
        0 24px 56px rgba(9, 21, 35, 0.24),
        inset 0 1px 0 rgba(255,255,255,0.12);
      opacity: 0.82;
      pointer-events: none;
    }}
    .public-static-hero-art::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(9, 21, 35, 0.02), rgba(9, 21, 35, 0.12));
    }}
    .public-static-hero-art img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      object-position: center;
      filter: saturate(1.04) contrast(0.98);
    }}
    .public-command-bar,
    .metric-grid,
    .workspace,
    .static-lower-grid {{
      position: relative;
      z-index: 1;
    }}
    .chart-panel .panel-head {{
      padding-bottom: 6px;
    }}
    .public-trend-layout {{
      display: grid;
      grid-template-columns: minmax(300px, 0.76fr) minmax(0, 1.24fr);
      gap: 22px;
      padding: 0 18px 20px;
      align-items: stretch;
    }}
    .public-trend-deck {{
      min-width: 0;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-template-rows: repeat(3, minmax(126px, auto));
      gap: 10px;
      align-content: start;
      height: auto;
    }}
    .public-trend-visual {{
      grid-column: 1 / -1;
      margin: 2px 0 0;
      aspect-ratio: 1817 / 866;
      border: 1px solid rgba(201, 214, 225, 0.92);
      border-radius: 18px;
      overflow: hidden;
      background:
        radial-gradient(circle at 50% 12%, rgba(36, 111, 168, 0.04), transparent 46%),
        linear-gradient(180deg, #ffffff, #f8fbfd);
      box-shadow:
        0 18px 34px rgba(23, 33, 43, 0.08),
        inset 0 1px 0 rgba(255,255,255,0.9);
    }}
    .public-trend-visual img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center;
      opacity: 0.96;
    }}
    .public-trend-stack-card {{
      position: relative;
      display: grid;
      grid-template-rows: auto auto auto;
      gap: 9px;
      width: 100%;
      min-height: 126px;
      height: auto;
      padding: 12px 14px 12px;
      border: 1px solid rgba(201, 214, 225, 0.92);
      border-radius: 18px;
      background:
        radial-gradient(circle at 100% 0%, rgba(36, 111, 168, 0.04), transparent 34%),
        linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,251,253,0.96));
      color: var(--ink);
      text-align: left;
      box-shadow:
        0 16px 34px rgba(23, 33, 43, 0.08),
        inset 0 1px 0 rgba(255,255,255,0.88);
      transition:
        transform 220ms cubic-bezier(0.2, 0.85, 0.28, 1.12),
        box-shadow 220ms ease,
        border-color 220ms ease,
        background 220ms ease;
    }}
    .public-trend-stack-card:hover {{
      transform: translateY(-3px);
      border-color: rgba(36, 111, 168, 0.22);
      box-shadow: 0 26px 44px rgba(23, 33, 43, 0.12);
    }}
    .public-trend-stack-card.active {{
      border-color: rgba(36, 111, 168, 0.28);
      background:
        radial-gradient(circle at 100% 0%, rgba(36, 111, 168, 0.08), transparent 38%),
        linear-gradient(180deg, #ffffff, #f9fbfd);
      box-shadow:
        0 30px 52px rgba(23, 33, 43, 0.14),
        inset 0 1px 0 rgba(255,255,255,0.92);
      transform: translateY(-2px);
    }}
    .public-trend-stack-card.active::after {{
      content: "";
      position: absolute;
      left: 14px;
      right: 14px;
      bottom: 0;
      height: 3px;
      border-radius: 999px 999px 0 0;
      background: linear-gradient(90deg, var(--green), var(--blue));
    }}
    .public-trend-stack-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .public-trend-stack-kicker {{
      width: fit-content;
      border-radius: 999px;
      padding: 4px 9px;
      background: rgba(237, 244, 251, 0.92);
      color: var(--blue);
      font-size: 11px;
      font-weight: 760;
    }}
    .public-trend-stack-index {{
      color: #8b98a5;
      font-size: 12px;
      font-weight: 760;
      letter-spacing: 0.08em;
    }}
    .public-trend-stack-title {{
      font-size: 15px;
      line-height: 1.32;
      font-weight: 800;
      color: #1c2835;
    }}
    .public-trend-stack-foot {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-width: 0;
      padding-top: 2px;
    }}
    .public-trend-stack-value {{
      font-size: 25px;
      line-height: 1;
      font-weight: 800;
      color: #152332;
    }}
    .public-trend-stack-meta {{
      color: #6b7987;
      font-size: 11px;
      line-height: 1.4;
      font-weight: 650;
      white-space: nowrap;
    }}
    .public-trend-stage {{
      min-width: 0;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      gap: 14px;
      padding: 18px 18px 16px;
      border: 1px solid rgba(198, 212, 225, 0.92);
      border-radius: 18px;
      background:
        radial-gradient(circle at 100% 0%, rgba(36, 111, 168, 0.06), transparent 34%),
        linear-gradient(180deg, #ffffff, #fbfcfe);
      box-shadow:
        0 24px 54px rgba(23, 33, 43, 0.08),
        inset 0 1px 0 rgba(255,255,255,0.94);
    }}
    .public-trend-stage-kicker {{
      color: #728090;
      font-size: 12px;
      font-weight: 760;
      margin-bottom: 8px;
    }}
    .public-trend-stage-title {{
      color: #17222f;
      font-size: 24px;
      line-height: 1.08;
      font-weight: 820;
    }}
    .public-trend-stage-meta {{
      color: #6b7987;
      font-size: 14px;
      line-height: 1.6;
      margin-top: 6px;
    }}
    .public-trend-stage-stats {{
      display: grid;
      grid-template-columns: minmax(120px, 0.56fr) minmax(280px, 1.58fr) minmax(120px, 0.56fr);
      gap: 10px;
    }}
    .public-trend-stage-stat {{
      min-width: 0;
      padding: 11px 12px;
      border: 1px solid rgba(217, 225, 231, 0.95);
      border-radius: 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(248,251,253,0.86));
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.9),
        0 10px 22px rgba(23, 33, 43, 0.04);
    }}
    .public-trend-stage-stat span {{
      display: block;
      color: #708090;
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .public-trend-stage-stat strong {{
      display: block;
      color: #162433;
      font-size: 18px;
      line-height: 1.1;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .public-trend-stage-canvas {{
      min-width: 0;
      min-height: 0;
      height: 100%;
      border: 1px solid rgba(227, 234, 240, 0.96);
      border-radius: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(250,252,253,0.94));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.92);
      padding: 10px 10px 2px;
    }}
    .public-trend-stage-canvas canvas {{
      height: 100%;
      min-height: 420px;
    }}
    @media (max-width: 900px) {{
      .public-static-hero-art {{
        display: none;
      }}
      .public-command-bar .report-links {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .public-command-bar {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .public-trend-layout {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 760px) {{
      .public-command-bar .report-links {{
        grid-template-columns: 1fr;
      }}
      .public-trend-layout {{
        grid-template-columns: 1fr;
        gap: 14px;
      }}
      .public-trend-deck {{
        grid-template-columns: 1fr;
        grid-template-rows: none;
        height: auto;
      }}
      .public-trend-visual {{
        grid-column: auto;
      }}
      .public-trend-visual img {{
        height: 100%;
      }}
      .public-trend-stack-card,
      .public-trend-stack-card.active {{
        width: 100%;
        transform: none;
      }}
      .public-trend-stack-title {{
        font-size: 16px;
      }}
      .public-trend-stack-value {{
        font-size: 24px;
      }}
      .public-trend-stage {{
        padding: 18px 16px 14px;
      }}
      .public-trend-stage-title {{
        font-size: 23px;
      }}
      .public-trend-stage-stats {{
        grid-template-columns: 1fr;
      }}
      .public-trend-stage-canvas canvas {{
        min-height: 360px;
      }}
      .public-ai-grid .ai-user-pill {{
        max-width: 100%;
      }}
    }}
"""
STATIC_ROOT_PAGE_STYLE = """
    .public-shell {
      max-width: 1480px;
      margin: 0 auto;
      padding: 32px 28px 56px;
    }
    .public-hero {
      color: #fff;
      padding: 28px 0 18px;
      display: grid;
      grid-template-columns: 1.3fr 0.7fr;
      gap: 20px;
      align-items: end;
    }
    .public-eyebrow {
      color: rgba(255,255,255,0.72);
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .public-hero h1 {
      margin: 0 0 10px;
      font-size: clamp(34px, 5vw, 62px);
      line-height: 1;
      letter-spacing: 0;
      font-weight: 800;
    }
    .public-hero-copy {
      color: rgba(255,255,255,0.84);
      font-size: 16px;
      line-height: 1.8;
      max-width: 840px;
    }
    .public-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
      align-items: center;
    }
    .public-meta span {
      border: 1px solid rgba(255,255,255,0.22);
      border-radius: 8px;
      background: rgba(255,255,255,0.14);
      backdrop-filter: blur(12px);
      padding: 8px 10px;
      color: rgba(255,255,255,0.9);
      font-size: 13px;
      white-space: nowrap;
    }
    .public-report-hub {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }
    .public-report-link {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 146px;
      padding: 18px;
      border-radius: 8px;
      text-decoration: none;
      color: #17212b;
      background: #ffffff;
      border: 1px solid rgba(215,221,230,0.88);
      box-shadow: var(--shadow);
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    .public-report-link:hover {
      transform: translateY(-2px);
      box-shadow: 0 20px 42px rgba(16, 36, 63, 0.14);
      border-color: rgba(29,111,184,0.24);
      text-decoration: none;
    }
    .public-report-link-kicker {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: fit-content;
      min-height: 24px;
      padding: 0 10px;
      border-radius: 999px;
      background: rgba(29,111,184,0.10);
      color: var(--blue);
      font-size: 12px;
      font-weight: 800;
    }
    .public-report-link-title {
      margin-top: 12px;
      font-size: 22px;
      line-height: 1.2;
      font-weight: 800;
      color: var(--navy);
    }
    .public-report-link-desc {
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    .static-report-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 18px;
      padding: 10px;
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 8px;
      background: rgba(255,255,255,0.10);
      backdrop-filter: blur(14px);
    }
    .static-report-nav a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 0 14px;
      border-radius: 8px;
      color: rgba(255,255,255,0.9);
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      font-size: 14px;
      font-weight: 760;
      text-decoration: none;
      transition: transform .18s ease, background .18s ease, color .18s ease;
    }
    .static-report-nav a:hover {
      transform: translateY(-1px);
      background: rgba(255,255,255,0.12);
      text-decoration: none;
    }
    .static-report-nav a.active {
      color: #10243f;
      background: rgba(255,255,255,0.82);
      border-color: rgba(255,255,255,0.42);
      box-shadow: 0 8px 20px rgba(0,0,0,0.10);
    }
    .public-board {
      display: grid;
      gap: 18px;
    }
    .public-overview {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }
    .public-card {
      background: #ffffff;
      border-radius: 8px;
      padding: 18px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(215,221,230,0.85);
      min-height: 128px;
    }
    .public-card-caption {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .public-card-label {
      color: #445065;
      font-size: 13px;
      font-weight: 700;
    }
    .public-card-value {
      font-size: 34px;
      line-height: 1.05;
      font-weight: 800;
      margin: 10px 0 8px;
      color: var(--navy);
    }
    .public-card-foot {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .public-panel {
      background: #ffffff;
      border-radius: 8px;
      padding: 18px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(215,221,230,0.85);
    }
    .public-panel-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }
    .public-panel-head h2 {
      margin: 0;
    }
    .public-panel-head p {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    .public-trend-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .public-trend-card {
      border: 1px solid rgba(215,221,230,0.9);
      border-radius: 8px;
      padding: 14px;
      background: linear-gradient(180deg, #ffffff, #f8fbfd);
      min-height: 216px;
    }
    .public-trend-title {
      font-size: 15px;
      font-weight: 760;
      color: var(--ink);
    }
    .public-trend-meta {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .public-trend-card canvas {
      width: 100%;
      height: 140px;
      display: block;
      margin-top: 10px;
    }
    .public-ai-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .public-ai-pill {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      border-radius: 8px;
      border: 1px solid rgba(215,221,230,0.9);
      background: #f8fbfd;
      padding: 10px 12px;
    }
    .public-ai-avatar {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: rgba(36,111,168,0.12);
      color: var(--blue);
      font-size: 13px;
      font-weight: 800;
      flex: 0 0 auto;
    }
    .public-ai-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 700;
      color: var(--ink);
    }
    .public-reports {
      margin-top: 22px;
    }
    .public-report-block {
      padding-top: 8px;
      border-top: 1px solid rgba(255,255,255,0.08);
    }
    .public-report-block .hero {
      margin: 0 0 22px;
      padding: 28px 30px;
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(260px, 0.85fr);
      gap: 22px;
      align-items: end;
      color: var(--ink);
      border: 1px solid rgba(201, 214, 225, 0.92);
      border-radius: 16px;
      background:
        radial-gradient(circle at 100% 0%, rgba(29, 111, 184, 0.055), transparent 34%),
        linear-gradient(180deg, #ffffff, #fbfcfe);
      box-shadow:
        0 20px 44px rgba(16, 36, 63, 0.08),
        inset 0 1px 0 rgba(255,255,255,0.94);
    }
    .public-report-block .hero h1 {
      color: var(--navy);
      font-size: clamp(34px, 4.2vw, 56px);
      line-height: 1;
      margin: 0 0 12px;
    }
    .public-report-block .subtitle {
      max-width: none;
      color: #617083;
      font-size: 16px;
      line-height: 1.7;
      font-weight: 650;
    }
    .public-report-block .run-card {
      justify-self: end;
      min-width: min(100%, 360px);
      color: var(--ink);
      border: 1px solid rgba(217, 225, 231, 0.95);
      border-radius: 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(248,251,253,0.88));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.92);
      backdrop-filter: none;
    }
    .public-report-block .run-card strong {
      color: var(--navy);
      font-size: 22px;
      line-height: 1.15;
    }
    .public-report-block .run-card div {
      color: #617083;
      font-weight: 650;
    }
    .public-report-block .run-card .meta {
      color: #718093 !important;
      font-size: 12px;
      line-height: 1.6;
    }
    .public-report-block footer {
      display: none;
    }
    .public-report-block .metrics {
      gap: 18px;
      margin: 22px 0 30px;
      padding: 6px;
    }
    .public-report-block .metric {
      min-height: 140px;
      padding: 22px 24px;
      border-radius: 14px;
      border-color: rgba(201, 214, 225, 0.92);
      background:
        radial-gradient(circle at 100% 0%, rgba(29, 111, 184, 0.045), transparent 34%),
        linear-gradient(180deg, #ffffff, #fbfcfe);
      box-shadow:
        0 18px 38px rgba(16, 36, 63, 0.08),
        inset 0 1px 0 rgba(255,255,255,0.92);
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    .public-report-block .metric:hover {
      transform: translateY(-2px);
      border-color: rgba(29, 111, 184, 0.20);
      box-shadow:
        0 24px 48px rgba(16, 36, 63, 0.11),
        inset 0 1px 0 rgba(255,255,255,0.96);
    }
    .public-report-block .metric-label {
      color: #687684;
      font-size: 14px;
      font-weight: 760;
    }
    .public-report-block .metric-value {
      margin: 12px 0 10px;
      font-size: 38px;
      line-height: 1;
      letter-spacing: 0;
    }
    .public-report-block .metric-note {
      color: #6b7987;
      font-size: 13px;
      line-height: 1.55;
    }
    .public-report-block .badge.submit-test { background: rgba(29,111,184,0.12); color: var(--blue); }
    .public-report-block .badge.online { background: rgba(15,139,111,0.12); color: var(--green); }
    .public-report-block .date {
      display: inline-flex;
      border-radius: 6px;
      padding: 5px 8px;
      font-weight: 800;
      white-space: nowrap;
      border: 1px solid transparent;
    }
    .public-report-block .date.old { color: var(--red); background: rgba(180,35,24,0.08); border-color: rgba(180,35,24,0.15); }
    .public-report-block .date.new { color: var(--green); background: rgba(15,139,111,0.10); border-color: rgba(15,139,111,0.16); }
    .public-report-block .date.current { color: var(--navy); background: #eef4fa; border-color: #d7e4f1; }
    @media (max-width: 1100px) {
      .public-overview,
      .public-report-hub,
      .public-trend-grid,
      .public-ai-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .public-report-block .hero {
        grid-template-columns: 1fr;
      }
      .public-report-block .run-card {
        justify-self: stretch;
      }
    }
    @media (max-width: 860px) {
      .public-hero {
        grid-template-columns: 1fr;
      }
      .public-meta {
        justify-content: flex-start;
      }
    }
    @media (max-width: 640px) {
      .public-shell {
        padding: 22px 14px 42px;
      }
      .public-overview,
      .public-report-hub,
      .public-trend-grid,
      .public-ai-grid {
        grid-template-columns: 1fr;
      }
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


def extract_report_main_content(html: str) -> str:
    match = re.search(r'<main class="shell">(.*)</main>', html, flags=re.S)
    content = match.group(1) if match else html
    content = re.sub(r'<nav class="report-nav">.*?</nav>\s*(?:<script>.*?</script>)?', "", content, flags=re.S)
    content = re.sub(r"<footer>.*?</footer>", "", content, flags=re.S)
    content = add_metric_count_classes(content)
    return content.strip()


def add_metric_count_classes(content: str) -> str:
    result: list[str] = []
    cursor = 0
    marker = '<div class="metrics'
    while True:
        start = content.find(marker, cursor)
        if start < 0:
            result.append(content[cursor:])
            break
        result.append(content[cursor:start])
        tag_end = content.find(">", start)
        if tag_end < 0:
            result.append(content[start:])
            break

        depth = 0
        close_end = -1
        for match in re.finditer(r"<div\b|</div>", content[start:], flags=re.I):
            token = match.group(0).lower()
            if token.startswith("<div"):
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    close_end = start + match.end()
                    break
        if close_end < 0:
            result.append(content[start:])
            break

        block = content[start:close_end]
        open_tag = content[start : tag_end + 1]
        body = content[tag_end + 1 : close_end - len("</div>")]
        count = len(re.findall(r'<div class="metric(?:\s|")', body))
        if count > 0 and f"metrics-{count}" not in open_tag:
            open_tag = open_tag.replace('class="metrics', f'class="metrics metrics-{count}', 1)
            block = open_tag + body + "</div>"
        result.append(block)
        cursor = close_end
    return "".join(result)


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
                    html_text(detail.get("跳转地址") or detail.get("detail_url") or detail.get("url")),
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


def display_unit(unit: str) -> str:
    return {
        "count": "个",
        "hour": "人天",
    }.get(unit, unit)


def first_present_value(item: dict, *keys: str):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


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


def latest_non_null(points: list[dict]) -> dict:
    for point in reversed(points or []):
        if point.get("value") is not None and point.get("value") != "":
            return point
    return {}


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


def json_script_payload(payload) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def public_overview_cards_html(summary: dict) -> str:
    cards = []
    for card in summary.get("overview", []):
        unit = card.get("unit") or ""
        suffix = ""
        preview_asset = metric_preview_asset(str(card.get("key") or ""))
        if unit and unit != "%" and card.get("key") != "ai_non_deep_users":
            suffix = f' <span class="muted">{html_text(display_unit(unit))}</span>'
        cards.append(
            f"""
            <article class="metric-card metric-{html_text(card.get('indicator_type') or 'default')}{' has-preview' if preview_asset else ''}">
              <div class="metric-topline">
                <span class="metric-caption">{html_text(card.get('caption') or '指标')}</span>
              </div>
              <div class="metric-label">{html_text(card.get('label') or '-')}</div>
              <div class="metric-value">{html_text(card.get('display_value') or '-')}{suffix}</div>
              <div class="metric-foot">
                <span>{html_text(card.get('date') or '-')}</span>
                <span>{html_text(card.get('title') or '')}</span>
              </div>
              {f'''
              <div class="metric-preview">
                <div class="metric-preview-label">巡检截图</div>
                <img
                  src="{html_text(preview_asset)}"
                  alt="{html_text(card.get('label') or '-') }巡检截图"
                  loading="lazy"
                  data-preview-full="{html_text(preview_asset)}"
                  data-preview-title="{html_text(card.get('label') or '-')}"
                />
              </div>
              ''' if preview_asset else ''}
            </article>
            """
        )
    return "".join(cards)


def public_ai_users_html(summary: dict) -> str:
    ai = summary.get("ai_inspection") or {}
    users = ai.get("users") or []
    if not users:
        return '<div class="list-item">暂无 AI 非深度用户名单</div>'
    pills = []
    for user in users:
        name = str(user.get("name") or user.get("用户姓名") or "")
        initials = re.sub(r"\(.*?\)", "", name).strip()[:1] or "-"
        pills.append(
            f"""
            <span class="ai-user-pill" title="{html_text(name)}">
              <span class="ai-user-avatar">{html_text(initials)}</span>
              <span class="ai-user-name">{html_text(name)}</span>
            </span>
            """
        )
    return "".join(pills)


def static_site_targets() -> list[dict]:
    return [
        {"key": "daily", "title": "日常巡检报告", "filename": "daily-report.html", "description": "查看日常 OKR、AI 与持续交付巡检结果。", "kicker": "日常"},
        {"key": "weekly", "title": "周度巡检报告", "filename": "weekly-report.html", "description": "查看周度 INE 指标汇总与团队分布明细。", "kicker": "周度"},
        {"key": "repair", "title": "修复巡检报告", "filename": "repair-report.html", "description": "查看延期提测、延期上线修复筛选与结果。", "kicker": "修复"},
        {"key": "thursday", "title": "计划日期调整报告", "filename": "thursday-report.html", "description": "查看计划日期调整执行情况与明细记录。", "kicker": "日期调整"},
    ]


def static_report_hub_html() -> str:
    cards = []
    for item in static_site_targets():
        cards.append(
            f"""
            <a class="button-link" href="./{html_text(item['filename'])}">
              <span class="public-report-link-inner">
                <span class="public-report-link-kicker">{html_text(item['kicker'])}</span>
                <span class="public-report-link-title">{html_text(item['title'])}</span>
                <span class="public-report-link-desc">{html_text(item['description'])}</span>
              </span>
            </a>
            """
        )
    return "".join(cards)


def preferred_static_trend_id(chart_options: list[dict]) -> str:
    preferred_keywords = (
        "technical_refactor_working_hours",
        "biweekly_delivery_rate",
        "delay_online_rate",
        "delay_test_rate",
    )
    for keyword in preferred_keywords:
        for option in chart_options:
            haystack = f"{option.get('id') or ''} {option.get('key') or ''}"
            if keyword in haystack:
                return str(option.get("id") or "")
    return str((chart_options[0].get("id") if chart_options else "") or "")


def static_trend_stack_html(chart_options: list[dict], active_id: str) -> str:
    cards: list[str] = []
    for index, option in enumerate(chart_options):
        latest = latest_non_null(option.get("points") or [])
        option_id = str(option.get("id") or "")
        active = " active" if option_id == active_id else ""
        cards.append(
            f"""
            <button
              class="public-trend-stack-card{active}"
              type="button"
              data-chart-option="{html_text(option_id)}"
              style="--stack-shift: {index * 14}px; z-index: {100 - index};"
            >
              <span class="public-trend-stack-head">
                <span class="public-trend-stack-kicker">指标细节</span>
                <span class="public-trend-stack-index">{index + 1:02d}</span>
              </span>
              <strong class="public-trend-stack-title">{html_text(option.get("title") or "-")}</strong>
              <span class="public-trend-stack-foot">
                <span class="public-trend-stack-value">{html_text(format_value(latest.get("value"), option.get("unit") or ""))}</span>
                <span class="public-trend-stack-meta">{html_text(latest.get("date") or "-")}</span>
              </span>
            </button>
            """
        )
    return "".join(cards)


def static_report_nav_html(current_key: str) -> str:
    links = [
        ("home", "返回看板", "./index.html"),
        ("daily", "日常报告", "./daily-report.html"),
        ("weekly", "周度报告", "./weekly-report.html"),
        ("repair", "修复报告", "./repair-report.html"),
        ("thursday", "日期调整报告", "./thursday-report.html"),
    ]
    items = []
    for key, label, href in links:
        active = " active" if key == current_key else ""
        items.append(f'<a class="{("active" if active else "").strip()}" href="{href}">{html_text(label)}</a>')
    return f'<nav class="static-report-nav" aria-label="报告导航">{"".join(items)}</nav>'


def static_report_shell(page_title: str, current_key: str, report_content: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_text(page_title)}</title>
  <style>{STATIC_ROOT_REPORT_STYLE}{STATIC_ROOT_PAGE_STYLE}</style>
</head>
<body>
  <main class="public-shell">
    {static_report_nav_html(current_key)}
    <section class="public-reports">
      <article class="public-report-block">{report_content}</article>
    </section>
  </main>
</body>
</html>"""


def build_static_site_index_html() -> str:
    summary = current_summary()
    chart_options = build_chart_options(summary)
    ai = summary.get("ai_inspection") or {}
    active_chart_id = preferred_static_trend_id(chart_options)
    active_option = next((option for option in chart_options if str(option.get("id") or "") == active_chart_id), chart_options[0] if chart_options else None)
    active_points = (active_option or {}).get("points") or []
    active_latest = latest_non_null(active_points)
    active_range = f"{(active_points[0] or {}).get('date') or '-'} ~ {(active_points[-1] or {}).get('date') or '-'}" if active_points else "-"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>收银台&内单交易域巡检看板</title>
  <link rel="stylesheet" href="{STATIC_FRONTEND_STYLESHEET_PATH}" />
  <style>{STATIC_HOME_OVERRIDE_STYLE}</style>
</head>
<body>
  <main class="app-shell">
    <header class="topbar hero-panel">
      <div>
        <div class="eyebrow">收银台&内单交易域</div>
        <h1>收银台&内单交易域巡检看板</h1>
      </div>
      <div class="header-meta">
        <span>{html_text(summary.get('display_domain') or summary.get('department_c3') or '-')}</span>
        <span>{html_text((summary.get('time_range') or {}).get('start_date') or '-')} ~ {html_text((summary.get('time_range') or {}).get('end_date') or '-')}</span>
      </div>
    </header>

    <section class="command-bar public-command-bar">
      <div class="command-group report-group">
        <div class="command-label">查看报告</div>
        <div class="report-links">{static_report_hub_html()}</div>
      </div>
      <figure class="public-static-hero-art" aria-hidden="true">
        <img src="{STATIC_HERO_BRAND_PATH}" alt="" loading="lazy" />
      </figure>
    </section>

    <section id="dashboard" class="metric-grid">{public_overview_cards_html(summary)}</section>

    <section class="workspace">
      <div class="panel chart-panel">
        <div class="panel-head">
          <div>
            <h2>本周趋势</h2>
          </div>
        </div>
        <div class="public-trend-layout">
          <div class="public-trend-deck">
            {static_trend_stack_html(chart_options, active_chart_id)}
            <figure class="public-trend-visual" aria-hidden="true">
              <img src="{STATIC_TREND_ILLUSTRATION_PATH}" alt="" loading="lazy" />
            </figure>
          </div>
          <div class="public-trend-stage" data-active-chart="{html_text(active_chart_id)}">
            <div class="public-trend-stage-copy">
              <div class="public-trend-stage-kicker">当前细节</div>
              <div class="public-trend-stage-title" id="publicTrendTitle">{html_text((active_option or {}).get("title") or "-")}</div>
              <div class="public-trend-stage-meta" id="publicTrendMeta">最新值 {html_text(format_value(active_latest.get("value"), (active_option or {}).get("unit") or ""))} / {html_text(active_latest.get("date") or "-")}</div>
            </div>
            <div class="public-trend-stage-stats">
              <div class="public-trend-stage-stat">
                <span>最新值</span>
                <strong id="publicTrendLatest">{html_text(format_value(active_latest.get("value"), (active_option or {}).get("unit") or ""))}</strong>
              </div>
              <div class="public-trend-stage-stat">
                <span>时间范围</span>
                <strong id="publicTrendRange">{html_text(active_range)}</strong>
              </div>
              <div class="public-trend-stage-stat">
                <span>采样点</span>
                <strong id="publicTrendCount">{len(active_points)}</strong>
              </div>
            </div>
            <div class="public-trend-stage-canvas">
              <canvas id="publicTrendCanvas"></canvas>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="lower-grid static-lower-grid">
      <div class="panel ai-users-panel public-ai-section">
        <div class="panel-head compact">
          <div>
            <h2>AI 非深度用户</h2>
            <p id="publicAiMeta">{html_text(ai.get('date') or '-')} · 共 {len(ai.get('users') or [])} 人</p>
          </div>
        </div>
        <div class="public-ai-grid">{public_ai_users_html(summary)}</div>
      </div>
    </section>

    <div id="imagePreviewModal" class="image-preview-modal" hidden>
      <div id="imagePreviewBackdrop" class="image-preview-backdrop"></div>
      <div class="image-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="imagePreviewTitle">
        <div class="image-preview-head">
          <div>
            <div class="image-preview-kicker">巡检截图</div>
            <h3 id="imagePreviewTitle">截图预览</h3>
          </div>
          <button id="imagePreviewCloseBtn" class="image-preview-close" type="button" aria-label="关闭预览">关闭</button>
        </div>
        <div class="image-preview-frame">
          <img id="imagePreviewImage" alt="" />
        </div>
      </div>
    </div>
  </main>

  <script id="staticChartData" type="application/json">{json_script_payload(chart_options)}</script>
  <script>
    (() => {{
      const fmt = (value, unit = "") => {{
        if (value === null || value === undefined || value === "") return "-";
        const shown = typeof value === "number" && !Number.isInteger(value)
          ? String(Number(value.toFixed(2))).replace(/\\.0$/, "")
          : String(value);
        return unit === "%" ? `${{shown}}%` : shown;
      }};
      const payload = JSON.parse(document.getElementById("staticChartData").textContent || "[]");
      const detailCanvas = document.getElementById("publicTrendCanvas");
      const trendTitle = document.getElementById("publicTrendTitle");
      const trendMeta = document.getElementById("publicTrendMeta");
      const trendLatest = document.getElementById("publicTrendLatest");
      const trendRange = document.getElementById("publicTrendRange");
      const trendCount = document.getElementById("publicTrendCount");
      const trendStage = document.querySelector(".public-trend-stage");
      const trendCards = Array.from(document.querySelectorAll("[data-chart-option]"));
      let activeChartId = trendStage?.dataset.activeChart || (payload[0]?.id ?? "");
      const drawChart = (canvas, option) => {{
        const ctx = canvas.getContext("2d");
        const points = (option.points || []).filter((point) => point.value !== null && point.value !== undefined);
        const rect = canvas.getBoundingClientRect();
        const cssWidth = Math.max(320, Math.floor(rect.width));
        const cssHeight = Math.max(420, Math.floor(rect.height));
        const dpr = Math.max(1, window.devicePixelRatio || 1);
        const bitmapWidth = Math.floor(cssWidth * dpr);
        const bitmapHeight = Math.floor(cssHeight * dpr);
        if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {{
          canvas.width = bitmapWidth;
          canvas.height = bitmapHeight;
        }}
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssWidth, cssHeight);
        const pad = {{ left: 74, right: 26, top: 24, bottom: 46 }};
        const width = cssWidth - pad.left - pad.right;
        const height = cssHeight - pad.top - pad.bottom;
        ctx.strokeStyle = "#d9e1e7";
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top);
        ctx.lineTo(pad.left, pad.top + height);
        ctx.lineTo(pad.left + width, pad.top + height);
        ctx.stroke();
        ctx.strokeStyle = "#eef3f5";
        ctx.lineWidth = 1.2;
        for (let i = 1; i < 4; i += 1) {{
          const y = pad.top + (height / 4) * i;
          ctx.beginPath();
          ctx.moveTo(pad.left, y);
          ctx.lineTo(pad.left + width, y);
          ctx.stroke();
        }}
        if (!points.length) {{
          ctx.fillStyle = "#62707c";
          ctx.font = "600 15px -apple-system, BlinkMacSystemFont, sans-serif";
          ctx.fillText("暂无可绘制数据", pad.left + 24, pad.top + 80);
          return;
        }}
        const values = points.map((point) => Number(point.value));
        let min = Math.min(...values);
        let max = Math.max(...values);
        if (min === max) {{
          min = Math.max(0, min - 1);
          max = max + 1;
        }}
        const yFor = (value) => pad.top + height - ((value - min) / (max - min)) * height;
        const xFor = (index) => pad.left + (points.length === 1 ? width / 2 : (index / (points.length - 1)) * width);
        ctx.strokeStyle = "#246fa8";
        ctx.lineWidth = 4;
        ctx.beginPath();
        points.forEach((point, index) => {{
          const x = xFor(index);
          const y = yFor(Number(point.value));
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }});
        ctx.stroke();
        points.forEach((point, index) => {{
          const x = xFor(index);
          const y = yFor(Number(point.value));
          ctx.fillStyle = "#ffffff";
          ctx.strokeStyle = "#246fa8";
          ctx.lineWidth = 3.5;
          ctx.beginPath();
          ctx.arc(x, y, 6, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
          const valueText = fmt(point.value, option.unit);
          ctx.font = "800 14px -apple-system, BlinkMacSystemFont, sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          const textWidth = ctx.measureText(valueText).width;
          let labelX = x;
          let labelY = Math.max(pad.top + 14, y - 18);
          if (index === 0 && points.length > 1) labelX = x + textWidth / 2 + 14;
          if (index === points.length - 1 && points.length > 1) labelX = x - textWidth / 2 - 14;
          ctx.fillStyle = "rgba(255,255,255,0.9)";
          ctx.fillRect(labelX - textWidth / 2 - 7, labelY - 10, textWidth + 14, 20);
          ctx.fillStyle = "#1d2a36";
          ctx.fillText(valueText, labelX, labelY);
          ctx.fillStyle = "#62707c";
          ctx.font = "700 13px -apple-system, BlinkMacSystemFont, sans-serif";
          ctx.textBaseline = "alphabetic";
          ctx.fillText(String(point.date || "").slice(5), x, pad.top + height + 38);
        }});
        ctx.textAlign = "right";
        ctx.fillStyle = "#62707c";
        ctx.font = "700 13px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText(fmt(max, option.unit), pad.left - 12, pad.top + 4);
        ctx.fillText(fmt(min, option.unit), pad.left - 12, pad.top + height + 4);
      }};
      const optionById = (id) => payload.find((option) => option.id === id) || payload[0];
      const renderActiveChart = (id) => {{
        const option = optionById(id);
        if (!option || !detailCanvas) return;
        activeChartId = option.id;
        const points = (option.points || []).filter((point) => point.value !== null && point.value !== undefined);
        const latest = points[points.length - 1] || {{}};
        const range = points.length ? `${{points[0].date || "-"}} ~ ${{points[points.length - 1].date || "-"}}` : "-";
        if (trendStage) trendStage.dataset.activeChart = activeChartId;
        if (trendTitle) trendTitle.textContent = option.title || "-";
        if (trendMeta) trendMeta.textContent = `最新值 ${{fmt(latest.value, option.unit)}} / ${{latest.date || "-"}}`;
        if (trendLatest) trendLatest.textContent = fmt(latest.value, option.unit);
        if (trendRange) trendRange.textContent = range;
        if (trendCount) trendCount.textContent = String(points.length);
        trendCards.forEach((card) => {{
          card.classList.toggle("active", card.dataset.chartOption === activeChartId);
        }});
        drawChart(detailCanvas, option);
      }};
      trendCards.forEach((card) => {{
        card.addEventListener("click", () => {{
          renderActiveChart(card.dataset.chartOption || "");
        }});
      }});
      const rerender = () => {{
        renderActiveChart(activeChartId);
      }};

      const modal = document.getElementById("imagePreviewModal");
      const modalImage = document.getElementById("imagePreviewImage");
      const modalTitle = document.getElementById("imagePreviewTitle");
      const closeBtn = document.getElementById("imagePreviewCloseBtn");
      const backdrop = document.getElementById("imagePreviewBackdrop");
      const openImagePreview = (src, title) => {{
        if (!modal || !modalImage || !modalTitle) return;
        modalImage.src = src;
        modalImage.alt = `${{title}}巡检截图`;
        modalTitle.textContent = title || "截图预览";
        modal.hidden = false;
        document.body.style.overflow = "hidden";
      }};
      const closeImagePreview = () => {{
        if (!modal || !modalImage) return;
        modal.hidden = true;
        modalImage.removeAttribute("src");
        document.body.style.overflow = "";
      }};
      document.querySelectorAll(".metric-preview img[data-preview-full]").forEach((image) => {{
        image.addEventListener("click", () => {{
          openImagePreview(image.dataset.previewFull || image.src, image.dataset.previewTitle || image.alt || "截图预览");
        }});
      }});
      closeBtn?.addEventListener("click", closeImagePreview);
      backdrop?.addEventListener("click", closeImagePreview);
      document.addEventListener("keydown", (event) => {{
        if (event.key === "Escape" && modal && !modal.hidden) closeImagePreview();
      }});

      rerender();
      window.addEventListener("resize", rerender);
    }})();
  </script>
</body>
</html>"""


def sync_public_static_site() -> dict:
    assets = sync_metric_preview_assets()
    files = {
        STATIC_ROOT_INDEX_PATH: build_static_site_index_html(),
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
