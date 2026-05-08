from pathlib import Path
import sys


ROOT_DIR = next(path for path in Path(__file__).resolve().parents if (path / "inspection_config.py").exists())
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from inspection_config import require_config


CONFIG = require_config("repair", "delayed_test")
URL = CONFIG["url"]
CARD_TITLE = CONFIG["card_title"]
FILTER_DATE_LABEL = CONFIG["filter_date_label"]
DEPARTMENT_FILTER_LABEL = CONFIG["department_filter_label"]
DEPARTMENT_C3 = require_config("common", "department_c3")
TEAM_SPACE_TARGET = CONFIG["team_space_target"]
TARGET_STATUS_HEADER = CONFIG["target_status_header"]
TARGET_STATUS_VALUE = CONFIG["target_status_value"]
TARGET_DATE_FIELD_LABEL = CONFIG["target_date_field_label"]
KEEP_BROWSER_OPEN = False
STOP_AFTER_FIRST_JUMP = False
STOP_ON_MODIFY_FAILURE = True
HOVER_DATE_FIELD_ONLY = False
LOCATE_RELEASE_CARD_ONLY = False

BASE_DIR = Path(__file__).resolve().parent
HISTORY_DIR = BASE_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)
