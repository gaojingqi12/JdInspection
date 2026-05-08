import argparse
import json
import re
from pathlib import Path

METRIC_ORDER = [
    "延期上线率",
    "延期提测率",
    "双周交付率",
    "技术改造工时占比",
]

FIELD_WTD = "WTD（当前周期）"
FIELD_WTD_DELTA = "WTD（环比差值）"
FIELD_MTD = "MTD（当前周期）"
FIELD_MTD_DELTA = "MTD（同比差值）"
FIELD_YTD = "YTD（当前周期）"


def parse_args():
    parser = argparse.ArgumentParser(description="将巡检 JSON 渲染为 Joyclaw 报备文案。")
    parser.add_argument("--json", required=True, type=Path, help="输入 JSON 文件路径。")
    parser.add_argument(
        "--focus-department",
        default="支付生态研发部",
        help="优先突出的研发部门名称。",
    )
    parser.add_argument("--out", type=Path, help="可选，输出报备文案文件路径。")
    return parser.parse_args()


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_metric_name(title: str):
    match = re.match(r"^共创指标汇总-(.*?)-[^-]+$", title)
    return match.group(1) if match else title


def extract_department_name(title: str):
    match = re.match(r"^共创指标汇总-.*?-([^-]+)$", title)
    return match.group(1) if match else ""


def parse_percent(value):
    if not value:
        return None

    text = str(value).strip().replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def sort_metrics(items):
    order_map = {name: index for index, name in enumerate(METRIC_ORDER)}
    return sorted(items, key=lambda item: order_map.get(extract_metric_name(item[0]), len(order_map)))


def choose_metrics(data, focus_department: str):
    matched = {title: row for title, row in data.items() if focus_department in title}
    if matched:
        return matched, None

    actual_departments = sorted({extract_department_name(title) for title in data.keys() if extract_department_name(title)})
    actual_department = "、".join(actual_departments) if actual_departments else "未知部门"
    note = f"说明：当前 JSON 未直接命中“{focus_department}”，以下按实际提取到的“{actual_department}”指标生成。"
    return data, note


def build_summary(focus_department: str, rows):
    metric_map = {extract_metric_name(title): row for title, row in rows}
    summary_parts = [f"本次跟踪 {focus_department} 4 项核心指标"]

    delay_online = metric_map.get("延期上线率")
    delay_test = metric_map.get("延期提测率")
    delivery = metric_map.get("双周交付率")
    tech = metric_map.get("技术改造工时占比")

    delay_bits = []
    if delay_online:
        delay_bits.append(f"延期上线率 WTD {delay_online.get(FIELD_WTD, '-')}")
    if delay_test:
        delay_bits.append(f"延期提测率 WTD {delay_test.get(FIELD_WTD, '-')}")
    if delay_bits:
        summary_parts.append("，".join(delay_bits))

    if delivery:
        summary_parts.append(f"双周交付率 MTD {delivery.get(FIELD_MTD, '-')}")

    if tech:
        summary_parts.append(f"技术改造工时占比 MTD {tech.get(FIELD_MTD, '-')}")

    return "，".join(summary_parts) + "。"


def build_metric_lines(rows):
    lines = []
    for index, (title, row) in enumerate(rows, start=1):
        metric_name = extract_metric_name(title)
        lines.append(
            f"{index}. {metric_name}：WTD {row.get(FIELD_WTD, '-')}（环比 {row.get(FIELD_WTD_DELTA, '-')}），"
            f"MTD {row.get(FIELD_MTD, '-')}（同比 {row.get(FIELD_MTD_DELTA, '-')}），"
            f"YTD {row.get(FIELD_YTD, '-')}。"
        )
    return lines


def build_attention(rows):
    candidates = []
    for title, row in rows:
        metric_name = extract_metric_name(title)
        for field, label in ((FIELD_WTD_DELTA, "WTD 环比"), (FIELD_MTD_DELTA, "MTD 同比")):
            value = parse_percent(row.get(field))
            if value is None or value == 0:
                continue
            candidates.append((abs(value), f"{metric_name} {label} {row.get(field)}"))

    if not candidates:
        return "重点关注：本次指标波动整体不大，建议继续跟踪延期类指标与交付率变化。"

    top_changes = [text for _, text in sorted(candidates, reverse=True)[:3]]
    return "重点关注：" + "，".join(top_changes) + "。"


def render_report(data, focus_department: str):
    selected, note = choose_metrics(data, focus_department)
    rows = sort_metrics(selected.items())
    if not rows:
        raise ValueError("输入 JSON 中没有可用的指标数据。")

    first_row = rows[0][1]
    virtual_group = first_row.get("虚拟组")
    title = f"{focus_department}指标报备"
    if virtual_group and not note:
        title += f"（虚拟组：{virtual_group}）"
    elif virtual_group:
        title += f"（当前数据虚拟组：{virtual_group}）"

    parts = [title + "："]
    if note:
        parts.append(note)
    parts.append(build_summary(focus_department, rows))
    parts.extend(build_metric_lines(rows))
    parts.append(build_attention(rows))
    return "\n".join(parts)


def main():
    args = parse_args()
    data = load_json(args.json)
    report = render_report(data, args.focus_department)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")

    print(report)


if __name__ == "__main__":
    main()
