"""
yfinance / Yahoo Finance 資料核心。

功能：
1. 依使用者勾選的市場及商品類型建立台灣商品清冊。
2. 透過 Yahoo 台灣本地化搜尋與報價頁補強繁體中文名稱。
3. 以 yf.download 批次下載行情。
4. 以 Ticker.history(actions=True) 取得股利與股票分割紀錄。

限制：
- yfinance 不是台灣官方證券主檔，只能取得 Yahoo 已收錄的商品。
- Yahoo 的 .TWO 無法可靠區分上櫃與興櫃。
- 股利事件日期通常是除息日，不是實際入帳日。
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import csv
import html
import importlib.util
import logging
import re
import time
from typing import Any

import pandas as pd
import requests
import yfinance as yf

try:
    from yfinance.data import YfData
except ImportError:  # pragma: no cover
    YfData = None

from app.config import (
    LOCALIZED_NAME_BATCH_SIZE,
    LOCALIZED_NAME_WORKERS,
    NAME_OVERRIDES_PATH,
    YFINANCE_CACHE_DIR,
    YAHOO_LOCALIZED_QUOTE_URL,
    YAHOO_LOCALIZED_SEARCH_URL,
    YAHOO_TW_QUOTE_PAGE,
)
from app.models import CorporateAction, Instrument, MarketQuote
from app.settings import RuntimeSettings
from app.utils import (
    chunks,
    contains_cjk,
    iso_date,
    market_from_symbol,
    normalize_stock_code,
    stock_code_from_symbol,
)

ProgressCallback = Callable[[str, int | None, int | None], None]


class YFinanceApiError(RuntimeError):
    """包裝 Yahoo/yfinance 查詢錯誤。"""


def _emit(
    progress: ProgressCallback | None,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if progress:
        progress(message, current, total)


class YFinanceClient:
    """行情、清冊、名稱與股利／分割資料的網路資料來源。"""

    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = (settings or RuntimeSettings()).normalized()
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
        except Exception:
            pass

        self.repair_enabled = bool(
            self.settings.enable_price_repair
            and importlib.util.find_spec('scipy') is not None
        )

        logging.getLogger('yfinance').setLevel(logging.CRITICAL)

        self._yf_data = None
        if YfData is not None:
            try:
                self._yf_data = YfData()
            except Exception:
                self._yf_data = None

        self._ensure_name_override_template()

    def update_settings(self, settings: RuntimeSettings) -> None:
        """套用 GUI 儲存的新設定，不必重啟程式。"""
        self.settings = settings.normalized()
        self.repair_enabled = bool(
            self.settings.enable_price_repair
            and importlib.util.find_spec('scipy') is not None
        )

    @staticmethod
    def _ensure_name_override_template() -> None:
        """
        建立或更新繁中名稱覆寫檔。

        不會刪除使用者原本的內容，只補入範例及已知常用商品。
        """
        NAME_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        defaults = {
            '0050.TW': '元大台灣50',
            '0056.TW': '元大高股息',
            '00919.TW': '群益台灣精選高息',
            '4513.TWO': '福裕',
        }

        existing: dict[str, str] = {}
        if NAME_OVERRIDES_PATH.exists():
            try:
                with NAME_OVERRIDES_PATH.open(
                    'r', encoding='utf-8-sig', newline=''
                ) as file:
                    for row in csv.DictReader(file):
                        symbol = str(row.get('symbol') or '').strip().upper()
                        name = str(row.get('name') or '').strip()
                        if symbol and name:
                            existing[symbol] = name
            except (OSError, csv.Error):
                existing = {}

        changed = False
        for symbol, name in defaults.items():
            if symbol not in existing:
                existing[symbol] = name
                changed = True

        if not NAME_OVERRIDES_PATH.exists() or changed:
            with NAME_OVERRIDES_PATH.open(
                'w', encoding='utf-8-sig', newline=''
            ) as file:
                writer = csv.writer(file)
                writer.writerow(['symbol', 'name'])
                for symbol in sorted(existing):
                    writer.writerow([symbol, existing[symbol]])

    @staticmethod
    def _load_name_overrides() -> dict[str, str]:
        if not NAME_OVERRIDES_PATH.exists():
            return {}

        result: dict[str, str] = {}
        try:
            with NAME_OVERRIDES_PATH.open(
                'r', encoding='utf-8-sig', newline=''
            ) as file:
                for row in csv.DictReader(file):
                    symbol = str(row.get('symbol') or '').strip().upper()
                    name = str(row.get('name') or '').strip()
                    if symbol and name:
                        result[symbol] = name
        except (OSError, csv.Error):
            return {}
        return result

    @staticmethod
    def _classify_product(
        quote: dict[str, Any],
        market_segment: str,
        origin_kind: str,
    ) -> str:
        """將 Yahoo 商品粗分為股票、ETF、ETN、權證或其他。"""
        if origin_kind == 'ETF':
            return 'TWSE_ETF' if market_segment == 'TWSE' else 'TPEX_ETF'

        symbol = str(quote.get('symbol') or '').upper()
        stock_code = stock_code_from_symbol(symbol)
        quote_type = str(quote.get('quoteType') or '').upper()
        name = str(
            quote.get('longName')
            or quote.get('shortName')
            or quote.get('longname')
            or quote.get('shortname')
            or quote.get('displayName')
            or ''
        ).upper()

        if quote_type in {'WARRANT', 'OPTION'} or 'WARRANT' in name or '權證' in name:
            return 'WARRANT'
        if quote_type == 'ETN' or stock_code.startswith('020'):
            return 'ETN'

        # 台灣一般公司股票通常是四位數；A/B 等尾碼可涵蓋部分特別股。
        if re.fullmatch(r'\d{4}[A-Z]?', stock_code):
            return 'TWSE_STOCK' if market_segment == 'TWSE' else 'TPEX_STOCK'

        return 'OTHER'

    @classmethod
    def _instrument_from_quote(
        cls,
        quote: dict[str, Any],
        origin_kind: str,
    ) -> Instrument | None:
        symbol = str(quote.get('symbol') or '').strip().upper()
        if not symbol.endswith(('.TW', '.TWO')):
            return None

        name = str(
            quote.get('longName')
            or quote.get('shortName')
            or quote.get('longname')
            or quote.get('shortname')
            or quote.get('displayName')
            or symbol
        ).strip()
        exchange = str(quote.get('exchange') or '').strip().upper()
        quote_type = str(quote.get('quoteType') or '').strip().upper()
        currency = str(quote.get('currency') or 'TWD').strip().upper()
        market_segment = market_from_symbol(symbol)

        return Instrument(
            symbol=symbol,
            stock_code=stock_code_from_symbol(symbol),
            name=name,
            exchange=exchange,
            market_segment=market_segment,
            quote_type=quote_type,
            currency=currency,
            product_category=cls._classify_product(
                quote, market_segment, origin_kind
            ),
        )

    def _fetch_localized_names_batch(
        self,
        symbols: list[str],
        progress: ProgressCallback | None = None,
    ) -> dict[str, str]:
        """使用 Yahoo quote JSON 批次取得繁中名稱。"""
        if not symbols or self._yf_data is None:
            return {}

        result: dict[str, str] = {}
        batches = list(
            chunks(sorted(set(symbols)), LOCALIZED_NAME_BATCH_SIZE)
        )
        for batch_index, batch in enumerate(batches, start=1):
            _emit(
                progress,
                f'繁中名稱快速補強：第 {batch_index}/{len(batches)} 批',
                batch_index,
                len(batches),
            )
            params = {
                'symbols': ','.join(batch),
                'lang': 'zh-TW',
                'region': 'TW',
                'corsDomain': 'tw.finance.yahoo.com',
            }
            try:
                payload = self._yf_data.get_raw_json(
                    YAHOO_LOCALIZED_QUOTE_URL,
                    params=params,
                    timeout=30,
                )
            except Exception:
                continue

            rows = (
                payload.get('quoteResponse', {}).get('result', [])
                if isinstance(payload, dict)
                else []
            )
            for row in rows:
                symbol = str(row.get('symbol') or '').strip().upper()
                name = str(
                    row.get('longName')
                    or row.get('shortName')
                    or row.get('displayName')
                    or ''
                ).strip()
                if symbol and name and contains_cjk(name):
                    result[symbol] = name

        return result

    @staticmethod
    def _fetch_localized_name_one(symbol: str) -> str:
        """
        單檔繁中名稱補強。

        先查 Yahoo 台灣地區搜尋 JSON；若仍無中文，再解析 Yahoo 奇摩股市
        報價頁標題，例如「福裕(4513.TWO) 走勢圖」。
        """
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 Chrome/124 Safari/537.36'
            )
        }

        try:
            response = requests.get(
                YAHOO_LOCALIZED_SEARCH_URL,
                params={
                    'q': symbol,
                    'lang': 'zh-TW',
                    'region': 'TW',
                    'quotesCount': 8,
                    'newsCount': 0,
                },
                headers=headers,
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            for quote in payload.get('quotes', []):
                quote_symbol = str(quote.get('symbol') or '').upper()
                if quote_symbol != symbol.upper():
                    continue
                name = str(
                    quote.get('longname')
                    or quote.get('shortname')
                    or quote.get('longName')
                    or quote.get('shortName')
                    or ''
                ).strip()
                if contains_cjk(name):
                    return name
        except Exception:
            pass

        try:
            response = requests.get(
                YAHOO_TW_QUOTE_PAGE.format(symbol=symbol),
                headers=headers,
                timeout=12,
            )
            response.raise_for_status()
            match = re.search(
                r'<title[^>]*>(.*?)</title>',
                response.text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match:
                title = html.unescape(
                    re.sub(r'<[^>]+>', '', match.group(1))
                ).strip()
                marker = f'({symbol})'
                if marker in title:
                    name = title.split(marker, maxsplit=1)[0].strip()
                    if contains_cjk(name):
                        return name
        except Exception:
            pass

        return ''

    def _fetch_localized_names_fallback(
        self,
        symbols: list[str],
        progress: ProgressCallback | None = None,
    ) -> dict[str, str]:
        """以有限執行緒逐檔補強快速批次 API 沒取得的名稱。"""
        unique_symbols = sorted(set(symbols))
        if not unique_symbols:
            return {}

        result: dict[str, str] = {}
        total = len(unique_symbols)
        _emit(progress, f'繁中名稱完整補強：共 {total} 檔', 0, total)

        with ThreadPoolExecutor(
            max_workers=LOCALIZED_NAME_WORKERS
        ) as executor:
            futures = {
                executor.submit(self._fetch_localized_name_one, symbol): symbol
                for symbol in unique_symbols
            }
            completed = 0
            for future in as_completed(futures):
                completed += 1
                symbol = futures[future]
                try:
                    name = future.result()
                except Exception:
                    name = ''
                if name:
                    result[symbol] = name

                if completed == total or completed % 20 == 0:
                    _emit(
                        progress,
                        f'繁中名稱完整補強：{completed}/{total}',
                        completed,
                        total,
                    )

        return result

    def _apply_preferred_names(
        self,
        instruments: list[Instrument],
        progress: ProgressCallback | None = None,
        thorough: bool = True,
    ) -> list[Instrument]:
        """名稱優先序：手動 CSV > Yahoo 台灣名稱 > Yahoo 全球名稱。"""
        if not instruments:
            return instruments

        overrides = self._load_name_overrides()
        symbols_without_override = [
            item.symbol for item in instruments
            if item.symbol not in overrides
        ]
        localized = self._fetch_localized_names_batch(
            symbols_without_override, progress
        )

        if thorough:
            unresolved = [
                item.symbol
                for item in instruments
                if item.symbol not in overrides
                and item.symbol not in localized
                and not contains_cjk(item.name)
            ]
            localized.update(
                self._fetch_localized_names_fallback(
                    unresolved, progress
                )
            )

        for item in instruments:
            item.name = overrides.get(
                item.symbol,
                localized.get(item.symbol, item.name),
            )
        return instruments

    def _screen_query(
        self,
        query: Any,
        origin_kind: str,
        allowed_categories: set[str],
        progress: ProgressCallback | None = None,
    ) -> list[Instrument]:
        """分頁執行 yfinance screen 並只保留勾選的商品種類。"""
        discovered: dict[str, Instrument] = {}
        seen_raw_symbols: set[str] = set()

        for page in range(self.settings.screener_max_pages):
            offset = page * self.settings.screener_page_size
            _emit(
                progress,
                f'Yahoo Screener：{origin_kind} offset={offset}',
            )

            try:
                response = yf.screen(
                    query,
                    offset=offset,
                    size=self.settings.screener_page_size,
                    sortField='ticker',
                    sortAsc=True,
                )
            except Exception as exc:
                raise YFinanceApiError(
                    f'Yahoo Screener 查詢失敗：{exc}'
                ) from exc

            quotes = (
                response.get('quotes', [])
                if isinstance(response, dict)
                else []
            )
            if not quotes:
                break

            raw_symbols = {
                str(quote.get('symbol') or '').strip().upper()
                for quote in quotes
                if quote.get('symbol')
            }
            new_raw_symbols = raw_symbols - seen_raw_symbols
            if page > 0 and not new_raw_symbols:
                # Yahoo 偶爾忽略 offset 並重複回傳同一頁。
                break
            seen_raw_symbols.update(raw_symbols)

            for quote in quotes:
                instrument = self._instrument_from_quote(
                    quote, origin_kind
                )
                if (
                    instrument
                    and instrument.product_category in allowed_categories
                ):
                    discovered[instrument.symbol] = instrument

            total = response.get('total') if isinstance(response, dict) else None
            if len(quotes) < self.settings.screener_page_size:
                break
            if (
                isinstance(total, int)
                and offset + len(quotes) >= total
            ):
                break

        return list(discovered.values())

    def discover_taiwan_universe(
        self,
        selected_categories: set[str],
        enrich_names: bool = True,
        progress: ProgressCallback | None = None,
    ) -> list[Instrument]:
        """依使用者勾選內容探索 Yahoo 可列舉的台灣商品。"""
        if not selected_categories:
            raise YFinanceApiError('請至少選擇一種商品類型。')
        if not all(
            hasattr(yf, name)
            for name in ('EquityQuery', 'ETFQuery', 'screen')
        ):
            raise YFinanceApiError(
                '目前安裝的 yfinance 太舊，請先升級 yfinance。'
            )

        equity_categories = {'TWSE_STOCK', 'TPEX_STOCK', 'ETN', 'WARRANT', 'OTHER'}
        queries: list[tuple[str, Any, str]] = []

        if selected_categories & equity_categories:
            if 'TWSE_STOCK' in selected_categories or selected_categories & {'ETN', 'WARRANT', 'OTHER'}:
                queries.append((
                    '上市股票類商品',
                    yf.EquityQuery('eq', ['exchange', 'TAI']),
                    'EQUITY',
                ))
            if 'TPEX_STOCK' in selected_categories or selected_categories & {'ETN', 'WARRANT', 'OTHER'}:
                queries.append((
                    '上櫃／興櫃股票類商品',
                    yf.EquityQuery('eq', ['exchange', 'TWO']),
                    'EQUITY',
                ))

        if 'TWSE_ETF' in selected_categories:
            queries.append((
                '上市 ETF／基金商品',
                yf.ETFQuery('eq', ['exchange', 'TAI']),
                'ETF',
            ))
        if 'TPEX_ETF' in selected_categories:
            queries.append((
                '上櫃 ETF／基金商品',
                yf.ETFQuery('eq', ['exchange', 'TWO']),
                'ETF',
            ))

        result: dict[str, Instrument] = {}
        errors: list[str] = []
        total_queries = len(queries)

        for index, (label, query, origin_kind) in enumerate(
            queries, start=1
        ):
            _emit(
                progress,
                f'探索商品 {index}/{total_queries}：{label}',
                index,
                total_queries,
            )
            try:
                for instrument in self._screen_query(
                    query,
                    origin_kind,
                    selected_categories,
                    progress,
                ):
                    result[instrument.symbol] = instrument
            except YFinanceApiError as exc:
                errors.append(f'{label}: {exc}')

        if not result and errors:
            raise YFinanceApiError('；'.join(errors))

        instruments = sorted(
            result.values(), key=lambda item: item.symbol
        )
        _emit(progress, f'商品篩選完成：{len(instruments)} 檔')
        return self._apply_preferred_names(
            instruments,
            progress,
            thorough=enrich_names,
        )

    def resolve_instrument(
        self,
        stock_code: str,
        market_segment: str = 'AUTO',
    ) -> Instrument:
        """解析單一台股代號並盡量取得繁中名稱。"""
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
                search = yf.Search(
                    code,
                    max_results=12,
                    news_count=0,
                    raise_errors=False,
                )
                for quote in getattr(search, 'quotes', []) or []:
                    symbol = str(quote.get('symbol') or '').upper()
                    if (
                        stock_code_from_symbol(symbol) == code
                        and symbol.endswith(('.TW', '.TWO'))
                    ):
                        instrument = self._instrument_from_quote(
                            quote, 'EQUITY'
                        )
                        if instrument:
                            if market_segment == 'EMERGING':
                                instrument.market_segment = 'EMERGING'
                            return self._apply_preferred_names(
                                [instrument], thorough=True
                            )[0]
            except Exception:
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
                    repair=self.repair_enabled,
                    raise_errors=False,
                )
                if (
                    history is None
                    or history.empty
                    or 'Close' not in history.columns
                ):
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
                exchange = str(
                    info.get('exchange')
                    or ('TAI' if symbol.endswith('.TW') else 'TWO')
                )
                quote_type = str(info.get('quoteType') or '')
                currency = str(info.get('currency') or 'TWD')
                segment = market_from_symbol(symbol)
                if market_segment == 'EMERGING':
                    segment = 'EMERGING'

                quote_stub = {
                    'symbol': symbol,
                    'quoteType': quote_type,
                    'longName': name,
                }
                instrument = Instrument(
                    symbol=symbol,
                    stock_code=code,
                    name=name,
                    exchange=exchange,
                    market_segment=segment,
                    quote_type=quote_type,
                    currency=currency,
                    product_category=self._classify_product(
                        quote_stub, segment, 'EQUITY'
                    ),
                )
                return self._apply_preferred_names(
                    [instrument], thorough=True
                )[0]
            except Exception:
                continue

        raise YFinanceApiError(
            f'Yahoo Finance 查無 {code}。請確認代號或指定市場後再試。'
        )

    @staticmethod
    def _extract_symbol_frame(
        data: pd.DataFrame,
        symbol: str,
    ) -> pd.DataFrame:
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
        """
        以批次下載方式取得最近行情。

        批次中失敗或沒有有效收盤價的商品，會再逐檔嘗試三次；LOG 會顯示
        失敗商品及每一次重試，避免整批失敗後無法辨識問題代號。
        """
        by_symbol = {
            item.symbol: item
            for item in instruments
            if item.symbol
        }
        symbols = sorted(by_symbol)
        quotes_by_symbol: dict[str, MarketQuote] = {}
        failed_candidates: set[str] = set()
        batches = list(chunks(symbols, self.settings.quote_batch_size))

        def parse_quote(symbol: str, data: pd.DataFrame) -> MarketQuote | None:
            frame = self._extract_symbol_frame(data, symbol)
            if frame.empty or 'Close' not in frame.columns:
                return None
            valid = frame.dropna(subset=['Close'])
            if valid.empty:
                return None

            last = valid.iloc[-1]
            previous = valid.iloc[-2] if len(valid) >= 2 else last
            close = float(last.get('Close') or 0.0)
            previous_close = float(previous.get('Close') or close)
            change = close - previous_close
            change_percent = (
                change / previous_close * 100
                if previous_close
                else 0.0
            )
            volume = float(last.get('Volume') or 0.0)
            instrument = by_symbol[symbol]
            return MarketQuote(
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

        for batch_index, batch in enumerate(batches, start=1):
            _emit(
                progress,
                f'行情下載第 {batch_index}/{len(batches)} 批，'
                f'{len(batch)} 檔；累計成功 {len(quotes_by_symbol)}',
                batch_index,
                len(batches),
            )
            try:
                data = yf.download(
                    tickers=batch,
                    period=self.settings.quote_period,
                    interval=self.settings.quote_interval,
                    group_by='ticker',
                    auto_adjust=False,
                    actions=False,
                    threads=min(self.settings.download_threads, len(batch)),
                    repair=self.repair_enabled,
                    progress=False,
                    keepna=False,
                    multi_level_index=True,
                    timeout=self.settings.yfinance_timeout_seconds,
                )
            except Exception as exc:
                failed_candidates.update(batch)
                _emit(
                    progress,
                    f'第 {batch_index} 批行情失敗，將逐檔重試：{exc}',
                    batch_index,
                    len(batches),
                )
                continue

            batch_success = 0
            for symbol in batch:
                quote = parse_quote(symbol, data)
                if quote is None:
                    failed_candidates.add(symbol)
                    continue
                quotes_by_symbol[symbol] = quote
                failed_candidates.discard(symbol)
                batch_success += 1

            _emit(
                progress,
                f'第 {batch_index} 批完成：成功 {batch_success}，'
                f'待重試 {len(batch) - batch_success}',
                batch_index,
                len(batches),
            )
            if self.settings.quote_batch_delay_seconds > 0:
                time.sleep(self.settings.quote_batch_delay_seconds)

        # 批次下載失敗的商品以小型執行緒池逐檔重試。
        retry_symbols = sorted(
            symbol for symbol in failed_candidates
            if symbol not in quotes_by_symbol
        )
        final_failed: list[str] = []

        def retry_quote(symbol: str) -> tuple[str, MarketQuote | None, str]:
            last_error = '沒有有效收盤價'
            for attempt in range(1, self.settings.item_retries + 1):
                _emit(
                    progress,
                    f'行情重試：{symbol} 第 {attempt}/'
                    f'{self.settings.item_retries} 次',
                    None,
                    None,
                )
                try:
                    data = yf.download(
                        tickers=[symbol],
                        period=self.settings.quote_period,
                        interval=self.settings.quote_interval,
                        group_by='ticker',
                        auto_adjust=False,
                        actions=False,
                        threads=False,
                        repair=self.repair_enabled,
                        progress=False,
                        keepna=False,
                        multi_level_index=True,
                        timeout=self.settings.yfinance_timeout_seconds,
                    )
                    quote = parse_quote(symbol, data)
                    if quote is None:
                        raise YFinanceApiError('沒有有效收盤價')
                    return symbol, quote, ''
                except Exception as exc:
                    last_error = str(exc)
                    if attempt < self.settings.item_retries:
                        time.sleep(self.settings.retry_backoff_seconds * attempt)
            return symbol, None, last_error

        if retry_symbols:
            retry_workers = min(4, self.settings.download_threads, len(retry_symbols))
            completed = 0
            with ThreadPoolExecutor(max_workers=max(retry_workers, 1)) as executor:
                futures = {
                    executor.submit(retry_quote, symbol): symbol
                    for symbol in retry_symbols
                }
                for future in as_completed(futures):
                    completed += 1
                    symbol, quote, error = future.result()
                    if quote is not None:
                        quotes_by_symbol[symbol] = quote
                        _emit(
                            progress,
                            f'行情重試成功：{symbol}',
                            completed,
                            len(retry_symbols),
                        )
                    else:
                        final_failed.append(symbol)
                        _emit(
                            progress,
                            f'行情最終失敗：{symbol}（{error}）',
                            completed,
                            len(retry_symbols),
                        )

        quotes = [quotes_by_symbol[symbol] for symbol in sorted(quotes_by_symbol)]
        _emit(
            progress,
            f'行情下載結束：成功 {len(quotes)}，失敗 {len(final_failed)}'
            + (f'；失敗代號：{", ".join(final_failed[:20])}' if final_failed else ''),
            len(batches),
            len(batches),
        )
        return quotes, final_failed

    def _action_history_kwargs(self) -> dict[str, object]:
        """建立 yfinance history/download 的期間參數。

        yfinance 原生 period 不支援 3y，因此 3y 使用明確 start/end；
        其他官方支援期間沿用 period，可降低日期邊界差異。
        """
        period = self.settings.action_period
        if period == '3y':
            today = date.today()
            try:
                start = today.replace(year=today.year - 3)
            except ValueError:  # 2/29
                start = today.replace(year=today.year - 3, day=28)
            return {
                'start': start.isoformat(),
                'end': (today + timedelta(days=1)).isoformat(),
            }
        return {'period': period}

    @staticmethod
    def _parse_actions_frame(
        instrument: Instrument,
        frame: pd.DataFrame,
    ) -> list[CorporateAction]:
        """將單一商品的行情 DataFrame 轉成股利／股票分割事件。"""
        if frame is None or frame.empty:
            return []

        actions: list[CorporateAction] = []
        for timestamp, row in frame.iterrows():
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
                        source='yfinance',
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
                        source='yfinance',
                    )
                )
        return actions

    def download_actions(
        self,
        instruments: list[Instrument],
        progress: ProgressCallback | None = None,
    ) -> tuple[dict[str, list[CorporateAction]], list[str]]:
        """批次下載持股的股利與股票分割，失敗項目再逐檔重試。

        相較逐檔 Ticker.history，批次 download(actions=True) 可共用連線與
        執行緒，持股較多時會明顯縮短等待時間。沒有股利／分割但行情存在
        的商品視為成功，回傳空清單。
        """
        by_symbol = {item.symbol: item for item in instruments if item.symbol}
        symbols = sorted(by_symbol)
        results: dict[str, list[CorporateAction]] = {}
        failed_candidates: set[str] = set()
        batches = list(chunks(symbols, self.settings.action_batch_size))
        history_kwargs = self._action_history_kwargs()

        for batch_index, batch in enumerate(batches, start=1):
            _emit(
                progress,
                f'[API／歷史] 批次 {batch_index}/{len(batches)}：{len(batch)} 檔',
                batch_index,
                len(batches) or 1,
            )
            try:
                data = yf.download(
                    tickers=batch,
                    interval='1d',
                    group_by='ticker',
                    auto_adjust=False,
                    actions=True,
                    threads=min(
                        self.settings.action_download_threads,
                        len(batch),
                    ),
                    repair=self.repair_enabled,
                    progress=False,
                    keepna=False,
                    multi_level_index=True,
                    timeout=self.settings.yfinance_timeout_seconds,
                    **history_kwargs,
                )
            except Exception as exc:
                failed_candidates.update(batch)
                _emit(
                    progress,
                    f'[API／歷史] 第 {batch_index} 批失敗，改逐檔重試：{exc}',
                    batch_index,
                    len(batches) or 1,
                )
                continue

            for symbol in batch:
                frame = self._extract_symbol_frame(data, symbol)
                # Close 存在即可判定 Yahoo 有回應；股利欄全為 0 仍是成功。
                if frame.empty or 'Close' not in frame.columns:
                    failed_candidates.add(symbol)
                    continue
                results[symbol] = self._parse_actions_frame(
                    by_symbol[symbol], frame
                )
                failed_candidates.discard(symbol)

            if self.settings.action_item_delay_seconds > 0:
                time.sleep(self.settings.action_item_delay_seconds)

        final_failed: list[str] = []
        retry_symbols = sorted(
            symbol for symbol in failed_candidates if symbol not in results
        )
        for item_index, symbol in enumerate(retry_symbols, start=1):
            instrument = by_symbol[symbol]
            try:
                results[symbol] = self.fetch_actions(instrument)
                _emit(
                    progress,
                    f'[API／歷史] 逐檔重試成功：{symbol}',
                    item_index,
                    len(retry_symbols) or 1,
                )
            except Exception as exc:
                final_failed.append(symbol)
                _emit(
                    progress,
                    f'[API／歷史] 最終失敗：{symbol}；{exc}',
                    item_index,
                    len(retry_symbols) or 1,
                )
        return results, final_failed

    def fetch_actions(
        self,
        instrument: Instrument,
    ) -> list[CorporateAction]:
        """取得設定範圍內的歷史股利與股票分割。"""
        try:
            history = yf.Ticker(instrument.symbol).history(
                interval='1d',
                auto_adjust=False,
                actions=True,
                repair=self.repair_enabled,
                raise_errors=False,
                **self._action_history_kwargs(),
            )
        except Exception as exc:
            raise YFinanceApiError(
                f'{instrument.symbol} 股利／分割資料下載失敗：{exc}'
            ) from exc

        if history is None or history.empty:
            return []
        return self._parse_actions_frame(instrument, history)

