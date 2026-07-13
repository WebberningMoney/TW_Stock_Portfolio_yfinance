"""
集中管理程式設定。

本版本的網路資料核心完全使用 yfinance；不再呼叫 TWSE 或 TPEx OpenAPI。
"""

from pathlib import Path

APP_TITLE = '台股庫存、損益與配息管理（yfinance）'
WINDOW_SIZE = '1480x880'

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
DATABASE_PATH = DATA_DIR / 'portfolio_yfinance.db'
EXPORT_DIR = PROJECT_ROOT / 'exports'
YFINANCE_CACHE_DIR = DATA_DIR / 'yfinance_cache'

# Yahoo Screener 單次最多通常為 250 筆；以 offset 分頁並設防呆頁數。
SCREENER_PAGE_SIZE = 250
SCREENER_MAX_PAGES = 30

# yf.download 批次太大較容易被 Yahoo 限流；100 檔是保守折衷。
QUOTE_BATCH_SIZE = 100
QUOTE_PERIOD = '1mo'
QUOTE_INTERVAL = '1d'

# 公司行動只針對持股同步，避免對全市場逐檔發出數千次請求。
ACTION_PERIOD = 'max'

MARKET_CHOICES = {
    'AUTO': '自動判斷',
    'TWSE': '上市／上市 ETF（.TW）',
    'TPEX': '上櫃／上櫃 ETF（.TWO）',
    'EMERGING': '興櫃（通常為 .TWO，Yahoo 覆蓋不保證）',
}
