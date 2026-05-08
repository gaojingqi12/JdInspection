from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from inspection_config import require_config


SKILL_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = SKILL_DIR / "out"
TEMPLATE_PATH = SKILL_DIR / "assets" / "inspection-summary-template.md"
DEFAULT_SUMMARY_JSON = OUT_DIR / "weekly-inspection-summary.json"
DEFAULT_OUTPUT_PATH = OUT_DIR / "daily-inspection-summary.md"
HTML_OUTPUT_PATH = ROOT_DIR / "index.html"

COMMON_CONFIG = require_config("common")
CONTINUOUS_DELIVERY_CONFIG = require_config("continuous_delivery")
DISPLAY_DOMAIN = COMMON_CONFIG.get("display_domain") or COMMON_CONFIG.get("department_c3", "")
ONLINE_REPORT_URL = COMMON_CONFIG.get("online_report_url", "")
STATUS_LABELS = {
    "success": "成功",
    "partial": "部分成功",
    "missing": "缺失",
    "failed": "失败",
    "timeout": "超时",
    "skipped": "已跳过",
    "not_triggered": "未触发",
    "missing_script": "脚本缺失",
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象")
    return data


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def format_bool(value: Any) -> str:
    return "是" if bool(value) else "否"


def format_status(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return STATUS_LABELS.get(str(value), str(value))


def format_number(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def format_value(value: Any, unit: str) -> str:
    shown = format_number(value)
    if shown == "-":
        return shown
    return f"{shown}%" if unit == "%" else shown


def markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def markdown_table(headers: list[str], rows: list[list[Any]], *, align_right: set[int] | None = None) -> str:
    align_right = align_right or set()
    separator = ["---:" if index in align_right else "---" for index in range(len(headers))]
    lines = [
        "| " + " | ".join(markdown_cell(item) for item in headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(item) for item in row) + " |")
    return "\n".join(lines)


def indicator_by_type(summary: dict[str, Any], indicator_type: str) -> dict[str, Any]:
    for indicator in as_list(summary.get("indicators")):
        if isinstance(indicator, dict) and indicator.get("indicator_type") == indicator_type:
            return indicator
    return {}


def latest_history_point(
    summary: dict[str, Any],
    indicator_type: str,
    metric_key: str,
) -> tuple[Any, str, str]:
    indicator = indicator_by_type(summary, indicator_type)
    history = as_dict(indicator.get("history"))
    points = [point for point in as_list(history.get(metric_key)) if isinstance(point, dict)]
    inspection_date = str(summary.get("inspection_date") or "")

    selected = None
    for point in points:
        if point.get("date") == inspection_date:
            selected = point
            break
    if selected is None and points:
        selected = sorted(points, key=lambda item: str(item.get("date", "")))[-1]

    if not selected:
        return None, "-", str(indicator.get("status") or "missing")
    return selected.get("value"), str(selected.get("date") or "-"), str(indicator.get("status") or "-")


def repair_by_type(summary: dict[str, Any], repair_type: str) -> dict[str, Any]:
    for repair in as_list(summary.get("repair_inspections")):
        if isinstance(repair, dict) and repair.get("repair_type") == repair_type:
            return repair
    return {}


def repair_count_key(summary: dict[str, Any], fallback: str) -> str:
    for key in summary:
        if key.startswith("筛选延期"):
            return key
    return fallback


def repair_metric(
    summary: dict[str, Any],
    repair_type: str,
    fallback_count_key: str,
) -> tuple[Any, str, str]:
    repair = repair_by_type(summary, repair_type)
    repair_summary = as_dict(repair.get("summary"))
    count_key = repair_count_key(repair_summary, fallback_count_key)
    return (
        repair_summary.get(count_key),
        str(repair_summary.get("巡检日期") or repair.get("date") or summary.get("inspection_date") or "-"),
        str(repair_summary.get("巡检状态") or "-"),
    )


def continuous_metric(summary: dict[str, Any], metric_key: str) -> tuple[Any, str, str]:
    delivery = as_dict(summary.get("continuous_delivery"))
    metrics = as_dict(delivery.get("metrics"))
    return (
        metrics.get(metric_key),
        str(delivery.get("date") or summary.get("inspection_date") or "-"),
        str(delivery.get("status") or "missing"),
    )


def ai_metric(summary: dict[str, Any]) -> tuple[Any, str, str]:
    ai = as_dict(summary.get("ai_inspection"))
    return (
        ai.get("count"),
        str(ai.get("date") or summary.get("inspection_date") or "-"),
        str(ai.get("status") or "missing"),
    )


def metric_row(label: str, scope: str, value: Any, unit: str, date: str, status: str) -> list[Any]:
    return [label, scope, format_value(value, unit), unit or "-", date, format_status(status)]


def build_metrics_table(summary: dict[str, Any]) -> str:
    rows: list[list[Any]] = []

    value, day, status = latest_history_point(summary, "delay_test_rate", "planned_test_requirements")
    rows.append(metric_row("计划提测需求数", "支付方案研发部 OKR 汇总", value, "个", day, status))

    value, day, status = repair_metric(summary, "delayed_test", "筛选延期提测数")
    rows.append(metric_row("延期提测需求数", f"{DISPLAY_DOMAIN} 当天", value, "个", day, status))

    value, day, status = latest_history_point(summary, "delay_test_rate", "delay_test_rate_okr")
    rows.append(metric_row("延期提测率", "支付方案研发部 OKR 汇总", value, "%", day, status))

    value, day, status = latest_history_point(summary, "delay_online_rate", "planned_online_requirements")
    rows.append(metric_row("计划上线需求数", "支付方案研发部 OKR 汇总", value, "个", day, status))

    value, day, status = repair_metric(summary, "delayed_online", "筛选延期上线数")
    rows.append(metric_row("延期上线需求数", f"{DISPLAY_DOMAIN} 当天", value, "个", day, status))

    value, day, status = latest_history_point(summary, "delay_online_rate", "delay_online_rate")
    rows.append(metric_row("延期上线率", "支付方案研发部 OKR 汇总", value, "%", day, status))

    value, day, status = latest_history_point(summary, "technical_refactor_working_hours", "total_working_hours")
    rows.append(metric_row("总工时/填报工时", "支付方案研发部 OKR 汇总", value, "人天", day, status))

    value, day, status = latest_history_point(summary, "technical_refactor_working_hours", "technical_refactor_working_hours")
    rows.append(metric_row("技术改造工时", "支付方案研发部 OKR 汇总", value, "人天", day, status))

    value, day, status = latest_history_point(summary, "technical_refactor_working_hours", "technical_refactor_working_hours_rate")
    rows.append(metric_row("技术改造工时占比", "支付方案研发部 OKR 汇总", value, "%", day, status))

    value, day, status = latest_history_point(summary, "bi_weekly_delivery_rate", "biweekly_delivery_rate")
    rows.append(metric_row("双周交付率", "支付方案研发部 OKR 汇总", value, "%", day, status))

    delivery_metric_labels = {
        item["key"]: item.get("label", item["key"])
        for item in CONTINUOUS_DELIVERY_CONFIG.get("metrics", [])
    }
    for metric_key in (
        "team_space_dev_test_online_requirements",
        "team_space_continuous_delivery_dev_test_online_requirements",
        "continuous_delivery_team_space_online_requirement_rate",
    ):
        value, day, status = continuous_metric(summary, metric_key)
        unit = "%" if metric_key.endswith("_rate") else "个"
        rows.append(metric_row(delivery_metric_labels.get(metric_key, metric_key), "持续交付当天", value, unit, day, status))

    value, day, status = ai_metric(summary)
    rows.append(metric_row("AI 非深度用户数", "AI 巡检当天", value, "人", day, status))

    return markdown_table(["指标", "口径", "最新值", "单位", "最新日期", "状态"], rows, align_right={2})


def build_repair_table(summary: dict[str, Any]) -> str:
    rows: list[list[Any]] = []
    for repair_type, title, fallback_key in (
        ("delayed_test", "延期提测修复", "筛选延期提测数"),
        ("delayed_online", "延期上线修复", "筛选延期上线数"),
    ):
        repair = repair_by_type(summary, repair_type)
        repair_summary = as_dict(repair.get("summary"))
        count_key = repair_count_key(repair_summary, fallback_key)
        notes = "；".join(str(item) for item in as_list(repair_summary.get("备注")) if item) or "-"
        rows.append(
            [
                title,
                format_bool(as_dict(repair.get("trigger")).get("triggered")),
                format_status(repair_summary.get("巡检状态")),
                repair_summary.get(count_key, 0),
                repair_summary.get("已点击数", 0),
                repair_summary.get("已修复数", 0),
                repair_summary.get("失败数", 0),
                notes,
            ]
        )

    return markdown_table(
        ["修复项", "是否触发", "巡检状态", "筛选数", "已点击数", "已修复数", "失败数", "备注"],
        rows,
        align_right={3, 4, 5, 6},
    )


def build_success_details(summary: dict[str, Any]) -> str:
    rows: list[list[Any]] = []
    for repair_type, title in (
        ("delayed_test", "延期提测修复"),
        ("delayed_online", "延期上线修复"),
    ):
        repair_summary = as_dict(repair_by_type(summary, repair_type).get("summary"))
        for item in as_list(repair_summary.get("成功明细")):
            if not isinstance(item, dict):
                continue
            jump_url = item.get("跳转地址") or ""
            link = f"[打开]({jump_url})" if jump_url else "-"
            rows.append(
                [
                    title,
                    item.get("需求编码") or "-",
                    item.get("需求名称") or "-",
                    item.get("研发负责人") or "-",
                    item.get("修改字段") or "-",
                    item.get("修改后") or "-",
                    link,
                ]
            )

    if not rows:
        return "暂无成功修复明细。"

    return markdown_table(["修复项", "需求编码", "需求名称", "研发负责人", "修改字段", "修改后", "跳转地址"], rows)


def build_attention(summary: dict[str, Any]) -> str:
    items: list[str] = []

    if summary.get("status") not in {"success", None}:
        items.append(f"总状态为 {format_status(summary.get('status'))}，需要确认缺失或部分成功的模块。")

    for indicator in as_list(summary.get("indicators")):
        if not isinstance(indicator, dict):
            continue
        status = indicator.get("status")
        if status != "success":
            name = indicator.get("indicator_name") or indicator.get("indicator_type") or "OKR 指标"
            items.append(f"{name} 状态为 {format_status(status)}。")

    ai = as_dict(summary.get("ai_inspection"))
    if ai.get("status") != "success":
        items.append(f"AI 巡检状态为 {format_status(ai.get('status') or 'missing')}：{ai.get('error') or '未读取到当天结果'}。")

    delivery = as_dict(summary.get("continuous_delivery"))
    if delivery.get("status") != "success":
        items.append(f"持续交付状态为 {format_status(delivery.get('status') or 'missing')}：{delivery.get('error') or '未读取到当天结果'}。")

    for repair in as_list(summary.get("repair_inspections")):
        if not isinstance(repair, dict):
            continue
        title = repair.get("title") or "延期修复巡检"
        repair_summary = as_dict(repair.get("summary"))
        state = repair_summary.get("巡检状态")
        if state not in {"通过", "未触发"}:
            items.append(f"{title} 状态为 {format_status(state)}。")

        script = as_dict(repair.get("script"))
        triggered = as_dict(repair.get("trigger")).get("triggered")
        if triggered and script.get("status") == "skipped":
            items.append(f"{title} 本次跳过真实修复脚本，仅展示已有修复 JSON。")
        elif triggered and script.get("status") in {"failed", "timeout", "missing_script"}:
            items.append(f"{title} 脚本执行状态为 {format_status(script.get('status'))}：{script.get('error') or '-'}。")

        failures = repair_summary.get("失败数")
        if isinstance(failures, (int, float)) and failures > 0:
            items.append(f"{title} 有 {format_number(failures)} 个失败项。")

        missing = as_list(repair_summary.get("缺失字段明细"))
        if missing:
            items.append(f"{title} 有 {len(missing)} 条明细需要补充字段。")

    if not items:
        return "- 暂无需关注项。"

    return "\n".join(f"- {item}" for item in items)


def data_range(summary: dict[str, Any]) -> str:
    time_range = as_dict(summary.get("time_range"))
    start = time_range.get("start_date") or "-"
    end = time_range.get("end_date") or "-"
    return f"{start} 至 {end}"


def fill_template(template: str, replacements: dict[str, str]) -> str:
    content = template
    for token, value in replacements.items():
        content = content.replace(token, value)
    return content


def render_summary_markdown(
    summary: dict[str, Any],
    *,
    template_path: Path = TEMPLATE_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    summary_json_path: Path = DEFAULT_SUMMARY_JSON,
) -> str:
    template = template_path.read_text(encoding="utf-8")
    replacements = {
        "{{展示域名}}": str(summary.get("display_domain") or DISPLAY_DOMAIN),
        "{{巡检日期}}": str(summary.get("inspection_date") or "-"),
        "{{数据周期}}": data_range(summary),
        "{{总状态}}": format_status(summary.get("status")),
        "{{报告地址}}": str(ONLINE_REPORT_URL or "-"),
        "{{巡检指标表}}": build_metrics_table(summary),
        "{{延期修复巡检表}}": build_repair_table(summary),
        "{{修复成功明细}}": build_success_details(summary),
        "{{需关注}}": build_attention(summary),
        "{{HTML产物}}": relative_path(HTML_OUTPUT_PATH),
        "{{总JSON产物}}": relative_path(summary_json_path),
        "{{巡检总结产物}}": relative_path(output_path),
    }
    return fill_template(template, replacements)


def render_summary_markdown_to_file(
    summary: dict[str, Any],
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    template_path: Path = TEMPLATE_PATH,
    summary_json_path: Path = DEFAULT_SUMMARY_JSON,
) -> Path:
    content = render_summary_markdown(
        summary,
        template_path=template_path,
        output_path=output_path,
        summary_json_path=summary_json_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="用真实巡检 JSON 填充中文巡检总结模板。")
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON, help="总巡检 JSON 路径。")
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH, help="中文 Markdown 模板路径。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="填充后的 Markdown 输出路径。")
    parser.add_argument("--stdout", action="store_true", help="同时把填充后的内容输出到终端。")
    args = parser.parse_args()

    summary = read_json(args.summary_json)
    output_path = render_summary_markdown_to_file(
        summary,
        output_path=args.output,
        template_path=args.template,
        summary_json_path=args.summary_json,
    )

    if args.stdout:
        content = output_path.read_text(encoding="utf-8")
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
