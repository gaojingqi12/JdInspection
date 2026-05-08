import json
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MODIFIED_JSON = BASE_DIR / "thursday_to_friday_modified.json"
SUBMIT_TEST_JSON = BASE_DIR / "thursday_submit_test_demands.json"
ONLINE_JSON = BASE_DIR / "thursday_online_demands.json"
REPORT_HTML = BASE_DIR / "index.html"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def text(value) -> str:
    return escape(str(value or ""))


def link(url: str, label: str) -> str:
    if not url:
        return '<span class="muted">-</span>'
    return f'<a href="{text(url)}" target="_blank" rel="noreferrer">{text(label)}</a>'


def field_badge(field_label: str) -> str:
    class_name = "submit-test" if field_label == "计划提测日期" else "online"
    return f'<span class="badge {class_name}">{text(field_label)}</span>'


def status_badge(confirm_clicked) -> str:
    if confirm_clicked:
        return '<span class="status ok">已确认</span>'
    return '<span class="status calm">无确认弹窗</span>'


def group_items(items: list[dict], field_label: str) -> list[dict]:
    return [item for item in items if item.get("field_label") == field_label]


def render_rows(items: list[dict]) -> str:
    if not items:
        return '<tr><td colspan="10" class="empty">暂无记录</td></tr>'

    rows = []
    for index, item in enumerate(items, 1):
        rows.append(
            f"""
            <tr>
              <td class="index">{index}</td>
              <td>
                <div class="demand">{text(item.get("demand_name"))}</div>
                <div class="meta">cardId {text(item.get("item_id"))} · group {text(item.get("group_id"))} · index {text(item.get("item_index"))}</div>
              </td>
              <td>{text(item.get("owner") or "未提取")}</td>
              <td>{text(item.get("sprint_title"))}<div class="meta">sprintId {text(item.get("sprint_data_item"))}</div></td>
              <td>{field_badge(str(item.get("field_label") or ""))}</td>
              <td><span class="date old">{text(item.get("old_value"))}</span></td>
              <td><span class="date new">{text(item.get("new_value"))}</span></td>
              <td><span class="date current">{text(item.get("page_current_value"))}</span></td>
              <td>{status_badge(item.get("confirm_clicked"))}<div class="meta">{text(item.get("modified_at"))}</div></td>
              <td>{link(str(item.get("detail_url") or item.get("page_url") or ""), "打开详情")}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_failed_rows(items: list[dict]) -> str:
    if not items:
        return '<tr><td colspan="8" class="empty">暂无失败记录</td></tr>'

    rows = []
    for index, item in enumerate(items, 1):
        rows.append(
            f"""
            <tr>
              <td class="index">{index}</td>
              <td><div class="demand">{text(item.get("demand_name"))}</div><div class="meta">cardId {text(item.get("item_id"))}</div></td>
              <td>{text(item.get("owner") or "未提取")}</td>
              <td>{text(item.get("sprint_title"))}</td>
              <td>{field_badge(str(item.get("field_label") or "-"))}</td>
              <td>{text(item.get("reason"))}</td>
              <td>{text(item.get("failed_at"))}</td>
              <td>{link(str(item.get("detail_url") or ""), "打开详情")}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_planned_rows(items: list[dict], kind: str) -> str:
    if not items:
        return '<tr><td colspan="7" class="empty">暂无待处理记录</td></tr>'

    rows = []
    for index, item in enumerate(items, 1):
        target_date = item.get("plan_submit_test_date") if kind == "submit" else item.get("plan_date")
        rows.append(
            f"""
            <tr>
              <td class="index">{index}</td>
              <td><div class="demand">{text(item.get("demand_name"))}</div><div class="meta">cardId {text(item.get("item_id"))}</div></td>
              <td>{text(item.get("owner") or "未提取")}</td>
              <td>{text(item.get("sprint_title"))}</td>
              <td><span class="date old">{text(target_date)}</span></td>
              <td>{text(item.get("plan_submit_test_date"))}</td>
              <td>{text(item.get("plan_date"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_metric(label: str, value: int | str, note: str = "") -> str:
    return f"""
    <div class="metric">
      <div class="metric-label">{text(label)}</div>
      <div class="metric-value">{text(value)}</div>
      <div class="metric-note">{text(note)}</div>
    </div>
    """


def generate_report() -> Path:
    modified_data = load_json(MODIFIED_JSON)
    submit_data = load_json(SUBMIT_TEST_JSON)
    online_data = load_json(ONLINE_JSON)

    modified_items = modified_data.get("modified_items") or []
    failed_items = modified_data.get("failed_items") or []
    submit_modified = group_items(modified_items, "计划提测日期")
    online_modified = group_items(modified_items, "计划上线日期")
    submit_planned = submit_data.get("items") or []
    online_planned = online_data.get("items") or []
    sprint_counter = Counter(item.get("sprint_title") or "未识别迭代" for item in modified_items)

    source_date = modified_data.get("source_date") or submit_data.get("target_date") or online_data.get("target_date") or "-"
    target_date = modified_data.get("target_date") or "-"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    top_sprints = " · ".join(f"{name} {count}" for name, count in sprint_counter.most_common(4)) or "暂无"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>需求计划日期调整执行报告</title>
  <style>
    :root {{
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
    }}
    * {{ box-sizing: border-box; }}
    body {{
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
    }}
    .shell {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 32px 28px 56px;
    }}
    .hero {{
      color: #fff;
      padding: 28px 0 22px;
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 24px;
      align-items: end;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(32px, 5vw, 64px);
      line-height: 1;
      letter-spacing: 0;
      font-weight: 800;
    }}
    .subtitle {{
      max-width: 880px;
      font-size: 16px;
      line-height: 1.8;
      color: rgba(255,255,255,0.82);
    }}
    .run-card {{
      background: rgba(255,255,255,0.14);
      border: 1px solid rgba(255,255,255,0.22);
      backdrop-filter: blur(12px);
      border-radius: 8px;
      padding: 18px;
      color: rgba(255,255,255,0.92);
    }}
    .run-card strong {{ display: block; font-size: 22px; margin-bottom: 4px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
      margin: 18px 0 26px;
    }}
    .metric {{
      background: var(--panel);
      border-radius: 8px;
      padding: 18px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(215,221,230,0.85);
      min-height: 112px;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .metric-value {{ font-size: 34px; font-weight: 800; margin: 8px 0 6px; color: var(--navy); }}
    .metric-note {{ color: var(--muted); font-size: 12px; line-height: 1.5; }}
    section {{
      background: var(--panel);
      border: 1px solid rgba(215,221,230,0.95);
      box-shadow: var(--shadow);
      border-radius: 8px;
      margin-top: 18px;
      overflow: hidden;
    }}
    .section-head {{
      padding: 20px 22px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      background: linear-gradient(90deg, #fff, #f7fafc);
    }}
    h2 {{ margin: 0; font-size: 20px; letter-spacing: 0; }}
    .section-note {{ color: var(--muted); font-size: 13px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1120px;
    }}
    th {{
      text-align: left;
      padding: 13px 14px;
      color: #445065;
      background: #f3f6fa;
      font-size: 12px;
      font-weight: 700;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }}
    td {{
      padding: 15px 14px;
      border-bottom: 1px solid #e8edf3;
      vertical-align: top;
      font-size: 13px;
      line-height: 1.45;
    }}
    tr:hover td {{ background: #f8fbfd; }}
    .index {{ color: var(--muted); width: 54px; }}
    .demand {{ font-weight: 700; color: var(--ink); max-width: 360px; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
    .muted {{ color: var(--muted); }}
    a {{ color: var(--blue); text-decoration: none; font-weight: 700; }}
    a:hover {{ text-decoration: underline; }}
    .badge, .status {{
      display: inline-flex;
      align-items: center;
      height: 24px;
      border-radius: 999px;
      padding: 0 10px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .badge.submit-test {{ background: rgba(29,111,184,0.12); color: var(--blue); }}
    .badge.online {{ background: rgba(15,139,111,0.12); color: var(--green); }}
    .status.ok {{ background: rgba(15,139,111,0.12); color: var(--green); }}
    .status.calm {{ background: rgba(183,121,31,0.12); color: var(--amber); }}
    .date {{
      display: inline-flex;
      border-radius: 6px;
      padding: 5px 8px;
      font-weight: 800;
      white-space: nowrap;
      border: 1px solid transparent;
    }}
    .date.old {{ color: var(--red); background: rgba(180,35,24,0.08); border-color: rgba(180,35,24,0.15); }}
    .date.new {{ color: var(--green); background: rgba(15,139,111,0.10); border-color: rgba(15,139,111,0.16); }}
    .date.current {{ color: var(--navy); background: #eef4fa; border-color: #d7e4f1; }}
    .empty {{ color: var(--muted); text-align: center; padding: 28px; }}
    .report-nav {{
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
    }}
    .report-nav a {{
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
    }}
    .report-nav a:hover {{
      color: #fff;
      background: rgba(255,255,255,0.08);
      border-color: rgba(255,255,255,0.14);
      text-decoration: none;
    }}
    .report-nav a[aria-current="page"] {{
      color: #10243f;
      background: rgba(255,255,255,0.76);
      border-color: rgba(255,255,255,0.46);
      box-shadow: 0 8px 20px rgba(0,0,0,0.10);
    }}
    .split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-top: 18px;
    }}
    .split section {{ margin-top: 0; }}
    footer {{
      color: rgba(255,255,255,0.76);
      font-size: 12px;
      margin-top: 22px;
      text-align: right;
    }}
    @media (max-width: 980px) {{
      .hero, .split {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .shell {{ padding: 22px 14px 42px; }}
    }}
    @media (max-width: 560px) {{
      .metrics {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <h1>需求计划日期调整执行报告</h1>
      </div>
      <div class="run-card">
        <strong>{text(generated_at)}</strong>
        <div>报告生成时间</div>
        <div class="meta" style="color: rgba(255,255,255,0.72);">主要迭代：{text(top_sprints)}</div>
      </div>
    </header>

    <div class="metrics">
      {render_metric("成功修改", len(modified_items), f"失败 {len(failed_items)} 条")}
      {render_metric("修改提测", len(submit_modified), f"待处理清单 {len(submit_planned)} 条")}
      {render_metric("修改上线", len(online_modified), f"待处理清单 {len(online_planned)} 条")}
      {render_metric("源日期", source_date, "本周四")}
      {render_metric("目标日期", target_date, "本周五")}
    </div>

    <section>
      <div class="section-head">
        <h2>修改提测</h2>
        <div class="section-note">计划提测日期已从周四调整到周五</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>需求</th><th>负责人</th><th>迭代</th><th>字段</th><th>修改前</th><th>修改后</th><th>页面当前值</th><th>确认状态</th><th>链接</th></tr>
          </thead>
          <tbody>{render_rows(submit_modified)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>修改上线</h2>
        <div class="section-note">计划上线日期已从周四调整到周五</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>需求</th><th>负责人</th><th>迭代</th><th>字段</th><th>修改前</th><th>修改后</th><th>页面当前值</th><th>确认状态</th><th>链接</th></tr>
          </thead>
          <tbody>{render_rows(online_modified)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>失败记录</h2>
        <div class="section-note">未能修改或详情校验不一致的需求</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>需求</th><th>负责人</th><th>迭代</th><th>字段</th><th>原因</th><th>时间</th><th>链接</th></tr>
          </thead>
          <tbody>{render_failed_rows(failed_items)}</tbody>
        </table>
      </div>
    </section>

    <div class="split">
      <section>
        <div class="section-head">
          <h2>本周四提测清单</h2>
          <div class="section-note">修改前识别结果</div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>需求</th><th>负责人</th><th>迭代</th><th>命中日期</th><th>计划提测</th><th>计划上线</th></tr>
            </thead>
            <tbody>{render_planned_rows(submit_planned, "submit")}</tbody>
          </table>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h2>本周四上线清单</h2>
          <div class="section-note">修改前识别结果</div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>需求</th><th>负责人</th><th>迭代</th><th>命中日期</th><th>计划提测</th><th>计划上线</th></tr>
            </thead>
            <tbody>{render_planned_rows(online_planned, "online")}</tbody>
          </table>
        </div>
      </section>
    </div>

    <footer>数据来源：thursday_to_friday_modified.json / thursday_submit_test_demands.json / thursday_online_demands.json</footer>
  </main>
</body>
</html>
"""
    REPORT_HTML.write_text(html, encoding="utf-8")
    return REPORT_HTML


if __name__ == "__main__":
    path = generate_report()
    print(f"已生成报告: {path}")
