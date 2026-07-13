"""
yfinance 資料核心。

功能：
1. Yahoo Screener 探索台灣上市／上櫃股票與 ETF。
2. Search 與 .TW/.TWO fallback 解析單一股票代號。
3. yf.download 批次下載最近行情。
4. Ticker.history(actions=True) 取得歷史股利與股票分割。

限制：
- yfinance 可查詢 Yahoo 已收錄的 symbol，但不是官方完整證券代號主檔。
- .TWO 同時涵蓋上櫃及 Yahoo 有收錄的部分興櫃，無法單靠 Yahoo exchange
  欄位精準區分，因此興櫃分類可由使用者手動指定。
- Yahoo 股利事件日期通常是除息日，不是實際入帳日。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import yfinance as yf

from app.config import (
    ACTION_PERIOD,
    QUOTE_BATCH_SIZE,
    QUOTE_INTERVAL,
    QUOTE_PERIOD,
    SCREENER_MAX_PAGES,
    SCREENER_PAGE_SIZE,
    YFINANCE_CACHE_DIR,
)
from app.models import CorporateAction, Instrument, MarketQuote
from app.utils import chunks, iso_date, market_from_symbol, normalize_stock_code, stock_code_from_symbol

ProgressCallback = Callable[[str], None]


class YFinanceApiError(RuntimeError):
    """包裝 Yahoo/yfinance 查詢錯誤。"""


class YFinanceClient:
    """所有行情、商品清冊與公司行動的唯一網路資料來源。"""

    def __init__(self) -> None:
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
        except Exception:
            # 舊版 yfinance 若不支援或快取初始化失敗，不阻止主程式。
            pass

    @staticmethod
    def _instrument_from_quote(quote: dict[str, Any]) -> Instrument | None:
        symbol = str(quote.get('symbol') or '').strip().upper()
        if not symbol.endswith(('.TW', '.TWO')):
            return None

        name = str(
            quote.get('longName')
            or quote.get('shortName')
            or quote.get('displayName')
            or symbol
        ).strip()
        exchange = str(quote.get('exchange') or '').strip().upper()
        quote_type = str(quote.get('quoteType') or '').strip().upper()
        currency = str(quote.get('currency') or 'TWD').strip().upper()

        return Instrument(
            symbol=symbol,
            stock_code=stock_code_from_symbol(symbol),
            name=name,
            exchange=exchange,
            market_segment=market_from_symbol(symbol),
            quote_type=quote_type,
            currency=currency,
        )

    def _screen_query(
        self,
        query: Any,
        progress: ProgressCallback | None = None,
    ) -> list[Instrument]:
        """分頁執行 yfinance screen，並防止 Yahoo 忽略 offset 時無限迴圈。"""
        discovered: dict[str, Instrument] = {}

        for page in range(SCREENER_MAX_PAGES):
            offset = page * SCREENER_PAGE_SIZE
            if progress:
                progress(f'Yahoo Screener 分頁 offset={offset}')

            try:
                response = yf.screen(
                    query,
                    offset=offset,
                    size=SCREENER_PAGE_SIZE,
                    sortField='ticker',
                    sortAsc=True,
                )
            except Exception as exc:
                raise YFinanceApiError(f'Yahoo Screener 查詢失敗：{exc}') from exc

            quotes = response.get('quotes', []) if isinstance(response, dict) else []
            if not quotes:
                break

            before = len(discovered)
            for quote in quotes:
                instrument = self._instrument_from_quote(quote)
                if instrument:
                    discovered[instrument.symbol] = instrument

            # 若這一頁完全沒有新增 symbol，表示 Yahoo 可能重複回傳第一頁。
            if len(discovered) == before:
                break

            total = response.get('total') if isinstance(response, dict) else None
            if len(quotes) < SCREENER_PAGE_SIZE:
                break
            if isinstance(total, int) and offset + len(quotes) >= total:
                break

        return list(discovered.values())

    def discover_taiwan_universe(
        self,
        progress: ProgressCallback | None = None,
    ) -> list[Instrument]:
        """
        探索 Yahoo 可列舉的台灣股票與 ETF。

        TAI = Taiwan Stock Exchange；TWO = Taipei Exchange。
        股票與 ETF 分開查詢後去重。
        """
        if not all(hasattr(yf, name) for name in ('EquityQuery', 'ETFQuery', 'screen')):
            raise YFinanceApiError('目前安裝的 yfinance 太舊，不支援 Screener；請升級 yfinance。')

        queries = [
            ('上市股票', yf.EquityQuery('eq', ['exchange', 'TAI'])),
            ('上櫃／興櫃股票', yf.EquityQuery('eq', ['exchange', 'TWO'])),
            ('上市 ETF', yf.ETFQuery('eq', ['exchange', 'TAI'])),
            ('上櫃 ETF', yf.ETFQuery('eq', ['exchange', 'TWO'])),
        ]

        result: dict[str, Instrument] = {}
        errors: list[str] = []
        for label, query in queries:
            if progress:
                progress(f'正在探索：{label}')
            try:
                for instrument in self._screen_query(query, progress):
                    result[instrument.symbol] = instrument
            except YFinanceApiError as exc:
                # 某一類查詢失敗時仍保留其他類型結果。
                errors.append(f'{label}: {exc}')

        if not result and errors:
            raise YFinanceApiError('；'.join(errors))
        return sorted(result.values(), key=lambda item: item.symbol)

    def resolve_instrument(
        self,
        stock_code: str,
        market_segment: str = 'AUTO',
    ) -> Instrument:
        """
        解析單一台股代號。

        指定市場時直接查 .TW 或 .TWO；AUTO 先 Search，再依序測試兩種後綴。
        """
        code = normalize_stock_code(stock_code)
        if not code:
            raise YFinanceApiError('股票代號不可空白。')

        candidates: list[str] = []
        if market_segment == 'TWSE':
            candidates = [f'{code}.TW']
        elif market_segment in {'TPEX', 'EMERGING'}:
            candidates = [f'{code}.TWO']
        else:
            try:
                search = yf.Search(code, max_results=12, news_count=0, raise_errors=False)
                for quote in getattr(search, 'quotes', []) or []:
                    symbol = str(quote.get('symbol') or '').upper()
                    if stock_code_from_symbol(symbol) == code and symbol.endswith(('.TW', '.TWO')):
                        instrument = self._instrument_from_quote(quote)
                        if instrument:
                            if market_segment == 'EMERGING':
                                instrument.market_segment = 'EMERGING'
                            return instrument
            except Exception:
                # Search 失敗仍可使用直接後綴探測。
                pass
            candidates = [f'{code}.TW', f'{code}.TWO']

        for symbol in candidates:
            try:
                ticker = yf.Ticker(symbol)
                history = ticker.history(
                    period='1mo',
                    interval='1d',
                    auto_adjust=False,
                    actions=False,
                    repair=True,
                    raise_errors=False,
                )
                if history is None or history.empty or 'Close' not in history.columns:
                    continue

                info: dict[str, Any] = {}
                try:
                    info = ticker.get_info() or {}
                except Exception:
                    pass

                name = str(
                    info.get('longName')
                    or info.get('shortName')
                    or symbol
                )
                exchange = str(info.get('exchange') or ('TAI' if symbol.endswith('.TW') else 'TWO'))
                quote_type = str(info.get('quoteType') or '')
                currency = str(info.get('currency') or 'TWD')
                segment = market_from_symbol(symbol)
                if market_segment == 'EMERGING':
                    segment = 'EMERGING'

                return Instrument(
                    symbol=symbol,
                    stock_code=code,
                    name=name,
                    exchange=exchange,
                    market_segment=segment,
                    quote_type=quote_type,
                    currency=currency,
                )
            except Exception:
                continue

        raise YFinanceApiError(
            f'Yahoo Finance 查無 {code}。請確認代號，或指定上市／上櫃／興櫃市場後再試。'
        )

    @staticmethod
    def _extract_symbol_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """兼容 yf.download 單一／多檔及不同 MultiIndex 層級排列。"""
        if data is None or data.empty:
            return pd.DataFrame()
        if not isinstance(data.columns, pd.MultiIndex):
            return data.copy()

        level0 = set(map(str, data.columns.get_level_values(0)))
        level1 = set(map(str, data.columns.get_level_values(1)))
        if symbol in level0:
            return data[symbol].copy()
        if symbol in level1:
            return data.xs(symbol, axis=1, level=1).copy()
        return pd.DataFrame()

    def download_quotes(
        self,
        instruments: list[Instrument],
        progress: ProgressCallback | None = None,
    ) -> tuple[list[MarketQuote], list[str]]:
        """以批次下載方式取得全部指定商品最近交易行情。"""
        by_symbol = {item.symbol: item for item in instruments if item.symbol}
        symbols = sorted(by_symbol)
        quotes: list[MarketQuote] = []
        failed: list[str] = []

        for batch_index, batch in enumerate(chunks(symbols, QUOTE_BATCH_SIZE), start=1):
            if progress:
                progress(f'下載行情第 {batch_index} 批，共 {len(batch)} 檔')
            try:
                data = yf.download(
                    tickers=batch,
                    period=QUOTE_PERIOD,
                    interval=QUOTE_INTERVAL,
                    group_by='ticker',
                    auto_adjust=False,
                    actions=False,
                    threads=min(8, len(batch)),
                    repair=True,
                    progress=False,
                    keepna=False,
                    multi_level_index=True,
                )
            except Exception as exc:
                failed.extend(batch)
                if progress:
                    progress(f'本批行情失敗：{exc}')
                continue

            for symbol in batch:
                frame = self._extract_symbol_frame(data, symbol)
                if frame.empty or 'Close' not in frame.columns:
                    failed.append(symbol)
                    continue

                valid = frame.dropna(subset=['Close'])
                if valid.empty:
                    failed.append(symbol)
                    continue

                last = valid.iloc[-1]
                previous = valid.iloc[-2] if len(valid) >= 2 else last
                close = float(last.get('Close') or 0.0)
                previous_close = float(previous.get('Close') or close)
                change = close - previous_close
                change_percent = change / previous_close * 100 if previous_close else 0.0
                volume = float(last.get('Volume') or 0.0)
                instrument = by_symbol[symbol]

                quotes.append(
                    MarketQuote(
                        symbol=symbol,
                        stock_code=instrument.stock_code,
                        name=instrument.name,
                        close=close,
                        previous_close=previous_close,
                        change=change,
                        change_percent=change_percent,
                        volume=volume,
                        trade_date=iso_date(valid.index[-1]),
                        currency=instrument.currency,
                    )
                )

        return quotes, sorted(set(failed))

    def fetch_actions(
        self,
        instrument: Instrument,
    ) -> list[CorporateAction]:
        """
        取得完整可用歷史股利與股票分割。

        Yahoo 的 Stock Splits 欄位可能也反映部分股票股利／面額調整；
        因資料語意不完全等同台灣法規用語，GUI 會以「分割／股票股利」呈現。
        """
        try:
            history = yf.Ticker(instrument.symbol).history(
                period=ACTION_PERIOD,
                interval='1d',
                auto_adjust=False,
                actions=True,
                repair=True,
                raise_errors=False,
            )
        except Exception as exc:
            raise YFinanceApiError(f'{instrument.symbol} 公司行動下載失敗：{exc}') from exc

        if history is None or history.empty:
            return []

        actions: list[CorporateAction] = []
        for timestamp, row in history.iterrows():
            action_date = iso_date(timestamp)
            dividend = float(row.get('Dividends') or 0.0)
            split = float(row.get('Stock Splits') or 0.0)

            if dividend > 0:
                actions.append(
                    CorporateAction(
                        symbol=instrument.symbol,
                        stock_code=instrument.stock_code,
                        stock_name=instrument.name,
                        action_date=action_date,
                        action_type='DIVIDEND',
                        value=dividend,
                    )
                )
            if split > 0:
                actions.append(
                    CorporateAction(
                        symbol=instrument.symbol,
                        stock_code=instrument.stock_code,
                        stock_name=instrument.name,
                        action_date=action_date,
                        action_type='SPLIT',
                        value=split,
                    )
                )

        return actions
