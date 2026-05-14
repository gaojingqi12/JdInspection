from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from inspection_config import require_config
from render_inspection_summary import render_summary_markdown_to_file


SKILL_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = SKILL_DIR / "out"
HTML_OUTPUT_PATH = ROOT_DIR / "index.html"
REPORT_SCREENSHOT_DIR = ROOT_DIR / "assets" / "screenshots"
TEMPLATE_PATH = SKILL_DIR / "assets" / "weekly-line-report-template.html"
AI_DIR = ROOT_DIR / "AI-inspection"
CONTINUOUS_DELIVERY_DIR = ROOT_DIR / "ContinuousDelivery-inspection"
DEFAULT_REPAIR_PYTHON = Path(sys.executable)
REPAIR_TIMEOUT_SECONDS = 45 * 60
COMMON_CONFIG = require_config("common")
OKR_CONFIG = require_config("okr")
REPAIR_SOURCE_CONFIG = require_config("repair")
AI_CONFIG = require_config("ai")
CONTINUOUS_DELIVERY_CONFIG = require_config("continuous_delivery")
DEPARTMENT_C3 = COMMON_CONFIG["department_c3"]
DISPLAY_DOMAIN = COMMON_CONFIG.get("display_domain") or DEPARTMENT_C3
CONTINUOUS_METRIC_KEYS = [item["key"] for item in CONTINUOUS_DELIVERY_CONFIG["metrics"]]
CONTINUOUS_METRIC_UNITS = {item["key"]: item.get("unit", "") for item in CONTINUOUS_DELIVERY_CONFIG["metrics"]}


@dataclass(frozen=True)
class MetricConfig:
    key: str
    label: str
    unit: str


@dataclass(frozen=True)
class SkillConfig:
    directory: str
    skill_name: str
    indicator_type: str
    indicator_name: str
    department_c3: str
    screenshot: str
    focus_metric_key: str
    metrics: tuple[MetricConfig, ...]


@dataclass(frozen=True)
class RepairConfig:
    repair_type: str
    title: str
    directory: str
    trigger_indicator_type: str
    trigger_metric_key: str
    trigger_metric_label: str
    inspection_item: str
    count_label: str
    date_field_label: str
    corrected_date_key: str
    status_key: str


def build_skill_config(key: str) -> SkillConfig:
    item = OKR_CONFIG[key]
    return SkillConfig(
        directory=item["directory"],
        skill_name=item["skill_name"],
        indicator_type=item["indicator_type"],
        indicator_name=item["indicator_name"],
        department_c3=DEPARTMENT_C3,
        screenshot=item["query_screenshot"],
        focus_metric_key=item["focus_metric_key"],
        metrics=tuple(
            MetricConfig(metric["key"], metric.get("label", metric["key"]), metric.get("unit", ""))
            for metric in item.get("metrics", [])
        ),
    )


def build_repair_config(key: str) -> RepairConfig:
    item = REPAIR_SOURCE_CONFIG[key]
    return RepairConfig(
        repair_type=item["repair_type"],
        title=item["title"],
        directory=item["directory"],
        trigger_indicator_type=item["trigger_indicator_type"],
        trigger_metric_key=item["trigger_metric_key"],
        trigger_metric_label=item["trigger_metric_label"],
        inspection_item=item["inspection_item"],
        count_label=item["count_label"],
        date_field_label=item["target_date_field_label"],
        corrected_date_key=item["corrected_date_key"],
        status_key=item["status_key"],
    )


SKILLS: tuple[SkillConfig, ...] = tuple(
    build_skill_config(key)
    for key in (
        "delay_test_rate",
        "delay_online_rate",
        "technical_refactor_working_hours",
        "bi_weekly_delivery_rate",
    )
)


REPAIR_CONFIGS: tuple[RepairConfig, ...] = tuple(
    build_repair_config(key)
    for key in ("delayed_test", "delayed_online")
)

REPAIR_FOCUS_SERIES: dict[str, dict[str, str]] = {
    "delay_test_rate": {
        "repair_type": "delayed_test",
        "name": "延期提测需求",
        "metric_key": "delayed_test_requirements",
        "label": f"延期提测需求数（{DISPLAY_DOMAIN}）",
    },
    "delay_online_rate": {
        "repair_type": "delayed_online",
        "name": "延期上线需求",
        "metric_key": "delayed_online_requirements",
        "label": f"延期上线需求数（{DISPLAY_DOMAIN}）",
    },
}


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def current_week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_numberish(value: Any) -> Any:
    if isinstance(value, (int, float)) or value is None:
        return value
    if not isinstance(value, str):
        return value

    raw = value.strip().replace(",", "")
    if not raw:
        return None
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    try:
        return float(raw)
    except ValueError:
        return value


def copy_screenshot_asset(source_path: Path, asset_name: str) -> str:
    if not source_path.exists():
        return ""

    REPORT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = REPORT_SCREENSHOT_DIR / asset_name
    shutil.copy2(source_path, target_path)
    return f"assets/screenshots/{asset_name}"


def skill_screenshot_path(config: SkillConfig) -> Path:
    return ROOT_DIR / config.directory / config.screenshot


def skill_screenshot_asset(config: SkillConfig) -> str:
    return copy_screenshot_asset(skill_screenshot_path(config), f"{config.indicator_type}.png")


def continuous_delivery_screenshot_asset() -> str:
    source = str(CONTINUOUS_DELIVERY_CONFIG.get("query_screenshot", "out/three_cards.png"))
    return copy_screenshot_asset(CONTINUOUS_DELIVERY_DIR / source, "continuous_delivery.png")


def remove_html_file_addresses(payload: Any) -> None:
    """最终 HTML 不暴露本地源文件地址；报告内部截图相对路径保留给 img 使用。"""
    hidden_keys = {"history_dir", "source_json", "output_json", "json", "command", "stdout_tail", "stderr_tail", "raw_json"}
    if isinstance(payload, dict):
        for key in list(payload.keys()):
            if key in hidden_keys:
                payload.pop(key, None)
            else:
                remove_html_file_addresses(payload[key])
    elif isinstance(payload, list):
        for item in payload:
            remove_html_file_addresses(item)


def ga4_measurement_id() -> str:
    return str(os.environ.get("XUNJIAN_GA4_MEASUREMENT_ID") or COMMON_CONFIG.get("ga4_measurement_id") or "").strip()


def ga4_head_html() -> str:
    measurement_id = ga4_measurement_id()
    if not re.fullmatch(r"G-[A-Z0-9]+", measurement_id):
        return ""
    return f"""
  <script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag("js", new Date());
    gtag("config", "{measurement_id}");
    document.addEventListener("click", (event) => {{
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!target || typeof gtag !== "function") return;
      const url = new URL(target.getAttribute("href"), window.location.href);
      gtag("event", url.hostname === window.location.hostname ? "click_internal_link" : "click_external_link", {{
        link_url: url.href,
        link_text: (target.textContent || target.getAttribute("aria-label") || "").trim().slice(0, 100),
        page_path: window.location.pathname
      }});
    }});
  </script>"""


def first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def normalize_ai_user(item: dict[str, Any]) -> dict[str, Any]:
    erp = first_present(item, "erp", "用户erp", "用户 erp", "用户ERP")
    name = first_present(item, "name", "用户姓名", "姓名", "用户erp", "用户 erp", "erp")
    submit_rate = first_present(
        item,
        "ai_code_local_submit_rate",
        "AI代码本地提交占比",
        "AI 代码本地提交占比",
        "AI代码本地提交占比(%)",
        "AI 代码本地提交占比(%)",
    )
    return {
        "erp": erp or "",
        "name": name or "",
        "ai_code_local_submit_rate": parse_numberish(submit_rate),
        "is_deep_user": first_present(item, "is_deep_user", "是否深度用户") or "",
    }


def continuous_metric_value(metrics: dict[str, Any], key: str) -> Any:
    legacy_keys = {
        "team_space_dev_test_online_requirements": "team_space_dev_test_online_requirement_count",
        "team_space_continuous_delivery_dev_test_online_requirements": "team_space_continuous_delivery_dev_test_online_requirement_count",
        "continuous_delivery_team_space_online_requirement_rate": "continuous_delivery_team_space_online_requirement_ratio",
    }
    return parse_numberish(metrics.get(key, metrics.get(legacy_keys.get(key, ""))))


def continuous_metrics_from(data: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = (data or {}).get("metrics") if isinstance(data, dict) else {}
    metrics = metrics if isinstance(metrics, dict) else {}
    return {key: continuous_metric_value(metrics, key) for key in CONTINUOUS_METRIC_KEYS}


def continuous_units_from(data: dict[str, Any] | None = None) -> dict[str, str]:
    units = (data or {}).get("unit") if isinstance(data, dict) else {}
    units = units if isinstance(units, dict) else {}
    return {key: units.get(key, CONTINUOUS_METRIC_UNITS.get(key, "")) for key in CONTINUOUS_METRIC_KEYS}


def empty_continuous_metrics() -> dict[str, Any]:
    return {key: None for key in CONTINUOUS_METRIC_KEYS}


def normalize_continuous_delivery(data: dict[str, Any], today: date) -> dict[str, Any]:
    day = today.isoformat()
    return {
        "date": data.get("date", day),
        "indicator_type": CONTINUOUS_DELIVERY_CONFIG["indicator_type"],
        "indicator_name": data.get("indicator_name", CONTINUOUS_DELIVERY_CONFIG["indicator_name"]),
        "department_c3": data.get("department_c3", DEPARTMENT_C3),
        "status": data.get("status", "success"),
        "metrics": continuous_metrics_from(data),
        "unit": continuous_units_from(data),
        "source": {
            "query_screenshot": continuous_delivery_screenshot_asset(),
            "json": f"../../ContinuousDelivery-inspection/out/continuous_delivery_{day}.json",
        },
        "error": data.get("error", ""),
    }


def load_continuous_delivery(today: date) -> dict[str, Any]:
    day = today.isoformat()
    json_path = CONTINUOUS_DELIVERY_DIR / "out" / f"continuous_delivery_{day}.json"
    legacy_json_path = CONTINUOUS_DELIVERY_DIR / "out" / "history" / f"{day}.json"
    screenshot_path = CONTINUOUS_DELIVERY_DIR / "out" / "three_cards.png"

    if json_path.exists():
        try:
            return normalize_continuous_delivery(read_json(json_path), today)
        except Exception as exc:
            return {
                "date": day,
                "indicator_type": CONTINUOUS_DELIVERY_CONFIG["indicator_type"],
                "indicator_name": CONTINUOUS_DELIVERY_CONFIG["indicator_name"],
                "department_c3": DEPARTMENT_C3,
                "status": "failed",
                "metrics": empty_continuous_metrics(),
                "unit": CONTINUOUS_METRIC_UNITS,
                "source": {
                    "query_screenshot": continuous_delivery_screenshot_asset(),
                    "json": f"../../ContinuousDelivery-inspection/out/continuous_delivery_{day}.json",
                },
                "error": str(exc),
            }

    if legacy_json_path.exists():
        try:
            return normalize_continuous_delivery(read_json(legacy_json_path), today)
        except Exception as exc:
            return {
                "date": day,
                "indicator_type": CONTINUOUS_DELIVERY_CONFIG["indicator_type"],
                "indicator_name": CONTINUOUS_DELIVERY_CONFIG["indicator_name"],
                "department_c3": DEPARTMENT_C3,
                "status": "failed",
                "metrics": empty_continuous_metrics(),
                "unit": CONTINUOUS_METRIC_UNITS,
                "source": {
                    "query_screenshot": continuous_delivery_screenshot_asset(),
                    "json": f"../../ContinuousDelivery-inspection/out/history/{day}.json",
                },
                "error": str(exc),
            }

    return {
        "date": day,
        "indicator_type": CONTINUOUS_DELIVERY_CONFIG["indicator_type"],
        "indicator_name": CONTINUOUS_DELIVERY_CONFIG["indicator_name"],
        "department_c3": DEPARTMENT_C3,
        "status": "missing",
        "metrics": empty_continuous_metrics(),
        "unit": CONTINUOUS_METRIC_UNITS,
        "source": {
            "query_screenshot": continuous_delivery_screenshot_asset() if screenshot_path.exists() else "",
            "json": f"../../ContinuousDelivery-inspection/out/continuous_delivery_{day}.json",
        },
        "error": "当天持续交付 JSON 不存在",
    }


def ai_inspection_target_date(today: date) -> date:
    if today.weekday() == 0:
        return today - timedelta(days=3)
    if today.weekday() == 6:
        return today - timedelta(days=2)
    return today - timedelta(days=1)


def choose_ai_json(inspection_json: Path, query_json: Path) -> Path:
    if inspection_json.exists() and query_json.exists():
        try:
            inspection_data = read_json(inspection_json)
        except Exception:
            return inspection_json
        if isinstance(inspection_data, dict) and (inspection_data.get("inspection_date") or inspection_data.get("query_date")):
            return inspection_json
        if query_json.stat().st_mtime > inspection_json.stat().st_mtime:
            return query_json
        return inspection_json
    if inspection_json.exists():
        return inspection_json
    if query_json.exists():
        return query_json
    return inspection_json


def load_ai_inspection(today: date) -> dict[str, Any]:
    inspection_day = today.isoformat()
    query_day = ai_inspection_target_date(today).isoformat()
    output_json = choose_ai_json(
        AI_DIR / "out" / f"non_deep_user_names_{inspection_day}.json",
        AI_DIR / "out" / f"non_deep_user_names_{query_day}.json",
    )
    source_json = choose_ai_json(
        AI_DIR / "out" / f"non_deep_users_{inspection_day}.json",
        AI_DIR / "out" / f"non_deep_users_{query_day}.json",
    )

    if source_json.exists():
        try:
            raw_data = read_json(source_json)
            raw_users = raw_data if isinstance(raw_data, list) else raw_data.get("users", [])
            users = [
                normalize_ai_user(item)
                for item in raw_users
                if str(first_present(item, "是否深度用户", "is_deep_user") or "").strip() == "否"
            ]
            names = [user["name"] for user in users if user["name"]]
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": AI_CONFIG["indicator_type"],
                "indicator_name": AI_CONFIG["indicator_name"],
                "status": raw_data.get("status", "success") if isinstance(raw_data, dict) else "success",
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}" if output_json.exists() else "",
                "count": raw_data.get("count", len(names)) if isinstance(raw_data, dict) else len(names),
                "names": names,
                "users": users,
            }
        except Exception as exc:
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": AI_CONFIG["indicator_type"],
                "indicator_name": AI_CONFIG["indicator_name"],
                "status": "failed",
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}" if output_json.exists() else "",
                "count": 0,
                "names": [],
                "users": [],
                "error": str(exc),
            }

    if output_json.exists():
        try:
            data = read_json(output_json)
            
            # 支持两种格式：对象格式 (有 users/names 字段) 或 数组格式 (直接是用户列表)
            if isinstance(data, dict):
                users = [normalize_ai_user(item) for item in data.get("users", [])]
                names = data.get("names") or [user["name"] for user in users if user["name"]]
                count = data.get("count", len(names))
                status = data.get("status", "success")
            elif isinstance(data, list):
                # 数组格式：直接是用户列表
                users = [normalize_ai_user(item) for item in data]
                names = [user["name"] for user in users if user["name"]]
                count = len(names)
                status = "success"
            else:
                raise ValueError(f"Unexpected data type: {type(data)}")
            
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": AI_CONFIG["indicator_type"],
                "indicator_name": AI_CONFIG["indicator_name"],
                "status": status,
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}",
                "count": count,
                "names": names,
                "users": users,
            }
        except Exception as exc:
            return {
                "date": inspection_day,
                "inspection_date": inspection_day,
                "query_date": query_day,
                "indicator_type": AI_CONFIG["indicator_type"],
                "indicator_name": AI_CONFIG["indicator_name"],
                "status": "failed",
                "source_json": f"../../AI-inspection/out/{source_json.name}",
                "output_json": f"../../AI-inspection/out/{output_json.name}",
                "count": 0,
                "names": [],
                "users": [],
                "error": str(exc),
            }

    return {
        "date": inspection_day,
        "inspection_date": inspection_day,
        "query_date": query_day,
        "indicator_type": AI_CONFIG["indicator_type"],
        "indicator_name": AI_CONFIG["indicator_name"],
        "status": "missing",
        "source_json": f"../../AI-inspection/out/{source_json.name}",
        "output_json": f"../../AI-inspection/out/{output_json.name}",
        "count": 0,
        "names": [],
        "users": [],
        "error": "当天 AI 巡检 JSON 不存在",
    }


def load_history(config: SkillConfig, start_date: date, end_date: date) -> list[dict[str, Any]]:
    history_dir = ROOT_DIR / config.directory / "out" / "history"
    if not history_dir.exists():
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.json")):
        try:
            item = read_json(path)
            item_date = parse_date(str(item.get("date", path.stem)))
        except Exception:
            continue

        if start_date <= item_date <= end_date:
            rows.append(item)

    return sorted(rows, key=lambda row: str(row.get("date", "")))


def build_skill_summary(config: SkillConfig, rows: list[dict[str, Any]], start_date: date, end_date: date) -> dict[str, Any]:
    history: dict[str, list[dict[str, Any]]] = {metric.key: [] for metric in config.metrics}
    metric_units = {metric.key: metric.unit for metric in config.metrics}

    for row in rows:
        metrics = row.get("metrics") or {}
        for metric in config.metrics:
            history[metric.key].append(
                {
                    "date": row.get("date"),
                    "value": metrics.get(metric.key),
                    "unit": metric.unit,
                }
            )

    statuses = {str(row.get("status", "success")) for row in rows}
    status = "success" if rows and statuses == {"success"} else "partial" if rows else "missing"

    return {
        "skill_name": config.skill_name,
        "indicator_type": config.indicator_type,
        "indicator_name": config.indicator_name,
        "department_c3": config.department_c3,
        "time_range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "status": status,
        "focus_metric_key": config.focus_metric_key,
        "history": history,
        "unit": metric_units,
        "source": {
            "history_dir": f"{config.directory}/out/history",
            "query_screenshot": skill_screenshot_asset(config),
        },
    }


def tail_text(value: Any, max_chars: int = 6000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    elif not isinstance(value, str):
        value = str(value)

    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def metric_value_for_date(summary: dict[str, Any], indicator_type: str, metric_key: str, target_date: date) -> Any:
    target_day = target_date.isoformat()
    for indicator in summary.get("indicators", []):
        if indicator.get("indicator_type") != indicator_type:
            continue

        for point in indicator.get("history", {}).get(metric_key, []):
            if point.get("date") == target_day:
                return point.get("value")

    return None


def raw_metric_value_for_date(config: RepairConfig, target_date: date) -> Any:
    skill_config = next(
        (skill for skill in SKILLS if skill.indicator_type == config.trigger_indicator_type),
        None,
    )
    if not skill_config:
        return None

    json_path = ROOT_DIR / skill_config.directory / "out" / "history" / f"{target_date.isoformat()}.json"
    if not json_path.exists():
        return None

    try:
        data = read_json(json_path)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None

    return metrics.get(config.trigger_metric_key)


def is_positive_number(value: Any) -> bool:
    parsed = parse_numberish(value)
    return isinstance(parsed, (int, float)) and parsed > 0


def repair_history_path(config: RepairConfig, target_date: date) -> Path:
    return ROOT_DIR / config.directory / "history" / f"{target_date.isoformat()}.json"


def repair_config_by_type(repair_type: str) -> RepairConfig | None:
    return next((config for config in REPAIR_CONFIGS if config.repair_type == repair_type), None)


def repair_history_count_points(config: RepairConfig, start_date: date, end_date: date) -> list[dict[str, Any]]:
    history_dir = ROOT_DIR / config.directory / "history"
    if not history_dir.exists():
        return []

    points: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.json")):
        try:
            item_date = parse_date(path.stem)
        except Exception:
            continue

        if not (start_date <= item_date <= end_date):
            continue

        try:
            data = read_json(path)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        results = data.get("results")
        count = len(results) if isinstance(results, list) else 0
        points.append(
            {
                "date": item_date.isoformat(),
                "value": count,
                "unit": "count",
                "source": "repair_history",
                "display_domain": DISPLAY_DOMAIN,
            }
        )

    return points


def repair_python_bin() -> Path:
    configured_value = os.environ.get("XUNJIAN_PYTHON", "").strip()
    if configured_value:
        configured = Path(configured_value).expanduser()
        if configured.exists():
            return configured
        resolved = shutil.which(configured_value)
        if resolved:
            return Path(resolved)
    return DEFAULT_REPAIR_PYTHON


def repair_command_display() -> str:
    return " ".join([str(repair_python_bin()), "main.py"])


def run_repair_script(config: RepairConfig, timeout_seconds: int) -> dict[str, Any]:
    workdir = ROOT_DIR / config.directory
    if not workdir.exists():
        return {
            "status": "missing_script",
            "directory": config.directory,
            "command": "",
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "error": "修复脚本目录不存在",
        }

    python_bin = repair_python_bin()
    command = [str(python_bin), "main.py"]
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        completed = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "directory": config.directory,
            "command": " ".join(command),
            "returncode": None,
            "started_at": started_at,
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stdout_tail": tail_text(exc.stdout or ""),
            "stderr_tail": tail_text(exc.stderr or ""),
            "error": f"修复脚本执行超过 {timeout_seconds} 秒",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "directory": config.directory,
            "command": " ".join(command),
            "returncode": None,
            "started_at": started_at,
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stdout_tail": "",
            "stderr_tail": "",
            "error": str(exc),
        }

    return {
        "status": "success" if completed.returncode == 0 else "failed",
        "directory": config.directory,
        "command": " ".join(command),
        "returncode": completed.returncode,
        "started_at": started_at,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stdout_tail": tail_text(completed.stdout or ""),
        "stderr_tail": tail_text(completed.stderr or ""),
        "error": "" if completed.returncode == 0 else "修复脚本返回非 0 状态",
    }


def list_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def by_requirement_code(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("需求编码", "")).strip(): item
        for item in items
        if str(item.get("需求编码", "")).strip()
    }


def repair_failure_reason(item: dict[str, Any]) -> str:
    return str(
        first_present(
            item,
            "失败原因",
            "error",
            "错误",
            "原因",
            "message",
        )
        or ""
    )


def repair_zero_note(config: RepairConfig) -> str:
    domain = COMMON_CONFIG.get("display_domain") or DEPARTMENT_C3
    return f"{domain}{config.trigger_metric_label}为0。"


def normalize_repair_json(config: RepairConfig, data: dict[str, Any], target_date: date, trigger_count: Any) -> dict[str, Any]:
    results = list_items(data.get("results"))
    clicked_items = list_items(data.get("clicked_items"))
    modified_items = list_items(data.get("modified_items"))
    failed_items = list_items(data.get("modify_failed_items"))

    results_by_code = by_requirement_code(results)
    clicked_by_code = by_requirement_code(clicked_items)
    success_details: list[dict[str, Any]] = []
    missing_details: list[dict[str, Any]] = []

    for item in modified_items:
        code = str(item.get("需求编码", "")).strip()
        merged: dict[str, Any] = {}
        if code:
            merged.update(results_by_code.get(code, {}))
            merged.update(clicked_by_code.get(code, {}))
        merged.update(item)

        corrected_date = first_present(merged, config.corrected_date_key, "修改后") or ""
        jump_url = first_present(merged, "跳转地址", "页面URL") or ""
        field_name = first_present(merged, "修改字段") or config.date_field_label
        page_value = first_present(merged, "页面当前值") or ""

        detail = {
            "需求编码": code,
            "需求名称": first_present(merged, "需求名称") or "",
            "团队空间": first_present(merged, "团队空间") or "",
            config.status_key: first_present(merged, config.status_key) or "",
            "研发负责人": first_present(merged, "研发负责人") or "",
            "修改字段": field_name,
            "修改前": first_present(merged, "修改前") or "",
            "修改后": first_present(merged, "修改后") or "",
            config.corrected_date_key: corrected_date,
            "页面当前值": page_value,
            "是否点击确认": bool(merged.get("是否点击确认")),
            "跳转地址": jump_url,
            "modified_at": first_present(merged, "modified_at") or "",
        }
        success_details.append(detail)

        missing_fields = [
            field
            for field in ("需求编码", "研发负责人", config.corrected_date_key, "跳转地址")
            if not detail.get(field)
        ]
        if field_name != config.date_field_label:
            missing_fields.append("修改字段")
        if page_value and corrected_date and page_value != corrected_date:
            missing_fields.append("页面当前值不一致")

        if missing_fields:
            missing_details.append(
                {
                    "需求编码": code,
                    "需求名称": detail["需求名称"],
                    "缺失字段": missing_fields,
                }
            )

    failure_details = [
        {
            "需求编码": str(item.get("需求编码", "")).strip(),
            "需求名称": first_present(item, "需求名称") or "",
            "修改字段": first_present(item, "修改字段") or config.date_field_label,
            "失败原因": repair_failure_reason(item),
            "failed_at": first_present(item, "failed_at") or "",
        }
        for item in failed_items
    ]

    filtered_count = len(results)
    clicked_count = parse_numberish(data.get("clicked_count", len(clicked_items)))
    modified_count = parse_numberish(data.get("modified_count", len(modified_items)))
    failed_count = len(failed_items)
    notes: list[str] = []

    if failed_count:
        status = "存在失败项"
    elif missing_details:
        status = "需人工复核"
    elif is_positive_number(trigger_count) and not (filtered_count or success_details or failed_count):
        status = "通过"
        notes.append(repair_zero_note(config))
    elif filtered_count and isinstance(modified_count, (int, float)) and modified_count < filtered_count:
        status = "需人工复核"
    else:
        status = "通过"

    if not notes and not results and not success_details and not failure_details and status == "通过":
        notes.append(f"当天无{config.trigger_metric_label.replace('数', '')}明细。")

    return {
        "巡检项": config.inspection_item,
        "巡检日期": target_date.isoformat(),
        "数据周期": first_present(data, "date_range") or "",
        "部门": first_present(data, "department_c3") or "",
        "团队空间": first_present(data, "team_space") or "",
        config.count_label: filtered_count,
        "已点击数": clicked_count,
        "已修复数": modified_count,
        "失败数": failed_count,
        "巡检状态": status,
        "成功明细": success_details,
        "失败明细": failure_details,
        "缺失字段明细": missing_details,
        "备注": notes,
    }


def load_repair_inspection(
    config: RepairConfig,
    target_date: date,
    trigger_count: Any,
    triggered: bool,
    script_result: dict[str, Any],
) -> dict[str, Any]:
    json_path = repair_history_path(config, target_date)
    relative_json_path = str(json_path.relative_to(ROOT_DIR))

    base = {
        "repair_type": config.repair_type,
        "title": config.title,
        "date": target_date.isoformat(),
        "trigger": {
            "indicator_type": config.trigger_indicator_type,
            "metric_key": config.trigger_metric_key,
            "metric_label": config.trigger_metric_label,
            "value": parse_numberish(trigger_count),
            "triggered": triggered,
        },
        "script": script_result,
        "json_file": relative_json_path,
        "json_exists": json_path.exists(),
        "raw_json": None,
        "summary": {
            "巡检项": config.inspection_item,
            "巡检日期": target_date.isoformat(),
            config.count_label: 0,
            "已点击数": 0,
            "已修复数": 0,
            "失败数": 0,
            "巡检状态": "未触发" if not triggered else "无当天JSON",
            "成功明细": [],
            "失败明细": [],
            "缺失字段明细": [],
            "备注": [repair_zero_note(config)] if not triggered else ["未生成当天修复 JSON，无法确认修复结果。"],
        },
    }

    if not json_path.exists():
        if triggered and script_result.get("status") in {"failed", "timeout", "missing_script"}:
            base["summary"]["巡检状态"] = "执行失败"
        return base

    try:
        data = read_json(json_path)
    except Exception as exc:
        base["summary"]["巡检状态"] = "JSON异常"
        base["summary"]["备注"] = [f"当天修复 JSON 读取失败：{exc}"]
        return base

    if not isinstance(data, dict):
        base["summary"]["巡检状态"] = "JSON异常"
        base["summary"]["备注"] = ["当天修复 JSON 不是对象格式。"]
        base["raw_json"] = data
        return base

    summary = normalize_repair_json(config, data, target_date, trigger_count)
    if triggered and script_result.get("status") in {"failed", "timeout", "missing_script"}:
        summary["巡检状态"] = "执行失败"
        summary.setdefault("备注", []).append(script_result.get("error") or "修复脚本执行失败。")

    base["summary"] = summary
    base["raw_json"] = data
    return base


def build_repair_inspections(
    summary: dict[str, Any],
    today: date,
    *,
    skip_repair: bool,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    repairs = []
    for config in REPAIR_CONFIGS:
        trigger_count = raw_metric_value_for_date(config, today)
        if trigger_count is None:
            trigger_count = metric_value_for_date(
                summary,
                config.trigger_indicator_type,
                config.trigger_metric_key,
                today,
            )
        triggered = is_positive_number(trigger_count)

        if triggered and not skip_repair:
            script_result = run_repair_script(config, timeout_seconds)
        elif triggered:
            script_result = {
                "status": "skipped",
                "directory": config.directory,
                "command": repair_command_display(),
                "returncode": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "error": "本次聚合使用 --skip-repair，未执行修复脚本。",
            }
        else:
            script_result = {
                "status": "not_triggered",
                "directory": config.directory,
                "command": repair_command_display(),
                "returncode": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "error": "",
            }

        repairs.append(load_repair_inspection(config, today, trigger_count, triggered, script_result))

    return repairs


def render_html(summary: dict[str, Any], output_path: Path) -> None:
    payload = json.loads(json.dumps({
        **summary,
        "generated_at": summary.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "focus_series": summary.get("focus_series") or build_focus_series(summary),
    }, ensure_ascii=False))
    remove_html_file_addresses(payload)
    content = TEMPLATE_PATH.read_text(encoding="utf-8").replace(
        "__JOYCLAW_WEEKLY_REPORT_JSON__",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    analytics = ga4_head_html()
    if analytics:
        content = content.replace("</head>", f"{analytics}\n</head>", 1)
    output_path.write_text(content, encoding="utf-8")


def build_focus_series(summary: dict[str, Any]) -> list[dict[str, Any]]:
    configs = {config.indicator_type: config for config in SKILLS}
    multi_metric_indicators = {"delay_test_rate", "delay_online_rate"}
    range_data = summary.get("time_range", {})
    start_date = parse_date(str(range_data.get("start_date")))
    end_date = parse_date(str(range_data.get("end_date")))
    series = []
    for indicator in summary.get("indicators", []):
        config = configs.get(indicator.get("indicator_type"))
        if not config:
            continue

        repair_focus = REPAIR_FOCUS_SERIES.get(config.indicator_type)
        if repair_focus:
            repair_config = repair_config_by_type(repair_focus["repair_type"])
            points = repair_history_count_points(repair_config, start_date, end_date) if repair_config else []
            metrics_payload = [
                {
                    "key": repair_focus["metric_key"],
                    "label": repair_focus["label"],
                    "unit": "count",
                    "points": points,
                    "source": "repair_history",
                }
            ]
            series.append(
                {
                    "indicator_type": config.indicator_type,
                    "name": repair_focus["name"],
                    "indicator_name": config.indicator_name,
                    "default_metric_key": repair_focus["metric_key"],
                    "screenshot": indicator.get("source", {}).get("query_screenshot") or skill_screenshot_asset(config),
                    "screenshot_label": "当天巡检截图",
                    "metrics": metrics_payload,
                    "source_note": f"延期需求数读取{DISPLAY_DOMAIN}修复巡检历史，不读取{DEPARTMENT_C3} OKR 汇总数。",
                }
            )
            continue

        if config.indicator_type in multi_metric_indicators:
            metrics = config.metrics
        else:
            metrics = tuple(metric for metric in config.metrics if metric.key == config.focus_metric_key)

        series.append(
            {
                "indicator_type": config.indicator_type,
                "name": {
                    "delay_test_rate": "延期提测率",
                    "delay_online_rate": "延期上线率",
                }.get(config.indicator_type, next(metric.label for metric in metrics)),
                "indicator_name": config.indicator_name,
                "default_metric_key": config.focus_metric_key,
                "screenshot": indicator.get("source", {}).get("query_screenshot") or skill_screenshot_asset(config),
                "screenshot_label": "当天巡检截图",
                "metrics": [
                    {
                        "key": metric.key,
                        "label": metric.label,
                        "unit": metric.unit,
                        "points": indicator.get("history", {}).get(metric.key, []),
                    }
                    for metric in metrics
                ],
            }
        )
    return series


def build_summary(start_date: date, end_date: date) -> dict[str, Any]:
    indicators = []
    for config in SKILLS:
        rows = load_history(config, start_date, end_date)
        indicators.append(build_skill_summary(config, rows, start_date, end_date))

    statuses = {item["status"] for item in indicators}
    status = "success" if statuses == {"success"} else "partial" if "success" in statuses or "partial" in statuses else "missing"

    return {
        "skill_name": "joyclaw-daily-inspection-orchestrator",
        "department_c3": DEPARTMENT_C3,
        "display_domain": DISPLAY_DOMAIN,
        "time_range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "status": status,
        "indicators": indicators,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate current-week JoyClaw inspection history into JSON and HTML reports.")
    parser.add_argument(
        "--skip-repair",
        action="store_true",
        help="只汇总已有修复 JSON，不根据 OKR 延期数量执行修复脚本。",
    )
    parser.add_argument(
        "--repair-timeout",
        type=int,
        default=REPAIR_TIMEOUT_SECONDS,
        help="单个修复脚本的最长执行秒数。",
    )
    args = parser.parse_args()

    today = date.today()
    start_date = current_week_start(today)
    end_date = today

    OUT_DIR.mkdir(exist_ok=True)
    summary = build_summary(start_date, end_date)
    summary["inspection_date"] = today.isoformat()
    summary["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary["repair_inspections"] = build_repair_inspections(
        summary,
        today,
        skip_repair=args.skip_repair,
        timeout_seconds=args.repair_timeout,
    )
    summary["focus_series"] = build_focus_series(summary)
    summary["ai_inspection"] = load_ai_inspection(today)
    summary["continuous_delivery"] = load_continuous_delivery(today)

    json_path = OUT_DIR / "weekly-inspection-summary.json"
    html_path = HTML_OUTPUT_PATH

    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(summary, html_path)
    markdown_path = render_summary_markdown_to_file(summary, summary_json_path=json_path)

    print(f"Wrote {json_path}")
    print(f"Wrote {html_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()
