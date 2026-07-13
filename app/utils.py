"""不依賴 GUI 或資料庫的共用函式。"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, TypeVar

T = TypeVar('T')


def normalize_stock_code(value: str) -> str:
    """保留前導零，移除空白與誤輸入的 Yahoo 後綴。"""
    text = str(value or '').strip().upper()
    for suffix in ('.TW', '.TWO'):
        if text.endswith(suffix):
            return text[:-len(suffix)]
    return text


def stock_code_from_symbol(symbol: str) -> str:
    """0050.TW → 0050；6488.TWO → 6488。"""
    return normalize_stock_code(symbol)


def market_from_symbol(symbol: str) -> str:
    """依 Yahoo 後綴推定市場；.TWO 無法可靠區分上櫃與興櫃。"""
    upper = symbol.upper()
    if upper.endswith('.TW'):
        return 'TWSE'
    if upper.endswith('.TWO'):
        return 'TPEX'
    return 'AUTO'


def build_symbol(stock_code: str, market_segment: str) -> str:
    """依使用者指定市場建立 Yahoo symbol。"""
    code = normalize_stock_code(stock_code)
    if not code:
        return ''
    if market_segment == 'TWSE':
        return f'{code}.TW'
    if market_segment in {'TPEX', 'EMERGING'}:
        return f'{code}.TWO'
    return code


def chunks(items: list[T], size: int) -> Iterator[list[T]]:
    """將清單切成固定大小批次。"""
    for start in range(0, len(items), size):
        yield items[start:start + size]


def iso_date(value) -> str:
    """將 pandas Timestamp、datetime 或字串轉為 YYYY-MM-DD。"""
    if value is None:
        return ''
    try:
        if hasattr(value, 'to_pydatetime'):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d')
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OverflowError):
        text = str(value)
        return text[:10] if len(text) >= 10 else ''



def contains_cjk(value: str) -> bool:
    """判斷文字是否包含常見中日韓統一表意文字。"""
    return any('\u4e00' <= char <= '\u9fff' for char in str(value or ''))

def money(value: float) -> str:
    return f'{value:,.0f}'


def decimal(value: float, digits: int = 2) -> str:
    return f'{value:,.{digits}f}'


def percent(value: float) -> str:
    return f'{value:,.2f}%'
