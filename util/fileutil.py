# util/fileutil.py — обновлённая версия с кроссплатформенным путём логов

import os
from datetime import datetime

# Базовый каталог для логов:
#   <Пользователь>/Documents/v7_terminal/logs
DEFAULT_LOG_DIR = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "v7_terminal",
    "logs",
)

TXT_LOG = "mppt_log.txt"
XLSX_LOG = "mppt_log.xlsx"


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def get_log_paths(base_dir: str | None = None):
    base = base_dir or DEFAULT_LOG_DIR
    ensure_dir(base)
    return (
        os.path.join(base, TXT_LOG),
        os.path.join(base, XLSX_LOG),
    )


def timestamp_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
