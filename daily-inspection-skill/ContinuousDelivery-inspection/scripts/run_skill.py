import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(PROJECT_DIR, "out")
os.makedirs(OUT_DIR, exist_ok=True)

ROOT_DIR = next(path for path in Path(__file__).resolve().parents if (path / "inspection_config.py").exists())
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from inspection_config import metric_units, require_config


CONFIG = require_config("continuous_delivery")
URL = CONFIG["url"]
INDICATOR_TYPE = CONFIG["indicator_type"]
INDICATOR_NAME = CONFIG["indicator_name"]
MENU_LABEL = CONFIG["menu_label"]
DEPARTMENT_FILTER_LABEL = CONFIG["department_filter_label"]
DEPARTMENT_LEVELS = CONFIG["department_levels"]
TARGET_METRIC_CONFIG = CONFIG["metrics"]
TARGET_METRICS = [item["title"] for item in TARGET_METRIC_CONFIG]
METRIC_KEY_BY_TITLE = {item["title"]: item["key"] for item in TARGET_METRIC_CONFIG}
METRIC_UNITS = metric_units(TARGET_METRIC_CONFIG)


def log(msg: str):
    print(f"[DEBUG] {msg}")


def clear_out_dir():
    for filename in os.listdir(OUT_DIR):
        file_path = os.path.join(OUT_DIR, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                log(f"删除旧文件失败: {file_path}, error={e}")


def save_final_locator_shot(locator, name="final_three_cards"):
    clear_out_dir()
    path = os.path.join(OUT_DIR, f"{name}.png")
    locator.screenshot(path=path)
    log(f"最终截图已保存: {path}")
    return path


def wait_page_stable(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=22000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    page.wait_for_timeout(3500)


def handle_guide_popup(page):
    try:
        log("检查是否存在引导弹窗")
        page.wait_for_timeout(2200)

        skip_btn = page.get_by_text("跳过", exact=True)
        if skip_btn.count() > 0 and skip_btn.first.is_visible():
            skip_btn.first.click(timeout=4500)
            log("已点击：跳过")
            page.wait_for_timeout(1500)
            return

        finish_btn = page.get_by_text("完成", exact=True)
        if finish_btn.count() > 0 and finish_btn.first.is_visible():
            finish_btn.first.click(timeout=4500)
            log("已点击：完成")
            page.wait_for_timeout(1500)
            return

        log("未发现引导弹窗")

    except Exception as e:
        log(f"处理引导弹窗异常（忽略）: {e}")


def click_delivery_detail_menu(page):
    log(f"开始点击左侧菜单：{MENU_LABEL}")
    page.wait_for_timeout(3000)

    candidates = [
        page.get_by_text(MENU_LABEL, exact=True),
        page.locator(f"text={MENU_LABEL}"),
        page.locator(f"span:has-text('{MENU_LABEL}')"),
        page.locator(f"div:has-text('{MENU_LABEL}')"),
        page.locator(f"li:has-text('{MENU_LABEL}')"),
        page.locator(f"a:has-text('{MENU_LABEL}')"),
    ]

    for i, locator in enumerate(candidates, start=1):
        try:
            if locator.count() == 0:
                continue

            target = locator.first
            try:
                target.scroll_into_view_if_needed(timeout=4500)
            except Exception:
                pass

            page.wait_for_timeout(800)

            if target.is_visible():
                target.click(timeout=7500)
                log(f"已点击：{MENU_LABEL}（方案{i}）")
                page.wait_for_timeout(3500)
                return

        except Exception as e:
            log(f"菜单定位方案{i}失败: {e}")

    raise Exception(f"未找到或无法点击左侧菜单：{MENU_LABEL}")


def get_department_cascade(page):
    li = page.locator("li").filter(
        has=page.locator(f"span.name:has-text('{DEPARTMENT_FILTER_LABEL}')")
    ).first

    if li.count() == 0:
        raise Exception(f"未找到“{DEPARTMENT_FILTER_LABEL}”区域")

    cascade = li.locator("div.query-cascade").first
    if cascade.count() == 0:
        raise Exception(f"未找到“{DEPARTMENT_FILTER_LABEL}”的级联控件")

    return cascade


def page_wait(page, ms=500):
    page.wait_for_timeout(int(ms * 1.5))


def clear_select_value(page, select_box):
    try:
        close_icons = select_box.locator("i.el-tag__close")
        while close_icons.count() > 0:
            try:
                close_icons.nth(0).click(timeout=1500)
                page_wait(page, 300)
            except Exception:
                break
    except Exception:
        pass


def get_select_input(select_box):
    candidates = [
        select_box.locator("input.el-select__input"),
        select_box.locator("input.el-input__inner"),
    ]

    for locator in candidates:
        try:
            if locator.count() > 0:
                return locator.first
        except Exception:
            pass

    raise Exception("未找到选择框输入元素")


def open_and_type_select(page, select_box, value, level_idx):
    try:
        select_box.scroll_into_view_if_needed(timeout=4500)
    except Exception:
        pass

    input_box = get_select_input(select_box)
    input_box.click(timeout=7500)
    page_wait(page, 300)

    try:
        select_box.click(timeout=3000)
        page_wait(page, 300)
    except Exception:
        pass

    input_box = get_select_input(select_box)

    try:
        input_box.fill("")
    except Exception:
        input_box.click()
        try:
            page.keyboard.press("Meta+A")
        except Exception:
            page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")

    page_wait(page, 200)

    try:
        input_box.fill(value)
    except Exception:
        input_box.click()
        page.keyboard.type(value, delay=80)

    log(f"第{level_idx}级已输入：{value}")
    page_wait(page, 1000)


def click_dropdown_option(page, text, level_idx):
    candidates = [
        page.locator(".el-select-dropdown:visible .el-select-dropdown__item span").filter(has_text=text),
        page.locator(".el-select-dropdown:visible .el-select-dropdown__item").filter(has_text=text),
        page.locator(".el-select-dropdown__item span").filter(has_text=text),
        page.locator(".el-select-dropdown__item").filter(has_text=text),
    ]

    for i, locator in enumerate(candidates, start=1):
        try:
            if locator.count() == 0:
                continue

            option = locator.first
            try:
                option.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            option.click(timeout=7500)
            log(f"已点击第{level_idx}级下拉项：{text}（方案{i}）")
            page_wait(page, 1200)
            return
        except Exception as e:
            log(f"第{level_idx}级点击下拉项失败（方案{i}）: {e}")

    raise Exception(f"未找到第{level_idx}级下拉选项：{text}")


def input_and_select_level(page, select_box, value, level_idx):
    log(f"开始处理第{level_idx}级，目标值：{value}")
    clear_select_value(page, select_box)
    page_wait(page, 300)
    open_and_type_select(page, select_box, value, level_idx)
    click_dropdown_option(page, value, level_idx)


def select_department_levels(page):
    log("开始重新输入交付负责人部门 1~4 级")

    cascade = get_department_cascade(page)
    selects = cascade.locator("div.el-select")
    select_count = selects.count()
    log(f"级联下拉框数量: {select_count}")

    if select_count < 5:
        raise Exception(f"级联下拉框数量不足，实际数量: {select_count}")

    for idx, value in enumerate(DEPARTMENT_LEVELS, start=1):
        input_and_select_level(page, selects.nth(idx - 1), value, idx)

    log("第5级保持不动")


def click_query_button(page):
    log("开始点击查询按钮")

    query_group = page.locator("div.queryGroup.control").first
    candidates = [
        query_group.get_by_role("button", name="查询"),
        query_group.locator("button:has-text('查询')"),
        page.get_by_role("button", name="查询"),
        page.locator("button:has-text('查询')"),
    ]

    for i, locator in enumerate(candidates, start=1):
        try:
            if locator.count() == 0:
                continue

            btn = locator.first
            try:
                btn.scroll_into_view_if_needed(timeout=4500)
            except Exception:
                pass

            page.wait_for_timeout(500)
            btn.click(timeout=7500)
            log(f"已点击查询按钮（方案{i}）")
            page.wait_for_timeout(6000)
            return

        except Exception as e:
            log(f"查询按钮方案{i}失败: {e}")

    raise Exception("未找到或无法点击查询按钮")


def locate_three_cards_row(page):
    log("开始定位三个指标卡片")

    keywords = TARGET_METRICS

    first_card_title = page.get_by_text(keywords[0], exact=False).first
    first_card_title.scroll_into_view_if_needed(timeout=7500)
    page.wait_for_timeout(2200)

    candidates = [
        page.locator("div").filter(has=page.get_by_text(keywords[0], exact=False))
                           .filter(has=page.get_by_text(keywords[1], exact=False))
                           .filter(has=page.get_by_text(keywords[2], exact=False)),
        page.locator("section").filter(has=page.get_by_text(keywords[0], exact=False))
                               .filter(has=page.get_by_text(keywords[1], exact=False))
                               .filter(has=page.get_by_text(keywords[2], exact=False)),
    ]

    for i, locator in enumerate(candidates, start=1):
        try:
            count = locator.count()
            log(f"三卡片公共容器方案{i}，匹配数量: {count}")
            if count == 0:
                continue

            target = locator.first
            target.scroll_into_view_if_needed(timeout=4500)
            page.wait_for_timeout(1500)
            return target
        except Exception as e:
            log(f"三卡片公共容器方案{i}失败: {e}")

    fallback = page.locator("body")
    return fallback


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_metric_value(raw: str):
    raw = normalize_text(raw).replace(",", "")
    if raw.endswith("%"):
        percent = raw[:-1].strip()
        if re.fullmatch(r"-?\d+", percent):
            return int(percent)
        if re.fullmatch(r"-?\d+\.\d+", percent):
            return float(percent)
        return percent
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def extract_three_metrics(page) -> dict:
    log("开始提取三个指标卡片的数据")

    cards = page.locator(".item-card__content")
    count = cards.count()
    log(f"匹配到 item-card__content 数量: {count}")

    result_map = {}

    for i in range(count):
        card = cards.nth(i)
        try:
            if not card.is_visible():
                continue

            title_el = card.locator(".item-card__title").first
            value_el = card.locator(".item-card__display span").first

            if title_el.count() == 0 or value_el.count() == 0:
                continue

            title = normalize_text(title_el.inner_text())
            value = normalize_text(value_el.inner_text())

            if not title:
                continue

            log(f"card[{i}] title={title}, value={value}")
            result_map[title] = value
        except Exception as e:
            log(f"提取 card[{i}] 失败: {e}")

    missing = [name for name in TARGET_METRICS if name not in result_map]
    if missing:
        raise Exception(f"未提取到以下指标卡片: {missing}")

    return {
        METRIC_KEY_BY_TITLE[title]: parse_metric_value(result_map[title])
        for title in TARGET_METRICS
    }


def build_daily_payload(metrics: dict, final_screenshot_path: str) -> dict:
    return {
        "date": date.today().strftime("%Y-%m-%d"),
        "indicator_type": INDICATOR_TYPE,
        "indicator_name": INDICATOR_NAME,
        "department_c3": DEPARTMENT_LEVELS[-1],
        "status": "success",
        "filters": {
            **{f"department_level_{index}": value for index, value in enumerate(DEPARTMENT_LEVELS, start=1)},
        },
        "metrics": metrics,
        "unit": METRIC_UNITS,
        "source": {
            "query_screenshot": os.path.relpath(final_screenshot_path, PROJECT_DIR).replace("\\", "/"),
            "metric_titles": TARGET_METRICS,
        },
        "source_mode": "metric_cards_dom",
        "notes": "查询后直接从三个指标卡片元素提取标题和值，并按统一 HTML 字段落盘。",
    }


def write_daily_json(payload: dict) -> str:
    path = os.path.join(OUT_DIR, f"continuous_delivery_{payload['date']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log(f"已写入当日巡检 JSON: {path}")
    return path


def write_failed_daily_json(error_message: str) -> str:
    payload = {
        "date": date.today().strftime("%Y-%m-%d"),
        "indicator_type": INDICATOR_TYPE,
        "indicator_name": INDICATOR_NAME,
        "department_c3": DEPARTMENT_LEVELS[-1],
        "status": "failed",
        "metrics": {item["key"]: None for item in TARGET_METRIC_CONFIG},
        "unit": METRIC_UNITS,
        "error": error_message,
        "source": {
            "query_screenshot": "out/three_cards.png",
            "metric_titles": TARGET_METRICS,
        },
        "source_mode": "metric_cards_dom",
    }
    return write_daily_json(payload)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )

        context = browser.new_context(
            viewport={"width": 1600, "height": 900}
        )
        page = context.new_page()

        try:
            log("开始打开页面")
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)

            wait_page_stable(page)
            handle_guide_popup(page)
            click_delivery_detail_menu(page)
            select_department_levels(page)
            click_query_button(page)

            cards_row = locate_three_cards_row(page)
            final_path = save_final_locator_shot(cards_row, "three_cards")

            metrics = extract_three_metrics(page)
            payload = build_daily_payload(metrics, final_path)
            json_path = write_daily_json(payload)

            log("流程完成")
            log(f"提取结果: {json.dumps(metrics, ensure_ascii=False)}")
            log(f"最终输出文件: {final_path}")
            log(f"JSON 输出文件: {json_path}")

            page.wait_for_timeout(4500)

        except PlaywrightTimeout as e:
            log(f"Playwright 超时: {e}")
            try:
                write_failed_daily_json(f"Playwright 超时: {e}")
            except Exception as json_exc:
                log(f"写入失败 JSON 失败: {json_exc}")
        except Exception as e:
            log(f"执行异常: {e}")
            try:
                write_failed_daily_json(str(e))
            except Exception as json_exc:
                log(f"写入失败 JSON 失败: {json_exc}")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
