"""開發環境與 macOS App 的檔案路徑管理。

直接執行原始碼時，沿用專案內的 data／exports 資料夾，方便開發與測試。
打包成 macOS App 後，程式本體位於唯讀的 .app 內，因此持股資料庫、設定、
yfinance 快取與匯出檔案必須改存到使用者可寫入的位置。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.branding import APP_NAME

IS_FROZEN = bool(getattr(sys, 'frozen', False))
SOURCE_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', SOURCE_ROOT))

if IS_FROZEN and sys.platform == 'darwin':
    DATA_DIR = Path.home() / 'Library' / 'Application Support' / APP_NAME
    CACHE_DIR = Path.home() / 'Library' / 'Caches' / APP_NAME
    LOG_DIR = Path.home() / 'Library' / 'Logs' / APP_NAME
    EXPORT_DIR = Path.home() / 'Documents' / f'{APP_NAME}匯出'
    DEFAULT_NAME_OVERRIDES_PATH = RESOURCE_ROOT / 'defaults' / 'name_overrides.csv'
else:
    DATA_DIR = SOURCE_ROOT / 'data'
    CACHE_DIR = DATA_DIR / 'yfinance_cache'
    LOG_DIR = DATA_DIR / 'logs'
    EXPORT_DIR = SOURCE_ROOT / 'exports'
    DEFAULT_NAME_OVERRIDES_PATH = SOURCE_ROOT / 'defaults' / 'name_overrides.csv'

DATABASE_PATH = DATA_DIR / 'portfolio_yfinance.db'
SETTINGS_PATH = DATA_DIR / 'app_settings.json'
NAME_OVERRIDES_PATH = DATA_DIR / 'name_overrides.csv'
YFINANCE_CACHE_DIR = CACHE_DIR / 'yfinance'
LOG_FILE_PATH = LOG_DIR / 'app.log'


def ensure_runtime_directories() -> None:
    """建立可寫入資料夾，並在第一次啟動時放入中文名稱範本。"""
    for directory in (DATA_DIR, CACHE_DIR, LOG_DIR, EXPORT_DIR, YFINANCE_CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    if not NAME_OVERRIDES_PATH.exists() and DEFAULT_NAME_OVERRIDES_PATH.exists():
        shutil.copy2(DEFAULT_NAME_OVERRIDES_PATH, NAME_OVERRIDES_PATH)
