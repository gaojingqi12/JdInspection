import time
from datetime import date, timedelta

from common import clean_text, log
from config import CARD_TITLE, DEPARTMENT_C3, DEPARTMENT_FILTER_LABEL, FILTER_DATE_LABEL


def collapse_sidebar_if_possible(page, timeout_ms=12000):
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        for idx, f in enumerate(page.frames):
            try:
                url = f.url or ""
                if "bi.jd.com/detail" in url:
                    btn = f.locator(".list-collapse").first
                    if btn.count() > 0 and btn.is_visible(timeout=800):
                        btn.click()
                        page.wait_for_timeout(1200)
                        log(f"已点击收起侧边栏，frame[{idx}]")
                        return
            except Exception:
                pass
        page.wait_for_timeout(700)

    log("未找到可点击的侧边栏收起按钮，跳过")


def find_target_frame(page, timeout_ms=45000):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for idx, frame in enumerate(page.frames):
            try:
                title = frame.locator(f"text={CARD_TITLE}").first
                if title.count() > 0 and title.is_visible(timeout=600):
                    log(f"找到目标 frame[{idx}]: {frame.url}")
                    return frame
            except Exception:
                continue
        page.wait_for_timeout(1000)

    raise RuntimeError(f"未找到包含“{CARD_TITLE}”的 frame")


def find_target_container(frame):
    container = frame.locator(
        "xpath=//div[contains(@class,'element-contaienr') or contains(@class,'element-container')]"
        f"[.//div[contains(@class,'chart-title') and contains(normalize-space(.), '{CARD_TITLE}')]]"
    ).first

    if container.count() == 0:
        title = frame.locator(
            f"xpath=//div[contains(@class,'chart-title') and contains(normalize-space(.), '{CARD_TITLE}')]"
        ).first
        if title.count() == 0:
            raise RuntimeError(f"未找到“{CARD_TITLE}”容器")

        container = title.locator(
            "xpath=ancestor::div[contains(@class,'element-contaienr') or contains(@class,'element-container')][1]"
        ).first

    container.wait_for(state="visible", timeout=15000)
    container.scroll_into_view_if_needed()
    frame.page.wait_for_timeout(1000)
    log("已定位目标卡片容器")
    return container


def move_mouse_into_locator(frame, locator, name="unknown"):
    locator.wait_for(state="visible", timeout=5000)
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    if not box:
        raise RuntimeError(f"{name} bounding_box 为空")

    page = frame.page
    start_x = max(box["x"] - 30, 0)
    start_y = max(box["y"] - 10, 0)
    enter_x = box["x"] + min(40, box["width"] * 0.2)
    enter_y = box["y"] + min(20, box["height"] * 0.2)

    page.mouse.move(start_x, start_y, steps=8)
    page.wait_for_timeout(150)
    page.mouse.move(enter_x, enter_y, steps=15)
    page.wait_for_timeout(300)

    log(f"鼠标已移入 {name}: ({enter_x:.1f}, {enter_y:.1f})")


def hover_card_and_reveal_toolbar(frame, container):
    candidates = [
        (container.locator(".chart-title").first, "chart-title"),
        (container.locator("#chart-main").first, "chart-main"),
        (container.locator(".chart.chart-padding").first, "chart-padding"),
        (container.locator(".table-render").first, "table-render"),
        (container, "container"),
    ]

    last_err = None

    for loc, name in candidates:
        try:
            if loc.count() == 0:
                continue

            move_mouse_into_locator(frame, loc, name=name)

            box = loc.bounding_box()
            if not box:
                continue

            target_x = box["x"] + box["width"] - 35
            target_y = box["y"] + 18

            frame.page.mouse.move(target_x, target_y, steps=20)
            frame.page.wait_for_timeout(900)

            toolbar = container.locator(".card-toolbar").first
            if toolbar.count() > 0 and toolbar.is_visible():
                log(f"工具栏已出现，触发区域: {name}")
                return

        except Exception as e:
            last_err = e
            log(f"hover 触发失败 {name}: {e}")

    raise RuntimeError(f"未能通过 hover 触发工具栏显示: {last_err}")


def click_chart_filter_button(frame, container):
    hover_card_and_reveal_toolbar(frame, container)

    toolbar = container.locator(".card-toolbar").first
    toolbar.wait_for(state="visible", timeout=5000)

    candidates = [
        toolbar.locator("div:nth-child(7)").first,
        container.locator(".preview-set .card-toolbar > div:nth-child(7)").first,
        container.locator(".card-toolbar > div:nth-child(7)").first,
        container.locator("svg use[*|href='#icon-filter']").locator(
            "xpath=ancestor::*[self::svg or self::div][1]"
        ).first,
    ]

    last_err = None
    for idx, btn in enumerate(candidates):
        try:
            if btn.count() == 0:
                continue
            if not btn.is_visible():
                continue

            btn.scroll_into_view_if_needed()
            btn.click(timeout=4000, force=True)
            frame.page.wait_for_timeout(1500)
            log(f"已点击图表筛选按钮，第 {idx} 个候选")
            return
        except Exception as e:
            last_err = e
            log(f"点击筛选按钮失败，第 {idx} 个候选: {e}")

    raise RuntimeError(f"图表筛选按钮点击失败: {last_err}")


def get_last_friday_and_today():
    today = date.today()
    days_since_friday = (today.weekday() - 4) % 7
    if days_since_friday == 0:
        days_since_friday = 7
    last_friday = today - timedelta(days=days_since_friday)
    return last_friday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def get_visible_filter_panel(frame):
    frame.page.wait_for_timeout(1500)

    selectors = [
        ".single-chart-filter",
        ".filter-contatiner",
        ".filter-container",
    ]

    for sel in selectors:
        panels = frame.locator(sel)
        count = panels.count()
        log(f"匹配到 {sel} 数量: {count}")
        for i in range(count):
            panel = panels.nth(i)
            try:
                if panel.is_visible():
                    log(f"命中可见筛选面板: {sel}[{i}]")
                    return panel
            except Exception:
                pass

    raise Exception("没找到可见的筛选面板")


def find_filter_item(panel, label_text: str):
    items = panel.locator(".filter-item")
    count = items.count()

    for i in range(count):
        item = items.nth(i)
        try:
            label = clean_text(item.locator(".filter-item-label").inner_text())
            if label == label_text:
                log(f"命中筛选项: {label_text}")
                return item
        except Exception:
            pass

    raise Exception(f"没找到筛选项: {label_text}")


def fill_card_date_range(frame):
    start_date, end_date = get_last_friday_and_today()
    log(f"开始时间: {start_date}, 结束时间: {end_date}")

    panel = get_visible_filter_panel(frame)
    target_item = find_filter_item(panel, FILTER_DATE_LABEL)

    inputs = target_item.locator("input.el-input__inner")
    input_count = inputs.count()
    log(f"{FILTER_DATE_LABEL} input 数量: {input_count}")

    if input_count < 2:
        raise Exception(f"{FILTER_DATE_LABEL} 输入框数量异常: {input_count}")

    start_input = inputs.nth(0)
    end_input = inputs.nth(1)

    start_input.scroll_into_view_if_needed()
    start_input.click()
    frame.page.wait_for_timeout(300)
    start_input.fill(start_date)
    frame.page.keyboard.press("Enter")
    frame.page.wait_for_timeout(800)

    end_input.scroll_into_view_if_needed()
    end_input.click()
    frame.page.wait_for_timeout(300)
    end_input.fill(end_date)
    frame.page.keyboard.press("Enter")
    frame.page.wait_for_timeout(1200)

    log(f"已填写：{FILTER_DATE_LABEL}")
    return start_date, end_date


def select_department_c3_by_enter(frame, department_name=DEPARTMENT_C3):
    panel = get_visible_filter_panel(frame)
    target_item = find_filter_item(panel, DEPARTMENT_FILTER_LABEL)

    dropdown_btn = target_item.locator("button.qd-button").first
    dropdown_btn.wait_for(state="visible", timeout=7500)
    dropdown_btn.click()
    frame.page.wait_for_timeout(1200)
    log(f"已点开：{DEPARTMENT_FILTER_LABEL} 下拉")

    search_box = None
    search_candidates = [
        '.el-popper input.el-input__inner[placeholder="请输入..."]',
        '.el-popper input.el-input__inner[placeholder*="请输入"]',
        '.el-popover input.el-input__inner[placeholder="请输入..."]',
        '.el-popover input.el-input__inner[placeholder*="请输入"]',
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
    frame.page.wait_for_timeout(200)
    search_box.fill(department_name)
    frame.page.wait_for_timeout(500)
    frame.page.keyboard.press("Enter")
    frame.page.wait_for_timeout(1500)
    log(f"已输入并回车：{DEPARTMENT_FILTER_LABEL} = {department_name}")

    try:
        selected_text = clean_text(target_item.locator("button.qd-button").inner_text())
        if department_name not in selected_text:
            option_candidates = [
                frame.locator(".el-popper").get_by_text(department_name, exact=True),
                frame.locator(".el-popover").get_by_text(department_name, exact=True),
                frame.get_by_text(department_name, exact=True),
            ]
            for cand in option_candidates:
                for i in range(cand.count()):
                    opt = cand.nth(i)
                    if opt.is_visible():
                        opt.click()
                        frame.page.wait_for_timeout(1000)
                        log(f"已兜底点击选项: {department_name}")
                        return
    except Exception as e:
        log(f"检查/兜底选择{DEPARTMENT_FILTER_LABEL}失败: {e}")


def close_filter_panel(frame):
    panel = get_visible_filter_panel(frame)

    close_btn = panel.locator(".header .active-btn").first
    close_btn.wait_for(state="visible", timeout=5000)
    close_btn.scroll_into_view_if_needed()
    frame.page.wait_for_timeout(300)

    box = close_btn.bounding_box()
    if not box:
        raise RuntimeError("关闭按钮 bounding_box 为空")

    frame.page.mouse.click(
        box["x"] + box["width"] / 2,
        box["y"] + box["height"] / 2,
    )
    frame.page.wait_for_timeout(1000)
    log("已通过坐标点击筛选面板头部叉号")


def click_query_button(frame):
    panel = get_visible_filter_panel(frame)
    query_btn = panel.locator(".serach-btn button").first
    query_btn.wait_for(state="visible", timeout=7500)
    query_btn.click()
    frame.page.wait_for_timeout(8000)
    log("已点击：查询")
