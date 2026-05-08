from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_FILENAME = "inspection-config.json"


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for path in (current, *current.parents):
        if (path / CONFIG_FILENAME).exists():
            return path

    raise FileNotFoundError(f"未找到 {CONFIG_FILENAME}")


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    path = find_repo_root() / CONFIG_FILENAME
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def config_path(*keys: str, default: Any = None) -> Any:
    value: Any = load_config()
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def require_config(*keys: str) -> Any:
    value = config_path(*keys, default=None)
    if value is None:
        joined = ".".join(keys)
        raise KeyError(f"配置缺失: {joined}")
    return value


def metric_units(metrics: list[dict[str, Any]]) -> dict[str, str]:
    return {str(item["key"]): str(item.get("unit", "")) for item in metrics}


def metric_headers(metrics: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item["key"]): str(item["source_header"])
        for item in metrics
        if item.get("source_header")
    }


def metric_labels(metrics: list[dict[str, Any]]) -> dict[str, str]:
    return {str(item["key"]): str(item.get("label", item["key"])) for item in metrics}
