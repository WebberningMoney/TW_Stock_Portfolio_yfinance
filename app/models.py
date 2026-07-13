"""跨資料庫、API 與 GUI 共用的資料模型。"""

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Instrument:
    """Yahoo Finance 可查詢的金融商品。"""

    symbol: str
    stock_code: str
    name: str
    exchange: str = ''
    market_segment: str = 'AUTO'
    quote_type: str = ''
    currency: str = 'TWD'
    product_category: str = 'OTHER'
    source: str = 'yfinance'


@dataclass(slots=True)
class Holding:
    """使用者持有的一檔商品。"""

    id: Optional[int]
    stock_code: str
    yahoo_symbol: str
    stock_name: str
    market_segment: str
    shares: int
    total_cost: float

    @property
    def average_cost(self) -> float:
        return self.total_cost / self.shares if self.shares > 0 else 0.0


@dataclass(slots=True)
class MarketQuote:
    """最近交易日行情。"""

    symbol: str
    stock_code: str
    name: str
    close: float
    previous_close: float
    change: float
    change_percent: float
    volume: float
    trade_date: str
    currency: str = 'TWD'


@dataclass(slots=True)
class CorporateAction:
    """現金股利或股票分割事件。

    action_date：股利使用除息日；分割使用事件日。
    payment_date：Yahoo 台灣股利政策頁可取得時，保存現金發放日。
    period：例如 2026Q2、2025。
    announcement_status：ANNOUNCED／EX_DATE_PASSED／PAID 等狀態。
    """

    symbol: str
    stock_code: str
    stock_name: str
    action_date: str
    action_type: str  # DIVIDEND 或 SPLIT
    value: float
    source: str = 'yfinance'
    period: str = ''
    payment_date: str = ''
    announcement_status: str = ''
