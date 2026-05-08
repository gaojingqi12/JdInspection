import json
import time
from pathlib import Path


def log(msg: str):
    print(f"[DEBUG] {msg}")


def clean_text(s: str) -> str:
    if not s:
        return ""
    return " ".join(s.replace("\xa0", " ").split()).strip()


def norm_header(s: str) -> str:
    s = clean_text(s)
    s = s.replace(".", "").replace("。", "").replace(" ", "")
    return s


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        log(f"历史文件为空，按空状态处理: {path}")
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log(f"历史文件 JSON 格式异常，按空状态处理: {path} | {e}")
        return {}


def dump_json(path: Path, data: dict):
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def keep_browser_open():
    log("浏览器已保持打开，按 Ctrl+C 结束脚本")
    while True:
        time.sleep(60)


def save_daily_results(path: Path, data: dict):
    """
    保存当天筛选结果，同时保留之前已经记录过的点击和修改状态。
    这样脚本重跑时，不会把 clicked_codes / modified_codes 清空。
    """
    existing = load_json(path)
    merged = {
        "date_range": data.get("date_range", ""),
        "department_c3": data.get("department_c3", ""),
        "team_space": data.get("team_space", ""),
        "results": data.get("results") or [],
        "clicked_codes": existing.get("clicked_codes") or [],
        "clicked_items": existing.get("clicked_items") or [],
        "clicked_count": existing.get("clicked_count") or 0,
        "modified_codes": existing.get("modified_codes") or [],
        "modified_items": existing.get("modified_items") or [],
        "modified_count": existing.get("modified_count") or 0,
        "modify_failed_items": existing.get("modify_failed_items") or [],
    }
    dump_json(path, merged)
