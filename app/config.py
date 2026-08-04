"""集中管理程式設定。"""

from app.branding import (
    APP_BUNDLE_IDENTIFIER,
    APP_CATEGORY,
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
)
from app.paths import (
    DATA_DIR,
    DATABASE_PATH,
    EXPORT_DIR,
    LOG_FILE_PATH,
    NAME_OVERRIDES_PATH,
    SETTINGS_PATH,
    YFINANCE_CACHE_DIR,
)

APP_TITLE = APP_NAME
WINDOW_SIZE = '1880x1220'

MARKET_CHOICES = {
    'AUTO': '自動判斷',
    'TWSE': '上市／上市 ETF（.TW）',
    'TPEX': '上櫃／上櫃 ETF（.TWO）',
    'EMERGING': '興櫃（通常為 .TWO，Yahoo 覆蓋不保證）',
}

MARKET_LABEL_TO_KEY = {label: key for key, label in MARKET_CHOICES.items()}

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
YAHOO_TW_DIVIDEND_PAGE = 'https://tw.stock.yahoo.com/quote/{symbol}/dividend'

DIVIDEND_SOURCE_CHOICES = {
    'BOTH': '兩者（建議：歷史＋已公告）',
    'YFINANCE': '僅 yfinance API（歷史股利／股票分割）',
    'SCRAPER': '僅 Yahoo 台灣股利政策爬蟲',
}
DIVIDEND_SOURCE_LABEL_TO_KEY = {
    label: key for key, label in DIVIDEND_SOURCE_CHOICES.items()
}

SINGLE_TEST_CHOICES = {
    'ALL': '全部測試（行情＋歷史＋公告）',
    'QUOTE': '僅測試行情',
    'YFINANCE': '僅測試 yfinance 歷史股利／股票分割',
    'SCRAPER': '僅測試 Yahoo 台灣股利政策爬蟲',
}
SINGLE_TEST_LABEL_TO_KEY = {
    label: key for key, label in SINGLE_TEST_CHOICES.items()
}
