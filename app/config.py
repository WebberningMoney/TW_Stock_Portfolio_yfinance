"""
集中管理程式設定。

本版本的行情及公司行動核心使用 yfinance；繁中名稱補強使用 Yahoo Finance
台灣地區的公開搜尋／報價頁，不呼叫 TWSE 或 TPEx OpenAPI。
"""

from pathlib import Path

APP_TITLE = '台股庫存、損益與配息管理（yfinance v1.3）'
WINDOW_SIZE = '1540x930'

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
DATABASE_PATH = DATA_DIR / 'portfolio_yfinance.db'
EXPORT_DIR = PROJECT_ROOT / 'exports'
YFINANCE_CACHE_DIR = DATA_DIR / 'yfinance_cache'

SCREENER_PAGE_SIZE = 250
SCREENER_MAX_PAGES = 30

QUOTE_BATCH_SIZE = 50
QUOTE_PERIOD = '1mo'
QUOTE_INTERVAL = '1d'
ACTION_PERIOD = 'max'

MARKET_CHOICES = {
    'AUTO': '自動判斷',
    'TWSE': '上市／上市 ETF（.TW）',
    'TPEX': '上櫃／上櫃 ETF（.TWO）',
    'EMERGING': '興櫃（通常為 .TWO，Yahoo 覆蓋不保證）',
}

MARKET_LABEL_TO_KEY = {label: key for key, label in MARKET_CHOICES.items()}

# 建立商品清冊時可選擇的範圍。預設不下載權證及其他衍生商品。
UNIVERSE_CATEGORY_CHOICES = {
    'TWSE_STOCK': '上市公司股票',
    'TPEX_STOCK': '上櫃／興櫃公司股票（Yahoo .TWO）',
    'TWSE_ETF': '上市 ETF／基金商品',
    'TPEX_ETF': '上櫃 ETF／基金商品',
    'ETN': 'ETN／其他交易所商品',
    'WARRANT': '權證／衍生商品',
    'OTHER': '其他無法分類商品',
}
DEFAULT_UNIVERSE_CATEGORIES = {
    'TWSE_STOCK',
    'TPEX_STOCK',
    'TWSE_ETF',
    'TPEX_ETF',
}

LOCALIZED_NAME_BATCH_SIZE = 50
LOCALIZED_NAME_WORKERS = 6
YAHOO_LOCALIZED_QUOTE_URL = 'https://query1.finance.yahoo.com/v7/finance/quote'
YAHOO_LOCALIZED_SEARCH_URL = 'https://query2.finance.yahoo.com/v1/finance/search'
YAHOO_TW_QUOTE_PAGE = 'https://tw.stock.yahoo.com/quote/{symbol}'
NAME_OVERRIDES_PATH = DATA_DIR / 'name_overrides.csv'

ENABLE_PRICE_REPAIR = True
