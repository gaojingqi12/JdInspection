import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "out"
HISTORY_DIR = OUT_DIR / "history"

ROOT_DIR = next(path for path in Path(__file__).resolve().parents if (path / "inspection_config.py").exists())
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from inspection_config import metric_units, require_config


CONFIG = require_config("okr", "bi_weekly_delivery_rate")
URL = CONFIG["url"]
DEPARTMENT_C3 = require_config("common", "department_c3")
INDICATOR_TYPE = CONFIG["indicator_type"]
INDICATOR_NAME = CONFIG["indicator_name"]
METRIC_KEY = CONFIG["metric_key"]
TOOLTIP_LABEL = CONFIG["tooltip_label"]
SNAPSHOT_FILTER_LABEL = CONFIG["snapshot_filter_label"]
DATE_FILTER_LABEL = CONFIG["date_filter_label"]
DEPARTMENT_FILTER_LABEL = CONFIG["department_filter_label"]
QUERY_SCREENSHOT_PATH = CONFIG["query_screenshot"]
METRIC_UNITS = metric_units(CONFIG["metrics"])


def log(msg: str):
    print(f"[DEBUG] {msg}")


def save_debug_screenshot(page, out_dir: Path, name: str):
    path = out_dir / name
    page.screenshot(path=str(path), full_page=True)
    log(f"已保存截图: {path}")


def parse_biweekly_rate(text: str):
    pattern = rf"{re.escape(TOOLTIP_LABEL)}\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*%"
    match = re.search(pattern, text or "")
    if not match:
        return None
    return float(match.group(1))


def visible_tooltip_text(frame) -> str:
    return frame.evaluate(
        """
        (label) => {
          const nodes = Array.from(document.querySelectorAll('body *'));
          const candidates = [];
          for (const node of nodes) {
            const text = (node.innerText || node.textContent || '').trim();
            if (!text.includes(label)) continue;
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            if (style.display === 'none') continue;
            if (style.visibility === 'hidden') continue;
            if (Number(style.opacity || 1) <= 0.05) continue;
            if (rect.width <= 0 || rect.height <= 0) continue;
            candidates.push(text);
          }
          return candidates.join('\\n');
        }
        """,
        TOOLTIP_LABEL,
    )


def extract_biweekly_rate_from_tooltip(frame):
    canvases = frame.locator("canvas[data-zr-dom-id], canvas")
    count = canvases.count()
    log(f"匹配到 canvas 数量: {count}")

    positions = [
        (0.50, 0.50),
        (0.25, 0.50),
        (0.75, 0.50),
        (0.15, 0.50),
        (0.85, 0.50),
        (0.50, 0.35),
        (0.50, 0.65),
        (0.25, 0.35),
        (0.75, 0.65),
    ]

    for index in range(count):
        canvas = canvases.nth(index)
        try:
            box = canvas.bounding_box()
        except Exception as exc:
            log(f"读取 canvas[{index}] 边界失败: {exc}")
            continue

        if not box or box["width"] < 120 or box["height"] < 80:
            continue

        log(f"尝试 hover canvas[{index}] size={box['width']:.0f}x{box['height']:.0f}")
        for x_ratio, y_ratio in positions:
            try:
                canvas.hover(
                    position={
                        "x": box["width"] * x_ratio,
                        "y": box["height"] * y_ratio,
                    },
                    timeout=3000,
                )
                frame.page.wait_for_timeout(450)
                tooltip_text = visible_tooltip_text(frame)
                value = parse_biweekly_rate(tooltip_text)
                if value is not None:
                    log(f"从 tooltip 提取到双周交付率: {value}%")
                    return value
            except Exception as exc:
                log(f"hover canvas[{index}] 失败: {exc}")

    return None


def write_daily_history(
    value,
    start_date: str,
    end_date: str,
    *,
    status: str,
    source_mode: str,
    error: str = "",
):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    day = date.today().strftime("%Y-%m-%d")
    payload = {
        "date": day,
        "indicator_type": INDICATOR_TYPE,
        "indicator_name": INDICATOR_NAME,
        "department_c3": DEPARTMENT_C3,
        "status": status,
        "filters": {
            "date_range": f"{start_date} ~ {end_date}",
            "department_c3": DEPARTMENT_C3,
        },
        "metrics": {
            METRIC_KEY: value,
        },
        "unit": METRIC_UNITS,
        "source": {
            "query_screenshot": QUERY_SCREENSHOT_PATH,
        },
        "source_mode": source_mode,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if error:
        payload["error"] = error

    out_file = HISTORY_DIR / f"{day}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"已写入每日 JSON: {out_file}")


def dump_frames(page):
    log(f"当前标题: {page.title()}")
    log(f"当前URL: {page.url}")
    log(f"frame 数量: {len(page.frames)}")
    for idx, frame in enumerate(page.frames):
        try:
            log(f"frame[{idx}] url = {frame.url}")
        except Exception as exc:
            log(f"读取 frame[{idx}] url 失败: {exc}")


def get_menu_frame(page, timeout_ms=22000):
    import time

    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        for idx, frame in enumerate(page.frames):
            try:
                url = frame.url or ""
                if "bi.jd.com/detail" in url:
                    log(f"命中菜单 frame[{idx}]")
                    return frame
            except Exception as exc:
                log(f"读取菜单 frame[{idx}] url 失败: {exc}")
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
        for idx, frame in enumerate(page.frames):
            try:
                url = frame.url or ""
                log(f"轮询 frame[{idx}] url = {url}")
                if "jddbi.jd.com/export/dashboard" in url:
                    log(f"命中 dashboard frame[{idx}]")
                    return frame
            except Exception as exc:
                log(f"读取 frame[{idx}] url 失败: {exc}")
        page.wait_for_timeout(1500)

    raise Exception("等待超时：没找到目标 dashboard iframe")


def get_last_friday_and_today():
    today = date.today()
    days_since_friday = (today.weekday() - 4) % 7
    if days_since_friday == 0:
        days_since_friday = 7
    last_friday = today - timedelta(days=days_since_friday)
    return last_friday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def get_visible_filter_panel(frame):
    frame.page.wait_for_timeout(1500)

    panels = frame.locator(".filter-list")
    count = panels.count()
    log(f"匹配到 filter-list 数量: {count}")

    for i in range(count):
        panel = panels.nth(i)
        try:
            if panel.is_visible():
                log(f"命中可见筛选面板 panel[{i}]")
                return panel
        except Exception as exc:
            log(f"panel[{i}] 检查失败: {exc}")

    raise Exception(f"没找到可见的 filter-list，当前共匹配到 {count} 个")


def find_filter_item(panel, label_text: str):
    items = panel.locator(".filter-item")
    count = items.count()

    for i in range(count):
        item = items.nth(i)
        try:
            label = item.locator("span").first.inner_text().strip()
            label = label.replace("：", "").replace(":", "").strip()
            if label_text in label:
                return item
        except Exception:
            pass

    raise Exception(f"没找到筛选项: {label_text}")


def set_snapshot_latest_day(frame):
    panel = get_visible_filter_panel(frame)
    item = find_filter_item(panel, SNAPSHOT_FILTER_LABEL)
    input_box = item.locator("input.el-input__inner").first
    input_box.wait_for(state="visible", timeout=7500)
    log(f"快照日期当前值: {input_box.input_value()}")
    log(f"已保留：{SNAPSHOT_FILTER_LABEL} = 最新日")


def fill_complete_date_range(frame):
    start_date, end_date = get_last_friday_and_today()
    log(f"{DATE_FILTER_LABEL}范围: {start_date} ~ {end_date}")

    panel = get_visible_filter_panel(frame)
    item = find_filter_item(panel, DATE_FILTER_LABEL)

    inputs = item.locator("input.el-input__inner")
    count = inputs.count()
    log(f"{DATE_FILTER_LABEL} input 数量: {count}")

    if count < 2:
        raise Exception(f"{DATE_FILTER_LABEL} 输入框数量异常: {count}")

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


def get_visible_popper(frame):
    poppers = frame.locator(".el-popper")
    count = poppers.count()
    for i in range(count):
        popper = poppers.nth(i)
        try:
            if popper.is_visible():
                log(f"命中可见弹层 index={i}")
                return popper
        except Exception:
            pass
    raise Exception("没找到可见的下拉弹层 el-popper")


def open_dropdown(item):
    select_box = item.locator(".el-select").first
    select_box.wait_for(state="visible", timeout=7500)
    select_box.click()
    item.page.wait_for_timeout(1200)


def select_department_c3(frame, department_name=DEPARTMENT_C3):
    panel = get_visible_filter_panel(frame)
    item = find_filter_item(panel, DEPARTMENT_FILTER_LABEL)

    open_dropdown(item)
    log(f"已点开：{DEPARTMENT_FILTER_LABEL} 下拉")

    popper = get_visible_popper(frame)

    search_box = None
    candidates = popper.locator('input[placeholder*="请输入"]')
    for i in range(candidates.count()):
        inp = candidates.nth(i)
        try:
            if inp.is_visible():
                search_box = inp
                break
        except Exception:
            pass

    if search_box:
        search_box.click()
        search_box.fill(department_name)
        frame.page.wait_for_timeout(1200)
        log(f"已输入搜索词: {department_name}")

    option = popper.get_by_text(department_name, exact=True).first
    option.wait_for(state="visible", timeout=22000)
    option.click()
    frame.page.wait_for_timeout(3000)

    log(f"已选择：{DEPARTMENT_FILTER_LABEL} = {department_name}")
    frame.page.keyboard.press("Escape")
    frame.page.wait_for_timeout(800)


def click_query_button(frame):
    query_btn = frame.get_by_text("查询", exact=True).first
    query_btn.wait_for(state="visible", timeout=7500)
    query_btn.click()
    frame.page.wait_for_timeout(7500)
    log("已点击：查询")
    frame.page.wait_for_timeout(30000)


def main():
    out_dir = OUT_DIR
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        try:
            log("开始打开页面")
            page.goto(URL, wait_until="domcontentloaded", timeout=180000)
            page.wait_for_timeout(7500)
            page.wait_for_load_state("domcontentloaded", timeout=90000)
            page.wait_for_load_state("networkidle", timeout=90000)
            page.wait_for_timeout(4500)

            collapse_sidebar(page)

            save_debug_screenshot(page, out_dir, "00_home.png")
            dump_frames(page)

            dashboard_frame = get_dashboard_frame(page)
            log(f"dashboard frame: {dashboard_frame.url}")

            set_snapshot_latest_day(dashboard_frame)
            start_date, end_date = fill_complete_date_range(dashboard_frame)
            save_debug_screenshot(page, out_dir, "01_after_fill_date.png")

            select_department_c3(dashboard_frame, DEPARTMENT_C3)
            save_debug_screenshot(page, out_dir, "02_after_select_c3.png")

            click_query_button(dashboard_frame)
            save_debug_screenshot(page, out_dir, "03_after_query.png")

            value = extract_biweekly_rate_from_tooltip(dashboard_frame)
            if value is None:
                write_daily_history(
                    None,
                    start_date,
                    end_date,
                    status="failed",
                    source_mode="echarts_tooltip",
                    error="未能从图表 tooltip 提取双周交付率",
                )
                raise Exception("未能从图表 tooltip 提取双周交付率")

            write_daily_history(
                value,
                start_date,
                end_date,
                status="success",
                source_mode="echarts_tooltip",
            )

            log(f"巡检完成，{DATE_FILTER_LABEL}范围：{start_date} ~ {end_date}")

        except PlaywrightTimeoutError as exc:
            log(f"Playwright 超时: {exc}")
            save_debug_screenshot(page, out_dir, "timeout_error.png")
            raise
        except Exception as exc:
            log(f"执行失败: {exc}")
            save_debug_screenshot(page, out_dir, "general_error.png")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
