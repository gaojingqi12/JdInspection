import asyncio
from datetime import date, datetime, timedelta
import json
import platform
from pathlib import Path
import time

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from generate_modification_report import generate_report


LIST_URL = "http://xingyun.jd.com/teamspace/scrum/JD_Cashier/allWorkItems"
DETAIL_URL_TEMPLATE = LIST_URL + "?sprintId={sprint_id}"
CARD_DETAIL_URL_TEMPLATE = LIST_URL + "?sprintId={sprint_id}&cardId={card_id}"
SPRINT_BLOCK_SELECTOR = ".jacpbiz-sidebar-block[data-item]"
TITLE_SELECTOR = ".jacpbiz-sidebar-block-title__label"
GROUP_WRAP_SELECTOR = ".cards-board-groupwrap"
GROUP_SELECTOR = ".cards-board__group"
GROUP_LABEL_SELECTOR = ".cards-board__group__label__status"
GROUP_ITEM_SELECTOR = ".cards-board__group__item"
CARD_TITLE_SELECTOR = ".text-sm.text-primary.leading-5.mb-1"
OUTPUT_PATH = Path(__file__).with_name("sprint_data_items.json")
THURSDAY_OUTPUT_PATH = Path(__file__).with_name("thursday_demands.json")
THURSDAY_SUBMIT_TEST_OUTPUT_PATH = Path(__file__).with_name("thursday_submit_test_demands.json")
THURSDAY_ONLINE_OUTPUT_PATH = Path(__file__).with_name("thursday_online_demands.json")
MODIFIED_OUTPUT_PATH = Path(__file__).with_name("thursday_to_friday_modified.json")
DEFAULT_TIMEOUT_MS = 60000
POST_PAGE_OPEN_WAIT_MS = 5000
BEFORE_CLOSE_WAIT_MS = 15000
FIELD_WAIT_TIMEOUT_MS = 30000
DETAIL_WAIT_TIMEOUT_MS = 30000
CONCURRENCY = 1
FIELD_LABEL_TO_ID = {
    "期望上线日期": "expectedReleaseDate",
    "计划提测日期": "planSubmitTestDate",
    "测试完成日期": "testDoneTime",
    "计划上线日期": "planDate",
    "实际上线日期": "realDate",
    "灰度开始日期": "grayStartDate",
}
DATE_KEY_TO_LABEL = {
    "plan_submit_test_date": "计划提测日期",
    "plan_date": "计划上线日期",
}


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def get_this_thursday() -> date:
    today = date.today()
    return today + timedelta(days=3 - today.weekday())


def get_this_friday() -> date:
    today = date.today()
    return today + timedelta(days=4 - today.weekday())


def build_thursday_payload(sprint_results: list[dict[str, object]]) -> dict[str, object]:
    thursday = get_this_thursday().isoformat()
    matched_items = []

    for sprint in sprint_results:
        sprint_title = str(sprint.get("title", ""))
        sprint_id = str(sprint.get("data_item", ""))
        detail_url = str(sprint.get("detail_url", ""))
        for demand in sprint.get("second_group_items", []):
            if not isinstance(demand, dict):
                continue

            matched_by = []
            if demand.get("plan_submit_test_date") == thursday:
                matched_by.append("plan_submit_test_date")
            if demand.get("plan_date") == thursday:
                matched_by.append("plan_date")

            for action in demand.get("detail_actions", []):
                if not isinstance(action, dict):
                    continue
                if action.get("status") != "modified" or action.get("source_date") != thursday:
                    continue
                matched_date_key = action.get("matched_date_key")
                if matched_date_key in DATE_KEY_TO_LABEL and matched_date_key not in matched_by:
                    matched_by.append(str(matched_date_key))

            if not matched_by:
                continue

            plan_submit_test_date = str(demand.get("plan_submit_test_date", ""))
            plan_date = str(demand.get("plan_date", ""))
            if "plan_submit_test_date" in matched_by and not plan_submit_test_date:
                plan_submit_test_date = thursday
            if "plan_date" in matched_by and not plan_date:
                plan_date = thursday

            matched_items.append(
                {
                    "sprint_title": sprint_title,
                    "sprint_data_item": sprint_id,
                    "detail_url": detail_url,
                    "item_id": str(demand.get("item_id", "")),
                    "card_detail_url": CARD_DETAIL_URL_TEMPLATE.format(
                        sprint_id=sprint_id,
                        card_id=str(demand.get("item_id", "")),
                    ),
                    "demand_name": str(demand.get("demand_name", "")),
                    "owner": str(demand.get("owner", "")),
                    "plan_submit_test_date": plan_submit_test_date,
                    "plan_date": plan_date,
                    "matched_by": matched_by,
                }
            )

    return {
        "target_weekday": "Thursday",
        "target_date": thursday,
        "count": len(matched_items),
        "items": matched_items,
    }


def empty_modified_payload() -> dict[str, object]:
    return {
        "source_date": get_this_thursday().isoformat(),
        "target_date": get_this_friday().isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": 0,
        "modified_items": [],
        "failed_items": [],
    }


def add_modified_record(payload: dict[str, object], record: dict[str, object]) -> None:
    payload.setdefault("modified_items", []).append(record)
    payload["count"] = len(payload.get("modified_items", []))


def add_failed_record(payload: dict[str, object], record: dict[str, object]) -> None:
    payload.setdefault("failed_items", []).append(record)


def build_filtered_payload(thursday_payload: dict[str, object], match_key: str) -> dict[str, object]:
    filtered_items = []
    for item in thursday_payload.get("items", []):
        if not isinstance(item, dict):
            continue
        matched_by = item.get("matched_by", [])
        if isinstance(matched_by, list) and match_key in matched_by:
            filtered_items.append(item)

    return {
        "target_weekday": thursday_payload.get("target_weekday", "Thursday"),
        "target_date": thursday_payload.get("target_date", ""),
        "match_key": match_key,
        "count": len(filtered_items),
        "items": filtered_items,
    }


async def get_text(locator) -> str:
    if await locator.count() == 0:
        return ""
    return normalize_text(await locator.first.inner_text())


async def find_visible_locator(locator, limit: int = 10, timeout_ms: int = 700):
    try:
        count = min(await locator.count(), limit)
    except Exception:
        return None

    for index in range(count):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible(timeout=timeout_ms):
                return candidate
        except Exception:
            pass
    return None


def iter_page_roots(page: Page):
    yield "page", page
    for index, page_frame in enumerate(page.frames):
        yield f"frame[{index}]", page_frame


async def find_date_form_item(target_page: Page, field_label: str, timeout_ms: int = DETAIL_WAIT_TIMEOUT_MS):
    field_id = FIELD_LABEL_TO_ID.get(field_label)
    data_prop = field_id
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
                form_item = await find_visible_locator(root.locator(selector), limit=5)
                if form_item is not None:
                    print(f"已在 {root_name} 中找到日期字段容器: {field_label}")
                    return root, form_item
        await target_page.wait_for_timeout(300)

    raise RuntimeError(f"未找到“{field_label}”字段容器")


async def find_date_value_locator(form_item):
    selectors = [
        ".jacp-form__value",
        ".jacp-forms-wrapper__content .el-tooltip",
        ".jacp-forms-wrapper__content",
        ".text-primary",
    ]
    for selector in selectors:
        value_locator = await find_visible_locator(form_item.locator(selector), limit=5)
        if value_locator is not None:
            return value_locator
    raise RuntimeError("未找到日期展示值元素")


async def read_date_field_display_value(form_item) -> str:
    selectors = [
        ".jacp-form__value span:not([style*='display: none'])",
        ".jacp-form__value span",
        ".jacp-form__value",
        ".jacp-forms-wrapper__content",
    ]

    for selector in selectors:
        try:
            values = form_item.locator(selector)
            for index in range(await values.count()):
                value = normalize_text(await values.nth(index).inner_text(timeout=1000))
                if value and value != "-":
                    return value
        except Exception:
            pass
    return ""


async def click_date_field_edit_entry(target_page: Page, form_item, value_locator) -> bool:
    await value_locator.scroll_into_view_if_needed()
    await value_locator.hover(timeout=5000, force=True)
    await target_page.wait_for_timeout(300)

    edit_selectors = [
        ".forms-wrapper-toolbar__item:has(.jacp-icon-edit)",
        ".jacp-forms-wrapper-toolbar .forms-wrapper-toolbar__item",
        ".jacp-icon-edit",
    ]
    for selector in edit_selectors:
        edit_entry = await find_visible_locator(form_item.locator(selector), limit=5, timeout_ms=500)
        if edit_entry is None:
            continue
        await edit_entry.click(timeout=4000, force=True)
        await target_page.wait_for_timeout(500)
        print("已点击日期字段悬浮编辑按钮")
        return True

    await value_locator.click(timeout=5000, force=True)
    await target_page.wait_for_timeout(500)
    print("未找到悬浮编辑按钮，已点击日期展示值")
    return False


async def find_editable_input(form_item):
    selectors = [
        "input.el-input__inner:not([readonly])",
        "input:not([readonly])",
        "input.el-input__inner",
        "input",
    ]
    for selector in selectors:
        input_locator = await find_visible_locator(form_item.locator(selector), limit=5, timeout_ms=500)
        if input_locator is not None:
            return input_locator
    return None


async def click_confirm_save_if_present(target_page: Page, field_label: str, timeout_ms: int = 6000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    message_texts = [
        f"{field_label}晚于期望上线日期",
        f"{field_label}晚于期望提测日期",
        f"{field_label}晚于期望提交测试日期",
        "计划上线日期晚于期望上线日期",
    ]

    while time.time() < deadline:
        for root_name, root in iter_page_roots(target_page):
            matched_message = False
            for message_text in message_texts:
                try:
                    if await root.get_by_text(message_text).first.is_visible(timeout=300):
                        matched_message = True
                        break
                except Exception:
                    pass
            if not matched_message:
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
                    button = await find_visible_locator(
                        root.locator(selector).filter(has_text=text),
                        timeout_ms=500,
                    )
                    if button is None:
                        continue
                    await button.click(timeout=4000, force=True)
                    await target_page.wait_for_timeout(1200)
                    print(f"已在 {root_name} 中点击{field_label}确认按钮: {text}")
                    return True

        await target_page.wait_for_timeout(300)

    print(f"未出现{field_label}确认弹窗，继续执行")
    return False


async def read_detail_date_field(target_page: Page, field_label: str, timeout_ms: int = 6000) -> str:
    _, form_item = await find_date_form_item(target_page, field_label, timeout_ms=timeout_ms)
    return await read_date_field_display_value(form_item)


async def update_date_field(target_page: Page, field_label: str, target_date: str) -> dict[str, object]:
    native_dialog_accepted = {"value": False}

    async def accept_dialog(dialog):
        native_dialog_accepted["value"] = True
        await dialog.accept()

    target_page.on("dialog", lambda dialog: asyncio.create_task(accept_dialog(dialog)))
    await target_page.bring_to_front()
    await target_page.wait_for_timeout(1200)

    try:
        await target_page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass

    _, form_item = await find_date_form_item(target_page, field_label)
    value_locator = await find_date_value_locator(form_item)
    old_value = await read_date_field_display_value(form_item)

    await click_date_field_edit_entry(target_page, form_item, value_locator)
    input_locator = await find_editable_input(form_item)
    if input_locator is not None:
        await input_locator.fill(target_date, timeout=4000)
        await input_locator.press("Enter")
    else:
        select_all = "Meta+A" if platform.system() == "Darwin" else "Control+A"
        await target_page.keyboard.press(select_all)
        await target_page.keyboard.type(target_date)
        await target_page.keyboard.press("Enter")

    await target_page.wait_for_timeout(1500)
    current_value = await read_date_field_display_value(form_item)
    confirm_clicked = await click_confirm_save_if_present(target_page, field_label)
    confirm_clicked = confirm_clicked or native_dialog_accepted["value"]
    await target_page.wait_for_timeout(1500)

    print(f"已修改{field_label}: {old_value or '-'} -> {target_date}")
    return {
        "field_label": field_label,
        "old_value": old_value,
        "new_value": target_date,
        "page_current_value": current_value,
        "confirm_clicked": confirm_clicked,
    }


async def close_detail_if_present(page: Page) -> None:
    close_selectors = [
        ".dialog-shell:visible .close-button",
        "[role='dialog']:visible .close-button",
        "[role='dialog']:visible .el-dialog__close",
        ".el-dialog:visible .el-dialog__close",
        ".jacp-icon-close",
    ]
    for selector in close_selectors:
        close_button = await find_visible_locator(page.locator(selector), limit=5, timeout_ms=500)
        if close_button is None:
            continue
        try:
            await close_button.click(timeout=3000, force=True)
            await page.wait_for_timeout(800)
            return
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def click_card_and_get_detail_page(context: BrowserContext, board_page: Page, card):
    await close_detail_if_present(board_page)
    pages_before = list(context.pages)
    await card.scroll_into_view_if_needed()
    await card.click(timeout=10000, force=True)
    await board_page.wait_for_timeout(2500)

    new_pages = [opened_page for opened_page in context.pages if opened_page not in pages_before]
    if new_pages:
        detail_page = new_pages[-1]
        try:
            await detail_page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        await detail_page.bring_to_front()
        return detail_page, "popup"

    try:
        await find_date_form_item(board_page, "计划提测日期", timeout_ms=5000)
        return board_page, "same_page"
    except Exception:
        await find_date_form_item(board_page, "计划上线日期", timeout_ms=5000)
        return board_page, "same_page"


async def open_card_detail_page(context: BrowserContext, sprint_item: dict[str, object], demand: dict[str, str]):
    sprint_id = str(sprint_item.get("data_item", ""))
    card_id = str(demand.get("item_id", ""))
    if not sprint_id or not card_id:
        raise RuntimeError(f"缺少 sprintId 或 cardId: sprintId={sprint_id}, cardId={card_id}")

    card_detail_url = CARD_DETAIL_URL_TEMPLATE.format(sprint_id=sprint_id, card_id=card_id)
    detail_page = await context.new_page()
    detail_page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    await detail_page.goto(card_detail_url, wait_until="domcontentloaded")
    await detail_page.wait_for_timeout(POST_PAGE_OPEN_WAIT_MS)
    await detail_page.bring_to_front()
    return detail_page, "direct_url", card_detail_url


def get_card_thursday_matches(demand: dict[str, str]) -> list[str]:
    thursday = get_this_thursday().isoformat()
    return [date_key for date_key in DATE_KEY_TO_LABEL if demand.get(date_key) == thursday]


def has_any_card_plan_date(demand: dict[str, str]) -> bool:
    return any(demand.get(date_key) for date_key in DATE_KEY_TO_LABEL)


async def wait_for_second_group_fields(page: Page) -> None:
    await page.wait_for_function(
        """
        () => {
          const groups = document.querySelectorAll('.cards-board-groupwrap .cards-board__group');
          if (groups.length < 2) {
            return false;
          }

          const secondGroup = groups[1];
          const cards = secondGroup.querySelectorAll('.cards-board__group__item');
          if (!cards.length) {
            return false;
          }

          const readText = (el) => {
            if (!el) {
              return '';
            }
            return (el.textContent || el.getAttribute?.('alt') || '').trim();
          };

          return Array.from(cards).some((card) => {
            const owner =
              readText(card.querySelector("[data-prop='owner'] .jacp-user__name")) ||
              readText(card.querySelector("[data-prop='owner'] img[alt]"));
            const submitTestDate = readText(card.querySelector("[data-prop='planSubmitTestDate'] .ml-2"));
            const planDate = readText(card.querySelector("[data-prop='planDate'] .ml-2"));
            return Boolean(owner || submitTestDate || planDate);
          });
        }
        """,
        timeout=FIELD_WAIT_TIMEOUT_MS,
    )


async def extract_card_fields(card) -> dict[str, str]:
    result = await card.evaluate(
        """
        (node) => {
          const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
          const pickText = (root, selector) => {
            const el = root.querySelector(selector);
            if (!el) {
              return '';
            }
            return normalize(el.textContent);
          };
          const pickOwner = (root) => {
            const ownerName = root.querySelector("[data-prop='owner'] .jacp-user__name");
            if (ownerName) {
              return normalize(ownerName.textContent);
            }
            const ownerAvatar = root.querySelector("[data-prop='owner'] img[alt]");
            if (ownerAvatar) {
              return normalize(ownerAvatar.getAttribute('alt'));
            }
            return '';
          };

          return {
            item_id: normalize(node.getAttribute('item-id')),
            group_id: normalize(node.getAttribute('group-id')),
            item_index: normalize(node.getAttribute('item-index')),
            demand_name: pickText(node, '.text-sm.text-primary.leading-5.mb-1'),
            owner: pickOwner(node),
            plan_submit_test_date: pickText(node, "[data-prop='planSubmitTestDate'] .ml-2"),
            plan_date: pickText(node, "[data-prop='planDate'] .ml-2"),
          };
        }
        """
    )
    return {key: normalize_text(value) for key, value in result.items()}


async def inspect_and_update_card(
    context: BrowserContext,
    board_page: Page,
    card,
    sprint_item: dict[str, object],
    demand: dict[str, str],
    modified_payload: dict[str, object],
) -> list[dict[str, object]]:
    thursday = get_this_thursday().isoformat()
    friday = get_this_friday().isoformat()
    matched_date_keys = get_card_thursday_matches(demand)
    detail_page = None
    open_mode = ""
    records = []

    if demand.get("demand_name") and not has_any_card_plan_date(demand):
        print(f"跳过无计划日期需求: {demand.get('demand_name', '')}")
        return [{"status": "skipped_no_plan_dates"}]

    if not matched_date_keys:
        return [{"status": "skipped_card_not_thursday"}]

    try:
        print(
            f"命中本周四，准备打开详情修改: {demand.get('demand_name', '')} "
            f"({', '.join(DATE_KEY_TO_LABEL[key] for key in matched_date_keys)})"
        )
        detail_page, open_mode, card_detail_url = await open_card_detail_page(context, sprint_item, demand)
        detail_url = card_detail_url

        for date_key in matched_date_keys:
            field_label = DATE_KEY_TO_LABEL[date_key]
            try:
                detail_value = await read_detail_date_field(detail_page, field_label)
            except Exception as exc:
                failed_record = {
                    "sprint_title": str(sprint_item.get("title", "")),
                    "sprint_data_item": str(sprint_item.get("data_item", "")),
                    "sprint_url": str(sprint_item.get("detail_url", "")),
                    "detail_url": detail_url,
                    "page_url": detail_page.url,
                    "item_id": demand.get("item_id", ""),
                    "group_id": demand.get("group_id", ""),
                    "item_index": demand.get("item_index", ""),
                    "demand_name": demand.get("demand_name", ""),
                    "owner": demand.get("owner", ""),
                    "matched_date_key": date_key,
                    "field_label": field_label,
                    "source_date": thursday,
                    "target_date": friday,
                    "reason": str(exc),
                    "failed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                add_failed_record(modified_payload, failed_record)
                records.append({"status": "field_not_found", **failed_record})
                continue

            if detail_value == friday:
                records.append(
                    {
                        "field_label": field_label,
                        "status": "already_target_date",
                        "detail_value": detail_value,
                    }
                )
                continue

            if detail_value != thursday:
                failed_record = {
                    "sprint_title": str(sprint_item.get("title", "")),
                    "sprint_data_item": str(sprint_item.get("data_item", "")),
                    "sprint_url": str(sprint_item.get("detail_url", "")),
                    "detail_url": detail_url,
                    "page_url": detail_page.url,
                    "item_id": demand.get("item_id", ""),
                    "group_id": demand.get("group_id", ""),
                    "item_index": demand.get("item_index", ""),
                    "demand_name": demand.get("demand_name", ""),
                    "owner": demand.get("owner", ""),
                    "matched_date_key": date_key,
                    "field_label": field_label,
                    "card_value": demand.get(date_key, ""),
                    "detail_value": detail_value,
                    "source_date": thursday,
                    "target_date": friday,
                    "reason": "卡片日期命中本周四，但详情页读取值不一致，已跳过以避免误改",
                    "failed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                add_failed_record(modified_payload, failed_record)
                records.append(
                    {
                        "status": "detail_value_mismatch",
                        **failed_record,
                    }
                )
                continue

            update_record = await update_date_field(detail_page, field_label, friday)
            record = {
                "sprint_title": str(sprint_item.get("title", "")),
                "sprint_data_item": str(sprint_item.get("data_item", "")),
                "sprint_url": str(sprint_item.get("detail_url", "")),
                "detail_url": detail_url,
                "page_url": detail_page.url,
                "item_id": demand.get("item_id", ""),
                "group_id": demand.get("group_id", ""),
                "item_index": demand.get("item_index", ""),
                "demand_name": demand.get("demand_name", ""),
                "owner": demand.get("owner", ""),
                "matched_date_key": date_key,
                "field_label": field_label,
                "source_date": thursday,
                "target_date": friday,
                "modified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                **update_record,
            }
            add_modified_record(modified_payload, record)
            records.append({"field_label": field_label, "status": "modified", **record})

        return records
    except Exception as exc:
        card_detail_url = ""
        if sprint_item.get("data_item") and demand.get("item_id"):
            card_detail_url = CARD_DETAIL_URL_TEMPLATE.format(
                sprint_id=str(sprint_item.get("data_item", "")),
                card_id=demand.get("item_id", ""),
            )
        failed_record = {
            "sprint_title": str(sprint_item.get("title", "")),
            "sprint_data_item": str(sprint_item.get("data_item", "")),
            "sprint_url": str(sprint_item.get("detail_url", "")),
            "detail_url": card_detail_url,
            "item_id": demand.get("item_id", ""),
            "group_id": demand.get("group_id", ""),
            "item_index": demand.get("item_index", ""),
            "demand_name": demand.get("demand_name", ""),
            "owner": demand.get("owner", ""),
            "reason": str(exc),
            "failed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        add_failed_record(modified_payload, failed_record)
        print(f"处理需求详情失败: {demand.get('demand_name', '')} | {exc}")
        return [{"status": "failed", **failed_record}]
    finally:
        if detail_page is not None and open_mode in ("popup", "direct_url"):
            try:
                await detail_page.close()
            except Exception:
                pass
            await board_page.bring_to_front()
        elif detail_page is not None:
            await close_detail_if_present(detail_page)


async def extract_second_group_items(
    context: BrowserContext,
    page: Page,
    sprint_item: dict[str, object],
    modified_payload: dict[str, object],
) -> dict[str, object]:
    detail_url = str(sprint_item["detail_url"])
    await page.goto(detail_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(POST_PAGE_OPEN_WAIT_MS)
    await page.wait_for_selector(f"{GROUP_WRAP_SELECTOR} {GROUP_SELECTOR}", timeout=DEFAULT_TIMEOUT_MS)

    group_wrap = page.locator(GROUP_WRAP_SELECTOR).first
    groups = group_wrap.locator(GROUP_SELECTOR)
    group_count = await groups.count()
    if group_count < 2:
        raise RuntimeError(f"仅找到 {group_count} 个 cards-board__group")

    second_group = groups.nth(1)
    group_label = await get_text(second_group.locator(GROUP_LABEL_SELECTOR))
    try:
        await wait_for_second_group_fields(page)
    except PlaywrightTimeoutError:
        print(f"{sprint_item.get('title', '')} 第二列字段等待超时，继续按已渲染卡片提取")
    cards = second_group.locator(GROUP_ITEM_SELECTOR)
    card_count = await cards.count()

    items = []
    for index in range(card_count):
        card = cards.nth(index)
        demand = await extract_card_fields(card)
        demand["detail_actions"] = await inspect_and_update_card(
            context,
            page,
            card,
            sprint_item,
            demand,
            modified_payload,
        )
        items.append(demand)

    return {
        "second_group_label": group_label,
        "second_group_count": len(items),
        "second_group_items": items,
    }


async def process_sprint(
    context: BrowserContext,
    sprint_item: dict[str, object],
    semaphore: asyncio.Semaphore,
    modified_payload: dict[str, object],
) -> dict[str, object]:
    async with semaphore:
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            extraction = await extract_second_group_items(context, page, sprint_item, modified_payload)
            result = {**sprint_item, **extraction}
            print(
                f"已提取 {result['title']} (data-item={result['data_item']}) "
                f"第二列 {result['second_group_count']} 条"
            )
            return result
        except Exception as exc:
            result = {**sprint_item, "error": str(exc), "second_group_items": []}
            print(f"提取失败 {result['title']} (data-item={result['data_item']}): {exc}")
            return result
        finally:
            await page.close()


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        list_page = await context.new_page()
        list_page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        await list_page.goto(LIST_URL, wait_until="domcontentloaded")
        await list_page.wait_for_timeout(POST_PAGE_OPEN_WAIT_MS)
        await list_page.wait_for_selector(SPRINT_BLOCK_SELECTOR, timeout=DEFAULT_TIMEOUT_MS)

        sprint_blocks = list_page.locator(SPRINT_BLOCK_SELECTOR)
        sprint_count = await sprint_blocks.count()
        print(f"页面已加载，当前找到 {sprint_count} 个迭代块。")

        sprint_items = []
        for index in range(sprint_count):
            block = sprint_blocks.nth(index)
            title = (await block.locator(TITLE_SELECTOR).inner_text()).strip()
            data_item = await block.get_attribute("data-item")
            class_name = await block.get_attribute("class") or ""
            if not data_item:
                continue

            sprint_items.append(
                {
                    "title": title,
                    "data_item": data_item,
                    "is_active": "jacpbiz-sidebar-block--actived" in class_name,
                    "detail_url": DETAIL_URL_TEMPLATE.format(sprint_id=data_item),
                }
            )

        modified_payload = empty_modified_payload()
        semaphore = asyncio.Semaphore(CONCURRENCY)
        sprint_results = await asyncio.gather(
            *(process_sprint(context, sprint_item, semaphore, modified_payload) for sprint_item in sprint_items)
        )

        OUTPUT_PATH.write_text(
            json.dumps(
                {
                    "list_url": LIST_URL,
                    "count": len(sprint_results),
                    "items": sprint_results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"已写入 JSON: {OUTPUT_PATH}")

        thursday_payload = build_thursday_payload(sprint_results)
        THURSDAY_OUTPUT_PATH.write_text(
            json.dumps(thursday_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"已写入本周四需求 JSON: {THURSDAY_OUTPUT_PATH} "
            f"(target_date={thursday_payload['target_date']}, count={thursday_payload['count']})"
        )

        submit_test_payload = build_filtered_payload(thursday_payload, "plan_submit_test_date")
        THURSDAY_SUBMIT_TEST_OUTPUT_PATH.write_text(
            json.dumps(submit_test_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"已写入本周四提测需求 JSON: {THURSDAY_SUBMIT_TEST_OUTPUT_PATH} "
            f"(count={submit_test_payload['count']})"
        )

        online_payload = build_filtered_payload(thursday_payload, "plan_date")
        THURSDAY_ONLINE_OUTPUT_PATH.write_text(
            json.dumps(online_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"已写入本周四上线需求 JSON: {THURSDAY_ONLINE_OUTPUT_PATH} "
            f"(count={online_payload['count']})"
        )

        MODIFIED_OUTPUT_PATH.write_text(
            json.dumps(modified_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"已写入周四改周五修改记录 JSON: {MODIFIED_OUTPUT_PATH} "
            f"(modified={modified_payload['count']}, failed={len(modified_payload.get('failed_items', []))})"
        )
        report_path = generate_report()
        print(f"已更新修改结果 HTML: {report_path}")

        print(f"{BEFORE_CLOSE_WAIT_MS / 1000:.0f} 秒后自动关闭浏览器。")
        await list_page.wait_for_timeout(BEFORE_CLOSE_WAIT_MS)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
