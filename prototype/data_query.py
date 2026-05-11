from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PRIMITIVE_TYPES = (str, int, float, bool, type(None))
MAX_FIELD_TEXT = 300
MAX_RECORDS_PER_SOURCE = 1200


FIELD_ALIASES = {
    "ai_code_local_submit_rate": [
        "AI代码本地提交占比",
        "AI 代码本地提交占比",
        "AI代码提交率",
        "AI 代码提交率",
        "AI提交率",
        "代码提交率",
        "ai代码提交率",
    ],
    "is_deep_user": ["是否深度用户", "深度用户", "AI深度用户", "AI 深度用户"],
    "continuous_delivery_team_space_online_requirement_rate": ["持续交付占比", "持续交付率"],
    "biweekly_delivery_rate": ["双周交付率", "双周交付"],
    "technical_refactor_working_hours_rate": ["技术改造工时占比", "技改工时占比"],
    "delayed_test_requirements": ["延期提测需求数", "延期提测数", "延期提测"],
    "delayed_online_requirements": ["延期上线需求数", "延期上线数", "延期上线"],
    "owner": ["负责人", "研发负责人", "owner"],
    "url": ["链接", "跳转地址", "页面URL", "url"],
}


FIELD_LABELS = {
    "ai_code_local_submit_rate": "AI代码本地提交占比",
    "is_deep_user": "是否深度用户",
    "continuous_delivery_team_space_online_requirement_rate": "持续交付占比",
    "biweekly_delivery_rate": "双周交付率",
    "technical_refactor_working_hours_rate": "技术改造工时占比",
    "delayed_test_requirements": "延期提测需求数",
    "delayed_online_requirements": "延期上线需求数",
    "owner": "负责人",
    "url": "链接",
}


PERCENT_FIELDS = {
    "ai_code_local_submit_rate",
    "continuous_delivery_team_space_online_requirement_rate",
    "biweekly_delivery_rate",
    "technical_refactor_working_hours_rate",
    "delay_test_rate_okr",
    "delay_online_rate",
}


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", "", text)
    return text


def clean_name(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"[（(].*?[）)]", "", text).strip()


def safe_read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_primitive(value: Any) -> bool:
    return isinstance(value, PRIMITIVE_TYPES)


def compact_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_TEXT:
        return value[: MAX_FIELD_TEXT - 3] + "..."
    return value


def source_label(path: Path, root_dir: Path) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return str(path)


def flatten_records(payload: Any, source: str, path: str = "$", records: list[dict[str, Any]] | None = None, depth: int = 0) -> list[dict[str, Any]]:
    records = records if records is not None else []
    if len(records) >= MAX_RECORDS_PER_SOURCE or depth > 10:
        return records

    if isinstance(payload, dict):
        fields = {
            str(key): compact_value(value)
            for key, value in payload.items()
            if is_primitive(value)
        }
        if fields:
            title = (
                fields.get("name")
                or fields.get("姓名")
                or fields.get("用户姓名")
                or fields.get("owner")
                or fields.get("负责人")
                or fields.get("研发负责人")
                or fields.get("indicator_name")
                or fields.get("title")
                or fields.get("skill_name")
                or path
            )
            records.append(
                {
                    "source": source,
                    "path": path,
                    "title": str(title or path),
                    "fields": fields,
                    "text": json.dumps(fields, ensure_ascii=False),
                }
            )
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                flatten_records(value, source, f"{path}.{key}", records, depth + 1)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if len(records) >= MAX_RECORDS_PER_SOURCE:
                break
            if isinstance(item, (dict, list)):
                flatten_records(item, source, f"{path}[{index}]", records, depth + 1)
            elif is_primitive(item):
                records.append(
                    {
                        "source": source,
                        "path": f"{path}[{index}]",
                        "title": str(item),
                        "fields": {"value": compact_value(item)},
                        "text": str(item),
                    }
                )
    return records


def wanted_fields(query: str) -> set[str]:
    normalized = normalize_text(query)
    fields: set[str] = set()
    for field, aliases in FIELD_ALIASES.items():
        if normalize_text(field) in normalized:
            fields.add(field)
            continue
        if any(normalize_text(alias) in normalized for alias in aliases):
            fields.add(field)
    return fields


def equivalent_field_names(field: str) -> set[str]:
    names = {field, FIELD_LABELS.get(field, field)}
    names.update(FIELD_ALIASES.get(field, []))
    return {str(name) for name in names if name}


def record_has_field(record: dict[str, Any], field: str) -> bool:
    fields = record.get("fields") or {}
    aliases = {normalize_text(name) for name in equivalent_field_names(field)}
    return any(normalize_text(key) in aliases for key in fields)


def get_record_field(record: dict[str, Any], field: str) -> tuple[str, Any] | None:
    fields = record.get("fields") or {}
    aliases = {normalize_text(name) for name in equivalent_field_names(field)}
    for key, value in fields.items():
        if normalize_text(key) in aliases:
            return key, value
    return None


def split_query_terms(query: str) -> list[str]:
    raw_terms = re.split(r"[\s,，。；;:：、/\\|?？!！的是多少为]+", query or "")
    terms = [term.strip() for term in raw_terms if len(term.strip()) >= 2]
    normalized = normalize_text(query)
    if normalized and len(normalized) <= 40:
        terms.append(normalized)
    return list(dict.fromkeys(terms))


def score_record(record: dict[str, Any], query: str, fields: set[str]) -> int:
    query_norm = normalize_text(query)
    text_norm = normalize_text(f"{record.get('title')} {record.get('path')} {record.get('text')}")
    score = 0

    for term in split_query_terms(query):
        term_norm = normalize_text(term)
        if term_norm and term_norm in text_norm:
            score += min(18, len(term_norm) * 2)

    record_fields = record.get("fields") or {}
    for key, value in record_fields.items():
        value_text = str(value or "")
        base_name = clean_name(value_text)
        if base_name and len(base_name) >= 2 and normalize_text(base_name) in query_norm:
            score += 36
        if value_text and normalize_text(value_text) in query_norm:
            score += 20
        if query_norm and query_norm in normalize_text(value_text):
            score += 12
        if normalize_text(key) in query_norm:
            score += 8

    if fields:
        matched_fields = [field for field in fields if record_has_field(record, field)]
        if matched_fields:
            score += 30 + 8 * len(matched_fields)
        else:
            score -= 8

    if record.get("path", "").endswith(".users") or ".users[" in str(record.get("path")):
        score += 4
    return score


def format_value(key: str, value: Any) -> str:
    if value is None or value == "":
        return "-"
    if key in PERCENT_FIELDS or "%" in str(FIELD_LABELS.get(key, "")) or "占比" in str(FIELD_LABELS.get(key, "")):
        if isinstance(value, (int, float)):
            return f"{value:g}%"
    return str(value)


def result_fact(record: dict[str, Any], fields: set[str]) -> str:
    record_fields = record.get("fields") or {}
    name = (
        record_fields.get("name")
        or record_fields.get("姓名")
        or record_fields.get("用户姓名")
        or record_fields.get("owner")
        or record_fields.get("负责人")
        or record_fields.get("研发负责人")
        or record.get("title")
    )
    erp = record_fields.get("erp") or record_fields.get("用户erp") or record_fields.get("用户ERP")
    parts = []
    selected = fields or set()
    if selected:
        for field in selected:
            pair = get_record_field(record, field)
            if pair:
                key, value = pair
                parts.append(f"{FIELD_LABELS.get(field, key)}：{format_value(field, value)}")
    if not parts:
        for key, value in list(record_fields.items())[:8]:
            parts.append(f"{key}：{format_value(key, value)}")
    who = str(name or record.get("title") or "-")
    if erp:
        who = f"{who}（{erp}）"
    return f"{who}：" + "，".join(parts)


def inspection_data_paths(root_dir: Path) -> list[Path]:
    paths = [
        root_dir / "daily-inspection-skill" / "joyclaw-daily-inspection-orchestrator-skill" / "out" / "weekly-inspection-summary.json",
        root_dir / "friday-inspection-skill" / "scripts" / "out" / "ine_metrics.json",
        root_dir / "daily-inspection-skill" / "inspection-config.json",
        root_dir / "daily-inspection-skill" / "ContinuousDelivery-inspection" / "out" / "continuous_delivery_2026-05-11.json",
        root_dir / "thursday-to-friday-adjustment" / "thursday_demands.json",
        root_dir / "thursday-to-friday-adjustment" / "thursday_submit_test_demands.json",
        root_dir / "thursday-to-friday-adjustment" / "thursday_online_demands.json",
        root_dir / "thursday-to-friday-adjustment" / "thursday_to_friday_modified.json",
    ]
    ai_out = root_dir / "daily-inspection-skill" / "AI-inspection" / "out"
    if ai_out.exists():
        paths.extend(sorted(ai_out.glob("non_deep_users_*.json"), reverse=True)[:5])
    repair_dirs = [
        root_dir / "daily-inspection-skill" / "reschedule-delayed-test " / "history",
        root_dir / "daily-inspection-skill" / "repair-delayed-launch" / "history",
    ]
    for directory in repair_dirs:
        if directory.exists():
            paths.extend(sorted(directory.glob("*.json"), reverse=True)[:5])
    return [path for path in paths if path.exists()]


def query_inspection_data(root_dir: Path, query: str, limit: int = 8) -> dict[str, Any]:
    query = str(query or "").strip()
    limit = max(1, min(int(limit or 8), 20))
    fields = wanted_fields(query)
    all_matches: list[dict[str, Any]] = []
    sources: list[str] = []

    for path in inspection_data_paths(root_dir):
        payload = safe_read_json(path)
        if payload is None:
            continue
        label = source_label(path, root_dir)
        sources.append(label)
        records = flatten_records(payload, label)
        for record in records:
            score = score_record(record, query, fields)
            if score > 0:
                all_matches.append({**record, "score": score})

    all_matches.sort(key=lambda item: item.get("score", 0), reverse=True)
    matches = []
    for item in all_matches[:limit]:
        matches.append(
            {
                "score": item.get("score"),
                "source": item.get("source"),
                "path": item.get("path"),
                "title": item.get("title"),
                "fields": item.get("fields"),
                "fact": result_fact(item, fields),
            }
        )

    return {
        "query": query,
        "matched_fields": sorted(fields),
        "match_count": len(all_matches),
        "sources": sources,
        "matches": matches,
        "answer_hint": "\n".join(f"- {item['fact']}（来源：{item['source']} {item['path']}）" for item in matches[:5]),
    }
