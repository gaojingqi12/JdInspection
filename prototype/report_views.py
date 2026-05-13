from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
STATIC_ROOT_ASSET_PATH = "./prototype/static/assets/jd-inspection-page-background.png"
STATIC_FRONTEND_STYLESHEET_PATH = "./prototype/static/styles.css"
STATIC_ROOT_REPORT_STYLE = REPORT_STYLE.replace('/static/assets/jd-inspection-page-background.png', STATIC_ROOT_ASSET_PATH)
STATIC_TREND_ILLUSTRATION_PATH = "./prototype/static/assets/jd-static-trend-banner.png"
STATIC_HERO_BRAND_PATH = "./prototype/static/assets/jd-static-showcase-hero-brand.png"

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
      object-fit: cover;
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

def format_value(value, unit: str = "") -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        shown = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        shown = str(value)
    return f"{shown}%" if unit == "%" else shown

def display_unit(unit: str) -> str:
    return {
        "count": "个",
        "hour": "人天",
    }.get(unit, unit)

def latest_non_null(points: list[dict]) -> dict:
    for point in reversed(points or []):
        if point.get("value") is not None and point.get("value") != "":
            return point
    return {}

def json_script_payload(payload) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

def public_overview_cards_html(summary: dict, preview_assets: dict[str, str | None] | None = None) -> str:
    preview_assets = preview_assets or {}
    cards = []
    for card in summary.get("overview", []):
        unit = card.get("unit") or ""
        suffix = ""
        preview_asset = preview_assets.get(str(card.get("key") or "")) or ""
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

def build_static_site_index_html(
    summary: dict[str, Any],
    chart_options: list[dict[str, Any]],
    preview_assets: dict[str, str | None] | None = None,
) -> str:
    preview_assets = preview_assets or {}
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

    <section id="dashboard" class="metric-grid">{public_overview_cards_html(summary, preview_assets)}</section>

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
