import json
import re
import sys
from pathlib import Path
from datetime import date, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "out"
HISTORY_DIR = OUT_DIR / "history"

ROOT_DIR = next(path for path in Path(__file__).resolve().parents if (path / "inspection_config.py").exists())
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from inspection_config import metric_headers, metric_units, require_config


CONFIG = require_config("okr", "technical_refactor_working_hours")
URL = CONFIG["url"]
CARD_TITLE = CONFIG["card_title"]
DEPARTMENT_C3 = require_config("common", "department_c3")
INDICATOR_TYPE = CONFIG["indicator_type"]
INDICATOR_NAME = CONFIG["indicator_name"]
DATE_FILTER_LABEL = CONFIG["date_filter_label"]
DEPARTMENT_FILTER_LABEL = CONFIG["department_filter_label"]
QUERY_SCREENSHOT_PATH = CONFIG["query_screenshot"]
METRICS_CONFIG = CONFIG["metrics"]
METRIC_HEADERS = metric_headers(METRICS_CONFIG)
METRIC_UNITS = metric_units(METRICS_CONFIG)


def log(msg: str):
    print(f"[DEBUG] {msg}")


def save_debug_screenshot(page, out_dir: Path, name: str):
    path = out_dir / name
    page.screenshot(path=str(path), full_page=True)
    log(f"已保存截图: {path}")


def dump_frames(page):
    log(f"当前标题: {page.title()}")
    log(f"当前URL: {page.url}")
    log(f"frame 数量: {len(page.frames)}")
    for idx, f in enumerate(page.frames):
        log(f"frame[{idx}] url = {f.url}")


def get_menu_frame(page, timeout_ms=22000):
    import time
    start = time.time()

    while (time.time() - start) * 1000 < timeout_ms:
        for idx, f in enumerate(page.frames):
            try:
                url = f.url or ""
                log(f"轮询菜单 frame[{idx}] url = {url}")
                if "bi.jd.com/detail" in url:
                    log(f"命中菜单 frame[{idx}]")
                    return f
            except Exception as e:
                log(f"读取菜单 frame[{idx}] url 失败: {e}")

        page.wait_for_timeout(800)

    raise Exception("没找到左侧菜单所在 frame")


def collapse_sidebar(page):
    menu_frame = get_menu_frame(page)

    btn = menu_frame.locator(".list-collapse").first
    btn.wait_for(state="visible", timeout=12000)
    btn.click()
    page.wait_for_timeout(1500)

    log("已点击收起侧边栏")


def get_dashboard_frame(page, timeout_ms=45000):
    import time
    start = time.time()

    while (time.time() - start) * 1000 < timeout_ms:
        for idx, f in enumerate(page.frames):
            try:
                url = f.url or ""
                log(f"轮询 frame[{idx}] url = {url}")
                if "jddbi.jd.com/export/dashboard" in url:
                    log(f"命中 dashboard frame[{idx}]")
                    return f
            except Exception as e:
                log(f"读取 frame[{idx}] url 失败: {e}")

        page.wait_for_timeout(1500)

    raise Exception("等待超时：没找到目标 dashboard iframe")


def locate_target_chart(frame):
    title = frame.locator(".chart-title", has_text=CARD_TITLE).first
    title.wait_for(state="visible", timeout=22000)
    title.scroll_into_view_if_needed()

    card = title.locator("xpath=ancestor::div[contains(@class,'element-contaienr')]").first
    card.wait_for(state="visible", timeout=15000)
    return title, card


def hover_card(page, card):
    candidates = [
        card,
        card.locator(".element-contaienr").first,
        card.locator(".preview-set").first,
        card.locator(".chart-title").first,
        card.locator(".chart").first,
    ]

    for idx, loc in enumerate(candidates):
        try:
            if loc.count() > 0:
                loc.scroll_into_view_if_needed()
                loc.hover()
                page.wait_for_timeout(1800)
                log(f"hover 成功，第 {idx} 个候选")
                return
        except Exception as e:
            log(f"hover 失败，第 {idx} 个候选, error={e}")

    raise Exception("所有 hover 候选都失败")


def click_chart_filter_button(page, card):
    hover_card(page, card)

    btn = card.locator(
        ".preview-set > .preview-set-setting-button > .card-toolbar > div:nth-child(7) > .el-tooltip"
    ).first

    btn.wait_for(state="visible", timeout=12000)
    btn.click()
    log("已点击图表筛选按钮")


def get_last_friday_and_today():
    today = date.today()
    days_since_friday = (today.weekday() - 4) % 7
    if days_since_friday == 0:
        days_since_friday = 7
    last_friday = today - timedelta(days=days_since_friday)
    return last_friday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def get_visible_filter_panel(frame):
    frame.page.wait_for_timeout(1500)

    panels = frame.locator(".single-chart-filter")
    count = panels.count()
    log(f"匹配到 single-chart-filter 数量: {count}")

    for i in range(count):
        panel = panels.nth(i)
        try:
            visible = panel.is_visible()
            log(f"panel[{i}] visible = {visible}")
            if visible:
                return panel
        except Exception as e:
            log(f"panel[{i}] 检查失败: {e}")

    raise Exception(f"没找到可见的 single-chart-filter，当前共匹配到 {count} 个")


def find_filter_item(panel, label_text: str):
    items = panel.locator(".filter-item")
    count = items.count()

    for i in range(count):
        item = items.nth(i)
        try:
            label = item.locator(".filter-item-label").inner_text().strip()
            if label == label_text:
                return item
        except Exception:
            pass

    raise Exception(f"没找到筛选项: {label_text}")


def fill_report_date_range(frame):
    start_date, end_date = get_last_friday_and_today()
    log(f"开始时间: {start_date}, 结束时间: {end_date}")

    panel = get_visible_filter_panel(frame)
    target_item = find_filter_item(panel, DATE_FILTER_LABEL)

    inputs = target_item.locator("input.el-input__inner")
    input_count = inputs.count()
    log(f"{DATE_FILTER_LABEL} input 数量: {input_count}")

    if input_count < 2:
        raise Exception(f"{DATE_FILTER_LABEL} 输入框数量异常: {input_count}")

    inputs.nth(0).scroll_into_view_if_needed()
    inputs.nth(0).click()
    inputs.nth(0).fill(start_date)
    frame.page.keyboard.press("Enter")
    frame.page.wait_for_timeout(800)

    inputs.nth(1).scroll_into_view_if_needed()
    inputs.nth(1).click()
    inputs.nth(1).fill(end_date)
    frame.page.keyboard.press("Enter")
    frame.page.wait_for_timeout(1200)

    log(f"已填写：{DATE_FILTER_LABEL}")
    return start_date, end_date


def select_department_c3(frame, department_name=DEPARTMENT_C3):
    panel = get_visible_filter_panel(frame)
    target_item = find_filter_item(panel, DEPARTMENT_FILTER_LABEL)

    dropdown_btn = target_item.locator("button.qd-button").first
    dropdown_btn.wait_for(state="visible", timeout=7500)
    dropdown_btn.click()
    frame.page.wait_for_timeout(1500)
    log(f"已点开：{DEPARTMENT_FILTER_LABEL} 下拉")

    search_box = None
    search_candidates = [
        '.el-popper input.el-input__inner[placeholder="请输入..."]',
        '.el-popper input.el-input__inner[placeholder*="请输入"]',
        'input.el-input__inner[placeholder="请输入..."]',
        'input.el-input__inner[placeholder*="请输入"]',
    ]

    for sel in search_candidates:
        try:
            locs = frame.locator(sel)
            for i in range(locs.count()):
                inp = locs.nth(i)
                if inp.is_visible():
                    search_box = inp
                    log(f"命中搜索框 selector: {sel}, index={i}")
                    break
            if search_box is not None:
                break
        except Exception as e:
            log(f"搜索框候选失败: {sel}, error={e}")

    if search_box is None:
        raise Exception(f"没找到{DEPARTMENT_FILTER_LABEL} 下拉弹层里的搜索框")

    search_box.click()
    search_box.fill(department_name)
    frame.page.wait_for_timeout(1500)
    log(f"已输入搜索词: {department_name}")

    option = None
    option_candidates = [
        frame.locator(".el-popper").get_by_text(department_name, exact=True),
        frame.get_by_text(department_name, exact=True),
    ]

    for cand in option_candidates:
        try:
            for i in range(cand.count()):
                opt = cand.nth(i)
                if opt.is_visible():
                    option = opt
                    break
            if option is not None:
                break
        except Exception as e:
            log(f"选项候选失败: {e}")

    if option is None:
        raise Exception(f"没找到可见选项: {department_name}")

    option.click()
    frame.page.wait_for_timeout(1200)
    log(f"已选择：{DEPARTMENT_FILTER_LABEL} = {department_name}")


def click_query_button(frame):
    panel = get_visible_filter_panel(frame)
    query_btn = panel.locator(".serach-btn button").first
    query_btn.wait_for(state="visible", timeout=7500)
    query_btn.click()
    frame.page.wait_for_timeout(7500)
    log("已点击：查询")


def wait_table_loaded(card):
    table = card.locator(".table-render").first
    table.wait_for(state="visible", timeout=22000)

    loading = card.locator(".loading")
    if loading.count() > 0:
        try:
            loading.first.wait_for(state="hidden", timeout=22000)
        except Exception:
            pass

    body_rows = card.locator(".vxe-table--body tbody tr")
    body_rows.first.wait_for(state="visible", timeout=22000)
    log("表格已加载完成")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_percent(text: str) -> float:
    normalized = normalize_text(text).replace("%", "").replace(",", "")
    return round(float(normalized), 2)


def extract_tech_hours_metrics(card) -> dict:
    wait_table_loaded(card)

    headers = card.locator(".vxe-table--header th")
    header_count = headers.count()
    log(f"表头数量: {header_count}")

    header_map = {}
    for i in range(header_count):
        th = headers.nth(i)
        title = normalize_text(th.inner_text())
        header_map[title] = i
        log(f"header[{i}] = {title}")

    required_headers = list(METRIC_HEADERS.values())
    for name in required_headers:
        if name not in header_map:
            raise Exception(f"表头中未找到字段: {name}")

    first_row = card.locator(".vxe-table--body tbody tr").first
    first_row.wait_for(state="visible", timeout=15000)

    cells = first_row.locator("td")
    cell_count = cells.count()
    log(f"首行单元格数量: {cell_count}")

    def get_cell_text_by_header(header_name: str) -> str:
        idx = header_map[header_name]
        text = normalize_text(cells.nth(idx).inner_text())
        log(f"{header_name} = {text}")
        return text

    metrics = {}
    for item in METRICS_CONFIG:
        key = item["key"]
        raw = get_cell_text_by_header(METRIC_HEADERS[key])
        parser = item.get("parser")
        if parser == "percent":
            metrics[key] = parse_percent(raw)
        elif parser == "int":
            metrics[key] = int(normalize_text(raw).replace(",", ""))
        else:
            metrics[key] = float(normalize_text(raw).replace(",", ""))

    return metrics


def build_daily_payload(start_date: str, end_date: str, metrics: dict) -> dict:
    return {
        "date": date.today().strftime("%Y-%m-%d"),
        "indicator_type": INDICATOR_TYPE,
        "indicator_name": INDICATOR_NAME,
        "department_c3": DEPARTMENT_C3,
        "status": "success",
        "filters": {
            "date_range": f"{start_date} ~ {end_date}",
            "department_c3": DEPARTMENT_C3,
        },
        "metrics": metrics,
        "unit": METRIC_UNITS,
        "source": {
            "query_screenshot": QUERY_SCREENSHOT_PATH,
            "table_title": CARD_TITLE,
        },
        "source_mode": "table_dom",
        "notes": "查询后直接从配置指定表头的第一行提取关注指标。",
    }


def write_daily_history_json(payload: dict) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{payload['date']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"已写入当日巡检 JSON: {path}")
    return path


def write_failed_history_json(start_date: str | None, end_date: str | None, error_message: str) -> Path:
    payload = {
        "date": date.today().strftime("%Y-%m-%d"),
        "indicator_type": INDICATOR_TYPE,
        "indicator_name": INDICATOR_NAME,
        "department_c3": DEPARTMENT_C3,
        "status": "failed",
        "filters": {
            "date_range": f"{start_date} ~ {end_date}" if start_date and end_date else "",
            "department_c3": DEPARTMENT_C3,
        },
        "metrics": {item["key"]: None for item in METRICS_CONFIG},
        "unit": METRIC_UNITS,
        "error": error_message,
        "source": {
            "query_screenshot": QUERY_SCREENSHOT_PATH,
            "table_title": CARD_TITLE,
        },
        "source_mode": "table_dom",
    }
    return write_daily_history_json(payload)


def main():
    out_dir = OUT_DIR
    out_dir.mkdir(exist_ok=True)

    start_date = None
    end_date = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        try:
            log("开始打开页面")
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7500)
            page.wait_for_load_state("networkidle", timeout=22000)
            page.wait_for_timeout(4500)

            collapse_sidebar(page)

            save_debug_screenshot(page, out_dir, "00_home.png")
            dump_frames(page)

            dashboard_frame = get_dashboard_frame(page)
            log(f"dashboard frame: {dashboard_frame.url}")

            title, card = locate_target_chart(dashboard_frame)
            log(f"已定位到目标标题: {normalize_text(title.inner_text())}")

            card.screenshot(path=str(out_dir / "01_target_card.png"))
            log("已保存目标卡片截图: out/01_target_card.png")

            click_chart_filter_button(page, card)
            save_debug_screenshot(page, out_dir, "02_after_click_filter.png")

            start_date, end_date = fill_report_date_range(dashboard_frame)
            save_debug_screenshot(page, out_dir, "03_after_fill_date_range.png")

            select_department_c3(dashboard_frame, DEPARTMENT_C3)
            save_debug_screenshot(page, out_dir, "04_after_select_c3.png")

            click_query_button(dashboard_frame)
            save_debug_screenshot(page, out_dir, "05_after_query.png")

            metrics = extract_tech_hours_metrics(card)
            payload = build_daily_payload(start_date, end_date, metrics)
            json_path = write_daily_history_json(payload)

            log(f"技术改造工时占比巡检完成，时间范围：{start_date} ~ {end_date}")
            log(f"提取结果: {json.dumps(metrics, ensure_ascii=False)}")
            log(f"JSON 已输出到: {json_path}")

        except PlaywrightTimeoutError as e:
            log(f"Playwright 超时: {e}")
            save_debug_screenshot(page, out_dir, "timeout_error.png")
            try:
                write_failed_history_json(start_date, end_date, f"Playwright 超时: {e}")
            except Exception as json_exc:
                log(f"写入失败 JSON 失败: {json_exc}")
            raise
        except Exception as e:
            log(f"执行失败: {e}")
            save_debug_screenshot(page, out_dir, "general_error.png")
            try:
                write_failed_history_json(start_date, end_date, str(e))
            except Exception as json_exc:
                log(f"写入失败 JSON 失败: {json_exc}")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
