import time
from pathlib import Path

from common import clean_text, dump_json, load_json, log
from config import (
    HOVER_DATE_FIELD_ONLY,
    LOCATE_RELEASE_CARD_ONLY,
    STOP_AFTER_FIRST_JUMP,
    STOP_ON_MODIFY_FAILURE,
    TARGET_DATE_FIELD_LABEL,
)
from detail_page import (
    click_drill_jump_if_present,
    close_drill_dialog_if_present,
    hover_date_field,
    locate_release_card,
    return_to_table_page,
    update_target_date,
)
from table_ops import go_first_page, go_next_page, wait_table_loaded


def first_visible_locator(locator, limit: int = 10, timeout_ms: int = 500):
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


def find_cell_index_by_text(cells, expected_text: str) -> int:
    if not expected_text:
        return -1

    try:
        cell_count = cells.count()
    except Exception:
        return -1

    for i in range(cell_count):
        try:
            text = clean_text(cells.nth(i).inner_text(timeout=1000))
        except Exception:
            continue

        if text == expected_text or expected_text in text:
            return i

    return -1


def get_new_page_after_click(page, pages_before):
    new_pages = [opened_page for opened_page in page.context.pages if opened_page not in pages_before]
    if not new_pages:
        return None

    popup = new_pages[-1]
    try:
        popup.wait_for_load_state("domcontentloaded", timeout=12000)
    except Exception:
        pass
    try:
        popup.bring_to_front()
        log(f"点击需求后已直接打开新页面: {popup.url}")
    except Exception:
        pass
    return popup


def click_locator_and_capture_popup(frame, locator):
    page = frame.page
    pages_before = list(page.context.pages)

    try:
        locator.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        locator.click(timeout=4000, force=True)
    except Exception as e:
        log(f"点击候选元素失败: {e}")
        return None

    page.wait_for_timeout(1200)

    popup = get_new_page_after_click(page, pages_before)
    if popup is not None:
        return popup

    popup = click_drill_jump_if_present(frame, timeout_ms=7000)
    if popup is not None:
        return popup

    close_drill_dialog_if_present(frame)
    return None


def get_name_click_targets(name_cell, name: str):
    targets = []
    selectors = [
        ".can-drill",
        "[class*='drill']",
        "a",
        "button",
        "[role='button']",
        ".vxe-cell--label",
        ".vxe-cell",
        "span",
    ]

    for selector in selectors:
        try:
            locator = name_cell.locator(selector)
            if name:
                named = first_visible_locator(locator.filter(has_text=name), limit=10)
                if named is not None:
                    targets.append(named)

            visible = first_visible_locator(locator, limit=10)
            if visible is not None:
                targets.append(visible)
        except Exception:
            pass

    targets.append(name_cell)
    return targets


def find_item_by_code(items, code: str):
    for item in items:
        if clean_text(item.get("需求编码")) == code:
            return item
    return None


def upsert_item_by_code(items, record: dict):
    code = clean_text(record.get("需求编码"))
    if not code:
        items.append(record)
        return

    existing = find_item_by_code(items, code)
    if existing is None:
        items.append(record)
        return

    existing.update(record)


def has_completed_json_metadata(item: dict) -> bool:
    if not item:
        return False
    required_fields = [
        "研发负责人",
        "跳转地址",
        f"修正后{TARGET_DATE_FIELD_LABEL}",
    ]
    return all(clean_text(item.get(field)) for field in required_fields)


def try_click_row_name_by_code(frame, container, code: str, name: str, name_idx: int, code_idx: int):
    """
    在当前分页表格中按“需求编码”匹配到行后，点击“需求名称”单元格。
    返回跳转打开的新页面；当前页没找到或点击失败时返回 None。
    """
    table = wait_table_loaded(container)
    rows = table.locator("tbody tr.vxe-body--row")
    row_count = rows.count()
    log(f"开始扫描当前页可见行以点击需求，row_count={row_count}, code_idx={code_idx}, name_idx={name_idx}, code={code}")

    for i in range(row_count):
        row = rows.nth(i)
        cells = row.locator("td")
        if cells.count() == 0:
            continue

        try:
            row_code = clean_text(cells.nth(code_idx).inner_text())
        except Exception:
            row_code = ""

        matched_code_idx = code_idx if row_code == code else find_cell_index_by_text(cells, code)
        if matched_code_idx < 0:
            continue

        try:
            matched_name_idx = find_cell_index_by_text(cells, name)
            if matched_name_idx < 0:
                matched_name_idx = name_idx

            name_cell = cells.nth(matched_name_idx)
            name_cell.scroll_into_view_if_needed()
            name_text = clean_text(name_cell.inner_text(timeout=1000))
            log(
                f"已匹配需求行: row={i}, code_col={matched_code_idx}, "
                f"name_col={matched_name_idx}, name_cell={name_text}"
            )

            for target_idx, target in enumerate(get_name_click_targets(name_cell, name)):
                log(f"尝试点击需求名称候选元素: row={i}, target={target_idx}")
                popup = click_locator_and_capture_popup(frame, target)
                if popup is not None:
                    return popup

            log(f"已找到需求行但所有点击候选都未打开详情: {code} | {name}")
            return None
        except Exception as e:
            log(f"点击需求名称失败，code={code}, row={i}, error={e}")
            return None

    return None


def click_requirements_from_json(frame, container, out_file: Path, code_idx: int, name_idx: int):
    """
    根据当日 json 的 results 逐个点击需求名称。
    点击时以“需求编码”判重；已修改过且已有研发负责人的需求不会再处理，并把修改记录回写到 json。
    """
    data = load_json(out_file)
    results = data.get("results") or []
    if not results:
        log("json results 为空，跳过点击")
        return

    clicked_codes = set(data.get("clicked_codes") or [])
    clicked_items = data.get("clicked_items") or []
    modified_codes = set(data.get("modified_codes") or [])
    modified_items = data.get("modified_items") or []
    failed_items = data.get("modify_failed_items") or []

    total = len(results)
    log(f"准备按 json 点击并修改，共 {total} 条（已修改 {len(modified_codes)} 条）")

    if go_first_page(container):
        frame.page.wait_for_timeout(800)
        log("开始点击前已回到第一页")
    else:
        log("当前已在第一页，或无需翻页")

    for idx, item in enumerate(results, 1):
        code = clean_text(item.get("需求编码"))
        name = clean_text(item.get("需求名称"))
        if not code:
            continue

        existing_modified_item = find_item_by_code(modified_items, code)
        if code in modified_codes and has_completed_json_metadata(existing_modified_item or {}):
            log(f"[{idx}/{total}] 已修改过，跳过: {code} | {name}")
            continue
        if code in modified_codes:
            log(f"[{idx}/{total}] 已修改过但 JSON 信息不完整，继续打开详情补提取: {code} | {name}")
        if code in clicked_codes:
            log(f"[{idx}/{total}] 曾点击过但没有修改记录，继续补改: {code} | {name}")

        log(f"[{idx}/{total}] 尝试点击: {code} | {name}")

        popup = None
        while True:
            popup = try_click_row_name_by_code(
                frame,
                container,
                code=code,
                name=name,
                name_idx=name_idx,
                code_idx=code_idx,
            )
            if popup is not None:
                break

            if not go_next_page(container):
                break

            frame.page.wait_for_timeout(800)

        if popup is None:
            log(f"未在表格中找到该需求编码（可能被过滤/不在当前列表）: {code}")
            continue

        if LOCATE_RELEASE_CARD_ONLY:
            popup.bring_to_front()
            locate_release_card(popup)
            log("已停在跳转页调试“周期与进度”卡片定位，不继续修改或关闭页面")
            return

        if HOVER_DATE_FIELD_ONLY:
            popup.bring_to_front()
            hover_date_field(popup, TARGET_DATE_FIELD_LABEL)
            log("已停在跳转页调试 hover，不继续修改或关闭页面")
            return

        try:
            modified_record = update_target_date(popup, code=code, name=name)
        except Exception as e:
            log(f"修改{TARGET_DATE_FIELD_LABEL}失败: {code} | {e}")
            failed_items.append(
                {
                    "需求编码": code,
                    "需求名称": name,
                    "修改字段": TARGET_DATE_FIELD_LABEL,
                    "失败原因": str(e),
                    "failed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            data["modify_failed_items"] = failed_items
            dump_json(out_file, data)
            if STOP_ON_MODIFY_FAILURE:
                try:
                    popup.bring_to_front()
                except Exception:
                    pass
                log("修改失败，已保留跳转页面用于排查，停止继续处理后续需求")
                return
            return_to_table_page(frame, popup)
            continue

        return_to_table_page(frame, popup)

        jump_url = modified_record.get("跳转地址") or modified_record.get("页面URL") or ""
        clicked_item = find_item_by_code(clicked_items, code)
        if clicked_item is None:
            clicked_items.append(
                {
                    "需求编码": code,
                    "需求名称": name,
                    "跳转地址": jump_url,
                    "clicked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        else:
            clicked_item["需求名称"] = name
            clicked_item["跳转地址"] = jump_url
            clicked_item.setdefault("clicked_at", time.strftime("%Y-%m-%d %H:%M:%S"))
        clicked_codes.add(code)
        modified_codes.add(code)
        upsert_item_by_code(modified_items, modified_record)

        result_item = find_item_by_code(results, code)
        if result_item is not None and modified_record.get("研发负责人"):
            result_item["研发负责人"] = modified_record["研发负责人"]
        if result_item is not None:
            result_item[f"修正后{TARGET_DATE_FIELD_LABEL}"] = modified_record.get("修改后", "")
            result_item["跳转地址"] = modified_record.get("跳转地址") or modified_record.get("页面URL") or ""

        data["clicked_codes"] = sorted(clicked_codes)
        data["clicked_items"] = clicked_items
        data["clicked_count"] = len(clicked_codes)
        data["modified_codes"] = sorted(modified_codes)
        data["modified_items"] = modified_items
        data["modified_count"] = len(modified_codes)
        dump_json(out_file, data)

        log(f"已修改并记录: {code}（累计 {len(modified_codes)}）")
        if STOP_AFTER_FIRST_JUMP:
            log("已按当前配置打开第一个跳转页面，停止继续点击后续需求")
            return
