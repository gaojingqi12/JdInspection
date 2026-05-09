from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class DailyInspectionRenderer:
    template_dir: Path
    parse_numberish: Callable[[Any], Any]
    build_overview: Callable[[dict], list[dict]]
    build_repair_metrics: Callable[[dict], dict[str, dict]]
    repair_metric_config: dict[str, dict]

    def __post_init__(self) -> None:
        object.__setattr__(self, "template", self._load_template("daily-inspection.md"))

    def daily_inspection_assessment(self, summary: dict) -> dict:
        biweekly_delivery_rate = self._numeric_metric_value(self._overview_value(summary, "biweekly_delivery_rate"))
        technical_refactor_rate = self._numeric_metric_value(self._overview_value(summary, "technical_refactor_working_hours_rate"))

        delayed_test_needed_repair_count = self._repair_needed_count(summary, "delayed_test")
        delayed_online_needed_repair_count = self._repair_needed_count(summary, "delayed_online")
        continuous = summary.get("continuous_delivery") or {}
        continuous_metrics = continuous.get("metrics") or {}
        ai = summary.get("ai_inspection") or {}

        delayed_test_normal = delayed_test_needed_repair_count == 0
        delayed_online_normal = delayed_online_needed_repair_count == 0
        biweekly_delivery_normal = biweekly_delivery_rate is not None and biweekly_delivery_rate >= 50
        technical_refactor_normal = technical_refactor_rate is not None and technical_refactor_rate <= 10

        checks = [
            {
                "name": "延期提测需求数",
                "value": self._count_text(delayed_test_needed_repair_count),
                "threshold": "= 0",
                "normal": delayed_test_normal,
                "abnormal_reason": "大于 0",
            },
            {
                "name": "延期上线需求数",
                "value": self._count_text(delayed_online_needed_repair_count),
                "threshold": "= 0",
                "normal": delayed_online_normal,
                "abnormal_reason": "大于 0",
            },
            {
                "name": "双周交付率",
                "value": self._percent_text(biweekly_delivery_rate),
                "threshold": ">= 50%",
                "normal": biweekly_delivery_normal,
                "abnormal_reason": "低于 50%",
            },
            {
                "name": "技改工时占比",
                "value": self._percent_text(technical_refactor_rate),
                "threshold": "<= 10%",
                "normal": technical_refactor_normal,
                "abnormal_reason": "高于 10%",
            },
        ]
        abnormal_checks = [item for item in checks if not item["normal"]]

        template_values = {
            "inspection_date_short": self._daily_inspection_date_text(summary.get("inspection_date") or ""),
            "display_domain": summary.get("display_domain") or summary.get("department_c3") or "-",
            "delayed_test_icon": self._status_icon(delayed_test_normal),
            "delayed_online_icon": self._status_icon(delayed_online_normal),
            "biweekly_delivery_icon": self._status_icon(biweekly_delivery_normal),
            "technical_refactor_icon": self._status_icon(technical_refactor_normal),
            "biweekly_delivery_rate": self._percent_text(biweekly_delivery_rate),
            "technical_refactor_rate": self._percent_text(technical_refactor_rate),
            "delayed_test_repair_count": self._count_text(delayed_test_needed_repair_count),
            "delayed_online_repair_count": self._count_text(delayed_online_needed_repair_count),
            "ai_non_deep_users": self._count_text(ai.get("count")),
            "team_space_online_requirements": self._count_text(continuous_metrics.get("team_space_dev_test_online_requirements")),
            "continuous_delivery_requirements": self._count_text(continuous_metrics.get("team_space_continuous_delivery_dev_test_online_requirements")),
            "continuous_delivery_rate": self._percent_text(continuous_metrics.get("continuous_delivery_team_space_online_requirement_rate"), fixed=False),
            "repair_detail_block": self._build_repair_detail_block(summary),
        }
        return {
            "status": "abnormal" if abnormal_checks else "normal",
            "checks": checks,
            "abnormal_items": abnormal_checks,
            "selected_template_name": "daily_inspection",
            "selected_template": self.template.format(**template_values),
            "template": self.template,
        }

    def _load_template(self, filename: str) -> str:
        return (self.template_dir / filename).read_text(encoding="utf-8").strip()

    def _numeric_metric_value(self, value):
        parsed = self.parse_numberish(value)
        return parsed if isinstance(parsed, (int, float)) else None

    def _percent_text(self, value, fixed: bool = True) -> str:
        number = self._numeric_metric_value(value)
        if number is None:
            return "-"
        if not fixed:
            return f"{number:g}%"
        return f"{number:.2f}%"

    def _count_text(self, value) -> str:
        number = self._numeric_metric_value(value)
        if number is None:
            return "-"
        return f"{number:g}"

    def _status_icon(self, is_normal: bool) -> str:
        return "✅" if is_normal else "⚠️"

    def _daily_inspection_date_text(self, value: str) -> str:
        text = str(value or "").strip()
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return text or "-"
        return f"{parsed.month}.{parsed.day:02d}"

    def _overview_value(self, summary: dict, key: str):
        for card in self.build_overview(summary):
            if card.get("key") == key:
                return card.get("value")
        return None

    def _repair_needed_count(self, summary: dict, repair_type: str) -> int | float:
        repair_metrics = self.build_repair_metrics(summary)
        return self._numeric_metric_value((repair_metrics.get(repair_type) or {}).get("value")) or 0

    def _repair_type_label(self, repair_type: str) -> str:
        return {
            "delayed_test": "延期提测",
            "delayed_online": "延期上线",
        }.get(repair_type, repair_type or "-")

    def _repair_count_label(self, repair_type: str) -> str:
        config = self.repair_metric_config.get(repair_type) or {}
        return str(config.get("count_label") or "")

    def _first_text(self, item: dict, *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _repair_summary_details(self, repair: dict) -> list[dict]:
        repair_summary = repair.get("summary") or {}
        details = repair_summary.get("成功明细")
        if isinstance(details, list) and details:
            return [item for item in details if isinstance(item, dict)]

        raw_json = repair.get("raw_json")
        if not isinstance(raw_json, dict):
            return []

        results = raw_json.get("results") if isinstance(raw_json.get("results"), list) else []
        clicked_items = raw_json.get("clicked_items") if isinstance(raw_json.get("clicked_items"), list) else []
        modified_items = raw_json.get("modified_items") if isinstance(raw_json.get("modified_items"), list) else []
        merged_by_code: dict[str, dict] = {}
        for collection in (results, clicked_items, modified_items):
            for item in collection:
                if not isinstance(item, dict):
                    continue
                code = self._first_text(item, "需求编码")
                if not code:
                    continue
                merged_by_code.setdefault(code, {}).update(item)
        return list(merged_by_code.values())

    def _build_repair_detail_block(self, summary: dict) -> str:
        sections: list[str] = []
        for repair in summary.get("repair_inspections", []):
            repair_type = str(repair.get("repair_type") or "")
            count_label = self._repair_count_label(repair_type)
            repair_summary = repair.get("summary") or {}
            needed_count = self._numeric_metric_value(repair_summary.get(count_label)) if count_label else None
            if needed_count is None:
                needed_count = 0
            if not needed_count:
                continue

            label = self._repair_type_label(repair_type)
            details = self._repair_summary_details(repair)
            if not details:
                sections.append(
                    f"⚠️ 需要修复：{label}\n"
                    "- 负责人：未获取\n"
                    "- 链接：未获取"
                )
                continue

            lines = [f"⚠️ 需要修复：{label}"]
            for item in details:
                code = self._first_text(item, "需求编码")
                name = self._first_text(item, "需求名称")
                owner = self._first_text(item, "研发负责人") or "未获取"
                link = self._first_text(item, "跳转地址", "页面URL") or "未获取"
                requirement = " | ".join(part for part in (code, name) if part) or "-"
                lines.append(f"- 需求：{requirement}")
                lines.append(f"  负责人：{owner}")
                lines.append(f"  链接：{link}")
            sections.append("\n".join(lines))

        if not sections:
            return ""
        return "\n" + "\n\n".join(sections) + "\n"
