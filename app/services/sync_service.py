"""協調 yfinance、Yahoo 台灣股利頁、SQLite 與 GUI 的同步流程。"""

from collections.abc import Callable
import time

from app.api.yahoo_tw_dividend_scraper import YahooTwDividendScraper
from app.api.yfinance_client import YFinanceClient
from app.config import HTTP_ITEM_RETRIES, RETRY_BACKOFF_SECONDS
from app.db.database import Database
from app.models import Instrument

ProgressCallback = Callable[[str, int | None, int | None], None]


class SyncService:
    def __init__(
        self,
        database: Database,
        client: YFinanceClient | None = None,
        dividend_scraper: YahooTwDividendScraper | None = None,
    ) -> None:
        self.database = database
        self.client = client or YFinanceClient()
        self.dividend_scraper = dividend_scraper or YahooTwDividendScraper()

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
        """清冊缺少持股商品時，最多重試三次解析。"""
        last_error: Exception | None = None
        for attempt in range(1, HTTP_ITEM_RETRIES + 1):
            try:
                return self.resolve_and_save_instrument(
                    stock_code,
                    market_segment,
                )
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(
                        f'解析商品 {symbol_hint} 第 {attempt}/'
                        f'{HTTP_ITEM_RETRIES} 次失敗：{exc}',
                        attempt,
                        HTTP_ITEM_RETRIES,
                    )
                if attempt < HTTP_ITEM_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError(
            f'{symbol_hint} 商品解析重試 {HTTP_ITEM_RETRIES} 次仍失敗：'
            f'{last_error}'
        )

    def _fetch_yfinance_actions_with_retry(
        self,
        instrument: Instrument,
        progress: ProgressCallback | None,
    ):
        """yfinance 歷史股利／分割資料最多重試三次。"""
        last_error: Exception | None = None
        for attempt in range(1, HTTP_ITEM_RETRIES + 1):
            try:
                if progress:
                    progress(
                        f'[API／歷史] {instrument.symbol}：'
                        f'第 {attempt}/{HTTP_ITEM_RETRIES} 次嘗試',
                        attempt,
                        HTTP_ITEM_RETRIES,
                    )
                return self.client.fetch_actions(instrument)
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(
                        f'[API／歷史] {instrument.symbol} 第 {attempt}/'
                        f'{HTTP_ITEM_RETRIES} 次失敗：{exc}',
                        attempt,
                        HTTP_ITEM_RETRIES,
                    )
                if attempt < HTTP_ITEM_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError(
            f'{instrument.symbol} 歷史股利／分割重試 '
            f'{HTTP_ITEM_RETRIES} 次仍失敗：{last_error}'
        )

    def sync_holding_actions(
        self,
        progress: ProgressCallback | None = None,
    ) -> tuple[int, int, int]:
        """
        更新持股的歷史股利／分割，並以 Yahoo 台灣股利政策頁補入已公告資料。

        回傳：
        - 儲存的 yfinance 歷史股利／分割筆數
        - Yahoo 台灣股利政策頁解析筆數
        - 重試後仍失敗的資料項目數
        """
        holdings = self.database.list_holdings()
        history_action_count = 0
        announced_dividend_count = 0
        failed_items: list[str] = []
        total = len(holdings)

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

            # 來源一：yfinance 歷史股利與股票分割。
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

            # 來源二：Yahoo 台灣股利政策頁，補足尚未除息／尚未發放的公告。
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

            # 兩個來源完成後，合併日期、商品與數值完全相同的事件。
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

        status = 'SUCCESS' if not failed_items else 'PARTIAL'
        self.database.add_sync_log(
            'DIVIDEND_SPLIT',
            status,
            f'history_actions={history_action_count}, '
            f'announced_dividends={announced_dividend_count}, '
            f'failed_items={failed_items[:50]}',
        )
        if progress and failed_items:
            progress(
                '重試後仍失敗的項目：' + '｜'.join(failed_items[:20]),
                total,
                total,
            )
        return (
            history_action_count,
            announced_dividend_count,
            len(failed_items),
        )
