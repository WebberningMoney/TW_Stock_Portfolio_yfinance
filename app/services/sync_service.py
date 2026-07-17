"""協調 yfinance、Yahoo 台灣股利頁、SQLite 與 GUI 的同步流程。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time

from app.api.yahoo_tw_dividend_scraper import YahooTwDividendScraper
from app.api.yfinance_client import YFinanceClient
from app.db.database import Database
from app.models import CorporateAction, Instrument
from app.settings import RuntimeSettings
from app.utils import normalize_stock_code, stock_code_from_symbol

ProgressCallback = Callable[[str, int | None, int | None], None]

VALID_ACTION_SOURCE_MODES = {'BOTH', 'YFINANCE', 'SCRAPER'}
VALID_SINGLE_TEST_MODES = {'ALL', 'QUOTE', 'YFINANCE', 'SCRAPER'}


@dataclass(slots=True)
class ActionSyncResult:
    """持股股利同步結果。"""

    source_mode: str
    history_action_count: int
    announced_dividend_count: int
    failed_count: int


@dataclass(slots=True)
class SingleTestResult:
    """單筆連線測試結果。"""

    symbol: str
    name: str
    test_mode: str
    quote_summary: str = ''
    history_summary: str = ''
    scraper_summary: str = ''

    def to_text(self) -> str:
        lines = [f'{self.symbol} {self.name}', f'測試模式：{self.test_mode}']
        for value in (
            self.quote_summary,
            self.history_summary,
            self.scraper_summary,
        ):
            if value:
                lines.append(value)
        return '\n'.join(lines)


class SyncService:
    def __init__(
        self,
        database: Database,
        settings: RuntimeSettings | None = None,
        client: YFinanceClient | None = None,
        dividend_scraper: YahooTwDividendScraper | None = None,
    ) -> None:
        self.database = database
        self.settings = (settings or RuntimeSettings()).normalized()
        self.client = client or YFinanceClient(self.settings)
        self.dividend_scraper = dividend_scraper or YahooTwDividendScraper(
            self.settings
        )

    def update_settings(self, settings: RuntimeSettings) -> None:
        """立即套用 GUI 儲存的新設定。"""
        self.settings = settings.normalized()
        self.client.update_settings(self.settings)
        self.dividend_scraper.update_settings(self.settings)

    def discover_universe(
        self,
        selected_categories: set[str],
        enrich_names: bool,
        rebuild: bool,
        progress: ProgressCallback | None = None,
    ) -> int:
        instruments = self.client.discover_taiwan_universe(
            selected_categories=selected_categories,
            enrich_names=enrich_names,
            progress=progress,
        )

        if rebuild:
            if progress:
                progress('清除舊商品清冊與行情快取後重建……', None, None)
            self.database.replace_universe(
                instruments,
                preserve_holding_instruments=True,
            )
        else:
            self.database.upsert_instruments(instruments)

        self.database.add_sync_log(
            'UNIVERSE',
            'SUCCESS',
            f'categories={sorted(selected_categories)}, '
            f'count={len(instruments)}, rebuild={rebuild}',
        )
        return len(instruments)

    def resolve_and_save_instrument(
        self,
        stock_code: str,
        market_segment: str,
    ) -> Instrument:
        instrument = self.client.resolve_instrument(
            stock_code, market_segment
        )
        self.database.upsert_instruments([instrument])
        return instrument

    def sync_all_quotes(
        self,
        progress: ProgressCallback | None = None,
    ) -> tuple[int, int]:
        instruments = self.database.list_instruments()
        if not instruments:
            raise RuntimeError(
                '商品清冊是空的，請先建立 Yahoo 台灣商品清冊或新增持股。'
            )
        quotes, failed = self.client.download_quotes(
            instruments, progress
        )
        self.database.upsert_quotes(quotes)
        self.database.add_sync_log(
            'QUOTES',
            'SUCCESS' if quotes else 'FAILED',
            f'success={len(quotes)}, failed={len(failed)}, '
            f'failed_symbols={failed[:50]}',
        )
        return len(quotes), len(failed)

    def sync_holding_quotes(
        self,
        progress: ProgressCallback | None = None,
    ) -> tuple[int, int]:
        holdings = self.database.list_holdings()
        instruments: list[Instrument] = []
        for holding in holdings:
            instrument = self.database.get_instrument(
                holding.yahoo_symbol
            )
            if instrument:
                instruments.append(instrument)
        if not instruments:
            return 0, 0

        quotes, failed = self.client.download_quotes(
            instruments, progress
        )
        self.database.upsert_quotes(quotes)
        return len(quotes), len(failed)

    def _resolve_holding_instrument_with_retry(
        self,
        stock_code: str,
        market_segment: str,
        symbol_hint: str,
        progress: ProgressCallback | None,
    ) -> Instrument:
        """清冊缺少持股商品時，依設定次數重試解析。"""
        last_error: Exception | None = None
        retries = self.settings.item_retries
        for attempt in range(1, retries + 1):
            try:
                return self.resolve_and_save_instrument(
                    stock_code,
                    market_segment,
                )
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(
                        f'解析商品 {symbol_hint} 第 {attempt}/{retries} 次失敗：{exc}',
                        attempt,
                        retries,
                    )
                if attempt < retries:
                    time.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError(
            f'{symbol_hint} 商品解析重試 {retries} 次仍失敗：{last_error}'
        )

    def _fetch_yfinance_actions_with_retry(
        self,
        instrument: Instrument,
        progress: ProgressCallback | None,
    ) -> list[CorporateAction]:
        """yfinance 歷史股利／分割資料依設定次數重試。"""
        last_error: Exception | None = None
        retries = self.settings.item_retries
        for attempt in range(1, retries + 1):
            try:
                if progress:
                    progress(
                        f'[API／歷史] {instrument.symbol}：'
                        f'第 {attempt}/{retries} 次嘗試',
                        attempt,
                        retries,
                    )
                return self.client.fetch_actions(instrument)
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(
                        f'[API／歷史] {instrument.symbol} 第 {attempt}/'
                        f'{retries} 次失敗：{exc}',
                        attempt,
                        retries,
                    )
                if attempt < retries:
                    time.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError(
            f'{instrument.symbol} 歷史股利／分割重試 '
            f'{retries} 次仍失敗：{last_error}'
        )

    def sync_holding_actions(
        self,
        source_mode: str = 'BOTH',
        progress: ProgressCallback | None = None,
    ) -> ActionSyncResult:
        """依選擇來源更新已登錄持股的股利資料。"""
        mode = str(source_mode or 'BOTH').upper()
        if mode not in VALID_ACTION_SOURCE_MODES:
            raise ValueError(f'不支援的股利來源模式：{source_mode}')

        holdings = self.database.list_holdings()
        history_action_count = 0
        announced_dividend_count = 0
        failed_items: list[str] = []
        total = len(holdings)

        if progress:
            progress(
                f'股利資料來源：{self._source_mode_label(mode)}；'
                f'共 {total} 檔持股',
                0,
                total or 1,
            )

        for index, holding in enumerate(holdings, start=1):
            if progress:
                progress(
                    f'處理持股 {index}/{total}：'
                    f'{holding.yahoo_symbol} {holding.stock_name}',
                    index,
                    total,
                )

            instrument = self.database.get_instrument(
                holding.yahoo_symbol
            )
            if not instrument:
                try:
                    instrument = self._resolve_holding_instrument_with_retry(
                        holding.stock_code,
                        holding.market_segment,
                        holding.yahoo_symbol,
                        progress,
                    )
                except Exception as exc:
                    failed_items.append(
                        f'{holding.yahoo_symbol} 商品解析：{exc}'
                    )
                    if progress:
                        progress(
                            f'最終失敗：{holding.yahoo_symbol} 商品解析；{exc}',
                            index,
                            total,
                        )
                    continue

            if mode in {'BOTH', 'YFINANCE'}:
                try:
                    actions = self._fetch_yfinance_actions_with_retry(
                        instrument,
                        progress,
                    )
                    self.database.replace_actions_for_symbol(
                        instrument.symbol,
                        actions,
                    )
                    history_action_count += len(actions)
                    if progress:
                        progress(
                            f'[API／歷史] 完成：{instrument.symbol} '
                            f'{len(actions)} 筆股利／分割',
                            index,
                            total,
                        )
                except Exception as exc:
                    failed_items.append(
                        f'{instrument.symbol} API／歷史股利／分割：{exc}'
                    )
                    if progress:
                        progress(
                            f'[API／歷史] 最終失敗：{instrument.symbol}；{exc}',
                            index,
                            total,
                        )
            elif progress:
                progress(
                    f'[API／歷史] 略過：本次選擇僅使用爬蟲 '
                    f'({instrument.symbol})',
                    index,
                    total,
                )

            if mode in {'BOTH', 'SCRAPER'}:
                try:
                    announced = self.dividend_scraper.fetch_dividends(
                        instrument,
                        progress,
                    )
                    self.database.replace_scraped_dividends_for_symbol(
                        instrument.symbol,
                        announced,
                    )
                    announced_dividend_count += len(announced)
                    if progress:
                        future_count = sum(
                            item.announcement_status in {
                                'ANNOUNCED', 'EX_DATE_PASSED'
                            }
                            for item in announced
                        )
                        progress(
                            f'[爬蟲／Yahoo 台灣已公告] 完成：{instrument.symbol} '
                            f'{len(announced)} 筆，其中尚未發放 {future_count} 筆',
                            index,
                            total,
                        )
                except Exception as exc:
                    failed_items.append(
                        f'{instrument.symbol} 爬蟲／Yahoo 台灣已公告：{exc}'
                    )
                    if progress:
                        progress(
                            f'[爬蟲／Yahoo 台灣已公告] 最終失敗：'
                            f'{instrument.symbol}；{exc}',
                            index,
                            total,
                        )
            elif progress:
                progress(
                    f'[爬蟲／Yahoo 台灣已公告] 略過：本次選擇僅使用 '
                    f'yfinance API ({instrument.symbol})',
                    index,
                    total,
                )

            # 無論本次使用哪個來源，都整理資料庫中既有的跨來源重複事件。
            merge_messages = self.database.consolidate_duplicate_actions_for_symbol(
                instrument.symbol
            )
            for message in merge_messages:
                if progress:
                    progress(
                        f'[資料整合] {message}',
                        index,
                        total,
                    )

            if self.settings.action_item_delay_seconds > 0:
                time.sleep(self.settings.action_item_delay_seconds)

        status = 'SUCCESS' if not failed_items else 'PARTIAL'
        self.database.add_sync_log(
            'DIVIDEND_SPLIT',
            status,
            f'source_mode={mode}, history_actions={history_action_count}, '
            f'announced_dividends={announced_dividend_count}, '
            f'failed_items={failed_items[:50]}',
        )
        if progress and failed_items:
            progress(
                '重試後仍失敗的項目：' + '｜'.join(failed_items[:20]),
                total,
                total or 1,
            )
        return ActionSyncResult(
            source_mode=mode,
            history_action_count=history_action_count,
            announced_dividend_count=announced_dividend_count,
            failed_count=len(failed_items),
        )

    def test_single_item(
        self,
        query: str,
        test_mode: str = 'ALL',
        progress: ProgressCallback | None = None,
    ) -> SingleTestResult:
        """不寫入資料庫的單檔診斷測試。"""
        mode = str(test_mode or 'ALL').upper()
        if mode not in VALID_SINGLE_TEST_MODES:
            raise ValueError(f'不支援的單筆測試模式：{test_mode}')

        instrument = self._resolve_test_instrument(query)
        result = SingleTestResult(
            symbol=instrument.symbol,
            name=instrument.name,
            test_mode=self._test_mode_label(mode),
        )

        if mode in {'ALL', 'QUOTE'}:
            if progress:
                progress(f'[單筆測試／行情] {instrument.symbol}', 1, 3)
            quotes, failed = self.client.download_quotes([instrument], progress)
            if failed or not quotes:
                result.quote_summary = '行情：失敗／沒有有效收盤價'
            else:
                quote = quotes[0]
                result.quote_summary = (
                    f'行情：成功，收盤 {quote.close:g}，'
                    f'行情日 {quote.trade_date}'
                )

        if mode in {'ALL', 'YFINANCE'}:
            if progress:
                progress(f'[單筆測試／API 歷史] {instrument.symbol}', 2, 3)
            actions = self._fetch_yfinance_actions_with_retry(
                instrument, progress
            )
            dividends = [a for a in actions if a.action_type == 'DIVIDEND']
            splits = [a for a in actions if a.action_type == 'SPLIT']
            last_date = max((a.action_date for a in actions), default='-')
            result.history_summary = (
                f'yfinance 歷史：股利 {len(dividends)} 筆、'
                f'分割 {len(splits)} 筆，最近事件 {last_date}'
            )

        if mode in {'ALL', 'SCRAPER'}:
            if progress:
                progress(f'[單筆測試／公告爬蟲] {instrument.symbol}', 3, 3)
            announced = self.dividend_scraper.fetch_dividends(
                instrument, progress
            )
            latest = max(
                announced,
                key=lambda item: item.action_date,
                default=None,
            )
            result.scraper_summary = (
                f'Yahoo 台灣公告：{len(announced)} 筆'
                + (
                    f'，最新 {latest.period or "-"}／'
                    f'{latest.action_date}／每股 {latest.value:g}'
                    if latest else ''
                )
            )

        return result

    def _resolve_test_instrument(self, query: str) -> Instrument:
        value = str(query or '').strip().upper()
        if not value:
            raise ValueError('請輸入股票代號或 Yahoo Symbol。')

        if value.endswith(('.TW', '.TWO')):
            existing = self.database.get_instrument(value)
            if existing:
                return existing
            code = stock_code_from_symbol(value)
            market = 'TWSE' if value.endswith('.TW') else 'TPEX'
            return self.client.resolve_instrument(code, market)

        code = normalize_stock_code(value)
        matches = self.database.find_instruments_by_code(code)
        if matches:
            # 常見情況優先 .TW；若只有 .TWO 則使用該筆。
            return sorted(
                matches,
                key=lambda item: (not item.symbol.endswith('.TW'), item.symbol),
            )[0]
        return self.client.resolve_instrument(code, 'AUTO')

    @staticmethod
    def _source_mode_label(mode: str) -> str:
        return {
            'BOTH': '兩者（yfinance 歷史＋Yahoo 台灣公告）',
            'YFINANCE': '僅 yfinance API 歷史資料',
            'SCRAPER': '僅 Yahoo 台灣公告爬蟲',
        }.get(mode, mode)

    @staticmethod
    def _test_mode_label(mode: str) -> str:
        return {
            'ALL': '全部測試',
            'QUOTE': '行情',
            'YFINANCE': 'yfinance 歷史股利／分割',
            'SCRAPER': 'Yahoo 台灣公告股利爬蟲',
        }.get(mode, mode)
