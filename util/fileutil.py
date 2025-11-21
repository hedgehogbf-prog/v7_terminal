# util/fileutil.py
import os
from datetime import datetime

DEFAULT_LOG_DIR = r"C:\Users\Flashchine\Documents\v7\logs"
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
