import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

URL = "https://ine.jd.com/portalDetail?location=%252Fdetail%253FportalUuid%253D20211122143031511247544858946828%2523c2a7e96635b0d71839c8bdfaaacb4b9f"

DEFAULT_DEPARTMENT_NAME = "支付方案研发部"

# 四个指标统一提取这些行，输出字段名按页面展示口径归一
TARGET_ROW_SPECS = [
    ("C3汇总", ["C3汇总"]),
    ("支付拓展研发部", ["支付拓展研发部"]),
    ("支付方案质量部", ["支付方案质量部"]),
    ("支付生态研发部", ["支付生态研发部"]),
    ("直挂C3", ["直挂C3", "支付方案直挂C3"]),
]

METRIC_PREFIXES = [
    "共创指标汇总-延期上线率",
    "共创指标汇总-延期提测率",
    "共创指标汇总-双周交付率",
    "共创指标汇总-技术改造工时占比",
]

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_JSON = OUT_DIR / "ine_metrics.json"
OUT_SCREENSHOT = OUT_DIR / "ine_metrics_page.png"


def parse_args():
    parser = argparse.ArgumentParser(description="抓取 INE 指标表中的部门数据。")
    parser.add_argument(
        "--department-name",
        default=DEFAULT_DEPARTMENT_NAME,
        help="指标标题中使用的研发部门名称，例如：支付方案研发部。",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=OUT_JSON,
        help="输出 JSON 文件路径。",
    )
    parser.add_argument(
        "--out-screenshot",
        type=Path,
        default=OUT_SCREENSHOT,
        help="输出截图文件路径。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="以无头模式启动浏览器。",
    )
    return parser.parse_args()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u3000", " ").replace("\xa0", " ")).strip()


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", clean_text(text))


def click_popup(scope):
    for txt in ["跳过", "暂不", "知道了", "我知道了", "关闭", "取消"]:
        try:
            loc = scope.get_by_text(txt, exact=True)
            if loc.count() > 0:
                loc.first.click(timeout=1000)
                return True
        except Exception:
            pass
    return False


def handle_popups(scope):
    for _ in range(3):
        if not click_popup(scope):
            break
        scope.wait_for_timeout(500)


def get_chart_scope(page):
    for _ in range(20):
        handle_popups(page)

        for frame in page.frames:
            try:
                if frame.locator(".chart-title").count() > 0:
                    return frame
            except Exception:
                pass

        page.wait_for_timeout(2000)

    raise RuntimeError("未找到图表所在 frame")


def get_card(scope, title: str):
    title_loc = scope.locator(".chart-title", has_text=title).first
    title_loc.wait_for(state="visible", timeout=20000)
    title_loc.scroll_into_view_if_needed()

    card = title_loc.locator(
        "xpath=ancestor::div[contains(@class,'element-contaienr') "
        "and contains(@class,'chart-card') "
        "and contains(@class,'table')][1]"
    )
    card.wait_for(state="visible", timeout=10000)
    return card


def try_get_card(scope, titles):
    last_error = None

    for title in titles:
        try:
            print(f"[INFO] 尝试定位指标: {title}")
            card = get_card(scope, title)
            return title, card
        except Exception as e:
            last_error = e
            print(f"[WARN] 未找到指标: {title}")

    raise RuntimeError(f"所有候选指标都未找到: {titles}") from last_error


def extract_headers(card):
    headers = [
        clean_text(x)
        for x in card.locator("thead th .header-cell .content").all_inner_texts()
    ]
    return [x for x in headers if x]


def extract_row(card, row_names):
    headers = extract_headers(card)
    rows = card.locator("tbody tr")
    targets = {compact_text(name) for name in row_names}

    for i in range(rows.count()):
        row = rows.nth(i)

        cells = [
            clean_text(x)
            for x in row.locator("td .column-default span").all_inner_texts()
        ]
        cells = [x for x in cells if x]

        if cells and compact_text(cells[0]) in targets:
            return dict(zip(headers, cells))

    raise RuntimeError(f"未找到目标行: {' / '.join(row_names)}")


def extract_rows(card, row_specs):
    data = {}

    for output_name, aliases in row_specs:
        try:
            row = extract_row(card, aliases)
            if isinstance(row, dict):
                row["虚拟组"] = output_name
            data[output_name] = row
        except Exception as e:
            print(f"[WARN] {e}")
            data[output_name] = None

    return data


def build_metric_groups(department_name: str):
    return {
        "延期上线率": [
            f"共创指标汇总-延期上线率-{department_name}",
        ],
        "延期提测率": [
            f"共创指标汇总-延期提测率-{department_name}",
        ],
        "双周交付率": [
            f"共创指标汇总-双周交付率-{department_name}",
        ],
        "技术改造工时占比": [
            f"共创指标汇总-技术改造工时占比-{department_name}",
            f"共创指标汇总-技改工时占比-{department_name}",
        ],
    }


def main():
    args = parse_args()

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_screenshot.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit("未安装 playwright，请先安装依赖后再执行抓取。") from exc

    metric_groups = build_metric_groups(args.department_name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page(viewport={"width": 1800, "height": 2200})

        try:
            print("[INFO] 打开页面...")
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                print("[WARN] networkidle 未等到，继续执行")

            scope = get_chart_scope(page)

            result = {
                "_meta": {
                    "inspection_date": date.today().isoformat(),
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "schedule": "每周五",
                }
            }

            for metric_name, candidate_titles in metric_groups.items():
                print(f"[INFO] 开始提取指标: {metric_name}")

                real_title, card = try_get_card(scope, candidate_titles)

                result[metric_name] = {
                    "title": real_title,
                    "rows": extract_rows(card, TARGET_ROW_SPECS),
                }

            with open(args.out_json, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            page.screenshot(path=str(args.out_screenshot), full_page=True)

            print("[INFO] 提取完成")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"[INFO] JSON: {args.out_json}")
            print(f"[INFO] 截图: {args.out_screenshot}")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
