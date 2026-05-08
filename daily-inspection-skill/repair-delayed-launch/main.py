from datetime import date

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from common import keep_browser_open, log, save_daily_results
from config import DEPARTMENT_C3, HISTORY_DIR, KEEP_BROWSER_OPEN, TARGET_STATUS_HEADER, TARGET_STATUS_VALUE, TEAM_SPACE_TARGET, URL
from dashboard import (
    click_chart_filter_button,
    click_query_button,
    close_filter_panel,
    collapse_sidebar_if_possible,
    fill_card_finish_date_range,
    find_target_container,
    find_target_frame,
    select_department_c3_by_enter,
)
from table_ops import (
    extract_rows_from_current_page,
    get_header_indexes,
    go_next_page,
    select_page_size_1000,
    wait_table_loaded,
)
from workflow import click_requirements_from_json


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)

            try:
                page.wait_for_load_state("networkidle", timeout=18000)
            except PlaywrightTimeoutError:
                log("networkidle 未等到，继续执行")

            page.wait_for_timeout(2500)
            collapse_sidebar_if_possible(page)

            frame = find_target_frame(page, timeout_ms=45000)
            container = find_target_container(frame)
            container.scroll_into_view_if_needed()
            page.wait_for_timeout(1200)

            click_chart_filter_button(frame, container)
            start_date, end_date = fill_card_finish_date_range(frame)
            select_department_c3_by_enter(frame, DEPARTMENT_C3)
            click_query_button(frame)
            close_filter_panel(frame)

            select_page_size_1000(frame, container)
            table = wait_table_loaded(container)
            code_idx, name_idx, status_idx, team_space_idx = get_header_indexes(table)

            all_results = []
            seen = set()

            while True:
                current_page_rows = extract_rows_from_current_page(
                    table, code_idx, name_idx, status_idx, team_space_idx
                )

                for item in current_page_rows:
                    key = item["需求编码"] or item["需求名称"]
                    if key and key not in seen:
                        seen.add(key)
                        all_results.append(item)

                if not go_next_page(container):
                    break

                table = wait_table_loaded(container)
                page.wait_for_timeout(800)

            print(f"\n===== {TARGET_STATUS_VALUE}需求 =====")
            for i, item in enumerate(all_results, 1):
                print(f"{i}. {item['需求编码']} | {item['需求名称']} | {item[TARGET_STATUS_HEADER]}")

            out_file = HISTORY_DIR / f"{date.today().strftime('%Y-%m-%d')}.json"
            save_daily_results(
                out_file,
                {
                    "date_range": f"{start_date} ~ {end_date}",
                    "department_c3": DEPARTMENT_C3,
                    "team_space": TEAM_SPACE_TARGET,
                    "results": all_results,
                },
            )

            log(f"共筛出 {len(all_results)} 条，已保存到: {out_file}")
            click_requirements_from_json(
                frame, container, out_file=out_file, code_idx=code_idx, name_idx=name_idx
            )

        except Exception as e:
            log(f"执行失败: {e}")
            raise
        finally:
            if KEEP_BROWSER_OPEN:
                keep_browser_open()
            else:
                browser.close()


if __name__ == "__main__":
    main()
