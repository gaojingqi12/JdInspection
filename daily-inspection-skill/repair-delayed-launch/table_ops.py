import time

from common import clean_text, log, norm_header
from config import TARGET_STATUS_HEADER, TARGET_STATUS_VALUE, TEAM_SPACE_TARGET


def select_page_size_1000(frame, container):
    pager = container.locator(".el-pagination").first
    pager.wait_for(state="visible", timeout=15000)

    size_input_candidates = [
        pager.locator(".el-select .el-input__inner").first,
        pager.locator("input.el-input__inner[readonly='readonly']").first,
    ]

    size_input = None
    for cand in size_input_candidates:
        try:
            if cand.count() > 0 and cand.is_visible():
                size_input = cand
                break
        except Exception:
            pass

    if size_input is None:
        raise RuntimeError("未找到分页大小选择框")

    current_text = clean_text(size_input.input_value() or "")
    log(f"当前分页大小显示值: {current_text}")

    if "1000" in current_text:
        log("当前已经是 1000条/页，无需切换")
        return

    size_input.click(force=True)
    frame.page.wait_for_timeout(1200)
    log("已点击分页大小选择框")

    option = None
    option_candidates = [
        frame.locator(".el-select-dropdown__item").get_by_text("1000条/页", exact=True),
        frame.locator(".el-select-dropdown__item").get_by_text("1000 条/页", exact=True),
        frame.get_by_text("1000条/页", exact=True),
        frame.get_by_text("1000 条/页", exact=True),
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
        except Exception:
            pass

    if option is None:
        raise RuntimeError("未找到“1000条/页”选项")

    option.click(force=True)
    frame.page.wait_for_timeout(2500)
    log("已切换分页大小为 1000条/页")

    loading = container.locator(".loading")
    if loading.count() > 0:
        try:
            loading.first.wait_for(state="hidden", timeout=20000)
        except Exception:
            pass

    rows = container.locator("tbody tr.vxe-body--row")
    if rows.count() > 0:
        rows.first.wait_for(state="visible", timeout=20000)

    log("切换分页大小后表格已重新加载")


def wait_table_loaded(container):
    table = container.locator("div.table-render").first
    table.wait_for(state="visible", timeout=20000)

    loading = container.locator(".loading")
    if loading.count() > 0:
        try:
            loading.first.wait_for(state="hidden", timeout=20000)
        except Exception:
            pass

    rows = container.locator("tbody tr.vxe-body--row")
    if rows.count() > 0:
        rows.first.wait_for(state="visible", timeout=20000)

    log("表格已加载完成")
    return table


def get_header_indexes(table):
    headers = table.locator("thead th .content")
    raw_headers = [clean_text(x.inner_text()) for x in headers.all()]
    norm_headers = [norm_header(x) for x in raw_headers]

    log(f"表头: {raw_headers}")

    def find_idx(keyword):
        for i, h in enumerate(norm_headers):
            if keyword in h:
                return i
        return -1

    code_idx = find_idx("需求编码")
    name_idx = find_idx("需求名称")
    status_idx = find_idx(TARGET_STATUS_HEADER)
    team_space_idx = find_idx("团队空间")

    if min(code_idx, name_idx, status_idx, team_space_idx) < 0:
        raise RuntimeError(
            "表头定位失败，"
            f"code_idx={code_idx}, name_idx={name_idx}, status_idx={status_idx}, team_space_idx={team_space_idx}, "
            f"headers={raw_headers}"
        )

    return code_idx, name_idx, status_idx, team_space_idx


def extract_rows_from_current_page(table, code_idx, name_idx, status_idx, team_space_idx):
    results = []
    rows = table.locator("tbody tr.vxe-body--row")

    row_count = rows.count()
    log(f"当前页行数: {row_count}")

    for i in range(row_count):
        row = rows.nth(i)
        cells = row.locator("td")
        cell_count = cells.count()
        if cell_count == 0:
            continue

        def cell_text(idx):
            if idx >= cell_count:
                return ""
            return clean_text(cells.nth(idx).inner_text())

        code = cell_text(code_idx)
        name = cell_text(name_idx)
        status = cell_text(status_idx)
        team_space = cell_text(team_space_idx)

        if not code and not name and not status and not team_space:
            continue

        if status == TARGET_STATUS_VALUE and team_space == TEAM_SPACE_TARGET:
            results.append(
                {
                    "需求编码": code,
                    "需求名称": name,
                    "团队空间": team_space,
                    TARGET_STATUS_HEADER: status,
                }
            )

    return results


def go_next_page(container):
    pager = container.locator(".el-pagination").first
    if pager.count() == 0:
        return False

    next_btn = pager.locator("button.btn-next").first
    if next_btn.count() == 0:
        return False

    cls = next_btn.get_attribute("class") or ""
    if "is-disabled" in cls or "disabled" in cls:
        return False

    try:
        next_btn.click(timeout=3000)
        time.sleep(1.5)
        return True
    except Exception:
        return False


def go_first_page(container):
    pager = container.locator(".el-pagination").first
    if pager.count() == 0:
        return False

    prev_btn = pager.locator("button.btn-prev").first
    if prev_btn.count() == 0:
        return False

    moved = False
    while True:
        cls = prev_btn.get_attribute("class") or ""
        if "is-disabled" in cls or "disabled" in cls:
            return moved

        try:
            prev_btn.click(timeout=3000)
            time.sleep(1.5)
            moved = True
        except Exception as e:
            log(f"回到第一页失败: {e}")
            return moved
