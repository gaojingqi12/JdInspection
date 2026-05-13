from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent / "data"
AI_CONFIG_PATH = DATA_DIR / "ai-config.json"
AI_CONFIG_LOCK = threading.Lock()
DEFAULT_BASE_URL_VALUE = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_MODEL_VALUE = "mimo-v2.5-pro"
BASE_URL_ENV = "XUNJIAN_BASE_URL"
MODEL_ENV = "XUNJIAN_MODEL"
API_KEY_ENV = "XUNJIAN_API_KEY"

MODEL_ALIASES = {
    "mimo-v2.5-pro": "mimo-v2.5-pro",
    "mimo-v2.5": "mimo-v2.5",
    "mimo-v2-pro": "mimo-v2-pro",
    "mimo-v2-omni": "mimo-v2-omni",
    "MiMo-V2.5-Pro".lower(): "mimo-v2.5-pro",
    "MiMo-V2.5".lower(): "mimo-v2.5",
    "MiMo-V2-Pro".lower(): "mimo-v2-pro",
    "MiMo-V2-Omni".lower(): "mimo-v2-omni",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


DEFAULT_BASE_URL = env_value(BASE_URL_ENV) or DEFAULT_BASE_URL_VALUE
DEFAULT_MODEL = env_value(MODEL_ENV) or DEFAULT_MODEL_VALUE
DEFAULT_API_KEY = env_value(API_KEY_ENV)


def normalize_model_name(model: str) -> str:
    text = str(model or "").strip()
    if not text:
        return DEFAULT_MODEL
    return MODEL_ALIASES.get(text.lower(), text)


def default_ai_config() -> dict[str, str]:
    return {
        "base_url": DEFAULT_BASE_URL,
        "model": normalize_model_name(DEFAULT_MODEL),
        "api_key": DEFAULT_API_KEY,
        "updated_at": "",
    }


def load_saved_ai_config() -> dict[str, Any]:
    saved = read_json_file(AI_CONFIG_PATH, {})
    return saved if isinstance(saved, dict) else {}


def load_ai_config() -> dict[str, str]:
    config = default_ai_config()
    saved = load_saved_ai_config()
    config.update({key: value for key, value in saved.items() if value is not None})
    config["base_url"] = str(config.get("base_url") or DEFAULT_BASE_URL).strip()
    config["model"] = normalize_model_name(str(config.get("model") or DEFAULT_MODEL))
    env_api_key = env_value(API_KEY_ENV)
    config["api_key"] = env_api_key or str(config.get("api_key") or "").strip()
    return config


def save_ai_config(config: dict[str, Any]) -> dict[str, str]:
    current = load_ai_config()
    saved_current = load_saved_ai_config()
    base_url = str(config.get("base_url") or current.get("base_url") or DEFAULT_BASE_URL).strip()
    model = normalize_model_name(str(config.get("model") or current.get("model") or DEFAULT_MODEL))
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        api_key = str(saved_current.get("api_key") or "").strip()
    saved = {
        "base_url": base_url,
        "model": model,
        "updated_at": now_text(),
    }
    if api_key:
        saved["api_key"] = api_key
    write_json_file(AI_CONFIG_PATH, saved)
    return load_ai_config()


def api_key_mask(api_key: str) -> str:
    if not api_key:
        return ""
    return "*" * 12 + api_key[-4:]


def public_ai_config(config: dict[str, Any]) -> dict[str, Any]:
    api_key = str(config.get("api_key") or "")
    return {
        "base_url": config.get("base_url") or DEFAULT_BASE_URL,
        "model": config.get("model") or DEFAULT_MODEL,
        "has_api_key": bool(api_key),
        "api_key_mask": api_key_mask(api_key),
        "api_key_source": "env" if env_value(API_KEY_ENV) else ("local" if api_key else ""),
        "updated_at": config.get("updated_at") or "",
    }
