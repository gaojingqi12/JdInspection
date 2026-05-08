import platform
import time
from datetime import date

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from common import clean_text, log
from config import TARGET_DATE_FIELD_LABEL


FIELD_LABEL_TO_ID = {
    "期望上线日期": "expectedReleaseDate",
    "计划提测日期": "planSubmitTestDate",
    "测试完成日期": "testDoneTime",
    "计划上线日期": "planDate",
    "实际上线日期": "realDate",
    "灰度开始日期": "grayStartDate",
}


def field_label_to_data_prop(field_label: str) -> str | None:
    return FIELD_LABEL_TO_ID.get(field_label)


def iter_page_roots(page):
    yield "page", page
    for idx, page_frame in enumerate(page.frames):
        yield f"frame[{idx}]", page_frame


def find_visible_locator(locator, limit: int = 10, timeout_ms: int = 700):
    try:
        count = min(locator.count(), limit)
    except Exception:
        return None

    for i in range(count):
        candidate = locator.nth(i)
        try:
            if candidate.is_visible(timeout=timeout_ms):
                return candidate
        except Exception:
            pass
    return None


def find_release_card(target_page):
    selectors = [
        "xpath=//div[contains(@class,'card-release')][.//*[normalize-space(.)='周期与进度']]",
        "xpath=//*[normalize-space(.)='周期与进度']/ancestor::div[contains(@class,'card-release')][1]",
        "xpath=//*[contains(normalize-space(.),'周期与进度')]/ancestor::div[contains(@class,'card-release')][1]",
    ]

    for root_name, root in iter_page_roots(target_page):
        for selector in selectors:
            card = find_visible_locator(root.locator(selector), limit=5)
            if card is not None:
                log(f"已在 {root_name} 中找到“周期与进度”卡片: {selector}")
                return card

    raise RuntimeError("未找到“周期与进度”卡片")


def locate_release_card(target_page):
    target_page.bring_to_front()
    target_page.wait_for_timeout(800)
    card = find_release_card(target_page)
    card.scroll_into_view_if_needed()
    card.hover(timeout=5000, force=True)
    target_page.wait_for_timeout(1200)
    log("已定位并悬停到“周期与进度”卡片")
    return card


def find_date_form_item(target_page, field_label: str, timeout_ms: int = 20000):
    field_id = FIELD_LABEL_TO_ID.get(field_label)
    data_prop = field_label_to_data_prop(field_label)
    selectors = []
    if field_id:
        selectors.extend(
            [
                f"xpath=//form[contains(@class,'card-release-form')]//label[@for='{field_id}']/ancestor::div[contains(@class,'el-form-item')][1]",
                f"xpath=//label[@for='{field_id}']/ancestor::div[contains(@class,'el-form-item')][1]",
            ]
        )
    selectors.extend(
        [
            f"xpath=//form[contains(@class,'card-release-form')]//label[normalize-space(.)='{field_label}']/ancestor::div[contains(@class,'el-form-item')][1]",
            f"xpath=//div[contains(@class,'card-release')]//label[normalize-space(.)='{field_label}']/ancestor::div[contains(@class,'el-form-item')][1]",
            f"xpath=//label[normalize-space(.)='{field_label}']/ancestor::div[contains(@class,'el-form-item')][1]",
        ]
    )
    if data_prop:
        selectors.extend(
            [
                f"xpath=//form[contains(@class,'card-release-form')]//*[@data-prop='{data_prop}' and .//*[normalize-space(.)='{field_label}']]",
                f"xpath=//*[@data-prop='{data_prop}' and .//*[normalize-space(.)='{field_label}']]",
            ]
        )

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for root_name, root in iter_page_roots(target_page):
            for selector in selectors:
                form_item = find_visible_locator(root.locator(selector), limit=5)
                if form_item is not None:
                    log(f"已在 {root_name} 中找到日期字段容器: {field_label} | {selector}")
                    return root, form_item
        target_page.wait_for_timeout(300)

    raise RuntimeError(f"未找到“{field_label}”字段容器")


def find_date_value_locator(form_item):
    selectors = [
        ".jacp-form__value",
        ".jacp-forms-wrapper__content .el-tooltip",
        ".jacp-forms-wrapper__content",
        ".text-primary",
    ]
    for selector in selectors:
        value_locator = find_visible_locator(form_item.locator(selector), limit=5)
        if value_locator is not None:
            return value_locator
    raise RuntimeError("未找到日期展示值元素")


def read_date_field_display_value(form_item) -> str:
    selectors = [
        ".jacp-form__value span:not([style*='display: none'])",
        ".jacp-form__value span",
        ".jacp-form__value",
    ]

    for selector in selectors:
        try:
            values = form_item.locator(selector)
            for i in range(values.count()):
                value = clean_text(values.nth(i).inner_text(timeout=1000))
                if value and value != "-":
                    return value
        except Exception:
            pass
    return ""


def read_user_names(container) -> str:
    names = []
    selectors = [
        ".jacp-user__name",
        ".jacp-erp__name",
    ]

    for selector in selectors:
        try:
            values = container.locator(selector)
            for i in range(values.count()):
                value = clean_text(values.nth(i).inner_text(timeout=1000))
                if value and value not in names:
                    names.append(value)
        except Exception:
            pass

    if not names:
        try:
            avatars = container.locator("img[alt]")
            for i in range(avatars.count()):
                value = clean_text(avatars.nth(i).get_attribute("alt") or "")
                if value and value not in names:
                    names.append(value)
        except Exception:
            pass

    return "、".join(names)


def read_development_owner(target_page, timeout_ms: int = 12000) -> str:
    selectors = [
        "xpath=//*[contains(@class,'j-label-secondary') and normalize-space(.)='（研发）负责人']/ancestor::div[contains(@class,'col-span-1')][1]",
        "xpath=//*[contains(@class,'j-label-secondary') and normalize-space(.)='(研发)负责人']/ancestor::div[contains(@class,'col-span-1')][1]",
        "xpath=//*[contains(@class,'j-label-secondary') and normalize-space(.)='研发负责人']/ancestor::div[contains(@class,'col-span-1')][1]",
        "xpath=//*[contains(@class,'j-label-secondary') and contains(normalize-space(.),'研发') and contains(normalize-space(.),'负责人')]/ancestor::div[contains(@class,'col-span-1')][1]",
    ]

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for root_name, root in iter_page_roots(target_page):
            for selector in selectors:
                container = find_visible_locator(root.locator(selector), limit=5, timeout_ms=500)
                if container is None:
                    continue

                owner = read_user_names(container)
                if owner:
                    log(f"已在 {root_name} 中提取研发负责人: {owner}")
                    return owner
        target_page.wait_for_timeout(300)

    log("未提取到研发负责人")
    return ""


def click_date_field_edit_entry(target_page, form_item, value_locator) -> bool:
    value_locator.scroll_into_view_if_needed()
    value_locator.hover(timeout=5000, force=True)
    target_page.wait_for_timeout(300)

    edit_selectors = [
        ".forms-wrapper-toolbar__item:has(.jacp-icon-edit)",
        ".jacp-forms-wrapper-toolbar .forms-wrapper-toolbar__item",
        ".jacp-icon-edit",
    ]
    for selector in edit_selectors:
        edit_entry = find_visible_locator(form_item.locator(selector), limit=5, timeout_ms=500)
        if edit_entry is None:
            continue
        edit_entry.click(timeout=4000, force=True)
        target_page.wait_for_timeout(500)
        log("已点击日期字段悬浮编辑按钮")
        return True

    value_locator.click(timeout=5000, force=True)
    target_page.wait_for_timeout(500)
    log("未找到悬浮编辑按钮，已点击日期展示值")
    return False


def find_editable_input(form_item):
    selectors = [
        "input.el-input__inner:not([readonly])",
        "input:not([readonly])",
        "input.el-input__inner",
        "input",
    ]
    for selector in selectors:
        input_locator = find_visible_locator(form_item.locator(selector), limit=5, timeout_ms=500)
        if input_locator is not None:
            return input_locator
    return None


def hover_date_field(target_page, field_label: str = TARGET_DATE_FIELD_LABEL) -> str:
    _, form_item = find_date_form_item(target_page, field_label)
    value_locator = find_date_value_locator(form_item)
    old_value = read_date_field_display_value(form_item)

    value_locator.scroll_into_view_if_needed()
    value_locator.hover(timeout=5000, force=True)
    target_page.wait_for_timeout(1000)
    log(f"已把鼠标移到“{field_label}”字段值上，当前值: {old_value or '-'}")
    return old_value


def click_date_value_and_type_today(target_page, field_label: str = TARGET_DATE_FIELD_LABEL):
    _, form_item = find_date_form_item(target_page, field_label)
    value_locator = find_date_value_locator(form_item)
    old_value = read_date_field_display_value(form_item)
    today = date.today().strftime("%Y-%m-%d")

    click_date_field_edit_entry(target_page, form_item, value_locator)

    input_locator = find_editable_input(form_item)
    if input_locator is not None:
        input_locator.fill(today, timeout=4000)
        input_locator.press("Enter")
    else:
        # 这个组件有时点击展示值后直接接收键盘输入，不一定会渲染出 input。
        select_all = "Meta+A" if platform.system() == "Darwin" else "Control+A"
        target_page.keyboard.press(select_all)
        target_page.keyboard.type(today)
        target_page.keyboard.press("Enter")
    target_page.wait_for_timeout(1500)

    current_value = read_date_field_display_value(form_item)
    log(f"已点击并输入“{field_label}”: {old_value or '-'} -> {today}")
    return old_value, today, current_value


def click_confirm_save_if_present(
    target_page,
    field_label: str = TARGET_DATE_FIELD_LABEL,
    timeout_ms: int = 5000,
) -> bool:
    deadline = time.time() + timeout_ms / 1000
    message_texts = [
        f"{field_label}晚于期望上线日期",
        f"{field_label}晚于期望提测日期",
        f"{field_label}晚于期望提交测试日期",
        "计划上线日期晚于期望上线日期",
    ]

    while time.time() < deadline:
        for root_name, root in iter_page_roots(target_page):
            try:
                matched_message = False
                for message_text in message_texts:
                    if root.get_by_text(message_text).first.is_visible(timeout=300):
                        matched_message = True
                        break
                if not matched_message:
                    continue
            except Exception:
                continue

            button_selectors = [
                ".el-popover:visible button",
                ".el-message-box:visible button",
                ".el-dialog:visible button",
                ".dialog-shell:visible button",
                "[role='dialog']:visible button",
                "button",
            ]

            for selector in button_selectors:
                for text in ("确认", "确定"):
                    button = find_visible_locator(
                        root.locator(selector).filter(has_text=text),
                        timeout_ms=500,
                    )
                    if button is None:
                        continue
                    button.click(timeout=4000, force=True)
                    target_page.wait_for_timeout(1200)
                    log(f"已在 {root_name} 中点击{field_label}确认按钮: {text}")
                    return True

        target_page.wait_for_timeout(300)

    log(f"未出现{field_label}确认弹窗，继续执行")
    return False


def update_target_date(target_page, code: str, name: str, field_label: str = TARGET_DATE_FIELD_LABEL) -> dict:
    native_dialog_accepted = {"value": False}

    def accept_dialog(dialog):
        log(f"捕获浏览器确认框，自动确认: {dialog.message}")
        native_dialog_accepted["value"] = True
        dialog.accept()

    target_page.on("dialog", accept_dialog)
    target_page.bring_to_front()
    target_page.wait_for_timeout(1200)

    try:
        target_page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    development_owner = read_development_owner(target_page)
    old_value, new_value, current_value = click_date_value_and_type_today(target_page, field_label)

    confirm_clicked = click_confirm_save_if_present(target_page, field_label, timeout_ms=6000)
    confirm_clicked = confirm_clicked or native_dialog_accepted["value"]
    target_page.wait_for_timeout(1500)

    log(f"已修改{field_label}: {code} | {old_value or '-'} -> {new_value}")
    jump_url = target_page.url
    return {
        "需求编码": code,
        "需求名称": name,
        "研发负责人": development_owner,
        "修改字段": field_label,
        "修改前": old_value,
        "修改后": new_value,
        f"修正后{field_label}": new_value,
        "页面当前值": current_value,
        "是否点击确认": confirm_clicked,
        "跳转地址": jump_url,
        "页面URL": jump_url,
        "modified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def close_drill_dialog_if_present(frame):
    for root_name, root in (("frame", frame), ("page", frame.page)):
        for selector in (
            ".dialog-shell:has(.drill-dialog):visible .close-button",
            ".drill-dialog:visible .close-button",
            "[class*='drill'][class*='dialog']:visible .close-button",
            "[role='dialog']:visible .close-button",
            "[role='dialog']:visible .el-dialog__close",
        ):
            try:
                close_btn = root.locator(selector).last
                if close_btn.is_visible(timeout=700):
                    close_btn.click(timeout=3000, force=True)
                    frame.page.wait_for_timeout(700)
                    log(f"已关闭 {root_name} 中的 drill 跳转弹窗: {selector}")
                    return
            except Exception:
                pass


def return_to_table_page(frame, popup=None):
    if popup is not None:
        try:
            popup.close()
        except Exception:
            pass

    try:
        frame.page.bring_to_front()
    except Exception:
        pass
    close_drill_dialog_if_present(frame)
    frame.page.wait_for_timeout(1000)


def click_drill_jump_if_present(frame, timeout_ms: int = 8000):
    """
    点击“需求名称”后，可能出现 drill 弹层，里面有“跳转”按钮。
    返回跳转打开的新页面；失败时返回 None。
    """
    page = frame.page
    try:
        dialog = None
        for root_name, root in (("frame", frame), ("page", page)):
            for selector in (
                ".dialog-shell:has(.drill-dialog):visible",
                ".drill-dialog:visible",
                "[class*='drill'][class*='dialog']:visible",
                "[role='dialog']:visible",
            ):
                try:
                    candidate = root.locator(selector).last
                    candidate.wait_for(state="visible", timeout=2500)
                    dialog = candidate
                    log(f"已在 {root_name} 中找到 drill 跳转弹窗: {selector}")
                    break
                except Exception:
                    pass
            if dialog is not None:
                break

        if dialog is None:
            raise RuntimeError("未找到可见的 drill 跳转弹窗")

        jump_btn = None
        for selector in (
            ".drill-dialog .drill-item button",
            "button",
            "[role='button']",
        ):
            for text in ("跳转", "打开", "查看"):
                candidate = find_visible_locator(
                    dialog.locator(selector).filter(has_text=text),
                    timeout_ms=500,
                )
                if candidate is not None:
                    jump_btn = candidate
                    break
            if jump_btn is not None:
                break

        if jump_btn is None:
            jump_btn = dialog.get_by_role("button", name="跳转").first
            jump_btn.wait_for(state="visible", timeout=timeout_ms)

        popup = None
        pages_before = list(page.context.pages)
        try:
            with page.context.expect_page(timeout=15000) as p:
                jump_btn.click(timeout=4000, force=True)
            popup = p.value
        except PlaywrightTimeoutError:
            log("已点击“跳转”，但未捕获到新窗口，继续执行")
            page.wait_for_timeout(3000)
        except Exception:
            jump_btn.click(timeout=4000, force=True)

        page.wait_for_timeout(1200)
        if popup is None:
            new_pages = [opened_page for opened_page in page.context.pages if opened_page not in pages_before]
            if new_pages:
                popup = new_pages[-1]

        if popup is None:
            raise RuntimeError("点击“跳转”后未捕获到新页面")

        try:
            popup.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass
        try:
            popup.bring_to_front()
            log(f"已打开跳转新页面: {popup.url}")
        except Exception:
            pass

        return popup
    except Exception as e:
        log(f"未能点击 drill 弹层里的“跳转”按钮: {e}")
        return None
